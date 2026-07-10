import requests

prompt = """
Stock: TSLA
Price: 320
RSI: 28
Trend: Up
Volume: Increasing

Return only:
Bullish
Neutral
Bearish
"""

response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "qwen3:4b",
        "prompt": prompt,
        "stream": False
    }
)

print(response.json()["response"])
