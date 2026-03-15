# -*- coding: utf-8 -*-
# File: ~/my_bot/main.py
import os, time, threading, schedule, sys, re, uuid
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import token_manager, account_info, macro_collector, ai_strategy, chart_data, stock_finder
import risk_manager, quant_screener
from kis_api import KISClient
from order_manager import OrderManager
from trade_logger import save_json_to_gdrive, load_json_from_gdrive

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
BENCHMARK_TICKER = "^TNX" 
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
        if title: 
            name = title.text.split(':')[0].strip()
        dvr = soup.find('em', id='_dvr')
        if dvr: 
            div = float(dvr.text.strip().replace(',', ''))
    except Exception as e:
        print(f"Log: [Naver Parse Error] {str(e)}")
    return name, div

def get_empty_result_blocks():
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "스캐닝 결과 만족 종목이 없습니다. 단기 반등(5MA>20MA) 조건으로 재검색하시겠습니까?"}
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "단기 반등 재검색"}, "style": "primary", "action_id": "action_relaxed_scan"},
                {"type": "button", "text": {"type": "plain_text", "text": "관망 유지"}, "action_id": "action_keep_observing"}
            ]
        }
    ]

def run_risk_routine():
    print(f"Log: [Risk Daemon] 실시간 리스크 감시 시작 ({datetime.now(KST)})", flush=True)
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID)

def daily_routine():
    if not CHANNEL_ID: return
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    macro = macro_collector.get_macro_indicators()
    if res["success"]:
        msg = (f"*[Daily Routine]*\n- 예수금: {int(float(res['cash'])):,}원\n"
               f"- 현재 수익률: {float(res['total_ratio']):+.2f}%\n- 기준 금리: {macro.get('us_10y_yield')}%")
        app.client.chat_postMessage(channel=CHANNEL_ID, text=msg)

def weekly_routine():
    if not CHANNEL_ID: return
    app.client.chat_postMessage(channel=CHANNEL_ID, text="[Weekly Routine] KIS 동적 퀀트 스캐너 가동 (약 30초)")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    benchmark = float(macro_collector.get_macro_indicators().get("us_10y_yield", 4.0))
    raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
    candidates = quant_screener.run_screener(raw_candidates, URL, APP_KEY, SECRET_KEY, token, benchmark, DART_API_KEY)

    if candidates:
        msg = [f"[주간 스캐너: {len(candidates)}종목 발굴]"]
        for c in candidates: msg.append(f"- {c['name']}({c['ticker']}): 배당 {c['div_yield']}%, PBR {c['pbr']}, ROE {c['roe']}%")
        app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg))
    else:
        app.client.chat_postMessage(channel=CHANNEL_ID, blocks=get_empty_result_blocks())

def run_scheduler():
    schedule.every().monday.at("08:45").do(daily_routine)
    schedule.every().tuesday.at("08:45").do(daily_routine)
    schedule.every().wednesday.at("08:45").do(daily_routine)
    schedule.every().thursday.at("08:45").do(daily_routine)
    schedule.every().friday.at("08:45").do(daily_routine)
    schedule.every().monday.at("09:10").do(weekly_routine)
    schedule.every(30).minutes.do(run_risk_routine)
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.message("!초기화")
def reset_paper_data(message, say):
    save_json_to_gdrive([], "paper_trades.json")
    save_json_to_gdrive({}, "paper_portfolio.json")
    say("[System] 모의 매매 기록 초기화 완료.")

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

# [수정] 거래 내역에서 최근 매수 사유를 역추적하는 로직 추가
@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    pf = load_json_from_gdrive("paper_portfolio.json") or {}
    trades = load_json_from_gdrive("paper_trades.json") or []
    
    pf_msg = "*[가상 장부 보유 종목]*\n"
    if not pf:
        pf_msg += "보유 종목 없음\n"
    else:
        for t, info in pf.items():
            if info.get('quantity', 0) > 0:
                name = info.get('name', t)
                qty = info.get('quantity', 0)
                avg_price = int(info.get('avg_price', 0))
                
                # paper_trades.json 역순 탐색으로 해당 종목의 가장 최근 사유 추출
                reason = "기록 없음"
                for trade in reversed(trades):
                    if trade.get('ticker') == t and trade.get('reason'):
                        reason = trade.get('reason')
                        break
                        
                pf_msg += f"- {name}({t}): {qty}주 (평단 {avg_price}원)\n  └── 📝 사유: {reason}\n"
                
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

    say(f"[System] {ticker} 분석 시작 (약 10~20초)")

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
                print("Log: [AI Task] 차트 데이터 재수집 시도", flush=True)
                time.sleep(1)
                chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)

            macro = macro_collector.get_macro_indicators()
            pf = load_json_from_gdrive("paper_portfolio.json") or {}

            report = ai_strategy.get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation)
            
            order_id = str(uuid.uuid4())
            pending_orders[order_id] = {
                "ticker": ticker, "total_budget": budget, 
                "current_price": int(valuation.get("current_price", 0)), "report": report
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
    
    res = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO).simulate_split_buy(order["ticker"], f"종목_{order['ticker']}", order["total_budget"], order["current_price"], reason)
    respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n{res['msg']}", replace_original=True) if res["success"] else respond(text=f"[Fail] {res['msg']}", replace_original=True)

@app.action("reject_buy")
def action_reject_buy(ack, body, respond):
    ack()
    if body["actions"][0]["value"] in pending_orders: del pending_orders[body["actions"][0]["value"]]
    respond(text=f"[Notice] <@{body['user']['id']}> 님이 매수를 기각했습니다.", replace_original=True)

@app.action("action_relaxed_scan")
def handle_relaxed_scan(ack, body, respond):
    ack()
    respond(text=f"<@{body['user']['id']}> 요청으로 단기 반등(5MA>20MA) 스캐너 가동 중...", replace_original=True)
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
def handle_unhandled_message_events(body, logger):
    pass

if __name__ == "__main__":
    print(f"Log: [System] Active at {datetime.now(KST)}", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
