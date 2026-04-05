# -*- coding: utf-8 -*-
# File: ~/my_bot/kis_api.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

class KISClient:
    def __init__(self):
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.app_key = os.getenv("APP_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.acc_no = os.getenv("ACCOUNT_NO")
        self.token = None

    def set_token(self, token):
        self.token = token

    def get_valuation_data(self, ticker):
        """특정 종목의 PBR, PER, ROE 등 투자지표와 현재가를 가져옵니다."""
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.token}",
            "appkey": self.app_key, "appsecret": self.secret_key, "tr_id": "FHKST01010100"
        }
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get('rt_cd') == '0':
                output = data.get('output', {})
                pbr = float(output.get('pbr', 0))
                per = float(output.get('per', 0))
                roe = round((pbr / per) * 100, 2) if per != 0 else 0
                return {
                    "pbr": pbr, "per": per, "roe": roe, 
                    "current_price": output.get('stck_prpr')
                }
            return None
        except Exception as e:
            print(f"Log: [KIS API] 지표 수집 중 오류: {e}")
            return None

    def get_psbl_cash(self):
        """매수 가능한 현금 잔고를 조회합니다."""
        if not self.acc_no or not self.token: return 0
        path = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.token}",
            "appkey": self.app_key, "appsecret": self.secret_key, "tr_id": "TTTC8908R"
        }
        params = {
            "CANO": self.acc_no[:8], "ACNT_PRDT_CD": self.acc_no[8:], "PDNO": "",
            "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        try:
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                return int(res.json().get("output", {}).get("ord_psbl_cash", "0"))
        except: pass
        return 0

    def get_real_holding_qty(self, ticker, test_mode="LIVE"):
        """특정 종목의 계좌 내 실제 보유 수량과 평단가를 조회합니다."""
        if not self.acc_no or not self.token: return 0, 0.0
        tr_id = "TTTC8434R" if test_mode == "LIVE" else "VTTC8434R"
        path = "/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.token}",
            "appkey": self.app_key, "appsecret": self.secret_key, "tr_id": tr_id
        }
        params = {
            "CANO": self.acc_no[:8], "ACNT_PRDT_CD": self.acc_no[8:], "AFHR_FLPR_YN": "N",
            "OFL_YN": "", "INQR_DVSN": "01", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                for item in res.json().get("output1", []):
                    if item.get("pdno") == ticker:
                        qty = int(item.get("hldg_qty", "0"))
                        avg_price = float(item.get("pchs_avg_pric", "0"))
                        return qty, avg_price
        except: pass
        return 0, 0.0
