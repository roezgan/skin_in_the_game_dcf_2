import streamlit as st
import pandas as pd
from pathlib import Path
import os
import json
from auth_utils import check_auth, login_icon
from dcf.data import delete_dcf_from_supabase
from dcf.data import load_saved_df, delete_dcf_from_supabase

st.set_page_config(page_title="Saved DCFs", layout="wide")

# =====================================================
# AUTHENTICATION (OPTIONAL)
# =====================================================
check_auth()
login_icon()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
os.makedirs(DATA_DIR, exist_ok=True)
SAVED_FILE = DATA_DIR / "saved_dcfs.csv"

st.title("📚 Saved DCF Calculations")

def load_saved() -> pd.DataFrame:
    """Load saved DCF calculations. Uses Supabase if user is logged in, otherwise CSV."""
    df = load_saved_df()  # This function already handles Supabase vs CSV
    
    if df.empty:
        return df
    
    # Ensure dates exist
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        missing_dates = df["Date"].isna()
        if missing_dates.any():
            df.loc[missing_dates, "Date"] = pd.Timestamp.now()
            # Only persist to CSV if not using Supabase
            if not st.session_state.get("user"):
                persist_saved(df)
    
    # Typing cleanup - convert all numeric columns
    numeric_columns_to_convert = [
        "Discount Rate (%)", "Upside (%)", "Revenue CAGR (%)", "Net Income CAGR (%)",
        "Scenario Chance (%)", "Forecast Years", "Year",
        "Intrinsic Value ($/share)", "Market Price ($/share)", "% Under / Overvalued"
    ]
    
    for col in numeric_columns_to_convert:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # Handle legacy column name
    if "Scenario % Change" in df.columns and "Scenario Chance (%)" not in df.columns:
        df["Scenario Chance (%)"] = pd.to_numeric(df["Scenario % Change"], errors="coerce")
        df.drop(columns=["Scenario % Change"], inplace=True)
    
    return df

def persist_saved(updated_df: pd.DataFrame):
    """Save DCF calculations. Uses Supabase if user is logged in, otherwise CSV."""
    # If user is logged in, updates are handled via Supabase (delete and re-insert)
    # For now, we'll only persist to CSV if user is not logged in
    # For logged-in users, individual updates (date, notes) would need separate Supabase update functions
    if not st.session_state.get("user"):
        updated_df.to_csv(SAVED_FILE, index=False)

df = load_saved()
if df.empty:
    user_logged_in = st.session_state.get("user") is not None
    if user_logged_in:
        st.info("📭 Je hebt nog geen opgeslagen DCF berekeningen. Ga naar de DCF-pagina en sla je eerste berekening op!")
    else:
        st.info("📭 Nog geen opgeslagen DCFs. Ga eerst naar de DCF-pagina en sla iets op. 💡 Tip: Log in om je data te synchroniseren over al je apparaten!")
    st.stop()

recent_rows = st.session_state.get("recent_saved_rows", [])
if recent_rows:
    try:
        existing_ids = set(df.get("Row ID", pd.Series(dtype=str)).astype(str))
    except Exception:
        existing_ids = set()
    new_rows = [
        row for row in recent_rows if str(row.get("Row ID", "")) not in existing_ids
    ]
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

# Ensure optional columns exist
for col in ["Revenue CAGR (%)", "Net Income CAGR (%)", "Notes"]:
    if col not in df.columns:
        df[col] = pd.NA if col != "Notes" else ""

if "Upside (%)" in df.columns:
    df["% Under / Overvalued"] = df["Upside (%)"]
else:
    df["% Under / Overvalued"] = pd.NA

# Derive year from Date for filtering
if "Date" in df.columns:
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Year"] = df["Date"].dt.year
else:
    df["Year"] = pd.NA

# ======================
# Filters
# ======================
col_ticker, col_year, col_scenario, col_val = st.columns([1.5, 1, 1, 1])

with col_ticker:
    ticker_options = sorted(df["Company"].dropna().unique().tolist())
    selected_tickers = st.multiselect(
        "Ticker(s)",
        ticker_options,
        default=ticker_options,
    )

with col_year:
    # Safely convert Year to integers, filtering out invalid values
    year_values = df["Year"].dropna().unique()
    base_year_options = []
    for y in year_values:
        try:
            year_int = int(float(y))  # Convert to float first, then int to handle numeric strings
            if year_int > 0:  # Basic validation
                base_year_options.append(year_int)
        except (ValueError, TypeError):
            continue
    base_year_options = sorted(base_year_options)
    include_unknown = df["Year"].isna().any()
    year_options = (["Unknown"] + base_year_options) if include_unknown else base_year_options
    default_years = year_options.copy()
    selected_years = st.multiselect(
        "Year(s)",
        year_options,
        default=default_years,
    )

with col_scenario:
    scenario_options = sorted(df["Scenario"].dropna().unique().tolist())
    selected_scenarios = st.multiselect(
        "Scenario(s)",
        scenario_options,
        default=scenario_options,
    )

with col_val:
    valuation_options = [
        "All valuations",
        "Undervalued by ≥10%",
        "Undervalued by ≥20%",
        "Undervalued by ≥30%",
        "Overvalued by ≥10%",
        "Overvalued by ≥20%",
        "Overvalued by ≥30%",
    ]
    valuation_choice = st.selectbox("Valuation filter", valuation_options, index=0)

mask = pd.Series(True, index=df.index)

if selected_tickers:
    mask &= df["Company"].isin(selected_tickers)
if selected_years:
    known_years = [y for y in selected_years if y != "Unknown"]
    include_unknown = "Unknown" in selected_years
    mask_year = pd.Series(False, index=df.index)
    if known_years:
        mask_year |= df["Year"].isin(known_years)
    if include_unknown:
        mask_year |= df["Year"].isna()
    mask &= mask_year
if selected_scenarios:
    mask &= df["Scenario"].isin(selected_scenarios)

if valuation_choice != "All valuations" and "% Under / Overvalued" in df.columns:
    val_series = pd.to_numeric(df["% Under / Overvalued"], errors="coerce")
    thresholds = {
        "Undervalued by ≥10%": 10,
        "Undervalued by ≥20%": 20,
        "Undervalued by ≥30%": 30,
        "Overvalued by ≥10%": -10,
        "Overvalued by ≥20%": -20,
        "Overvalued by ≥30%": -30,
    }
    target = thresholds.get(valuation_choice)
    if target is not None:
        if target > 0:
            mask &= val_series >= target
        else:
            mask &= val_series <= target

view_cols = [
    "Date",
    "Year",
    "Company",
    "Scenario",
    "Forecast Years",
    "Revenue CAGR (%)",
    "Net Income CAGR (%)",
    "Operating Model",
    "Exit Value",
    "Discount Rate (%)",
    "TBV Included",
    "Intrinsic Value ($/share)",
    "Market Price ($/share)",
    "% Under / Overvalued",
    "Notes",
]
view_cols = [c for c in view_cols if c in df.columns]
filtered_df = df.loc[mask, :].copy()
filtered_df = filtered_df.sort_values("Date", ascending=False)

# Remove JSON columns from filtered_df to prevent data editor issues
# These columns will be loaded separately when needed for the detailed view
json_columns_to_remove = [col for col in filtered_df.columns if "(JSON)" in str(col)]
if json_columns_to_remove:
    # Store JSON data in session state for later use, then remove from dataframe
    # Only update if not already set (to avoid overwriting on rerun before deletion completes)
    if "json_forecast_data" not in st.session_state or st.session_state.get("_force_reload_json_data", False):
        st.session_state.json_forecast_data = {}
        st.session_state._force_reload_json_data = False
        for idx, row in filtered_df.iterrows():
            row_id = str(row.get("Row ID", ""))
            if row_id:
                json_data = {}
                for json_col in json_columns_to_remove:
                    if json_col in row and pd.notna(row[json_col]):
                        json_data[json_col] = row[json_col]
                if json_data:
                    st.session_state.json_forecast_data[row_id] = json_data
    
    # Remove JSON columns from filtered_df
    filtered_df = filtered_df.drop(columns=json_columns_to_remove)

# Clear editor session state when filters change (to reset original dates and notes tracking)
filter_key = f"filter_state_{hash(str(selected_tickers) + str(selected_years) + str(selected_scenarios) + str(valuation_choice))}"
# Use a deletion counter to force data editor reset after deletions
deletion_counter = st.session_state.get("_deletion_counter", 0)
editor_key = f"saved_dcf_data_editor_{deletion_counter}"

if "last_filter_key" not in st.session_state or st.session_state.get("last_filter_key") != filter_key:
    # Filters changed, clear editor state
    if f"{editor_key}_original_dates" in st.session_state:
        del st.session_state[f"{editor_key}_original_dates"]
    if f"{editor_key}_original_notes" in st.session_state:
        del st.session_state[f"{editor_key}_original_notes"]
    if f"{editor_key}_processing_updates" in st.session_state:
        del st.session_state[f"{editor_key}_processing_updates"]
    st.session_state["last_filter_key"] = filter_key
if "Upside (%)" in filtered_df.columns:
    filtered_df["% Under / Overvalued"] = filtered_df["Upside (%)"]

if filtered_df.empty:
    st.caption("Geen resultaten voor deze filters.")
else:
    st.divider()
    st.subheader("Manage saved forecasts")
    if "Row ID" not in filtered_df.columns:
        st.error("Row identifiers missing; please resave forecasts.")
        st.stop()

    editable_cols = list(dict.fromkeys(view_cols + ["Row ID"]))
    editable_cols = [c for c in editable_cols if c in filtered_df.columns]
    # Explicitly exclude JSON columns from editable table to avoid data editor issues
    json_columns = [col for col in filtered_df.columns if "(JSON)" in str(col)]
    editable_cols = [c for c in editable_cols if c not in json_columns]
    
    # Create a clean copy with only the columns we need, ensuring no JSON columns
    table_df = filtered_df[editable_cols].copy()
    
    # Define numeric columns that should be converted
    numeric_columns = [
        "Year", "Forecast Years", "Revenue CAGR (%)", "Net Income CAGR (%)",
        "Discount Rate (%)", "% Under / Overvalued", "Intrinsic Value ($/share)",
        "Market Price ($/share)", "Scenario Chance (%)"
    ]
    
    # Define text columns that should remain as strings
    text_columns = ["Company", "Scenario", "Operating Model", "Exit Value", "TBV Included"]
    
    # Convert numeric columns BEFORE setting index to avoid data editor issues
    for col in table_df.columns:
        if col in ["Row ID", "Delete Row", "Date", "Notes"]:
            continue
        
        if col in numeric_columns:
            # Force conversion for known numeric columns, fill NaN with 0 for display
            table_df[col] = pd.to_numeric(table_df[col], errors='coerce')
            # Don't fill NaN with 0, leave as NaN for proper display
        elif col in text_columns:
            # Ensure text columns are strings
            table_df[col] = table_df[col].astype(str).replace(['nan', 'None', '<NA>', 'NaT'], '')
        elif table_df[col].dtype == 'object':
            # Try to convert object columns that might be numeric
            try:
                numeric_series = pd.to_numeric(table_df[col], errors='coerce')
                # Only convert if at least some values could be converted and it's not all NaN
                if not numeric_series.isna().all():
                    table_df[col] = numeric_series
            except Exception:
                # Keep as string if conversion fails
                table_df[col] = table_df[col].astype(str).replace(['nan', 'None', '<NA>', 'NaT'], '')
    
    # Ensure Row ID is string type and exists
    if "Row ID" not in table_df.columns and "Row ID" in filtered_df.columns:
        table_df["Row ID"] = filtered_df["Row ID"].astype(str).values
    
    if "Row ID" in table_df.columns:
        table_df["Row ID"] = table_df["Row ID"].astype(str)
        # Remove rows with empty Row IDs
        table_df = table_df[table_df["Row ID"].str.strip() != ''].copy()
    
    # Add Delete Row column as boolean
    table_df["Delete Row"] = False
    table_df["Delete Row"] = table_df["Delete Row"].astype(bool)
    
    # Reset index to integer index (Streamlit data editor works better with integer index)
    table_df = table_df.reset_index(drop=True)
    
    # Final check: ensure no problematic data types remain
    for col in table_df.columns:
        if table_df[col].dtype == 'object':
            # Check if it's actually numeric data stored as string
            if col not in text_columns and col not in ["Row ID", "Notes", "Delete Row", "Date"]:
                try:
                    # Try a sample conversion
                    sample = table_df[col].dropna().iloc[0] if not table_df[col].dropna().empty else None
                    if sample is not None:
                        float(sample)
                        # If successful, convert the whole column
                        table_df[col] = pd.to_numeric(table_df[col], errors='coerce')
                except (ValueError, IndexError, TypeError):
                    pass

    # Convert Notes to string type to avoid float inference issues
    if "Notes" in table_df.columns:
        # Convert to string, handling NaN and None values properly
        table_df["Notes"] = table_df["Notes"].fillna("").astype(str)
        # Replace string representations of NaN/None with empty string
        table_df["Notes"] = table_df["Notes"].replace(["nan", "None", "<NA>", "NaT"], "")

    # Keep Date as datetime for editing (don't convert to string)
    if "Date" in table_df.columns:
        table_df["Date"] = pd.to_datetime(table_df["Date"], errors="coerce")

    column_config = {
        col: st.column_config.Column(col, disabled=True)
        for col in table_df.columns
        if col not in ["Delete Row", "Date", "Notes", "Row ID"]
    }
    
    # Hide or disable Row ID column (used internally only)
    # Don't add to column_config, just leave it as is - Streamlit will handle it
    # If needed, we can hide it later but for now let's see if it causes issues
    
    # Make Date column editable
    if "Date" in table_df.columns:
        column_config["Date"] = st.column_config.DatetimeColumn(
            "Date",
            format="YYYY-MM-DD HH:mm",
            help="Edit to change the forecast date (you can set earlier dates)",
        )
    
    # Make Notes column editable
    if "Notes" in table_df.columns:
        column_config["Notes"] = st.column_config.TextColumn(
            "Notes",
            help="Add or edit notes/annotations for this DCF calculation",
        )
    if "% Under / Overvalued" in table_df.columns:
        column_config["% Under / Overvalued"] = st.column_config.NumberColumn(
            "% Under / Overvalued",
            disabled=True,
            format="%.2f",
            help="Positive = undervalued, Negative = overvalued vs intrinsic value.",
        )
    if "Intrinsic Value ($/share)" in table_df.columns:
        column_config["Intrinsic Value ($/share)"] = st.column_config.NumberColumn(
            "Intrinsic Value ($/share)",
            disabled=True,
            format="%.2f",
        )
    if "Market Price ($/share)" in table_df.columns:
        column_config["Market Price ($/share)"] = st.column_config.NumberColumn(
            "Market Price ($/share)",
            disabled=True,
            format="%.2f",
        )

    column_config["Delete Row"] = st.column_config.CheckboxColumn(
        "Delete?",
        help="Select and click Apply to delete this saved scenario.",
        default=False,
    )

    st.markdown(
        """
        <style>
            div[data-testid="stDataFrame"] td[data-field="% Under / Overvalued"][data-masked="false"][data-value^="-"] {
                background-color: #fee2e2 !important;
                color: #7f1d1d !important;
            }
            div[data-testid="stDataFrame"] td[data-field="% Under / Overvalued"][data-masked="false"]:not([data-value^="-"]) {
                background-color: #dcfce7 !important;
                color: #065f46 !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Store original dates and notes in session state for comparison (using Row ID as key)
    # editor_key is already set above with deletion counter
    if f"{editor_key}_original_dates" not in st.session_state:
        dates_dict = {}
        if "Date" in table_df.columns and "Row ID" in table_df.columns:
            for idx, row_id in enumerate(table_df["Row ID"]):
                dates_dict[str(row_id)] = table_df.iloc[idx]["Date"] if pd.notna(table_df.iloc[idx]["Date"]) else None
        st.session_state[f"{editor_key}_original_dates"] = dates_dict
    if f"{editor_key}_original_notes" not in st.session_state:
        notes_dict = {}
        if "Notes" in table_df.columns and "Row ID" in table_df.columns:
            for idx, row_id in enumerate(table_df["Row ID"]):
                note_val = table_df.iloc[idx]["Notes"]
                if pd.notna(note_val):
                    note_str = str(note_val).strip().replace("nan", "").replace("None", "").replace("<NA>", "").replace("NaT", "")
                    notes_dict[str(row_id)] = note_str
                else:
                    notes_dict[str(row_id)] = ""
        st.session_state[f"{editor_key}_original_notes"] = notes_dict
    
    # Check if we're processing updates (to prevent infinite loops)
    processing_updates_key = f"{editor_key}_processing_updates"
    if st.session_state.get(processing_updates_key, False):
        # Skip update processing this cycle to prevent infinite loop
        st.session_state[processing_updates_key] = False
    
    # Data editor outside form for immediate date saving
    # Try with minimal configuration first to isolate the issue
    try:
        # First, show basic info for debugging
        if st.session_state.get("_debug_mode", False):
            with st.expander("🔍 Debug Info"):
                st.write("DataFrame shape:", table_df.shape)
                st.write("Columns:", list(table_df.columns))
                st.write("Data types:")
                st.write(table_df.dtypes)
                st.write("Sample data (first 3 rows):")
                st.write(table_df.head(3))
        
        # Ensure all columns exist in column_config
        valid_column_config = {k: v for k, v in column_config.items() if k in table_df.columns}
        
        # Try with column_config first
        edited_df = None
        error_msg = None
        
        try:
            edited_df = st.data_editor(
                table_df,
                hide_index=True,
                column_config=valid_column_config if valid_column_config else None,
                num_rows="fixed",
                key=editor_key,
                use_container_width=True,
            )
        except Exception as e1:
            error_msg = str(e1)
            error_type = type(e1).__name__
            
            # Show detailed error info
            st.error(f"❌ Error displaying data editor: {error_msg}")
            
            # Try to identify the problematic column
            with st.expander("🔍 Debug Information"):
                st.write(f"**Error Type:** {error_type}")
                st.write(f"**Error Message:** {error_msg}")
                st.write(f"**DataFrame Info:**")
                st.write(f"- Shape: {table_df.shape}")
                st.write(f"- Columns: {list(table_df.columns)}")
                st.write("**Column Data Types:**")
                for col in table_df.columns:
                    dtype = table_df[col].dtype
                    sample_val = table_df[col].iloc[0] if len(table_df) > 0 else "N/A"
                    st.write(f"- {col}: {dtype} (sample: {sample_val})")
                
                import traceback
                st.code(traceback.format_exc())
            
            # Try minimal fallback - just show the data without editor
            st.warning("⚠️ Showing data in read-only mode. Editing is temporarily disabled.")
            st.dataframe(table_df, use_container_width=True, hide_index=True)
            edited_df = table_df.copy()
                
    except Exception as e:
        st.error(f"❌ Error preparing data editor: {e}")
        import traceback
        with st.expander("🔍 Technical Details"):
            st.code(traceback.format_exc())
        edited_df = table_df.copy()
    
    if edited_df is None:
        edited_df = table_df.copy()
    else:
        # Convert to DataFrame if it's not already
        if not isinstance(edited_df, pd.DataFrame):
            edited_df = pd.DataFrame(edited_df)
    
    # Ensure Row ID column exists and is string type
    if "Row ID" not in edited_df.columns:
        # Try to reconstruct from original table_df
        if "Row ID" in table_df.columns:
            edited_df["Row ID"] = table_df["Row ID"].values
    if "Row ID" in edited_df.columns:
        edited_df["Row ID"] = edited_df["Row ID"].astype(str)
    
    # Ensure Delete Row column exists and is boolean
    if "Delete Row" not in edited_df.columns:
        edited_df["Delete Row"] = False
    else:
        # Ensure Delete Row is boolean type
        edited_df["Delete Row"] = edited_df["Delete Row"].astype(bool)
    
    # Ensure Notes is string type in edited_df
    if "Notes" in edited_df.columns:
        edited_df["Notes"] = edited_df["Notes"].fillna("").astype(str).replace(["nan", "None", "<NA>", "NaT"], "")

    # Handle date and notes updates immediately (on Enter/blur)
    # Only process if we're not already processing updates
    date_updated = False
    notes_updated = False
    
    if not st.session_state.get(processing_updates_key, False):
        if "Date" in edited_df.columns and "Row ID" in edited_df.columns:
            # Get original dates from session state (now a dict keyed by Row ID)
            original_dates = st.session_state.get(f"{editor_key}_original_dates", {})
            edited_dates = pd.to_datetime(edited_df["Date"], errors="coerce")
            
            # Update dates in main dataframe if they changed
            for idx in edited_df.index:
                row_id_str = str(edited_df.loc[idx, "Row ID"])
                try:
                    original_date = original_dates.get(row_id_str)
                    new_date = edited_dates.loc[idx] if pd.notna(edited_dates.loc[idx]) else None
                    
                    # Check if date actually changed
                    if pd.notna(new_date):
                        if original_date is None or new_date != original_date:
                            # Update in main df
                            mask = df["Row ID"].astype(str) == row_id_str
                            if mask.any():
                                df.loc[mask, "Date"] = new_date.strftime("%Y-%m-%d %H:%M")
                                date_updated = True
                except (KeyError, IndexError):
                    # Handle case where row doesn't exist
                    continue
        
        # Handle notes updates
        if "Notes" in edited_df.columns and "Row ID" in edited_df.columns:
            original_notes = st.session_state.get(f"{editor_key}_original_notes", {})
            for idx in edited_df.index:
                row_id_str = str(edited_df.loc[idx, "Row ID"])
                try:
                    new_notes = str(edited_df.loc[idx, "Notes"]).strip() if pd.notna(edited_df.loc[idx, "Notes"]) else ""
                    new_notes = new_notes.replace("nan", "").replace("None", "").replace("<NA>", "").replace("NaT", "")
                    original_note = original_notes.get(row_id_str, "")
                    
                    # Only update if actually different
                    if new_notes != original_note:
                        # Update in main df
                        mask = df["Row ID"].astype(str) == row_id_str
                        if mask.any():
                            df.loc[mask, "Notes"] = new_notes
                            notes_updated = True
                except (KeyError, IndexError):
                    continue

        # Save date/notes changes immediately if detected
        if date_updated or notes_updated:
            # Set flag to prevent infinite loop
            st.session_state[processing_updates_key] = True
            # Recalculate Year column after date updates
            if date_updated:
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                df["Year"] = df["Date"].dt.year
            persist_saved(df)
            # Update session state with new dates and notes (using Row ID as key)
            if date_updated and "Row ID" in edited_df.columns:
                dates_dict = {}
                for idx in edited_df.index:
                    row_id_str = str(edited_df.loc[idx, "Row ID"])
                    dates_dict[row_id_str] = edited_df.loc[idx, "Date"] if pd.notna(edited_df.loc[idx, "Date"]) else None
                st.session_state[f"{editor_key}_original_dates"] = dates_dict
            if notes_updated and "Row ID" in edited_df.columns:
                notes_dict = {}
                for idx in edited_df.index:
                    row_id_str = str(edited_df.loc[idx, "Row ID"])
                    note_val = edited_df.loc[idx, "Notes"]
                    note_str = str(note_val).strip().replace("nan", "").replace("None", "").replace("<NA>", "").replace("NaT", "") if pd.notna(note_val) else ""
                    notes_dict[row_id_str] = note_str
                st.session_state[f"{editor_key}_original_notes"] = notes_dict
            update_msg = []
            if date_updated:
                update_msg.append("Date(s)")
            if notes_updated:
                update_msg.append("Note(s)")
            st.success(f"{' and '.join(update_msg)} updated successfully.")
            st.rerun()

    # Form for delete functionality only
    with st.form("saved_dcf_delete_form"):
        st.caption("Use the checkboxes above to select rows for deletion, then click 'Apply changes' below.")
        submitted = st.form_submit_button("Apply changes")

    if submitted:
        delete_ids = []
        try:
            # Safely check for Delete Row column and get selected rows
            if "Delete Row" not in edited_df.columns:
                st.warning("Delete Row column not found in edited dataframe. This may indicate a data editor issue.")
            else:
                # Handle boolean values - check for True, 1, or "True" string
                delete_mask = (
                    (edited_df["Delete Row"] == True) | 
                    (edited_df["Delete Row"] == 1) | 
                    (edited_df["Delete Row"].astype(str).str.upper() == "TRUE")
                )
                
                if delete_mask.any() and "Row ID" in edited_df.columns:
                    # Get Row IDs from the rows marked for deletion
                    delete_ids = edited_df.loc[delete_mask, "Row ID"].tolist()
                    # Convert to strings for comparison
                    delete_ids = [str(did) for did in delete_ids if did is not None]
        except Exception as e:
            st.error(f"Error reading delete selections: {e}")
            import traceback
            st.code(traceback.format_exc())
            delete_ids = []

        if delete_ids:
            # Delete from Supabase if user is logged in, otherwise delete from CSV
            user_logged_in = st.session_state.get("user") is not None
            deleted_count = 0
            
            if user_logged_in:
                # Delete from Supabase
                for row_id in delete_ids:
                    if delete_dcf_from_supabase(str(row_id)):
                        deleted_count += 1
            else:
                # Delete from CSV
                df = load_saved()
                # Ensure we're comparing strings
                df["Row ID"] = df["Row ID"].astype(str)
                # Filter out rows to delete
                df = df[~df["Row ID"].isin(delete_ids)].copy()
                # Recalculate Year column after deletions
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                df["Year"] = df["Date"].dt.year
                persist_saved(df)
                deleted_count = len(delete_ids)
            
            # Clear all relevant caches and session state to force complete reload
            # Set flag to force JSON data reload on next render
            st.session_state._force_reload_json_data = True
            if "json_forecast_data" in st.session_state:
                del st.session_state["json_forecast_data"]
            
            # Increment deletion counter to force data editor to reset with new key
            st.session_state._deletion_counter = st.session_state.get("_deletion_counter", 0) + 1
            
            # Clear all editor-related session state (using old editor_key)
            old_editor_key = f"saved_dcf_data_editor_{st.session_state._deletion_counter - 1}"
            keys_to_clear = [
                f"{old_editor_key}_original_dates",
                f"{old_editor_key}_original_notes",
                f"{old_editor_key}_processing_updates",
                "last_filter_key",
                "selected_dcf_for_details"
            ]
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            
            if deleted_count > 0:
                st.success(f"Deleted {deleted_count} scenario(s).")
            else:
                st.warning("Could not delete some scenarios. Please try again.")
            # Use st.rerun() to refresh the page immediately - the new editor_key will force a fresh data editor
            st.rerun()
        else:
            st.info("Select at least one row to delete and click Apply.")

    # ======================
    # DETAILED FORECAST VIEW
    # ======================
    st.divider()
    st.subheader("📊 View Detailed Forecast Breakdown")
    
    if not edited_df.empty and "Row ID" in edited_df.columns:
        # Create display labels for the selectbox (using Row ID as identifier)
        def format_row_label(row_id):
            try:
                # Find row by Row ID
                row_mask = edited_df["Row ID"] == row_id
                if not row_mask.any():
                    return str(row_id)
                row = edited_df[row_mask].iloc[0]
                company = str(row.get('Company', 'N/A'))
                scenario = str(row.get('Scenario', 'N/A'))
                date = row.get('Date')
                if pd.notna(date):
                    try:
                        date_str = pd.to_datetime(date).strftime('%Y-%m-%d')
                    except:
                        date_str = str(date)[:10] if date else 'N/A'
                else:
                    date_str = 'N/A'
                return f"{company} - {scenario} ({date_str})"
            except Exception:
                return str(row_id)
        
        # Use Row IDs as options
        row_id_options = edited_df["Row ID"].astype(str).unique().tolist()
        selected_row_id = st.selectbox(
            "Select a saved DCF to view detailed forecast:",
            options=row_id_options,
            format_func=format_row_label,
            key="selected_dcf_for_details",
            help="Choose a saved DCF calculation to see year-by-year forecasted revenue, net income, net margin, and revenue growth"
        )
        
        if selected_row_id:
            # Find selected row by Row ID
            row_mask = edited_df["Row ID"].astype(str) == str(selected_row_id)
            if not row_mask.any():
                st.warning("Selected row not found in filtered data.")
                selected_row = None
            else:
                selected_row = edited_df[row_mask].iloc[0]
            row_id_str = str(selected_row_id)
            
            if selected_row is not None:
                # Load the full row data (including JSON columns) from the original df
                # We need to reload from CSV to get JSON columns since we removed them from filtered_df
                main_df_row = df[df["Row ID"].astype(str) == row_id_str]
                
                if not main_df_row.empty:
                    main_row = main_df_row.iloc[0]
                    
                    # Try to parse JSON columns if they exist
                    forecast_years_val = main_row.get("Forecast Years", 0)
                    try:
                        forecast_years = int(float(forecast_years_val)) if pd.notna(forecast_years_val) else 0
                    except (ValueError, TypeError):
                        forecast_years = 0
                    
                    # Parse JSON data - try session state first, then main_row
                    revenues = []
                    net_incomes = []
                    net_margins = []
                    revenue_growths = []
                    
                    try:
                        # Try to get from session state first (if we stored it)
                        json_data = st.session_state.get("json_forecast_data", {}).get(row_id_str, {})
                        
                        # Parse from session state or main_row
                        if "Forecasted Revenue (JSON)" in json_data:
                            revenues = json.loads(str(json_data["Forecasted Revenue (JSON)"]))
                        elif "Forecasted Revenue (JSON)" in main_row and pd.notna(main_row["Forecasted Revenue (JSON)"]):
                            revenues = json.loads(str(main_row["Forecasted Revenue (JSON)"]))
                        
                        if "Forecasted Net Income (JSON)" in json_data:
                            net_incomes = json.loads(str(json_data["Forecasted Net Income (JSON)"]))
                        elif "Forecasted Net Income (JSON)" in main_row and pd.notna(main_row["Forecasted Net Income (JSON)"]):
                            net_incomes = json.loads(str(main_row["Forecasted Net Income (JSON)"]))
                        
                        if "Forecasted Net Margin % (JSON)" in json_data:
                            net_margins = json.loads(str(json_data["Forecasted Net Margin % (JSON)"]))
                        elif "Forecasted Net Margin % (JSON)" in main_row and pd.notna(main_row["Forecasted Net Margin % (JSON)"]):
                            net_margins = json.loads(str(main_row["Forecasted Net Margin % (JSON)"]))
                        
                        if "Forecasted Revenue Growth % (JSON)" in json_data:
                            revenue_growths = json.loads(str(json_data["Forecasted Revenue Growth % (JSON)"]))
                        elif "Forecasted Revenue Growth % (JSON)" in main_row and pd.notna(main_row["Forecasted Revenue Growth % (JSON)"]):
                            revenue_growths = json.loads(str(main_row["Forecasted Revenue Growth % (JSON)"]))
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        st.warning(f"Could not parse forecast data for this DCF. It may have been saved before detailed forecasts were available.")
                        revenues = []
                        net_incomes = []
                        net_margins = []
                        revenue_growths = []
                    
                    # Display detailed breakdown
                    company_name = str(selected_row.get('Company', 'N/A'))
                    scenario_name = str(selected_row.get('Scenario', 'N/A'))
                    
                    with st.expander(f"📈 Forecast Details: **{company_name}** - {scenario_name}", expanded=True):
                        if revenues and net_incomes and len(revenues) == forecast_years:
                            # Create forecast table
                            forecast_data = {
                                "Year": [f"Year {i+1}" for i in range(forecast_years)],
                                "Revenue ($M)": [f"${r:,.2f}" for r in revenues],
                                "Net Income ($M)": [f"${ni:,.2f}" for ni in net_incomes],
                            }
                            
                            if net_margins and len(net_margins) == forecast_years:
                                forecast_data["Net Margin (%)"] = [f"{m:.2f}%" for m in net_margins]
                            
                            if revenue_growths and len(revenue_growths) == forecast_years:
                                forecast_data["Revenue Growth (%)"] = [f"{g:.2f}%" for g in revenue_growths]
                            
                            forecast_df = pd.DataFrame(forecast_data)
                            st.dataframe(forecast_df, use_container_width=True, hide_index=True)
                            
                            # Add summary metrics
                            col1, col2, col3, col4 = st.columns(4)
                            with col1:
                                st.metric("Final Year Revenue", f"${revenues[-1]:,.2f}M" if revenues else "N/A")
                            with col2:
                                st.metric("Final Year Net Income", f"${net_incomes[-1]:,.2f}M" if net_incomes else "N/A")
                            with col3:
                                if net_margins:
                                    st.metric("Final Year Net Margin", f"{net_margins[-1]:.2f}%")
                                else:
                                    st.metric("Final Year Net Margin", "N/A")
                            with col4:
                                if revenue_growths:
                                    avg_growth = sum(revenue_growths) / len(revenue_growths) if revenue_growths else 0
                                    st.metric("Avg Revenue Growth", f"{avg_growth:.2f}%")
                                else:
                                    st.metric("Avg Revenue Growth", "N/A")
                        else:
                            st.info("📝 This DCF was saved before detailed forecast breakdowns were available. Only summary metrics (CAGR) are stored.")
                            if forecast_years > 0:
                                st.caption(f"Forecast period: {forecast_years} years")
                            else:
                                st.caption("Forecast period information not available.")

# Exports
st.download_button(
    "⬇️ Download CSV",
    data=filtered_df[view_cols].to_csv(index=False).encode("utf-8"),
    file_name="saved_dcfs_filtered.csv",
    mime="text/csv"
)
