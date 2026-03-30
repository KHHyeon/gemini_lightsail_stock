# -*- coding: utf-8 -*-
# File: ~/my_bot/order_manager.py
import requests
import json
import os
from trade_logger import record_trade

class OrderManager:
    def __init__(self, base_url, app_key, secret_key, token, acc_no):
        self.base_url = base_url
        self.app_key = app_key
        self.secret_key = secret_key
        self.token = token
        self.acc_no = acc_no 

    def execute_order(self, ticker, name, quantity, current_price, side, reason):
        """
        .env의 TRADING_MODE 값에 따라 모의투자(PAPER) 또는 실전매매(LIVE)를 수행합니다.
        side: "buy" or "sell"
        """
        mode = os.getenv("TRADING_MODE", "PAPER").upper()
        action = "BUY" if side == "buy" else "SELL"
        
        if mode == "LIVE":
            # [실전 매매 모드] KIS API 실제 시장가 주문 전송
            path = "/uapi/domestic-stock/v1/trading/order-cash"
            tr_id = "TTTC0802U" if side == "buy" else "TTTC0801U"
            headers = {
                "Content-Type": "application/json", "authorization": f"Bearer {self.token}",
                "appkey": self.app_key, "appsecret": self.secret_key, "tr_id": tr_id, "custtype": "P"
            }
            payload = {
                "CANO": self.acc_no[:8], "ACNT_PRDT_CD": self.acc_no[8:],
                "PDNO": ticker, "ORD_DVSN": "01", # 01: 시장가
                "ORD_QTY": str(int(quantity)), "ORD_UNPR": "0"
            }
            try:
                res = requests.post(f"{self.base_url}{path}", headers=headers, json=payload)
                data = res.json()
                if res.status_code == 200 and data.get('rt_cd') == '0':
                    # 실제 체결 성공 시 가상 장부에도 동기화 기록
                    record_trade(ticker, name, action, current_price, quantity, f"[LIVE] {reason}")
                    return {"success": True, "msg": f"*[실전 {action} 체결]* {name}({ticker}) {quantity}주 시장가 주문 접수 완료\n- 사유: {reason}"}
                else:
                    error_msg = data.get('msg1', '알 수 없는 API 거부')
                    return {"success": False, "msg": f"[실전 주문 실패] {error_msg}"}
            except Exception as e:
                return {"success": False, "msg": f"[실전 통신 에러] {str(e)}"}
        else:
            # [모의 투자 모드] 가상 장부에만 기록
            record_trade(ticker, name, action, current_price, quantity, f"[PAPER] {reason}")
            return {"success": True, "msg": f"[모의 {action}] {name}({ticker}) {quantity}주 @ {current_price}원\n- 사유: {reason}"}

    def simulate_split_buy(self, ticker, name, total_budget, current_price, reason):
        """
        AI가 매수를 승인했을 때, 10일 분할 매수 예산을 쪼개어 검증합니다.
        """
        if current_price <= 0: return {"success": False, "msg": "주가 데이터 오류"}
        
        daily_budget = total_budget / 10
        quantity = int(daily_budget // current_price)
        
        if quantity < 1:
            return {"success": False, "msg": "할당 금액이 1주 가격보다 적어 분할 매수가 불가능합니다."}
            
        return {"success": True, "msg": f"{name} 분할 매수 승인 완료. (1회차 {quantity}주 모의/실전 대기)"}
