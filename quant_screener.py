# -*- coding: utf-8 -*-
# File: ~/my_bot/quant_screener.py
import requests
import time
from bs4 import BeautifulSoup
import OpenDartReader

def get_naver_dividend(ticker):
    """
    KIS API의 배당률 누락 결함을 방어하기 위해, 
    네이버 금융 개별 종목 페이지에서 실제 배당수익률을 직접 추출합니다.
    """
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'
        }
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            # 네이버 금융의 배당수익률 고유 ID 태그 탐색
            dvr_tag = soup.find('em', id='_dvr')
            if dvr_tag:
                return float(dvr_tag.text.strip().replace(',', ''))
    except Exception as e:
        print(f"Log: [Naver Dividend Error] Ticker {ticker} - {str(e)}")
    return 0.0

def get_dart_fundamentals(dart_client, ticker):
    if not dart_client:
        return None
    try:
        report = None
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
            
            if not equity_row.empty and not income_row.empty:
                equity_str = str(equity_row.iloc[0]['thstrm_amount']).replace(',', '').strip()
                income_str = str(income_row.iloc[0]['thstrm_amount']).replace(',', '').strip()
                if equity_str and income_str:
                    try:
                        equity = float(equity_str)
                        income = float(income_str)
                        if equity > 0:
                            roe = (income / equity) * 100
                            return {"roe": roe}
                    except ValueError:
                        pass
    except Exception as e:
        print(f"Log: [DART API Error] Ticker {ticker} - {str(e)}")
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
    except Exception as e:
        pass
    return {"pbr": 0.0, "per": 0.0}

def run_screener(raw_candidates, base_url, app_key, secret_key, token, benchmark_rate, dart_api_key):
    print(f"Log: [Screener Debug] ===== 하이브리드 동적 밸류에이션 스캐너 가동 =====")
    print(f"Log: [Screener Debug] 전달받은 1차 후보군 종목 수: {len(raw_candidates)}개")
    
    if not raw_candidates:
        return []

    dart_client = OpenDartReader(dart_api_key) if dart_api_key else None
    final_list = []
    min_dividend = round(benchmark_rate * 0.8, 2)
    
    print(f"Log: [Screener Debug] 1차 필터 목표 배당률: {min_dividend}% 이상")
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        name = c.get("name", "Unknown")
        
        if not ticker:
            continue
            
        time.sleep(0.15)
        
        # 1. 네이버에서 정확한 배당률 추출
        div_yield = get_naver_dividend(ticker)
        
        # 탈락 사유 1: 배당률 미달
        if div_yield < min_dividend:
            print(f"Log: [Screener Debug] [Drop] [{name}] 배당 미달: {div_yield}% < {min_dividend}%")
            continue
            
        c["div_yield"] = div_yield
        
        # 2. KIS API에서 PBR/PER 추출
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        pbr = val["pbr"]
        per = val["per"]
        
        # KIS 데이터 정상인 경우 (PBR, PER 모두 존재)
        if pbr > 0 and per > 0:
            roe = round((pbr / per) * 100, 2)
            
            # 탈락 사유 2: 고평가 (PBR >= 2.0)
            if pbr >= 2.0:
                print(f"Log: [Screener Debug] [Drop] [{name}] 고평가 탈락: PBR {pbr} >= 2.0")
                continue
                
            # 탈락 사유 3: 적자 기업 (ROE <= 0)
            if roe <= 0:
                print(f"Log: [Screener Debug] [Drop] [{name}] 적자 탈락: 산출 ROE {roe}% <= 0")
                continue
                
            # 최종 생존 (KIS)
            print(f"Log: [Screener Debug] [Pass] [{name}] KIS 검증 통과! 배당: {div_yield}%, PBR: {pbr}, ROE: {roe}%")
            c["pbr"] = pbr
            c["per"] = per
            c["roe"] = roe
            c["source"] = "KIS"
            final_list.append(c)
            
        # KIS 데이터 누락 시 DART 교차 검증
        elif pbr <= 0 or per <= 0:
            print(f"Log: [Screener Debug] [Check] [{name}] KIS PBR/PER 결측치 발생. DART 교차 검증 진입.")
            dart_data = get_dart_fundamentals(dart_client, ticker)
            
            if dart_data and dart_data["roe"] > 0:
                print(f"Log: [Screener Debug] [Pass] [{name}] DART 검증 통과! 배당: {div_yield}%, 산출 ROE: {dart_data['roe']:.2f}%")
                c["pbr"] = 0.0
                c["per"] = 0.0
                c["roe"] = round(dart_data["roe"], 2)
                c["source"] = "DART"
                final_list.append(c)
            else:
                print(f"Log: [Screener Debug] [Drop] [{name}] DART 검증 탈락 (적자 또는 데이터 누락)")
                
    final_list.sort(key=lambda x: x.get("div_yield", 0), reverse=True)
    print(f"Log: [Screener Debug] ===== 검증 완료: 최종 {len(final_list)}개 종목 생존 =====")
    return final_list
