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
    "Category", "Type", "Amount (USD)", "Purchased By", "Month", "Year", "Upload Date",
]

BUDGET_HEADERS = ["Category", "Monthly Budget"]

NOTES_HEADERS = ["Period", "Note", "Updated"]

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


# ─── DATA SAVING ──────────────────────────────────────────────────────────────
def save_transactions(sh, df_new: pd.DataFrame):
    ws = get_or_create_worksheet(sh, "transactions")
    has_data = bool(ws.get_all_values())
    rows = [list(map(str, row)) for row in df_new.itertuples(index=False, name=None)]
    if not has_data:
        ws.update([TRANSACTION_HEADERS] + rows)
    else:
        ws.append_rows(rows)
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

    total_spent = month_df["Amount (USD)"].sum()
    total_budget = sum(budgets.get(c, 0) for c in DEFAULT_BUDGETS)
    remaining = total_budget - total_spent
    avg_tx = month_df["Amount (USD)"].mean() if len(month_df) else 0
    largest = month_df.nlargest(1, "Amount (USD)")

    # KPI row
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Total Spent", f"${total_spent:,.2f}",
                    f"${remaining:,.2f} {'remaining' if remaining >= 0 else 'over budget'}",
                    "#667eea" if remaining >= 0 else "#e53e3e")
    with c2:
        metric_card("Monthly Budget", f"${total_budget:,.2f}",
                    f"{len(DEFAULT_BUDGETS)} categories tracked", "#48bb78")
    with c3:
        metric_card("Transactions", str(len(month_df)),
                    f"Avg ${avg_tx:,.2f} each", "#ed8936")
    with c4:
        top_merchant = largest.iloc[0]["Merchant"] if len(largest) else "—"
        top_amt = largest.iloc[0]["Amount (USD)"] if len(largest) else 0
        metric_card("Largest Purchase", f"${top_amt:,.2f}", top_merchant, "#9f7aea")

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
    if st.button("Save Note", type="secondary"):
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

    purchases = df_new[df_new["Type"] == "Purchase"]
    payments = df_new[df_new["Type"] == "Payment"]
    months_in = df_new["Month"].dropna().unique().tolist()
    years_in = df_new["Year"].dropna().unique().tolist()

    st.success(
        f"✅ Parsed **{len(df_new)}** rows — "
        f"{', '.join(months_in)} {', '.join(set(years_in))}"
    )

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

    # Duplicate detection
    existing_df = load_transactions(sh)
    dupe_count = 0
    if not existing_df.empty:
        existing_keys = set(
            zip(
                existing_df["Transaction Date"].astype(str),
                existing_df["Merchant"].astype(str),
                existing_df["Amount (USD)"].astype(str),
            )
        )
        dupe_count = sum(
            1
            for k in zip(
                df_new["Transaction Date"].astype(str),
                df_new["Merchant"].astype(str),
                df_new["Amount (USD)"].astype(str),
            )
            if k in existing_keys
        )
        if dupe_count:
            st.warning(
                f"⚠️ {dupe_count} transaction(s) look like possible duplicates "
                "(same date + merchant + amount already exist). They'll still be imported; "
                "remove manually from the Transactions page if needed."
            )

    if st.button("💾 Import to Google Sheets", type="secondary", use_container_width=True):
        with st.spinner("Saving…"):
            df_save = df_new.copy()
            df_save["Transaction Date"] = df_save["Transaction Date"].astype(str)
            save_transactions(sh, df_save)
        st.success("Done! Head to the Dashboard to see your data.")
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
        st.caption("Edit the **Category** column directly. Click a cell to change it, then save.")

        display_cols = ["Transaction Date", "Merchant", "Category", "Amount (USD)", "Purchased By", "Type"]
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
            },
            key="tx_editor",
        )

        changed_mask = edited["Category"].values != edit_df["Category"].values
        n_changed = int(changed_mask.sum())

        sc1, sc2 = st.columns([3, 1])
        with sc1:
            if n_changed:
                st.info(f"**{n_changed}** row(s) have unsaved category changes.")
            else:
                st.caption("No unsaved changes.")
        with sc2:
            save_clicked = st.button(
                f"💾 Save {n_changed} change(s)" if n_changed else "💾 Save Changes",
                type="secondary",
                disabled=(n_changed == 0),
                use_container_width=True,
                key="save_inline",
            )

        if save_clicked and n_changed:
            with st.spinner("Saving to Google Sheets…"):
                # Use _orig_idx to map edited rows back to correct positions in full df
                full_df = df.copy()
                new_cats = edited.loc[changed_mask, "Category"].values
                orig_indices = base.loc[changed_mask, "_orig_idx"].values
                full_df.loc[orig_indices, "Category"] = new_cats
                save_all_transactions(sh, full_df)
            st.success(f"✅ Saved {n_changed} category update(s)!")
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
            st.success(
                f"✅ Re-categorized all **{tx_count}** '{sel_merchant}' transactions → **{sel_new_cat}**"
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

    if st.button("💾 Save Budgets", type="secondary", use_container_width=True):
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

    purchases = get_purchases(df)
    purchases = purchases.copy()
    purchases["Period"] = purchases["Transaction Date"].dt.to_period("M").astype(str)

    # Monthly total line
    monthly = (
        purchases.groupby("Period")["Amount (USD)"]
        .sum()
        .reset_index()
        .rename(columns={"Amount (USD)": "Total"})
        .sort_values("Period")
    )

    budgets = load_budgets(sh)
    total_budget = sum(v for k, v in budgets.items())
    monthly["Budget"] = total_budget

    st.subheader("Monthly Spending")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=monthly["Period"], y=monthly["Total"],
        name="Spent", marker_color="#667eea",
    ))
    fig.add_trace(go.Scatter(
        x=monthly["Period"], y=monthly["Budget"],
        name="Budget", line=dict(color="#e53e3e", width=2, dash="dash"),
    ))
    fig.update_layout(
        height=300, margin=dict(t=10, b=10, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Category heatmap
    st.subheader("Category Heatmap by Month")
    cat_monthly = purchases.groupby(["Period", "Category"])["Amount (USD)"].sum().reset_index()
    pivot = cat_monthly.pivot(index="Category", columns="Period", values="Amount (USD)").fillna(0)

    fig2 = px.imshow(
        pivot,
        color_continuous_scale="Blues",
        aspect="auto",
        text_auto="$.0f",
    )
    fig2.update_layout(height=380, margin=dict(t=10, b=10, l=0, r=0))
    st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # MoM comparison
    periods_avail = sorted(purchases["Period"].unique())
    if len(periods_avail) < 2:
        st.info("Upload at least 2 months of data to compare.")
        return

    st.subheader("Month-over-Month Comparison")
    cc1, cc2 = st.columns(2)
    p1 = cc1.selectbox("From", periods_avail, index=len(periods_avail) - 2, key="p1")
    p2 = cc2.selectbox("To", periods_avail, index=len(periods_avail) - 1, key="p2")

    s1 = purchases[purchases["Period"] == p1].groupby("Category")["Amount (USD)"].sum()
    s2 = purchases[purchases["Period"] == p2].groupby("Category")["Amount (USD)"].sum()
    cmp = pd.DataFrame({"Previous": s1, "Current": s2}).fillna(0).reset_index()
    cmp["Change"] = cmp["Current"] - cmp["Previous"]
    cmp["Change %"] = (
        cmp["Change"] / cmp["Previous"].replace(0, float("nan")) * 100
    ).round(1)
    cmp = cmp.sort_values("Change", ascending=False)

    fig3 = go.Figure()
    fig3.add_trace(go.Bar(x=cmp["Category"], y=cmp["Previous"],
                          name=p1, marker_color="rgba(100,126,234,0.45)"))
    fig3.add_trace(go.Bar(x=cmp["Category"], y=cmp["Current"],
                          name=p2, marker_color="#667eea"))
    fig3.update_layout(
        barmode="group", height=320,
        margin=dict(t=10, b=10, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.01),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig3, use_container_width=True)

    def color_change(val):
        if isinstance(val, float) and val > 0:
            return "color:#e53e3e"
        if isinstance(val, float) and val < 0:
            return "color:#38a169"
        return ""

    st.dataframe(
        cmp.style
        .format({"Previous": "${:,.2f}", "Current": "${:,.2f}",
                 "Change": "${:+,.2f}", "Change %": "{:+.1f}%"})
        .map(color_change, subset=["Change", "Change %"]),
        use_container_width=True,
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
    if confirm and st.button("🗑️ Delete", type="secondary"):
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
                "⚙️ Manage Data",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"🕐 {datetime.now().strftime('%I:%M %p')}")
        if st.button("🔄 Refresh", use_container_width=True, type="secondary"):
            load_transactions.clear()
            load_budgets.clear()
            load_notes.clear()
            st.rerun()
        if st.button("🔒 Log Out", use_container_width=True, type="secondary"):
            st.session_state["authenticated"] = False
            st.rerun()

    pages = {
        "📊 Dashboard": page_dashboard,
        "📤 Upload": page_upload,
        "🧾 Transactions": page_transactions,
        "🎯 Budgets": page_budgets,
        "📈 Trends": page_trends,
        "💡 Insights": page_insights,
        "⚙️ Manage Data": page_manage,
    }
    pages[page](sh)


if __name__ == "__main__":
    main()
