# ai-trader-google.py
import os
import json
import logging
import requests
import time
import psycopg2
from psycopg2.extras import RealDictCursor  # Allows pulling data as a clean dictionary
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": "stocks",
    "user": "trader",
    "password": "mypassword",
    "host": "postgres",

    "port": 5432
}

# Direct log outputs to your centralized logs folder
#logging.basicConfig(
#    level=logging.INFO,
#    format='%(asctime)s [%(levelname)s] %(message)s',
#    handlers=[logging.FileHandler("/home/simon/ai-trader/logs/ai-trader2.log"), logging.StreamHandler()]
#)

# ---------------------------
# LOGGING
# ---------------------------

os.makedirs("/logs", exist_ok=True)

LOG_FILE = "/logs/ai-executor.log"

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

def log(message):
    logger.info(message)

OLLAMA_URL = "http://ollama-service:11434/api/generate"

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------------
# NEW FEATURE: FETCH CURRENT ASSET EXPOSURE FROM DB
# ---------------------------
def get_portfolio_position(symbol):
    """Checks if we currently own an open position for this ticker."""
    query = """
        SELECT quantity, avg_cost 
        FROM portfolio_positions 
        WHERE symbol = %s LIMIT 1;
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (symbol,))
            return cur.fetchone()
    except Exception as e:
        logging.error(f"Error fetching portfolio state for {symbol}: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ---------------------------
# FETCH LATEST MARKET SNAPSHOT FROM POSTGRES
# ---------------------------
def get_latest_market_snapshot():
    """Queries Postgres for the single most recently added stock data point."""
    query = """
        SELECT distinct on (symbol) symbol, close as price, rsi, timestamp 
        FROM stock_data 
        ORDER BY symbol, timestamp DESC;
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            log(f"Executing postgreSQL query for all tickers....")
            cur.execute(query)
            rows = cur.fetchall()

            if rows is None:
                log(f"PostgreSQL returned None from fetchall().")
                return None
            log(f"Database query successful. Found {len(rows)} ticker rows.")

            if len(rows) == 0:
                log(f"The Stock_data table is completely empty. 0 rows returned")
                return None

            for row in rows: 
                if row:
                    row['timestamp'] = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            return rows
    except Exception as e:
        logging.error(f"Database query error: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ---------------------------
# SAVE TRADING DECISIONS TO ai_signals
# ---------------------------
def save_ai_signal(ticker, price, action, confidence, reasoning):
    """Inserts the AI decision into the ai_signals table."""
    query = """
        INSERT INTO ai_signals (ticker, price, action, confidence, reasoning, timestamp)
        VALUES (%s, %s, %s, %s, %s, NOW());
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, (ticker, price, action, confidence, reasoning))
            conn.commit()
            log(f"Successfully saved AI Decision to the DB for {ticker}: {action}")
    except Exception as e:
        log(f"Failed to save AI Decision to DB: {e}")
    finally:
        if conn:
            conn.close()

# ---------------------------
# AI DECISION LOGIC WITH PORTFOLIO MANAGEMENT CONTEXT
# ---------------------------
def get_ai_decision(market_snapshot):
    # Expanded instructions so the low-temperature Qwen layer calculates asset exit triggers
    system_instructions = (
        "You are an expert quantitative algorithmic trading agent. Analyze the provided market snapshot "
        "and current portfolio holding state to output trade execution decisions.\n\n"
        "Trading Rules:\n"
        "1. BUY: Only suggest BUY if 'portfolio_holding' is null and market data shows strong entry metrics.\n"
        "2. SELL: Suggest SELL if 'portfolio_holding' contains shares AND the current price meets profit targets, "
        "drops below stop-loss risk tolerance thresholds, or technical signals reverse.\n"
        "3. HOLD: Suggest HOLD if you currently own the shares and trend is stable, or if no trade setup is present.\n\n"
         "Respond strictly in JSON matching this schema:\n"
        '{"action": "BUY"|"SELL"|"HOLD", "ticker": "SYMBOL", "confidence": 0.0-1.0, "reasoning": "short explanation text"}'
    )
    
    payload = {
        "model": "qwen3-trader",
        "prompt": f"{system_instructions}\n\nSnapshot Context:\n{json.dumps(market_snapshot, indent=2)}",
        "format": "json",
        "options": {
            "num_predict": 150,
            "temperature": 0.0
        },
        "stream": False
    }

    fallback_response = {
        "action": "HOLD",
        "ticker": market_snapshot.get("symbol"),
        "confidence": 0.0,
        "reasoning": "Error linking to Ollama container"
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()

        if not response.text.strip():
            logging.error("Ollama returned an empty response body.")
            return fallback_response

        ollama_data = response.json()
        raw_ai_response = ollama_data.get("response", "").strip()
        
        if not raw_ai_response and "thinking" in ollama_data:
            raw_ai_response = ollama_data.get("thinking", "").strip()

        if not raw_ai_response:
            return fallback_response

        return json.loads(raw_ai_response)

    except Exception as e:
        logging.error(f"AI Execution Loop Error: {e}")
        return fallback_response

if __name__ == "__main__":
    logging.info("AI Strategic Execution engine linked successfully to PostgreSQL.")
    
    last_processed_times = {}
    
    while True:
        market_snapshots = get_latest_market_snapshot()

        if market_snapshots and isinstance(market_snapshots, list):
            for snapshot in market_snapshots:
                ticker = snapshot.get("symbol")
                current_timestamp = snapshot.get("timestamp")
                current_price = snapshot.get("price")

                if not ticker or not current_timestamp:
                    continue
            
                # Only process if the specific ticker has a brand new timestamp update
                if last_processed_times.get(ticker) != current_timestamp:
                    logging.info(f"Processing data loop for {ticker} at {current_timestamp}")
                    
                    # --- FIXED STEP: Fetch database exposure before asking Ollama ---
                    position = get_portfolio_position(ticker)
                    
                    if position:
                        pnl_pct = ((current_price - float(position['avg_cost'])) / float(position['avg_cost'])) * 100
                        snapshot["portfolio_holding"] = {
                            "shares_owned": int(position['quantity']),
                            "average_buy_cost": float(position['avg_cost']),
                            "unrealized_pnl_percent": round(pnl_pct, 2)
                        }
                    else:
                        snapshot["portfolio_holding"] = None
                    
                    # Ask Ollama with full contextual awareness
                    decision = get_ai_decision(snapshot)
                    
                    action = decision.get("action", "HOLD")
                    confidence = decision.get("confidence", 0.0)
                    reasoning = decision.get("reasoning", "Processed via routine loop execution.")
                    
                    # Save decision row down to db for the database execution script to pick up
                    save_ai_signal(ticker, current_price, action, confidence, reasoning)
                    
                    # Update snapshot tracking memory
                    last_processed_times[ticker] = current_timestamp
        
        # Idle brief rest to clear Raspberry Pi CPU load spikes
        time.sleep(5)
