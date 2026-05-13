# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# File: ~/my_bot/chart_data.py
import requests
from datetime import datetime, timedelta

def get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=30):
    """
    한국투자증권 API를 통해 최근 n일간의 일봉 데이터를 가져옵니다.
    """
    path = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    url = f"{base_url}{path}"
    
    # 날짜 설정: 종료일(오늘), 시작일(100일 전으로 넉넉히 설정하여 30개를 추출)
    today = datetime.now().strftime("%Y%m%d")
    start_day = (datetime.now() - timedelta(days=100)).strftime("%Y%m%d")
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "FHKST03010100",
        "custtype": "P"
    }
    
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": ticker,
        "fid_input_date_1": start_day,  # 시작일자 (YYYYMMDD) - 추가됨
        "fid_input_date_2": today,      # 종료일자 (YYYYMMDD) - 추가됨
        "fid_period_div_code": "D",
        "fid_org_adj_prc": "1"
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        if data.get('rt_cd') == '0':
            raw_charts = data.get('output2', [])
            # 사용자가 요청한 count(30개)만큼만 슬라이싱
            selected_charts = raw_charts[:count]
            
            refined_data = []
            for day in selected_charts:
                refined_data.append({
                    "date": day['stck_bsop_date'],
                    "open": int(day['stck_oprc']),
                    "high": int(day['stck_hgpr']),
                    "low": int(day['stck_lwpr']),
                    "close": int(day['stck_clpr']),
                    "volume": int(day['acml_vol'])
                })
            
            refined_data.reverse() # 과거 -> 현재 순서로 정렬
            return refined_data
        else:
            print(f"Log: [Error] API 응답 에러: {data.get('msg1')}")
            return None
            
    except Exception as e:
        print(f"Log: [Exception] 차트 데이터 수집 중 에러: {str(e)}")
        return None
