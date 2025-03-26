import yfinance as yf
import pandas as pd

def calculate_correlation(ticker1, ticker2):
    # 데이터 다운로드 (최근 1년), Close 가격만 사용
    data = yf.download([ticker1, ticker2], period='1y')['Close']
    
    # 상관계수 계산
    correlation = data[ticker1].corr(data[ticker2])

    print(f"{ticker1}와 {ticker2}의 상관계수: {correlation:.4f}")

if __name__ == "__main__":
    calculate_correlation('AAPL', 'MSFT')
