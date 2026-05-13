# -*- coding: utf-8 -*-
import os, time, threading, schedule, sys, re, uuid
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import OpenDartReader

from src.core import token_manager, account_info, kis_api
from src.data import collector as macro_collector, chart as chart_data
from src.data.crawler import news_crawler, theme_crawler, research_crawler
from src.strategy import ai_logic as ai_strategy, screener as quant_screener, finder as stock_finder
from src.execution import risk_monitor as risk_manager, order as order_manager
from src.utils import helpers as market_hours, logger as trade_logger
from src.core.kis_api import KISClient
from src.execution.order import OrderManager
from src.utils.logger import save_json_to_gdrive, load_json_from_gdrive


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

def get_auth_kis(force=False):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY, force=force)
    kis.set_token(token)
    return token

def issue_daily_token():
    if not market_hours.is_market_open(): return
    get_auth_kis(force=True)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 08:00 KIS API 일일 접근 토큰 갱신 완료.")

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
    except: pass
    return name, div, is_etf

def get_parsed_keywords():
    kw_text = ai_strategy.infer_news_keywords()
    kws = [k.strip() for k in kw_text.split(',')] if kw_text else []
    us_kw = kws[0] if len(kws) > 0 else "미국증시"
    kr_kw = kws[1] if len(kws) > 1 else "한국증시"
    return us_kw, kr_kw

def daily_routine():
    if not market_hours.is_market_open(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 일일 시황 브리핑 작성을 시작합니다.")
    macro = macro_collector.get_macro_indicators()
    us_kw, kr_kw = get_parsed_keywords()
    us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
    kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
    research_reports = research_crawler.get_latest_industry_reports(limit=8)
    report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, research_reports, "특이사항 없음")
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[일간 마감 브리핑]\n\n{report}")

def deep_market_routine():
    if not market_hours.is_market_open(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 10:00 장 초반 자금 흐름 기반 심층 시황 보고를 시작합니다.")
    macro = macro_collector.get_macro_indicators()
    _, kr_kw = get_parsed_keywords()
    kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
    research_reports = research_crawler.get_latest_industry_reports(limit=5)
    report = ai_strategy.get_deep_market_report(macro, kr_news, research_reports)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[10:00 심층 시황 및 전략]\n\n{report}")

def auto_stock_discovery():
    if datetime.now(KST).weekday() >= 5: return
    token = get_auth_kis()
    
    gem_stocks = quant_screener.run_condition_screener(kis, "기대주_발굴")
    if gem_stocks:
        passed_gem = quant_screener.run_unified_screener(gem_stocks, URL, APP_KEY, SECRET_KEY, token, DART_API_KEY)
        top_gems = [p for p in passed_gem if p.get('score', 0) >= 60]
        
        msg = ["[ Track A. 기대주 (60점 상회) ]\n"]
        if not top_gems:
            msg.append("- 조건을 통과한 유망 종목이 없습니다.")
        else:
            for s in top_gems[:5]:
                name, _, _ = get_stock_info_naver(s['ticker'])
                news = news_crawler.get_latest_news(name, limit=2)
                rating = ai_strategy.get_quick_rating(s['ticker'], name, news, "기대주", s)
                msg.append(f"- {name} ({s['ticker']}) [{s.get('score')}점]\n{rating}\n")
        if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg))

    div_stocks = quant_screener.run_condition_screener(kis, "배당주_발굴")
    if div_stocks:
        msg = ["[ Track B. 배당 가치주 ]\n"]
        for s in div_stocks[:5]:
            name, _, _ = get_stock_info_naver(s['ticker'])
            news = news_crawler.get_latest_news(name, limit=2)
            val = kis.get_valuation_data(s['ticker']) or {}
            rating = ai_strategy.get_dividend_risk_check(s['ticker'], name, news, val)
            msg.append(f"- {name} ({s['ticker']})\n{rating}\n")
        if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg))

def weekly_routine():
    if not market_hours.is_market_open(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 주간 투자 이유(상승조건) 유효성 진단을 시작합니다.")
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=3, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[주간 이유 확인 리포트]\n\n{report}")

def monthly_routine():
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=4, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[월간 시장 트렌드 및 리밸런싱 리포트]\n\n{report}")

def quarterly_routine():
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=5, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[분기 핵심 실적 및 펀더멘털 점검 리포트]\n\n{report}")

def alert_manual_stocks():
    if not market_hours.is_market_open(): return
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    
    token = get_auth_kis()
    messages = []
    
    for ticker, info in portfolio.items():
        if "수동등록" in info.get("reason", ""):
            val = kis.get_valuation_data(ticker)
            if not val or int(val.get("current_price", 0)) <= 0: continue
            current_price = int(val["current_price"])
            
            chart_data_list = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=5)
            if not chart_data_list or len(chart_data_list) < 5: continue
            
            ma5 = sum(day['close'] for day in chart_data_list) / 5
            
            if current_price <= ma5 * 1.03:
                messages.append(f"- {info['name']}({ticker}) : 현재가 {current_price:,}원 (5일선 {int(ma5):,}원 부근)")
                
    if messages and CHANNEL_ID:
        app.client.chat_postMessage(channel=CHANNEL_ID, text="[수동 등록 종목 매수 타점 알림]\n현재 아래 수동 종목들이 매수 타이밍(눌림목)에 진입했습니다. 최종 매수 여부를 직접 결정해 주십시오.\n" + "\n".join(messages))

def daily_fundamental_stop_loss():
    if not market_hours.is_market_open(): return
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    
    split_orders = load_json_from_gdrive("split_orders.json") or {}
    split_orders_updated = False
    
    token = get_auth_kis()
    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    macro = macro_collector.get_macro_indicators()
    
    keys_to_delete = []
    messages = []
    portfolio_updated = False
    
    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0: continue
        
        name = info.get("name", ticker)
        mode_type = info.get("mode_type", "PAPER_ONLY")
        context = info.get("reason", "매수 근거 기록 없음")
        avg_price = info.get("avg_price", 0)
        high_water_mark = info.get("high_water_mark", avg_price)
        
        val = kis.get_valuation_data(ticker)
        if not val or int(val.get("current_price", 0)) <= 0: continue
            
        current_price = int(val["current_price"])
        
        if current_price > high_water_mark:
            info["high_water_mark"] = current_price
            high_water_mark = current_price
            portfolio_updated = True
            
        trigger_reason = None
        report_comment = ""
        
        if avg_price > 0 and current_price <= avg_price * 0.90:
            trigger_reason = "원금 방어선(-10%) 이탈 (기계적 손절)"
        elif avg_price > 0 and high_water_mark > avg_price and current_price <= high_water_mark * 0.90:
            trigger_reason = "최고점 대비 하락선(-10%) 이탈 (추적 익절/손절)"
        else:
            chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
            report = ai_strategy.check_fundamental_damage(ticker, name, chart_30d, macro, val, context)
            if "[펀더멘털훼손]" in report:
                trigger_reason = "AI 팩트체크: 투자 이유 훼손 (치명적 악재 발생)"
                report_comment = f"\n- 코멘트: {report}"
        
        if trigger_reason:
            res = order_mgr.execute_order(ticker, name, qty, current_price, "sell", trigger_reason, mode_type)
            messages.append(res["msg"] + report_comment)
            keys_to_delete.append(ticker)
            
            split_keys_to_delete = [oid for oid, s_info in split_orders.items() if s_info["ticker"] == ticker]
            if split_keys_to_delete:
                for k in split_keys_to_delete:
                    del split_orders[k]
                split_orders_updated = True
                messages.append(f"  └── [연쇄 조치] {name} 3중 방어막 가동에 따라 대기 중인 잔여 분할 매수 스케줄 강제 취소.")
            
            time.sleep(3)
        
    for k in keys_to_delete: del portfolio[k]
    
    if keys_to_delete or portfolio_updated: save_json_to_gdrive(portfolio, "paper_portfolio.json")
    if split_orders_updated: save_json_to_gdrive(split_orders, "split_orders.json")
    if messages and CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[3중 철통 방어막 및 AI 팩트 진단 결과]\n" + "\n\n".join(messages))

def execute_daily_split_buys(check_news=False):
    if not market_hours.is_market_open(): return
    macro = macro_collector.get_macro_indicators()
    try:
        vix = float(macro.get("VIX", 20.0))
        wti = float(macro.get("WTI", macro.get("wti", 70.0)))
        us10y = float(macro.get("us_10y_yield", macro.get("US10Y", 4.0)))
    except:
        vix, wti, us10y = 20.0, 70.0, 4.0
        
    shutdown_reason = ""
    half_buy_reason = ""
    
    # 2단계 셧다운 룰 적용
    if vix >= 30.0: shutdown_reason = f"VIX 지수 위험 ({vix})"
    elif vix >= 25.0: half_buy_reason = f"VIX 지수 경계 ({vix})"
    
    if wti >= 95.0: shutdown_reason = f"WTI 유가 위험 ({wti})"
    elif wti >= 90.0: half_buy_reason = f"WTI 유가 경계 ({wti})"
    
    if us10y >= 4.8: shutdown_reason = f"미 국채 10년물 금리 위험 ({us10y}%)"
    elif us10y >= 4.5: half_buy_reason = f"미 국채 금리 경계 ({us10y}%)"
        
    if shutdown_reason:
        if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[Macro Shutdown 발동]\n{shutdown_reason}\n오늘의 신규 분할 매수를 전면 중단(Skip)합니다.")
        return

    split_orders = load_json_from_gdrive("split_orders.json") or {}
    if not split_orders: return
    
    token = get_auth_kis()
    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    messages = []
    if half_buy_reason:
        messages.append(f"[Macro Alert] {half_buy_reason}\n선제적 리스크 관리를 위해 오늘 매수 예산은 50%로 축소됩니다.")
        
    keys_to_delete = []
    
    for oid, info in split_orders.items():
        ticker, name = info["ticker"], info["name"]
        daily_budget = info["daily_budget"]
        if half_buy_reason: daily_budget /= 2
        
        remain, reason = info["remaining_days"], info["reason"]
        mode_type = info.get("mode_type", "PAPER_ONLY") 
        score = info.get("score", 0)
        
        if check_news:
            recent_news = news_crawler.get_latest_news(name, limit=3, search_type="stock")
            news_text = " ".join(recent_news)
            news_check = ai_strategy.get_emergency_news_check(name, news_text)
            if "[위험]" in news_check:
                messages.append(f"[정오 긴급 스캔] {name}({ticker}) 돌발 악재 감지: 매수 스킵.\n사유: {news_check}")
                continue
        
        val = kis.get_valuation_data(ticker)
        if not val or int(val.get("current_price", 0)) <= 0: continue
            
        current_price = int(val["current_price"])
        chart_data_list = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=5)
        if not chart_data_list or len(chart_data_list) < 5: continue
            
        ma5 = sum(day['close'] for day in chart_data_list) / 5
        nth_round = 11 - remain
        
        # High-Pass 룰 적용: 85점 이상 초우량주는 5일선 + 5%까지 허용
        threshold_ratio = 1.05 if score >= 85 else 1.03
        
        if current_price <= ma5 * threshold_ratio:
            qty = int(daily_budget // current_price)
            if qty > 0:
                res = order_mgr.execute_order(ticker, name, qty, current_price, "buy", f"{reason} ({nth_round}/10회차)", mode_type)
                messages.append(res["msg"])
                info["remaining_days"] -= 1
            else:
                messages.append(f"[예산 부족] {name}({ticker}): 스킵 ({nth_round}/10회차)")
                info["remaining_days"] -= 1
        else:
            target_prc = int(ma5 * threshold_ratio)
            messages.append(f"[매수 보류] {name}({ticker}): 단기 과열 스킵 [현재가 {current_price:,}원 > 기준가 {target_prc:,}원].")

        if info["remaining_days"] <= 0:
            keys_to_delete.append(oid)
            messages.append(f"  └── [알림] {name} 10회 분할 매수 스케줄 최종 종료.")
            
    for k in keys_to_delete: del split_orders[k]
    if messages or keys_to_delete: save_json_to_gdrive(split_orders, "split_orders.json")
    if messages and CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[자동 분할 매수 데몬]\n" + "\n".join(messages))

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

def noon_routine():
    if not market_hours.is_market_open(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 11:45 정오의 보초 및 자동 분할 매수를 시작합니다.")
    execute_daily_split_buys(check_news=True)

def afternoon_routine():
    if not market_hours.is_market_open(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 14:30 장 마감 전 안전 진단(3중 방어막)을 시작합니다.")
    daily_fundamental_stop_loss()

def run_scheduler():
    schedule.every().day.at("08:00").do(issue_daily_token)
    schedule.every().day.at("08:45").do(daily_routine)
    schedule.every().day.at("08:50").do(auto_stock_discovery)
    schedule.every().day.at("10:00").do(deep_market_routine)
    schedule.every().day.at("10:45").do(check_monthly_quarterly)
    schedule.every().day.at("11:45").do(noon_routine)
    schedule.every().day.at("14:20").do(alert_manual_stocks)
    schedule.every().day.at("14:30").do(afternoon_routine)
    schedule.every().monday.at("09:45").do(weekly_routine)
    schedule.every(30).minutes.do(lambda: risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token_manager.get_access_token(APP_KEY, SECRET_KEY), ACC_NO, app, CHANNEL_ID))
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.message(re.compile(r"^!명령어", re.IGNORECASE))
def cmd_help(message, say):
    help_text = """[ 봇 명령어 매뉴얼 ]
- !잔고 : 실계좌 현금 및 포트폴리오 요약 조회
- !기대주테스트 : 기대주 발굴 (60점 커트 + AI 5단계 검증)
- !배당주테스트 : 배당주 발굴 (AI 배당컷 5단계 검증)
- !발굴 [배당률/테마] : 기존 100점 만점 펀더멘탈 스크리닝
- !ai매수 [코드] [예산] : 정밀 분석 후 10일 분할매수 세팅
- !수동등록 [코드] : 내 보유종목 방어막 감시망에 편입
- !일일보고 / !주간보고 / !월간보고 / !분기보고 : 각종 리포트 수동 생성
- !초기화 : 장부 및 주문 데이터 초기화"""
    say(help_text)

@app.message(re.compile(r"^!기대주테스트", re.IGNORECASE))
def cmd_test_gem(message, say):
    say("[System] 기대주 발굴 중입니다 (기준: 60점 이상)...")
    def task():
        token = get_auth_kis()
        stocks = quant_screener.run_condition_screener(kis, "기대주_발굴")
        if not stocks: return say("[결과] 조건식 통과 종목이 없습니다.")
        passed_gem = quant_screener.run_unified_screener(stocks, URL, APP_KEY, SECRET_KEY, token, DART_API_KEY)
        top_gems = [p for p in passed_gem if p.get('score', 0) >= 60]
        if not top_gems: return say("[결과] 60점 이상 펀더멘털 대장주가 없습니다.")
        output = ["[ 기대주 (60점 이상) 테스트 결과 ]\n"]
        for s in top_gems[:5]:
            name, _, _ = get_stock_info_naver(s['ticker'])
            news = news_crawler.get_latest_news(name, limit=2)
            rating = ai_strategy.get_quick_rating(s['ticker'], name, news, "기대주", s)
            output.append(f"- {name} ({s['ticker']}) [{s.get('score')}점]\n{rating}\n")
        say("\n".join(output))
    threading.Thread(target=task, daemon=True).start()

@app.message(re.compile(r"^!배당주테스트", re.IGNORECASE))
def cmd_test_div(message, say):
    say("[System] 배당주 스캔 및 AI 위험 검증 중...")
    def task():
        get_auth_kis()
        stocks = quant_screener.run_condition_screener(kis, "배당주_발굴")
        if not stocks: return say("[결과] 조건식 통과 종목이 없습니다.")
        output = ["[ 배당 가치주 테스트 결과 ]\n"]
        for s in stocks[:5]:
            name, _, _ = get_stock_info_naver(s['ticker'])
            news = news_crawler.get_latest_news(name, limit=2)
            val = kis.get_valuation_data(s['ticker']) or {}
            rating = ai_strategy.get_dividend_risk_check(s['ticker'], name, news, val)
            output.append(f"- {name} ({s['ticker']})\n{rating}\n")
        say("\n".join(output))
    threading.Thread(target=task, daemon=True).start()

@app.message(re.compile(r"^!잔고", re.IGNORECASE))
def cmd_balance(message, say):
    say("[System] KIS 실전 계좌 및 AI 가상 장부 현황을 조회합니다...")
    def bg_task():
        get_auth_kis()
        cash_balance = kis.get_psbl_cash()
        
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        split_orders = load_json_from_gdrive("split_orders.json") or {}
        
        msg = ["[ 현재 계좌 및 포트폴리오 현황 ]"]
        msg.append(f"KIS 실계좌 매수 가능 현금: {cash_balance:,}원\n")
        
        if not portfolio:
            msg.append("텅~ (현재 장부에 감시 중인 보유 종목이 없습니다.)")
        else:
            msg.append("[ 보유 종목 리스크 감시 현황 ]")
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
                    msg.append(f"  내러티브: {reason}\n")
                elif qty == 0:
                    msg.append(f"- {info['name']}({ticker}) [{mode}] : 관심 등록 종목 (0주 보유 중)")
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
        
    say(f"[System] 총 {len(unique_candidates)}개 종목 대상 100점 만점 펀더멘털 스크리닝(차트/수급/실적)을 시작합니다.")
    token = get_auth_kis()
    
    passed_stocks = quant_screener.run_unified_screener(unique_candidates, URL, APP_KEY, SECRET_KEY, token, DART_API_KEY)
    
    if not passed_stocks:
        return say(f"[결과] {keyword_msg} 관련 종목 중 펀더멘털 스코어 60점 이상을 획득한 대장주가 전멸했습니다.")

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
    say("[System] 수동 일일 시황 브리핑 작성을 시작합니다.")
    def bg_task():
        macro = macro_collector.get_macro_indicators()
        us_kw, kr_kw = get_parsed_keywords()
        us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
        kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
        research_reports = research_crawler.get_latest_industry_reports(limit=8)
        report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, research_reports, "수동 요청")
        say(f"[일간 마감 브리핑]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!주간보고", re.IGNORECASE))
def cmd_weekly_report(message, say):
    say("[System] 수동 주간 투자 이유(상승조건) 유효성 진단을 시작합니다.")
    def bg_task():
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return say("[결과] 장부에 보유 중인 종목이 없습니다.")
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=3, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
        say(f"[주간 이유 확인 리포트]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!월간보고", re.IGNORECASE))
def cmd_monthly_report(message, say):
    say("[System] 수동 월간 시장 트렌드 및 리밸런싱 리포트 작성을 시작합니다.")
    def bg_task():
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return say("[결과] 장부에 보유 중인 종목이 없습니다.")
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=4, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
        say(f"[월간 시장 트렌드 및 리밸런싱 리포트]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!분기보고", re.IGNORECASE))
def cmd_quarterly_report(message, say):
    say("[System] 수동 분기 핵심 실적 및 펀더멘털 점검 리포트 작성을 시작합니다.")
    def bg_task():
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return say("[결과] 장부에 보유 중인 종목이 없습니다.")
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=5, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
        say(f"[분기 핵심 실적 및 펀더멘털 점검 리포트]\n\n{report}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!수동등록", re.IGNORECASE))
def manual_register_stock(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split()
    if len(parts) < 2: return say("[Error] 사용법: !수동등록 [종목코드]")
        
    ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
    say(f"[System] {ticker} KIS 증권사 잔고 조회 및 AI 팩트체크를 시작합니다...")
    
    def bg_task():
        token = get_auth_kis()
        qty, avg_price, found_mode = 0, 0.0, "PAPER_ONLY"
        
        for test_mode in ["LIVE", "PAPER"]:
            q, a_price = kis.get_real_holding_qty(ticker, test_mode)
            if q > 0:
                qty, avg_price = q, a_price
                found_mode = "LIVE_MANUAL" if test_mode == "LIVE" else "PAPER_ONLY"
                break
            
        if qty <= 0:
            say(f"[알림] 잔고에서 {ticker} 종목을 찾을 수 없으므로, 신규 관심 종목(0주)으로 가상 장부에 등록합니다.")
            val = kis.get_valuation_data(ticker)
            avg_price = float(val.get("current_price", "0")) if val else 0.0

        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        stock_name, div_yield, is_etf = get_stock_info_naver(ticker)
        if is_etf: return say(f"[거절] {stock_name}({ticker})은(는) ETF 종목입니다. 시스템 장부에 등록 불가.")
        
        now_str = datetime.now(KST).strftime("%Y-%m-%d")
        
        valuation = kis.get_valuation_data(ticker)
        if not valuation or int(valuation.get("current_price", 0)) <= 0:
            return say(f"[에러] {stock_name} 주가 데이터를 가져오지 못했습니다.")
        valuation.update({"div_yield": div_yield, "name": stock_name})
        
        chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
        macro = macro_collector.get_macro_indicators()
        recent_news = news_crawler.get_latest_news(stock_name, limit=5, search_type="stock")
        
        report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, portfolio, valuation, theme_context="사용자 수동 발굴", recent_news=recent_news)
        
        summary_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
        short_reason = summary_match.group(1).strip() if summary_match else "AI 팩트체크 완료"
        reason_log = f"수동등록 | {short_reason}"
        
        if ticker in portfolio:
            portfolio[ticker].update({"quantity": qty, "avg_price": avg_price, "mode_type": found_mode, "reason": reason_log})
            portfolio[ticker]["high_water_mark"] = max(portfolio[ticker].get("high_water_mark", avg_price), avg_price)
            save_json_to_gdrive(portfolio, "paper_portfolio.json")
            say(f"[Success] {stock_name}({ticker}) 기존 장부 업데이트 및 펀더멘털 최신화 완료.\n(잔고 연동: {qty}주 / 평단 {avg_price:,.0f}원)\n\n{report}")
        else:
            portfolio[ticker] = {
                "name": stock_name, "quantity": qty, "avg_price": avg_price, 
                "high_water_mark": avg_price, "mode_type": found_mode, 
                "reason": reason_log, "buy_date": now_str
            }
            save_json_to_gdrive(portfolio, "paper_portfolio.json")
            say(f"[ {stock_name}({ticker}) 수동 등록 완료 및 AI 리포트 ]\n- 연동: {qty}주 / 평단 {avg_price:,.0f}원\n- 3중 방어막 손절 감시 활성화 완료\n\n{report}")
            
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
            say(f"[System] {stock_name}({ticker}) 최신 뉴스 스캔 및 최종 매수 승인 보고서 작성 중... (모드: {actual_mode})")
            
            token = get_auth_kis()
            valuation = kis.get_valuation_data(ticker)
            
            if not valuation or int(valuation.get("current_price", 0)) <= 0:
                return say(f"[에러] {stock_name} 주가 데이터를 가져오지 못했습니다. KIS 서버 상태를 확인하세요.")
                
            valuation.update({"div_yield": div_yield, "name": stock_name})
            
            chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
            macro = macro_collector.get_macro_indicators()
            pf = load_json_from_gdrive("paper_portfolio.json") or {}
            theme_memory = load_json_from_gdrive("theme_context.json") or {}
            
            recent_news = news_crawler.get_latest_news(stock_name, limit=5, search_type="stock")
            
            # High-Pass 점수 기록을 위해 1종목 퀵 스캔
            candidate = [{"ticker": ticker, "name": stock_name}]
            passed = quant_screener.run_unified_screener(candidate, URL, APP_KEY, SECRET_KEY, token, DART_API_KEY)
            score = passed[0].get("score", 0) if passed else 0
            
            report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context=theme_memory.get(ticker, ""), recent_news=recent_news)
            
            order_id = str(uuid.uuid4())
            
            summary_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
            full_reason = summary_match.group(1).strip() if summary_match else "AI 분석 완료"

            pending_orders[order_id] = {
                "ticker": ticker, "total_budget": budget, "current_price": int(valuation.get("current_price", 0)), 
                "report": report, "stock_name": stock_name, "mode_type": "NORMAL", "reason": full_reason, "score": score
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
    
    ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
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
            "remaining_days": 10, "reason": reason, "mode_type": order["mode_type"], "score": order.get("score", 0)
        }
        save_json_to_gdrive(split_orders, "split_orders.json")
        respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n{res['msg']}\n(11:45 정오 보초 루틴에 자동 매수 스케줄 편입 완료)", replace_original=True)
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
