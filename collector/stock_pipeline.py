import yfinance as yf
import pandas as pd
import time
import psycopg2
from datetime import datetime, timezone
from ta.momentum import RSIIndicator
import logging
import os

# ---------------------------
# CONFIG
# ---------------------------
TICKERS = ["AAPL", "TSLA", "AMZN", "MSFT", "GOOGL", "META", "NVDA", "JPM", "V", "DIS", "COF", "AZN.L", "4503.T"]

TICKER_META = {
    "AAPL": "Apple Inc.",
    "TSLA": "Tesla Inc.",
    "AMZN": "Amazon.com Inc.",
    "MSFT": "Microsoft Corporation",
    "GOOGL": "Alphabet Inc.",
    "META": "Meta Platforms, Inc.",
    "NVDA": "Nvidia Corporation",
    "JPM": "JPMorgan Chase & Co.",
    "V": "Visa Inc.",
    "DIS": "The Walt Disney Company",
    "COF": "Capital One Financial Corporation",
    "AZN.L": "Astrazeneca PLC",
    "4503.T": "Astellas Pharma Inc."
}

DB_CONFIG = {
    "dbname": "stocks",
    "user": "trader",
    "password": "mypassword",
    #"host": "localhost", # unhash if testing locally and hashout line below
    "host": "postgres",
    "port": 5432
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILENAME = "stock_pipeline.log"
# ---------------------------
# LOGGING
# ---------------------------

os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, LOG_FILENAME)

logging.basicConfig(
     level=logging.INFO,
     format="%(asctime)s [%(levelname)s %(message)s]",
     datefmt="%Y-%m-%d %H:%M:%S %Z",
     handlers=[
          logging.StreamHandler(),      # Docker logs
          logging.FileHandler(LOG_FILE) # File Logs
     ]
)
logger = logging.getLogger(__name__)



# ---------------------------
# DB CONNECTION
# ---------------------------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------------
# FETCH DATA
# ---------------------------

def fetch_data(symbol):
    #df = yf.download(symbol, period="2d", interval="1m", progress=False)
    ticker =yf.Ticker(symbol)
    df = ticker.history(period="2d", interval="1m", auto_adjust=True)

    if df.empty:
        log(f"No data returned for {symbol} (Market might be closed)")
        return None

    # 🔥 FIX: flatten yfinance structure
    if isinstance(df.columns, pd.MultiIndex):
        #df.columns = df.columns.get_level_values(0)
        df.columns = df.columns.droplevel(1)
    # Clean series extraction of RSI
    #close = df["Close"].astype(float).squeeze()
    close_series = df["Close"].astype(float)

    # Calculate RSI
    #rsi_series = RSIIndicator(close=close, window=14).rsi()
    rsi_series = RSIIndicator(close=close_series, window=14).rsi()

    # Extract final row
    row = df.iloc[-1]

    # Safely hanbdle RSI value extraction
    #rsi_value = rsi_series.dropna().iloc[-1]
    valid_rsi = rsi_series.dropna()
    if valid_rsi.empty:
       log(f"Not enough data to calculate RSI for {symbol}")
       rsi_value = None
    else:
       rsi_value = float(valid_rsi.iloc[-1])

    data= {
        "symbol": symbol,
        "timestamp": row.name.to_pydatetime(),
        "name": TICKER_META.get(symbol, symbol),
        "open": float(row["Open"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "close": float(row["Close"]),
        "volume": int(row["Volume"]),
        "rsi": rsi_value
    }

    log(f"Data downloaded for {data['name']}")

    return data

# ---------------------------
# SAVE TO DB
# ---------------------------
def save_to_db(conn, data):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO stock_data
            (symbol, timestamp, name, open, high, low, close, volume, rsi)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol, timestamp) Do NOTHING;
        """, (
            data["symbol"],
            data["timestamp"],
            data["name"],
            data["open"],
            data["high"],
            data["low"],
            data["close"],
            data["volume"],
            data["rsi"]
        ))
    conn.commit()

# ---------------------------
# Check for existing values
# ---------------------------
def check_if_exists(conn, symbol, timestamp):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 from stock_data where symbol = %s and timestamp = %s limit 1;",
            (symbol, timestamp)
        )
        return cur.fetchone() is not None

# ---------------------------
# LOG MESSAGE
# ---------------------------
def log(message):
    #print(f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}] {message}")
    logger.info(message)


# ---------------------------
# MAIN LOOP
# ---------------------------
def run_once():
    conn= None
    try:
        conn = get_conn()
        log("Starting stock pipeline...")

#    print("Starting stock pipeline...")

#    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting stock pipeline....")
    #while True:
        for symbol in TICKERS:
            data = fetch_data(symbol)
            log(f"Fetching data for {data['name']} stocks...")
 
            if data:
                 if check_if_exists(conn, data["symbol"], data["timestamp"]):
                    log(f"Skipping {symbol}: Timestamp {data['timestamp']} already in database.")
                    continue
                 log(f"Writing {data['name']} to PostgreSQL....")
                 save_to_db(conn, data)
                 log(f"Saved {data['name']}, {symbol} @ {data['close']}")
            else:
                 log(f"Skipping DB write fo {symbol} due to missing data.")
        log("Pipeline Complete")
    except Exception as e:
            #print("Error:", e)
            log(f"ERROR: {e}")
            time.sleep(10)
    
    finally:
        if conn:
            conn.close()
            log("Database connection closed")

if __name__ == "__main__":
    run_once()
