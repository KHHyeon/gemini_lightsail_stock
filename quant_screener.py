# -*- coding: utf-8 -*-
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from contextlib import redirect_stdout
import chart_data
import OpenDartReader

def get_naver_dividend(ticker):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            dvr_tag = soup.find('em', id='_dvr')
            if dvr_tag: return float(dvr_tag.text.strip().replace(',', ''))
    except: pass
    return 0.0

def get_basic_valuation(base_url, app_key, secret_key, token, ticker):
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": secret_key, "tr_id": "FHKST01010100"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    time.sleep(0.1)
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("output", {})
            # acml_tr_pbmn: 누적 거래 대금 (단위: 원)
            tr_amount = int(data.get("acml_tr_pbmn", "0") or 0)
            return {
                "current_price": int(data.get("stck_prpr", "0") or 0),
                "pbr": float(data.get("pbr", "0") or 0.0),
                "per": float(data.get("per", "0") or 0.0),
                "tr_amount": tr_amount
            }
    except: pass
    return {"current_price": 0, "pbr": 0.0, "per": 0.0, "tr_amount": 0}

def get_smart_money_accumulation(base_url, app_key, secret_key, token, ticker):
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": secret_key, "tr_id": "FHKST01010900"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    time.sleep(0.2)
    frgn_net, orgn_net = 0, 0
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            daily_data = res.json().get("output2", [])
            for day in daily_data:
                frgn_net += int(day.get("frgn_ntby_qty", "0"))
                orgn_net += int(day.get("orgn_ntby_qty", "0"))
    except: pass
    return frgn_net, orgn_net

def get_dart_yoy_growth(dart_client, ticker):
    if not dart_client: return 0.0, 0.0, False
    current_year = datetime.now().year
    search_queue = [(current_year, "11013"), (current_year, "11012"), (current_year - 1, "11011")]
    report = None
    f = io.StringIO()
    time.sleep(0.6)
    try:
        with redirect_stdout(f):
            for year, rpt_code in search_queue:
                try:
                    report = dart_client.finstate(ticker, year, rpt_code)
                    if report is not None and not report.empty: break
                except: continue
        if report is not None and not report.empty:
            op_income_row = report.loc[(report['account_nm'] == '영업이익') | (report['account_nm'] == '연결영업이익')]
            sales_row = report.loc[report['account_nm'].str.contains('매출|영업수익|수익', na=False)]
            if not op_income_row.empty and not sales_row.empty:
                cur_op = float(str(op_income_row.iloc[0].get('thstrm_amount', '0')).replace(',', '').strip() or 0)
                cur_sales = float(str(sales_row.iloc[0].get('thstrm_amount', '0')).replace(',', '').strip() or 0)
                prev_op = float(str(op_income_row.iloc[0].get('frmtrm_amount', '0')).replace(',', '').strip() or 0)
                prev_sales = float(str(sales_row.iloc[0].get('frmtrm_amount', '0')).replace(',', '').strip() or 0)
                
                sales_growth = ((cur_sales - prev_sales) / abs(prev_sales)) * 100 if prev_sales != 0 else 0.0
                turnaround = (prev_op <= 0 and cur_op > 0)
                op_growth = ((cur_op - prev_op) / abs(prev_op)) * 100 if prev_op != 0 else 0.0
                return sales_growth, op_growth, turnaround
    except: pass
    return 0.0, 0.0, False

def run_condition_screener(kis_client, target_condition_name):
    print(f"Log: [Screener] '{target_condition_name}' 탐색 시작...")
    seq = kis_client.find_condition_seq(target_condition_name)
    if not seq:
        print(f"Log: [Error] '{target_condition_name}' 조건식을 HTS 목록에서 찾을 수 없습니다.")
        return []
        
    tickers = kis_client.get_condition_stocks(seq)
    if not tickers:
        print(f"Log: [Info] '{target_condition_name}' 조건에 맞는 종목이 현재 시장에 없습니다.")
        return []

    results = []
    for ticker in tickers:
        results.append({"ticker": ticker, "name": ticker})
    print(f"Log: [Screener] 조건식 확인 완료. 종목 추출 중...")
    return results

def run_unified_screener(raw_candidates, base_url, app_key, secret_key, token, dart_api_key):
    if not raw_candidates: return []
    dart_client = OpenDartReader(dart_api_key) if dart_api_key else None
    final_list = []
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        if not ticker: continue
        
        # 1. 유동성 필터 (데이터 무결성 검증 포함)
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        if val["current_price"] <= 0: continue # 가격 데이터 무결성 실패 시 스킵
        
        # 당일 거래대금 10억 미만인 종목은 즉시 탈락 (유동성 부족)
        if val["tr_amount"] < 1000000000:
            print(f"Log: [Liquidity Filter] {c.get('name', ticker)} 탈락 (거래대금: {val['tr_amount']/1000000:,.1f}백만)")
            continue
            
        score = 0
        details = []
        
        # 2. 기술적 지표 채점
        chart_60d = chart_data.get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=60)
        if chart_60d and len(chart_60d) >= 60:
            current_close = chart_60d[0]['close']
            ma60 = sum(day['close'] for day in chart_60d) / 60
            if current_close >= ma60:
                score += 20
                details.append("차트 정배열(+20)")
                
        # 3. 수급 채점
        frgn, orgn = get_smart_money_accumulation(base_url, app_key, secret_key, token, ticker)
        if frgn > 0 or orgn > 0:
            score += 30
            details.append("수급 유입(+30)")
            
        # 4. 실적 채점
        sales_growth, op_growth, turnaround = get_dart_yoy_growth(dart_client, ticker)
        if sales_growth >= 10.0:
            score += 25
            details.append("매출성장(+25)")
        if op_growth >= 15.0 or turnaround:
            score += 25
            details.append("이익성장/턴어라운드(+25)")
            
        c.update({
            "current_price": val["current_price"],
            "pbr": val["pbr"],
            "per": val["per"],
            "score": score,
            "score_details": details,
            "target_theme": c.get("target_theme", "가치성장 대장주")
        })
        final_list.append(c)
        
    final_list.sort(key=lambda x: x.get("score", 0), reverse=True)
    return final_list

def run_screener(raw_candidates, base_url, app_key, secret_key, token, benchmark_rate, dart_api_key):
    """기존 배당주 스캐너에도 유동성 필터 적용"""
    if not raw_candidates: return []
    final_list = []
    min_dividend = round(benchmark_rate * 0.8, 2)
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        if val["current_price"] <= 0 or val["tr_amount"] < 1000000000: continue
        
        div_yield = get_naver_dividend(ticker)
        if div_yield < min_dividend: continue
        
        if val["pbr"] > 0 and val["per"] > 0:
            roe = round((val["pbr"] / val["per"]) * 100, 2)
            if val["pbr"] >= 2.0 or roe <= 0: continue
            
            c.update({
                "current_price": val["current_price"], 
                "pbr": val["pbr"], 
                "per": val["per"], 
                "roe": roe, 
                "div_yield": div_yield
            })
            final_list.append(c)
            
    final_list.sort(key=lambda x: x.get("div_yield", 0), reverse=True)
    print(f"Log: [Screener] 총 {len(final_list)}개 종목 발굴 완료.")
    return final_list
