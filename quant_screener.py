# -*- coding: utf-8 -*-
# File: ~/my_bot/quant_screener.py
import time
import OpenDartReader

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
        print(f"Log: [DART Debug] Ticker {ticker} DART API 에러: {str(e)}")
    return None

def run_screener(raw_candidates, benchmark_rate, kis_client, dart_api_key):
    """
    1차 기초 후보군을 입력받아 밸류에이션을 검증하며, 모든 판단 결과를 터미널에 로깅합니다.
    """
    print(f"Log: [Screener Debug] ===== 동적 스캐너 가동 =====")
    print(f"Log: [Screener Debug] 전달받은 1차 후보군 종목 수: {len(raw_candidates)}개")
    
    if not raw_candidates:
        print("Log: [Screener Debug] 치명적 문제: stock_finder에서 수집한 종목이 0개입니다. stock_finder의 API 상태를 점검해야 합니다.")
        return []

    dart_client = OpenDartReader(dart_api_key) if dart_api_key else None
    final_list = []
    
    for c in raw_candidates:
        ticker = c.get("ticker") or c.get("code") or c.get("stck_shrn_iscd", "")
        name = c.get("name", "Unknown")
        div_yield = c.get("div_yield", 0.0)
        
        if not ticker:
            continue
            
        time.sleep(0.2)
        val = kis_client.get_valuation_data(ticker)
        if not val:
            print(f"Log: [Screener Debug] [{name}({ticker})] KIS 가치평가 데이터 수집 실패 (탈락)")
            continue
            
        try:
            pbr = float(val.get("pbr", 0))
            per = float(val.get("per", 0))
        except ValueError:
            pbr = 0.0
            per = 0.0
        
        # 1. KIS API 데이터 정상(제조업 등)
        if pbr > 0 and per > 0:
            roe = round((pbr / per) * 100, 2)
            if pbr < 2.0 and roe > 0:
                print(f"Log: [Screener Debug] [{name}] KIS 통과 -> PBR: {pbr}, PER: {per}, ROE: {roe}%")
                c["pbr"] = pbr
                c["per"] = per
                c["roe"] = roe
                c["source"] = "KIS"
                final_list.append(c)
            else:
                print(f"Log: [Screener Debug] [{name}] KIS 조건 미달 탈락 -> PBR: {pbr} (목표<2.0), ROE: {roe}% (목표>0)")
        
        # 2. KIS API 누락(금융주 등) 시 DART 검증
        elif (pbr <= 0 or per <= 0):
            dart_data = get_dart_fundamentals(dart_client, ticker)
            if dart_data and dart_data["roe"] > 0:
                print(f"Log: [Screener Debug] [{name}] DART 교차 검증 통과 -> 산출 ROE: {dart_data['roe']}%")
                c["pbr"] = 0.0
                c["per"] = 0.0
                c["roe"] = round(dart_data["roe"], 2)
                c["source"] = "DART"
                final_list.append(c)
            else:
                roe_val = dart_data["roe"] if dart_data else "데이터없음/적자"
                print(f"Log: [Screener Debug] [{name}] DART 검증 탈락 (KIS 데이터 누락 & DART ROE: {roe_val})")
                
    final_list.sort(key=lambda x: x.get("div_yield", 0), reverse=True)
    print(f"Log: [Screener Debug] ===== 검증 완료: 최종 {len(final_list)}개 종목 생존 =====")
    return final_list
