# -*- coding: utf-8 -*-
# File: ~/my_bot/quant_screener.py
import requests
import time

def run_screener(base_url, app_key, secret_key, token, benchmark_rate, kis_client):
    """
    리츠/우선주를 사전 제외하여 API 부하를 줄이고, 여유있게 고배당 가치주를 스크리닝합니다.
    """
    path = "/uapi/domestic-stock/v1/ranking/dividend-yield"
    url = f"{base_url}{path}"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "HHDFS76410100",
        "custtype": "P"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_cond_scr_div_code": "20171",
        "fid_input_iscd": "0000",
        "fid_div_cls_code": "0",
        "fid_rank_sort_cls_code": "0",
        "fid_etc_cls_code": "0"
    }

    min_dividend = benchmark_rate * 0.8
    candidates = []
    
    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get('rt_cd') == '0':
                for item in data.get('output', [])[:100]:
                    name = item.get('hts_kor_isnm', '')
                    
                    # [최적화] 리츠, 스팩, 우선주 필터링 (불필요한 현재가 API 호출 방지)
                    if "리츠" in name or "스팩" in name or name.endswith("우") or name.endswith("우B"):
                        continue

                    div_yield = float(item.get('divi_yield', 0))
                    if div_yield >= min_dividend:
                        candidates.append({
                            "ticker": item.get('stck_shrn_iscd'),
                            "name": name,
                            "div_yield": div_yield
                        })
    except Exception as e:
        print(f"Log: [Screener Dividend Error] {str(e)}")
        return []

    final_list = []
    for c in candidates:
        time.sleep(0.5) # [최적화] API 호출 제한 방어를 위해 0.5초로 여유있게 대기
        
        val = kis_client.get_valuation_data(c["ticker"])
        if not val:
            continue
            
        pbr = float(val.get("pbr", 0))
        per = float(val.get("per", 0))
        
        if pbr <= 0 or per <= 0:
            continue
            
        roe = round((pbr / per) * 100, 2)
        
        if pbr < 2.0 and roe > 0:
            c["pbr"] = pbr
            c["per"] = per
            c["roe"] = roe
            final_list.append(c)
            
    final_list.sort(key=lambda x: x["div_yield"], reverse=True)
    return final_list
