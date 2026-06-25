import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import hashlib
import hmac

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Budget Tracker",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CUSTOM CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 12px;
        padding: 1rem 1.25rem;
        color: white;
        margin-bottom: 0.5rem;
    }
    .metric-card h3 { margin: 0; font-size: 0.85rem; opacity: 0.85; font-weight: 400; }
    .metric-card h2 { margin: 0; font-size: 1.6rem; font-weight: 700; }
    .metric-card small { opacity: 0.75; font-size: 0.75rem; }
    .stProgress > div > div > div > div { border-radius: 10px; }
    div[data-testid="stSidebarNav"] { display: none; }
</style>
""", unsafe_allow_html=True)

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
TRANSACTION_HEADERS = [
    "Transaction Date", "Clearing Date", "Description", "Merchant",
    "Category", "Type", "Amount (USD)", "Purchased By", "Month", "Year", "Upload Date", "Source",
]

BUDGET_HEADERS = ["Category", "Monthly Budget"]

NOTES_HEADERS = ["Period", "Note", "Updated"]

RULES_HEADERS = ["Merchant", "Category", "Created"]
COMMENTS_HEADERS = ["Key", "Comment", "Updated"]
INCOME_HEADERS   = ["Period", "Source", "Amount", "Added"]

DEFAULT_BUDGETS = {
    "Grocery": 600.0,
    "Restaurants": 300.0,
    "Gas": 150.0,
    "Medical": 100.0,
    "Shopping": 200.0,
    "Entertainment": 100.0,
    "Travel": 200.0,
    "Utilities": 200.0,
    "Subscriptions": 100.0,
    "Other": 150.0,
}

CATEGORY_COLORS = {
    "Grocery": "#4CAF50",
    "Restaurants": "#FF9800",
    "Gas": "#2196F3",
    "Medical": "#F44336",
    "Shopping": "#9C27B0",
    "Entertainment": "#FF5722",
    "Travel": "#00BCD4",
    "Utilities": "#607D8B",
    "Subscriptions": "#E91E63",
    "Other": "#9E9E9E",
    "Payment": "#795548",
}

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ─── AUTHENTICATION ───────────────────────────────────────────────────────────
def check_password() -> bool:
    """Simple SHA-256 password gate. Returns True when authenticated."""
    if st.session_state.get("authenticated"):
        return True

    def _verify():
        entered = st.session_state.get("pw_input", "")
        entered_hash = hashlib.sha256(entered.encode()).hexdigest()
        expected = st.secrets["app"]["password_hash"]
        if hmac.compare_digest(entered_hash, expected):
            st.session_state["authenticated"] = True
        else:
            st.session_state["auth_failed"] = True

    st.markdown("""
    <div style="max-width:380px;margin:8rem auto 0;text-align:center;">
        <div style="font-size:3rem;">💰</div>
        <h2 style="margin-bottom:0.25rem;">Budget Tracker</h2>
        <p style="color:#888;margin-bottom:1.5rem;">Enter your password to continue</p>
    </div>
    """, unsafe_allow_html=True)

    col = st.columns([1, 2, 1])[1]
    with col:
        st.text_input("Password", type="password", key="pw_input",
                      on_change=_verify, label_visibility="collapsed",
                      placeholder="Password")
        if st.session_state.get("auth_failed"):
            st.error("Incorrect password — try again.")
            st.session_state["auth_failed"] = False

    return False


# ─── GOOGLE SHEETS CLIENT ─────────────────────────────────────────────────────
@st.cache_resource
def get_gc():
    creds_dict = dict(st.secrets["gcp"]["service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def get_spreadsheet():
    gc = get_gc()
    return gc.open_by_key(st.secrets["gcp"]["spreadsheet_id"])


def get_or_create_worksheet(sh, name: str, rows: int = 2000, cols: int = 15):
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=rows, cols=cols)
        return ws


# ─── DATA LOADING ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=90, show_spinner=False)
def load_transactions(_sh):
    ws = get_or_create_worksheet(_sh, "transactions")
    data = ws.get_all_records()
    if not data:
        return pd.DataFrame(columns=TRANSACTION_HEADERS)
    df = pd.DataFrame(data)
    df["Amount (USD)"] = pd.to_numeric(df["Amount (USD)"], errors="coerce").fillna(0)
    df["Transaction Date"] = pd.to_datetime(df["Transaction Date"], errors="coerce")
    if "Source" not in df.columns:
        df["Source"] = "Import"
    df["Source"] = df["Source"].replace("", "Import").fillna("Import")
    return df


@st.cache_data(ttl=90, show_spinner=False)
def load_budgets(_sh):
    ws = get_or_create_worksheet(_sh, "budgets")
    data = ws.get_all_records()
    if not data:
        return dict(DEFAULT_BUDGETS)
    df = pd.DataFrame(data)
    return dict(zip(df["Category"], pd.to_numeric(df["Monthly Budget"], errors="coerce").fillna(0)))


@st.cache_data(ttl=90, show_spinner=False)
def load_notes(_sh):
    ws = get_or_create_worksheet(_sh, "notes")
    data = ws.get_all_records()
    if not data:
        return {}
    df = pd.DataFrame(data)
    return dict(zip(df["Period"], df["Note"]))


@st.cache_data(ttl=90, show_spinner=False)
def load_rules(_sh):
    """Returns dict of {merchant: category} from the rules sheet."""
    ws = get_or_create_worksheet(_sh, "rules")
    data = ws.get_all_records()
    if not data:
        return {}
    df = pd.DataFrame(data)
    return dict(zip(df["Merchant"], df["Category"]))


def make_tx_key(date, merchant, amount) -> str:
    """Stable fingerprint for a transaction used as the comments key."""
    return f"{str(date)[:10]}|{merchant}|{amount}"


@st.cache_data(ttl=90, show_spinner=False)
def load_comments(_sh):
    """Returns dict of {tx_key: comment} from the comments sheet."""
    ws = get_or_create_worksheet(_sh, "comments")
    data = ws.get_all_records()
    if not data:
        return {}
    df = pd.DataFrame(data)
    return dict(zip(df["Key"], df["Comment"]))


def save_comments(sh, comments: dict):
    """Overwrite entire comments sheet with the provided dict."""
    ws = get_or_create_worksheet(sh, "comments")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = [[k, v, now] for k, v in comments.items() if v and str(v).strip()]
    ws.clear()
    if rows:
        ws.update([COMMENTS_HEADERS] + rows)
    else:
        ws.update([COMMENTS_HEADERS])
    load_comments.clear()


@st.cache_data(ttl=90, show_spinner=False)
def load_income(_sh):
    """Returns DataFrame of income entries: Period, Source, Amount."""
    ws = get_or_create_worksheet(_sh, "income")
    # Use get_all_values so we can validate headers before trusting the data
    rows = ws.get_all_values()
    rows = [r for r in rows if any(c.strip() for c in r)]  # drop empty rows
    if not rows or rows[0] != INCOME_HEADERS:
        return pd.DataFrame(columns=INCOME_HEADERS)
    data = rows[1:]
    if not data:
        return pd.DataFrame(columns=INCOME_HEADERS)
    df = pd.DataFrame(data, columns=INCOME_HEADERS)
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    return df


def save_income_entry(sh, period: str, source: str, amount: float):
    """Append a single income entry."""
    ws = get_or_create_worksheet(sh, "income")
    existing = ws.get_all_values()
    # Filter empty rows — a brand-new gspread worksheet can return
    # rows of empty strings which are truthy but have no real content.
    existing = [r for r in existing if any(c.strip() for c in r)]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not existing or existing[0] != INCOME_HEADERS:
        # No real data yet, or headers are wrong — write fresh
        data_rows = existing[1:] if existing else []
        ws.clear()
        ws.update([INCOME_HEADERS] + data_rows + [[period, source, amount, now]])
    else:
        ws.append_rows([[period, source, amount, now]])
    load_income.clear()


def delete_income_entry(sh, period: str, source: str, amount: float):
    """Delete the first matching income row."""
    ws = get_or_create_worksheet(sh, "income")
    data = ws.get_all_records()
    if not data:
        return
    df = pd.DataFrame(data)
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
    mask = (df["Period"] == period) & (df["Source"] == source) & (df["Amount"] == amount)
    keep = df[~mask | mask.cumsum().gt(1)]  # drop only the FIRST match
    ws.clear()
    if not keep.empty:
        ws.update([INCOME_HEADERS] + keep[INCOME_HEADERS].values.tolist())
    else:
        ws.update([INCOME_HEADERS])
    load_income.clear()


def income_for_period(income_df: pd.DataFrame, period: str) -> float:
    """Sum all income entries for a given YYYY-MM period string."""
    if income_df.empty or "Period" not in income_df.columns:
        return 0.0
    return float(income_df[income_df["Period"] == period]["Amount"].sum())


def income_for_year(income_df: pd.DataFrame, year: str) -> float:
    """Sum all income entries for a given year string."""
    if income_df.empty or "Period" not in income_df.columns:
        return 0.0
    return float(income_df[income_df["Period"].str.startswith(year)]["Amount"].sum())

# ─── DATA SAVING ──────────────────────────────────────────────────────────────
def save_transactions(sh, df_new: pd.DataFrame):
    ws = get_or_create_worksheet(sh, "transactions")
    existing = ws.get_all_values()
    has_data = bool(existing)

    # If sheet header is outdated (missing Source or other new columns),
    # rewrite the full sheet so the header and all rows stay in sync.
    if has_data and existing[0] != TRANSACTION_HEADERS:
        old_headers = existing[0]
        data_rows = existing[1:]
        # Pad / remap each row to match the current TRANSACTION_HEADERS
        migrated = []
        for row in data_rows:
            row_dict = dict(zip(old_headers, row))
            if "Source" not in row_dict or not row_dict["Source"]:
                row_dict["Source"] = "Import"
            migrated.append([row_dict.get(h, "") for h in TRANSACTION_HEADERS])
        # Append the new rows too
        new_rows = [list(map(str, r)) for r in df_new.itertuples(index=False, name=None)]
        ws.clear()
        ws.update([TRANSACTION_HEADERS] + migrated + new_rows)
    else:
        new_rows = [list(map(str, r)) for r in df_new.itertuples(index=False, name=None)]
        if not has_data:
            ws.update([TRANSACTION_HEADERS] + new_rows)
        else:
            ws.append_rows(new_rows)
    load_transactions.clear()


def save_budgets(sh, budgets: dict):
    ws = get_or_create_worksheet(sh, "budgets")
    rows = [BUDGET_HEADERS] + [[k, v] for k, v in budgets.items()]
    ws.clear()
    ws.update(rows)
    load_budgets.clear()


def save_note(sh, period: str, note: str):
    ws = get_or_create_worksheet(sh, "notes")
    data = ws.get_all_records()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not data:
        ws.update([NOTES_HEADERS, [period, note, now]])
    else:
        df = pd.DataFrame(data)
        if period in df["Period"].values:
            idx = df.index[df["Period"] == period][0] + 2  # 1-indexed + header
            ws.update(f"A{idx}:C{idx}", [[period, note, now]])
        else:
            ws.append_rows([[period, note, now]])
    load_notes.clear()


def save_rule(sh, merchant: str, category: str):
    """Upsert a merchant → category rule into the rules sheet."""
    ws = get_or_create_worksheet(sh, "rules")
    data = ws.get_all_records()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if not data:
        ws.update([RULES_HEADERS, [merchant, category, now]])
    else:
        df = pd.DataFrame(data)
        if merchant in df["Merchant"].values:
            idx = df.index[df["Merchant"] == merchant][0] + 2
            ws.update(f"A{idx}:C{idx}", [[merchant, category, now]])
        else:
            ws.append_rows([[merchant, category, now]])
    load_rules.clear()


def delete_rule(sh, merchant: str):
    """Remove a rule by merchant name."""
    ws = get_or_create_worksheet(sh, "rules")
    data = ws.get_all_records()
    if not data:
        return
    df = pd.DataFrame(data)
    keep = df[df["Merchant"] != merchant]
    ws.clear()
    if not keep.empty:
        ws.update([RULES_HEADERS] + keep.values.tolist())
    else:
        ws.update([RULES_HEADERS])
    load_rules.clear()


def apply_rules(df: pd.DataFrame, rules: dict) -> tuple[pd.DataFrame, int]:
    """Apply merchant→category rules to df. Returns (updated_df, n_changed)."""
    if not rules or df.empty:
        return df, 0
    df = df.copy()
    mask = df["Merchant"].isin(rules) & (df["Type"] == "Purchase")
    original = df.loc[mask, "Category"].copy()
    df.loc[mask, "Category"] = df.loc[mask, "Merchant"].map(rules)
    n_changed = int((df.loc[mask, "Category"] != original).sum())
    return df, n_changed

# ─── HELPERS ──────────────────────────────────────────────────────────────────
def get_purchases(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["Type"] == "Purchase"].copy()


def parse_apple_card_csv(uploaded_file) -> pd.DataFrame:
    df = pd.read_csv(uploaded_file)
    df.columns = df.columns.str.strip()
    df["Transaction Date"] = pd.to_datetime(df["Transaction Date"], errors="coerce")
    df["Month"] = df["Transaction Date"].dt.strftime("%B")
    df["Year"] = df["Transaction Date"].dt.year.astype(str)
    df["Upload Date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    df["Source"] = "Import"
    for col in TRANSACTION_HEADERS:
        if col not in df.columns:
            df[col] = ""
    return df[TRANSACTION_HEADERS]


def available_periods(df: pd.DataFrame):
    return sorted(
        df.dropna(subset=["Transaction Date"])["Transaction Date"]
        .dt.to_period("M").unique(),
        reverse=True,
    )


def metric_card(label: str, value: str, sub: str = "", color: str = "#667eea"):
    st.markdown(
        f"""
        <div style="background:linear-gradient(135deg,{color}cc,{color}88);
                    border-radius:12px;padding:1rem 1.2rem;color:white;
                    border-left:4px solid {color};">
            <div style="font-size:.8rem;opacity:.85;margin-bottom:.2rem">{label}</div>
            <div style="font-size:1.55rem;font-weight:700">{value}</div>
            <div style="font-size:.75rem;opacity:.75">{sub}</div>
        </div>""",
        unsafe_allow_html=True,
    )


# ─── PAGE: DASHBOARD ──────────────────────────────────────────────────────────
def page_dashboard(sh):
    st.title("📊 Dashboard")

    df = load_transactions(sh)
    budgets = load_budgets(sh)
    notes = load_notes(sh)
    comments = load_comments(sh)
    income_df = load_income(sh)

    if df.empty or get_purchases(df).empty:
        st.info("👆 No data yet — head to **Upload** to add your first statement!")
        return

    purchases = get_purchases(df)
    periods = available_periods(purchases)

    sel = st.selectbox(
        "Month",
        [str(p) for p in periods],
        index=0,
        label_visibility="collapsed",
    )
    selected_period = pd.Period(sel)
    month_df = purchases[purchases["Transaction Date"].dt.to_period("M") == selected_period]

    total_spent  = month_df["Amount (USD)"].sum()
    total_budget = sum(budgets.get(c, 0) for c in DEFAULT_BUDGETS)
    remaining    = total_budget - total_spent
    avg_tx       = month_df["Amount (USD)"].mean() if len(month_df) else 0
    largest      = month_df.nlargest(1, "Amount (USD)")
    month_income = income_for_period(income_df, sel)
    surplus      = month_income - total_spent
    savings_rate = (surplus / month_income * 100) if month_income > 0 else None

    # KPI row — top
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Total Spent", f"${total_spent:,.2f}",
                    f"${remaining:,.2f} {'remaining' if remaining >= 0 else 'over budget'}",
                    "#667eea" if remaining >= 0 else "#e53e3e")
    with c2:
        metric_card("Monthly Budget", f"${total_budget:,.2f}",
                    f"{len(DEFAULT_BUDGETS)} categories tracked", "#48bb78")
    with c3:
        avg_tx_val = month_df["Amount (USD)"].mean() if len(month_df) else 0
        metric_card("Transactions", str(len(month_df)),
                    f"Avg ${avg_tx_val:,.2f} each", "#ed8936")

    # KPI row — income row
    i1, i2, i3 = st.columns(3)
    with i1:
        if month_income > 0:
            metric_card("Take-Home Pay", f"${month_income:,.2f}",
                        f"Entered for {sel}", "#00b4d8")
        else:
            metric_card("Take-Home Pay", "Not entered",
                        "Add via 💵 Income page", "#aaaaaa")
    with i2:
        if month_income > 0:
            color = "#38a169" if surplus >= 0 else "#e53e3e"
            metric_card(
                "Surplus / Deficit",
                f"${surplus:+,.2f}",
                f"{'Saved' if surplus >= 0 else 'Over'} vs take-home",
                color,
            )
        else:
            metric_card("Surplus / Deficit", "—", "Enter income to calculate", "#aaaaaa")
    with i3:
        if savings_rate is not None:
            rate_color = "#38a169" if savings_rate >= 20 else "#ed8936" if savings_rate >= 0 else "#e53e3e"
            metric_card("Savings Rate", f"{savings_rate:.1f}%",
                        "≥20% is a healthy target", rate_color)
        else:
            metric_card("Savings Rate", "—", "Enter income to calculate", "#aaaaaa")

    # Largest purchase card
    top_merchant = largest.iloc[0]["Merchant"] if len(largest) else "—"
    top_amt      = largest.iloc[0]["Amount (USD)"] if len(largest) else 0
    if len(largest):
        top_key = make_tx_key(
            largest.iloc[0]["Transaction Date"],
            largest.iloc[0]["Merchant"],
            largest.iloc[0]["Amount (USD)"],
        )
        top_comment = comments.get(top_key, "")
        sub_label = f"💬 {top_comment}" if top_comment else top_merchant
    else:
        sub_label = "—"
    lp1, lp2, lp3 = st.columns(3)
    with lp2:
        metric_card("Largest Purchase", f"${top_amt:,.2f}", sub_label, "#9f7aea")

    st.divider()

    # Category spend vs budget
    cat_spend = (
        month_df.groupby("Category")["Amount (USD)"]
        .sum()
        .reset_index()
        .rename(columns={"Amount (USD)": "Spent"})
    )
    cat_spend["Budget"] = cat_spend["Category"].map(budgets).fillna(0)
    cat_spend["Remaining"] = cat_spend["Budget"] - cat_spend["Spent"]
    cat_spend["Pct"] = (
        cat_spend["Spent"]
        / cat_spend["Budget"].replace(0, float("nan"))
        * 100
    ).round(1)
    cat_spend = cat_spend.sort_values("Spent", ascending=False)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.subheader("Spending vs. Budget")
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name="Budget",
            x=cat_spend["Category"],
            y=cat_spend["Budget"],
            marker_color="rgba(180,180,200,0.35)",
            marker_line_color="rgba(150,150,180,0.6)",
            marker_line_width=1,
        ))
        fig.add_trace(go.Bar(
            name="Spent",
            x=cat_spend["Category"],
            y=cat_spend["Spent"],
            marker_color=[CATEGORY_COLORS.get(c, "#9E9E9E") for c in cat_spend["Category"]],
        ))
        fig.update_layout(
            barmode="overlay",
            height=320,
            margin=dict(t=10, b=10, l=0, r=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Budget Gauges")
        for _, row in cat_spend[cat_spend["Budget"] > 0].iterrows():
            pct = min((row["Pct"] or 0) / 100, 1.0)
            icon = "🟢" if pct < 0.75 else "🟡" if pct < 1.0 else "🔴"
            st.markdown(f"{icon} **{row['Category']}** — ${row['Spent']:,.0f} / ${row['Budget']:,.0f}")
            st.progress(pct)

    st.divider()

    # Bottom row
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        st.subheader("Breakdown")
        fig2 = px.pie(
            cat_spend[cat_spend["Spent"] > 0],
            values="Spent",
            names="Category",
            color="Category",
            color_discrete_map=CATEGORY_COLORS,
            hole=0.45,
        )
        fig2.update_traces(textposition="inside", textinfo="percent")
        fig2.update_layout(height=280, margin=dict(t=10, b=10, l=0, r=0),
                           showlegend=True,
                           legend=dict(font=dict(size=11)),
                           plot_bgcolor="rgba(0,0,0,0)",
                           paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, use_container_width=True)

    with col_b:
        st.subheader("Top Merchants")
        top_m = (
            month_df.groupby("Merchant")["Amount (USD)"]
            .sum()
            .sort_values(ascending=True)
            .tail(8)
            .reset_index()
        )
        fig3 = px.bar(
            top_m,
            x="Amount (USD)",
            y="Merchant",
            orientation="h",
            color_discrete_sequence=["#667eea"],
        )
        fig3.update_layout(height=280, margin=dict(t=10, b=10, l=0, r=0),
                           yaxis_title="", xaxis_title="",
                           plot_bgcolor="rgba(0,0,0,0)",
                           paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig3, use_container_width=True)

    with col_c:
        st.subheader("Daily Spend")
        daily = (
            month_df.groupby(month_df["Transaction Date"].dt.date)["Amount (USD)"]
            .sum()
            .reset_index()
        )
        daily.columns = ["Date", "Amount"]
        daily["Cumulative"] = daily["Amount"].cumsum()
        fig4 = go.Figure()
        fig4.add_trace(go.Bar(
            x=daily["Date"], y=daily["Amount"],
            name="Daily", marker_color="#667eea", opacity=0.8,
        ))
        fig4.add_trace(go.Scatter(
            x=daily["Date"], y=daily["Cumulative"],
            name="Running Total",
            line=dict(color="#f093fb", width=2),
            yaxis="y2",
        ))
        fig4.update_layout(
            height=280,
            margin=dict(t=10, b=10, l=0, r=0),
            yaxis2=dict(overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", font=dict(size=10), yanchor="bottom", y=1.01),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig4, use_container_width=True)

    # Monthly note
    st.divider()
    st.subheader("📝 Monthly Note")
    existing_note = notes.get(sel, "")
    new_note = st.text_area(
        "Add context for this month (vacation, big purchase, etc.)",
        value=existing_note,
        height=80,
        key=f"note_{sel}",
        label_visibility="collapsed",
        placeholder="E.g. 'Concord day trip week of 2/21 — extra restaurant spend expected'"
    )
    if st.button("Save Note"):
        save_note(sh, sel, new_note)
        st.success("Note saved!")


# ─── PAGE: UPLOAD ─────────────────────────────────────────────────────────────
def page_upload(sh):
    st.title("📤 Upload Statement")
    st.markdown(
        "Export your Apple Card statement as a **CSV** from the Wallet app, then upload it here."
    )

    with st.expander("ℹ️ How to export from Apple Wallet", expanded=False):
        st.markdown("""
1. Open the **Wallet** app on your iPhone
2. Tap your **Apple Card**
3. Tap the **three-dot menu** (···) → **Statements**
4. Select the month → **Export Transactions**
5. Choose **CSV** and save/share the file
        """)


    uploaded = st.file_uploader("Drop your Apple Card CSV here", type="csv")

    if uploaded is None:
        return


    try:
        df_new = parse_apple_card_csv(uploaded)
    except Exception as e:
        st.error(f"Could not parse file: {e}")
        return

    # Apply saved merchant→category rules before preview
    rules = load_rules(sh)
    df_new, n_remapped = apply_rules(df_new, rules)

    purchases = df_new[df_new["Type"] == "Purchase"]
    payments = df_new[df_new["Type"] == "Payment"]
    months_in = df_new["Month"].dropna().unique().tolist()
    years_in = df_new["Year"].dropna().unique().tolist()

    st.success(
        f"✅ Parsed **{len(df_new)}** rows — "
        f"{', '.join(months_in)} {', '.join(set(years_in))}"
    )
    if n_remapped:
        st.info(f"🤖 **{n_remapped}** transaction(s) auto-remapped using your saved rules.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Purchases", len(purchases))
    c2.metric("Payments / Credits", len(payments))
    c3.metric("Gross Spend", f"${purchases['Amount (USD)'].sum():,.2f}")
    c4.metric("Payments Applied", f"${abs(payments['Amount (USD)'].sum()):,.2f}")

    st.subheader("Preview (first 25 rows)")
    st.dataframe(
        df_new[["Transaction Date", "Merchant", "Category", "Amount (USD)", "Type"]].head(25),
        use_container_width=True,
        column_config={"Amount (USD)": st.column_config.NumberColumn(format="$%.2f")},
    )

    # ── Duplicate detection ────────────────────────────────────────────────
    existing_df = load_transactions(sh)
    dupe_mask = pd.Series([False] * len(df_new), dtype=bool)

    if not existing_df.empty:
        existing_keys = set(
            zip(
                existing_df["Transaction Date"].astype(str),
                existing_df["Merchant"].astype(str),
                existing_df["Amount (USD)"].astype(str),
            )
        )
        new_keys = list(
            zip(
                df_new["Transaction Date"].astype(str),
                df_new["Merchant"].astype(str),
                df_new["Amount (USD)"].astype(str),
            )
        )
        dupe_mask = pd.Series(
            [k in existing_keys for k in new_keys], dtype=bool
        )

    dupes_df = df_new[dupe_mask].copy()
    clean_df = df_new[~dupe_mask].copy()

    # ── Duplicate review UI ──────────────────────────────────────────────────
    rows_to_exclude = set()

    if not dupes_df.empty:
        st.warning(
            f"⚠️ **{len(dupes_df)}** transaction(s) look like possible duplicates "
            "(same date + merchant + amount already in your history). "
            "Review below — uncheck any that are legitimately separate transactions."
        )

        with st.expander(f"Review {len(dupes_df)} flagged transaction(s)", expanded=True):
            st.caption(
                "Checked rows will be **excluded** from this import. "
                "Uncheck any that are real separate transactions (e.g. same coffee shop twice in one day)."
            )

            # Header row
            h0, h1, h2, h3, h4 = st.columns([1, 2, 3, 2, 2])
            h0.markdown("**Skip?**")
            h1.markdown("**Date**")
            h2.markdown("**Merchant**")
            h3.markdown("**Category**")
            h4.markdown("**Amount**")

            st.divider()

            for i, (orig_idx, row) in enumerate(dupes_df.iterrows()):
                c0, c1, c2, c3, c4 = st.columns([1, 2, 3, 2, 2])
                exclude = c0.checkbox(
                    "exclude",
                    value=True,
                    key=f"dupe_chk_{i}",
                    label_visibility="collapsed",
                )
                c1.write(str(row["Transaction Date"])[:10])
                c2.write(row["Merchant"])
                c3.write(row["Category"])
                c4.write(f"${float(row['Amount (USD)']):,.2f}")
                if exclude:
                    rows_to_exclude.add(i)

            n_excluded = len(rows_to_exclude)
            n_included = len(dupes_df) - n_excluded
            if n_excluded:
                st.info(
                    f"**{n_excluded}** flagged row(s) will be skipped. "
                    + (f"**{n_included}** flagged row(s) will still be imported as new transactions." if n_included else "")
                )

        # Build the final df to import: clean rows + any un-excluded dupes
        included_dupes = [
            row for i, (_, row) in enumerate(dupes_df.iterrows())
            if i not in rows_to_exclude
        ]
        if included_dupes:
            df_to_import = pd.concat(
                [clean_df, pd.DataFrame(included_dupes)], ignore_index=True
            )
        else:
            df_to_import = clean_df
    else:
        df_to_import = df_new
        st.success("✅ No duplicates detected.")

    # ── Import button ────────────────────────────────────────────────────────
    n_importing = len(df_to_import)
    n_skipping = len(df_new) - n_importing

    btn_label = f"💾 Import {n_importing} transaction(s) to Google Sheets"
    if n_skipping:
        btn_label += f" (skipping {n_skipping} duplicate(s))"

    if n_importing == 0:
        st.warning("Nothing to import — all rows are duplicates and marked to skip.")
    elif st.button(btn_label, type="primary", use_container_width=True):
        with st.spinner("Saving…"):
            df_save = df_to_import.copy()
            df_save["Transaction Date"] = df_save["Transaction Date"].astype(str)
            save_transactions(sh, df_save)
        skipped_note = f" {n_skipping} duplicate(s) skipped." if n_skipping else ""
        st.success(f"Done! Imported {n_importing} transaction(s).{skipped_note} Head to the Dashboard.")
        st.balloons()


# ─── CATEGORY SAVE HELPER ─────────────────────────────────────────────────────
def save_all_transactions(sh, df: pd.DataFrame):
    """Overwrite the entire transactions sheet with df."""
    ws = get_or_create_worksheet(sh, "transactions")
    df_save = df.copy()
    df_save["Transaction Date"] = df_save["Transaction Date"].astype(str)
    for col in TRANSACTION_HEADERS:
        if col not in df_save.columns:
            df_save[col] = ""
    ws.clear()
    ws.update([TRANSACTION_HEADERS] + df_save[TRANSACTION_HEADERS].values.tolist())
    load_transactions.clear()


# ─── PAGE: TRANSACTIONS ───────────────────────────────────────────────────────
def page_transactions(sh):
    st.title("🧾 Transactions")

    df = load_transactions(sh)
    if df.empty:
        st.info("No data yet.")
        return

    purchases = get_purchases(df)
    all_cats = sorted(list(DEFAULT_BUDGETS.keys()))

    # ── Filters ───────────────────────────────────────────────────────────────
    with st.expander("🔍 Filter", expanded=True):
        fc1, fc2, fc3, fc4, fc5 = st.columns(5)
        periods = ["All"] + [str(p) for p in available_periods(purchases)]
        sel_period = fc1.selectbox("Month", periods)
        cats = ["All"] + sorted(purchases["Category"].dropna().unique().tolist())
        sel_cat = fc2.selectbox("Category", cats)
        types_opts = ["Purchases Only", "All Types"]
        sel_type = fc3.selectbox("Type", types_opts)
        search = fc4.text_input("Search merchant")
        min_amt = fc5.number_input("Min $ amount", value=0.0, step=5.0)

    base = purchases.copy() if sel_type == "Purchases Only" else df.copy()
    if sel_period != "All":
        base = base[base["Transaction Date"].dt.to_period("M") == pd.Period(sel_period)]
    if sel_cat != "All":
        base = base[base["Category"] == sel_cat]
    if search:
        mask = (
            base["Merchant"].str.contains(search, case=False, na=False) |
            base["Description"].str.contains(search, case=False, na=False)
        )
        base = base[mask]
    base = base[base["Amount (USD)"] >= min_amt]
    base = base.sort_values("Transaction Date", ascending=False)
    base["_orig_idx"] = base.index  # preserve original df row position before reset
    base = base.reset_index(drop=True)

    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("Rows shown", len(base))
    tc2.metric("Total", f"${base['Amount (USD)'].sum():,.2f}")
    tc3.metric("Average", f"${base['Amount (USD)'].mean():,.2f}" if len(base) else "$—")

    tab_edit, tab_bulk = st.tabs(["✏️ Edit Transactions", "🔁 Bulk Re-categorize"])

    # ── Tab 1: Inline editor ──────────────────────────────────────────────────
    with tab_edit:
        st.caption("Edit **Category** or add a **Comment** to any row. Click a cell, then save.")

        # Load existing comments and join onto base
        comments = load_comments(sh)
        base["_tx_key"] = base.apply(
            lambda r: make_tx_key(r["Transaction Date"], r["Merchant"], r["Amount (USD)"]), axis=1
        )
        base["Comment"] = base["_tx_key"].map(comments).fillna("")

        display_cols = ["Transaction Date", "Merchant", "Category", "Amount (USD)", "Purchased By", "Type", "Comment"]
        edit_df = base[display_cols].copy().rename(columns={"Amount (USD)": "Amount"})

        edited = st.data_editor(
            edit_df,
            use_container_width=True,
            height=520,
            num_rows="fixed",
            column_config={
                "Transaction Date": st.column_config.DateColumn("Date", disabled=True),
                "Merchant": st.column_config.TextColumn("Merchant", disabled=True),
                "Category": st.column_config.SelectboxColumn(
                    "Category",
                    options=all_cats,
                    required=True,
                ),
                "Amount": st.column_config.NumberColumn("Amount ($)", format="$%.2f", disabled=True),
                "Purchased By": st.column_config.TextColumn("Purchased By", disabled=True),
                "Type": st.column_config.TextColumn("Type", disabled=True),
                "Comment": st.column_config.TextColumn(
                    "💬 Comment",
                    help="Optional note for this transaction",
                    max_chars=200,
                ),
            },
            key="tx_editor",
        )

        cat_changed_mask = edited["Category"].values != edit_df["Category"].values
        comment_changed_mask = edited["Comment"].fillna("").values != edit_df["Comment"].fillna("").values
        any_changed_mask = cat_changed_mask | comment_changed_mask
        n_cat = int(cat_changed_mask.sum())
        n_comment = int(comment_changed_mask.sum())
        n_changed = int(any_changed_mask.sum())

        sc1, sc2 = st.columns([3, 1])
        with sc1:
            parts = []
            if n_cat:
                parts.append(f"**{n_cat}** category change(s)")
            if n_comment:
                parts.append(f"**{n_comment}** comment change(s)")
            if parts:
                st.info(f"{' and '.join(parts)} unsaved.")
            else:
                st.caption("No unsaved changes.")
        with sc2:
            save_clicked = st.button(
                f"💾 Save {n_changed} change(s)" if n_changed else "💾 Save Changes",
                type="primary",
                disabled=(n_changed == 0),
                use_container_width=True,
                key="save_inline",
            )

        if save_clicked and n_changed:
            with st.spinner("Saving to Google Sheets…"):
                # Save category changes back to transactions sheet
                if n_cat:
                    full_df = df.copy()
                    new_cats = edited.loc[cat_changed_mask, "Category"].values
                    orig_indices = base.loc[cat_changed_mask, "_orig_idx"].values
                    full_df.loc[orig_indices, "Category"] = new_cats
                    save_all_transactions(sh, full_df)

                # Save comment changes to comments sheet
                if n_comment:
                    updated_comments = dict(comments)  # copy existing
                    for i, row in edited[comment_changed_mask].iterrows():
                        key = base.loc[i, "_tx_key"]
                        new_comment = str(row["Comment"]).strip() if row["Comment"] else ""
                        if new_comment:
                            updated_comments[key] = new_comment
                        elif key in updated_comments:
                            del updated_comments[key]  # blank comment = delete it
                    save_comments(sh, updated_comments)

            st.success(f"✅ Saved {n_changed} change(s)!")
            st.rerun()

        st.divider()
        csv_bytes = base.to_csv(index=False).encode()
        st.download_button(
            "⬇️ Export filtered CSV",
            csv_bytes,
            f"transactions_{sel_period}.csv",
            "text/csv",
        )

    # ── Tab 2: Bulk re-categorize ─────────────────────────────────────────────
    with tab_bulk:
        st.markdown(
            "Pick a merchant and assign a new category to **all** of their transactions "
            "across your entire history — useful for fixing Apple's auto-categorization in bulk."
        )

        merchant_list = sorted(df["Merchant"].dropna().unique().tolist())
        bc1, bc2, bc3 = st.columns([3, 2, 1])

        sel_merchant = bc1.selectbox("Merchant", merchant_list, key="bulk_merchant")
        sel_new_cat = bc2.selectbox("New Category", all_cats, key="bulk_cat")

        merchant_rows = df[df["Merchant"] == sel_merchant]
        current_cats = merchant_rows["Category"].value_counts()
        current_str = ", ".join(f"{c} ({n})" for c, n in current_cats.items())
        tx_count = len(merchant_rows)

        st.caption(
            f"**{sel_merchant}** has **{tx_count}** transaction(s). "
            f"Current categories: {current_str}"
        )

        if merchant_rows[merchant_rows["Type"] == "Purchase"]["Amount (USD)"].sum() > 0:
            total_str = f"${merchant_rows[merchant_rows['Type'] == 'Purchase']['Amount (USD)'].sum():,.2f} total spend"
        else:
            total_str = ""
        if total_str:
            st.caption(total_str)


        save_as_rule = st.checkbox(
            f"🤖 Save as rule — always categorize '{sel_merchant}' as {sel_new_cat} on future imports",
            value=True,
            key="bulk_save_rule",
        )

        bulk_btn = bc3.button(
            f"Apply to {tx_count} rows",
            type="primary",
            use_container_width=True,
            key="bulk_apply",
        )

        if bulk_btn:
            with st.spinner("Updating…"):
                full_df = load_transactions(sh).copy()
                full_df.loc[full_df["Merchant"] == sel_merchant, "Category"] = sel_new_cat
                save_all_transactions(sh, full_df)
                load_transactions.clear()
                if save_as_rule:
                    save_rule(sh, sel_merchant, sel_new_cat)
            rule_note = " Rule saved! 🤖" if save_as_rule else ""
            st.success(
                f"✅ Re-categorized all **{tx_count}** '{sel_merchant}' transactions → **{sel_new_cat}**.{rule_note}"
            )
            st.rerun()

        st.divider()
        st.subheader("Category Assignment by Merchant")
        st.caption("Overview of every merchant and their current categories — spot miscategorizations at a glance.")
        merchant_summary = (
            df[df["Type"] == "Purchase"]
            .groupby(["Merchant", "Category"])
            .agg(Transactions=("Amount (USD)", "count"), Total=("Amount (USD)", "sum"))
            .reset_index()
            .sort_values("Total", ascending=False)
        )
        st.dataframe(
            merchant_summary.style.format({"Total": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
            height=420,
        )


# ─── PAGE: BUDGETS ────────────────────────────────────────────────────────────
def page_budgets(sh):
    st.title("🎯 Monthly Budgets")
    st.markdown("Set your spending targets for each category. Saved directly to Google Sheets.")

    budgets = load_budgets(sh)
    cats = [c for c in DEFAULT_BUDGETS]

    updated = {}
    cols = st.columns(2)
    for i, cat in enumerate(cats):
        col = cols[i % 2]
        color = CATEGORY_COLORS.get(cat, "#9E9E9E")
        col.markdown(
            f'<span style="color:{color};font-size:1.1rem">●</span> **{cat}**',
            unsafe_allow_html=True,
        )
        val = col.number_input(
            f"budget_{cat}",
            value=float(budgets.get(cat, DEFAULT_BUDGETS.get(cat, 0))),
            min_value=0.0,
            step=25.0,
            format="%.2f",
            label_visibility="collapsed",
            key=f"b_{cat}",
        )
        updated[cat] = val

    st.divider()
    total = sum(updated.values())
    st.info(f"💡 Total monthly budget across all categories: **${total:,.2f}**")

    if st.button("💾 Save Budgets", type="primary", use_container_width=True):
        with st.spinner("Saving…"):
            save_budgets(sh, updated)
        st.success("Budgets updated!")


# ─── PAGE: TRENDS ─────────────────────────────────────────────────────────────
def page_trends(sh):
    st.title("📈 Trends")

    df = load_transactions(sh)
    if df.empty or get_purchases(df).empty:
        st.info("Need at least one month of data.")
        return

    purchases = get_purchases(df).copy()
    purchases["Period"] = purchases["Transaction Date"].dt.to_period("M").astype(str)
    purchases["Year"]   = purchases["Transaction Date"].dt.year.astype(str)
    purchases["Month#"] = purchases["Transaction Date"].dt.month

    budgets = load_budgets(sh)
    income_df = load_income(sh)
    total_budget = sum(v for k, v in budgets.items())

    def color_change(val):
        if isinstance(val, float) and val > 0:
            return "color:#e53e3e"
        if isinstance(val, float) and val < 0:
            return "color:#38a169"
        return ""

    CHART_LAYOUT = dict(
        margin=dict(t=10, b=10, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )

    tab_monthly, tab_heatmap, tab_mom, tab_year, tab_yoy = st.tabs([
        "📅 Monthly", "🌡️ Heatmap", "↔️ Month-over-Month",
        "📆 Year View", "📊 Year-over-Year",
    ])

    # ── Tab 1: Monthly ────────────────────────────────────────────────────────
    with tab_monthly:
        monthly = (
            purchases.groupby("Period")["Amount (USD)"]
            .sum().reset_index()
            .rename(columns={"Amount (USD)": "Total"})
            .sort_values("Period")
        )
        monthly["Budget"] = total_budget

        # Join income by period
        if not income_df.empty:
            inc_by_period = income_df.groupby("Period")["Amount"].sum().reset_index()
            monthly = monthly.merge(inc_by_period, on="Period", how="left").rename(
                columns={"Amount": "Income"}
            )
        else:
            monthly["Income"] = None

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=monthly["Period"], y=monthly["Total"],
            name="Spent", marker_color="#667eea",
        ))
        fig.add_trace(go.Scatter(
            x=monthly["Period"], y=monthly["Budget"],
            name="Budget", line=dict(color="#e53e3e", width=2, dash="dash"),
        ))
        if monthly["Income"].notna().any():
            fig.add_trace(go.Scatter(
                x=monthly["Period"], y=monthly["Income"],
                name="Take-Home", line=dict(color="#00b4d8", width=2),
                mode="lines+markers",
            ))
        fig.update_layout(height=320, **CHART_LAYOUT)
        st.plotly_chart(fig, use_container_width=True)

    # ── Tab 2: Heatmap ────────────────────────────────────────────────────────
    with tab_heatmap:
        cat_monthly = purchases.groupby(["Period", "Category"])["Amount (USD)"].sum().reset_index()
        pivot = cat_monthly.pivot(index="Category", columns="Period", values="Amount (USD)").fillna(0)
        fig2 = px.imshow(
            pivot, color_continuous_scale="Blues",
            aspect="auto", text_auto="$.0f",
        )
        fig2.update_layout(height=400, margin=dict(t=10, b=10, l=0, r=0))
        st.plotly_chart(fig2, use_container_width=True)

    # ── Tab 3: Month-over-Month ───────────────────────────────────────────────
    with tab_mom:
        periods_avail = sorted(purchases["Period"].unique())
        if len(periods_avail) < 2:
            st.info("Upload at least 2 months of data to compare.")
        else:
            cc1, cc2 = st.columns(2)
            p1 = cc1.selectbox("From", periods_avail, index=len(periods_avail) - 2, key="p1")
            p2 = cc2.selectbox("To",   periods_avail, index=len(periods_avail) - 1, key="p2")

            s1  = purchases[purchases["Period"] == p1].groupby("Category")["Amount (USD)"].sum()
            s2  = purchases[purchases["Period"] == p2].groupby("Category")["Amount (USD)"].sum()
            cmp = pd.DataFrame({"Previous": s1, "Current": s2}).fillna(0).reset_index()
            cmp["Change"]   = cmp["Current"] - cmp["Previous"]
            cmp["Change %"] = (cmp["Change"] / cmp["Previous"].replace(0, float("nan")) * 100).round(1)
            cmp = cmp.sort_values("Change", ascending=False)

            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=cmp["Category"], y=cmp["Previous"],
                                  name=p1, marker_color="rgba(100,126,234,0.45)"))
            fig3.add_trace(go.Bar(x=cmp["Category"], y=cmp["Current"],
                                  name=p2, marker_color="#667eea"))
            fig3.update_layout(barmode="group", height=320, **CHART_LAYOUT)
            st.plotly_chart(fig3, use_container_width=True)

            st.dataframe(
                cmp.style
                .format({"Previous": "${:,.2f}", "Current": "${:,.2f}",
                         "Change": "${:+,.2f}", "Change %": "{:+.1f}%"})
                .map(color_change, subset=["Change", "Change %"]),
                use_container_width=True,
            )

    # ── Tab 4: Year View ──────────────────────────────────────────────────────
    with tab_year:
        years_avail = sorted(purchases["Year"].unique(), reverse=True)
        sel_year = st.selectbox("Year", years_avail, key="year_sel")
        yr_df = purchases[purchases["Year"] == sel_year]

        if yr_df.empty:
            st.info("No data for this year.")
        else:
            total_yr     = yr_df["Amount (USD)"].sum()
            months_in_yr = yr_df["Period"].nunique()
            avg_monthly  = total_yr / months_in_yr if months_in_yr else 0
            biggest_mo   = yr_df.groupby("Period")["Amount (USD)"].sum().idxmax()
            biggest_mo_amt = yr_df.groupby("Period")["Amount (USD)"].sum().max()
            top_cat      = yr_df.groupby("Category")["Amount (USD)"].sum().idxmax()

            annual_income = income_for_year(income_df, sel_year)
            annual_surplus = annual_income - total_yr
            annual_savings_rate = (annual_surplus / annual_income * 100) if annual_income > 0 else None

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                metric_card("Total Spent", f"${total_yr:,.2f}",
                            f"{months_in_yr} month(s) of data", "#667eea")
            with k2:
                over_budget_months = int(
                    (yr_df.groupby("Period")["Amount (USD)"].sum() > total_budget).sum()
                )
                metric_card("Avg / Month", f"${avg_monthly:,.2f}",
                            f"{over_budget_months} month(s) over budget", "#48bb78")
            with k3:
                metric_card("Biggest Month", f"${biggest_mo_amt:,.2f}",
                            biggest_mo, "#ed8936")
            with k4:
                top_cat_amt = yr_df.groupby("Category")["Amount (USD)"].sum().max()
                metric_card("Top Category", f"${top_cat_amt:,.2f}",
                            top_cat, "#9f7aea")

            # Income KPI row
            i1, i2, i3, i4 = st.columns(4)
            with i1:
                if annual_income > 0:
                    metric_card("Annual Take-Home", f"${annual_income:,.2f}",
                                f"Avg ${annual_income/12:,.2f}/mo", "#00b4d8")
                else:
                    metric_card("Annual Take-Home", "Not entered",
                                "Add via 💵 Income page", "#aaaaaa")
            with i2:
                if annual_income > 0:
                    sc = "#38a169" if annual_surplus >= 0 else "#e53e3e"
                    metric_card("Annual Surplus", f"${annual_surplus:+,.2f}",
                                f"{'Saved' if annual_surplus >= 0 else 'Over'} vs take-home", sc)
                else:
                    metric_card("Annual Surplus", "—", "Enter income to calculate", "#aaaaaa")
            with i3:
                if annual_savings_rate is not None:
                    rc = "#38a169" if annual_savings_rate >= 20 else "#ed8936" if annual_savings_rate >= 0 else "#e53e3e"
                    metric_card("Savings Rate", f"{annual_savings_rate:.1f}%",
                                "≥20% is a healthy target", rc)
                else:
                    metric_card("Savings Rate", "—", "Enter income to calculate", "#aaaaaa")
            with i4:
                metric_card("Biggest Month", f"${biggest_mo_amt:,.2f}", biggest_mo, "#ed8936")

            st.divider()

            # 12-month bar chart for the selected year
            ALL_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
                          "Jul","Aug","Sep","Oct","Nov","Dec"]
            mo_spend = yr_df.groupby("Month#")["Amount (USD)"].sum().reset_index()
            mo_spend["Month"] = mo_spend["Month#"].apply(lambda m: ALL_MONTHS[m - 1])
            # Fill missing months with zero
            full_mo = pd.DataFrame({"Month#": range(1, 13), "Month": ALL_MONTHS})
            mo_spend = full_mo.merge(mo_spend, on=["Month#", "Month"], how="left").fillna(0)

            fig_yr = go.Figure()
            fig_yr.add_trace(go.Bar(
                x=mo_spend["Month"], y=mo_spend["Amount (USD)"],
                name="Spent",
                marker_color=[
                    "#e53e3e" if v > total_budget else "#667eea"
                    for v in mo_spend["Amount (USD)"]
                ],
            ))
            fig_yr.add_hline(
                y=total_budget, line_dash="dash",
                line_color="#e53e3e", annotation_text="Monthly Budget",
                annotation_position="top left",
            )
            if annual_income > 0:
                monthly_income_avg = annual_income / 12
                fig_yr.add_hline(
                    y=monthly_income_avg, line_dash="dot",
                    line_color="#00b4d8",
                    annotation_text=f"Avg Monthly Income (${monthly_income_avg:,.0f})",
                    annotation_position="bottom left",
                )
            fig_yr.update_layout(height=320, showlegend=False, **CHART_LAYOUT)
            st.plotly_chart(fig_yr, use_container_width=True)

            st.divider()

            # Category breakdown for the year
            col_l, col_r = st.columns(2)
            with col_l:
                st.subheader("Category Breakdown")
                cat_yr = yr_df.groupby("Category")["Amount (USD)"].sum().reset_index()
                cat_yr["Annual Budget"] = cat_yr["Category"].map(
                    {k: v * 12 for k, v in budgets.items()}
                ).fillna(0)
                cat_yr["vs Budget"] = cat_yr["Amount (USD)"] - cat_yr["Annual Budget"]
                cat_yr = cat_yr.sort_values("Amount (USD)", ascending=False)
                st.dataframe(
                    cat_yr.style.format({
                        "Amount (USD)":   "${:,.2f}",
                        "Annual Budget":  "${:,.2f}",
                        "vs Budget":      "${:+,.2f}",
                    }).map(color_change, subset=["vs Budget"]),
                    use_container_width=True,
                    hide_index=True,
                )
            with col_r:
                st.subheader("Spend Distribution")
                fig_pie = px.pie(
                    cat_yr, values="Amount (USD)", names="Category",
                    color="Category", color_discrete_map=CATEGORY_COLORS, hole=0.4,
                )
                fig_pie.update_layout(
                    height=340, margin=dict(t=10, b=10, l=0, r=0),
                    legend=dict(font=dict(size=11)),
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_pie, use_container_width=True)

    # ── Tab 5: Year-over-Year ─────────────────────────────────────────────────
    with tab_yoy:
        years_avail_asc = sorted(purchases["Year"].unique())

        if len(years_avail_asc) < 2:
            st.info("Upload data from at least 2 calendar years to enable this view.")
        else:
            yc1, yc2 = st.columns(2)
            y1 = yc1.selectbox("Base Year",       years_avail_asc,
                               index=len(years_avail_asc) - 2, key="yoy_y1")
            y2 = yc2.selectbox("Comparison Year", years_avail_asc,
                               index=len(years_avail_asc) - 1, key="yoy_y2")

            y1_df = purchases[purchases["Year"] == y1]
            y2_df = purchases[purchases["Year"] == y2]

            # ── Top-line KPIs ────────────────────────────────────────────────
            y1_total = y1_df["Amount (USD)"].sum()
            y2_total = y2_df["Amount (USD)"].sum()
            delta_total = y2_total - y1_total
            delta_pct   = (delta_total / y1_total * 100) if y1_total else 0

            y1_mo_avg = y1_total / max(y1_df["Period"].nunique(), 1)
            y2_mo_avg = y2_total / max(y2_df["Period"].nunique(), 1)

            kc1, kc2, kc3, kc4 = st.columns(4)
            with kc1:
                metric_card(f"{y1} Total", f"${y1_total:,.2f}",
                            f"{y1_df['Period'].nunique()} months", "#667eea")
            with kc2:
                metric_card(f"{y2} Total", f"${y2_total:,.2f}",
                            f"{y2_df['Period'].nunique()} months",
                            "#e53e3e" if delta_total > 0 else "#48bb78")
            with kc3:
                sign = "+" if delta_total >= 0 else ""
                metric_card("Δ Total Spend",
                            f"{sign}${delta_total:,.2f}",
                            f"{sign}{delta_pct:.1f}% year over year",
                            "#e53e3e" if delta_total > 0 else "#48bb78")
            with kc4:
                mo_delta = y2_mo_avg - y1_mo_avg
                sign = "+" if mo_delta >= 0 else ""
                metric_card("Δ Monthly Avg",
                            f"{sign}${mo_delta:,.2f}",
                            f"{y1}: ${y1_mo_avg:,.0f}  →  {y2}: ${y2_mo_avg:,.0f}",
                            "#e53e3e" if mo_delta > 0 else "#48bb78")

            st.divider()

            # ── Month-by-month overlay ───────────────────────────────────────
            st.subheader("Month-by-Month Overlay")
            ALL_MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
                          "Jul","Aug","Sep","Oct","Nov","Dec"]

            def monthly_by_year(yr_purchases, label):
                mo = yr_purchases.groupby("Month#")["Amount (USD)"].sum().reset_index()
                full = pd.DataFrame({"Month#": range(1, 13), "Month": ALL_MONTHS})
                mo = full.merge(mo, on="Month#", how="left").fillna(0)
                mo["Year"] = label
                return mo

            y1_mo = monthly_by_year(y1_df, y1)
            y2_mo = monthly_by_year(y2_df, y2)

            fig_ov = go.Figure()
            fig_ov.add_trace(go.Scatter(
                x=y1_mo["Month"], y=y1_mo["Amount (USD)"],
                name=y1, mode="lines+markers",
                line=dict(color="rgba(102,126,234,0.55)", width=2, dash="dot"),
                marker=dict(size=6),
            ))
            fig_ov.add_trace(go.Scatter(
                x=y2_mo["Month"], y=y2_mo["Amount (USD)"],
                name=y2, mode="lines+markers",
                line=dict(color="#667eea", width=2),
                marker=dict(size=7),
            ))
            fig_ov.add_hline(
                y=total_budget, line_dash="dash",
                line_color="#e53e3e", annotation_text="Monthly Budget",
                annotation_position="top left",
            )
            fig_ov.update_layout(height=320, **CHART_LAYOUT)
            st.plotly_chart(fig_ov, use_container_width=True)

            st.divider()

            # ── Category YoY table + chart ───────────────────────────────────
            st.subheader("Category Comparison")
            s_y1 = y1_df.groupby("Category")["Amount (USD)"].sum()
            s_y2 = y2_df.groupby("Category")["Amount (USD)"].sum()
            yoy  = pd.DataFrame({y1: s_y1, y2: s_y2}).fillna(0).reset_index()
            yoy["Δ $"]  = yoy[y2] - yoy[y1]
            yoy["Δ %"]  = (yoy["Δ $"] / yoy[y1].replace(0, float("nan")) * 100).round(1)
            yoy = yoy.sort_values("Δ $", ascending=False)

            fig_yoy = go.Figure()
            fig_yoy.add_trace(go.Bar(
                x=yoy["Category"], y=yoy[y1],
                name=y1, marker_color="rgba(102,126,234,0.45)",
            ))
            fig_yoy.add_trace(go.Bar(
                x=yoy["Category"], y=yoy[y2],
                name=y2, marker_color="#667eea",
            ))
            fig_yoy.update_layout(barmode="group", height=320, **CHART_LAYOUT)
            st.plotly_chart(fig_yoy, use_container_width=True)

            st.dataframe(
                yoy.style
                .format({y1: "${:,.2f}", y2: "${:,.2f}",
                         "Δ $": "${:+,.2f}", "Δ %": "{:+.1f}%"})
                .map(color_change, subset=["Δ $", "Δ %"]),
                use_container_width=True,
                hide_index=True,
            )

            st.divider()

            # ── Callout cards ────────────────────────────────────────────────
            st.subheader("Notable Changes")
            yoy_valid = yoy[yoy[y1] > 0].copy()
            if not yoy_valid.empty:
                most_improved = yoy_valid.loc[yoy_valid["Δ $"].idxmin()]
                most_worsened = yoy_valid.loc[yoy_valid["Δ $"].idxmax()]

                nc1, nc2 = st.columns(2)
                with nc1:
                    delta_str = f"${most_improved['Δ $']:+,.2f} ({most_improved['Δ %']:+.1f}%)"
                    metric_card(
                        "✅ Most Improved Category",
                        most_improved["Category"],
                        delta_str, "#38a169",
                    )
                with nc2:
                    delta_str = f"${most_worsened['Δ $']:+,.2f} ({most_worsened['Δ %']:+.1f}%)"
                    metric_card(
                        "⚠️ Largest Increase",
                        most_worsened["Category"],
                        delta_str, "#e53e3e",
                    )


# ─── PAGE: INSIGHTS ───────────────────────────────────────────────────────────
def page_insights(sh):
    st.title("💡 Insights")

    df = load_transactions(sh)
    if df.empty or get_purchases(df).empty:
        st.info("No data yet.")
        return

    purchases = get_purchases(df).copy()
    purchases["Period"] = purchases["Transaction Date"].dt.to_period("M").astype(str)
    purchases["DOW"] = purchases["Transaction Date"].dt.day_name()
    purchases["Week"] = purchases["Transaction Date"].dt.isocalendar().week

    budgets = load_budgets(sh)

    tab1, tab2, tab3, tab4 = st.tabs([
        "🏆 Top Merchants", "📅 Spending Patterns", "📋 Budget Summary", "🔁 Recurring"
    ])

    with tab1:
        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("All-Time Top Merchants")
            top = (
                purchases.groupby("Merchant")["Amount (USD)"]
                .agg(["sum", "count"])
                .reset_index()
                .rename(columns={"sum": "Total Spent", "count": "Visits"})
            )
            top["Avg / Visit"] = (top["Total Spent"] / top["Visits"]).round(2)
            top = top.sort_values("Total Spent", ascending=False).head(15)
            st.dataframe(
                top.style.format({"Total Spent": "${:,.2f}", "Avg / Visit": "${:,.2f}"}),
                use_container_width=True,
                hide_index=True,
            )
        with col_b:
            st.subheader("Spend by Category (All Time)")
            cat_all = purchases.groupby("Category")["Amount (USD)"].sum().reset_index()
            fig = px.pie(cat_all, values="Amount (USD)", names="Category",
                         color="Category", color_discrete_map=CATEGORY_COLORS, hole=0.4)
            fig.update_layout(height=350, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Spending by Day of Week")
            dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            dow = purchases.groupby("DOW")["Amount (USD)"].sum().reindex(dow_order).reset_index()
            fig = px.bar(dow, x="DOW", y="Amount (USD)", color_discrete_sequence=["#667eea"])
            fig.update_layout(height=300, margin=dict(t=10, b=10, l=0, r=0),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.subheader("Avg Transaction by Category")
            avg_cat = (
                purchases.groupby("Category")["Amount (USD)"]
                .mean()
                .sort_values(ascending=True)
                .reset_index()
            )
            fig = px.bar(avg_cat, x="Amount (USD)", y="Category", orientation="h",
                         color="Category", color_discrete_map=CATEGORY_COLORS)
            fig.update_layout(height=300, margin=dict(t=10, b=10, l=0, r=0),
                               showlegend=False,
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        total_budget = sum(v for k, v in budgets.items() if k in DEFAULT_BUDGETS)
        monthly = purchases.groupby("Period")["Amount (USD)"].sum().reset_index()
        monthly["Budget"] = total_budget
        monthly["Delta"] = monthly["Budget"] - monthly["Amount (USD)"]
        monthly["Status"] = monthly["Delta"].apply(
            lambda x: "✅ Under" if x >= 0 else "🔴 Over"
        )
        monthly.columns = ["Month", "Spent", "Budget", "Remaining", "Status"]
        st.dataframe(
            monthly.sort_values("Month", ascending=False)
            .style.format({"Spent": "${:,.2f}", "Budget": "${:,.2f}", "Remaining": "${:+,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )

    with tab4:
        st.subheader("Potential Recurring Charges")
        st.caption("Merchants that appear in 2+ months are flagged as possible subscriptions or habits.")
        purchases["YearMonth"] = purchases["Transaction Date"].dt.to_period("M")
        recur = (
            purchases.groupby("Merchant")
            .agg(Months=("YearMonth", "nunique"), Total=("Amount (USD)", "sum"),
                 Count=("Amount (USD)", "count"), AvgAmt=("Amount (USD)", "mean"))
            .reset_index()
        )
        recur = recur[recur["Months"] >= 2].sort_values("Total", ascending=False)
        recur["Avg/Month"] = (recur["Total"] / recur["Months"]).round(2)
        st.dataframe(
            recur.style.format({"Total": "${:,.2f}", "AvgAmt": "${:,.2f}", "Avg/Month": "${:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )


# ─── PAGE: INCOME ────────────────────────────────────────────────────────────
def page_income(sh):
    st.title("💵 Income")
    st.markdown(
        "Track your monthly take-home pay by source. "
        "Income is used on the Dashboard and Trends page to calculate surplus and savings rate."
    )

    tab_add, tab_manage = st.tabs(["➕ Add Income", "📋 Manage Income"])

    # ── Add income entry ──────────────────────────────────────────────────────
    with tab_add:
        with st.form("income_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            period_date = f1.date_input("Month", value=datetime.today().replace(day=1))
            source = f2.text_input(
                "Source", placeholder="e.g. Salary, Freelance, Rental Income"
            )
            amount = st.number_input(
                "Take-Home Amount ($)", min_value=0.0, step=100.0, format="%.2f"
            )
            submitted = st.form_submit_button(
                "💾 Save Income Entry", type="primary", use_container_width=True
            )

        if st.session_state.get("income_save_success"):
            msg = st.session_state.pop("income_save_success")
            st.success(msg)

        if submitted:
            if not source.strip():
                st.error("Source is required.")
            elif amount <= 0:
                st.error("Amount must be greater than $0.")
            else:
                period_str = pd.Timestamp(period_date).strftime("%Y-%m")
                with st.spinner("Saving…"):
                    save_income_entry(sh, period_str, source.strip(), amount)
                st.session_state["income_save_success"] = (
                    f"✅ Saved: **{source.strip()}** — "
                    f"${amount:,.2f} for {pd.Timestamp(period_date).strftime('%B %Y')}"
                )
                st.rerun()

    # ── Manage income entries ─────────────────────────────────────────────────
    with tab_manage:
        income_df = load_income(sh)

        if income_df.empty:
            st.info("No income entries yet — add one in the **Add Income** tab.")
        else:
            # Summary by period
            st.subheader("Monthly Summary")
            summary = (
                income_df.groupby("Period")["Amount"]
                .agg(Total="sum", Sources="count")
                .reset_index()
                .sort_values("Period", ascending=False)
            )
            st.dataframe(
                summary.style.format({"Total": "${:,.2f}"}),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Period":  st.column_config.TextColumn("Month"),
                    "Total":   st.column_config.NumberColumn("Total Take-Home", format="$%.2f"),
                    "Sources": st.column_config.NumberColumn("# Sources"),
                },
            )

            st.divider()
            st.subheader("All Entries")
            st.caption("Click 🗑️ to delete an individual entry.")

            # Header
            h0, h1, h2, h3 = st.columns([2, 3, 2, 1])
            h0.markdown("**Month**")
            h1.markdown("**Source**")
            h2.markdown("**Amount**")
            h3.markdown("**Del**")
            st.divider()

            display = income_df.sort_values(
                ["Period", "Source"], ascending=[False, True]
            ).reset_index(drop=True)

            for i, row in display.iterrows():
                c0, c1, c2, c3 = st.columns([2, 3, 2, 1])
                try:
                    label = pd.Timestamp(row["Period"]).strftime("%B %Y")
                except Exception:
                    label = row["Period"]
                c0.write(label)
                c1.write(row["Source"])
                c2.write(f"${float(row['Amount']):,.2f}")
                if c3.button("🗑️", key=f"del_inc_{i}",
                             help=f"Delete {row['Source']} {row['Period']}"):
                    with st.spinner("Deleting…"):
                        delete_income_entry(
                            sh, row["Period"], row["Source"], float(row["Amount"])
                        )
                    st.success(
                        f"Deleted **{row['Source']}** entry for {label}."
                    )
                    st.rerun()


# ─── PAGE: RULES ─────────────────────────────────────────────────────────────
def page_rules(sh):
    st.title("🤖 Category Rules")
    st.markdown(
        "Rules automatically remap merchant categories on every import. "
        "Create them here or via the **Bulk Re-categorize** tab in Transactions."
    )

    rules = load_rules(sh)
    all_cats = sorted(list(DEFAULT_BUDGETS.keys()))

    # ── Add rule manually ────────────────────────────────────────────────────
    st.subheader("Add / Update a Rule")
    df_tx = load_transactions(sh)
    known_merchants = sorted(df_tx["Merchant"].dropna().unique().tolist()) if not df_tx.empty else []

    ra1, ra2, ra3 = st.columns([3, 2, 1])
    # Allow free-text or pick from known merchants
    merchant_input = ra1.selectbox(
        "Merchant", ["— type or select —"] + known_merchants, key="rule_merchant_sel"
    )
    if merchant_input == "— type or select —":
        merchant_input = ra1.text_input(
            "Or type merchant name", key="rule_merchant_text", label_visibility="collapsed",
            placeholder="Type exact merchant name…"
        ).strip()

    cat_input = ra2.selectbox("Category", all_cats, key="rule_cat_sel")

    if ra3.button("💾 Save Rule", type="primary", use_container_width=True, key="save_rule_btn"):
        if merchant_input:
            with st.spinner("Saving…"):
                save_rule(sh, merchant_input, cat_input)
            action = "Updated" if merchant_input in rules else "Added"
            st.success(f"✅ {action} rule: **{merchant_input}** → **{cat_input}**")
            st.rerun()
        else:
            st.warning("Please enter a merchant name.")

    st.divider()

    # ── Re-apply all rules to history ────────────────────────────────────────
    st.subheader("Re-apply All Rules to History")
    st.caption(
        "Runs every saved rule against your entire transaction history and saves the result. "
        "Useful after adding or editing rules."
    )
    if st.button("🔄 Re-apply All Rules Now", use_container_width=True, key="reapply_all"):
        if not rules:
            st.warning("No rules saved yet.")
        elif df_tx.empty:
            st.warning("No transaction history to update.")
        else:
            with st.spinner("Applying rules to full history…"):
                updated_df, n_changed = apply_rules(df_tx, rules)
                if n_changed:
                    save_all_transactions(sh, updated_df)
            if n_changed:
                st.success(f"✅ Re-applied rules — **{n_changed}** transaction(s) updated.")
            else:
                st.info("No changes needed — all transactions already match your rules.")
            st.rerun()

    st.divider()

    # ── Existing rules table ─────────────────────────────────────────────────
    st.subheader(f"Saved Rules ({len(rules)})")

    if not rules:
        st.info(
            "No rules yet. Add one above, or use the **Bulk Re-categorize** tab "
            "in Transactions and check \"Save as rule\"."
        )
        return

    rules_df = pd.DataFrame(
        [(m, c) for m, c in rules.items()],
        columns=["Merchant", "Category"]
    ).sort_values("Merchant").reset_index(drop=True)

    # Show table with per-row delete buttons
    header_cols = st.columns([4, 3, 1])
    header_cols[0].markdown("**Merchant**")
    header_cols[1].markdown("**Category**")
    header_cols[2].markdown("**Delete**")

    for _, row in rules_df.iterrows():
        rc1, rc2, rc3 = st.columns([4, 3, 1])
        color = CATEGORY_COLORS.get(row["Category"], "#9E9E9E")
        rc1.markdown(row["Merchant"])
        rc2.markdown(
            f'<span style="color:{color}">●</span> {row["Category"]}',
            unsafe_allow_html=True,
        )
        if rc3.button("🗑️", key=f"del_rule_{row['Merchant']}", help=f"Delete rule for {row['Merchant']}"):
            with st.spinner("Deleting…"):
                delete_rule(sh, row["Merchant"])
            st.success(f"Deleted rule for **{row['Merchant']}**")
            st.rerun()


# ─── PAGE: MANUAL ENTRY ──────────────────────────────────────────────────────
def page_manual_entry(sh):
    st.title("✏️ Manual Entry")

    all_cats = sorted(list(DEFAULT_BUDGETS.keys()))
    tab_add, tab_manage = st.tabs(["➕ Add Transaction", "🗑️ Manage Manual Entries"])

    # ── Tab 1: Add a transaction ───────────────────────────────────────────────
    with tab_add:
        st.markdown("Manually log a transaction that doesn't appear on your Apple Card statement.")

        with st.form("manual_entry_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            tx_date = fc1.date_input("Date", value=datetime.today())
            merchant = fc2.text_input("Merchant / Payee", placeholder="e.g. Flatbread Pizza")

            fc3, fc4, fc5 = st.columns(3)
            category  = fc3.selectbox("Category", all_cats)
            tx_type   = fc4.selectbox("Type", ["Purchase", "Payment / Credit"])
            amount    = fc5.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f")

            purchased_by = st.text_input("Purchased By (optional)", placeholder="Your name")

            submitted = st.form_submit_button("💾 Save Transaction", type="primary", use_container_width=True)

        if submitted:
            if not merchant.strip():
                st.error("Merchant / Payee is required.")
            elif amount <= 0:
                st.error("Amount must be greater than $0.")
            else:
                tx_dt = pd.Timestamp(tx_date)
                # Payments/credits stored as negative to match Apple Card convention
                stored_amount = -abs(amount) if "Payment" in tx_type else abs(amount)
                new_row = pd.DataFrame([{
                    "Transaction Date": str(tx_dt.date()),
                    "Clearing Date":    str(tx_dt.date()),
                    "Description":      "",
                    "Merchant":         merchant.strip(),
                    "Category":         category,
                    "Type":             "Payment" if "Payment" in tx_type else "Purchase",
                    "Amount (USD)":     stored_amount,
                    "Purchased By":     purchased_by.strip() or "Manual Entry",
                    "Month":            tx_dt.strftime("%B"),
                    "Year":             str(tx_dt.year),
                    "Upload Date":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Source":           "Manual",
}])
                with st.spinner("Saving…"):
                    save_transactions(sh, new_row)
                st.session_state["manual_save_success"] = (
                    f"✅ Saved: **{merchant.strip()}** — "
                    f"${abs(stored_amount):,.2f} on {tx_dt.strftime('%B %d, %Y')}"
                )
                st.rerun()

    if st.session_state.get("manual_save_success"):
        st.success(st.session_state.pop("manual_save_success"))

    # ── Tab 2: Manage / delete manual entries ─────────────────────────────────
    with tab_manage:
        df = load_transactions(sh)

        manual = df[df["Source"] == "Manual"].copy().sort_values(
            "Transaction Date", ascending=False
        ).reset_index(drop=True)

        if manual.empty:
            st.info("No manual entries yet — add one in the **Add Transaction** tab.")
        else:
            st.caption(
                f"**{len(manual)}** manual transaction(s). "
                "Click 🗑️ to delete individual entries."
            )

            # Column headers
            h0, h1, h2, h3, h4, h5 = st.columns([2, 3, 2, 2, 2, 1])
            h0.markdown("**Date**")
            h1.markdown("**Merchant**")
            h2.markdown("**Category**")
            h3.markdown("**Type**")
            h4.markdown("**Amount**")
            h5.markdown("**Del**")
            st.divider()

            for i, row in manual.iterrows():
                c0, c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 2, 2, 1])
                date_str = str(row["Transaction Date"])[:10]
                c0.write(date_str)
                c1.write(row["Merchant"])
                c2.write(row["Category"])
                c3.write(row["Type"])
                c4.write(f"${float(row['Amount (USD)']):,.2f}")
                if c5.button("🗑️", key=f"del_manual_{i}",
                             help=f"Delete {row['Merchant']} on {date_str}"):
                    with st.spinner("Deleting…"):
                        full_df = load_transactions(sh).copy()
                        # Match by fingerprint to avoid index drift
                        drop_mask = (
                            (full_df["Transaction Date"].astype(str).str[:10] == date_str) &
                            (full_df["Merchant"] == row["Merchant"]) &
                            (full_df["Amount (USD)"].astype(str) == str(row["Amount (USD)"])) &
                            (full_df["Source"] == "Manual")
                        )
                        first_match = full_df[drop_mask].index[:1]
                        if len(first_match):
                            full_df = full_df.drop(index=first_match)
                            save_all_transactions(sh, full_df)
                            st.success(f"Deleted **{row['Merchant']}** on {date_str}.")
                        else:
                            st.error("Could not find the row to delete — try refreshing.")
                    st.rerun()


# ─── PAGE: MANAGE DATA ────────────────────────────────────────────────────────
def page_manage(sh):
    st.title("⚙️ Manage Data")

    df = load_transactions(sh)

    st.subheader("Data Overview")
    if not df.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Rows", len(df))
        c2.metric("Months Loaded", df["Month"].nunique())
        c3.metric("Date Range",
                  f"{df['Transaction Date'].min().strftime('%b %Y')} – "
                  f"{df['Transaction Date'].max().strftime('%b %Y')}"
                  if not df["Transaction Date"].isna().all() else "—")

    st.divider()
    st.subheader("Delete a Month's Transactions")
    if df.empty:
        st.info("Nothing to delete.")
        return

    periods = [str(p) for p in available_periods(get_purchases(df))]
    del_period = st.selectbox("Select month to delete", periods)

    to_del_count = len(
        df[df["Transaction Date"].dt.to_period("M") == pd.Period(del_period)]
    )
    st.warning(f"This will permanently delete **{to_del_count}** transactions for {del_period}.")

    confirm = st.checkbox(f"Yes, delete all {del_period} transactions")
    if confirm and st.button("🗑️ Delete", type="primary"):
        with st.spinner("Deleting…"):
            ws = get_or_create_worksheet(sh, "transactions")
            keep = df[df["Transaction Date"].dt.to_period("M") != pd.Period(del_period)].copy()
            keep["Transaction Date"] = keep["Transaction Date"].astype(str)
            ws.clear()
            if not keep.empty:
                ws.update([TRANSACTION_HEADERS] + keep.values.tolist())
            else:
                ws.update([TRANSACTION_HEADERS])
            load_transactions.clear()
        st.success(f"Deleted {to_del_count} transactions for {del_period}.")
        st.rerun()


# ─── SIDEBAR & MAIN ───────────────────────────────────────────────────────────
def main():
    if not check_password():
        return

    sh = get_spreadsheet()

    with st.sidebar:
        st.markdown("## 💰 Budget Tracker")
        st.divider()
        page = st.radio(
            "Navigate",
            [
                "📊 Dashboard",
                "📤 Upload",
                "🧾 Transactions",
                "🎯 Budgets",
                "📈 Trends",
                "💡 Insights",
                "💵 Income",
                "✏️ Manual Entry",
                "🤖 Rules",
                "⚙️ Manage Data",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"🕐 {datetime.now().strftime('%I:%M %p')}")
        if st.button("🔄 Refresh", use_container_width=True):
            load_transactions.clear()
            load_budgets.clear()
            load_notes.clear()
            load_rules.clear()
            load_comments.clear()
            load_income.clear()
            st.rerun()
        if st.button("🔒 Log Out", use_container_width=True):
            st.session_state["authenticated"] = False
            st.rerun()

    pages = {
        "📊 Dashboard": page_dashboard,
        "📤 Upload": page_upload,
        "🧾 Transactions": page_transactions,
        "🎯 Budgets": page_budgets,
        "📈 Trends": page_trends,
        "💡 Insights": page_insights,
        "💵 Income": page_income,
        "✏️ Manual Entry": page_manual_entry,
        "🤖 Rules": page_rules,
        "⚙️ Manage Data": page_manage,
    }
    pages[page](sh)


if __name__ == "__main__":
    main()
