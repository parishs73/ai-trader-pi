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
#    "host": "localhost",
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


# ---------------------------
# LOG MESSAGE
# ---------------------------
def log(message):
    #print(f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}] {message}")
    logger.info(message)


OLLAMA_URL = "http://ollama-service:11434/api/generate"

# OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------------
# NEW: FETCH LATEST MARKET SNAPSHOT FROM POSTGRES
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
            log(f"Executing postgreSQL query for all symbols....")
            cur.execute(query)
            rows = cur.fetchall()

            #Diagnostics
            if rows is None:
                log(f"PostgreSQL returned None from fetchall().")
                return None
            log(f"Database query successful. Found {len(rows)} symbol rows.")

            if len(rows) == 0:
                log(f"The Stock_data table is completely empty. 0 rows returned")
                return None

            for row in rows:
                if row:
                # Convert datetime object to string so it can be JSON serialized safely
                    row['timestamp'] = row['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            return rows

    except Exception as e:
        logging.error(f"Database query error: {e}")
        log(f"Database query error: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ---------------------------
# SAVE TRADING DECISIONS TO ai_signals
# ---------------------------

def save_ai_signal(symbol, price, action, confidence, reasoning):
    """Inserts the AI decision into the ai_signals3 table."""
    query = """
        INSERT INTO ai_signals3 (symbol, price, action, confidence, reasoning, timestamp)
        VALUES (%s, %s, %s, %s, %s, NOW());
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query,(symbol, price, action, confidence, reasoning))
            conn.commit()
            log(f"Successfully save AI Decision to the DB for {symbol}: {action}")
    except Exception as e:
        log(f"Failed to save AI Decision to DB: {e}")
    finally:
        if conn:
            conn.close()

# ---------------------------
# UPDATED: AI DECISION LOGIC WITH DETAILED PROMPT
# ---------------------------
def get_ai_decision(market_snapshot):
    # Give the AI specific trading guidelines since it expects a strict JSON response
    system_instructions = (
        "You are an expert algorithmic trading assistant. Analyze the market snapshot JSON. "
        "Respond strictly in JSON format matching this schema: "
#        '{"action": "BUY"|"SELL"|"HOLD", "symbol": "SYMBOL", "confidence": 0.0-1.0}'
        '{"action": "BUY"|"SELL"|"HOLD", "symbol": "SYMBOL", "confidence": 0.0-1.0, "reasoning": "short explanation text"}'
    )

    payload = {
        "model": "qwen3-trader",
        "prompt": f"{system_instructions}\n\nSnapshot: {json.dumps(market_snapshot)}",
        "format": "json",
        "options": {
            "num_predict": 150,
            "temperature": 0.0
        },
        "stream": False
    }

    fallback_response = {
        "action": "HOLD",
        "symbol": market_snapshot.get("symbol"),
        "confidence": 0.0,
        "reasoning": "Error linking to  Ollama container"
    }


    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60) # Boosted timeout to 60s for Pi 5 CPU & testing
        response.raise_for_status()

        # safe check for empty text bodies
        if not response.text.strip():
            logging.error("Ollama returened an empty response body.")
            log(f"Ollama returned an empty response body.")
            return fallback_response

        # safely parse the outer Ollama layer
        ollama_data = response.json()

        if "error" in ollama_data:
             log(f"Ollama API Error: {ollama_data.get('error')} - Full payload: {ollama_data}")

        raw_ai_response = ollama_data.get("response", "").strip()
        if not raw_ai_response and "thinking" in ollama_data:
            raw_ai_response = ollama_data.get("thinking", "").strip()

        if not raw_ai_response:
            logging.error("Ollama payload did not contain a 'response' field.")
            log(f"Ollama payload did not contain a 'response' field. Received keys: {list(ollama_data.keys())} - Full payload: {ollama_data}")
            return fallback_response

        return json.loads(raw_ai_response)



    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occured: {http_err} - Raw Output: {response.text}")
        log(f"HTTP error occured: {http_err} - Raw Output: {response.text}")
        return fallback_response
    except json.JSONDecodeError as json_err:
        logging.error(f"JSON parsing error: {json_err} -  Raw Model Output was: {response.text}")
        log(f"JSON parsing error: {json_err} -  Raw Model Output was: {response.text}")
        return fallback_response
    except Exception as e:
        logging.error(f"AI Matrix Error: {e}")
        log(f"AI Matrix Error: {e}")
        return fallback_response

if __name__ == "__main__":
    logging.info("AI Strategic Execution engine linked successfully to PostgreSQL.")
    log(f"AI Strategic Execution engine linked successfully to PostgreSQL.")

    # Track the last processed timestamp to avoid feeding the exact same data point to the AI on every loop
    last_processed_times = {}

    while True:
        market_snapshots = get_latest_market_snapshot()
        # 1. Grab fresh data directly from your live Postgres pipeline
#        live_data = get_latest_market_snapshot()

        if market_snapshots and isinstance(market_snapshots, list):
            for snapshot in market_snapshots:
                symbol = snapshot.get("symbol")
                current_timestamp = snapshot.get("timestamp")
                current_price = snapshot.get("price")

                if not symbol or not current_timestamp:
                    log(f"Valid fields?")
                    continue

            # 2. Only process if the specific symbol (symbol)has a brand new data update
                if last_processed_times.get(symbol) != current_timestamp:
                    logging.info(f"Processing new data point for {symbol} at {current_timestamp}")
                    log(f"Processing new data point for {symbol} at {current_timestamp}")

                # 3. Get decision from Ollama container
                    decision = get_ai_decision(snapshot)

                    action = decision.get('action')
                    ai_symbol = decision.get('symbol')
                    confidence = decision.get('confidence')
                    reasoning = decision.get('reasoning', 'No Reason Provided')

                # 4. Log strategic action output
                    logging.info(f"AI_METRIC | Action: {decision.get('action')} | Symbol: {decision.get('symbol')} | Conf: {decision.get('confidence', 0)} | Reason: {decision.get('reasoning')}")
                    log(f"AI_METRIC | Action: {action} | Symbol: {ai_symbol} | Conf: {confidence} | Reason: {reasoning}")

                # Update tracking pointer
                    save_ai_signal(ai_symbol, current_price, action, confidence, reasoning)
                    last_processed_times[symbol] = current_timestamp

                else:
                    logging.debug("No new market updates found in database. Waiting...")
                    log(f"No new market updates found in database. Waiting...")

        # Check database for new tracking updates every 10 seconds
        time.sleep(10)
