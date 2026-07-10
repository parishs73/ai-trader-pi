import os
import json
import logging
import requests
import time
import psycopg2
from dotenv import load_dotenv


load_dotenv()

DB_CONFIG = {
    "dbname": "stocks",
    "user": "trader",
    "password": "mypassword",
    #"host": "localhost",
    "host": "postgres",
    "port": 5432
}


# ---------------------------
# DB CONNECTION
# ---------------------------
def get_conn():
    return psycopg2.connect(**DB_CONFIG)


# Direct log outputs to your centralized logs folder
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("/app/logs/pipeline.log"), logging.StreamHandler()]
)

OLLAMA_URL = "http://ollama-service:11434/api/generate"

def get_ai_decision(market_snapshot):
    payload = {
        "model": "qwen3-trader",
        "prompt": f"Snapshot: {json.dumps(market_snapshot)}",
        "format": "json",
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=10)
        response.raise_for_status()
        return json.loads(response.json().get("response", "{}"))
    except Exception as e:
        logging.error(f"AI Matrix Error: {e}")
        return {"action": "HOLD", "ticker": market_snapshot.get("ticker"), "confidence": 0.0, "reasoning": "Error"}

if __name__ == "__main__":
    logging.info("AI Strategic Execution engine linked successfully.")
    while True:
        # Replace this dictionary with a database query to your Postgres container,
        # or tail your collector/logs/pipeline.log to process data live.
        mock_live_data = {"ticker": "NVDA", "price": 125.00, "rsi": 22.0}

        decision = get_ai_decision(mock_live_data)
        logging.info(f"AI_METRIC | Action: {decision.get('action')} | Ticker: {decision.get('ticker')} | Conf: {decision.get('confidence', 0)}")

        time.sleep(10)
