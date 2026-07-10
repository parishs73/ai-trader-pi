import yfinance as yf

stocks = ["AAPL", "TSLA", "AMZN", "MSFT", "GOOGL",
           "META", "NVDA", "JPM", "V", "DIS", "COF", "AZN.L", "4503.T"]



for stock in stocks:
    data = yf.Ticker(stock).history(period="6mo", interval="1d")
    print("\n", stock)
    print(data.tail())
