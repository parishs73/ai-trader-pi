import yfinance as yf
import pandas as pd
import time
import psycopg2
from datetime import datetime, timezone
from ta.momentum import RSIIndicator

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
    "host": "localhost",
    "port": 5432
}

# ---------------------------
# DB CONNECTION
# ---------------------------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------------
# FETCH DATA
# ---------------------------

def fetch_data(symbol):
    df = yf.download(symbol, period="2d", interval="1m", progress=False)

    if df.empty:
        log(f"No data returned for {data['name']}, {symbol}")
        return None

    # 🔥 FIX: flatten yfinance structure
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df["Close"].astype(float).squeeze()
    rsi_series = RSIIndicator(close=close, window=14).rsi()

    row = df.iloc[-1]
    rsi_value = rsi_series.dropna().iloc[-1]

    data= {
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc),
        "name": TICKER_META.get(symbol, symbol),
        "open": float(row["Open"].item() if hasattr(row["Open"], "item") else row["Open"]),
        "high": float(row["High"].item() if hasattr(row["High"], "item") else row["High"]),
        "low": float(row["Low"].item() if hasattr(row["Low"], "item") else row["Low"]),
        "close": float(row["Close"].item() if hasattr(row["Close"], "item") else row["Close"]),
        "volume": int(row["Volume"].item() if hasattr(row["Volume"], "item") else row["Volume"]),

        "rsi": float(rsi_value)

    }
    log(f"Data downloaded for {data['name']}")

    return data

# def fetch_data(symbol):
#     df = yf.download(symbol, period="2d", interval="1m") # changed 1d to 2d
#     df.columns = df.columns.get_level_values(0)
#     #df = df.tail(1)  # latest candle only

#     if df.empty:
#         return None

#     #~#df = df.astype(float)

#     #df["RSI"] = RSIIndicator(close=df["Close"]).rsi()  - change with discussion with chatgpt
#     # Newe code to make it work
#     close = df["Close"].astype(float).squeeze()
#     rsi_series = RSIIndicator(close=close, window=14).rsi()

#     #row = df.iloc[-1] # changed 0 to -1 changed to line below
#     row = df.iloc[-1]
#     #rsi_value = rsi_series.iloc[-1] # changed to line below
#     rsi_value = float(rsi_series.dropna().iloc[-1])

#     return {
#         "symbol": symbol,
#         "timestamp": datetime.now(timezone.utc),
#         #"timestamp": datetime.utcnow(),
#         "open": float(row["Open"]),
#         "high": float(row["High"]),
#         "low": float(row["Low"]),
#         "close": float(row["Close"]),
#         "volume": int(row["Volume"]),
#         "rsi": float(rsi_value) if pd.notna(rsi_value) else None
#     }

# ---------------------------
# SAVE TO DB
# ---------------------------
def save_to_db(conn, data):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO stock_data
            (symbol, timestamp, name, open, high, low, close, volume, rsi)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
# LOG MESSAGE
# ---------------------------
def log(message):
    print(f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}] {message}")



# ---------------------------
# MAIN LOOP
# ---------------------------
def run_once():
    conn = get_conn()
    log("Starting stock pipeline...")

#    print("Starting stock pipeline...")

#    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting stock pipeline....")
    #while True:
    try:
            for symbol in TICKERS:
                data = fetch_data(symbol)
                log(f"Fetching data for {data['name']} stocks...")
                
                if data:
                    log(f"Writing {data['name']} to PostgreSQL....")
                    save_to_db(conn, data)
                    #print(f"Saved {symbol} @ {data['close']}")
                    log(f"Saved {data['name']}, {symbol} @ {data['close']}")

     #       time.sleep(10)
            log("Pipeline Complete")
    except Exception as e:
            #print("Error:", e)
            log(f"ERROR: {e}")
            time.sleep(10)
    
    finally:
            conn.close()
            log("Database connection closed")

if __name__ == "__main__":
    run_once()
