# -*- coding: utf-8 -*-
# File: ~/my_bot/main.py
import os, time, threading, schedule, sys, re, uuid
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

def run_risk_routine():
    print(f"Log: [Risk Daemon] 실시간 리스크 감시 시작 ({datetime.now(KST)})")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID)

def daily_routine():
    print(f"Log: [Daily Routine] 시작 ({datetime.now(KST)})")
    if not CHANNEL_ID:
        return
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    macro = macro_collector.get_macro_indicators()
    
    if res["success"]:
        msg = (f"*[Daily Routine]*\n- 예수금: {int(float(res['cash'])):,}원\n"
               f"- 현재 수익률: {float(res['total_ratio']):+.2f}%\n- 기준 금리: {macro.get('us_10y_yield')}%")
        app.client.chat_postMessage(channel=CHANNEL_ID, text=msg)

def weekly_routine():
    print(f"Log: [Weekly Routine] 퀀트 스캐너 시작 ({datetime.now(KST)})")
    if not CHANNEL_ID:
        return
    
    app.client.chat_postMessage(channel=CHANNEL_ID, text="[Weekly Routine] 주간 동적 퀀트 스캐너 가동을 시작합니다. (약 1분 소요)")
    
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)
    macro = macro_collector.get_macro_indicators()
    benchmark_str = macro.get("us_10y_yield", 4.0)
    benchmark = float(benchmark_str) if benchmark_str != "N/A" else 4.0

    print("Log: [Main] 1차 stock_finder 데이터 수집 시작")
    raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
    candidates = quant_screener.run_screener(raw_candidates, benchmark, kis, DART_API_KEY)

    if candidates:
        msg_lines = [f"[주간 스캐너 결과: 최정예 {len(candidates)}종목 발굴]"]
        for c in candidates:
            name = c.get("name", "Unknown")
            ticker = c.get("ticker", c.get("code", ""))
            msg_lines.append(f"- {name}({ticker}): 배당 {c.get('div_yield')}% / PBR {c.get('pbr')} / ROE {c.get('roe')}% ({c.get('source')} 검증)")
        app.client.chat_postMessage(channel=CHANNEL_ID, text="\n".join(msg_lines))
    else:
        app.client.chat_postMessage(channel=CHANNEL_ID, text="[Notice] 이번 주 스캐닝 결과, 조건을 만족하는 종목이 없습니다. 서버의 디버그 로그를 확인해 주십시오.")

def quarterly_routine():
    if CHANNEL_ID:
        app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Quarterly Routine]* 분기 실적 기반 밸류에이션 조정을 실시합니다.")

def half_yearly_routine():
    if CHANNEL_ID:
        app.client.chat_postMessage(channel=CHANNEL_ID, text="*[Half-Yearly Routine]* 상/하반기 결산 및 전략 수정을 검토합니다.")

def run_scheduler():
    schedule.every().monday.at("08:45").do(daily_routine)
    schedule.every().tuesday.at("08:45").do(daily_routine)
    schedule.every().wednesday.at("08:45").do(daily_routine)
    schedule.every().thursday.at("08:45").do(daily_routine)
    schedule.every().friday.at("08:45").do(daily_routine)
    
    schedule.every().monday.at("09:10").do(weekly_routine)
    schedule.every(30).minutes.do(run_risk_routine)
    
    def check_calendar():
        now = datetime.now(KST)
        if now.day == 1 and now.month in [1, 4, 7, 10]: quarterly_routine()
        if now.day == 1 and now.month in [1, 7]: half_yearly_routine()

    schedule.every().day.at("00:05").do(check_calendar)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

@app.message("!초기화")
def reset_paper_data(message, say):
    try:
        save_json_to_gdrive([], "paper_trades.json")
        save_json_to_gdrive({}, "paper_portfolio.json")
        say("[System] 시스템 메시지: 모든 모의 매매 기록과 포트폴리오 잔고가 완벽하게 초기화(Reset) 되었습니다.")
    except Exception as e:
        say(f"[Error] 초기화 중 오류 발생: {str(e)}")

@app.message("!리스크점검")
def force_run_risk_manager(message, say):
    say("[System] 수동 지시 수신: 리스크 감시 데몬을 즉각 가동합니다.")
    if not CHANNEL_ID:
        say("[Error] SLACK_CHANNEL 환경 변수가 설정되지 않았습니다.")
        return
    try:
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        risk_manager.run_risk_monitor(kis, URL, APP_KEY, SECRET_KEY, token, ACC_NO, app, CHANNEL_ID, say_func=say)
        say("[System] 리스크 감시 사이클이 완료되었습니다.")
    except Exception as e:
        say(f"[Error] 데몬 실행 중 오류: {str(e)}")

@app.message("!발굴")
def discover_stocks(message, say):
    def background_discovery():
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        kis.set_token(token)
        macro = macro_collector.get_macro_indicators()
        benchmark_str = macro.get("us_10y_yield", 4.0)
        benchmark = float(benchmark_str) if benchmark_str != "N/A" else 4.0
        
        target_div = round(benchmark * 0.8, 2)
        say(f"[System] 동적 스캐너 가동: 배당률 {target_div}% 이상, 흑자(ROE>0) 기업 탐색 (디버그 모드, 약 1분 소요)")
        
        print("Log: [Main Debug] 1차 stock_finder 데이터 수집 시작")
        raw_candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark)
        candidates = quant_screener.run_screener(raw_candidates, benchmark, kis, DART_API_KEY)
        
        if candidates:
            msg_lines = [f"[스캐닝 완료: 최정예 {len(candidates)}종목 발굴]"]
            for c in candidates:
                name = c.get("name", "Unknown")
                ticker = c.get("ticker", c.get("code", ""))
                msg_lines.append(f"- {name}({ticker}): 배당 {c.get('div_yield')}% / PBR {c.get('pbr')} / ROE {c.get('roe')}% ({c.get('source')} 검증)")
            say("\n".join(msg_lines))
        else:
            say(f"[Notice] 현재 조건을 만족하는 종목이 없습니다. 서버 터미널의 [Screener Debug] 로그를 확인해 주십시오.")

    threading.Thread(target=background_discovery, daemon=True).start()

@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    paper_portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    paper_msg = "*[가상 장부 보유 종목]*\n"
    if not paper_portfolio:
        paper_msg += "보유 종목 없음\n"
    else:
        for t, info in paper_portfolio.items():
            if info['quantity'] > 0:
                paper_msg += f"- {info['name']}({t}): {info['quantity']}주 (평단가: {int(info['avg_price'])}원)\n"
                
    if res["success"]:
        say(f"*[실계좌 잔고]*: {int(float(res['cash'])):,}원 / *[수익률]*: {float(res['total_ratio']):+.2f}%\n\n{paper_msg}")

@app.message("!모의매수")
def paper_buy_stock(message, say):
    raw_text = message.get("text", "")
    clean_text = re.sub(r'<[^|>]*\|([^>]+)>', r'\1', raw_text)
    clean_text = re.sub(r'<([^>]+)>', r'\1', clean_text)
    
    parts = clean_text.split()
    if len(parts) < 3:
        say("[Error] 사용법: !모의매수 [종목코드] [총투자금액]")
        return

    ticker = re.sub(r'[^\d]', '', parts[1])[:6]
    total_budget = int(re.sub(r'[^\d]', '', parts[2]))

    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)
    valuation = kis.get_valuation_data(ticker)
    
    current_price = int(valuation.get("current_price", 0))
    reason = f"Slack 수동 지시 (현재가: {current_price}원, 총예산: {total_budget}원)"

    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    res = order_mgr.simulate_split_buy(ticker, f"종목_{ticker}", total_budget, current_price, reason)
    say(f"[Success] 모의매수 기록 완료:\n{res['msg']}" if res["success"] else f"[Fail] 모의매수 실패: {res['msg']}")

@app.message(re.compile(r"^!ai매수", re.IGNORECASE))
def ai_buy_stock(message, say):
    raw_text = message.get("text", "")
    clean_text = re.sub(r'<[^|>]*\|([^>]+)>', r'\1', raw_text)
    clean_text = re.sub(r'<([^>]+)>', r'\1', clean_text)
    
    parts = clean_text.split()
    if len(parts) < 3:
        say("[Error] 사용법: !AI매수 [종목코드] [총투자금액]")
        return

    ticker = re.sub(r'[^\d]', '', parts[1])[:6]
    total_budget = int(re.sub(r'[^\d]', '', parts[2]))

    say(f"[System] {ticker} 종목의 시장 데이터를 수집하고 AI 분석을 시작합니다. (약 10~20초 소요)")

    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)

    valuation = kis.get_valuation_data(ticker)
    current_price = int(valuation.get("current_price", 0))
    chart_30d = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30)
    macro = macro_collector.get_macro_indicators()
    paper_portfolio = load_json_from_gdrive("paper_portfolio.json") or {}

    report = ai_strategy.get_ai_investment_report(ticker, chart_30d, macro, paper_portfolio, valuation)

    order_id = str(uuid.uuid4())
    pending_orders[order_id] = {
        "ticker": ticker,
        "total_budget": total_budget,
        "current_price": current_price,
        "report": report
    }

    say(f"*[System] {ticker} AI 투자 분석 리포트*\n\n{report}")

    button_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "위 AI의 리포트 및 *[반대 근거]*를 명확히 확인하셨습니까? 이성에 기반하여 최종 결정을 내려주십시오."
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "승인 (10일 분할매수)"},
                    "style": "primary",
                    "action_id": "approve_buy",
                    "value": order_id
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "기각 (매수 취소)"},
                    "style": "danger",
                    "action_id": "reject_buy",
                    "value": order_id
                }
            ]
        }
    ]
    say(blocks=button_blocks, text="AI 리포트 승인 대기 중")

@app.action("approve_buy")
def action_approve_buy(ack, body, respond):
    ack()
    user_id = body["user"]["id"]
    order_id = body["actions"][0]["value"]

    if order_id not in pending_orders:
        respond(text="[Error] 만료되었거나 이미 처리된 주문입니다.", replace_original=False)
        return

    order = pending_orders.pop(order_id)
    ticker, total_budget, current_price, report = order["ticker"], order["total_budget"], order["current_price"], order["report"]

    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    first_line = report.strip().split('\n')[0]
    short_reason = first_line[:80] + "..." if len(first_line) > 80 else first_line
    reason = f"AI 승인 매수 (현재가: {current_price}원) | {short_reason}"
    
    res = order_mgr.simulate_split_buy(ticker, f"종목_{ticker}", total_budget, current_price, reason)
    
    if res["success"]:
        respond(text=f"[Success] <@{user_id}> 님이 AI 매수 논리를 승인했습니다.\n{res['msg']}", replace_original=True)
    else:
        respond(text=f"[Fail] 승인하였으나 실행에 실패했습니다: {res['msg']}", replace_original=True)

@app.action("reject_buy")
def action_reject_buy(ack, body, respond):
    ack()
    user_id = body["user"]["id"]
    order_id = body["actions"][0]["value"]
    
    if order_id in pending_orders:
        del pending_orders[order_id]
        
    respond(text=f"[Notice] <@{user_id}> 님이 위험성을 인지하고 매수를 기각했습니다. 훌륭한 리스크 관리입니다.", replace_original=True)

if __name__ == "__main__":
    print(f"Log: [System] Stock Bot Command Center Active at {datetime.now(KST)}", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
