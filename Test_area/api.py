import requests

prompt = """
Stock: AMZN
RSI: 32
Trend: Uptrend
Volume: Increasing

Return: Bullish, Neutral, or Bearish
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
