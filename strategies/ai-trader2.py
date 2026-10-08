# ai-tradeer2.py
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

os.makedirs("logs", exist_ok=True)

LOG_FILE = "logs/ai-executor.log"

logging.basicConfig(
     level=logging.INFO,
     format="%(asctime)s [%(levelname)s %(message)s]",
     datefmt="%Y-%m-%d %H:%M:%S %Z",
     handlers=[
          logging.StreamHandler(),      # Docker logs
          logging.FileHandler(LOG_FILE, delay=True) # File Logs
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
# --------------------------
# NEW FEATURE: FETCH PORTFOLIO POSITION FROM POSTGRES
# --------------------------

def get_portfolio_position(symbol):
    """Checxks if we currently own an open position for these stocks"""

    query = """
        SELECT quantity, avg_cost
        FROM portfolio_positions
        WHERE symbol = %s 
        AND quantity > 0
        LIMIT 1;
        """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            log(f"Executing postrgeSQL query to fetch current owned open position for {symbol}.")
            cur.execute(query, (symbol,))
        # does a position exist
            position = cur.fetchone()
            if position:
               quantity = position['quantity']
               avg_cost = position['avg_cost']
               log(f"Position for {symbol} - quantity={quantity}, average cost = {avg_cost}.")
            else:
               log(f"No position exists for {symbol}")

            return position
    except Exception as e:
        logging.error(f"Error fetching portfolio state for {symbol}: {e}")
        log(f"Error fetching portfolio state for {symbol}: {e}")
        return None
    finally:
        if conn:
            conn.close()



# ---------------------------
# NEW: FETCH LATEST MARKET SNAPSHOT FROM POSTGRES
# ---------------------------
def get_latest_market_snapshot():
    """Queries Postgres for the single most recently added stock data point."""
    query = """
        SELECT distinct on (symbol) symbol, close as price, open, high, low, volume, rsi, timestamp
        FROM stock_data
        ORDER BY symbol, timestamp DESC;
    """

    conn = None
    try:
        conn = get_conn()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            log(f"Executing postgreSQL query to fetch latest market snapshot for all symbols....")
            cur.execute(query)
            rows = cur.fetchall()

            #Diagnostics
            if rows is None:
                log(f"PostgreSQL returned None from fetchall().")
                return None
            log(f"Database query successful. Found {len(rows)} rows.")

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

# --------------------------
# Market Metrics
# --------------------------
def calculate_market_metrics(symbol):

    """
    Retrieve recent market data for a symbol and calculate
    technical metrics for the AI trading model.

    Returns a dictionary containing the latest market data
    and calculated technical indicators.
    """

    query = """
        SELECT
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            rsi
        FROM stock_data
        WHERE symbol = %s
        ORDER BY timestamp DESC
        LIMIT 50;
    """

    conn = None

    try:
        conn = get_conn()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            log(f"Calculating market metrics for {symbol}")

            cur.execute(query, (symbol,))
            rows = cur.fetchall()

            if not rows:
                log(f"No market data found for {symbol}")
                return None

            # PostgreSQL returns newest first.
            # Reverse it so calculations run oldest -> newest.
            rows = list(reversed(rows))

            # --------------------------------------------------
            # BASIC DATA
            # --------------------------------------------------

            latest = rows[-1]

            current_price = float(latest["close"])
            current_rsi = (
                float(latest["rsi"])
                if latest["rsi"] is not None
                else None
            )

            # --------------------------------------------------
            # SMA20
            # --------------------------------------------------

            sma20 = None

            if len(rows) >= 20:

                last_20_prices = [
                    float(row["close"])
                    for row in rows[-20:]
                    if row["close"] is not None
                ]

                if len(last_20_prices) == 20:
                    sma20 = sum(last_20_prices) / 20

            # --------------------------------------------------
            # SMA50
            # --------------------------------------------------

            sma50 = None

            if len(rows) >= 50:

                last_50_prices = [
                    float(row["close"])
                    for row in rows[-50:]
                    if row["close"] is not None
                ]

                if len(last_50_prices) == 50:
                    sma50 = sum(last_50_prices) / 50

            # --------------------------------------------------
            # RSI DIRECTION
            # --------------------------------------------------

            rsi_direction = "UNKNOWN"

            if len(rows) >= 2:

                previous_rsi = rows[-2]["rsi"]

                if previous_rsi is not None and current_rsi is not None:

                    previous_rsi = float(previous_rsi)

                    if current_rsi > previous_rsi:
                        rsi_direction = "RISING"

                    elif current_rsi < previous_rsi:
                        rsi_direction = "FALLING"

                    else:
                        rsi_direction = "FLAT"

            # --------------------------------------------------
            # 5 PERIOD MOMENTUM
            # --------------------------------------------------

            momentum_5 = None

            if len(rows) >= 6:

                price_5_periods_ago = float(
                    rows[-6]["close"]
                )

                if price_5_periods_ago != 0:

                    momentum_5 = (
                        (current_price - price_5_periods_ago)
                        / price_5_periods_ago
                    ) * 100

            # --------------------------------------------------
            # 20 PERIOD MOMENTUM
            # --------------------------------------------------

            momentum_20 = None

            if len(rows) >= 21:

                price_20_periods_ago = float(
                    rows[-21]["close"]
                )

                if price_20_periods_ago != 0:

                    momentum_20 = (
                        (current_price - price_20_periods_ago)
                        / price_20_periods_ago
                    ) * 100

            # --------------------------------------------------
            # PRICE VS SMA20
            # --------------------------------------------------

            price_vs_sma20 = None

            if sma20 is not None and sma20 != 0:

                price_vs_sma20 = (
                    (current_price - sma20)
                    / sma20
                ) * 100

            # --------------------------------------------------
            # PRICE VS SMA50
            # --------------------------------------------------

            price_vs_sma50 = None

            if sma50 is not None and sma50 != 0:

                price_vs_sma50 = (
                    (current_price - sma50)
                    / sma50
                ) * 100

            # --------------------------------------------------
            # VOLUME
            # --------------------------------------------------

            current_volume = (
                float(latest["volume"])
                if latest["volume"] is not None
                else None
            )

            average_volume = None
            volume_ratio = None

            volumes = [
                float(row["volume"])
                for row in rows
                if row["volume"] is not None
            ]

            if len(volumes) >= 20:

                average_volume = (
                    sum(volumes[-20:]) / 20
                )

                if average_volume > 0 and current_volume is not None:

                    volume_ratio = (
                        current_volume / average_volume
                    )

            # --------------------------------------------------
            # BUILD RESULT
            # --------------------------------------------------

            metrics = {
                "symbol": symbol,

                "price": round(current_price, 4),

                "rsi": (
                    round(current_rsi, 2)
                    if current_rsi is not None
                    else None
                ),

                "rsi_direction": rsi_direction,

                "sma20": (
                    round(sma20, 4)
                    if sma20 is not None
                    else None
                ),

                "sma50": (
                    round(sma50, 4)
                    if sma50 is not None
                    else None
                ),

                "price_vs_sma20_percent": (
                    round(price_vs_sma20, 2)
                    if price_vs_sma20 is not None
                    else None
                ),

                "price_vs_sma50_percent": (
                    round(price_vs_sma50, 2)
                    if price_vs_sma50 is not None
                    else None
                ),

                "momentum_5_period_percent": (
                    round(momentum_5, 2)
                    if momentum_5 is not None
                    else None
                ),

                "momentum_20_period_percent": (
                    round(momentum_20, 2)
                    if momentum_20 is not None
                    else None
                ),

                "volume": (
                    int(current_volume)
                    if current_volume is not None
                    else None
                ),

                "average_volume": (
                    int(average_volume)
                    if average_volume is not None
                    else None
                ),

                "volume_ratio": (
                    round(volume_ratio, 2)
                    if volume_ratio is not None
                    else None
                ),

                "data_points_used": len(rows),

                "timestamp": (
                    latest["timestamp"].strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    if latest["timestamp"] is not None
                    else None
                )
            }

            log(
                f"Market metrics for {symbol}: "
                f"price={metrics['price']} "
                f"RSI={metrics['rsi']} "
                f"SMA20={metrics['sma20']} "
                f"SMA50={metrics['sma50']} "
                f"momentum5={metrics['momentum_5_period_percent']}% "
                f"momentum20={metrics['momentum_20_period_percent']}% "
                f"volume_ratio={metrics['volume_ratio']}"
            )

            return metrics

    except Exception as e:

        log(
            f"Error calculating market metrics "
            f"for {symbol}: {e}"
        )

        return None

    finally:

        if conn:
            conn.close()

# ---------------------------
# SAVE TRADING DECISIONS TO ai_signals
# ---------------------------

def save_ai_signal(symbol, price, action, confidence, reasoning):
    """Inserts the AI decision into the ai_signals table."""
    query = """
        INSERT INTO ai_signals (symbol, price, action, confidence, reasoning, timestamp)
        VALUES (%s, %s, %s, %s, %s, NOW());
    """
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query,(symbol, price, action, confidence, reasoning))
            conn.commit()
            log(f"Successfully saved AI Decision to the DB for {symbol}: {action}")
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
    # Expanded instructions so the low-temperature Qwen layer calculates asset exit triggers
    system_instructions = """
    You are qwen3-trader, a stock trading decision engine.

    Your task is to analyze the supplied market data and portfolio position
    and choose exactly one action:

    BUY
    SELL
    HOLD

    Do NOT automatically choose HOLD.

    Use the available evidence to determine whether the stock has a stronger
    BUY case, stronger SELL case, or no clear signal.

    BUY RULES

    BUY is only possible when portfolio_holding is null or shares_owned is 0.
F
    Positive BUY evidence includes:

    - RSI below 30: strong BUY evidence
    - RSI 30-40: moderate BUY evidence
    - RSI rising after being below 40: positive
    - Positive short-term momentum: positive
    - Price recovering from a recent decline: positive
    - Price moving above SMA20: positive
    - Price above SMA20 and SMA50: positive
    - Higher-than-average volume during price recovery: positive

    Negative BUY evidence includes:

    - RSI above 70
    - Strong negative momentum
    - Price below SMA20 and SMA50
    - Strong downward trend

    SELL RULES

    SELL is only possible when portfolio_holding contains shares.

    Positive SELL evidence includes:

    - RSI above 70: moderate SELL evidence
    - RSI above 75: strong SELL evidence
    - RSI falling after being overbought: positive SELL evidence
    - Negative short-term momentum
    - Price falling below SMA20
    - Price below SMA20 and SMA50
    - Strong downward reversal
    - Large negative movement with increased volume
    - Existing position has reached a reasonable profit target

    Do NOT sell simply because the position is profitable.

    HOLD RULES

    Choose HOLD when the evidence for BUY and SELL is weak or mixed.

    Examples:

    - RSI around 40-60
    - Weak momentum
    - Mixed trend indicators
    - No clear reversal
    - Existing position has no strong exit signal

    CONFIDENCE

    Confidence MUST be a number between 0.0 and 1.0.

    Use:

    0.90-1.00 = extremely strong evidence
    0.75-0.89 = strong evidence
    0.60-0.74 = moderate evidence
    0.50-0.59 = weak evidence

    Do not use words such as "high", "medium" or "low".

    REASONING

    You MUST provide reasoning for every decision.

    The reasoning must state the main indicators that caused the decision.

    Do not return an empty reasoning field.

    OUTPUT

    Return ONLY valid JSON in exactly this format:

    {
    "action": "BUY",
    "symbol": "AAPL",
    "confidence": 0.82,
    "reasoning": "RSI is oversold and rising while short-term momentum is recovering."
    }

    The action must be exactly BUY, SELL or HOLD.

    The confidence must be numeric.

    The reasoning must be a short explanation.

    Never return markdown.
    Never return additional fields.
    """

    payload = {
        "model": "qwen3-trader",
        "system": system_instructions,
        "prompt": f"""
            Analyse this market snapshot and make one trading decision
            Market snapshot:
            {json.dumps(market_snapshot, indent=2)}
            
            Return the required JSON decision
            """,
        "format": "json",
        "options": {
            "num_predict": 250,
            "temperature": 0.1
        },
        "stream": False
    }

    fallback_response = {
        "action": "HOLD",
        "symbol": market_snapshot.get("symbol"),
        "confidence": 0.0,
        "reasoning": "Ai decision unavailable - Ollama request failed"
    }


    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120) # Boosted timeout to 60s for Pi 5 CPU & testing
        response.raise_for_status()

        # safe check for empty text bodies
        if not response.text.strip():
            logging.error("Ollama returned an empty response body.")
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

        #return json.loads(raw_ai_response)
    # Parse Qwen's JSON response
        decision = json.loads(raw_ai_response)

        # --------------------------------------------------
        # VALIDATE AI RESPONSE
        # --------------------------------------------------

        action = decision.get("action")
        ai_symbol = decision.get("symbol")
        confidence = decision.get("confidence")
        reasoning = decision.get("reasoning")

        # Normalise action
        if action:
            action = str(action).upper()

        # Validate action
        if action not in ["BUY", "SELL", "HOLD"]:
            log(
                f"Invalid AI action returned: {action}. "
                f"Full decision: {decision}"
            )

            return {
                "action": "HOLD",
                "symbol": market_snapshot.get("symbol"),
                "confidence": 0.0,
                "reasoning": "AI returned an invalid trading action"
            }

        # Validate confidence
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            log(
                f"Invalid AI confidence returned: {confidence}"
            )
            confidence = 0.0

        # Keep confidence within valid range
        confidence = max(0.0, min(1.0, confidence))

        # Validate reasoning
        if not reasoning:
            reasoning = "No reasoning provided by AI"

        # --------------------------------------------------
        # SAFETY CHECKS
        # --------------------------------------------------

        portfolio_holding = market_snapshot.get("portfolio_holding")

        # BUY is only allowed when we don't already own the stock
        if action == "BUY":

            if portfolio_holding is not None:

                shares_owned = portfolio_holding.get(
                    "shares_owned", 0
                )

                if shares_owned > 0:

                    log(
                        f"SAFETY: AI requested BUY for "
                        f"{market_snapshot.get('symbol')} but "
                        f"already owns {shares_owned} shares. "
                        f"Changing BUY -> HOLD."
                    )

                    action = "HOLD"
                    confidence = 0.0
                    reasoning = (
                        "AI BUY rejected by safety check because "
                        "a position is already held."
                    )

        # SELL is only allowed when we actually own the stock
        if action == "SELL":

            if portfolio_holding is None:

                log(
                    f"SAFETY: AI requested SELL for "
                    f"{market_snapshot.get('symbol')} but "
                    f"no position is held. "
                    f"Changing SELL -> HOLD."
                )

                action = "HOLD"
                confidence = 0.0
                reasoning = (
                    "AI SELL rejected by safety check because "
                    "no position is currently held."
                )

        # --------------------------------------------------
        # RETURN CLEAN DECISION
        # --------------------------------------------------

        return {
            "action": action,
            "symbol": ai_symbol or market_snapshot.get("symbol"),
            "confidence": confidence,
            "reasoning": reasoning
}

        log(f"response text = {response.text}")

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

                    # --- FIXED STEP: Fetch database exposure before asking Ollama ---
                    position = get_portfolio_position(symbol)

                    metrics = calculate_market_metrics(symbol)

                    if metrics is None:
                        log(f"Unable to calculate market metrics for {symbol}")
                        continue
                    snapshot = metrics

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

                    action = decision.get('action')
                    if not action:
                        action = "HOLD"
                    else:
                        action = str(action).upper() # Safeguard: converts "buy"
                    ai_symbol = decision.get('symbol')
                    confidence = decision.get('confidence')
                    reasoning = decision.get('reasoning', 'No Reason Provided')

                # 4. Log strategic action output
#                    logging.info(f"AI_METRIC | Action: {decision.get('action')} | Symbol: {decision.get('symbol')} | Conf: {decision.get('confidence', 0)} | Reason: {decision.get('reasoning')}")
                    log(f"AI_METRIC | Action: {action} | Symbol: {ai_symbol} | Conf: {confidence} | Reason: {reasoning}")

                # Update tracking pointer
                    save_ai_signal(ai_symbol, current_price, action, confidence, reasoning)
                    last_processed_times[symbol] = current_timestamp

                else:
                    logging.debug("No new market updates found in database. Waiting...")
                    log(f"No new market updates found in database. Waiting...")

        # Check database for new tracking updates every 10 seconds
        time.sleep(10)
