# -*- coding: utf-8 -*-
# File: ~/my_bot/main.py
import os, time, threading, schedule, sys
from datetime import datetime
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import token_manager, account_info, market_hours, macro_collector, ai_strategy, chart_data, stock_finder
from kis_api import KISClient

load_dotenv()

# 환경 변수 및 설정
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
# 기준 금리 티커 (미국 10년물 국채 ^TNX 또는 직접 숫자 입력 가능)
BENCHMARK_TICKER = "^TNX" 

app = App(token=os.getenv("SLACK_TOKEN"))
kis = KISClient()

# --- [4단계 루틴 정의] ---

def daily_routine():
    """[매일] 개장 전 잔고 보고 및 시장 지표 브리핑"""
    print(f"Log: 일일 루틴 실행 ({datetime.now()})")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    macro = macro_collector.get_macro_indicators()
    
    if res["success"]:
        msg = (f"☀️ *[Daily Routine]*\\n- 예수금: {int(float(res['cash'])):,}원\\n"
               f"- 현재 수익률: {float(res['total_ratio']):+.2f}%\\n- 기준 금리: {macro.get('us_10y_yield')}%")
        app.client.chat_postMessage(channel="stock-bot", text=msg)

def weekly_routine():
    """[매주 월요일] 주간 종목 발굴 및 AI 전략 수립"""
    print("Log: 주간 루틴 실행")
    app.client.chat_postMessage(channel="stock-bot", text="���️ *[Weekly Routine]* 이번 주 고배당 유망주 발굴을 시작합니다.")
    # !발굴 명령어 로직을 여기서 자동 호출 가능

def quarterly_routine():
    """[분기별] 포트폴리오 PBR/ROE 가치 재평가"""
    print("Log: 분기 루틴 실행")
    app.client.chat_postMessage(channel="stock-bot", text="��� *[Quarterly Routine]* 분기 실적 기반 밸류에이션 조정을 실시합니다.")

def half_yearly_routine():
    """[반기별] 자산 배분 및 중장기 매크로 점검"""
    print("Log: 반기 루틴 실행")
    app.client.chat_postMessage(channel="stock-bot", text="��� *[Half-Yearly Routine]* 상/하반기 결산 및 전략 수정을 검토합니다.")

# --- [스케줄러 매니저] ---
def run_scheduler():
    # 일일: 평일 08:45
    schedule.every().monday.to(.friday).at("08:45").do(daily_routine)
    # 주간: 매주 월요일 09:10
    schedule.every().monday.at("09:10").do(weekly_routine)
    
    def check_calendar():
        now = datetime.now()
        # 분기 (1, 4, 7, 10월 1일)
        if now.day == 1 and now.month in [1, 4, 7, 10]: quarterly_routine()
        # 반기 (1, 7월 1일)
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
    
    # 기준 금리 유연하게 적용 (데이터 없으면 4.0% 고정값 사용)
    benchmark = macro.get("us_10y_yield", 4.0)
    if benchmark == "N/A": benchmark = 4.0
    
    say(f"��� 금리({benchmark}%)보다 높은 배당주를 찾는 중...")
    candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, float(benchmark))
    
    if candidates:
        msg = "*✅ 발굴된 후보군*\\n" + "\\n".join([f"- {c['name']}: {c['div_yield']}%" for c in candidates])
        say(msg)
    else:
        say(f"현재 기준 금리({benchmark}%)를 초과하는 종목이 없습니다.")

@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    res = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    if res["success"]:
        say(f"*��� 잔고*: {int(float(res['cash'])):,}원 / *수익률*: {float(res['total_ratio']):+.2f}%")

if __name__ == "__main__":
    print("Log: Stock Bot Command Center Active.", flush=True)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
