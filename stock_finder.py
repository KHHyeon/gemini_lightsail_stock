# -*- coding: utf-8 -*-
# File: ~/my_bot/stock_finder.py
import requests
import json

def get_high_dividend_candidates(base_url, app_key, secret_key, token, benchmark_rate):
    """
    배당수익률 상위 종목 중 시장 금리(benchmark_rate)보다 높은 종목을 발굴합니다.
    """
    path = "/uapi/domestic-stock/v1/ranking/dividend-yield" # 배당수익률 랭킹 API
    url = f"{base_url}{path}"
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "HHDFS76410100" # 배당수익률 상위 순위 TR
    }
    
    params = {
        "fid_cond_mrkt_div_code": "J", # 주식
        "fid_cond_scr_div_code": "20171", # 화면 번호
        "fid_input_iscd": "0000", # 전체
        "fid_div_cls_code": "0", # 전체
        "fid_rank_sort_cls_code": "0", # 순위순
        "fid_etc_cls_code": "0"
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
        
        candidates = []
        if data.get('rt_cd') == '0':
            for item in data.get('output', []):
                div_yield = float(item.get('divi_yield', 0))
                # 원칙 준수: 배당 수익률 > 시장 금리
                if div_yield > benchmark_rate:
                    candidates.append({
                        "ticker": item.get('stck_shrn_iscd'),
                        "name": item.get('hts_kor_isnm'),
                        "div_yield": div_yield,
                        "current_price": item.get('stck_prpr')
                    })
        
        # 토큰 절약을 위해 상위 10개만 슬라이싱하여 반환
        return candidates[:10]
    except Exception as e:
        print(f"Log: [Stock Finder Error] {e}")
        return []
