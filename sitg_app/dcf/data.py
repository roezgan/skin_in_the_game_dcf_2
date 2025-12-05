import streamlit as st
import pandas as pd
import os
from pathlib import Path
import requests
from urllib.parse import quote_plus
from dotenv import load_dotenv
import json
from datetime import datetime

# ======================
# Paths & config
# ======================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
os.makedirs(DATA_DIR, exist_ok=True)

SAVED_FILE = DATA_DIR / "saved_dcfs.csv"

load_dotenv()
LOCAL_FILE = os.getenv("LOCAL_FINANCIALS_FILE", str(DATA_DIR / "FMP_all_tickers_financials.xlsx"))


def _resolve_fmp_key() -> str | None:
    """Resolve FMP API key from environment variables or Streamlit secrets.
    
    Returns:
        API key string if found, None otherwise.
    """
    env_key = os.getenv("FMP_API_KEY", "")
    if env_key:
        return env_key
    try:
        secrets_key = st.secrets.get("FMP_API_KEY") or st.secrets.get("fmp_api_key")
        if secrets_key:
            return secrets_key
        nested = st.secrets.get("fmp", {})
        if isinstance(nested, dict):
            api_key = nested.get("api_key", "")
            if api_key:
                return api_key
    except Exception:
        pass
    return None


FMP_API_KEY = _resolve_fmp_key()


def check_fmp_api_key_configured() -> bool:
    """Check if FMP API key is configured and show error message if not.
    
    Returns:
        True if API key is configured, False otherwise.
    """
    if not FMP_API_KEY:
        st.error(
            "⚠️ **FMP API Key Not Configured**\n\n"
            "The Financial Modeling Prep API key is required for this feature. "
            "Please configure it using one of the following methods:\n\n"
            "1. **Environment Variable**: Set `FMP_API_KEY` in your environment\n"
            "2. **Streamlit Secrets**: Add to `.streamlit/secrets.toml`:\n"
            "   ```toml\n"
            "   FMP_API_KEY = \"your-api-key-here\"\n"
            "   ```\n"
            "   Or:\n"
            "   ```toml\n"
            "   [fmp]\n"
            "   api_key = \"your-api-key-here\"\n"
            "   ```\n\n"
            "Get your API key from: https://site.financialmodelingprep.com/developer/docs/"
        )
        return False
    return True


# ======================
# Data loaders
# ======================
@st.cache_data
def load_local_financials(ticker: str):
    # Probeer eerst parquet (kleiner, sneller, staat in git)
    parquet_file = str(DATA_DIR / "FMP_all_tickers_financials.parquet")
    if os.path.exists(parquet_file):
        df = pd.read_parquet(parquet_file)
        df = df[df["Ticker"].str.upper() == ticker.upper()].copy()
        for col in ["TTM", "2024", "2023", "2022", "2021", "2020"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df if not df.empty else None
    
    # Fallback naar Excel (als het bestaat)
    if not os.path.exists(LOCAL_FILE):
        st.error(f"File not found: {LOCAL_FILE}")
        return None
    df = pd.read_excel(LOCAL_FILE)
    df = df[df["Ticker"].str.upper() == ticker.upper()].copy()
    for col in ["TTM", "2024", "2023", "2022", "2021", "2020"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df if not df.empty else None

@st.cache_data(ttl=3600)
def fmp_get_profile(ticker: str):
    if not FMP_API_KEY:
        return {}
    url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={FMP_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            row = data[0]
            return {
                "marketCap": row.get("mktCap"),
                "totalDebt": row.get("totalDebt"),
                "totalCash": row.get("cash"),
                "sharesOutstanding": row.get("sharesOutstanding"),
                "bookValue": row.get("bookValue"),
                "price": row.get("price"),
            }
    except Exception:
        return {}
    return {}

@st.cache_data(ttl=3600)
def get_balance_from_fmp(info: dict, ticker: str):
    """Haalt debt, cash en shares op — met fallback op /shares-float."""
    try:
        debt = (info.get("totalDebt") or 0) / 1e6
        cash = (info.get("totalCash") or 0) / 1e6
        shares = None

        # Probeer nieuw endpoint
        if FMP_API_KEY:
            url = f"https://financialmodelingprep.com/stable/shares-float?symbol={ticker}&apikey={FMP_API_KEY}"
            try:
                r = requests.get(url, timeout=8)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    shares = data[0].get("outstandingShares")
            except Exception:
                shares = None

        # Fallback op profile
        if not shares:
            shares = info.get("sharesOutstanding")

        shares = float(shares or 0)
        return debt, cash, shares
    except Exception:
        return 0.0, 0.0, 0.0


@st.cache_data(ttl=1800)
def fmp_get_quarterly_income(ticker: str, limit: int = 24) -> pd.DataFrame:
    """Fetch recent quarterly revenue & net income (in millions) from FMP."""
    if not FMP_API_KEY:
        return pd.DataFrame()

    endpoints = [
        (
            "https://financialmodelingprep.com/stable/income-statement"
            f"?symbol={ticker}&period=quarter&limit={limit}&apikey={FMP_API_KEY}"
        ),
        (
            f"https://financialmodelingprep.com/api/v3/income-statement/"
            f"{ticker}?period=quarter&limit={limit}&apikey={FMP_API_KEY}"
        ),
    ]

    data = None
    for url in endpoints:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            payload = r.json()
        except Exception:
            continue
        if isinstance(payload, list) and payload:
            data = payload
            break

    if not data:
        return pd.DataFrame()

    rows = []
    for entry in data:
        period_code = str(entry.get("period") or "").upper()
        date = entry.get("date")
        revenue = entry.get("revenue")
        net_income = entry.get("netIncome")
        if revenue is None or net_income is None:
            continue

        label = date or period_code
        period_key = None
        try:
            if date:
                period_key = pd.Period(date, freq="Q")
                label = f"{period_key.year} Q{period_key.quarter}"
        except Exception:
            pass

        rows.append(
            {
                "Period": label,
                "Revenue": revenue / 1e6,
                "Net Income": net_income / 1e6,
                "PeriodKey": period_key,
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if df["PeriodKey"].notna().any():
        df = df.sort_values("PeriodKey").reset_index(drop=True)
    else:
        df = df.iloc[::-1].reset_index(drop=True)
    return df


@st.cache_data(ttl=3600)
def fmp_get_product_segmentation(ticker: str) -> pd.DataFrame:
    """Fetch revenue by product segment (annual) from FMP stable endpoint."""
    if not FMP_API_KEY:
        return pd.DataFrame()
    url = (
        "https://financialmodelingprep.com/stable/revenue-product-segmentation"
        f"?symbol={ticker}&apikey={FMP_API_KEY}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        rows = []
        if isinstance(data, list):
            for entry in data:
                fiscal_year = entry.get("fiscalYear")
                period = entry.get("period")
                date = entry.get("date")
                segments = entry.get("data") or {}
                if not isinstance(segments, dict):
                    continue
                for name, value in segments.items():
                    if value is None:
                        continue
                    rows.append(
                        {
                            "Fiscal Year": fiscal_year,
                            "Period": period,
                            "Date": date,
                            "Segment": name,
                            "Revenue ($M)": (value or 0) / 1e6,
                        }
                    )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df.sort_values(
            by=["Fiscal Year", "Segment"], ascending=[False, True], na_position="last"
        ).reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def fmp_search_symbols(query: str, limit: int = 8) -> list[dict]:
    """Search tickers by company name or symbol via FMP."""
    if not query or not FMP_API_KEY:
        return []
    url = (
        "https://financialmodelingprep.com/api/v3/search"
        f"?query={quote_plus(query)}&limit={limit}&apikey={FMP_API_KEY}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []

@st.cache_data(ttl=3600)
def fmp_get_key_metrics(ticker: str) -> dict:
    """Fetch key metrics from FMP stable endpoint, including tangibleAssetValue."""
    if not FMP_API_KEY:
        return {}
    url = (
        "https://financialmodelingprep.com/stable/key-metrics"
        f"?symbol={ticker}&apikey={FMP_API_KEY}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            # Return the most recent (first) entry
            return data[0]
    except Exception:
        return {}
    return {}

@st.cache_data(ttl=3600)
def fmp_get_balance_sheet_quarterly(ticker: str) -> dict:
    """Fetch balance sheet from FMP stable endpoint, tries quarterly first, then annual.
    Returns most recent period (quarter preferred, annual as fallback)."""
    if not FMP_API_KEY:
        return {}
    
    # Try quarterly first
    url_quarterly = (
        "https://financialmodelingprep.com/stable/balance-sheet-statement"
        f"?symbol={ticker}&period=quarter&apikey={FMP_API_KEY}"
    )
    try:
        r = requests.get(url_quarterly, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            # Return the most recent (first) entry - latest quarter
            return data[0]
    except Exception:
        pass
    
    # Fallback to annual if quarterly fails
    url_annual = (
        "https://financialmodelingprep.com/stable/balance-sheet-statement"
        f"?symbol={ticker}&apikey={FMP_API_KEY}"
    )
    try:
        r = requests.get(url_annual, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) > 0:
            # Return the most recent (first) entry - latest annual
            return data[0]
    except Exception:
        pass
    
    return {}

@st.cache_data(ttl=3600)
def fmp_get_annual_income_statements(ticker: str, limit: int = 6) -> list[dict]:
    """Fetch annual income statements from FMP."""
    if not FMP_API_KEY:
        return []
    
    endpoints = [
        (
            "https://financialmodelingprep.com/stable/income-statement"
            f"?symbol={ticker}&period=annual&limit={limit}&apikey={FMP_API_KEY}"
        ),
        (
            f"https://financialmodelingprep.com/api/v3/income-statement/"
            f"{ticker}?period=annual&limit={limit}&apikey={FMP_API_KEY}"
        ),
    ]
    
    for url in endpoints:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                return data
        except Exception:
            continue
    
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def fmp_get_analyst_estimates(ticker: str, limit: int = 10) -> list[dict]:
    """Fetch analyst estimates from FMP. Returns list of estimates for multiple years.
    Returns estimates sorted by date (earliest/upcoming first, e.g., 2025, 2026, 2027...)."""
    if not FMP_API_KEY:
        return []
    
    endpoints = [
        (
            "https://financialmodelingprep.com/stable/analyst-estimates"
            f"?symbol={ticker}&period=annual&page=0&limit={limit}&apikey={FMP_API_KEY}"
        ),
        (
            f"https://financialmodelingprep.com/api/v3/analyst-estimates/"
            f"{ticker}?period=annual&limit={limit}&apikey={FMP_API_KEY}"
        ),
    ]
    
    for url in endpoints:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                # FMP API returns estimates sorted by date descending (furthest future first)
                # Sort by date ascending to get earliest/upcoming first (2025, 2026, 2027...)
                # This ensures we use the correct year for each forecast period
                sorted_data = sorted(data, key=lambda x: x.get("date", ""))
                return sorted_data
        except Exception:
            continue
    
    return []

# ======================
# Supabase save/load (for logged-in users)
# ======================
def _get_supabase_client():
    """Get Supabase client, returns None if not available or user not logged in."""
    try:
        from auth_utils import init_supabase, check_auth
        # Check if user is logged in
        if not st.session_state.get("user"):
            return None
        return init_supabase()
    except Exception:
        return None


def _get_user_id():
    """Get current user ID, returns None if not logged in."""
    user = st.session_state.get("user")
    if user and isinstance(user, dict):
        return user.get("id")
    return None


def _payload_to_db_record(payload: dict, user_id: str) -> dict:
    """Convert CSV payload format to database record format."""
    # Parse exit value
    exit_label = payload.get("Exit Value", "")
    exit_multiple = None
    terminal_growth_rate = None
    
    if "× PE" in exit_label or "x PE" in exit_label:
        try:
            exit_multiple = float(exit_label.split("×")[0].split("x")[0].strip())
        except (ValueError, IndexError):
            pass
    elif "% perp" in exit_label.lower() or "perp" in exit_label.lower():
        try:
            terminal_growth_rate = float(exit_label.split("%")[0].strip())
        except (ValueError, IndexError):
            pass
    
    # Parse revenue growth (use CAGR or first year growth)
    revenue_growth = None
    revenue_growths_json = payload.get("Forecasted Revenue Growth % (JSON)", "[]")
    try:
        revenue_growths = json.loads(revenue_growths_json) if isinstance(revenue_growths_json, str) else revenue_growths_json
        if revenue_growths and len(revenue_growths) > 0:
            revenue_growth = float(revenue_growths[0])
    except (json.JSONDecodeError, ValueError, IndexError):
        pass
    
    # Parse margin (use first year margin)
    margin = None
    margins_json = payload.get("Forecasted Net Margin % (JSON)", "[]")
    try:
        margins = json.loads(margins_json) if isinstance(margins_json, str) else margins_json
        if margins and len(margins) > 0:
            margin = float(margins[0]) / 100.0  # Convert percentage to decimal
    except (json.JSONDecodeError, ValueError, IndexError):
        pass
    
    # Create full payload JSON with all CSV data
    full_payload = {
        "row_id": payload.get("Row ID"),
        "date": payload.get("Date"),
        "revenue_cagr": payload.get("Revenue CAGR (%)"),
        "net_income_cagr": payload.get("Net Income CAGR (%)"),
        "forecast_years": payload.get("Forecast Years"),
        "tbv_included": payload.get("TBV Included"),
        "notes": payload.get("Notes", ""),
        "forecasted_revenue": json.loads(payload.get("Forecasted Revenue (JSON)", "[]")) if isinstance(payload.get("Forecasted Revenue (JSON)", "[]"), str) else payload.get("Forecasted Revenue (JSON)", []),
        "forecasted_net_income": json.loads(payload.get("Forecasted Net Income (JSON)", "[]")) if isinstance(payload.get("Forecasted Net Income (JSON)", "[]"), str) else payload.get("Forecasted Net Income (JSON)", []),
        "forecasted_net_margin_pct": json.loads(payload.get("Forecasted Net Margin % (JSON)", "[]")) if isinstance(payload.get("Forecasted Net Margin % (JSON)", "[]"), str) else payload.get("Forecasted Net Margin % (JSON)", []),
        "forecasted_revenue_growth_pct": json.loads(payload.get("Forecasted Revenue Growth % (JSON)", "[]")) if isinstance(payload.get("Forecasted Revenue Growth % (JSON)", "[]"), str) else payload.get("Forecasted Revenue Growth % (JSON)", []),
        "scenario_chance": payload.get("Scenario Chance (%)"),
    }
    
    db_record = {
        "user_id": user_id,
        "ticker": payload.get("Company", ""),
        "scenario": payload.get("Scenario", "Base"),
        "operating_model": payload.get("Operating Model", ""),
        "discount_rate": float(payload.get("Discount Rate (%)", 0)) if payload.get("Discount Rate (%)") is not None else None,
        "terminal_growth_rate": terminal_growth_rate,
        "exit_multiple": exit_multiple,
        "revenue_growth": revenue_growth,
        "margin": margin,
        "intrinsic_value_per_share": float(payload.get("Intrinsic Value ($/share)", 0)) if payload.get("Intrinsic Value ($/share)") is not None else None,
        "market_price_per_share": float(payload.get("Market Price ($/share)", 0)) if payload.get("Market Price ($/share)") is not None else None,
        "upside_percentage": float(payload.get("Upside (%)", 0)) if payload.get("Upside (%)") is not None else None,
        "full_payload_json": full_payload,
    }
    
    return db_record


def _db_record_to_payload(record: dict) -> dict:
    """Convert database record format to CSV payload format."""
    full_payload = record.get("full_payload_json", {}) or {}
    
    # Determine exit label
    exit_label = ""
    if record.get("exit_multiple"):
        exit_label = f"{record['exit_multiple']:.2f}× PE"
    elif record.get("terminal_growth_rate"):
        exit_label = f"{record['terminal_growth_rate']:.2f}% perp. g"
    
    payload = {
        "Row ID": full_payload.get("row_id", str(record.get("id", ""))),
        "Date": full_payload.get("date", record.get("created_at", datetime.now()).strftime("%Y-%m-%d %H:%M") if hasattr(record.get("created_at"), "strftime") else str(record.get("created_at", datetime.now()))),
        "Company": record.get("ticker", ""),
        "Scenario": record.get("scenario", "Base"),
        "Intrinsic Value ($/share)": float(record.get("intrinsic_value_per_share", 0)) if record.get("intrinsic_value_per_share") is not None else None,
        "Market Price ($/share)": float(record.get("market_price_per_share", 0)) if record.get("market_price_per_share") is not None else None,
        "Upside (%)": float(record.get("upside_percentage", 0)) if record.get("upside_percentage") is not None else None,
        "Operating Model": record.get("operating_model", ""),
        "Exit Value": exit_label,
        "Discount Rate (%)": float(record.get("discount_rate", 0)) if record.get("discount_rate") is not None else None,
        "TBV Included": full_payload.get("tbv_included", "No"),
        "Forecast Years": full_payload.get("forecast_years", 5),
        "Revenue CAGR (%)": full_payload.get("revenue_cagr"),
        "Net Income CAGR (%)": full_payload.get("net_income_cagr"),
        "Scenario Chance (%)": full_payload.get("scenario_chance"),
        "Notes": full_payload.get("notes", ""),
        "Forecasted Revenue (JSON)": json.dumps(full_payload.get("forecasted_revenue", [])),
        "Forecasted Net Income (JSON)": json.dumps(full_payload.get("forecasted_net_income", [])),
        "Forecasted Net Margin % (JSON)": json.dumps(full_payload.get("forecasted_net_margin_pct", [])),
        "Forecasted Revenue Growth % (JSON)": json.dumps(full_payload.get("forecasted_revenue_growth_pct", [])),
    }
    
    return payload


def save_dcf_to_supabase(payload: dict) -> bool:
    """Save DCF calculation to Supabase. Returns True if successful, False otherwise."""
    try:
        sb = _get_supabase_client()
        user_id = _get_user_id()
        
        if not sb or not user_id:
            return False
        
        db_record = _payload_to_db_record(payload, user_id)
        
        # Insert into Supabase
        result = sb.table("dcf_calculations").insert(db_record).execute()
        
        if result.data:
            return True
        return False
    except Exception as e:
        # Silently fail - fallback to CSV
        return False


def load_dcfs_from_supabase() -> pd.DataFrame:
    """Load DCF calculations from Supabase for current user. Returns empty DataFrame if not logged in or error."""
    try:
        sb = _get_supabase_client()
        user_id = _get_user_id()
        
        if not sb or not user_id:
            return pd.DataFrame()
        
        # Query Supabase
        result = sb.table("dcf_calculations").select("*").eq("user_id", user_id).order("created_at", desc=False).execute()
        
        # Reverse the list to get newest first (descending order)
        if result.data:
            result.data.reverse()
        
        if not result.data:
            return pd.DataFrame()
        
        # Convert records to payload format
        payloads = [_db_record_to_payload(record) for record in result.data]
        
        if not payloads:
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(payloads)
        
        # Ensure date column is properly formatted
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        
        return df
    except Exception as e:
        # Silently fail - fallback to CSV
        return pd.DataFrame()


def delete_dcf_from_supabase(row_id: str) -> bool:
    """Delete DCF calculation from Supabase by row_id. Returns True if successful."""
    try:
        sb = _get_supabase_client()
        user_id = _get_user_id()
        
        if not sb or not user_id:
            return False
        
        # Query all records for this user to find the matching row_id
        result = sb.table("dcf_calculations").select("id, full_payload_json").eq("user_id", user_id).execute()
        
        if not result.data:
            return False
        
        # Search for matching row_id in full_payload_json
        matching_id = None
        for record in result.data:
            full_payload = record.get("full_payload_json", {}) or {}
            if isinstance(full_payload, dict):
                if full_payload.get("row_id") == row_id:
                    matching_id = record.get("id")
                    break
        
        if matching_id:
            # Delete by database ID
            delete_result = sb.table("dcf_calculations").delete().eq("id", matching_id).eq("user_id", user_id).execute()
            return True
        
        return False
    except Exception as e:
        # Silently fail - return False
        return False


# ======================
# Local CSV save (fallback for non-logged-in users)
# ======================
def load_saved_df() -> pd.DataFrame:
    """Load saved DCF calculations. Uses Supabase if user is logged in, otherwise CSV."""
    # Try Supabase first if user is logged in
    supabase_df = load_dcfs_from_supabase()
    if not supabase_df.empty:
        return supabase_df
    
    # Fallback to CSV
    if SAVED_FILE.exists():
        try:
            df = pd.read_csv(SAVED_FILE)
            if "TBV Included" in df.columns:
                df["TBV Included"] = df["TBV Included"].astype(str)
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def append_saved_row(row: dict) -> bool:
    """Save DCF calculation. Uses Supabase if user is logged in, otherwise CSV.
    Returns True if saved to Supabase, False if saved to CSV."""
    # Try Supabase first if user is logged in
    if save_dcf_to_supabase(row):
        return True  # Successfully saved to Supabase
    
    # Fallback to CSV
    df = load_saved_df()
    # If we got data from Supabase, convert to list first
    if isinstance(df, pd.DataFrame) and not df.empty:
        df_list = df.to_dict("records")
        df_list.append(row)
        df = pd.DataFrame(df_list)
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    
    df.to_csv(SAVED_FILE, index=False)
    try:
        load_saved_df.clear()
    except AttributeError:
        pass
    return False  # Saved to CSV

@st.cache_data(ttl=3600)
def fmp_get_historical_prices(ticker: str, days: int = 365) -> pd.DataFrame:
    """Fetch historical daily price data from FMP API.
    Returns DataFrame with columns: date, close, open, high, low, volume.
    """
    if not FMP_API_KEY:
        return pd.DataFrame()
    
    # Calculate start date (days ago from today)
    from datetime import datetime, timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    endpoints = [
        (
            f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
            f"?from={start_date.strftime('%Y-%m-%d')}&to={end_date.strftime('%Y-%m-%d')}&apikey={FMP_API_KEY}"
        ),
        (
            f"https://financialmodelingprep.com/stable/historical-price-full/{ticker}"
            f"?from={start_date.strftime('%Y-%m-%d')}&to={end_date.strftime('%Y-%m-%d')}&apikey={FMP_API_KEY}"
        ),
    ]
    
    for url in endpoints:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            
            # FMP returns data in format: {"symbol": "AAPL", "historical": [...]}
            if isinstance(data, dict) and "historical" in data:
                historical = data["historical"]
            elif isinstance(data, list):
                historical = data
            else:
                continue
            
            if not historical:
                continue
            
            rows = []
            for entry in historical:
                date_str = entry.get("date")
                close_price = entry.get("close")
                
                if date_str and close_price is not None:
                    rows.append({
                        "date": pd.to_datetime(date_str),
                        "close": float(close_price),
                        "open": float(entry.get("open", 0)),
                        "high": float(entry.get("high", 0)),
                        "low": float(entry.get("low", 0)),
                        "volume": int(entry.get("volume", 0)),
                    })
            
            if rows:
                df = pd.DataFrame(rows)
                df = df.sort_values("date").reset_index(drop=True)
                return df
        except Exception:
            continue
    
    return pd.DataFrame()
