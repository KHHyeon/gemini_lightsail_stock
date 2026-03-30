# -*- coding: utf-8 -*-
# File: ~/my_bot/quant_screener.py
import requests
import time
import io
from contextlib import redirect_stdout
from bs4 import BeautifulSoup
import OpenDartReader
import chart_data
from datetime import datetime

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

def get_dart_fundamentals(dart_client, ticker):
    if not dart_client: return None
    try:
        report = None
        f = io.StringIO()
        
        # [수정] 하드코딩 제거: 현재 연도 기준으로 최근 3개년도 자동 계산
        current_year = datetime.now().year
        target_years = [current_year, current_year - 1, current_year - 2]
        
        with redirect_stdout(f):
            for year in target_years:
                for rpt_code in ["11011", "11013", "11012", "11014"]: # 1분기, 반기, 3분기, 사업보고서 순차 조회
                    try:
                        report = dart_client.finstate(ticker, year, rpt_code)
                        if report is not None and not report.empty: break
                    except: continue
                if report is not None and not report.empty: break
                
        if report is not None and not report.empty:
            equity_row = report.loc[(report['account_nm'] == '자본총계') | (report['account_nm'] == '자본총액')]
            income_row = report.loc[(report['account_nm'] == '당기순이익') | (report['account_nm'] == '연결당기순이익')]
            op_income_row = report.loc[(report['account_nm'] == '영업이익') | (report['account_nm'] == '연결영업이익')]
            sales_row = report.loc[report['account_nm'].str.contains('매출|영업수익|수익', na=False)]
            
            if not equity_row.empty and not income_row.empty and not op_income_row.empty:
                equity = float(str(equity_row.iloc[0]['thstrm_amount']).replace(',', '').strip() or 0)
                income = float(str(income_row.iloc[0]['thstrm_amount']).replace(',', '').strip() or 0)
                op_income = float(str(op_income_row.iloc[0]['thstrm_amount']).replace(',', '').strip() or 0)
                sales = float(str(sales_row.iloc[0]['thstrm_amount']).replace(',', '').strip() or 0) if not sales_row.empty else 0
                
                if equity > 0:
                    roe = (income / equity) * 100
                    return {"roe": roe, "operating_profit": op_income, "sales": sales}
    except: pass
    return None

def get_basic_valuation(base_url, app_key, secret_key, token, ticker):
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json", "authorization": f"Bearer {token}",
        "appkey": app_key, "appsecret": secret_key, "tr_id": "FHKST01010100"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("output", {})
            return {
                "pbr": float(data.get("pbr", "0") or 0.0),
                "per": float(data.get("per", "0") or 0.0)
            }
    except: pass
    return {"pbr": 0.0, "per": 0.0}

def run_screener(raw_candidates, base_url, app_key, secret_key, token, benchmark_rate, dart_api_key, relaxed_mode=False):
    if not raw_candidates: return []
    dart_client = OpenDartReader(dart_api_key) if dart_api_key else None
    final_list = []
    min_dividend = round(benchmark_rate * 0.8, 2)
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        if not ticker: continue
        time.sleep(0.15)
        div_yield = get_naver_dividend(ticker)
        if div_yield < min_dividend: continue
        c["div_yield"] = div_yield
        
        chart_60d = chart_data.get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=60)
        if chart_60d and len(chart_60d) >= 60:
            closes = [day['close'] for day in chart_60d]
            if not relaxed_mode:
                if sum(closes[:20])/20 < sum(closes[:60])/60: continue
            else:
                if sum(closes[:5])/5 <= sum(closes[:20])/20: continue
        else: continue

        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        pbr, per = val["pbr"], val["per"]
        if pbr > 0 and per > 0:
            roe = round((pbr / per) * 100, 2)
            if pbr >= 2.0 or roe <= 0: continue
            dart_data = get_dart_fundamentals(dart_client, ticker)
            if dart_data and dart_data.get("operating_profit", 0) <= 0: continue
            c.update({"pbr": pbr, "per": per, "roe": roe, "source": "KIS+DART"})
            final_list.append(c)
    final_list.sort(key=lambda x: x.get("div_yield", 0), reverse=True)
    return final_list

def run_theme_screener(raw_candidates, base_url, app_key, secret_key, token, dart_api_key):
    if not raw_candidates: return []
    dart_client = OpenDartReader(dart_api_key) if dart_api_key else None
    final_list = []
    
    print("\nLog: [Theme Screener] 테마주 실적 및 차트 검증 시작...", flush=True)
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        name = c.get("name")
        if not ticker: continue
        time.sleep(0.2)
        
        # 1. 차트 추세 검증
        chart_60d = chart_data.get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=60)
        if not chart_60d or len(chart_60d) < 60:
            print(f" └ 탈락: {name} (차트 데이터 60일 미만)", flush=True)
            continue
            
        closes = [day['close'] for day in chart_60d]
        current_close = closes[0]
        ma20 = sum(closes[:20]) / 20
        ma60 = sum(closes[:60]) / 60
        
        if current_close < ma60 and ma20 < ma60:
            print(f" └ 탈락: {name} (차트 역배열/하락추세)", flush=True)
            continue 
            
        # 2. 실적 검증 (DART + KIS 우회로)
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        pbr = val["pbr"]
        per = val["per"]
        
        dart_data = get_dart_fundamentals(dart_client, ticker)
        
        if dart_data:
            sales = dart_data.get("sales", 0)
            op = dart_data.get("operating_profit", 0)
            roe = round(dart_data.get("roe", 0), 2)
            
            if sales <= 0 or op <= 0:
                print(f" └ 탈락: {name} (DART 실적 적자 또는 매출 0)", flush=True)
                continue
        else:
            # DART 생존 우회로
            if per <= 0:
                print(f" └ 탈락: {name} (DART 응답 실패 & KIS PER 적자)", flush=True)
                continue
            else:
                roe = round((pbr / per) * 100, 2) if per > 0 else 0.0
                sales = "DART 미응답(우회 흑자검증)"
                print(f" └ 통과: {name} (DART 응답 실패했으나 PER>0 으로 우회 통과)", flush=True)
                
        c.update({
            "pbr": pbr, 
            "per": per, 
            "roe": roe, 
            "sales": sales
        })
        print(f" [합격]: {name} (ROE: {roe}%)", flush=True)
        final_list.append(c)
        
    print(f"Log: [Theme Screener] 검증 완료. 총 {len(final_list)}종목 통과.\n", flush=True)
    return final_list
