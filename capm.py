import yfinance as yf
import numpy as np
import pandas as pd
import statsmodels.api as sm
from datetime import datetime

def calculate_capm_and_additional_metrics(ticker):
    # 무위험 수익률(Rf): 10년 만기 미국 국채 금리 가져오기
    treasury_bond = yf.Ticker("^TNX")  # 10년 만기 국채 금리 (미국)
    rf = treasury_bond.history(period="1d")['Close'].iloc[-1] / 100  # 퍼센트를 소수로 변환

    # 시장 기대수익률(Rm): S&P 500의 장기 평균 수익률 (여기서는 8%로 가정)
    expected_market_return = 0.08

    # yfinance에서 제공하는 해당 주식의 베타(β) 가져오기
    stock = yf.Ticker(ticker)
    beta_yfinance = stock.info.get('beta', np.nan)  # 값이 없을 경우 대비

    # S&P 500과 해당 주식의 과거 주가 데이터를 가져와 직접 베타 계산
    sp500 = yf.Ticker("^GSPC")  # S&P 500 지수

    # 분석 기간 설정 (예시: 2015-03-01부터 2025-03-20까지)
    start_date = "2015-03-01"
    end_date = datetime.today().strftime("%Y-%m-%d")
    stock_data = stock.history(start=start_date, end=end_date)
    sp500_data = sp500.history(start=start_date, end=end_date)

    # 종가 기준 수익률 계산
    stock_returns = stock_data['Close'].pct_change().dropna()
    sp500_returns = sp500_data['Close'].pct_change().dropna()

    # 공통 날짜만 사용 (날짜 인덱스를 기준으로 병합)
    returns = pd.DataFrame({ticker: stock_returns, 'SP500': sp500_returns}).dropna()

    # 전체 데이터에 대해 선형 회귀 분석 (CAPM 모형)
    X = returns['SP500']
    y = returns[ticker]
    X_with_const = sm.add_constant(X)  # 절편 추가
    model = sm.OLS(y, X_with_const).fit()
    beta_calculated = model.params['SP500']  # 전체 베타
    alpha_calculated = model.params['const']  # 전체 알파

    # CAPM 모형: 주식의 기대수익률 계산
    expected_return = rf + beta_calculated * (expected_market_return - rf)

    # 업사이드 (시장 상승일) 데이터 추출
    returns_up = returns[returns['SP500'] > 0]
    if len(returns_up) > 0:
        X_up = sm.add_constant(returns_up['SP500'])
        y_up = returns_up[ticker]
        model_up = sm.OLS(y_up, X_up).fit()
        upside_beta = model_up.params['SP500']
        upside_alpha = model_up.params['const']
        win_rate_up = (returns_up[ticker] > 0).mean()  # 시장 상승일 중 주식도 상승한 비율
        avg_gain = returns_up[ticker].mean()          # 평균 상승폭
    else:
        upside_beta = np.nan
        upside_alpha = np.nan
        win_rate_up = np.nan
        avg_gain = np.nan

    # 다운사이드 (시장 하락일) 데이터 추출
    returns_down = returns[returns['SP500'] < 0]
    if len(returns_down) > 0:
        X_down = sm.add_constant(returns_down['SP500'])
        y_down = returns_down[ticker]
        model_down = sm.OLS(y_down, X_down).fit()
        downside_beta = model_down.params['SP500']
        downside_alpha = model_down.params['const']
        win_rate_down = (returns_down[ticker] > 0).mean()  # 시장 하락일 중 주식이 상승한 비율 (방어성 여부)
        avg_loss = returns_down[ticker].mean()             # 평균 하락폭 (보통 음수 값)
    else:
        downside_beta = np.nan
        downside_alpha = np.nan
        win_rate_down = np.nan
        avg_loss = np.nan

    # =========================== 결과 ===========================
    print(f"무위험 수익률 (Rf): {rf:.2%}")
    print(f"시장 기대수익률 (Rm): {expected_market_return:.2%}")
    print(f"{ticker}의 yfinance 제공 베타 (β): {beta_yfinance:.2f}")
    print(f"{ticker}의 직접 계산한 전체 베타 (β): {beta_calculated:.2f}")
    print(f"{ticker}의 전체 알파 (α): {alpha_calculated:.4f}")
    print(f"{ticker}의 기대수익률 (E(R)): {expected_return:.2%}")
    print("---------- 업사이드/다운사이드 세부 지표 ----------")
    print(f"업사이드 베타 (시장 상승 시): {upside_beta:.2f}")
    print(f"업사이드 알파: {upside_alpha:.4f}")
    print(f"시장 상승일 주식 승률: {win_rate_up:.2%}")
    print(f"평균 상승폭 (시장 상승일): {avg_gain:.2%}")
    print(f"다운사이드 베타 (시장 하락 시): {downside_beta:.2f}")
    print(f"다운사이드 알파: {downside_alpha:.4f}")
    print(f"시장 하락일 주식 승률: {win_rate_down:.2%}")
    print(f"평균 하락폭 (시장 하락일): {avg_loss:.2%}")

if __name__ == "__main__":
    calculate_capm_and_additional_metrics("INTC")
