# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# File: ~/my_bot/macro_collector.py
import yfinance as yf
from datetime import datetime

def get_macro_indicators():
    try:
        # float()으로 명시적 변환 추가
        usd_krw = float(yf.Ticker("KRW=X").history(period="1d")['Close'].iloc[-1])
        us_10y_yield = float(yf.Ticker("^TNX").history(period="1d")['Close'].iloc[-1])
        wti_oil = float(yf.Ticker("CL=F").history(period="1d")['Close'].iloc[-1])
        
        return {
            "usd_krw": round(usd_krw, 2),
            "us_10y_yield": round(us_10y_yield, 2),
            "wti_oil": round(wti_oil, 2),
            "date": datetime.now().strftime("%Y-%m-%d")
        }
    except Exception as e:
        print(f"Log: [Macro Error] {str(e)}")
        return None
