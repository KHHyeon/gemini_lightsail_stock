# -*- coding: utf-8 -*-
import os
import time
import schedule
import threading
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import token_manager
import account_info
import macro_collector
import ai_strategy
import chart_data
from kis_api import KISClient

load_dotenv()

APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"

app = App(token=os.getenv("SLACK_TOKEN"))
kis = KISClient()

@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    result = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    
    if result["success"]:
        msg = (
            f"* 현재 잔고 현황*\n"
            f"- 예수금: {int(float(result['cash'])):,}원\n"
            f"- 평가손익: {int(float(result['total_pnl'])):,}원\n"
            f"- 총 수익률: {float(result['total_ratio']):+.2f}%"
        )
        say(msg)

@app.message("!분석")
def analyze_stock(message, say):
    text = message.get("text", "")
    parts = text.split()
    if len(parts) < 2:
        say("종목 코드를 입력해주세요. (예: !분석 005930)")
        return

    ticker = parts[1]
    say(f"🔍 {ticker}의 PBR/ROE 및 차트 데이터를 수집하여 AI 분석을 시작합니다...")

    try:
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        kis.set_token(token)
        
        # 1. 데이터 수집
        val_data = kis.get_valuation_data(ticker) # PBR, PER, ROE
        ohlcv = chart_data.get_daily_ohlcv(URL, APP_KEY, SECRET_KEY, token, ticker, count=30) #
        macro = macro_collector.get_macro_indicators() #
        balance = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO) #
        
        # 2. AI 리포트 생성
        report = ai_strategy.get_ai_investment_report(ticker, ohlcv, macro, balance, val_data)
        
        if report:
            say(f"*📊 {ticker} AI 전략 보고서*\n\n{report}")
        else:
            say("⚠️ 보고서 생성 실패")

    except Exception as e:
        say(f"❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    print("Log: Stock Bot Command Center Starting...", flush=True)
    handler = SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN"))
    handler.start()
