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
import risk_manager, quant_screener, market_hours, news_crawler
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
    name, div = ticker, 0.0
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = soup.find('title')
        if title: name = title.text.split(':')[0].strip()
        dvr = soup.find('em', id='_dvr')
        if dvr: div = float(dvr.text.strip().replace(',', ''))
    except: pass
    return name, div

# [핵심 수정] 보고서 루틴은 장 시간이 아니라 주말 여부만 체크합니다.
def is_weekday():
    return datetime.now(KST).weekday() < 5

def daily_routine():
    if not is_weekday(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 일일 시황 브리핑 작성을 시작합니다.")
    macro = macro_collector.get_macro_indicators()
    us_kw, kr_kw = ai_strategy.infer_news_keywords()
    us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
    kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
    report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, "특이사항 없음")
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"*[일간 마감 브리핑]*\n\n{report}")

def weekly_routine():
    if not is_weekday(): return
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="[System] 주간 포트폴리오 진단을 시작합니다.")
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=3, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"*[주간 포트폴리오 진단]*\n\n{report}")

def monthly_routine():
    if not is_weekday(): return
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=4, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"*[월간 포트폴리오 리포트]*\n\n{report}")

def quarterly_routine():
    if not is_weekday(): return
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return
    news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=5, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
    report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
    if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"*[분기 포트폴리오 리포트]*\n\n{report}")

def run_risk_routine():
    if not market_hours.is_market_open(): return
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID)

def execute_daily_split_buys():
    if not market_hours.is_market_open(): return
    
    # [핵심 수정] 매크로 셧다운 스위치: VIX, 유가(WTI), 국채금리 종합 연동
    macro = macro_collector.get_macro_indicators()
    try:
        vix = float(macro.get("VIX", 20.0))
        # API 딕셔너리 키는 macro_collector 구현에 따라 다를 수 있으므로 범용적으로 탐색
        wti = float(macro.get("WTI", macro.get("wti", 70.0)))
        us10y = float(macro.get("us_10y_yield", macro.get("US10Y", 4.0)))
    except:
        vix, wti, us10y = 20.0, 70.0, 4.0
        
    shutdown_reason = ""
    if vix >= 30.0:
        shutdown_reason = f"VIX 지수 위험 수치 도달 ({vix})"
    elif wti >= 95.0:
        shutdown_reason = f"WTI 유가 인플레이션 한계치 돌파 (${wti})"
    elif us10y >= 4.8:
        shutdown_reason = f"미 국채 10년물 금리 발작 ({us10y}%)"
        
    if shutdown_reason:
        if CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text=f"[Macro Shutdown 발동]\n{shutdown_reason}\n성장주 밸류에이션 붕괴 위험을 감지하여 시스템 보호를 위해 오늘의 모든 신규 분할 매수를 전면 중단(Skip)합니다.")
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
        
        val = kis.get_valuation_data(ticker)
        if not val: continue
        current_price = int(val.get("current_price", 0))
        if current_price <= 0: continue

        chart_data_list = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=5)
        if not chart_data_list or len(chart_data_list) < 5:
            continue
            
        closes = [day['close'] for day in chart_data_list]
        ma5 = sum(closes) / 5
        nth_round = 11 - remain
        
        if current_price <= ma5 * 1.03:
            qty = int(daily_budget // current_price)
            if qty > 0:
                order_mgr.execute_order(ticker, name, qty, current_price, "buy", f"{reason} ({nth_round}/10회차 눌림목)")
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
    if messages and CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="*[자동 분할 매수 데몬 (이평선 눌림목 모드)]*\n" + "\n".join(messages))

def check_monthly_quarterly():
    today = datetime.now(KST)
    if today.day == 1:
        if today.month in [1, 4, 7, 10]:
            quarterly_routine()
        else:
            monthly_routine()

def run_scheduler():
    schedule.every().day.at("08:45").do(daily_routine)
    schedule.every().monday.at("09:45").do(weekly_routine)
    schedule.every().day.at("10:45").do(check_monthly_quarterly)
    schedule.every().day.at("11:45").do(execute_daily_split_buys)
    schedule.every(30).minutes.do(run_risk_routine)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.message("!일일보고")
def cmd_daily_report(message, say):
    threading.Thread(target=daily_routine, daemon=True).start()

@app.message("!주간보고")
def cmd_weekly_report(message, say):
    threading.Thread(target=weekly_routine, daemon=True).start()

@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    pf = load_json_from_gdrive("paper_portfolio.json") or {}
    trades = load_json_from_gdrive("paper_trades.json") or []
    pf_msg = "*[가상 장부 보유 종목]*\n"
    if not pf: pf_msg += "보유 종목 없음\n"
    else:
        for t, info in pf.items():
            if info.get('quantity', 0) > 0:
                name = info.get('name', t)
                if name.startswith("종목_"): name, _ = get_stock_info_naver(t)
                qty = info.get('quantity', 0)
                avg_price = int(info.get('avg_price', 0))
                reason = "기록 없음"
                for trade in reversed(trades):
                    if trade.get('ticker') == t and trade.get('reason'):
                        reason = trade.get('reason')
                        break
                pf_msg += f"- {name}({t}): {qty}주 (평단 {avg_price:,}원)\n  └── [사유]: {reason}\n"
    if res["success"]: say(f"*[실계좌 잔고]*: {int(float(res['cash'])):,}원 / *[수익률]*: {float(res['total_ratio']):+.2f}%\n\n{pf_msg}")

@app.message(re.compile(r"^!테마발굴", re.IGNORECASE))
def discover_theme_stocks(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split(" ", 1)
    
    def bg_task():
        themes = []
        if len(parts) > 1 and parts[1].strip():
            themes = [parts[1].strip()]
            say(f"[System] '{themes[0]}' 관련 테마주 스캐닝을 시작합니다.")
        else:
            say("[System] AI가 주도 테마를 스스로 발굴합니다...")
            trending_str = ai_strategy.get_trending_themes()
            themes = [t.strip() for t in trending_str.split(',') if t.strip()]
            say(f"*[AI 추론 주도 테마]*: {', '.join(themes)}")

        all_candidates = []
        seen_tickers = set()
        
        for theme in themes:
            candidates = ai_strategy.get_theme_universe(theme)
            for c in candidates:
                ticker = c.get("ticker")
                if ticker and ticker not in seen_tickers:
                    c["target_theme"] = theme 
                    all_candidates.append(c)
                    seen_tickers.add(ticker)

        if not all_candidates:
            return say("[Error] 테마 종목을 추론하지 못했습니다.")
            
        say(f"[System] AI 1차 후보군 ({len(all_candidates)}개) 검증 시작...")
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        passed_stocks = quant_screener.run_theme_screener(all_candidates, URL, APP_KEY, SECRET_KEY, token, DART_API_KEY)
        
        if not passed_stocks:
            return say(f"[결과] 매출/흑자, 추세가 살아있는 종목이 없습니다.")

        theme_memory = {}
        report_msg = [f"*[ 융합형 성장주 발굴 완료 ({len(passed_stocks)}종목) ]*"]
        
        for p in passed_stocks:
            ticker, name, target_theme = p['ticker'], p['name'], p['target_theme']
            fundamentals = {"roe": p.get("roe"), "per": p.get("per"), "pbr": p.get("pbr"), "sales": p.get("sales")}
            narrative = ai_strategy.get_theme_stock_narrative(target_theme, name, ticker, fundamentals)
            
            theme_memory[ticker] = f"[테마: {target_theme}]\n{narrative}"
            report_msg.append(f"\n*[ {name} ({ticker}) - {target_theme} ]*\n  - 매출/흑자 검증완료 / ROE {p.get('roe')}%\n  - [AI 내러티브]\n{narrative}")

        save_json_to_gdrive(theme_memory, "theme_context.json")
        say("\n".join(report_msg))

    threading.Thread(target=bg_task, daemon=True).start()

@app.message(re.compile(r"^!ai매수", re.IGNORECASE))
def ai_buy_stock(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split()
    if len(parts) < 3: return say("[Error] 사용법: !AI매수 [종목코드] [금액]")
    ticker, budget = re.sub(r'[^\d]', '', parts[1])[:6], int(re.sub(r'[^\d]', '', parts[2]))

    say(f"*[System]* {ticker} 심층 분석 시작 (약 20초)")
    def bg_task():
        try:
            token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
            kis.set_token(token)
            stock_name, div_yield = get_stock_info_naver(ticker)
            valuation = kis.get_valuation_data(ticker)
            valuation["div_yield"] = div_yield
            valuation["name"] = stock_name
            chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
            if not chart_30d:
                time.sleep(1)
                chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
            macro = macro_collector.get_macro_indicators()
            pf = load_json_from_gdrive("paper_portfolio.json") or {}
            
            theme_memory = load_json_from_gdrive("theme_context.json") or {}
            context = theme_memory.get(ticker, "")

            report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context=context)
            
            order_id = str(uuid.uuid4())
            pending_orders[order_id] = {
                "ticker": ticker, "total_budget": budget, 
                "current_price": int(valuation.get("current_price", 0)), 
                "report": report, "stock_name": stock_name 
            }
            say(f"*[System] {stock_name}({ticker}) AI 리포트*\n\n{report}")
            say(blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": "반대 근거를 확인하셨습니까? 최종 결정을 내려주십시오."}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "승인 (10일 이평선 매수)"}, "style": "primary", "action_id": "approve_buy", "value": order_id},
                    {"type": "button", "text": {"type": "plain_text", "text": "기각 (매수 취소)"}, "style": "danger", "action_id": "reject_buy", "value": order_id}
                ]}
            ], text="승인 대기 중")
        except Exception as e:
            say(f"[Error] AI 분석 오류: {str(e)}")
    threading.Thread(target=bg_task, daemon=True).start()

@app.action("approve_buy")
def action_approve_buy(ack, body, respond):
    ack()
    order_id = body["actions"][0]["value"]
    if order_id not in pending_orders: return respond(text="[Error] 만료된 주문입니다.", replace_original=False)
    order = pending_orders.pop(order_id)
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    summary_match = re.search(r'\[한줄요약\](.*)', order['report'])
    short_reason = summary_match.group(1).strip()[:40] if summary_match else "AI 팩트 기반 승인"
    reason = f"AI 승인 | {short_reason}"
    res = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO).simulate_split_buy(
        order["ticker"], order["stock_name"], order["total_budget"], order["current_price"], f"{reason} (1/10회차 대기)"
    )
    if res["success"]:
        split_orders = load_json_from_gdrive("split_orders.json") or {}
        split_orders[str(uuid.uuid4())] = {
            "ticker": order["ticker"], "name": order["stock_name"],
            "daily_budget": order["total_budget"] / 10, "remaining_days": 10, "reason": reason
        }
        save_json_to_gdrive(split_orders, "split_orders.json")
        respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n*(매 평일 11시 45분 5일선 눌림목 조건 도달 시에만 매수합니다)*", replace_original=True)
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
    print(f"Log: [System] Active KST", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
