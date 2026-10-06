import psycopg2
import logging
import os
from datetime import datetime, timezone

# ---------------------------
# DB CONFIG
# ---------------------------
DB_CONFIG = {
    "host": "postgres",
    "database": "stocks",
    "user": "trader",
    "password": "mypassword",
}

STARTING_CASH = 100000
POSITION_SIZE = 5000
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILENAME = "paper_trading_test.log"
# ---------------------------
# DB CONNECTION
# ---------------------------

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

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
# LOG MESSAGE
# ---------------------------
def log(message):
    #print(f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}] {message}")
    logger.info(message)

# --------------------------
# GET LATEST PRICES
# -------------------------

def get_latest_price(conn, cur, symbol):
    
    cur.execute(
        "select close FROM stock_data where symbol = %s order by timestamp DESC Limit 1;",
            (symbol)
    )

    return cur.fetchone() is not None

# -------------------------
# GET CASH BALANCE
# -------------------------

def get_cash_balance(cur):

    cur.execute("""
        SELECT cash_balance
        FROM ps2
        ORDER BY updated_at DESC
        LIMIT 1
    """)

    return float(cur.fetchone()[0])
    
# --------------------------
# GET POSITION
# --------------------------

def get_position(conn, cur, symbol):
    cur.execute(
        "Select quantity, avg_cost from pp2 where symbol = %s",
        (symbol)
    )
    return cur.fetchone()

# -------------------------
# EXECUTE BUY
# -------------------------

def execute_buy(conn, cur, signal_id, symbol):
    
    price= get_latest_price(cur, symbol)

    if not price:
        return
    
    existing = get_position(cur, symbol)

    if existing:
        logging.info(f"{symbol} already owned")
        return
    
    cash = get_cash_balance(cur)

    shares = int(POSITION_SIZE / price)

    cost = shares * price

    if cost > cash:
        log(f"WARNING:Insufficient cash")
        return
    

    cur.execute(
        "INSERT into pt2 (timestamp, symbol, trade_type, quantity, price, trade_value, signal_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (datetime.now(timezone.utc), symbol, "BUY", shares, price, cost, signal_id)
    )

    cur.execute(
        "INSERT INTO pp2(symbol, quantity, avg_cost) VALUES (%s,%s,%s)",
        (symbol,shares,price)
    )

    cur.execute(
        "update ps2 set cash_balance = cash_balance -%s, updated_at = now()",
        (cost,)
    )

    conn.commit()
    log(f"Bought {shares} of {symbol} at {price} for {cost}")



# ---------------------
# EXECUTE SELL
# ---------------------

def execute_sell(conn, cur, signal_id, symbol):
    position = get_position(cur, symbol)
    if not position:
        return
    quantity, avg_cost = position
    price = get_latest_price(cur, symbol)
    proceeds = quantity * price
    profit = (price - avg_cost) * quantity

    cur.execute(
        "insert into pt2 (timestamp, symbol,trade_type,quantity,price,trade_value,signal_id) Values (%s,%s,%s,%s,%s,%s,%s)",
        (datetime.now(timezone.utc),symbol,"SELL",quantity,price,proceeds,signal_id)
    )
    cur.execute(
        "delete from pp2 where symbol =%s",
        (symbol,)
    )
    cur.execute(
        """update ps2 set cash_balance = cash_balance + %s,
            realized_pnl = realized_pnl + %s,
            updated_at = NOW()""",
            (proceeds,profit)
    )
    

    conn.commit()
    
    logging.info(f"SELL {quantity} {symbol} @ {price}")

# ---------------------
# UPDATE PROFIT/LOSS
# ---------------------
def update_positions(cur):

    cur.execute("""
        SELECT symbol,
               quantity,
               avg_cost
        FROM pp2
    """)

    positions = cur.fetchall()

    total_unrealized = 0

    for symbol, qty, avg_cost in positions:

        current_price = get_latest_price(
            cur,
            symbol
        )

        market_value = qty * current_price

        pnl = (
            current_price - avg_cost
        ) * qty

        total_unrealized += pnl

        cur.execute("""
            UPDATE pp2
            SET current_price=%s,
                market_value=%s,
                unrealized_pnl=%s,
                updated_at=NOW()
            WHERE symbol=%s
        """,
        (
            current_price,
            market_value,
            pnl,
            symbol
        ))


# ------------------------
# UPDATE PORTFOLIO VALUE
# ------------------------
def update_portfolio_summary(cur):

    cur.execute("""
        SELECT cash_balance,
               realized_pnl
        FROM ps2
        ORDER BY updated_at DESC
        LIMIT 1
    """)

    cash, realized = cur.fetchone()

    cur.execute("""
        SELECT
        COALESCE(
            SUM(market_value),
            0
        ),
        COALESCE(
            SUM(unrealized_pnl),
            0
        )
        FROM pp2
    """)

    market_value, unrealized = cur.fetchone()

    total_value = cash + market_value

    total_return = (
        (total_value - STARTING_CASH)
        / STARTING_CASH
    ) * 100

    cur.execute("""
        UPDATE ps2
        SET portfolio_value=%s,
            unrealized_pnl=%s,
            total_return_pct=%s,
            updated_at=NOW()
    """,
    (
        total_value,
        unrealized,
        total_return
    ))


# -------------------------
# PROCESS SIGNALS
# -------------------------

def process_signals(conn, cur):

    cur.execute("""
        SELECT id,
               symbol,
               action
        FROM ai_signals2
        WHERE processed = FALSE
        ORDER BY timestamp
    """)

    signals = cur.fetchall()

    for signal_id, symbol, action in signals:

        if action == "BUY":
            execute_buy(
                conn,
                cur,
                signal_id,
                symbol
            )

        elif action == "SELL":
            execute_sell(
                conn,
                cur,
                signal_id,
                symbol
            )

        cur.execute("""
            UPDATE ai_signals2
            SET processed = TRUE
            WHERE id = %s
        """,
        (signal_id,))

# -----------------------
# Main Function
# -----------------------
def main():
    conn = get_conn()
    cur = conn.cursor()

    process_signals(conn, cur)

    update_positions(cur)

    update_portfolio_summary(cur)

    conn.commit()

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()