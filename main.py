# -*- coding: utf-8 -*-
# File: ~/my_bot/main.py (전체 업데이트)
import os, time, threading, schedule
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import token_manager
import account_info
import macro_collector
import ai_strategy
import stock_finder
from kis_api import KISClient

load_dotenv()
APP_KEY, SECRET_KEY, ACC_NO = os.getenv("APP_KEY"), os.getenv("SECRET_KEY"), os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
app = App(token=os.getenv("SLACK_TOKEN"))
kis = KISClient()

@app.message("!잔고")
def show_balance(message, say):
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    result = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    if result["success"]:
        msg = (f"* 현재 잔고 현황*\n- 예수금: {int(float(result['cash'])):,}원\n"
               f"- 평가손익: {int(float(result['total_pnl'])):,}원\n- 총 수익률: {float(result['total_ratio']):+.2f}%")
        say(msg)

@app.message("!분석")
def analyze_stock(message, say):
    ticker = message.get("text", "").split()[-1]
    say(f"{ticker} 종목 분석을 시작합니다...")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    kis.set_token(token)
    val_data = kis.get_valuation_data(ticker) # PBR, PER, ROE 수집
    macro = macro_collector.get_macro_indicators()
    balance = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    report = ai_strategy.get_ai_investment_report(ticker, {}, macro, balance, val_data)
    say(f"{ticker} 전략 보고서*\n\n{report}")

@app.message("!발굴")
def discover_dividend_stocks(message, say):
    say("[Section 1. Rule 4] 원칙에 따라 고배당 유망주를 발굴 중입니다...")
    token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
    macro = macro_collector.get_macro_indicators()
    
    # 기준 금리 설정 (미국 10년물 국채 금리 등)
    benchmark_rate = float(macro.get("us_10y_yield", 3.5))
    
    # 파이썬에서 1차 수치 필터링 (토큰 절약 전략)
    candidates = stock_finder.get_high_dividend_candidates(URL, APP_KEY, SECRET_KEY, token, benchmark_rate)
    
    if not candidates:
        say(f"현재 시장 금리({benchmark_rate}%)보다 높은 배당 수익률을 가진 종목을 찾지 못했습니다.")
        return

    result_msg = f"✅ 금리({benchmark_rate}%) 대비 매력적인 고배당주 {len(candidates)}개를 찾았습니다.\n"
    for c in candidates:
        result_msg += f"- {c['name']}({c['ticker']}): 배당수익률 {c['div_yield']}%\n"
    
    say(result_msg)
    say("이 중 가장 유망한 종목에 대해 AI 심층 리뷰를 진행합니다...")
    
    # 가장 배당률이 높은 1순위 종목 자동 분석
    top_ticker = candidates[0]['ticker']
    kis.set_token(token)
    val_data = kis.get_valuation_data(top_ticker)
    balance = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
    report = ai_strategy.get_ai_investment_report(top_ticker, {}, macro, balance, val_data)
    say(f"오늘의 추천 고배당주 분석 ({candidates[0]['name']})*\n\n{report}")

if __name__ == "__main__":
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
