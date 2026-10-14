import psycopg2
import logging
import os
from datetime import datetime, timezone

# ---------------------------
# DB CONFIG
# ---------------------------
DB_CONFIG = {
    "host": "postgres",
#    "host": "localhost",
    "database": "stocks",
    "user": "trader",
    "password": "mypassword",
}

STARTING_CASH = 100000
POSITION_SIZE = 5000
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILENAME = "paper_trading.log"
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

def get_latest_price(cur, symbol):

    cur.execute(
        "select close FROM stock_data where symbol = %s order by timestamp DESC Limit 1;",
            (symbol,)
    )

    row = cur.fetchone()
    if row:
        return float(row[0])

    return None

# -------------------------
# GET CASH BALANCE
# -------------------------

def get_cash_balance(cur):

        cur.execute(
            "SELECT cash_balance FROM portfolio_summary ORDER BY updated_at DESC LIMIT 1;"
        )

        return float(cur.fetchone()[0])

# --------------------------
# GET POSITION
# --------------------------

def get_position(cur, symbol):
    cur.execute(
        "Select quantity, avg_cost from portfolio_positions where symbol = %s",
        (symbol,)
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
        "INSERT into portfolio_trades (timestamp, symbol, trade_type, quantity, price, trade_value, signal_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (datetime.now(timezone.utc),symbol, "BUY", shares, price, cost, signal_id)
    )

    cur.execute(
        "INSERT INTO portfolio_positions(symbol, quantity, avg_cost) VALUES (%s,%s,%s)",
        (symbol,shares,price)
    )

    cur.execute(
        "update portfolio_summary set cash_balance = cash_balance -%s, updated_at = now()",
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
        "insert into portfolio_trades (timestamp,symbol,trade_type,quantity,price,trade_value,signal_id) Values (%s,%s,%s,%s,%s,%s)",
        (datetime.now(timezone.utc),symbol,"SELL",quantity,price,proceeds,signal_id)
    )
    cur.execute(
        "delete from portfolio_positions where symbol =%s",
        (symbol,)
    )
    cur.execute(
        """update portfolio_summary set cash_balance = cash_balance + %s,
            realized_pnl = realized_pnl + %s,
            updated_at = now()""",
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
        FROM portfolio_positions
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
            UPDATE portfolio_positions
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
        FROM portfolio_summary
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
        FROM portfolio_positions
    """)

    market_value, unrealized = cur.fetchone()

    total_value = cash + market_value

    total_return = (
        (total_value - STARTING_CASH)
        / STARTING_CASH
    ) * 100

    cur.execute("""
        UPDATE portfolio_summary
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
# RECORD SNAPSHOT
# -------------------------

def record_portfolio_snapshot(conn, cur):

    cur.execute("""
        SELECT
            cash_balance,
            portfolio_value,
            realized_pnl,
            unrealized_pnl,
            total_return_pct,
            updated_at
        FROM portfolio_summary
        LIMIT 1
    """)

    row = cur.fetchone()

    if not row:
        log(f"WHAT")
        return

    cash_balance, portfolio_value, realized_pnl, unrealized_pnl, total_return_pct, updated_at = row

    cur.execute("""
        INSERT INTO portfolio_history (
            cash_balance,
            portfolio_value,
            realized_pnl,
            unrealized_pnl,
            total_return_pct,
            timestamp
        )
        VALUES (%s,%s,%s,%s,%s,%s)
    """,
    (
        cash_balance,
        portfolio_value,
        realized_pnl,
        unrealized_pnl,
        total_return_pct,
        updated_at
    ))
    log(f"Cash Balance = {cash_balance}, Portfolio Value = {portfolio_value}, P&L = {realized_pnl}, Total Return = {total_return_pct}%")
    conn.commit()

# -------------------------
# PROCESS SIGNALS
# -------------------------

def process_signals(conn, cur):

    cur.execute("""
        SELECT id,
               symbol,
               action
        FROM ai_signals
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
            UPDATE ai_signals
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

    record_portfolio_snapshot(conn, cur)

    conn.commit()

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
