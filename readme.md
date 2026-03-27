# 💰 Apple Card Budget Tracker

A personal budgeting app for Apple Card, built with Streamlit and backed by Google Sheets. Runs on Streamlit Community Cloud with password protection.

---

## Features

| Page | What it does |
|---|---|
| **Dashboard** | Monthly KPIs, spending vs. budget bars, category donut, top merchants, daily spend chart, monthly notes |
| **Upload** | Parse & import Apple Card CSV exports; duplicate detection |
| **Transactions** | Search, filter by month/category/merchant/amount; CSV export |
| **Budgets** | Set monthly targets per category, saved to Google Sheets |
| **Trends** | Month-over-month line chart, category heatmap, MoM comparison table |
| **Insights** | Top merchants, day-of-week patterns, budget summary, recurring charge detection |
| **Manage Data** | Delete a month's transactions; data overview |

---

## Setup — Step by Step

### 1. Create the Google Sheet

1. Go to [sheets.google.com](https://sheets.google.com) and create a new blank spreadsheet
2. Name it something like **Budget Tracker**
3. Copy the **Spreadsheet ID** from the URL:
   ```
   https://docs.google.com/spreadsheets/d/SPREADSHEET_ID_IS_HERE/edit
   ```
   You'll need this in Step 3.

The app will **automatically create** three tabs on first run:
- `transactions` — all imported Apple Card rows
- `budgets` — your category budget targets
- `notes` — monthly context notes

> You do **not** need to create the tabs manually.

---

### 2. Create a Google Cloud Service Account

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Google Sheets API**:
   - Navigation → APIs & Services → Library → search "Google Sheets API" → Enable
4. Create a service account:
   - Navigation → IAM & Admin → Service Accounts → **+ Create Service Account**
   - Name it anything (e.g. `budget-tracker`)
   - Skip role assignment — click Done
5. Open the new service account → **Keys** tab → **Add Key** → **Create new key** → **JSON**
6. Download the JSON file — keep it safe, you'll paste it into secrets

7. **Share your Google Sheet with the service account:**
   - Open the JSON file and copy the `client_email` value (looks like `budget-tracker@your-project.iam.gserviceaccount.com`)
   - Open your Google Sheet → Share → paste that email → set to **Editor** → Share

---

### 3. Set Your Password Hash

Generate a SHA-256 hash of your chosen password. Run this in a terminal:

```python
python3 -c "import hashlib; print(hashlib.sha256('yourpassword'.encode()).hexdigest())"
```

Copy the output — that's your `password_hash`.

---

### 4. Configure Secrets

**For local development**, create `.streamlit/secrets.toml` (copy from `.streamlit/secrets.toml.template`):

```toml
[app]
password_hash = "paste-your-sha256-hash-here"

[gcp]
spreadsheet_id = "paste-your-spreadsheet-id-here"
service_account_json = """
{ ... paste entire JSON key file content here ... }
"""
```

**For Streamlit Community Cloud**, paste the same content into:
- App Settings → **Secrets** → paste the entire TOML block

---

### 5. Deploy to Streamlit Community Cloud

1. Push this project to a **GitHub repository** (public or private)
   - Make sure `.gitignore` is committed so `secrets.toml` is never pushed
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Click **New app** → connect your GitHub repo
4. Set **Main file path** to `app.py`
5. Open **Advanced settings** → paste your secrets into the Secrets box
6. Click **Deploy**

---

## Exporting from Apple Card

1. Open **Wallet** on iPhone → tap Apple Card
2. Tap **···** (top right) → **Statements**
3. Select the month → **Export Transactions** → **CSV**

The app expects these columns (standard Apple Card export format):

| Column | Example |
|---|---|
| Transaction Date | 02/25/2026 |
| Clearing Date | 02/27/2026 |
| Description | SHAWS.COM #3669 4 PLAISTOW... |
| Merchant | Shaws.Com #3669 |
| Category | Grocery |
| Type | Purchase / Payment |
| Amount (USD) | 102.94 |
| Purchased By | Your Name |

---

## Google Sheet Structure

The app manages three tabs automatically:

### `transactions`
All imported rows. Do not edit column headers. You can add notes in unused columns if you want.

### `budgets`
Two columns: `Category` and `Monthly Budget`. Edited via the Budgets page.

### `notes`
Three columns: `Period` (e.g. `2026-02`), `Note`, `Updated`. Edited from the Dashboard.

---

## Local Development

```bash
# Clone repo
git clone https://github.com/yourname/budget-tracker
cd budget-tracker

# Install dependencies
pip install -r requirements.txt

# Create secrets file
cp .streamlit/secrets.toml.template .streamlit/secrets.toml
# Edit secrets.toml with your values

# Run
streamlit run app.py
```

---

## Tech Stack

- [Streamlit](https://streamlit.io) — UI and hosting
- [gspread](https://docs.gspread.org) — Google Sheets read/write
- [Plotly](https://plotly.com/python/) — Interactive charts
- [Pandas](https://pandas.pydata.org) — Data processing
- [Google Auth](https://google-auth.readthedocs.io) — Service account credentials
