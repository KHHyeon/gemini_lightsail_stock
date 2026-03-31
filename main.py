# -*- coding: utf-8 -*-
# File: ~/my_bot/main.py
import os, time, threading, schedule, sys, re, uuid
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import OpenDartReader

import token_manager, account_info, macro_collector, ai_strategy, chart_data, stock_finder
import risk_manager, quant_screener, market_hours, news_crawler, theme_crawler, research_crawler
from kis_api import KISClient
from order_manager import OrderManager
from trade_logger import save_json_to_gdrive, load_json_from_gdrive

load_dotenv()
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
CHANNEL_ID = os.getenv("SLACK_CHANNEL")
DART_API_KEY = os.getenv("DART_API_KEY")
KST = timezone(timedelta(hours=9))

app = App(token=os.getenv("SLACK_TOKEN"))
kis = KISClient()
pending_orders = {}

def get_stock_info_naver(ticker):
    name, div, is_etf = ticker, 0.0, False
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = soup.find('title')
        if title: name = title.text.split(':')[0].strip()
        dvr = soup.find('em', id='_dvr')
        if dvr: div = float(dvr.text.strip().replace(',', ''))
        
        etf_keywords = ['KODEX', 'TIGER', 'KBSTAR', 'ACE', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'TIMEFOLIO', '히어로즈']
        if any(kw in name.upper() for kw in etf_keywords) or 'ETN' in name.upper() or 'ETF' in name.upper():
            is_etf = True
        elif soup.find('img', alt='ETF') or soup.find('img', alt='ETN'):
            is_etf = True
    except: pass
    return name, div, is_etf

def daily_routine():
    if datetime.now(KST).weekday() >= 5: return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 일일 시황 브리핑 작성을 시작합니다.")
    macro = macro_collector.get_macro_indicators()
    us_kw, kr_kw = ai_strategy.infer_news_keywords()
    us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
    kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
    research_reports = research_crawler.get_latest_industry_reports(limit=8)
    report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, research_reports, "특이사항 없음")
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[일간 마감 브리핑]\n\n{report}")

def weekly_routine():
    if datetime.now(KST).weekday() >= 5: return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 주간 포트폴리오 진단을 시작합니다.")
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=3, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[주간 포트폴리오 진단]\n\n{report}")

def monthly_routine():
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=4, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[월간 포트폴리오 리포트]\n\n{report}")

def quarterly_routine():
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=5, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[분기 포트폴리오 리포트]\n\n{report}")

def run_risk_routine():
    if not market_hours.is_market_open(): return
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID)

def daily_fundamental_stop_loss():
    if not market_hours.is_market_open(): return
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 14:30 펀더멘털 손절매 감시를 시작합니다. (구체적 손절조건 도달 여부 점검)")
    
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)
    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    macro = macro_collector.get_macro_indicators()
    
    keys_to_delete = []
    messages = []
    
    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0: continue
        
        name = info.get("name", ticker)
        mode_type = info.get("mode_type", "PAPER_ONLY")
        context = info.get("reason", "매수 근거 기록 없음")
        
        val = kis.get_valuation_data(ticker)
        # 데이터 무결성 검증 방어막 적용
        if not val or int(val.get("current_price", 0)) <= 0: continue
            
        current_price = int(val["current_price"])
        chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
        
        report = ai_strategy.check_fundamental_damage(ticker, name, chart_30d, macro, val, context)
        
        if "[펀더멘털훼손]" in report:
            reason = "AI 펀더멘털 훼손 진단 (사전 설정 손절조건 도달)"
            res = order_mgr.execute_order(ticker, name, qty, current_price, "sell", reason, mode_type)
            messages.append(f"[구조적 손절매 발동] {name}({ticker}) 전량 매도\n- 사유: {reason}\n- 코멘트: {report}")
            keys_to_delete.append(ticker)
        
        time.sleep(3)
        
    for k in keys_to_delete: del portfolio[k]
    if keys_to_delete: save_json_to_gdrive(portfolio, "paper_portfolio.json")
    if messages and CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[AI 펀더멘털 진단 결과]\n" + "\n".join(messages))

def execute_daily_split_buys():
    if not market_hours.is_market_open(): return
    macro = macro_collector.get_macro_indicators()
    try:
        vix = float(macro.get("VIX", 20.0))
        wti = float(macro.get("WTI", macro.get("wti", 70.0)))
        us10y = float(macro.get("us_10y_yield", macro.get("US10Y", 4.0)))
    except:
        vix, wti, us10y = 20.0, 70.0, 4.0
        
    shutdown_reason = ""
    if vix >= 30.0: shutdown_reason = f"VIX 지수 위험 수치 도달 ({vix})"
    elif wti >= 95.0: shutdown_reason = f"WTI 유가 인플레이션 한계치 돌파 ({wti})"
    elif us10y >= 4.8: shutdown_reason = f"미 국채 10년물 금리 발작 ({us10y}%)"
        
    if shutdown_reason:
        if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[Macro Shutdown 발동]\n{shutdown_reason}\n시스템 보호를 위해 오늘의 모든 신규 분할 매수를 전면 중단(Skip)합니다.")
        return

    split_orders = load_json_from_gdrive("split_orders.json") or {}
    if not split_orders: return
    
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)
    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    messages = []
    keys_to_delete = []
    
    for oid, info in split_orders.items():
        ticker, name, daily_budget = info["ticker"], info["name"], info["daily_budget"]
        remain, reason = info["remaining_days"], info["reason"]
        mode_type = info.get("mode_type", "PAPER_ONLY") 
        
        val = kis.get_valuation_data(ticker)
        # 데이터 무결성 검증 방어막 적용
        if not val or int(val.get("current_price", 0)) <= 0: continue
            
        current_price = int(val["current_price"])
        chart_data_list = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=5)
        if not chart_data_list or len(chart_data_list) < 5: continue
            
        ma5 = sum(day['close'] for day in chart_data_list) / 5
        nth_round = 11 - remain
        
        if current_price <= ma5 * 1.03:
            qty = int(daily_budget // current_price)
            if qty > 0:
                order_mgr.execute_order(ticker, name, qty, current_price, "buy", f"{reason} ({nth_round}/10회차 눌림목)", mode_type)
                messages.append(f"[매수 성공] {name}({ticker}): {qty}주 매수 완료 ({nth_round}/10회차) | 주가 <= 5일선+3%")
                info["remaining_days"] -= 1
            else:
                messages.append(f"[예산 부족] {name}({ticker}): 스킵 ({nth_round}/10회차)")
                info["remaining_days"] -= 1
        else:
            messages.append(f"[매수 보류] {name}({ticker}): 단기 과열 스킵 [현재가 {current_price:,}원 > 5일선 {int(ma5):,}원+3%].")

        if info["remaining_days"] <= 0:
            keys_to_delete.append(oid)
            messages.append(f"  └── [알림] {name} 10회 분할 매수 스케줄 최종 종료.")
            
    for k in keys_to_delete: del split_orders[k]
    if messages or keys_to_delete: save_json_to_gdrive(split_orders, "split_orders.json")
    if messages and CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[자동 분할 매수 데몬 (이평선 눌림목 모드)]\n" + "\n".join(messages))

def is_first_trading_day_of_month():
    today = datetime.now(KST)
    if today.weekday() >= 5: return False 
    if today.day == 1: return True
    if today.day == 2 and today.weekday() == 0: return True
    if today.day == 3 and today.weekday() == 0: return True
    return False

def check_monthly_quarterly():
    if is_first_trading_day_of_month():
        today = datetime.now(KST)
        if today.month in [1, 4, 7, 10]:
            quarterly_routine()
        else:
            monthly_routine()

def run_scheduler():
    schedule.every().day.at("08:45").do(daily_routine)
    schedule.every().monday.at("09:45").do(weekly_routine)
    schedule.every().day.at("10:45").do(check_monthly_quarterly)
    schedule.every().day.at("11:45").do(execute_daily_split_buys)
    schedule.every().day.at("14:30").do(daily_fundamental_stop_loss)
    schedule.every(30).minutes.do(run_risk_routine)
    while True:
        schedule.run_pending()
        time.sleep(1)

# ==============================================================
# 슬랙 명령어 처리
# ==============================================================
@app.message(re.compile(r"^!잔고", re.IGNORECASE))
def cmd_balance(message, say):
    say("[System] KIS 실전 계좌 및 AI 가상 장부 현황을 조회합니다...")
    def bg_task():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        cash_url = f"{URL}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {token}",
            "appkey": APP_KEY, "appsecret": SECRET_KEY, "tr_id": "TTTC8908R"
        }
        params = {
            "CANO": ACC_NO[:8], "ACNT_PRDT_CD": ACC_NO[8:], "PDNO": "",
            "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        cash_balance = 0
        try:
            res = requests.get(cash_url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                cash_balance = int(res.json().get("output", {}).get("ord_psbl_cash", "0"))
        except: pass

        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        split_orders = load_json_from_gdrive("split_orders.json") or {}
        
        msg = ["[ 현재 계좌 및 포트폴리오 현황 ]"]
        msg.append(f"KIS 실계좌 매수 가능 현금: {cash_balance:,}원\n")
        
        if not portfolio:
            msg.append("텅~ (현재 장부에 감시 중인 보유 종목이 없습니다.)")
        else:
            msg.append("[ 보유 종목 리스크 감시 현황 ]")
            kis.set_token(token)
            for ticker, info in portfolio.items():
                qty = info.get("quantity", 0)
                avg_price = info.get("avg_price", 0)
                mode = info.get("mode_type", "PAPER")
                reason = info.get("reason", "매수 근거 기록 없음") 
                
                val = kis.get_valuation_data(ticker)
                curr_price = int(val.get("current_price", 0)) if val else 0
                
                if curr_price > 0 and avg_price > 0:
                    ret_pct = ((curr_price - avg_price) / avg_price) * 100
                    ret_str = f"+{ret_pct:.2f}%" if ret_pct > 0 else f"{ret_pct:.2f}%"
                    msg.append(f"- {info['name']}({ticker}) [{mode}] : {qty}주 | 평단 {avg_price:,.0f}원 -> 현재 {curr_price:,}원 ({ret_str})")
                    # 긴 문장을 내어쓰기 형태로 가독성 있게 출력
                    msg.append(f"  내러티브: {reason}\n")
        
        if split_orders:
            msg.append("\n[ 10일 분할 매수 진행 중 ]")
            for oid, info in split_orders.items():
                reason = info.get("reason", "매수 근거 기록 없음")
                msg.append(f"- {info['name']} : {11 - info['remaining_days']}/10회차 진행 중 (1일 예산 {info['daily_budget']:,.0f}원)")
                msg.append(f"  내러티브: {reason}\n")
                
        say("\n".join(msg))
    threading.Thread(target=bg_task, daemon=True).start()

def execute_unified_scan(say, candidates, keyword_msg):
    unique_candidates = []
    seen = set()
    for c in candidates:
        if c['ticker'] not in seen:
            seen.add(c['ticker'])
            unique_candidates.append(c)

    if not unique_candidates:
        return say(f"[Error] {keyword_msg} 소속 종목을 추출하지 못했습니다.")
        
    say(f"[System] 총 {len(unique_candidates)}개 종목 대상 100점 만점 펀더멘털 스크리닝(차트/수급/실적YoY)을 시작합니다. (API 딜레이로 약 1~3분 소요)")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    
    passed_stocks = quant_screener.run_unified_screener(unique_candidates, URL, APP_KEY, SECRET_KEY, token, DART_API_KEY)
    
    if not passed_stocks:
        return say(f"[결과] {keyword_msg} 관련 종목 중 펀더멘털 스코어 70점(수급/실적)을 넘은 진짜 대장주가 전멸했습니다. (모두 가치함정 또는 역배열)")

    theme_memory = load_json_from_gdrive("theme_context.json") or {}
    report_msg = [f"[ 100점 만점 펀더멘털 검증 완료 ({len(passed_stocks)}종목 합격) ]"]
    
    for p in passed_stocks:
        ticker, name, target_theme = p['ticker'], p['name'], p['target_theme']
        score = p.get('score', 0)
        current_price = p.get('current_price', 0)
        details = ', '.join(p.get('score_details', []))
        
        fundamentals = {"score": score, "details": details, "pbr": p.get("pbr"), "per": p.get("per")}
        narrative = ai_strategy.get_theme_stock_narrative(target_theme, name, ticker, fundamentals)
        theme_memory[ticker] = f"[테마: {target_theme} | 총점: {score}]\n{narrative}"
        
        report_msg.append(f"\n[ {name} ({ticker}) - {target_theme} | 현재가: {current_price:,}원 ]\n  - 펀더멘털 총점: {score}점\n  - 획득 내역: {details}\n  - [AI 팩트체크]\n{narrative}")

    save_json_to_gdrive(theme_memory, "theme_context.json")
    say("\n".join(report_msg))

@app.message(re.compile(r"^!일일보고", re.IGNORECASE))
def cmd_daily_report(message, say):
    say("[System] 수동 일일 시황 브리핑 작성을 시작합니다 (산업 리포트 분석 포함). 약 1~2분 소요될 수 있습니다.")
    def bg_task():
        macro = macro_collector.get_macro_indicators()
        us_kw, kr_kw = ai_strategy.infer_news_keywords()
        us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
        kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
        research_reports = research_crawler.get_latest_industry_reports(limit=8)
        report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, research_reports, "수동 요청")
        say(f"[일간 마감 브리핑]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!주간보고", re.IGNORECASE))
def cmd_weekly_report(message, say):
    say("[System] 수동 주간 포트폴리오 진단을 시작합니다.")
    def bg_task():
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return say("[결과] 장부에 보유 중인 종목이 없습니다.")
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=3, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
        say(f"[주간 포트폴리오 진단]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!월간보고", re.IGNORECASE))
def cmd_monthly_report(message, say):
    say("[System] 수동 월간 포트폴리오 리포트 작성을 시작합니다.")
    def bg_task():
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return say("[결과] 장부에 보유 중인 종목이 없습니다.")
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=4, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
        say(f"[월간 포트폴리오 리포트]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!분기보고", re.IGNORECASE))
def cmd_quarterly_report(message, say):
    say("[System] 수동 분기 포트폴리오 리포트 작성을 시작합니다.")
    def bg_task():
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return say("[결과] 장부에 보유 중인 종목이 없습니다.")
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=5, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
        say(f"[분기 포트폴리오 리포트]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!수동등록", re.IGNORECASE))
def manual_register_stock(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split()
    if len(parts) < 2: return say("[Error] 사용법: !수동등록 [종목코드]")
        
    ticker = re.sub(r'[^\d]', '', parts[1])[:6]
    say(f"[System] {ticker} KIS 증권사 잔고 조회를 시작합니다...")
    
    def bg_task():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        kis.set_token(token)
        qty, avg_price, found_mode = 0, 0.0, "PAPER_ONLY"
        
        for test_mode in ["LIVE", "PAPER"]:
            tr_id = "TTTC8434R" if test_mode == "LIVE" else "VTTC8434R"
            url = f"{URL}/uapi/domestic-stock/v1/trading/inquire-balance"
            headers = {
                "Content-Type": "application/json", "authorization": f"Bearer {token}",
                "appkey": APP_KEY, "appsecret": SECRET_KEY, "tr_id": tr_id
            }
            params = {
                "CANO": ACC_NO[:8], "ACNT_PRDT_CD": ACC_NO[8:], "AFHR_FLPR_YN": "N",
                "OFL_YN": "", "INQR_DVSN": "01", "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
            }
            try:
                res = requests.get(url, headers=headers, params=params, timeout=5)
                if res.status_code == 200:
                    for item in res.json().get("output1", []):
                        if item.get("pdno") == ticker:
                            hldg_qty = int(item.get("hldg_qty", "0"))
                            if hldg_qty > 0:
                                qty = hldg_qty
                                avg_price = float(item.get("pchs_avg_pric", "0"))
                                found_mode = "NORMAL" if test_mode == "LIVE" else "PAPER_ONLY"
                                break
            except: pass
            if qty > 0: break
            
        if qty <= 0: return say(f"[결과] 잔고에서 {ticker} 종목을 찾을 수 없습니다. (매수 체결 후 등록 요망)")

        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        stock_name, div_yield, is_etf = get_stock_info_naver(ticker)
        if is_etf: return say(f"[거절] {stock_name}({ticker})은(는) ETF 종목입니다. 시스템 장부에 등록 불가.")
        
        if ticker in portfolio:
            portfolio[ticker].update({"quantity": qty, "avg_price": avg_price, "mode_type": found_mode})
            portfolio[ticker]["high_water_mark"] = max(portfolio[ticker].get("high_water_mark", avg_price), avg_price)
            save_json_to_gdrive(portfolio, "paper_portfolio.json")
            say(f"[Success] {stock_name}({ticker}) 기존 가상 장부 업데이트 완료.\n(잔고 연동: {qty}주 / 평단 {avg_price:,.0f}원)")
        else:
            say(f"[System] {stock_name}({ticker}) 잔고 확인 완료 ({qty}주). AI 팩트체크 리포트 생성 중...")
            valuation = kis.get_valuation_data(ticker)
            # 데이터 무결성 검증 추가
            if not valuation or int(valuation.get("current_price", 0)) <= 0:
                return say(f"[에러] {stock_name} 주가 데이터를 가져오지 못했습니다.")
            valuation.update({"div_yield": div_yield, "name": stock_name})
            
            chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
            macro = macro_collector.get_macro_indicators()
            
            report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, portfolio, valuation, theme_context="사용자 수동 발굴")
            
            # re.DOTALL 적용하여 개행 무시하고 끝까지 가져옴
            summary_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
            short_reason = summary_match.group(1).strip() if summary_match else "AI 팩트체크 완료"
            reason_log = f"수동등록 | {short_reason}"
            
            portfolio[ticker] = {"name": stock_name, "quantity": qty, "avg_price": avg_price, "high_water_mark": avg_price, "mode_type": found_mode, "reason": reason_log}
            save_json_to_gdrive(portfolio, "paper_portfolio.json")
            say(f"[ {stock_name}({ticker}) 수동 등록 완료 및 AI 리포트 ]\n- 연동: {qty}주 / 평단 {avg_price:,.0f}원\n- 펀더멘털 손절 감시 활성화\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!발굴", re.IGNORECASE))
def cmd_discover_merged(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split(" ", 1)
    
    if len(parts) < 2 or parts[1].strip().replace('.', '', 1).isdigit():
        bm_rate = float(parts[1].strip()) if len(parts) > 1 and parts[1].strip().replace('.', '', 1).isdigit() else 4.0
        say(f"[System] 목표 배당률 {bm_rate}% 이상 고배당 가치주 스캐닝을 시작합니다.")
        
        def bg_task_div():
            token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
            candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, bm_rate)
            passed_stocks = quant_screener.run_screener(candidates, URL, APP_KEY, SECRET_KEY, token, bm_rate, DART_API_KEY)
            if not passed_stocks: return say("[결과] 통과한 가치주가 없습니다.")
            report_msg = [f"[ 배당 가치주 발굴 완료 ({len(passed_stocks)}종목) ]"]
            for p in passed_stocks:
                price = p.get('current_price', 0)
                report_msg.append(f"- {p['name']}({p['ticker']}): 현재가 {price:,}원, 배당 {p['div_yield']}%, PBR {p['pbr']}, ROE {p['roe']}%")
            say("\n".join(report_msg))
        threading.Thread(target=bg_task_div, daemon=True).start()
        
    else:
        keyword = parts[1].strip()
        def bg_task_theme():
            say(f"[System] '{keyword}' 키워드를 네이버 공식 테마 메뉴판과 대조합니다...")
            all_themes = theme_crawler.get_all_naver_themes()
            if not all_themes: return say("[Error] 네이버 테마 메뉴판을 긁어오지 못했습니다.")
                
            matched_names = ai_strategy.match_naver_themes(keyword, list(all_themes.keys()))
            if not matched_names: return say(f"[결과] '{keyword}'와 일치하는 공식 테마를 찾지 못했습니다.")
                
            say(f"[System] AI 라우팅 완료. 매핑된 테마: {', '.join(matched_names)}\n해당 테마 전 종목 100점 스코어링 시작...")
            all_candidates = []
            for t_name in matched_names:
                all_candidates.extend(theme_crawler.get_stocks_by_theme_link(all_themes[t_name], t_name))
            execute_unified_scan(say, all_candidates, keyword)
        threading.Thread(target=bg_task_theme, daemon=True).start()

def process_ai_buy(ticker, budget, say):
    def bg_task():
        try:
            stock_name, div_yield, is_etf = get_stock_info_naver(ticker)
            if is_etf:
                say(f"[거절] {stock_name}({ticker})은(는) ETF 종목입니다. AI 매수 불가.")
                return

            actual_mode = os.getenv("TRADING_MODE_NORMAL", "PAPER").upper()
            say(f"[System] {stock_name}({ticker}) 최종 매수 승인 보고서 작성 중... (모드: {actual_mode})")
            
            token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
            kis.set_token(token)
            valuation = kis.get_valuation_data(ticker)
            
            # 데이터 무결성 검증 추가
            if not valuation or int(valuation.get("current_price", 0)) <= 0:
                return say(f"[에러] {stock_name} 주가 데이터를 가져오지 못했습니다. KIS 서버 상태를 확인하세요.")
                
            valuation.update({"div_yield": div_yield, "name": stock_name})
            
            chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
            macro = macro_collector.get_macro_indicators()
            pf = load_json_from_gdrive("paper_portfolio.json") or {}
            theme_memory = load_json_from_gdrive("theme_context.json") or {}
            
            report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context=theme_memory.get(ticker, ""))
            
            order_id = str(uuid.uuid4())
            
            # re.DOTALL 적용하여 개행 무시하고 끝까지 가져옴
            summary_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
            full_reason = summary_match.group(1).strip() if summary_match else "AI 분석 완료"

            pending_orders[order_id] = {
                "ticker": ticker, "total_budget": budget, "current_price": int(valuation.get("current_price", 0)), 
                "report": report, "stock_name": stock_name, "mode_type": "NORMAL", "reason": full_reason
            }
            say(f"[System] {stock_name}({ticker}) 최종 AI 리포트 ({actual_mode})\n\n{report}")
            say(blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": f"반대 및 리스크 근거를 확인하셨습니까? 최종 10일 분할매수({actual_mode}) 승인을 내려주십시오."}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": f"승인 ({actual_mode} 매수)"}, "style": "primary", "action_id": "approve_buy", "value": order_id},
                    {"type": "button", "text": {"type": "plain_text", "text": "기각 (취소)"}, "style": "danger", "action_id": "reject_buy", "value": order_id}
                ]}
            ], text="승인 대기 중")
        except Exception as e:
            say(f"[Error] 승인 보고서 오류: {str(e)}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!ai매수", re.IGNORECASE))
def ai_buy_stock(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split()
    if len(parts) < 3: return say("[Error] 사용법: !ai매수 [종목코드] [총예산]\n예시: !ai매수 005930 1000000")
    
    ticker = re.sub(r'[^\d]', '', parts[1])[:6]
    budget = int(re.sub(r'[^\d]', '', parts[2]))
    process_ai_buy(ticker, budget, say)

@app.action("approve_buy")
def action_approve_buy(ack, body, respond):
    ack()
    order_id = body["actions"][0]["value"]
    if order_id not in pending_orders: return respond(text="[Error] 만료된 주문입니다.", replace_original=False)
    order = pending_orders.pop(order_id)
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    
    reason = f"AI 승인 | {order.get('reason', '사유 누락')}"
    
    res = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO).simulate_split_buy(
        order["ticker"], order["stock_name"], order["total_budget"], order["current_price"], f"{reason} (1/10회차 대기)"
    )
    if res["success"]:
        split_orders = load_json_from_gdrive("split_orders.json") or {}
        split_orders[str(uuid.uuid4())] = {
            "ticker": order["ticker"], "name": order["stock_name"], "daily_budget": res["daily_budget"], 
            "remaining_days": 10, "reason": reason, "mode_type": order["mode_type"] 
        }
        save_json_to_gdrive(split_orders, "split_orders.json")
        respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n{res['msg']}\n(매 평일 11시 45분 5일선 눌림목 도달 시에만 기계적 매수)", replace_original=True)
    else: respond(text=f"[Fail] {res['msg']}", replace_original=True)

@app.action("reject_buy")
def action_reject_buy(ack, body, respond):
    ack()
    if body["actions"][0]["value"] in pending_orders: del pending_orders[body["actions"][0]["value"]]
    respond(text=f"[Notice] <@{body['user']['id']}> 님이 매수를 기각했습니다.", replace_original=True)

@app.message("!초기화")
def reset_paper_data(message, say):
    save_json_to_gdrive([], "paper_trades.json")
    save_json_to_gdrive({}, "paper_portfolio.json")
    save_json_to_gdrive({}, "split_orders.json")
    save_json_to_gdrive({}, "theme_context.json")
    say("[System] 모의 매매, 예약 주문, 테마 메모리 초기화 완료.")

@app.event("message")
def handle_unhandled_message_events(body, logger): pass

if __name__ == "__main__":
    print("Log: [System] Active KST", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
