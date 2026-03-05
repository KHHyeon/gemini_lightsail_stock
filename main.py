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
import market_hours #

load_dotenv()

# 설정값 로드
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"

app = App(token=os.getenv("SLACK_TOKEN"))

# --- [슬랙 명령어 핸들러] ---
@app.message("!잔고")
def show_balance(message, say):
    print("Log: !잔고 명령 수신", flush=True)
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    result = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    if result["success"]:
        msg = f"*현재 잔고 현황*\n- 예수금: {int(float(result['cash'])):,}원\n- 수익률: {result['total_ratio']}%"
        say(msg)
    else:
        say(f"⚠️ 조회 실패: {result['msg']}")
        # KIS 보안 공지 반영: 계좌번호 오류(rt_cd: 7) 시 무한 재시도 방지를 위해 강제 종료
        if result.get("rt_cd") == "7":
            print("Log: [Critical] 계좌번호 설정 오류로 안전 종료합니다.", flush=True)
            os._exit(1)

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

