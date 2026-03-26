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

def get_empty_result_blocks():
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "스캐닝 결과 만족 종목이 없습니다. 단기 반등 조건으로 재검색할까요?"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "단기 반등 재검색"}, "style": "primary", "action_id": "action_relaxed_scan"},
            {"type": "button", "text": {"type": "plain_text", "text": "관망 유지"}, "action_id": "action_keep_observing"}
        ]}
    ]

def run_risk_routine():
    if not market_hours.is_market_open(): return
    print(f"Log: [Risk Daemon] 실시간 리스크 감시 시작 ({datetime.now(KST)})", flush=True)
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID)

def execute_daily_split_buys():
    if not market_hours.is_market_open(): return
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
        
        if current_price > 0:
            qty = int(daily_budget // current_price)
            nth_round = 11 - remain
            if qty > 0:
                order_mgr.execute_paper_order(ticker, name, qty, current_price, "buy", f"{reason} ({nth_round}/10회차)")
                messages.append(f"- {name}({ticker}): {qty}주 매수 완료 ({nth_round}/10회차)")
            else:
                messages.append(f"- {name}({ticker}): 예산 부족 스킵 ({nth_round}/10회차)")
        
        info["remaining_days"] -= 1
        if info["remaining_days"] <= 0:
            keys_to_delete.append(oid)
            messages.append(f"  └── [알림] {name} 10일 분할 매수 종료.")
            
    for k in keys_to_delete: del split_orders[k]
    if messages or keys_to_delete: save_json_to_gdrive(split_orders, "split_orders.json")
    if messages and CHANNEL_ID: app.client.chat_postMessage(channel=CHANNEL_ID, text="*[자동 분할 매수 데몬 작동]*\n" + "\n".join(messages))

def daily_routine():
    if not CHANNEL_ID: return
    # [수정] 딜레이에 대한 슬랙 안내 추가
    app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Daily Routine]* 일간 매크로 점검 및 AI 시황 리포트 작성을 시작합니다.\n*(안내: 최적 검색어 추론 등 AI 연속 호출로 인해 약 1~2분의 딜레이가 발생합니다. 잠시만 기다려주세요.)*")
    
    def bg_task():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
        macro = macro_collector.get_macro_indicators()
        
        pf = load_json_from_gdrive("paper_portfolio.json") or {}
        trades = load_json_from_gdrive("paper_trades.json") or []
        
        disclosures = {}
        dart = OpenDartReader(DART_API_KEY) if DART_API_KEY else None
        if dart:
            yesterday_str = (datetime.now(KST) - timedelta(days=1)).strftime('%Y%m%d')
            today_str = datetime.now(KST).strftime('%Y%m%d')
            for t, info in pf.items():
                if info.get('quantity', 0) > 0:
                    try:
                        dart_res = dart.list(t, start=yesterday_str, end=today_str)
                        if dart_res is not None and not dart_res.empty:
                            disclosures[info['name']] = dart_res['report_nm'].tolist()
                    except: pass

        # [수정] AI를 이용한 검색어 사전 추론 (1st Call)
        us_kw, kr_kw = ai_strategy.infer_news_keywords()
        print(f"Log: [AI Keyword] US: {us_kw} / KR: {kr_kw}")
        
        # 추론된 키워드로 크롤링
        us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
        kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
        
        # 리포트 생성 (2nd Call)
        ai_report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, disclosures)
        
        pf_msg = "*[가상 장부 보유 종목]*\n"
        if not pf: pf_msg += "보유 종목 없음\n"
        else:
            for t, info in pf.items():
                if info.get('quantity', 0) > 0:
                    name = info.get('name', t)
                    if name.startswith("종목_"):
                        name, _ = get_stock_info_naver(t)
                        
                    qty = info.get('quantity', 0)
                    avg_price = int(info.get('avg_price', 0))
                    reason = "기록 없음"
                    for trade in reversed(trades):
                        if trade.get('ticker') == t and trade.get('reason'):
                            reason = trade.get('reason')
                            break
                    pf_msg += f"- {name}({t}): {qty}주 (평단 {avg_price:,}원)\n  └── [사유]: {reason}\n"

        if res["success"]:
            msg = (f"*[실계좌 잔고]*: {int(float(res['cash'])):,}원 / *[수익률]*: {float(res['total_ratio']):+.2f}%\n\n"
                   f"{pf_msg}\n"
                   f"=================================\n\n"
                   f"*[AI Daily Market Briefing]*\n\n{ai_report}")
            app.client.chat_postMessage(channel=CHANNEL_ID, text=msg)
    threading.Thread(target=bg_task, daemon=True).start()

def weekly_routine():
    if not CHANNEL_ID: return
    # [수정] 딜레이 안내 추가
    app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Weekly Routine]* 주간 포트폴리오 이유 진단 및 스캐너를 가동합니다.\n*(안내: 포트폴리오 순회 및 AI 분석으로 인해 종목당 약 30초 이상의 딜레이가 발생합니다.)*")
    
    def bg_task():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        kis.set_token(token)
        pf = load_json_from_gdrive("paper_portfolio.json") or {}
        trades = load_json_from_gdrive("paper_trades.json") or []
        
        active_holdings = {t: info for t, info in pf.items() if info.get('quantity', 0) > 0}
        
        if not active_holdings:
            app.client.chat_postMessage(channel=CHANNEL_ID, text="보유 종목이 없어 포트폴리오 이유 진단을 생략합니다. 주간 스캐너를 바로 가동합니다.")
        else:
            portfolio_details = {}
            news_dict = {}
            
            for t, info in active_holdings.items():
                name = info.get('name', t)
                if name.startswith("종목_"):
                    name, _ = get_stock_info_naver(t)
                    
                avg_price = info.get('avg_price', 0)
                val = kis.get_valuation_data(t)
                current_price = int(val.get("current_price", 0)) if val else 0
                return_rate = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
                
                reason = "기록 없음"
                for trade in reversed(trades):
                    if trade.get('ticker') == t and trade.get('reason'):
                        reason = trade.get('reason')
                        break
                
                portfolio_details[name] = {"최초매수사유": reason, "평단가": avg_price, "현재가": current_price, "현재수익률": f"{return_rate:+.2f}%"}
                news_dict[name] = news_crawler.get_latest_news(name, limit=5, search_type="stock")
                time.sleep(1)
            
            ai_report = ai_strategy.get_weekly_portfolio_report(portfolio_details, news_dict)
            app.client.chat_postMessage(channel=CHANNEL_ID, text=f"*[AI Weekly Portfolio Review]*\n\n{ai_report}")
        
        benchmark = float(macro_collector.get_macro_indicators().get("us_10y_yield", 4.0))
        raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
        candidates = quant_screener.run_screener(raw_candidates, URL, APP_KEY, SECRET_KEY, token, benchmark, DART_API_KEY)

        if candidates:
            msg = [f"[주간 스캐너: {len(candidates)}종목 발굴]"]
            for c in candidates: msg.append(f"- {c['name']}({c['ticker']}): 배당 {c['div_yield']}%, PBR {c['pbr']}, ROE {c['roe']}%")
            app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg))
        else:
            app.client.chat_postMessage(channel=CHANNEL_ID, blocks=get_empty_result_blocks())
            
    threading.Thread(target=bg_task, daemon=True).start()

def quarterly_routine():
    if not CHANNEL_ID: return
    now = datetime.now(KST)
    if now.month not in [1, 4, 7, 10] or now.day > 7: return
        
    app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Quarterly Routine]* 분기 실적 시즌 전면 스캐닝을 시작합니다.")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    benchmark = float(macro_collector.get_macro_indicators().get("us_10y_yield", 4.0))
    raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
    candidates = quant_screener.run_screener(raw_candidates, URL, APP_KEY, SECRET_KEY, token, benchmark, DART_API_KEY)

    if candidates:
        msg = [f"[분기 전면 스캐너: {len(candidates)}종목 발굴]"]
        for c in candidates: msg.append(f"- {c['name']}({c['ticker']}): 배당 {c['div_yield']}%, PBR {c['pbr']}, ROE {c['roe']}%")
        app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg))
    else:
        app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Quarterly Routine]* 대장주가 없습니다. 보수적 운용을 권장합니다.")

def run_scheduler():
    # [수정] 모든 스케줄을 1시간 단위로 재배치 (API 과부하 및 타임아웃 방지)
    
    # 1. 일간 루틴: 매일 08:45
    schedule.every().monday.at("08:45").do(daily_routine)
    schedule.every().tuesday.at("08:45").do(daily_routine)
    schedule.every().wednesday.at("08:45").do(daily_routine)
    schedule.every().thursday.at("08:45").do(daily_routine)
    schedule.every().friday.at("08:45").do(daily_routine)
    
    # 2. 주간 루틴: 매주 월요일 09:45 (일간 루틴과 1시간 간격)
    schedule.every().monday.at("09:45").do(weekly_routine)
    
    # 3. 분기 루틴: 매주 월요일 10:45 (주간 루틴과 1시간 간격, 조건부 실행)
    schedule.every().monday.at("10:45").do(quarterly_routine)

    # 4. 일일 분할 매수 데몬: 매일 11:45 (모든 분석 루틴 종료 후 가장 안정적인 시간에 매수)
    schedule.every().monday.at("11:45").do(execute_daily_split_buys)
    schedule.every().tuesday.at("11:45").do(execute_daily_split_buys)
    schedule.every().wednesday.at("11:45").do(execute_daily_split_buys)
    schedule.every().thursday.at("11:45").do(execute_daily_split_buys)
    schedule.every().friday.at("11:45").do(execute_daily_split_buys)

    schedule.every(30).minutes.do(run_risk_routine)
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.message("!일일보고")
def manual_daily_routine(message, say):
    say("일간 루틴(AI 시황 리포트)을 수동으로 즉시 가동합니다.")
    daily_routine()

@app.message("!주간보고")
def manual_weekly_routine(message, say):
    say("주간 루틴(포트폴리오 변동 이유 분석 및 스캐너)을 수동으로 즉시 가동합니다.")
    weekly_routine()

@app.message("!분기보고")
def manual_quarterly_routine(message, say):
    say("분기 루틴을 수동으로 가동합니다 (강제 실행이므로 월/일 조건 무시).")
    app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Quarterly Routine]* 분기 실적 시즌 전면 스캐닝을 시작합니다.")
    def bg_task():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        benchmark = float(macro_collector.get_macro_indicators().get("us_10y_yield", 4.0))
        raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
        candidates = quant_screener.run_screener(raw_candidates, URL, APP_KEY, SECRET_KEY, token, benchmark, DART_API_KEY)
        if candidates:
            msg = [f"[분기 전면 스캐너: {len(candidates)}종목 발굴]"]
            for c in candidates: msg.append(f"- {c['name']}({c['ticker']}): 배당 {c['div_yield']}%, PBR {c['pbr']}, ROE {c['roe']}%")
            app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg))
        else:
            app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Quarterly Routine]* 대장주가 없습니다. 보수적 운용을 권장합니다.")
    threading.Thread(target=bg_task, daemon=True).start()

@app.message("!초기화")
def reset_paper_data(message, say):
    save_json_to_gdrive([], "paper_trades.json")
    save_json_to_gdrive({}, "paper_portfolio.json")
    save_json_to_gdrive({}, "split_orders.json")
    say("[System] 모의 매매 및 예약 주문 기록 초기화 완료.")

@app.message("!리스크점검")
def force_run_risk_manager(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID, say_func=say)

@app.message("!발굴")
def discover_stocks(message, say):
    def background_discovery():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        benchmark = float(macro_collector.get_macro_indicators().get("us_10y_yield", 4.0))
        target_div = round(benchmark * 0.8, 2)
        say(f"[System] 스캐너 가동: 배당률 {target_div}% 이상, 흑자 탐색 (약 30초)")
        
        raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
        candidates = quant_screener.run_screener(raw_candidates, URL, APP_KEY, SECRET_KEY, token, benchmark, DART_API_KEY)
        
        if candidates:
            msg = [f"[스캐닝 완료: {len(candidates)}종목 발굴]"]
            for c in candidates: msg.append(f"- {c['name']}({c['ticker']}): 배당 {c['div_yield']}%, PBR {c['pbr']}, ROE {c['roe']}%")
            say("\n".join(msg))
        else:
            say(blocks=get_empty_result_blocks(), text="종목 발굴 실패")
    threading.Thread(target=background_discovery, daemon=True).start()

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
                if name.startswith("종목_"):
                    name, _ = get_stock_info_naver(t)
                qty = info.get('quantity', 0)
                avg_price = int(info.get('avg_price', 0))
                reason = "기록 없음"
                for trade in reversed(trades):
                    if trade.get('ticker') == t and trade.get('reason'):
                        reason = trade.get('reason')
                        break
                pf_msg += f"- {name}({t}): {qty}주 (평단 {avg_price:,}원)\n  └── [사유]: {reason}\n"
                
    if res["success"]:
        say(f"*[실계좌 잔고]*: {int(float(res['cash'])):,}원 / *[수익률]*: {float(res['total_ratio']):+.2f}%\n\n{pf_msg}")

@app.message("!모의매수")
def paper_buy_stock(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split()
    if len(parts) < 3: return say("[Error] 사용법: !모의매수 [종목코드] [금액]")
    ticker, budget = re.sub(r'[^\d]', '', parts[1])[:6], int(re.sub(r'[^\d]', '', parts[2]))
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)
    current_price = int(kis.get_valuation_data(ticker).get("current_price", 0))
    res = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO).simulate_split_buy(ticker, f"종목_{ticker}", budget, current_price, f"수동 지시")
    say(f"[Success] 모의매수 완료:\n{res['msg']}" if res["success"] else f"[Fail] {res['msg']}")

@app.message(re.compile(r"^!ai매수", re.IGNORECASE))
def ai_buy_stock(message, say):
    text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
    parts = text.split()
    if len(parts) < 3: return say("[Error] 사용법: !AI매수 [종목코드] [금액]")
    ticker, budget = re.sub(r'[^\d]', '', parts[1])[:6], int(re.sub(r'[^\d]', '', parts[2]))

    say(f"*[System]* {ticker} 분석 시작 (약 10~20초)")
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

            report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation)
            order_id = str(uuid.uuid4())
            pending_orders[order_id] = {
                "ticker": ticker, "total_budget": budget, 
                "current_price": int(valuation.get("current_price", 0)), 
                "report": report,
                "stock_name": stock_name 
            }
            say(f"*[System] {stock_name}({ticker}) AI 리포트*\n\n{report}")
            say(blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": "반대 근거를 확인하셨습니까? 최종 결정을 내려주십시오."}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "승인 (10일 분할매수)"}, "style": "primary", "action_id": "approve_buy", "value": order_id},
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
        order["ticker"], order["stock_name"], order["total_budget"], order["current_price"], f"{reason} (1/10회차)"
    )
    if res["success"]:
        split_orders = load_json_from_gdrive("split_orders.json") or {}
        split_orders[str(uuid.uuid4())] = {
            "ticker": order["ticker"], "name": order["stock_name"],
            "daily_budget": order["total_budget"] / 10, "remaining_days": 9, "reason": reason
        }
        save_json_to_gdrive(split_orders, "split_orders.json")
        respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n{res['msg']}\n*(나머지 9회차는 매 평일 오전 11시 45분에 자동 매수됩니다)*", replace_original=True)
    else: respond(text=f"[Fail] {res['msg']}", replace_original=True)

@app.action("reject_buy")
def action_reject_buy(ack, body, respond):
    ack()
    if body["actions"][0]["value"] in pending_orders: del pending_orders[body["actions"][0]["value"]]
    respond(text=f"[Notice] <@{body['user']['id']}> 님이 매수를 기각했습니다.", replace_original=True)

@app.action("action_relaxed_scan")
def handle_relaxed_scan(ack, body, respond):
    ack()
    respond(text=f"<@{body['user']['id']}> 요청으로 단기 반등 스캐너 가동 중...", replace_original=True)
    def bg_task():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        bm = float(macro_collector.get_macro_indicators().get("us_10y_yield", 4.0))
        cands = quant_screener.run_screener(stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, bm), URL, APP_KEY, SECRET_KEY, token, bm, DART_API_KEY, relaxed_mode=True)
        app.client.chat_postMessage(channel=body["container"]["channel_id"], text="\n".join([f"[단기 반등 스캐너: {len(cands)}종목]"] + [f"- {c['name']}({c['ticker']}): 배당 {c['div_yield']}%, PBR {c['pbr']}, ROE {c['roe']}%" for c in cands]) if cands else "[Notice] 반등 종목 없음.")
    threading.Thread(target=bg_task, daemon=True).start()

@app.action("action_keep_observing")
def handle_keep_observing(ack, body, respond):
    ack()
    respond(text=f"<@{body['user']['id']}> 결정으로 관망을 유지합니다.", replace_original=True)

@app.event("message")
def handle_unhandled_message_events(body, logger): pass

if __name__ == "__main__":
    print(f"Log: [System] Active at {datetime.now(KST)}", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
