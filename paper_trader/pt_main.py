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

# ---------------------------
# DB CONNECTION
# ---------------------------

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

# ---------------------------
# LOGGING
# ---------------------------

os.makedirs("/logs", exist_ok=True)

LOG_FILE = "/logs/paper_trader.log"

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


# --------------------
# Process Signals
# --------------------   
def process_signals(conn,cur):

    #with conn.cursor() as cur:
        cur.execute(
            "select id, symbol, action from ai_signals2 where processed = FALSE order by timestamp"
        )

        signals = cur.fetchall()

        for signal_id, symbol, action in signals:

            if action == "BUY":
                print("BUY shares for {symbnol}")

            elif action =="SELL":
                print(" SELL shares for {symbol}")

            cur.execute(
                 "update ai_signals2 Set processed = TRUE where id =%s",
                 (signal_id,)
            )
            conn.commit()



# ----------------------
# MAIN
# ----------------------
def main():
    conn = get_conn()
    cur = conn.cursor()
    process_signals(conn,cur)

    conn.close()

if __name__ == "__main__":
    main()
