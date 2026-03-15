# -*- coding: utf-8 -*-
# File: ~/my_bot/quant_screener.py
import requests
import time
import io
from contextlib import redirect_stdout
from bs4 import BeautifulSoup
import OpenDartReader
import chart_data

def get_naver_dividend(ticker):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        }
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            dvr_tag = soup.find('em', id='_dvr')
            if dvr_tag:
                return float(dvr_tag.text.strip().replace(',', ''))
    except Exception:
        pass
    return 0.0

def get_dart_fundamentals(dart_client, ticker):
    if not dart_client:
        return None
    try:
        report = None
        f = io.StringIO()
        with redirect_stdout(f):
            for year in [2025, 2024]:
                for rpt_code in ["11011", "11013"]:
                    try:
                        report = dart_client.finstate(ticker, year, rpt_code)
                        if report is not None and not report.empty:
                            break
                    except:
                        continue
                if report is not None and not report.empty:
                    break
                
        if report is not None and not report.empty:
            equity_row = report.loc[(report['account_nm'] == '자본총계') | (report['account_nm'] == '자본총액')]
            income_row = report.loc[(report['account_nm'] == '당기순이익') | (report['account_nm'] == '연결당기순이익')]
            op_income_row = report.loc[(report['account_nm'] == '영업이익') | (report['account_nm'] == '연결영업이익')]
            
            if not equity_row.empty and not income_row.empty and not op_income_row.empty:
                equity_str = str(equity_row.iloc[0]['thstrm_amount']).replace(',', '').strip()
                income_str = str(income_row.iloc[0]['thstrm_amount']).replace(',', '').strip()
                op_income_str = str(op_income_row.iloc[0]['thstrm_amount']).replace(',', '').strip()
                
                if equity_str and income_str and op_income_str:
                    try:
                        equity = float(equity_str)
                        income = float(income_str)
                        op_income = float(op_income_str)
                        if equity > 0:
                            roe = (income / equity) * 100
                            return {"roe": roe, "operating_profit": op_income}
                    except ValueError:
                        pass
    except Exception:
        pass
    return None

def get_basic_valuation(base_url, app_key, secret_key, token, ticker):
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": ticker
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("output", {})
            pbr_raw = data.get("pbr", "0")
            per_raw = data.get("per", "0")
            try:
                return {
                    "pbr": float(pbr_raw) if pbr_raw else 0.0,
                    "per": float(per_raw) if per_raw else 0.0
                }
            except ValueError:
                pass
    except Exception:
        pass
    return {"pbr": 0.0, "per": 0.0}

def run_screener(raw_candidates, base_url, app_key, secret_key, token, benchmark_rate, dart_api_key, relaxed_mode=False):
    mode_str = "단기반등 (5MA>20MA)" if relaxed_mode else "엄격 (20MA>60MA)"
    print(f"Log: [Screener] 스캐너 가동 모드: {mode_str} (세부 탈락 로그 생략)", flush=True)
    if not raw_candidates:
        return []

    dart_client = OpenDartReader(dart_api_key) if dart_api_key else None
    final_list = []
    min_dividend = round(benchmark_rate * 0.8, 2)
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        
        if not ticker:
            continue
            
        time.sleep(0.15)
        
        div_yield = get_naver_dividend(ticker)
        if div_yield < min_dividend:
            continue
            
        c["div_yield"] = div_yield
        
        chart_60d = chart_data.get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=60)
        if chart_60d and len(chart_60d) >= 60:
            closes = [day['close'] for day in chart_60d]
            if not relaxed_mode:
                ma20 = sum(closes[:20]) / 20
                ma60 = sum(closes[:60]) / 60
                if ma20 < ma60:
                    continue
            else:
                ma5 = sum(closes[:5]) / 5
                ma20 = sum(closes[:20]) / 20
                if ma5 <= ma20:
                    continue
        else:
            continue

        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        pbr = val["pbr"]
        per = val["per"]
        
        if pbr > 0 and per > 0:
            roe = round((pbr / per) * 100, 2)
            
            if pbr >= 2.0 or roe <= 0:
                continue
                
            dart_data = get_dart_fundamentals(dart_client, ticker)
            if dart_data:
                if dart_data.get("operating_profit", 0) <= 0:
                    continue
            
            c["pbr"] = pbr
            c["per"] = per
            c["roe"] = roe
            c["source"] = "KIS+DART"
            final_list.append(c)
            
        elif pbr <= 0 or per <= 0:
            dart_data = get_dart_fundamentals(dart_client, ticker)
            if dart_data and dart_data["roe"] > 0 and dart_data.get("operating_profit", 0) > 0:
                c["pbr"] = 0.0
                c["per"] = 0.0
                c["roe"] = round(dart_data["roe"], 2)
                c["source"] = "DART"
                final_list.append(c)
                
    final_list.sort(key=lambda x: x.get("div_yield", 0), reverse=True)
    print(f"Log: [Screener] 스캐닝 완료. 최종 {len(final_list)}종목 발굴.", flush=True)
    return final_list
