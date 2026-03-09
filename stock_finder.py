# -*- coding: utf-8 -*-
# File: ~/my_bot/stock_finder.py
import requests
import json

def get_high_dividend_candidates(base_url, app_key, secret_key, token, benchmark_rate):
    """
    배당수익률 상위 종목을 발굴하고 기준 금리와 비교합니다.
    """
    path = "/uapi/domestic-stock/v1/ranking/dividend-yield"
    url = f"{base_url}{path}"
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "HHDFS76410100",
        "custtype": "P" # 개인 고객 설정 필수
    }
    
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20171",
        "fid_input_iscd": "0000",
        "fid_div_cls_code": "0",
        "fid_rank_sort_cls_code": "0",
        "fid_etc_cls_code": "0"
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        
        # JSON 변환 전 상태 코드 확인 (404, 500 등 방지)
        if res.status_code != 200:
            print(f"Log: [API Error] Status {res.status_code}: {res.text[:100]}")
            return []

        data = res.json() # 여기서 에러가 발생했던 부분
        
        candidates = []
        if data.get('rt_cd') == '0':
            for item in data.get('output', []):
                try:
                    div_yield = float(item.get('divi_yield', 0))
                    # 유연한 기준 금리 비교 로직
                    if div_yield > benchmark_rate:
                        candidates.append({
                            "ticker": item.get('stck_shrn_iscd'),
                            "name": item.get('hts_kor_isnm'),
                            "div_yield": div_yield
                        })
                except: continue
        return candidates[:10] # 상위 10개 후보 반환

    except Exception as e:
        print(f"Log: [Stock Finder Error] {str(e)}")
        return []
