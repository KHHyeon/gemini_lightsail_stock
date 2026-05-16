# -*- coding: utf-8 -*-
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from contextlib import redirect_stdout
from src.data import chart as chart_data



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

def calculate_rsi(ohlcv, period=14):
    if len(ohlcv) < period + 1: return 50.0
    deltas = []
    for i in range(1, len(ohlcv)):
        deltas.append(ohlcv[i]['close'] - ohlcv[i-1]['close'])
    
    up = [d if d > 0 else 0 for d in deltas]
    down = [abs(d) if d < 0 else 0 for d in deltas]
    
    avg_up = sum(up[-period:]) / period
    avg_down = sum(down[-period:]) / period
    
    if avg_down == 0: return 100.0
    rs = avg_up / avg_down
    return 100.0 - (100.0 / (1+rs))

def calculate_envelope_bottom(ohlcv, period=20, spread=15.0):
    if len(ohlcv) < period: return 0.0
    closes = [x['close'] for x in ohlcv[-period:]]
    sma = sum(closes) / period
    return sma * (1 - (spread / 100.0))

def check_contrarian_signal(ohlcv):
    """
    RSI 30 이하, 엔벨로프 하단 터치 + 도지 캔들 + 거래량 급감 시그널 확인
    """
    if not ohlcv or len(ohlcv) < 20: return False, ""
    
    curr = ohlcv[-1]
    prev = ohlcv[-2]
    
    rsi = calculate_rsi(ohlcv)
    env_bottom = calculate_envelope_bottom(ohlcv)
    
    # 1차 필터: 과매도권 (RSI 30 이하 또는 엔벨로프 하단 근접)
    is_oversold = rsi <= 35 or curr['close'] <= env_bottom * 1.02
    if not is_oversold: return False, ""
    
    # 2. 2차 필터: 하락 진정 패턴 (도지 캔들 + 거래량 급감)
    body_size = abs(curr['open'] - curr['close'])
    total_size = curr['high'] - curr['low'] if curr['high'] != curr['low'] else 1
    
    # 사용자의 정밀 요청: 시가와 종가의 차이가 전체 캔들 길이의 1.5% 이내일 때 도지로 인정
    is_doji = (body_size / total_size) <= 0.015
    
    # 최근 5일 평균 거래량 대비 급감 (80% 이하)
    avg_vol = sum([x['volume'] for x in ohlcv[-6:-1]]) / 5
    is_vol_drop = curr['volume'] < avg_vol * 0.8
    
    if is_oversold and is_doji and is_vol_drop:
        return True, f"RSI:{rsi:.1f}/도지/거래량급감"
    elif is_oversold and curr['close'] > prev['close'] and is_vol_drop:
        return True, f"RSI:{rsi:.1f}/양봉전환/거래량급감"
        
    return False, ""

def get_basic_valuation(base_url, app_key, secret_key, token, ticker):
    # FHKST01010100: 주식 현재가 시세
    url_price = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": secret_key, "tr_id": "FHKST01010100"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    time.sleep(0.1)
    
    res_val = {"current_price": 0, "pbr": 0.0, "per": 0.0, "roe": 0.0, "tr_amount": 0, "dvd_yld": 0.0}
    
    try:
        res = requests.get(url_price, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("output", {})
            res_val["current_price"] = int(data.get("stck_prpr", "0") or 0)
            res_val["pbr"] = float(data.get("pbr", "0") or 0.0)
            res_val["per"] = float(data.get("per", "0") or 0.0)
            res_val["tr_amount"] = int(data.get("acml_tr_pbmn", "0") or 0)
    except: pass

    # FHKST03010300: 주식 가치지표 (실제 ROE, 배당수익률 등)
    headers["tr_id"] = "FHKST03010300"
    time.sleep(0.1)
    try:
        res = requests.get(url_price, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("output", {})
            res_val["roe"] = float(data.get("roe", "0") or 0.0)
            res_val["dvd_yld"] = float(data.get("dvd_yld", "0") or 0.0)
    except: pass
    
    return res_val

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

def get_kis_growth_metrics(base_url, app_key, secret_key, token, ticker):
    # FHKST03010400: 국내주식 성장성지표 조회
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": secret_key, "tr_id": "FHKST03010400"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    time.sleep(0.1)
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("output", {})
            sales_growth = float(data.get("gr_sales", "0") or 0.0)
            op_growth = float(data.get("gr_op_profit", "0") or 0.0)
            # 증가율이 매우 높으면(100% 이상) 턴어라운드 가능성이 높은 것으로 간주
            return sales_growth, op_growth, (op_growth > 100)
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

def run_unified_screener(raw_candidates, base_url, app_key, secret_key, token):
    if not raw_candidates: return []
    final_list = []
    
    financial_keywords = ['지주', '은행', '증권', '보험', '금융']
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        stock_name = c.get("name", ticker)
        if not ticker: continue
        
        is_financial = any(kw in stock_name for kw in financial_keywords)
        
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        if val["current_price"] <= 0: continue
        
        if val["tr_amount"] < 1000000000:
            print(f"Log: [Liquidity Filter] {stock_name} 탈락 (거래대금 부족)")
            continue
            
        score = 0
        details = []
        
        chart_60d = chart_data.get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=60)
        if chart_60d and len(chart_60d) >= 60:
            current_close = chart_60d[0]['close']
            ma60 = sum(day['close'] for day in chart_60d) / 60
            if current_close >= ma60:
                score += 20
                details.append("차트 정배열(+20)")
                
        frgn, orgn = get_smart_money_accumulation(base_url, app_key, secret_key, token, ticker)
        if frgn > 0 or orgn > 0:
            score += 30
            details.append("수급 유입(+30)")
            
        if is_financial:
            if val["pbr"] > 0 and val["pbr"] <= 1.0:
                score += 20
                details.append("저PBR(+20)")
            
            roe = val.get("roe", 0.0)
            if roe <= 0: # API 데이터 부재 시 추정치 활용
                roe = round((val["pbr"] / val["per"]) * 100, 2) if val["per"] > 0 else 0
                
            if roe >= 8.0:
                score += 30
                details.append("ROE 8% 이상(+30)")
                
            if score >= 80:
                c.update({
                    "current_price": val["current_price"], "pbr": val["pbr"], "per": val["per"], "roe": roe,
                    "score": score, "score_details": details, "target_theme": c.get("target_theme", "우량 금융주")
                })
                final_list.append(c)
        else:
            sales_growth, op_growth, turnaround = get_kis_growth_metrics(base_url, app_key, secret_key, token, ticker)
            if sales_growth >= 10.0:
                score += 25
                details.append("매출성장(+25)")
            if op_growth >= 15.0 or turnaround:
                score += 25
                details.append("이익성장/턴어라운드(+25)")
                
            if score >= 60:
                c.update({
                    "current_price": val["current_price"], "pbr": val["pbr"], "per": val["per"],
                    "score": score, "score_details": details, "target_theme": c.get("target_theme", "가치성장 대장주")
                })
                final_list.append(c)
        
    final_list.sort(key=lambda x: x.get("score", 0), reverse=True)
    return final_list

def run_screener(raw_candidates, base_url, app_key, secret_key, token, benchmark_rate):
    if not raw_candidates: return []
    final_list = []
    min_dividend = round(benchmark_rate * 0.8, 2)
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        if val["current_price"] <= 0 or val["tr_amount"] < 1000000000: continue
        
        div_yield = get_naver_dividend(ticker)
        if div_yield <= 0: div_yield = val.get("dvd_yld", 0.0) # 네이버 실패 시 KIS 데이터 활용
        
        if div_yield < min_dividend: continue
        
        roe = val.get("roe", 0.0)
        if roe <= 0: roe = round((val["pbr"] / val["per"]) * 100, 2) if val["per"] > 0 else 0
        
        if val["pbr"] > 0 and val["per"] > 0:
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
