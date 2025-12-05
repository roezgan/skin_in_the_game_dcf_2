import numpy as np
import pandas as pd
import streamlit as st
from .data import (
    fmp_get_key_metrics, fmp_get_balance_sheet_quarterly,
    fmp_get_annual_income_statements, fmp_get_analyst_estimates,
    fmp_get_quarterly_income
)

# ======================================
# FINANCIAL LOGIC (discounting, terminal, tbv)
# ======================================

def discount_values(values, r):
    r /= 100
    return [v / ((1 + r) ** (i + 1)) for i, v in enumerate(values)]

def gordon_terminal(last_cf, wacc, g):
    r, g = wacc / 100, g / 100
    return float("inf") if r <= g else last_cf * (1 + g) / (r - g)

def get_tbv_from_fmp(ticker: str):
    """Get tangible book value from FMP balance sheet (latest quarter or annual).
    Calculated as: totalAssets - goodwillAndIntangibleAssets - totalLiabilities
    """
    try:
        balance_sheet = fmp_get_balance_sheet_quarterly(ticker)
        if not balance_sheet:
            return None, None
        
        total_assets = balance_sheet.get("totalAssets")
        goodwill_and_intangible = balance_sheet.get("goodwillAndIntangibleAssets") or 0
        total_liabilities = balance_sheet.get("totalLiabilities")
        
        if total_assets is not None and total_liabilities is not None:
            # Calculate TBV: totalAssets - goodwillAndIntangibleAssets - totalLiabilities
            tbv = float(total_assets) - float(goodwill_and_intangible) - float(total_liabilities)
            # Convert to millions
            tbv_usd = tbv / 1e6
            # Determine period type from balance sheet data
            period = balance_sheet.get("period", "").upper()
            period_label = "FMP (Q)" if period == "Q" else "FMP (FY)"
            return tbv_usd, period_label
    except Exception as e:
        # Debug: uncomment to see errors
        # st.write(f"TBV error for {ticker}: {e}")
        pass
    return None, None

def fmt_money(x):
    try:
        return f"{x:,.0f}"
    except Exception:
        return "—"

def fmt_pct(x):
    try:
        return f"{x*100:,.2f}%"
    except Exception:
        return "—"


# ======================================
# FORECAST LOGIC (session_state + editor)
# ======================================

# Forecast presets
FORECAST_PRESETS = {
    "High Growth": {
        "description": "15% → 8% growth, expanding margins",
        "growth_start": 0.15,
        "growth_end": 0.08,
        "margin_start_offset": 0.0,
        "margin_end_offset": 0.05,
    },
    "Moderate Growth": {
        "description": "10% → 5% growth, stable margins",
        "growth_start": 0.10,
        "growth_end": 0.05,
        "margin_start_offset": 0.0,
        "margin_end_offset": 0.0,
    },
    "Low Growth": {
        "description": "5% → 2% growth, declining margins",
        "growth_start": 0.05,
        "growth_end": 0.02,
        "margin_start_offset": 0.0,
        "margin_end_offset": -0.03,
    },
    "Recession": {
        "description": "0% → -5% growth, compressed margins",
        "growth_start": 0.0,
        "growth_end": -0.05,
        "margin_start_offset": 0.0,
        "margin_end_offset": -0.05,
    },
    "Stable": {
        "description": "0% growth, stable margins",
        "growth_start": 0.0,
        "growth_end": 0.0,
        "margin_start_offset": 0.0,
        "margin_end_offset": 0.0,
    },
    "Default": {
        "description": "12% → 5% growth, declining margins",
        "growth_start": 0.12,
        "growth_end": 0.05,
        "margin_start_offset": 0.0,
        "margin_end_offset": -0.03,
    },
}

# Revenue growth presets (growth only)
REVENUE_PRESETS = {
    "High Growth Revenue": {
        "description": "15% → 8% revenue growth",
        "growth_start": 0.15,
        "growth_end": 0.08,
    },
    "Moderate Growth Revenue": {
        "description": "10% → 5% revenue growth",
        "growth_start": 0.10,
        "growth_end": 0.05,
    },
    "Low Growth Revenue": {
        "description": "5% → 2% revenue growth",
        "growth_start": 0.05,
        "growth_end": 0.02,
    },
    "Stable Revenue": {
        "description": "0% revenue growth",
        "growth_start": 0.0,
        "growth_end": 0.0,
    },
    "Declining Revenue": {
        "description": "-2% → -5% revenue growth",
        "growth_start": -0.02,
        "growth_end": -0.05,
    },
}

# Margin % presets (margin only)
MARGIN_PRESETS = {
    "Expanding Margins": {
        "description": "+5pp margin expansion",
        "margin_start_offset": 0.0,
        "margin_end_offset": 0.05,
    },
    "Stable Margins": {
        "description": "Stable margins (no change)",
        "margin_start_offset": 0.0,
        "margin_end_offset": 0.0,
    },
    "Declining Margins": {
        "description": "-3pp margin compression",
        "margin_start_offset": 0.0,
        "margin_end_offset": -0.03,
    },
    "Strong Compression": {
        "description": "-5pp margin compression",
        "margin_start_offset": 0.0,
        "margin_end_offset": -0.05,
    },
    "Moderate Expansion": {
        "description": "+2pp margin expansion",
        "margin_start_offset": 0.0,
        "margin_end_offset": 0.02,
    },
}

def apply_preset(preset_name: str, base_margin: float, forecast_years: int):
    """Apply a preset forecast pattern to buffer_growth and buffer_margin."""
    if preset_name not in FORECAST_PRESETS:
        return
    
    preset = FORECAST_PRESETS[preset_name]
    
    # Generate growth pattern (linear interpolation)
    if forecast_years == 1:
        growth_series = [preset["growth_start"]]
    else:
        growth_series = np.linspace(
            preset["growth_start"],
            preset["growth_end"],
            forecast_years
        ).round(4).tolist()
    
    # Generate margin pattern (linear interpolation)
    margin_start = max(base_margin + preset["margin_start_offset"], 0.01)
    margin_end = max(base_margin + preset["margin_end_offset"], 0.01)
    
    if forecast_years == 1:
        margin_series = [margin_start]
    else:
        margin_series = np.linspace(
            margin_start,
            margin_end,
            forecast_years
        ).round(4).tolist()
    
    # Apply to buffer (working values)
    st.session_state.buffer_growth = growth_series
    st.session_state.buffer_margin = margin_series

def apply_revenue_preset(preset_name: str, forecast_years: int):
    """Apply a revenue growth preset to buffer_growth only (leaves margin unchanged)."""
    if preset_name not in REVENUE_PRESETS:
        return
    
    preset = REVENUE_PRESETS[preset_name]
    
    # Generate growth pattern (linear interpolation)
    if forecast_years == 1:
        growth_series = [preset["growth_start"]]
    else:
        growth_series = np.linspace(
            preset["growth_start"],
            preset["growth_end"],
            forecast_years
        ).round(4).tolist()
    
    # Apply only to growth buffer (leave margin unchanged)
    st.session_state.buffer_growth = growth_series

def apply_margin_preset(preset_name: str, base_margin: float, forecast_years: int):
    """Apply a margin preset to buffer_margin only (leaves revenue growth unchanged)."""
    if preset_name not in MARGIN_PRESETS:
        return
    
    preset = MARGIN_PRESETS[preset_name]
    
    # Generate margin pattern (linear interpolation)
    margin_start = max(base_margin + preset["margin_start_offset"], 0.01)
    margin_end = max(base_margin + preset["margin_end_offset"], 0.01)
    
    if forecast_years == 1:
        margin_series = [margin_start]
    else:
        margin_series = np.linspace(
            margin_start,
            margin_end,
            forecast_years
        ).round(4).tolist()
    
    # Apply only to margin buffer (leave growth unchanged)
    st.session_state.buffer_margin = margin_series

def calculate_avg_growth_last_5_years(ticker: str) -> float | None:
    """Calculate average CAGR over last 5 years from annual income statements."""
    try:
        statements = fmp_get_annual_income_statements(ticker, limit=6)
        if not statements or len(statements) < 6:
            return None
        
        revenues = []
        for stmt in statements[:6]:  # Last 6 years (need 6 to calculate 5-year CAGR)
            rev = stmt.get("revenue")
            if rev is None:
                return None
            revenues.append(float(rev))
        
        if len(revenues) < 6 or revenues[0] == 0 or revenues[-1] <= 0:
            return None
        
        # Calculate 5-year CAGR
        start_rev = revenues[-1]  # Oldest (6 years ago)
        end_rev = revenues[0]       # Most recent
        years = 5
        
        if start_rev <= 0:
            return None
        
        cagr = ((end_rev / start_rev) ** (1 / years)) - 1
        return round(cagr, 4)
    except Exception:
        return None

def calculate_growth_last_year(ticker: str) -> float | None:
    """Calculate YoY growth from last year's annual income statements."""
    try:
        statements = fmp_get_annual_income_statements(ticker, limit=2)
        if not statements or len(statements) < 2:
            return None
        
        prev_rev = statements[1].get("revenue")
        curr_rev = statements[0].get("revenue")
        
        if prev_rev is None or curr_rev is None or prev_rev == 0:
            return None
        
        growth = (float(curr_rev) - float(prev_rev)) / float(prev_rev)
        return round(growth, 4)
    except Exception:
        return None

def calculate_growth_last_quarter(ticker: str) -> float | None:
    """Calculate YoY growth from last quarter's quarterly income statements.
    Compares the latest quarter to the same quarter from the previous year (4 quarters ago)."""
    try:
        quarterly_df = fmp_get_quarterly_income(ticker, limit=5)
        if quarterly_df is None or quarterly_df.empty or len(quarterly_df) < 5:
            return None
        
        # Check if we have PeriodKey to properly identify YoY quarters
        if "PeriodKey" in quarterly_df.columns and quarterly_df["PeriodKey"].notna().any():
            # Use PeriodKey to find the quarter exactly 4 periods before the latest
            latest_period_key = quarterly_df.iloc[-1]["PeriodKey"]
            if pd.isna(latest_period_key):
                return None
            
            # Find the quarter that's 4 periods before (same quarter, previous year)
            target_period_key = latest_period_key - 4
            
            # Find the index of the target quarter
            target_idx = None
            for idx, row in quarterly_df.iterrows():
                if row["PeriodKey"] == target_period_key:
                    target_idx = idx
                    break
            
            if target_idx is None:
                return None
            
            curr_rev = pd.to_numeric(quarterly_df.iloc[-1]["Revenue"], errors="coerce")
            prev_rev = pd.to_numeric(quarterly_df.iloc[target_idx]["Revenue"], errors="coerce")
        else:
            # Fallback: assume quarters are in order and use index-based lookup
            if len(quarterly_df) < 5:
                return None
            
            curr_rev = pd.to_numeric(quarterly_df.iloc[-1]["Revenue"], errors="coerce")
            prev_rev = pd.to_numeric(quarterly_df.iloc[-5]["Revenue"], errors="coerce")
        
        if pd.isna(curr_rev) or pd.isna(prev_rev) or prev_rev == 0:
            return None
        
        # Calculate YoY growth
        yoy_growth = (float(curr_rev) - float(prev_rev)) / float(prev_rev)
        return round(yoy_growth, 4)
    except Exception:
        return None

def get_available_analyst_years(ticker: str) -> int:
    """Get the number of years for which analyst estimates are available.
    Returns the count of future years (current year and later) with valid estimates."""
    try:
        estimates_list = fmp_get_analyst_estimates(ticker, limit=10)
        if not estimates_list or len(estimates_list) == 0:
            return 0
        
        from datetime import datetime
        current_year = datetime.now().year
        
        # Filter estimates to only include current year and future years
        future_estimates = []
        for est in estimates_list:
            est_date = est.get("date", "")
            if est_date:
                try:
                    est_year = int(est_date[:4])
                    # Include estimates for current year and later (future years)
                    if est_year >= current_year:
                        # Check if the estimate has valid data (at least revenueAvg)
                        if est.get("revenueAvg") is not None:
                            future_estimates.append(est)
                except (ValueError, TypeError):
                    continue
        
        return len(future_estimates)
    except Exception:
        return 0

def get_analyst_revenue_growth_series(ticker: str, estimate_type: str, forecast_years: int, baseline_rev_millions: float | None = None) -> list[float] | None:
    """Get analyst revenue growth estimates year-by-year (low/mid/high).
    estimate_type should be 'low', 'mid', or 'high'.
    Returns a list of growth rates for each forecast year based on analyst estimates.
    Uses the most recent annual revenue (typically 2024) as baseline for Year 1 growth."""
    try:
        estimates_list = fmp_get_analyst_estimates(ticker, limit=10)
        if not estimates_list or len(estimates_list) == 0:
            return None
        
        # Get baseline revenue (most recent annual, typically 2024)
        # If not provided, fetch from FMP API
        if baseline_rev_millions is None:
            statements = fmp_get_annual_income_statements(ticker, limit=5)
            if not statements:
                return None
            
            # Use the most recent annual statement (first in list, which is most recent)
            # FMP API returns annual statements sorted by date descending
            baseline_rev_raw = statements[0].get("revenue")
            if baseline_rev_raw is None or baseline_rev_raw == 0:
                return None
            
            # FMP API returns revenue in dollars (not millions)
            # Convert to millions by dividing by 1e6
            # Example: 25,785,000,000 -> 25,785
            baseline_rev_millions = float(baseline_rev_raw) / 1e6
        
        if baseline_rev_millions is None or baseline_rev_millions == 0:
            return None
        
        # Determine which field to use based on estimate_type
        revenue_field = {
            "low": "revenueLow",
            "mid": "revenueAvg",
            "high": "revenueHigh"
        }.get(estimate_type)
        
        if revenue_field is None:
            return None
        
        # Get revenue estimates for each forecast year
        # Estimates are sorted earliest first (current year, next year, etc.)
        # Filter out any estimates that are for years before the current year
        # We only want current year and future estimates
        from datetime import datetime
        
        # Get current year to filter estimates
        current_year = datetime.now().year
        
        # Filter estimates to only include current year and future years
        # Skip any estimates for years before current year (those are historical, not forecasts)
        future_estimates = []
        for est in estimates_list:
            est_date = est.get("date", "")
            if est_date:
                try:
                    est_year = int(est_date[:4])
                    # Only include estimates for current year and later (future years)
                    if est_year >= current_year:
                        future_estimates.append(est)
                except (ValueError, TypeError):
                    continue
        
        # Sort by year to ensure correct order (current year first, then next year, etc.)
        future_estimates.sort(key=lambda x: int(x.get("date", "0")[:4]) if x.get("date") else 0)
        
        if len(future_estimates) == 0:
            return None
        
        growth_rates = []
        prev_rev = baseline_rev_millions  # Start with baseline (e.g., 2024 revenue)
        
        for year_idx in range(forecast_years):
            if year_idx >= len(future_estimates):
                # If we run out of estimates, use the last available growth rate
                if growth_rates:
                    growth_rates.append(growth_rates[-1])
                else:
                    return None
                continue
            
            estimate = future_estimates[year_idx]
            estimate_date = estimate.get("date", "")
            estimate_rev_raw = estimate.get(revenue_field)
            
            if estimate_rev_raw is None or estimate_rev_raw == 0:
                # If estimate is missing, use last growth rate or return None
                if growth_rates:
                    growth_rates.append(growth_rates[-1])
                else:
                    return None
                continue
            
            # FMP API returns revenue in dollars (not millions)
            # Convert to millions by dividing by 1e6
            # Example: 32695293647 -> 32,695.29
            estimate_rev_millions = float(estimate_rev_raw) / 1e6
            
            # Calculate growth rate from previous year (or baseline for Year 1)
            if prev_rev == 0:
                return None
            
            growth = (estimate_rev_millions - prev_rev) / prev_rev
            growth_rates.append(round(growth, 4))
            
            # Update previous revenue for next iteration
            prev_rev = estimate_rev_millions
        
        return growth_rates if growth_rates else None
    except Exception as e:
        # Debug: uncomment to see errors
        # st.write(f"Analyst revenue growth error for {ticker}: {e}")
        return None

def apply_calculated_revenue_growth(growth_rate: float | None, forecast_years: int):
    """Apply a calculated growth rate to all forecast years."""
    if growth_rate is None:
        return
    
    # Apply the same growth rate to all years
    growth_series = [growth_rate] * forecast_years
    st.session_state.buffer_growth = growth_series

def apply_analyst_revenue_growth(ticker: str, estimate_type: str, forecast_years: int, baseline_rev_millions: float | None = None):
    """Apply analyst revenue growth estimates year-by-year to forecast."""
    # Ensure buffer exists and has correct length
    if "buffer_growth" not in st.session_state or len(st.session_state.get("buffer_growth", [])) != forecast_years:
        # Initialize buffer if needed
        if "baseline_growth" in st.session_state and len(st.session_state.baseline_growth) == forecast_years:
            st.session_state.buffer_growth = st.session_state.baseline_growth[:]
        else:
            # Create default buffer
            st.session_state.buffer_growth = [0.12] * forecast_years
    
    growth_series = get_analyst_revenue_growth_series(ticker, estimate_type, forecast_years, baseline_rev_millions)
    if growth_series is not None and len(growth_series) == forecast_years:
        st.session_state.buffer_growth = growth_series.copy()

def calculate_avg_margin_last_5_years(ticker: str) -> float | None:
    """Calculate average net margin over last 5 years from annual income statements."""
    try:
        statements = fmp_get_annual_income_statements(ticker, limit=5)
        if not statements or len(statements) < 5:
            return None
        
        margins = []
        for stmt in statements[:5]:
            rev = stmt.get("revenue")
            ni = stmt.get("netIncome")
            if rev is None or ni is None or rev == 0:
                continue
            margin = float(ni) / float(rev)
            margins.append(margin)
        
        if not margins:
            return None
        
        avg_margin = sum(margins) / len(margins)
        return round(avg_margin, 4)
    except Exception:
        return None

def calculate_margin_last_year(ticker: str) -> float | None:
    """Calculate net margin from last year's annual income statement."""
    try:
        statements = fmp_get_annual_income_statements(ticker, limit=1)
        if not statements:
            return None
        
        rev = statements[0].get("revenue")
        ni = statements[0].get("netIncome")
        
        if rev is None or ni is None or rev == 0:
            return None
        
        margin = float(ni) / float(rev)
        return round(margin, 4)
    except Exception:
        return None

def calculate_margin_last_quarter(ticker: str) -> float | None:
    """Calculate net margin from last quarter's quarterly income statement."""
    try:
        quarterly_df = fmp_get_quarterly_income(ticker, limit=1)
        if quarterly_df is None or quarterly_df.empty:
            return None
        
        revenues = pd.to_numeric(quarterly_df["Revenue"], errors="coerce").tolist()
        net_incomes = pd.to_numeric(quarterly_df["Net Income"], errors="coerce").tolist()
        
        if len(revenues) == 0 or len(net_incomes) == 0:
            return None
        
        rev = revenues[0]
        ni = net_incomes[0]
        
        if pd.isna(rev) or pd.isna(ni) or rev == 0:
            return None
        
        margin = float(ni) / float(rev)
        return round(margin, 4)
    except Exception:
        return None

def get_analyst_margin_series(ticker: str, estimate_type: str, forecast_years: int) -> list[float] | None:
    """Get analyst margin estimates year-by-year (low/mid/high).
    estimate_type should be 'low', 'mid', or 'high'.
    Returns a list of margins for each forecast year based on analyst estimates.
    Margin is calculated as netIncome / revenue for each year."""
    try:
        estimates_list = fmp_get_analyst_estimates(ticker, limit=10)
        if not estimates_list or len(estimates_list) == 0:
            return None
        
        # Determine which fields to use based on estimate_type
        revenue_field = {
            "low": "revenueLow",
            "mid": "revenueAvg",
            "high": "revenueHigh"
        }.get(estimate_type)
        
        net_income_field = {
            "low": "netIncomeLow",
            "mid": "netIncomeAvg",
            "high": "netIncomeHigh"
        }.get(estimate_type)
        
        if revenue_field is None or net_income_field is None:
            return None
        
        # Filter estimates to only include current year and future years
        # Skip any estimates for years before current year (those are historical, not forecasts)
        from datetime import datetime
        
        # Get current year to filter estimates
        current_year = datetime.now().year
        
        # Filter estimates to only include current year and future years
        future_estimates = []
        for est in estimates_list:
            est_date = est.get("date", "")
            if est_date:
                try:
                    est_year = int(est_date[:4])
                    # Only include estimates for current year and later (future years)
                    if est_year >= current_year:
                        future_estimates.append(est)
                except (ValueError, TypeError):
                    continue
        
        # Sort by year to ensure correct order (current year first, then next year, etc.)
        future_estimates.sort(key=lambda x: int(x.get("date", "0")[:4]) if x.get("date") else 0)
        
        if len(future_estimates) == 0:
            return None
        
        # Get margin estimates for each forecast year
        margins = []
        
        for year_idx in range(forecast_years):
            if year_idx >= len(future_estimates):
                # If we run out of estimates, use the last available margin
                if margins:
                    margins.append(margins[-1])
                else:
                    return None
                continue
            
            estimate = future_estimates[year_idx]
            estimate_rev_raw = estimate.get(revenue_field)
            estimate_ni_raw = estimate.get(net_income_field)
            
            if estimate_rev_raw is None or estimate_ni_raw is None or estimate_rev_raw == 0:
                # If estimate is missing, use last margin or return None
                if margins:
                    margins.append(margins[-1])
                else:
                    return None
                continue
            
            # FMP API returns revenue and net income in dollars (not millions)
            # Convert to millions by dividing by 1e6
            # Example: 32695293647 -> 32,695.29 and 6260133553 -> 6,260.13
            estimate_rev_millions = float(estimate_rev_raw) / 1e6
            estimate_ni_millions = float(estimate_ni_raw) / 1e6
            
            # Calculate margin: netIncome / revenue
            # Example: 6,260.13 / 32,695.29 = 0.1914 = 19.14%
            margin = estimate_ni_millions / estimate_rev_millions
            margins.append(round(margin, 4))
        
        return margins if margins else None
    except Exception as e:
        # Debug: uncomment to see errors
        # st.write(f"Analyst margin error for {ticker}: {e}")
        return None

def apply_calculated_margin(margin_value: float | None, forecast_years: int):
    """Apply a calculated margin value to all forecast years."""
    if margin_value is None:
        return
    
    # Apply the same margin to all years
    margin_series = [margin_value] * forecast_years
    st.session_state.buffer_margin = margin_series.copy()

def apply_analyst_margin(ticker: str, estimate_type: str, forecast_years: int):
    """Apply analyst margin estimates year-by-year to forecast."""
    # Ensure buffer exists and has correct length
    if "buffer_margin" not in st.session_state or len(st.session_state.get("buffer_margin", [])) != forecast_years:
        # Initialize buffer if needed
        if "baseline_margin" in st.session_state and len(st.session_state.baseline_margin) == forecast_years:
            st.session_state.buffer_margin = st.session_state.baseline_margin[:]
        else:
            # Create default buffer
            base_margin = st.session_state.get("baseline_margin", [0.30])[0] if st.session_state.get("baseline_margin") else 0.30
            st.session_state.buffer_margin = [base_margin] * forecast_years
    
    margin_series = get_analyst_margin_series(ticker, estimate_type, forecast_years)
    if margin_series is not None and len(margin_series) == forecast_years:
        st.session_state.buffer_margin = margin_series.copy()

def init_defaults(base_margin: float, forecast_years: int):
    """Initieert standaard groeimarges en marges voor de forecast."""
    g = np.linspace(0.12, 0.05, forecast_years).round(4).tolist()
    m = np.linspace(base_margin, max(base_margin - 0.03, 0.05), forecast_years).round(4).tolist()
    st.session_state.baseline_growth = g[:]
    st.session_state.baseline_margin = m[:]
    st.session_state.buffer_growth = g[:]
    st.session_state.buffer_margin = m[:]

def ensure_series(base_margin: float, forecast_years: int):
    """Zorgt dat growth/margin series in session_state bestaan en correct zijn."""
    if "baseline_growth" not in st.session_state or len(st.session_state.baseline_growth) != forecast_years:
        init_defaults(base_margin, forecast_years)
    
    # Ensure buffer arrays are also resized when forecast_years changes
    if "buffer_growth" not in st.session_state or len(st.session_state.get("buffer_growth", [])) != forecast_years:
        if "baseline_growth" in st.session_state and len(st.session_state.baseline_growth) == forecast_years:
            st.session_state.buffer_growth = st.session_state.baseline_growth[:]
        else:
            g = np.linspace(0.12, 0.05, forecast_years).round(4).tolist()
            st.session_state.buffer_growth = g[:]
    
    if "buffer_margin" not in st.session_state or len(st.session_state.get("buffer_margin", [])) != forecast_years:
        if "baseline_margin" in st.session_state and len(st.session_state.baseline_margin) == forecast_years:
            st.session_state.buffer_margin = st.session_state.baseline_margin[:]
        else:
            m = np.linspace(base_margin, max(base_margin - 0.03, 0.05), forecast_years).round(4).tolist()
            st.session_state.buffer_margin = m[:]
    
    if "forecast_edit" not in st.session_state:
        st.session_state.forecast_edit = False

def toolbar_edit_reset(base_margin: float, forecast_years: int):
    """Bovenste toolbar voor edit/save/reset."""
    st.markdown(
        """
        <style>
            div[data-testid="column"]:first-of-type button {
                background-color:#f59e0b !important;
                color:#fff !important;
                font-weight:600 !important;
                border-radius:10px !important;
                border:none !important;
                box-shadow:0 4px 12px rgba(245,158,11,0.4) !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
    toolbar = st.columns([0.35, 0.12, 0.12, 0.41])

    # Column 0: Edit forecast (when not editing) or Save (when editing)
    with toolbar[0]:
        if not st.session_state.forecast_edit:
            if st.button(
                "✏️ Edit forecast",
                use_container_width=True,
                key="edit_forecast_btn",
                help="Adjust growth, margins, and forecast duration",
            ):
                # Initialize buffer with current baseline values when entering edit mode
                # Ensure buffers match the current forecast_years length
                if (len(st.session_state.baseline_growth) == forecast_years and 
                    len(st.session_state.baseline_margin) == forecast_years):
                    st.session_state.buffer_growth = st.session_state.baseline_growth[:]
                    st.session_state.buffer_margin = st.session_state.baseline_margin[:]
                else:
                    # If baseline arrays don't match, ensure_series will fix them, but we need to initialize buffers
                    # This should not happen if ensure_series is called before, but handle it just in case
                    g = np.linspace(0.12, 0.05, forecast_years).round(4).tolist()
                    m = np.linspace(base_margin, max(base_margin - 0.03, 0.05), forecast_years).round(4).tolist()
                    st.session_state.buffer_growth = g[:]
                    st.session_state.buffer_margin = m[:]
                st.session_state.forecast_edit = True
                st.rerun()
        else:
            if st.button("💾 Save", use_container_width=True, key="save_forecast_btn"):
                # Save buffer values to baseline and exit edit mode
                st.session_state.baseline_growth = st.session_state.buffer_growth[:]
                st.session_state.baseline_margin = st.session_state.buffer_margin[:]
                st.session_state.forecast_edit = False
                st.rerun()
    
    # Column 1: Cancel button (only when editing)
    with toolbar[1]:
        if st.session_state.forecast_edit:
            if st.button("↩️ Cancel", use_container_width=True, key="cancel_forecast_btn"):
                # Restore buffer from baseline and exit edit mode (discard unsaved changes)
                st.session_state.buffer_growth = st.session_state.baseline_growth[:]
                st.session_state.buffer_margin = st.session_state.baseline_margin[:]
                st.session_state.forecast_edit = False
                st.rerun()
    
    # Column 2: Reset button (only when editing)
    with toolbar[2]:
        if st.session_state.forecast_edit:
            if st.button("↺ Reset", use_container_width=True, key="reset_forecast_btn"):
                # Reset buffer to current baseline values (not to defaults)
                st.session_state.buffer_growth = st.session_state.baseline_growth[:]
                st.session_state.buffer_margin = st.session_state.baseline_margin[:]
                st.rerun()

def quick_adjust(forecast_years: int):
    """UI voor snelle aanpassing van CAGR."""
    st.markdown("##### 🔢 Quick Adjust (apply to all years)")
    colx, coly = st.columns(2)
    with colx:
        cagr_rev = st.number_input("Revenue Growth CAGR (%)",
                                   value=round(np.mean(st.session_state.buffer_growth)*100, 2))
    with coly:
        cagr_margin = st.number_input("Margin CAGR (%)",
                                      value=round(np.mean(st.session_state.buffer_margin)*100, 2))
    if st.button("Apply CAGR to All Years"):
        st.session_state.buffer_growth = [cagr_rev/100.0]*forecast_years
        st.session_state.buffer_margin = [cagr_margin/100.0]*forecast_years

def editor_table(forecast_years: int):
    """Data editor voor jaar-op-jaar growth en marges."""
    year_cols = [f"Year {i+1}" for i in range(forecast_years)]
    edit_df = pd.DataFrame({
        "Metric": ["Revenue Growth (%)", "Margin (%)"],
        **{year_cols[i]: [st.session_state.buffer_growth[i]*100.0,
                          st.session_state.buffer_margin[i]*100.0] for i in range(forecast_years)},
    }).set_index("Metric")
    edited = st.data_editor(edit_df, use_container_width=True, hide_index=False, num_rows="fixed")
    new_g = [float(pd.to_numeric(edited.iloc[0, i], errors="coerce") or 0.0)/100.0 for i in range(len(year_cols))]
    new_m = [float(pd.to_numeric(edited.iloc[1, i], errors="coerce") or 0.0)/100.0 for i in range(len(year_cols))]
    st.session_state.buffer_growth = new_g
    st.session_state.buffer_margin = new_m

def render_preset_selector(base_margin: float, forecast_years: int, ticker: str, baseline_rev_millions: float | None = None):
    """Render preset selector UI (only shown in edit mode)."""
    # Always read the current forecast_years from session state to ensure we use the latest value
    # This fixes the issue where buttons don't work after changing forecast years
    current_forecast_years = int(st.session_state.get("dcf_forecast_years", forecast_years))
    
    st.markdown("##### 📊 Presets")
    
    # FMP-based revenue growth buttons
    st.markdown("**FMP Data-Based Revenue Growth**")
    fmp_buttons = [
        ("5-Year CAGR", "avg_5y", calculate_avg_growth_last_5_years, True),
        ("Growth Last Year", "yoy", calculate_growth_last_year, True),
        ("Growth Last Quarter (YoY)", "qoq", calculate_growth_last_quarter, True),
        ("Analyst Expectation Low", "analyst_low", "low", False),
        ("Analyst Expectation Mid", "analyst_mid", "mid", False),
        ("Analyst Expectation High", "analyst_high", "high", False),
    ]
    
    fmp_cols = st.columns(len(fmp_buttons))
    for idx, (label, key_suffix, calc_func_or_type, is_single_rate) in enumerate(fmp_buttons):
        with fmp_cols[idx]:
            if is_single_rate:
                # For single growth rate functions
                growth_rate = calc_func_or_type(ticker) if ticker else None
                help_text = f"{label}"
                if growth_rate is not None:
                    help_text += f": {growth_rate*100:.1f}%"
                else:
                    help_text += ": Data unavailable"
                
                if st.button(
                    label,
                    use_container_width=True,
                    key=f"fmp_revenue_{key_suffix}",
                    help=help_text,
                    disabled=(growth_rate is None),
                ):
                    if growth_rate is not None:
                        # Preserve current forecast_years before applying
                        preserved_forecast_years = int(st.session_state.get("dcf_forecast_years", current_forecast_years))
                        apply_calculated_revenue_growth(growth_rate, preserved_forecast_years)
                        # Ensure forecast_years is preserved after rerun
                        st.session_state.dcf_forecast_years = preserved_forecast_years
                        st.rerun()
            else:
                # For analyst estimates (year-by-year)
                estimate_type = calc_func_or_type
                growth_series = get_analyst_revenue_growth_series(ticker, estimate_type, current_forecast_years, baseline_rev_millions) if ticker else None
                help_text = f"{label}"
                if growth_series is not None and len(growth_series) > 0:
                    avg_growth = sum(growth_series) / len(growth_series)
                    help_text += f": {len(growth_series)} years, avg {avg_growth*100:.1f}%"
                else:
                    help_text += ": Data unavailable"
                
                if st.button(
                    label,
                    use_container_width=True,
                    key=f"fmp_revenue_{key_suffix}",
                    help=help_text,
                    disabled=(growth_series is None),
                ):
                    if growth_series is not None:
                        # Preserve current forecast_years before applying
                        preserved_forecast_years = int(st.session_state.get("dcf_forecast_years", current_forecast_years))
                        apply_analyst_revenue_growth(ticker, estimate_type, preserved_forecast_years, baseline_rev_millions)
                        # Ensure forecast_years is preserved after rerun
                        st.session_state.dcf_forecast_years = preserved_forecast_years
                        st.rerun()
    
    st.markdown("---")
    
    # FMP-based margin buttons
    st.markdown("**FMP Data-Based Margins**")
    fmp_margin_buttons = [
        ("Avg. Margin Last 5 Years", "avg_5y", calculate_avg_margin_last_5_years, True),
        ("Margin Last Year", "yoy", calculate_margin_last_year, True),
        ("Margin Last Quarter", "qoq", calculate_margin_last_quarter, True),
        ("Analyst Expectation Low", "analyst_low", "low", False),
        ("Analyst Expectation Mid", "analyst_mid", "mid", False),
        ("Analyst Expectation High", "analyst_high", "high", False),
    ]
    
    fmp_margin_cols = st.columns(len(fmp_margin_buttons))
    for idx, (label, key_suffix, calc_func_or_type, is_single_value) in enumerate(fmp_margin_buttons):
        with fmp_margin_cols[idx]:
            if is_single_value:
                # For single margin value functions
                margin_value = calc_func_or_type(ticker) if ticker else None
                help_text = f"{label}"
                if margin_value is not None:
                    help_text += f": {margin_value*100:.1f}%"
                else:
                    help_text += ": Data unavailable"
                
                if st.button(
                    label,
                    use_container_width=True,
                    key=f"fmp_margin_{key_suffix}",
                    help=help_text,
                    disabled=(margin_value is None),
                ):
                    if margin_value is not None:
                        # Preserve current forecast_years before applying
                        preserved_forecast_years = int(st.session_state.get("dcf_forecast_years", current_forecast_years))
                        apply_calculated_margin(margin_value, preserved_forecast_years)
                        # Ensure forecast_years is preserved after rerun
                        st.session_state.dcf_forecast_years = preserved_forecast_years
                        st.rerun()
            else:
                # For analyst estimates (year-by-year)
                estimate_type = calc_func_or_type
                margin_series = get_analyst_margin_series(ticker, estimate_type, current_forecast_years) if ticker else None
                help_text = f"{label}"
                if margin_series is not None and len(margin_series) > 0:
                    avg_margin = sum(margin_series) / len(margin_series)
                    help_text += f": {len(margin_series)} years, avg {avg_margin*100:.1f}%"
                else:
                    help_text += ": Data unavailable"
                
                if st.button(
                    label,
                    use_container_width=True,
                    key=f"fmp_margin_{key_suffix}",
                    help=help_text,
                    disabled=(margin_series is None),
                ):
                    if margin_series is not None:
                        # Preserve current forecast_years before applying
                        preserved_forecast_years = int(st.session_state.get("dcf_forecast_years", current_forecast_years))
                        apply_analyst_margin(ticker, estimate_type, preserved_forecast_years)
                        # Ensure forecast_years is preserved after rerun
                        st.session_state.dcf_forecast_years = preserved_forecast_years
                        st.rerun()

def get_series(is_editing: bool):
    """Geeft de juiste growth/margin arrays terug."""
    growth_series = st.session_state.buffer_growth if is_editing else st.session_state.baseline_growth
    margin_series = st.session_state.buffer_margin if is_editing else st.session_state.baseline_margin
    return growth_series, margin_series
