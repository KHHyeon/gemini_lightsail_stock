# -*- coding: utf-8 -*-
# File: ~/my_bot/order_manager.py
import requests
import json
from trade_logger import record_trade

class OrderManager:
    def __init__(self, base_url, app_key, secret_key, token, acc_no):
        self.base_url = base_url
        self.app_key = app_key
        self.secret_key = secret_key
        self.token = token
        self.acc_no = acc_no 

    def execute_paper_order(self, ticker, name, quantity, current_price, side, reason):
        """
        [안전 모드] 실제 주문은 넣지 않고, 조건 달성 시 로깅만 수행합니다.
        side: "buy" or "sell"
        """
        # ---------------------------------------------------------
        # [CRITICAL] 실전 매매용 KIS API 코드 (현재 철저히 주석 처리됨)
        # ---------------------------------------------------------
        """
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
        # res = requests.post(f"{self.base_url}{path}", headers=headers, json=payload)
        """
        # ---------------------------------------------------------
        
        # 실제 API 호출 대신, 매매 기록장(Logger)에 기록
        action = "BUY" if side == "buy" else "SELL"
        record = record_trade(ticker, name, action, current_price, quantity, reason)
        
        return {
            "success": True, 
            "msg": f"[Paper {action}] {name}({ticker}) {quantity}주 @ {current_price}원\n사유: {reason}"
        }

    def simulate_split_buy(self, ticker, name, total_budget, current_price, reason):
        """
        투자 원칙 [Section 2]: '10일 분할 매수'의 1회차분을 계산하여 모의 매수합니다.
        """
        if current_price <= 0: return {"success": False, "msg": "가격 오류"}
        
        daily_budget = total_budget / 10
        quantity = int(daily_budget // current_price)
        
        if quantity < 1:
            return {"success": False, "msg": "할당 금액이 1주 가격보다 적습니다."}
            
        return self.execute_paper_order(ticker, name, quantity, current_price, "buy", reason)

    def simulate_stop_loss(self, ticker, name, current_qty, avg_price, current_price, reason):
        """
        투자 원칙 [Section 2]: 손절 규칙 검증 (기본 -10% 등)
        """
        return self.execute_paper_order(ticker, name, current_qty, current_price, "sell", reason)
