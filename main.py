# -*- coding: utf-8 -*-
import os
import time
import schedule
import threading
import sys
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import token_manager
import account_info
import market_hours
import macro_collector
import ai_strategy

load_dotenv()

# 설정값 로드
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"

app = App(token=os.getenv("SLACK_TOKEN"))

# --- [슬랙 명령어 핸들러] ---
# main.py 의 show_balance 핸들러 수정
@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    result = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    if result["success"]:
        cash = int(float(result['cash']))
        pnl = int(float(result['total_pnl']))
        ratio = float(result['total_ratio']) # 이제 11.85 같은 값이 들어옵니다.
        
        msg = (
            f"* 현재 잔고 현황*\n"
            f"- 예수금: {cash:,}원\n"
            f"- 평가손익: {pnl:,}원\n"
            f"- 총 수익률: {ratio:+.2f}%"
        )
        say(msg)
    else:
        say(f"⚠️ 조회 실패: {result['msg']}")
        if result.get("rt_cd") == "7":
            os._exit(1)

# --- [슬랙 명령어 핸들러: !분석] ---
@app.message("!분석")
def analyze_stock(message, say):
    # 1. 명령어에서 종목 코드 추출 (예: !분석 005930)
    text = message.get("text", "")
    parts = text.split()
    if len(parts) < 2:
        say("종목 코드를 입력해주세요. (예: !분석 005930)")
        return

    ticker = parts[1]
    say(f"🔍 {ticker} 종목에 대해 사용자님의 투자 프로토콜에 따른 심층 분석을 시작합니다. (2026-03-05 데이터 기준)")

    try:
        # 2. 데이터 수집 단계
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY) #
        
        # 잔고 및 포트폴리오 상황 수집
        balance = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
        
        # 매크로 지표 수집 (환율, 금리, 유가)
        macro = macro_collector.get_macro_indicators()
        
        # 3. AI 전략 분석 요청 (Section 1~3 원칙 주입)
        # 차트 데이터는 현재 수집 로직이 없으므로 "최근 추세 반영" 메시지로 대체
        report = ai_strategy.get_ai_investment_report(ticker, "최근 30일 가격 추세", macro, balance)
        
        # 4. 결과 출력
        if report:
            say(f"*📊 {ticker} AI 전략 보고서*\n\n{report}")
        else:
            say("⚠️ AI 보고서 생성에 실패했습니다.")

    except Exception as e:
        print(f"Log: [Analysis Error] {str(e)}", flush=True)
        say(f"❌ 분석 도중 오류가 발생했습니다: {str(e)}")

# --- [정기 스케줄러 루틴] ---
def daily_job():
    if market_hours.is_market_open(): #
        print(f"Log: 정기 체크 실행 ({market_hours.get_current_kst_time()})")
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        # 여기에 v1에서 사용하던 정기 보고 로직을 추가할 수 있습니다.

def run_scheduler():
    # 1분마다 시장 상태 체크
    schedule.every(1).minutes.do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    print("Log: Stock Bot Command Center Starting...", flush=True)
    
    # 1. 스케줄러를 별도 스레드에서 실행 (병렬 처리)
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    # 2. 슬랙 소켓 모드 핸들러 실행 (메인 스레드)
    handler = SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN"))
    handler.start()
