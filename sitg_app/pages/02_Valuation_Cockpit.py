import streamlit as st
import pandas as pd

from dcf.data import load_saved_df
from auth_utils import check_auth, login_icon

st.set_page_config(page_title="Valuation Cockpit", layout="wide")

# =====================================================
# AUTHENTICATION (OPTIONAL)
# =====================================================
check_auth()
login_icon()
st.title("🧭 Valuation Cockpit")
st.caption("Quick snapshot of your latest saved scenarios per company.")

saved_df = load_saved_df()
if saved_df.empty:
    st.info("Nog geen opgeslagen DCFs. Ga eerst naar de DCF-pagina en sla een scenario op.")
    st.stop()

saved_df["Date"] = pd.to_datetime(saved_df.get("Date"), errors="coerce")
saved_df = saved_df.sort_values("Date")

scenario_map = {
    "Pessimistic": "Pessimistic",
    "Bear": "Pessimistic",
    "Conservative": "Pessimistic",
    "Base": "Base",
    "Optimistic": "Optimistic",
    "Bull": "Optimistic",
}
saved_df["ScenarioNormalized"] = (
    saved_df["Scenario"].astype(str).str.title().map(scenario_map)
)
saved_df = saved_df.dropna(subset=["ScenarioNormalized"])

scenario_columns = ["Pessimistic", "Base", "Optimistic"]

intrinsic_latest = (
    saved_df.dropna(subset=["Intrinsic Value ($/share)"])
    .sort_values("Date")
    .drop_duplicates(["Company", "ScenarioNormalized"], keep="last")
    .pivot(index="Company", columns="ScenarioNormalized", values="Intrinsic Value ($/share)")
    .reindex(columns=scenario_columns)
)

upside_latest = (
    saved_df.dropna(subset=["Upside (%)"])
    .sort_values("Date")
    .drop_duplicates(["Company", "ScenarioNormalized"], keep="last")
    .pivot(index="Company", columns="ScenarioNormalized", values="Upside (%)")
    .reindex(columns=scenario_columns)
)

latest_market_price = (
    saved_df.dropna(subset=["Market Price ($/share)"])
    .sort_values("Date")
    .drop_duplicates("Company", keep="last")
    .set_index("Company")["Market Price ($/share)"]
)

all_companies = sorted(saved_df["Company"].dropna().unique().tolist())

selected_companies = st.multiselect(
    "Select companies",
    options=all_companies,
    default=all_companies,
)

if not selected_companies:
    st.warning("Selecteer minstens één ticker om de cockpit te tonen.")
    st.stop()

# Prepare data for absolute values table
iv_rows = []
for company in selected_companies:
    iv_series = (
        intrinsic_latest.loc[company]
        if company in intrinsic_latest.index
        else pd.Series([pd.NA] * len(scenario_columns), index=scenario_columns)
    )
    price = latest_market_price.get(company, pd.NA)

    row_iv = {"Company": company}
    for scen in scenario_columns:
        row_iv[scen] = iv_series.get(scen, pd.NA)
    row_iv["Actual price"] = price
    iv_rows.append(row_iv)

# Prepare data for percentage table
pct_rows = []
for company in selected_companies:
    pct_series = (
        upside_latest.loc[company]
        if company in upside_latest.index
        else pd.Series([pd.NA] * len(scenario_columns), index=scenario_columns)
    )

    row_pct = {"Company": company}
    for scen in scenario_columns:
        row_pct[scen] = pct_series.get(scen, pd.NA)
    pct_rows.append(row_pct)

if not iv_rows and not pct_rows:
    st.info("Geen scenario's voor de geselecteerde tickers.")
    st.stop()

def highlight_pct(row):
    """Highlight positive values in green and negative values in red."""
    styles = []
    for val in row:
        if pd.isna(val):
            styles.append("")
            continue
        if val >= 0:
            styles.append("background-color:#d1fae5;color:#065f46;font-weight:600;")
        else:
            styles.append("background-color:#fee2e2;color:#7f1d1d;font-weight:600;")
    return styles

# Create and display percentage table
if pct_rows:
    st.subheader("Upside / Downside (%)")
    pct_df = pd.DataFrame(pct_rows).set_index("Company")
    
    pct_styled = (
        pct_df.style
        .format(
            lambda v: "–" if pd.isna(v) else f"{v:+.2f}%",
            subset=scenario_columns,
        )
        .apply(highlight_pct, axis=1, subset=scenario_columns)
    )
    
    st.dataframe(pct_styled, use_container_width=True)

# Create and display absolute values table
if iv_rows:
    st.subheader("Intrinsic Value Prices ($/share)")
    iv_df = pd.DataFrame(iv_rows).set_index("Company")
    
    iv_styled = (
        iv_df.style
        .format(
            lambda v: "–" if pd.isna(v) else f"${v:,.0f}",
            subset=scenario_columns + ["Actual price"],
        )
    )
    
    st.dataframe(iv_styled, use_container_width=True)

