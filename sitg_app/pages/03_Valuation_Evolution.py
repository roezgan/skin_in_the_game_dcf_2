import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
from dcf.data import load_saved_df, fmp_get_historical_prices, check_fmp_api_key_configured
from auth_utils import check_auth, login_icon

st.set_page_config(page_title="Valuation Evolution", layout="wide")

# =====================================================
# AUTHENTICATION (OPTIONAL)
# =====================================================
check_auth()
login_icon()
st.title("📈 Valuation Evolution")
st.caption("Track how your valuations and market prices evolve over time")

# Load saved DCF data
saved_df = load_saved_df()
if saved_df.empty:
    st.info("No saved DCF calculations found. Go to the DCF page and save some forecasts first.")
    st.stop()

# Ensure Date column is datetime
if "Date" in saved_df.columns:
    saved_df["Date"] = pd.to_datetime(saved_df["Date"], errors="coerce")

# Get unique tickers
all_tickers = sorted(saved_df["Company"].dropna().unique().tolist())

if not all_tickers:
    st.info("No companies found in saved DCF calculations.")
    st.stop()

# Ticker selection
selected_tickers = st.multiselect(
    "Select ticker(s) to view",
    options=all_tickers,
    default=all_tickers,
    help="Select one or more tickers to compare their valuation evolution"
)

if not selected_tickers:
    st.warning("Please select at least one ticker.")
    st.stop()

# Scenario mapping (normalize scenario names)
scenario_map = {
    "Pessimistic": "Pessimistic",
    "Bear": "Pessimistic",
    "Conservative": "Pessimistic",
    "Base": "Base",
    "Optimistic": "Optimistic",
    "Bull": "Optimistic",
}

# Process each selected ticker
for ticker in selected_tickers:
    st.divider()
    st.subheader(f"📊 {ticker}")
    
    # Filter saved data for this ticker
    ticker_data = saved_df[saved_df["Company"] == ticker].copy()
    
    if ticker_data.empty:
        st.info(f"No saved forecasts found for {ticker}.")
        continue
    
    # Normalize scenarios
    ticker_data["ScenarioNormalized"] = (
        ticker_data["Scenario"].astype(str).str.title().map(scenario_map)
    )
    ticker_data = ticker_data.dropna(subset=["ScenarioNormalized", "Date", "Intrinsic Value ($/share)"])
    
    if ticker_data.empty:
        st.info(f"No valid forecasts with intrinsic values found for {ticker}.")
        continue
    
    # Get historical price data
    if not check_fmp_api_key_configured():
        st.warning(f"⚠️ Cannot fetch price history for {ticker} - FMP API key not configured.")
        price_df = pd.DataFrame(columns=["date", "close", "value", "type"])
    else:
        with st.spinner(f"Fetching price history for {ticker}..."):
            # Get price data for the date range of saved forecasts
            min_date = ticker_data["Date"].min()
            max_date = ticker_data["Date"].max()
            # Get price data from 30 days before first valuation to today
            days_back = max(365, (datetime.now() - min_date).days + 60)  # At least 1 year or more, with buffer
            
            price_df = fmp_get_historical_prices(ticker, days=days_back)
            
            # Filter price data to relevant date range (30 days before first valuation to today)
            if not price_df.empty and not ticker_data.empty:
                cutoff_date = min_date - timedelta(days=30)
                price_df = price_df[price_df["date"] >= cutoff_date].copy()
    
    # Get the most recent date from price data (to align valuation lines with price line)
    if not price_df.empty:
        latest_price_date = pd.to_datetime(price_df["date"].max())
    else:
        latest_price_date = datetime.now()
        st.warning(f"Could not fetch price history for {ticker}. Showing only valuation data.")
        price_df = pd.DataFrame(columns=["date", "close", "value", "type"])
    
    # Prepare valuation data by scenario
    valuation_data = []
    for scenario in ["Pessimistic", "Base", "Optimistic"]:
        scenario_data = ticker_data[ticker_data["ScenarioNormalized"] == scenario].copy()
        if not scenario_data.empty:
            # Sort by date
            scenario_data = scenario_data.sort_values("Date")
            
            for _, row in scenario_data.iterrows():
                valuation_data.append({
                    "date": row["Date"],
                    "scenario": scenario,
                    "value": row["Intrinsic Value ($/share)"],
                })
            
            # Add extension point: extend the last valuation to the latest price date
            last_valuation = scenario_data.iloc[-1]
            last_date = pd.to_datetime(last_valuation["Date"])
            last_value = last_valuation["Intrinsic Value ($/share)"]
            
            # Only extend if the last valuation is before the latest price date
            if last_date < latest_price_date:
                valuation_data.append({
                    "date": pd.Timestamp(latest_price_date),
                    "scenario": scenario,
                    "value": last_value,
                })
    
    if not valuation_data:
        st.info(f"No valuation data available for {ticker}.")
        continue
    
    valuation_df = pd.DataFrame(valuation_data)
    valuation_df = valuation_df.sort_values("date")
    
    # Keep a copy of original price data for display
    price_df_display = price_df.copy() if not price_df.empty else pd.DataFrame()
    
    # Prepare data for combined chart
    # Add a label column to price data
    if not price_df.empty:
        price_df["type"] = "Market Price"
        price_df = price_df.rename(columns={"close": "value"})
    
    # Add type column to valuation data
    valuation_df["type"] = valuation_df["scenario"] + " Valuation"
    
    # Combine all data
    chart_data_list = []
    if not price_df.empty:
        chart_data_list.append(price_df[["date", "value", "type"]])
    chart_data_list.append(valuation_df[["date", "value", "type"]])
    
    if chart_data_list:
        combined_data = pd.concat(chart_data_list, ignore_index=True)
        combined_data = combined_data.sort_values("date")
        
        # Define colors for each line
        color_scale = alt.Scale(
            domain=["Market Price", "Pessimistic Valuation", "Base Valuation", "Optimistic Valuation"],
            range=["#f97316", "#ef4444", "#3b82f6", "#10b981"]
        )
        
        # Separate price and valuation data
        price_data = combined_data[combined_data["type"] == "Market Price"]
        valuation_data = combined_data[combined_data["type"] != "Market Price"]
        
        # Create price chart (line only, no points)
        charts = []
        if not price_data.empty:
            price_chart = (
                alt.Chart(price_data)
                .mark_line(strokeWidth=2, opacity=0.8)
                .encode(
                    x=alt.X("date:T", title="Date", axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45)),
                    y=alt.Y("value:Q", title="Price / Valuation ($/share)", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "type:N",
                        title="Series",
                        scale=color_scale,
                        legend=alt.Legend(title="Series", orient="right")
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
                        alt.Tooltip("value:Q", title="Price", format="$.2f"),
                        alt.Tooltip("type:N", title="Type"),
                    ],
                )
            )
            charts.append(price_chart)
        
        # Create valuation chart (step function - horizontal lines until next valuation)
        if not valuation_data.empty:
            valuation_chart = (
                alt.Chart(valuation_data)
                .mark_line(point=True, strokeWidth=2.5, interpolate='step-after')
                .encode(
                    x=alt.X("date:T", title="Date", axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45)),
                    y=alt.Y("value:Q", title="Price / Valuation ($/share)", scale=alt.Scale(zero=False)),
                    color=alt.Color(
                        "type:N",
                        title="Series",
                        scale=color_scale,
                        legend=alt.Legend(title="Series", orient="right")
                    ),
                    tooltip=[
                        alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
                        alt.Tooltip("value:Q", title="Value", format="$.2f"),
                        alt.Tooltip("type:N", title="Type"),
                    ],
                )
            )
            charts.append(valuation_chart)
        
        # Combine charts
        if charts:
            if len(charts) > 1:
                chart = alt.layer(*charts)
            else:
                chart = charts[0]
            
            chart = chart.properties(
                width=800,
                height=400,
                title=f"{ticker} - Price & Valuation Evolution Over Time"
            ).resolve_scale(y="shared", color="shared").interactive()
        
        st.altair_chart(chart, use_container_width=True)
        
        # Show data table
        with st.expander(f"View data for {ticker}"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("**Valuation History**")
                display_valuation = valuation_df.copy()
                display_valuation["date"] = display_valuation["date"].dt.strftime("%Y-%m-%d")
                display_valuation["value"] = display_valuation["value"].apply(lambda x: f"${x:,.2f}")
                display_valuation = display_valuation.rename(columns={
                    "date": "Date",
                    "scenario": "Scenario",
                    "value": "Intrinsic Value ($/share)"
                })
                st.dataframe(display_valuation, use_container_width=True, hide_index=True)
            
            with col2:
                if not price_df_display.empty:
                    st.markdown("**Price History (Last 30 days)**")
                    display_price = price_df_display.tail(30).copy()
                    display_price["date"] = display_price["date"].dt.strftime("%Y-%m-%d")
                    display_price["close"] = display_price["close"].apply(lambda x: f"${x:,.2f}")
                    display_price = display_price[["date", "close"]].rename(columns={
                        "date": "Date",
                        "close": "Close Price ($/share)"
                    })
                    st.dataframe(display_price, use_container_width=True, hide_index=True)
                else:
                    st.info("Price data not available")

st.divider()
st.caption("💡 Tip: Use the date picker in 'Saved DCF Calculations' to set earlier forecast dates and see historical valuation evolution.")

