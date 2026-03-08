# -*- coding: utf-8 -*-
# File: ~/my_bot/macro_collector.py
import yfinance as yf
from datetime import datetime

def get_safe_history(ticker_symbol):
    """
    야후 파이낸스에서 데이터를 가져올 때 발생할 수 있는 에러를 방지하고 
    최근 거래일의 데이터를 안전하게 반환합니다.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        # 주말/공휴일 대응을 위해 5일치 데이터를 조회합니다.
        hist = ticker.history(period="5d")
        
        # 데이터가 존재할 경우에만 마지막 행(최근 거래일)을 추출합니다.
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
        
        print(f"Log: [Ticker Warning] {ticker_symbol} 데이터가 비어있습니다.")
        return None
    except Exception as e:
        print(f"Log: [Ticker Error] {ticker_symbol} 수집 실패: {str(e)}")
        return None

def get_macro_indicators():
    """
    환율(USD/KRW), 미국 10년물 국채 금리, WTI 유가 데이터를 수집합니다.
    """
    try:
        # 개별 지표 수집 (하나가 실패해도 나머지는 진행됨)
        usd_krw = get_safe_history("KRW=X")
        us_10y_yield = get_safe_history("^TNX")
        wti_oil = get_safe_history("CL=F")
        
        # 지표 중 하나라도 성공했다면 데이터를 구성하여 반환합니다.
        if usd_krw or us_10y_yield or wti_oil:
            return {
                "usd_krw": round(usd_krw, 2) if usd_krw else "N/A",
                "us_10y_yield": round(us_10y_yield, 2) if us_10y_yield else "N/A",
                "wti_oil": round(wti_oil, 2) if wti_oil else "N/A",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        print("Log: [Macro Error] 모든 매크로 지표 수집에 실패했습니다.")
        return None

    except Exception as e:
        print(f"Log: [Macro Total Error] {str(e)}")
        return None

if __name__ == "__main__":
    # 개별 테스트용 코드
    print("매크로 지표 수집 테스트 시작...")
    print(get_macro_indicators())
