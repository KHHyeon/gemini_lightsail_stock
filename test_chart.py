# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# test_chart.py
import os
from dotenv import load_dotenv
import token_manager
import chart_data

load_dotenv()
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
URL = "https://openapi.koreainvestment.com:9443"

token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
result = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, "005930")

if result:
    print(f"수집된 데이터 개수: {len(result)}")
    print(f"가장 최근 데이터: {result[-1]}")
