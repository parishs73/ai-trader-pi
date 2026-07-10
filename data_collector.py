import yfinance as yf

ticker = yf.Ticker("AAPL")

data = ticker.history(period="30d")

print(data.tail())
