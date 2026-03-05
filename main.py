# -*- coding: utf-8 -*-
import os
import threading
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# 기존 모듈 임포트
import token_manager
import account_info
import chart_data
import macro_collector
import ai_strategy
import schedule
import time

load_dotenv()

# 슬랙 앱 초기화 (Bot Token & App Token 필요)
app = App(token=os.getenv("SLACK_TOKEN"))
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"

# --- [슬랙 명령 핸들러] ---

@app.message("!잔고")
def show_balance(message, say):
    print("\n--- [DEBUG] !잔고 명령 수신 ---", flush=True)
    
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    print(f"1. 토큰 생성 결과: {'성공' if token else '실패'}", flush=True)
    
    if not token:
        say("토큰 생성에 실패했습니다.")
        return

    print(f"2. 잔고 조회 시도 (URL: {URL}, ACC: {ACC_NO})", flush=True)
    result = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    if result:
        print(f"3. 잔고 조회 성공: {result['cash']}원", flush=True)
        msg = f"*현재 잔고 현황*\n- 현금: {int(float(result['cash'])):,}원\n- 총 수익률: {result['total_ratio']}%"
        say(msg)
    else:
        print("3. 잔고 조회 실패 (결과가 None임)", flush=True)
        say("⚠️ 잔고 조회 실패! 서버 로그를 확인하세요.")

@app.message("!분석")
def analyze_request(message, say):
    """ '!분석 종목코드' 입력 시 AI 심층 분석 수행 """
    text = message.get('text', '').split()
    if len(text) < 2:
        say("명령어 예시: `!분석 005930` (종목코드 6자리)")
        return
    
    ticker = text[1]
    say(f"Log: [{ticker}] 종목의 심층 분석을 시작합니다. 잠시만 기다려주세요...")
    
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    charts = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker)
    macro = macro_collector.get_macro_indicators()
    
    # AI 리포트 생성 (Section 1~3 원칙 적용)
    report = ai_strategy.get_ai_investment_report(ticker, charts, macro, {"name": ticker, "pnl_ratio": "0"})
    say(f"*[{ticker} AI 전략 보고서]*\n\n{report}")

# --- [기존 스케줄러 실행 루틴] ---

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # 1. 스케줄러를 별도 스레드에서 가동
    threading.Thread(target=run_scheduler, daemon=True).start()
    
    # 2. 슬랙 명령 대기 모드 (Socket Mode) 실행
    print("Log: Slack Command Center is Active.")
    handler = SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN"))
    handler.start()
