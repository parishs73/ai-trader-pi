import psycopg2
import yfinance as yf
from datetime import datetime, timezone

DB = {
    "host": "localhost",
    "database": "stocks",
    "user": "trader",
    "password": "mypassword"
}

SYMBOL = "AAPL"
BUY_AMOUNT = 1000


conn = psycopg2.connect(**DB)
cur = conn.cursor()


# Get current price
ticker = yf.Ticker(SYMBOL)
price = ticker.history(period="1d")["Close"].iloc[-1]


# Get cash
cur.execute("""
    SELECT cash_balance
    FROM ps2
    ORDER BY id DESC
    LIMIT 1
""")

cash = cur.fetchone()[0]


# Calculate shares
quantity = int(BUY_AMOUNT / price)

cost = quantity * price


if quantity > 0 and cash >= cost:

    # Log trade
    cur.execute("""
        INSERT INTO pt2
        (symbol, action, quantity, price, trade_time)
        VALUES (%s,%s,%s,%s,%s)
    """,
    (
        SYMBOL,
        "BUY",
        quantity,
        price,
        datetime.now(timezone.utc)
    ))


    # Update position
    cur.execute("""
        INSERT INTO pp2
        (symbol, quantity, avg_price)
        VALUES (%s,%s,%s)
        ON CONFLICT(symbol)
        DO UPDATE SET
            quantity = pp2.quantity + EXCLUDED.quantity
    """,
    (
        SYMBOL,
        quantity,
        price
    ))


    # Update cash
    cur.execute("""
        UPDATE ps2
        SET cash_balance = cash_balance - %s
    """,
    (cost,))


    conn.commit()

    print(f"Bought {quantity} shares of {SYMBOL} at {price}")

else:
    print("Insufficient cash")


cur.close()
conn.close()