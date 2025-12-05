import streamlit as st
import pandas as pd
import numpy as np
import uuid
from datetime import datetime
from pathlib import Path
import json
import altair as alt
from pandas.api.types import CategoricalDtype

from .data import (
    load_local_financials, fmp_get_profile, get_balance_from_fmp,
    load_saved_df, append_saved_row, fmp_get_quarterly_income,
    fmp_get_product_segmentation, check_fmp_api_key_configured,
    fmp_search_symbols
)

from .logic import (
    discount_values, gordon_terminal, get_tbv_from_fmp, fmt_money, fmt_pct,
    ensure_series, toolbar_edit_reset, quick_adjust, editor_table, get_series,
    render_preset_selector, get_available_analyst_years
)


# ==============
# CSS (behouden)
# ==============
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
INPUT_STATE_FILE = DATA_DIR / "last_dcf_inputs.json"


_CUSTOM_CSS = """
<style>
    .main {background-color:#fafafa;font-family:'Segoe UI',sans-serif;}
    h2 {margin-top:40px;background-color:#f0f0f0;padding:10px 15px;border-radius:6px;font-size:20px;}
    table {border-collapse:collapse;width:100%;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.1);}
    th {background-color:#222;color:white!important;text-align:center!important;padding:6px;}
    td {padding:6px;text-align:center!important;}
    tr:hover td {background-color:#eaf6ff;}
    .val-card {margin-top:15px;padding:14px;border:1px solid #ddd;border-radius:12px;background:#fff;}
    .val-scale {position:relative;height:12px;background:#f1f3f5;border-radius:999px;overflow:visible;}
    .val-fill {position:absolute;left:0;top:0;height:100%;border-radius:999px;}
    .val-marker {position:absolute;top:-7px;transform:translateX(-50%);padding:2px 6px;border-radius:6px;font-size:11px;white-space:nowrap;background:#111;color:#fff;}
    .val-tick {position:absolute;top:100%;transform:translateX(-50%);font-size:11px;color:#555;margin-top:6px;}
    .val-legend {display:flex;gap:12px;font-size:12px;color:#333;margin-top:10px;}
    .dot {width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px;}
    .muted {color:#666;font-size:12px;margin-top:6px;}
    form[data-testid="stForm"][aria-label="save_dcf_form"] button {
        font-size:18px;
        font-weight:700;
    }
</style>
"""


def _compute_cagr(start_value: float | None, end_value: float | None, periods: int) -> float | None:
    """Return CAGR (%) between start and end over periods, or None if invalid."""
    try:
        if start_value is None or end_value is None:
            return None
        years = int(periods)
        if years <= 0:
            return None
        start = float(start_value)
        end = float(end_value)
        if start == 0 or start * end <= 0:
            return None
        return round(((end / start) ** (1 / years) - 1) * 100, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _load_last_inputs() -> dict:
    if INPUT_STATE_FILE.exists():
        try:
            return json.loads(INPUT_STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _persist_last_inputs(payload: dict):
    try:
        INPUT_STATE_FILE.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def _snapshot_current_inputs():
    keys_defaults = {
        "dcf_ticker": "AAPL",
        "dcf_operating_model": "Equity Model: Net Income. PE Exit",
        "dcf_exit_multiple": 15.0,
        "dcf_terminal_growth": 2.0,
        "dcf_forecast_years": 5,
        "dcf_discount_rate": 7.34,
        "dcf_include_tbv": "No",
    }
    snapshot = {k: st.session_state.get(k, default) for k, default in keys_defaults.items()}
    _persist_last_inputs(snapshot)


# ==========================
# Hoofd-render van de sectie
# ==========================
def render_dcf_section():
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
    st.title("💰 DCF Valuation")

    last_inputs = _load_last_inputs()

    # Initialize session state from saved inputs, prioritizing session state if it exists
    if "dcf_ticker" not in st.session_state:
        st.session_state.dcf_ticker = last_inputs.get("dcf_ticker", "AAPL")
    
    # Check if a suggestion was selected (using a separate key to avoid widget conflict)
    if "selected_ticker_suggestion" in st.session_state:
        st.session_state.dcf_ticker = st.session_state.selected_ticker_suggestion
        del st.session_state.selected_ticker_suggestion
        st.rerun()
    
    # Helper function to validate ticker format
    def _validate_ticker_format(ticker: str) -> tuple[bool, str]:
        """Validate ticker format. Returns (is_valid, error_message)."""
        if not ticker:
            return False, "Please enter a ticker symbol."
        ticker = ticker.upper().strip()
        if len(ticker) < 1 or len(ticker) > 100:
            return False, "Ticker symbol must be between 1 and 100 characters."
        # Allow letters, numbers, dots, hyphens, and spaces
        allowed_chars = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.- ")
        if not all(c in allowed_chars for c in ticker):
            return False, "Ticker symbol can only contain letters, numbers, dots, hyphens, and spaces."
        return True, ""
    
    # Callback to save ticker immediately when it changes
    def on_ticker_change():
        ticker_val = st.session_state.dcf_ticker
        if ticker_val:
            # Update JSON file immediately
            current_inputs = _load_last_inputs()
            current_inputs["dcf_ticker"] = ticker_val
            _persist_last_inputs(current_inputs)
    
    ticker_input = st.text_input(
        "🔎 Enter Ticker Symbol",
        value=st.session_state.dcf_ticker,
        key="dcf_ticker",
        on_change=on_ticker_change,
        help="Enter a stock ticker symbol (e.g., AAPL, MSFT, GOOGL). Suggestions will appear below as you type.",
    )
    
    ticker = (ticker_input or st.session_state.dcf_ticker or "").upper().strip()
    
    # Show ticker suggestions if user is typing and API key is available
    if ticker and len(ticker) >= 1:
        is_valid_format, format_error = _validate_ticker_format(ticker)
        if not is_valid_format:
            st.warning(f"⚠️ {format_error}")
        elif check_fmp_api_key_configured():
            # Show suggestions if API key is available and ticker is at least 1 character
            with st.spinner("Searching for ticker suggestions..."):
                suggestions = fmp_search_symbols(ticker, limit=8)
                if suggestions:
                    st.caption("💡 **Suggestions:** Click a suggestion to select it")
                    cols = st.columns(min(4, len(suggestions)))
                    for idx, suggestion in enumerate(suggestions[:8]):
                        symbol = suggestion.get("symbol", "")
                        name = suggestion.get("name", "")
                        exchange = suggestion.get("exchangeShortName", "")
                        with cols[idx % 4]:
                            display_text = f"**{symbol}**"
                            if name:
                                display_text += f"\n{name[:25]}{'...' if len(name) > 25 else ''}"
                            if exchange:
                                display_text += f"\n_{exchange}_"
                            if st.button(
                                display_text,
                                key=f"ticker_suggestion_{idx}_{symbol}",
                                use_container_width=True,
                            ):
                                # Use a separate session state key to avoid widget conflict
                                st.session_state.selected_ticker_suggestion = symbol
                                st.rerun()
    
    if not ticker:
        st.info("👆 Enter a ticker symbol above to get started.")
        st.stop()
    
    # Update session state if ticker changed (normalize to uppercase for consistency)
    current_ticker_upper = str(st.session_state.dcf_ticker).upper().strip()
    if ticker != current_ticker_upper:
        st.session_state.dcf_ticker = ticker
        # Save immediately when ticker changes
        current_inputs = _load_last_inputs()
        current_inputs["dcf_ticker"] = ticker
        _persist_last_inputs(current_inputs)

    # Validate ticker format before attempting to load data
    is_valid_format, format_error = _validate_ticker_format(ticker)
    if not is_valid_format:
        st.error(f"❌ Invalid ticker format: {format_error}")
        st.stop()
    
    # Try to load financial data
    df = load_local_financials(ticker)
    if df is None:
        # Provide more helpful error message
        error_msg = (
            f"❌ **No financial data found for ticker '{ticker}'.**\n\n"
            "**Possible reasons:**\n"
            "• The ticker symbol may be incorrect or not in our database\n"
            "• The ticker may not be listed on major US exchanges (NASDAQ, NYSE, AMEX)\n"
            "• Financial data file may be missing or incomplete\n\n"
            "**Try:**\n"
            "• Check the ticker spelling (e.g., AAPL, not APPL)\n"
            "• Use the suggestions above to find the correct ticker\n"
            "• Verify the ticker is listed on a major US exchange"
        )
        st.error(error_msg)
        st.stop()

    st.markdown(f"### {ticker} DCF Valuation")

    # Quick metric extractor
    def metric(df, m):
        try:
            return float(df.loc[df["Metric"].str.lower() == m.lower(), "TTM"].iloc[0])
        except Exception:
            return None

    def _pct_change(prev: float | None, curr: float | None) -> float | None:
        try:
            if prev is None or curr is None or pd.isna(prev) or pd.isna(curr):
                return None
            if prev == 0:
                return None
            return round(((curr - prev) / prev) * 100, 1)
        except Exception:
            return None

    def _render_historical_table(
        col_labels: list[str], revenues: list[float], net_incomes: list[float]
    ) -> pd.DataFrame | None:
        if not col_labels:
            st.info("Historical data not available.")
            return None
        net_margins = []
        for rev_val, ni_val in zip(revenues, net_incomes):
            if pd.notna(rev_val) and rev_val not in (0, None) and pd.notna(ni_val):
                try:
                    net_margins.append(round((ni_val / rev_val) * 100, 1))
                except ZeroDivisionError:
                    net_margins.append(np.nan)
            else:
                net_margins.append(np.nan)
        data = {"Metric": ["Revenue", "Net income", "Net Margin (%)"]}
        for idx, label in enumerate(col_labels):
            data[label] = [
                revenues[idx] if idx < len(revenues) else np.nan,
                net_incomes[idx] if idx < len(net_incomes) else np.nan,
                net_margins[idx] if idx < len(net_margins) else np.nan,
            ]
        numeric_df = pd.DataFrame(data)
        display_df = numeric_df.copy()
        def _fmt_amount(val):
            if pd.isna(val):
                return ""
            try:
                return f"{float(val):,.0f}"
            except (TypeError, ValueError):
                return ""

        def _fmt_margin(val):
            if pd.isna(val):
                return ""
            try:
                return f"{float(val):.1f}"
            except (TypeError, ValueError):
                return ""

        for label in col_labels:
            if label not in display_df.columns:
                continue
            mask_amounts = display_df["Metric"].isin(["Revenue", "Net income"])
            display_df.loc[mask_amounts, label] = display_df.loc[mask_amounts, label].apply(
                _fmt_amount
            )
            mask_margin = display_df["Metric"] == "Net Margin (%)"
            display_df.loc[mask_margin, label] = display_df.loc[mask_margin, label].apply(
                _fmt_margin
            )
        st.dataframe(
            display_df.style.set_properties(**{"text-align": "center"}),
            use_container_width=True,
            hide_index=True,
        )
        return pd.DataFrame(
            {
                "Label": col_labels,
                "Revenue": revenues,
                "Net Income": net_incomes,
                "Net Margin": net_margins,
            }
        )

    def _render_yoy_table(data: dict, *, freq_key: str, button_suffix: str, use_expander: bool = True):
        if not data or not data.get("labels"):
            return
        
        yoy_df = _compute_yoy_dataframe(data, freq_key=freq_key)
        if yoy_df is None or yoy_df.empty:
            if use_expander:
                with st.expander("Show YoY data", expanded=False):
                    st.info("Not enough history to compute YoY changes.")
            else:
                st.info("Not enough history to compute YoY changes.")
            return

        if use_expander:
            with st.expander("Show YoY data", expanded=False):
                st.dataframe(
                    yoy_df.style.set_properties(**{"text-align": "center"}),
                    use_container_width=True,
                    hide_index=True,
                )
        else:
            st.subheader("YoY Changes")
            st.dataframe(
                yoy_df.style.set_properties(**{"text-align": "center"}),
                use_container_width=True,
                hide_index=True,
            )

    def _render_segment_breakdown_expander(ticker: str):
        expander = st.expander("Show revenue by segment (FMP)", expanded=False)
        with expander:
            seg_df = fmp_get_product_segmentation(ticker)
            if seg_df is None or seg_df.empty:
                st.info("Segment data unavailable for this ticker.")
                return
            pivot_df = (
                seg_df.pivot_table(
                    index="Segment",
                    columns="Fiscal Year",
                    values="Revenue ($M)",
                    aggfunc="sum",
                )
                .sort_index()
            )
            year_cols = sorted(pivot_df.columns)
            pivot_df = pivot_df.reindex(columns=year_cols)
            st.markdown("**Revenue by segment ($M)**")
            display_df = pivot_df.reset_index()
            display_df.columns = [
                str(col) if isinstance(col, (int, float)) else col for col in display_df.columns
            ]
            for col in display_df.columns[1:]:
                display_df[col] = display_df[col].apply(
                    lambda x: f"{x:,.1f}" if pd.notna(x) else ""
                )
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            yoy_df = pivot_df.copy()
            yoy_df = yoy_df.apply(lambda row: row.pct_change() * 100, axis=1)
            yoy_display = yoy_df.reset_index()
            yoy_display.columns = [
                str(col) if isinstance(col, (int, float)) else col for col in yoy_display.columns
            ]
            st.markdown("**YoY change (%)**")
            for col in yoy_display.columns[1:]:
                yoy_display[col] = yoy_display[col].apply(
                    lambda x: f"{x:+.1f}%" if pd.notna(x) and abs(x) > 1e-6 else ""
                )
            st.dataframe(
                yoy_display,
                use_container_width=True,
                hide_index=True,
            )
            st.caption("Source: FMP revenue-product-segmentation endpoint (USD millions).")
            st.caption("Source: FMP revenue-product-segmentation endpoint (USD millions).")

    def _compute_yoy_dataframe(data: dict, *, freq_key: str) -> pd.DataFrame | None:
        labels = data.get("labels") or []
        revenues = data.get("revenues") or []
        net_incomes = data.get("net_incomes") or []
        net_margins = data.get("net_margins") or []
        period_keys = data.get("period_keys")

        # Filter out TTM from YoY calculations as it's not a good YoY comparison
        ttm_indices = [i for i, label in enumerate(labels) if str(label).upper() == "TTM"]
        if ttm_indices:
            # Remove TTM from all lists
            for idx in sorted(ttm_indices, reverse=True):  # Reverse to maintain indices
                labels.pop(idx)
                revenues.pop(idx)
                net_incomes.pop(idx)
                if idx < len(net_margins):
                    net_margins.pop(idx)
                if period_keys and idx < len(period_keys):
                    period_keys.pop(idx)

        yoy_labels = []
        rev_changes, ni_changes, margin_changes = [], [], []

        if freq_key == "quarterly":
            lookback = 4
            if period_keys and any(pk is not None for pk in period_keys):
                pk_map = {pk: idx for idx, pk in enumerate(period_keys) if pk is not None}
                for idx, pk in enumerate(period_keys):
                    if pk is None:
                        continue
                    prev_idx = pk_map.get(pk - lookback)
                    if prev_idx is None:
                        continue
                    yoy_labels.append(labels[idx])
                    rev_changes.append(_pct_change(revenues[prev_idx], revenues[idx]))
                    ni_changes.append(_pct_change(net_incomes[prev_idx], net_incomes[idx]))
                    prev_margin = net_margins[prev_idx] if prev_idx < len(net_margins) else None
                    curr_margin = net_margins[idx] if idx < len(net_margins) else None
                    if (
                        prev_margin is None
                        or curr_margin is None
                        or pd.isna(prev_margin)
                        or pd.isna(curr_margin)
                    ):
                        margin_changes.append(None)
                    else:
                        margin_changes.append(round(curr_margin - prev_margin, 1))
            else:
                for idx in range(lookback, len(labels)):
                    prev_idx = idx - lookback
                    yoy_labels.append(labels[idx])
                    rev_changes.append(_pct_change(revenues[prev_idx], revenues[idx]))
                    ni_changes.append(_pct_change(net_incomes[prev_idx], net_incomes[idx]))
                    prev_margin = net_margins[prev_idx] if prev_idx < len(net_margins) else None
                    curr_margin = net_margins[idx] if idx < len(net_margins) else None
                    if (
                        prev_margin is None
                        or curr_margin is None
                        or pd.isna(prev_margin)
                        or pd.isna(curr_margin)
                    ):
                        margin_changes.append(None)
                    else:
                        margin_changes.append(round(curr_margin - prev_margin, 1))
        else:  # annual sequential YoY
            for idx in range(1, len(labels)):
                yoy_labels.append(labels[idx])
                rev_changes.append(_pct_change(revenues[idx - 1], revenues[idx]))
                ni_changes.append(_pct_change(net_incomes[idx - 1], net_incomes[idx]))
                prev_margin = net_margins[idx - 1] if idx - 1 < len(net_margins) else None
                curr_margin = net_margins[idx] if idx < len(net_margins) else None
                if (
                    prev_margin is None
                    or curr_margin is None
                    or pd.isna(prev_margin)
                    or pd.isna(curr_margin)
                ):
                    margin_changes.append(None)
                else:
                    margin_changes.append(round(curr_margin - prev_margin, 1))

        if not yoy_labels:
            return None

        table = {"Metric": ["Revenue YoY (%)", "Net Income YoY (%)", "Net Margin Δ (pp)"]}
        for idx, label in enumerate(yoy_labels):
            table[label] = [
                f"{rev_changes[idx]:.1f}" if rev_changes[idx] is not None else "",
                f"{ni_changes[idx]:.1f}" if ni_changes[idx] is not None else "",
                f"{margin_changes[idx]:.1f}" if margin_changes[idx] is not None else "",
            ]
        return pd.DataFrame(table)

    rev, ni, fcf = metric(df, "Revenue"), metric(df, "Net income"), metric(df, "FCF")

    # ======================
    # HISTORICAL
    # ======================
    st.header("📈 Historical")

    cols = [c for c in ["2020", "2021", "2022", "2023", "2024", "TTM"] if c in df.columns]
    rev_row = df.loc[df["Metric"].str.lower() == "revenue", cols].astype(float)
    ni_row = df.loc[df["Metric"].str.lower() == "net income", cols].astype(float)
    revenues = [
        rev_row[c].iloc[0] if not rev_row.empty and c in rev_row.columns else np.nan for c in cols
    ]
    net_incomes = [
        ni_row[c].iloc[0] if not ni_row.empty and c in ni_row.columns else np.nan for c in cols
    ]
    net_margins = []
    for rev_val, ni_val in zip(revenues, net_incomes):
        if pd.notna(rev_val) and rev_val not in (0, None) and pd.notna(ni_val):
            net_margins.append(round((ni_val / rev_val) * 100, 1))
        else:
            net_margins.append(np.nan)
    annual_yoy_payload = {
        "labels": cols,
        "revenues": revenues,
        "net_incomes": net_incomes,
        "net_margins": net_margins,
        "period_keys": None,
    }
    _render_historical_table(cols, revenues, net_incomes)
    _render_yoy_table(annual_yoy_payload, freq_key="annual", button_suffix="annual")

    with st.expander("Show quarterly data (FMP)", expanded=False):
        lookback_years = 5
        lookback_quarters = lookback_years * 4
        quarterly_df = fmp_get_quarterly_income(ticker, limit=40)
        if quarterly_df is None or quarterly_df.empty:
            st.info("Quarterly FMP data unavailable for this ticker.")
        else:
            period_series = quarterly_df.get("PeriodKey")
            if period_series is not None and period_series.notna().any():
                latest_period = period_series.dropna().max()
                cutoff_period = latest_period - lookback_quarters
                mask = period_series >= cutoff_period
                if mask.any():
                    quarterly_df = quarterly_df.loc[mask].reset_index(drop=True)
            else:
                quarterly_df = quarterly_df.tail(lookback_quarters + 1)
            col_labels = quarterly_df["Period"].tolist()
            revenues = pd.to_numeric(quarterly_df["Revenue"], errors="coerce").tolist()
            net_incomes = pd.to_numeric(quarterly_df["Net Income"], errors="coerce").tolist()
            quarterly_payload = {
                "labels": col_labels,
                "revenues": revenues,
                "net_incomes": net_incomes,
                "net_margins": [
                    round((ni / rev) * 100, 1) if (rev not in (0, None) and pd.notna(rev)) else np.nan
                    for rev, ni in zip(revenues, net_incomes)
                ],
                "period_keys": quarterly_df.get("PeriodKey").tolist()
                if "PeriodKey" in quarterly_df.columns
                else None,
            }
            _render_historical_table(col_labels, revenues, net_incomes)
            st.caption("Quarterly revenue & net income sourced directly from FMP (values in millions).")
            _render_yoy_table(quarterly_payload, freq_key="quarterly", button_suffix="quarterly", use_expander=False)

    _render_segment_breakdown_expander(ticker)

    # ======================
    # FORECAST
    # ======================
    st.header("🔮 Forecast")
    st.write("")

    # Initialize all inputs from saved state, but preserve session state if it exists
    if "dcf_operating_model" not in st.session_state:
        st.session_state.dcf_operating_model = last_inputs.get("dcf_operating_model", "Equity Model: Net Income. PE Exit")
    if "dcf_exit_multiple" not in st.session_state:
        st.session_state.dcf_exit_multiple = last_inputs.get("dcf_exit_multiple", 15.0)
    if "dcf_terminal_growth" not in st.session_state:
        st.session_state.dcf_terminal_growth = last_inputs.get("dcf_terminal_growth", 2.0)
    if "dcf_discount_rate" not in st.session_state:
        st.session_state.dcf_discount_rate = float(last_inputs.get("dcf_discount_rate", 7.34))
    if "dcf_include_tbv" not in st.session_state:
        st.session_state.dcf_include_tbv = last_inputs.get("dcf_include_tbv", "No")
    
    # Callback to save inputs immediately when they change
    def save_inputs_on_change():
        _snapshot_current_inputs()
    
    # Track the last ticker to detect changes
    last_ticker_key = "dcf_last_ticker_for_forecast"
    ticker_changed = st.session_state.get(last_ticker_key) != ticker
    
    # Check if analyst estimates are available and set forecast_years accordingly
    # Automatically match forecast_years to available analyst years from FMP
    available_analyst_years = get_available_analyst_years(ticker)
    default_forecast_years = int(last_inputs.get("dcf_forecast_years", 5))
    
    # Track if user has manually changed forecast_years (via slider)
    forecast_years_manually_changed_key = f"dcf_forecast_years_manually_changed_{ticker}"
    forecast_years_manually_changed = st.session_state.get(forecast_years_manually_changed_key, False)
    
    current_forecast_years = st.session_state.get("dcf_forecast_years")
    
    # If analyst data is available, automatically set forecast_years to match available years
    # But only if ticker changed or if user hasn't manually changed it
    if available_analyst_years > 0:
        if ticker_changed:
            # Ticker changed - always update to match available analyst years
            st.session_state.dcf_forecast_years = available_analyst_years
            st.session_state[last_ticker_key] = ticker
            # Reset manual change flag for new ticker
            st.session_state[forecast_years_manually_changed_key] = False
        elif current_forecast_years is None:
            # First time setting forecast_years for this session
            st.session_state.dcf_forecast_years = available_analyst_years
            st.session_state[last_ticker_key] = ticker
        elif not forecast_years_manually_changed and current_forecast_years != available_analyst_years:
            # Auto-update to match available years if user hasn't manually changed it
            st.session_state.dcf_forecast_years = available_analyst_years
    else:
        # No analyst data available - use default or preserve existing
        if current_forecast_years is None:
            st.session_state.dcf_forecast_years = default_forecast_years
        if ticker_changed:
            st.session_state[last_ticker_key] = ticker
    
    forecast_years = int(st.session_state.dcf_forecast_years)

    # Forecast setup
    ttm_rev_val = float(rev or 0.0)
    ttm_ni_val = float(ni or 0.0)
    base_margin = (ttm_ni_val / ttm_rev_val) if ttm_rev_val else 0.30

    ensure_series(base_margin, forecast_years)
    toolbar_edit_reset(base_margin, forecast_years)

    if st.session_state.forecast_edit:
        render_preset_selector(base_margin, forecast_years, ticker, ttm_rev_val)
        st.markdown("##### Forecast period")
        
        # Track if user manually changes forecast_years via slider
        forecast_years_manually_changed_key = f"dcf_forecast_years_manually_changed_{ticker}"
        
        def on_forecast_years_change():
            """Callback when user manually changes forecast years slider."""
            st.session_state[forecast_years_manually_changed_key] = True
            save_inputs_on_change()
        
        st.slider(
            "Forecast Period (years)",
            min_value=3,
            max_value=30,
            value=int(st.session_state.dcf_forecast_years),
            step=1,
            key="dcf_forecast_years",
            on_change=on_forecast_years_change,
        )
        forecast_years = int(st.session_state.dcf_forecast_years)
        ensure_series(base_margin, forecast_years)
        quick_adjust(forecast_years)
        editor_table(forecast_years)

    growth_series, margin_series = get_series(st.session_state.forecast_edit)

    forecast_years = int(st.session_state.dcf_forecast_years)
    revenues, net_incomes = [], []
    r = ttm_rev_val or 1.0
    for i in range(forecast_years):
        r *= (1 + growth_series[i])
        revenues.append(r)
        net_incomes.append(r * margin_series[i])

    # ======================
    # FORECAST GRAPH (single chart with side buttons)
    # ======================
    ordered_years = ["TTM"] + [f"Year {i}" for i in range(1, forecast_years + 1)]

    # Ensure a default metric in session state
    st.session_state.setdefault("forecast_metric_choice", "Revenue")

    col_left, col_right = st.columns([0.25, 0.75])

    with col_left:
        st.markdown("**Forecast metric**")
        for label in ["Revenue", "Net Income", "Net Margin (%)"]:
            if st.button(label, use_container_width=True, key=f"forecast_metric_btn_{label}"):
                st.session_state["forecast_metric_choice"] = label

    metric_choice = st.session_state["forecast_metric_choice"]

    ttm_margin_pct = (ttm_ni_val / ttm_rev_val * 100) if ttm_rev_val else (margin_series[0] * 100 if margin_series else 0)

    if metric_choice == "Revenue":
        metric_values = [ttm_rev_val] + revenues
    elif metric_choice == "Net Income":
        metric_values = [ttm_ni_val] + net_incomes
    else:  # "Net Margin (%)"
        metric_values = [ttm_margin_pct] + [m * 100 for m in margin_series[:forecast_years]]

    cat_dtype = CategoricalDtype(categories=ordered_years, ordered=True)
    df_chart = (
        pd.DataFrame(
            {
                "Year": ordered_years,
                metric_choice: metric_values,
            }
        )
        .astype({"Year": cat_dtype})
        .set_index("Year")
        .sort_index()
    )

    with col_right:
        st.subheader(f"Forecast – {metric_choice}")
        st.line_chart(df_chart)

    st.markdown("#### Valuation inputs")
    col_model, col_exit = st.columns([0.5, 0.5])
    with col_model:
        operating_choice = st.selectbox(
            "Operating Model",
            [
                "Equity Model: Net Income. PE Exit",
                "Equity Model: Net Income. Perpetual Growth Exit",
            ],
            key="dcf_operating_model",
            on_change=save_inputs_on_change,
        )

    with col_exit:
        if "PE Exit" in operating_choice:
            exit_value = st.number_input(
                "P/E Exit Multiple",
                value=st.session_state.dcf_exit_multiple,
                step=0.5,
                key="dcf_exit_multiple",
                on_change=save_inputs_on_change,
            )
            terminal_growth = None
        else:
            exit_value = None
            terminal_growth = st.slider(
                "Perpetual Growth (%)",
                min_value=-10.0,
                max_value=10.0,
                value=st.session_state.dcf_terminal_growth,
                step=0.25,
                key="dcf_terminal_growth",
                on_change=save_inputs_on_change,
            )

    col_disc, col_tbv = st.columns([0.5, 0.5])
    with col_disc:
        discount_rate = st.slider(
            "Discount Rate (%)",
            min_value=3.0,
            max_value=40.0,
            value=st.session_state.dcf_discount_rate,
            step=0.1,
            key="dcf_discount_rate",
            on_change=save_inputs_on_change,
        )
    with col_tbv:
        include_tbv_choice = st.selectbox(
            "Include Tangible Book Value",
            ["No", "Yes"],
            index=0 if st.session_state.dcf_include_tbv == "No" else 1,
            key="dcf_include_tbv",
            on_change=save_inputs_on_change,
        )
        include_tbv = include_tbv_choice == "Yes"

    pv_stream = discount_values(net_incomes, discount_rate)

    # ======================
    # DCF & VALUATION
    # ======================
    if "Perpetual Growth" in operating_choice:
        terminal_val = gordon_terminal(net_incomes[-1], discount_rate, terminal_growth)
    else:
        terminal_val = net_incomes[-1] * exit_value
    pv_terminal = terminal_val / ((1 + discount_rate/100) ** forecast_years)

    enterprise_val = sum(pv_stream) + pv_terminal
    
    # Check API key before making FMP API calls
    if not check_fmp_api_key_configured():
        st.stop()
    
    fmp_profile = fmp_get_profile(ticker)
    tbv, tbv_src = (None, None)
    if include_tbv:
        tbv, tbv_src = get_tbv_from_fmp(ticker)
    
    # Add TBV to enterprise value if included and available
    # TBV is in millions, same as enterprise_val
    if include_tbv:
        tbv_value = tbv if tbv is not None else 0
    else:
        tbv_value = 0
    
    enterprise_total = enterprise_val + tbv_value
    debt, cash, shares = get_balance_from_fmp(fmp_profile, ticker)
    equity_val = enterprise_total - debt + cash

    # per-share
    intrinsic_value_per_share = (equity_val * 1e6 / shares) if shares and shares > 0 else None
    market_price_per_share = fmp_profile.get("price")
    upside = ((intrinsic_value_per_share / market_price_per_share) - 1) * 100 if intrinsic_value_per_share and market_price_per_share else None

    st.header("💵 Valuation")

    # Calculate per-share breakdown components
    pv_forecast_per_share = None
    pv_terminal_per_share = None
    tbv_per_share = None
    if shares and shares > 0:
        pv_forecast_total = sum(pv_stream) * 1e6  # Convert to USD
        pv_forecast_per_share = pv_forecast_total / shares if shares > 0 else None
        
        pv_terminal_total = pv_terminal * 1e6  # Convert to USD
        pv_terminal_per_share = pv_terminal_total / shares if shares > 0 else None
        
        if tbv:
            tbv_total = tbv * 1e6  # Convert to USD
            tbv_per_share = tbv_total / shares if shares > 0 else None

    # Add CSS for tooltip
    st.markdown(
        """
        <style>
            .info-tooltip {
                position: relative;
                display: inline-block;
                cursor: help;
                margin-left: 6px;
                color: #666;
                font-size: 14px;
                vertical-align: middle;
            }
            .info-tooltip .tooltiptext {
                display: none;
                width: 280px;
                background-color: #333;
                color: #fff;
                text-align: left;
                border-radius: 6px;
                padding: 10px;
                position: absolute;
                z-index: 1000;
                bottom: 125%;
                left: 50%;
                margin-left: -140px;
                font-size: 12px;
                line-height: 1.6;
                box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                white-space: normal;
                word-wrap: break-word;
                pointer-events: none;
            }
            .info-tooltip .tooltiptext::after {
                content: "";
                position: absolute;
                top: 100%;
                left: 50%;
                margin-left: -5px;
                border-width: 5px;
                border-style: solid;
                border-color: #333 transparent transparent transparent;
            }
            .info-tooltip:hover .tooltiptext {
                display: block;
                pointer-events: auto;
            }
            .info-tooltip .tooltiptext * {
                display: block;
            }
            .tooltip-row {
                margin: 4px 0;
            }
            .tooltip-label {
                font-weight: 600;
                color: #fff;
            }
            .tooltip-value {
                color: #a0e7ff;
                margin-left: 8px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    
    with col1:
        if intrinsic_value_per_share:
            st.metric("Intrinsic Value ($/share)", f"${intrinsic_value_per_share:,.2f}")
        else:
            st.metric("Intrinsic Value ($/share)", "N/A")
    
    col2.metric("Market Price ($/share)", f"{market_price_per_share:,.2f}" if market_price_per_share else "N/A")

    # Info bij Intrinsic Value
    if shares and shares > 0 and intrinsic_value_per_share:
        total_intrinsic_value = equity_val  # in miljoenen USD
        st.markdown(
            f"""
            <div class="muted">
                ℹ️ Based on <b>{shares:,.0f}</b> outstanding shares.
                Total intrinsic equity value: <b>${total_intrinsic_value:,.0f}M</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Prettier over/under-valuation bar
    if intrinsic_value_per_share and market_price_per_share:
        _render_valuation_bar(intrinsic_value_per_share, market_price_per_share)

    # Debug info for TBV
    if include_tbv:
        if tbv is not None:
            st.caption(f"✅ Tangible Book Value included ({tbv_src}): {tbv:,.0f} $M (Enterprise: {enterprise_val:,.0f} → {enterprise_total:,.0f} $M)")
        else:
            st.warning(f"⚠️ Tangible Book Value could not be fetched for {ticker}. Check if balance sheet data is available.")
    else:
        st.caption(f"ℹ️ Tangible Book Value not included (Enterprise: {enterprise_val:,.0f} $M)")

    # ======================
    # SAVE FLOW (scenario na click)
    # ======================
    if "pending_save_payload" not in st.session_state:
        st.session_state["pending_save_payload"] = None
    st.session_state.setdefault("submissions", [])

    with st.form("save_dcf_form"):
        save_clicked = st.form_submit_button("💾 Save DCF Calculation", use_container_width=True)

    exit_label = f"{exit_value:.2f}× PE" if exit_value is not None else f"{terminal_growth:.2f}% perp. g"
    operating_model_label = "NI + PE Exit" if "PE Exit" in operating_choice else "NI + Perp. Growth Exit"

    # Calculate net margins and revenue growth percentages for each year
    net_margins = []
    revenue_growths = []
    prev_rev = ttm_rev_val or 1.0
    
    for i in range(forecast_years):
        # Net margin as percentage
        if revenues[i] and revenues[i] > 0:
            net_margins.append(round((net_incomes[i] / revenues[i]) * 100, 2))
        else:
            net_margins.append(0.0)
        
        # Revenue growth percentage
        if prev_rev and prev_rev > 0:
            revenue_growths.append(round(growth_series[i] * 100, 2))
        else:
            revenue_growths.append(0.0)
        prev_rev = revenues[i]

    payload = {
        "Row ID": str(uuid.uuid4()),
        "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Company": ticker,
        "Scenario": None,  # later gekozen
        "Intrinsic Value ($/share)": round(intrinsic_value_per_share, 4) if intrinsic_value_per_share else None,
        "Market Price ($/share)": round(market_price_per_share, 4) if market_price_per_share else None,
        "Upside (%)": round(upside, 2) if upside is not None else None,
        "Operating Model": operating_model_label,
        "Exit Value": exit_label,
        "Discount Rate (%)": round(discount_rate, 2),
        "TBV Included": "Yes" if include_tbv else "No",
        "Forecast Years": int(forecast_years),
        "Revenue CAGR (%)": _compute_cagr(ttm_rev_val, revenues[-1] if revenues else None, forecast_years),
        "Net Income CAGR (%)": _compute_cagr(ttm_ni_val, net_incomes[-1] if net_incomes else None, forecast_years),
        "Scenario Chance (%)": None,
        "Notes": "",  # Will be set during finalize save
        # Store forecast data as JSON strings
        "Forecasted Revenue (JSON)": json.dumps([round(r, 2) for r in revenues]),
        "Forecasted Net Income (JSON)": json.dumps([round(ni, 2) for ni in net_incomes]),
        "Forecasted Net Margin % (JSON)": json.dumps(net_margins),
        "Forecasted Revenue Growth % (JSON)": json.dumps(revenue_growths),
    }

    if save_clicked:
        st.session_state["pending_save_payload"] = payload


    # Finalize stap (ook na login)
    if st.session_state.get("pending_save_payload"):
        with st.expander("Finalize Save: kies scenario (Base / Conservative / Optimistic)", expanded=True):
            scenario = st.radio("Scenario label", ["Base", "Conservative", "Optimistic"],
                                horizontal=True, index=0, key="scenario_choice")
            
            # Notes/Annotations field
            notes_key = "save_notes_input"
            # Clear notes if we just saved (using flag to avoid widget state conflict)
            if st.session_state.get("_clear_notes_on_next_render", False):
                st.session_state[notes_key] = ""
                del st.session_state["_clear_notes_on_next_render"]
            if notes_key not in st.session_state:
                st.session_state[notes_key] = ""
            notes = st.text_area(
                "📝 Notes / Annotations (optional)",
                value=st.session_state[notes_key],
                key=notes_key,
                help="Add any notes, observations, or context for this DCF calculation",
                height=100
            )
            
            col_ok, col_cancel = st.columns([0.25, 0.75])

            with col_ok:
                if st.button("✅ Confirm Save", use_container_width=True, key="confirm_save_btn"):
                    final_row = st.session_state["pending_save_payload"].copy()
                    final_row["Scenario"] = scenario
                    final_row["Notes"] = notes.strip() if notes else ""

                    saved_to_supabase = append_saved_row(final_row)
                    if saved_to_supabase:
                        st.success("✅ Saved to cloud! Your data is now synced across all your devices. Jumping to Saved DCFs…")
                    else:
                        st.success("💾 Saved locally. Jumping to Saved DCFs…")

                    st.session_state["submissions"].append(final_row)
                    st.session_state["pending_save_payload"] = None
                    # Clear notes by using a separate flag that will reset the widget on next render
                    st.session_state["_clear_notes_on_next_render"] = True

                    recent_rows = st.session_state.setdefault("recent_saved_rows", [])
                    recent_rows.append(final_row)
                    if len(recent_rows) > 25:
                        del recent_rows[:-25]

                    try:
                        st.switch_page("pages/01_Saved_DCFs.py")
                    except Exception:
                        st.info("Couldn't auto-open Saved DCFs tab. Please click it manually.")

            with col_cancel:
                if st.button("❌ Cancel", use_container_width=True, key="cancel_save_btn"):
                    st.session_state["pending_save_payload"] = None
                    st.info("Save canceled.")

    # Lokale sessie-tabel
    st.markdown("#### Recent Saves (this session)")
    if st.session_state.get("submissions"):
        cols_show = [
            "Date","Company","Scenario","Intrinsic Value ($/share)","Market Price ($/share)","Upside (%)",
            "Operating Model","Exit Value","Discount Rate (%)","TBV Included","Forecast Years","Notes"
        ]
        df_sub = pd.DataFrame(st.session_state["submissions"])
        df_sub = df_sub[[c for c in cols_show if c in df_sub.columns]]
        st.dataframe(df_sub, use_container_width=True, hide_index=True)
    else:
        st.caption("Nog niets opgeslagen in deze sessie. Druk op ‘Save DCF Calculation’.")

    _snapshot_current_inputs()


def _render_valuation_bar(intrinsic_value_per_share: float, market_price_per_share: float):
    iv = float(intrinsic_value_per_share)
    mp = float(market_price_per_share)

    diff_pct = ((mp - iv) / iv) * 100 if iv else 0.0
    is_over = diff_pct > 0
    label = "Overvalued" if is_over else "Undervalued"
    color = "#ef4444" if is_over else "#10b981"

    chart_df = pd.DataFrame(
        {
            "Label": ["Intrinsic Value", "Market Price"],
            "Value": [iv, mp],
            "Color": ["#0ea5e9", "#f97316"],
        }
    )

    bar_chart = (
        alt.Chart(chart_df)
        .mark_bar(size=26, cornerRadius=6)
        .encode(
            y=alt.Y(
                "Label",
                sort=["Intrinsic Value", "Market Price"],
                title="",
                scale=alt.Scale(padding=0.6),
            ),
            x=alt.X("Value", title="$/share"),
            color=alt.Color(
                "Label",
                scale=alt.Scale(
                    domain=["Intrinsic Value", "Market Price"],
                    range=["#0ea5e9", "#f97316"],
                ),
                legend=None,
            ),
        )
        .properties(height=150)
    )

    text_layer = bar_chart.mark_text(
        align="left",
        baseline="middle",
        dx=5,
        color="#111",
        fontWeight=600,
    ).encode(text=alt.Text("Value", format="$.2f"))

    st.altair_chart(bar_chart + text_layer, use_container_width=True)
    st.markdown(
        f"""
        <div class="val-card" style="border:1px solid #e5e7eb;margin-top:10px;margin-bottom:20px;">
            <div style="text-align:center;font-weight:700;color:{color};font-size:18px;">
                {label.replace("valued", "valuation")} {abs(diff_pct):.0f}%
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
