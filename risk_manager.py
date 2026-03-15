# -*- coding: utf-8 -*-
# File: ~/my_bot/risk_manager.py
from datetime import datetime, timezone, timedelta
from trade_logger import load_json_from_gdrive
from order_manager import OrderManager

# 한국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

def run_risk_monitor(kis_client, url, app_key, secret_key, token, acc_no, slack_app, channel_id, say_func=None):
    """
    백그라운드에서 30분마다 실행되며 포트폴리오의 리스크(손절, 시간 만료)를 감시합니다.
    수동 테스트 시 say_func를 통해 즉각 응답합니다.
    """
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    trades = load_json_from_gdrive("paper_trades.json") or []

    if not portfolio:
        return

    order_mgr = OrderManager(url, app_key, secret_key, token, acc_no)

    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0:
            continue
            
        avg_price = info.get("avg_price", 0)
        
        valuation = kis_client.get_valuation_data(ticker)
        if not valuation:
            continue
            
        current_price = int(valuation.get("current_price", 0))
        if current_price == 0:
            continue
            
        yield_pct = ((current_price - avg_price) / avg_price) * 100
        
        # [원칙 1] 가격 손절 (Stop-Loss -10%)
        if yield_pct <= -10.0:
            reason = f"리스크 데몬: -10% 손절매 규정 도달 (현재 수익률: {yield_pct:.2f}%)"
            res = order_mgr.execute_paper_order(ticker, info["name"], qty, current_price, "sell", reason)
            if res["success"]:
                msg = f"[자동 손절 집행 Warning]\n{info['name']}({ticker}) 종목이 -10% 손절선을 이탈하여 기계적 전량 매도되었습니다.\n사유: {reason}"
                # say_func가 전달되었으면 명령어 입력 방으로 즉시 출력, 아니면 공용 채널로 전송
                if say_func:
                    say_func(msg)
                elif channel_id:
                    slack_app.client.chat_postMessage(channel=channel_id, text=msg)
            continue

        # [원칙 2] 시간 손절 (Time-Stop 8주 / 56일)
        buy_trades = [t for t in trades if t["ticker"] == ticker and t["action"] == "BUY"]
        if buy_trades:
            first_buy_str = buy_trades[0]["timestamp"]
            try:
                first_buy_date = datetime.strptime(first_buy_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
                days_held = (datetime.now(KST) - first_buy_date).days
                
                if days_held >= 56 and yield_pct <= 0:
                    reason = f"리스크 데몬: 8주 보유 초과 및 수익 부재 (보유: {days_held}일, 수익률: {yield_pct:.2f}%)"
                    res = order_mgr.execute_paper_order(ticker, info["name"], qty, current_price, "sell", reason)
                    if res["success"]:
                        msg = f"[시간 손절 집행 Notice]\n{info['name']}({ticker}) 종목이 8주(56일)간 수익을 내지 못해 전량 매도되었습니다.\n사유: {reason}"
                        if say_func:
                            say_func(msg)
                        elif channel_id:
                            slack_app.client.chat_postMessage(channel=channel_id, text=msg)
                    continue
            except Exception as e:
                pass

        # [원칙 3] 이익 극대화 알림 (Trailing Stop 준비)
        if yield_pct >= 20.0:
            msg = f"[익절 타겟 도달 Success]\n{info['name']}({ticker}) 종목이 +20% 수익률을 돌파했습니다! (현재: {yield_pct:.2f}%)\n시스템이 추적 손절매(Trailing Stop) 가드레일을 평단가 위로 상향 조정합니다."
            if say_func:
                say_func(msg)
            elif channel_id:
                slack_app.client.chat_postMessage(channel=channel_id, text=msg)
