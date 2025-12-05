import os
import json
import time
import requests
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======================
# CONFIG
# ======================

# 🔹 Basispad (1 niveau omhoog vanaf /modules/)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# 🔹 Relatieve mappen
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(BASE_DIR, "cache_fmp")
OUTPUT_XLSX = os.path.join(DATA_DIR, "FMP_all_tickers_financials.xlsx")
OUTPUT_PARQUET = os.path.join(DATA_DIR, "FMP_all_tickers_financials.parquet")
CHECKPOINT_FILE = os.path.join(CACHE_DIR, "checkpoint.json")

# 🔹 Maak mappen aan als ze niet bestaan
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

# 🔹 API-config
API_KEY = os.getenv("FMP_API_KEY", "JSthYT7gRiNKc0KjNrvQhZ6Ay8UiSpLc")  # <-- later via .env
BASE_URL = "https://financialmodelingprep.com"

YEARS = [2020, 2021, 2022, 2023, 2024]
METRICS = {
    "Revenue": ("income-statement", "revenue"),
    "Operating income": ("income-statement", "operatingIncome"),
    "Net income": ("income-statement", "netIncome"),
    "FCF": ("cash-flow-statement", "freeCashFlow"),
}

BATCH_SIZE = 500        # per batch wegschrijven
MAX_WORKERS = 5         # aantal gelijktijdige API-calls
PAUSE_BETWEEN_CALLS = 0.2


# ======================
# HELPERS
# ======================
def safe_request(url, params=None, max_retries=3, backoff_factor=2):
    """GET met retry & exponentiële backoff."""
    params = params or {}
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 402:
                print(f"⚠️  402 Payment Required: {r.url}")
                return []
            else:
                print(f"⚠️  HTTP {r.status_code} voor {r.url}")
        except Exception as e:
            print(f"❌ Fout: {e}")
        time.sleep(backoff_factor ** attempt)
    return []


def get_fmp_json(endpoint, params=None):
    """Wrapper om queryparams + apikey toe te voegen."""
    params = params.copy() if params else {}
    params["apikey"] = API_KEY
    url = f"{BASE_URL}/stable/{endpoint}"
    return safe_request(url, params=params)


def cache_path(ticker, endpoint):
    safe_ticker = ticker.replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe_ticker}_{endpoint}.json")


def load_from_cache(ticker, endpoint):
    path = cache_path(ticker, endpoint)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_to_cache(ticker, endpoint, data):
    path = cache_path(ticker, endpoint)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def ttm_from_quarters(ticker, field, is_cashflow=False):
    endpoint = "cash-flow-statement" if is_cashflow else "income-statement"
    cache_key = f"{endpoint}_quarter"
    data = load_from_cache(ticker, cache_key)
    if data is None:
        data = get_fmp_json(endpoint, {"symbol": ticker, "period": "quarter", "limit": 4})
        save_to_cache(ticker, cache_key, data)
    if not data:
        return None, None

    recent_quarters = data[:4]
    total = sum((q.get(field, 0) or 0) for q in recent_quarters)
    latest_period = recent_quarters[0].get("period")
    return total / 1_000_000, latest_period


def autosave(df, suffix="partial"):
    temp_xlsx = OUTPUT_XLSX.replace(".xlsx", f"_{suffix}.xlsx")
    temp_parquet = OUTPUT_PARQUET.replace(".parquet", f"_{suffix}.parquet")
    df.to_excel(temp_xlsx, index=False)
    df.to_parquet(temp_parquet, index=False, engine="pyarrow", compression="snappy")
    print(f"💾 Autosave uitgevoerd → {temp_xlsx} & {temp_parquet}")


# ----------------------
# CHECKPOINT SYSTEM
# ----------------------
def load_checkpoint():
    """Lees laatst opgeslagen voortgang."""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_index": 0, "processed_tickers": []}


def save_checkpoint(last_index, processed_tickers):
    """Sla huidige voortgang op."""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_index": last_index, "processed_tickers": processed_tickers}, f)
    print(f"📍 Checkpoint opgeslagen bij index {last_index} ({len(processed_tickers)} tickers verwerkt).")


# ======================
# 1) Alle tickers ophalen
# ======================
print("📥 Ophalen van ALLE tickers wereldwijd...")
tickers_data = safe_request(f"{BASE_URL}/api/v3/stock/list", params={"apikey": API_KEY})
all_tickers = [
    item["symbol"]
    for item in tickers_data
    if item.get("exchangeShortName") in {"NASDAQ", "NYSE", "AMEX"} and item.get("symbol")
]
print(f"✅ {len(all_tickers)} tickers gevonden (NASDAQ, NYSE, AMEX).\n")

# ======================
# 2) Checkpoint laden
# ======================
checkpoint = load_checkpoint()
start_index = checkpoint["last_index"]
processed_tickers = set(checkpoint["processed_tickers"])

remaining_tickers = [t for t in all_tickers[start_index:] if t not in processed_tickers]
print(f"🔁 Hervat vanaf index {start_index}. Nog {len(remaining_tickers)} tickers te verwerken.\n")


# ======================
# 3) Parallel ophalen per batch
# ======================
def fetch_ticker_data(ticker):
    income_annual = load_from_cache(ticker, "income_annual")
    if income_annual is None:
        income_annual = get_fmp_json("income-statement", {"symbol": ticker, "limit": 10})
        save_to_cache(ticker, "income_annual", income_annual)

    cf_annual = load_from_cache(ticker, "cf_annual")
    if cf_annual is None:
        cf_annual = get_fmp_json("cash-flow-statement", {"symbol": ticker, "limit": 10})
        save_to_cache(ticker, "cf_annual", cf_annual)

    return ticker, income_annual, cf_annual


rows = []
batch_num = 1

for i in range(0, len(remaining_tickers), BATCH_SIZE):
    batch_tickers = remaining_tickers[i: i + BATCH_SIZE]
    print(f"\n📦 Batch {batch_num} gestart ({len(batch_tickers)} tickers)...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_ticker_data, t): t for t in batch_tickers}
        for future in tqdm(as_completed(futures), total=len(futures), desc=f"Batch {batch_num}"):
            ticker = futures[future]
            try:
                ticker, income_annual, cf_annual = future.result()
            except Exception as e:
                print(f"⚠️  Fout bij {ticker}: {e}")
                continue

            income_by_year, cf_by_year = {}, {}
            for rec in income_annual or []:
                try:
                    y = int(str(rec.get("date", ""))[:4])
                    income_by_year[y] = rec
                except Exception:
                    pass

            for rec in cf_annual or []:
                try:
                    y = int(str(rec.get("date", ""))[:4])
                    cf_by_year[y] = rec
                except Exception:
                    pass

            for metric_name, (endpoint, field) in METRICS.items():
                row = {"Ticker": ticker, "Metric": metric_name}
                for y in YEARS:
                    rec = income_by_year.get(y) if endpoint == "income-statement" else cf_by_year.get(y)
                    val = rec.get(field) if rec else None
                    row[str(y)] = (val / 1_000_000) if isinstance(val, (int, float)) and val is not None else None

                is_cf = endpoint == "cash-flow-statement"
                ttm_val, ttm_from = ttm_from_quarters(ticker, field, is_cashflow=is_cf)
                row["TTM"] = ttm_val
                row["TTM_from"] = ttm_from

                rows.append(row)

            processed_tickers.add(ticker)
            time.sleep(PAUSE_BETWEEN_CALLS)

    # ---- Autosave + checkpoint na batch ----
    df_batch = pd.DataFrame(rows)
    if os.path.exists(OUTPUT_PARQUET):
        existing_df = pd.read_parquet(OUTPUT_PARQUET)
        df_combined = pd.concat([existing_df, df_batch], ignore_index=True)
    else:
        df_combined = df_batch

    autosave(df_combined, suffix=f"batch_{batch_num}")
    df_combined.to_parquet(OUTPUT_PARQUET, index=False, engine="pyarrow", compression="snappy")

    # Update checkpoint
    last_index = all_tickers.index(batch_tickers[-1])
    save_checkpoint(last_index, list(processed_tickers))

    rows = []  # reset geheugen
    batch_num += 1


# ======================
# 4) Export eindresultaat
# ======================
df_final = pd.read_parquet(OUTPUT_PARQUET)
ordered_cols = ["Ticker", "Metric"] + [str(y) for y in YEARS] + ["TTM", "TTM_from"]
df_final = df_final.reindex(columns=ordered_cols)

df_final.to_excel(OUTPUT_XLSX, index=False)
print(f"✅ Bestand opgeslagen als Excel: {OUTPUT_XLSX}")

print("\n🏁 Klaar! Alle tickers wereldwijd succesvol opgehaald, inclusief checkpoint-herstel.")
