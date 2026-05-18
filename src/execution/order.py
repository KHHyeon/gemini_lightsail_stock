# -*- coding: utf-8 -*-
# File: ~/my_bot/order_manager.py
import requests
import json
import os
from datetime import datetime
from src.data import chart
from src.utils.logger import record_trade



class OrderManager:
    def __init__(self, base_url, app_key, secret_key, token, acc_no):
        self.base_url = base_url
        self.app_key = app_key
        self.secret_key = secret_key
        self.token = token
        self.acc_no = acc_no 

    def execute_order(self, ticker, name, quantity, current_price, side, reason, mode_type="NORMAL", strategy_tag="UNKNOWN"):
        # [수정됨] 수동 등록 종목의 독립성 보장 로직
        if mode_type == "PAPER_ONLY":
            mode = "PAPER"
        elif mode_type == "LIVE_MANUAL":
            mode = "LIVE" # 전체 환경변수와 무관하게 무조건 실전 매도 집행
        else:
            # AI 자동 발굴 종목은 글로벌 환경변수를 따름
            env_var = "TRADING_MODE_SMALL" if mode_type == "SMALL" else "TRADING_MODE_NORMAL"
            mode = os.getenv(env_var, "PAPER").upper()
            
        action = "BUY" if side == "buy" else "SELL"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if mode == "LIVE":
            path = "/uapi/domestic-stock/v1/trading/order-cash"
            tr_id = "TTTC0802U" if side == "buy" else "TTTC0801U"
            headers = {
                "Content-Type": "application/json", "authorization": f"Bearer {self.token}",
                "appkey": self.app_key, "appsecret": self.secret_key, "tr_id": tr_id, "custtype": "P"
            }
            payload = {
                "CANO": self.acc_no[:8], "ACNT_PRDT_CD": self.acc_no[8:],
                "PDNO": ticker, "ORD_DVSN": "01", 
                "ORD_QTY": str(int(quantity)), "ORD_UNPR": "0"
            }
            try:
                res = requests.post(f"{self.base_url}{path}", headers=headers, json=payload)
                data = res.json()
                if res.status_code == 200 and data.get('rt_cd') == '0':
                    record_trade(ticker, name, action, current_price, quantity, f"[LIVE-{mode_type}] {reason}", strategy_tag=strategy_tag, purchase_date=now_str)
                    return {"success": True, "msg": f"[실전 {action} 체결] {name}({ticker}) {quantity}주 시장가 주문 접수 완료\n- 사유: {reason}\n- 태그: {strategy_tag}"}
                else:
                    error_msg = data.get('msg1', '알 수 없는 API 거부')
                    return {"success": False, "msg": f"[실전 주문 실패] {error_msg}"}
            except Exception as e:
                return {"success": False, "msg": f"[실전 통신 에러] {str(e)}"}
        else:
            record_trade(ticker, name, action, current_price, quantity, f"[PAPER-{mode_type}] {reason}", strategy_tag=strategy_tag, purchase_date=now_str)
            return {"success": True, "msg": f"[모의 {action}] {name}({ticker}) {quantity}주 @ {current_price}원\n- 사유: {reason}\n- 태그: {strategy_tag}"}


    def simulate_split_buy(self, ticker, name, total_budget, current_price, reason):
        if current_price <= 0: return {"success": False, "msg": "주가 데이터 오류"}
        
        daily_budget = total_budget / 10
        adjusted = False
        
        if daily_budget < current_price:
            daily_budget = current_price
            total_budget = daily_budget * 10
            adjusted = True
            
        qty = int(daily_budget // current_price)
        msg = f"{name} 분할 매수 승인. (1회차 {qty}주 대기)"
        
        if adjusted:
            msg += f"\n[예산 자동 보정] 입력하신 예산이 적어, 최소 1주 매수를 위해 총 예산이 {int(total_budget):,}원으로 상향 조정되었습니다."
            
        return {"success": True, "msg": msg, "daily_budget": daily_budget}
