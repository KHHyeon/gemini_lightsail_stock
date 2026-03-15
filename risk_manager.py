# -*- coding: utf-8 -*-
# File: ~/my_bot/risk_manager.py
import time
from datetime import datetime, timezone, timedelta
from trade_logger import load_json_from_gdrive, save_json_to_gdrive

KST = timezone(timedelta(hours=9))

def run_risk_monitor(kis_client, base_url, app_key, secret_key, token, acc_no, app, channel_id, say_func=None):
    print("Log: [Risk Manager] 3중 매도 필터(손절/시간/추적) 점검을 시작합니다.", flush=True)
    
    portfolio = load_json_from_gdrive("paper_portfolio.json")
    if not portfolio:
        print("Log: [Risk Manager] 관리 중인 보유 종목이 없습니다.", flush=True)
        return

    modified = False
    messages = []
    now = datetime.now(KST)

    kis_client.set_token(token)

    for ticker, info in list(portfolio.items()):
        qty = info.get("quantity", 0)
        if qty <= 0:
            continue

        name = info.get("name", ticker)
        avg_price = info.get("avg_price", 0)
        
        # 매수 시점 및 최고가 기록 추적 (기존 데이터 호환)
        buy_timestamp = info.get("buy_timestamp", now.timestamp())
        buy_date = datetime.fromtimestamp(buy_timestamp, tz=KST)
        highest_price = info.get("highest_price", avg_price)

        # 현재가 조회
        val = kis_client.get_valuation_data(ticker)
        current_price = int(val.get("current_price", 0))

        if current_price <= 0:
            continue

        # 고점 갱신
        if current_price > highest_price:
            highest_price = current_price
            info["highest_price"] = highest_price
            modified = True

        # 지표 연산
        profit_rate = ((current_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
        peak_profit_rate = ((highest_price - avg_price) / avg_price) * 100 if avg_price > 0 else 0
        drawdown_from_peak = ((current_price - highest_price) / highest_price) * 100 if highest_price > 0 else 0
        days_held = (now - buy_date).days

        sell_reason = ""

        # 필터 1: 원금 손절매 (-10%)
        if profit_rate <= -10.0:
            sell_reason = f"원금 손절매 (-10% 도달 / 현재수익률 {profit_rate:.2f}%)"
            
        # 필터 2: 시간 손절매 (8주=56일 경과 및 유의미한 수익 5% 미만 시)
        elif days_held >= 56 and profit_rate < 5.0:
            sell_reason = f"시간 손절매 (8주 경과 수익 부진 / 현재수익률 {profit_rate:.2f}%)"

        # 필터 3: 추적 손절매 (최고 20% 이상 수익 후, 고점 대비 5% 하락 시 익절)
        elif peak_profit_rate >= 20.0 and drawdown_from_peak <= -5.0:
            sell_reason = f"추적 손절매 (고점 대비 5% 하락 익절 / 현재수익률 {profit_rate:.2f}%)"

        # 매도 트리거 발생 시 처리 (모의 장부 수량 0으로 변경)
        if sell_reason:
            msg = f"*[리스크 관리 데몬 작동]*\n- 종목: {name} ({ticker})\n- 사유: {sell_reason}\n- 매도 단가: {current_price:,}원"
            messages.append(msg)
            print(f"Log: [Risk Manager] [Sell] {name} - {sell_reason}", flush=True)
            info["quantity"] = 0
            modified = True

    if modified:
        save_json_to_gdrive(portfolio, "paper_portfolio.json")

    # 슬랙 알림 전송
    if messages and channel_id and app:
        for m in messages:
            app.client.chat_postMessage(channel=channel_id, text=m)
    
    if say_func and messages:
        say_func("\n".join(messages))

    print("Log: [Risk Manager] 점검이 완료되었습니다.", flush=True)
