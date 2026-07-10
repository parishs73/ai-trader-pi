import requests

print("Sending request...")

response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "qwen3:4b",
        "prompt": "Say hello",
        "stream": False
    },
    timeout=120
)

print("Response received")
print(response.json()["response"])
