# -*- coding: utf-8 -*-
# File: ~/my_bot/main.py
import os, time, threading, schedule, sys, re
from datetime import datetime
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import token_manager, account_info, market_hours, macro_collector, ai_strategy, chart_data, stock_finder
from kis_api import KISClient
from order_manager import OrderManager

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
BENCHMARK_TICKER = "^TNX" 

app = App(token=os.getenv("SLACK_TOKEN"))
kis = KISClient()

# --- [4단계 루틴 정의] ---

def daily_routine():
    print(f"Log: [Daily Routine] 시작 ({datetime.now()})")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    macro = macro_collector.get_macro_indicators()
    
    if res["success"]:
        msg = (f"*[Daily Routine]*\n- 예수금: {int(float(res['cash'])):,}원\n"
               f"- 현재 수익률: {float(res['total_ratio']):+.2f}%\n- 기준 금리: {macro.get('us_10y_yield')}%")
        app.client.chat_postMessage(channel="stock-bot", text=msg)

def weekly_routine():
    print("Log: [Weekly Routine] 실행")
    app.client.chat_postMessage(channel="stock-bot", text="*[Weekly Routine]* 이번 주 고배당 유망주 발굴을 시작합니다.")

def quarterly_routine():
    print("Log: [Quarterly Routine] 실행")
    app.client.chat_postMessage(channel="stock-bot", text="*[Quarterly Routine]* 분기 실적 기반 밸류에이션 조정을 실시합니다.")

def half_yearly_routine():
    print("Log: [Half-Yearly Routine] 실행")
    app.client.chat_postMessage(channel="stock-bot", text="*[Half-Yearly Routine]* 상/하반기 결산 및 전략 수정을 검토합니다.")

# --- [스케줄러 매니저] ---
def run_scheduler():
    schedule.every().monday.at("08:45").do(daily_routine)
    schedule.every().tuesday.at("08:45").do(daily_routine)
    schedule.every().wednesday.at("08:45").do(daily_routine)
    schedule.every().thursday.at("08:45").do(daily_routine)
    schedule.every().friday.at("08:45").do(daily_routine)
    
    schedule.every().monday.at("09:10").do(weekly_routine)
    
    def check_calendar():
        now = datetime.now()
        if now.day == 1 and now.month in [1, 4, 7, 10]: quarterly_routine()
        if now.day == 1 and now.month in [1, 7]: half_yearly_routine()

    schedule.every().day.at("00:05").do(check_calendar)
    
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- [슬랙 명령어 핸들러] ---
@app.message("!발굴")
def discover_stocks(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    macro = macro_collector.get_macro_indicators()
    
    benchmark = macro.get("us_10y_yield", 4.0)
    if benchmark == "N/A": benchmark = 4.0
    
    say(f"[System] 금리({benchmark}%)보다 높은 배당주를 찾는 중...")
    candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, float(benchmark))
    
    if candidates:
        msg = "*[발굴된 후보군]*\n" + "\n".join([f"- {c['name']}: {c['div_yield']}%" for c in candidates])
        say(msg)
    else:
        say(f"[Notice] 현재 기준 금리({benchmark}%)를 초과하는 종목이 없습니다.")

@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    if res["success"]:
        say(f"*[잔고]*: {int(float(res['cash'])):,}원 / *[수익률]*: {float(res['total_ratio']):+.2f}%")

@app.message("!모의매수")
def paper_buy_stock(message, say):
    """Slack에서 수동으로 모의 매수를 지시하는 테스트 명령어"""
    raw_text = message.get("text", "")
    
    # [Fix] 1차 방어선: Slack의 전화번호/웹사이트 자동 링크(<tel:...|보이는텍스트>)에서 순수 텍스트만 추출
    clean_text = re.sub(r'<[^|>]*\|([^>]+)>', r'\1', raw_text)
    clean_text = re.sub(r'<([^>]+)>', r'\1', clean_text)
    
    parts = clean_text.split()
    if len(parts) < 3:
        say("[Error] 사용법: !모의매수 [종목코드] [총투자금액]")
        return

    # [Fix] 2차 방어선: 종목코드 변수에서 숫자 6자리만 강제 추출
    ticker = re.sub(r'[^\d]', '', parts[1])
    if len(ticker) < 6:
        say(f"[Error] 유효한 종목코드가 아닙니다. (인식된 값: '{ticker}')")
        return
    ticker = ticker[:6] # 혹시 더 길게 잡혔다면 앞의 6자리만 사용
    
    # [Fix] 3차 방어선: 투자금액에서 숫자만 강제 추출
    raw_budget_str = re.sub(r'[^\d]', '', parts[2])
    if not raw_budget_str:
        say(f"[Error] 투자금액에서 숫자를 인식할 수 없습니다. (인식된 값: '{parts[2]}')")
        return
        
    try:
        total_budget = int(raw_budget_str)
    except ValueError:
        say("[Error] 투자금액 변환 중 알 수 없는 오류가 발생했습니다.")
        return

    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)

    # 현재가 조회
    valuation = kis.get_valuation_data(ticker)
    if not valuation:
        say(f"[Error] {ticker} 종목의 가격 정보를 불러올 수 없습니다.")
        return

    current_price = int(valuation.get("current_price", 0))
    reason = f"Slack 수동 지시 (현재가: {current_price}원, 총예산: {total_budget}원)"

    # 모의 매수 실행 (총 예산의 1/10을 1회차로 매수)
    order_mgr = OrderManager(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    res = order_mgr.simulate_split_buy(ticker, f"종목_{ticker}", total_budget, current_price, reason)

    if res["success"]:
        say(f"[Success] 모의매수 기록 완료:\n{res['msg']}")
    else:
        say(f"[Fail] 모의매수 실패: {res['msg']}")

if __name__ == "__main__":
    print("Log: [System] Stock Bot Command Center Active.", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
