# -*- coding: utf-8 -*-
import os, requests, json
from dotenv import load_dotenv

load_dotenv()

class KISClient:
    def __init__(self):
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.app_key = os.getenv("APP_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.acc_no = os.getenv("ACCOUNT_NO")
        raw_id = os.getenv("HTS_ID") or ""
        self.hts_id = raw_id.replace('"', '').replace("'", "").strip()
        self.token = None

    def set_token(self, token):
        self.token = token

    def get_psbl_cash(self):
        path = "/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "TTTC8908R"
        }
        params = {
            "CANO": self.acc_no[:8],
            "ACNT_PRDT_CD": self.acc_no[8:],
            "PDNO": "", "ORD_UNPR": "", "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        try:
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                return int(res.json().get("output", {}).get("ord_psbl_cash", "0"))
        except: pass
        return 0

    def get_real_holding_qty(self, ticker, test_mode="LIVE"):
        """실계좌 또는 모의계좌의 실제 보유 수량과 평단가를 조회합니다."""
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

    def get_condition_list(self):
        path = "/uapi/domestic-stock/v1/quotations/psearch-title"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "HHKST03900300",
            "custtype": "P"
        }
        params = { "user_id": self.hts_id }
        try:
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") not in ["0", "1"]: return []
            return data.get("output2") or data.get("output") or []
        except: return []

    def find_condition_seq(self, target_name):
        full_list = self.get_condition_list()
        if not full_list: return None
        for item in full_list:
            nm = item.get("condition_nm") or item.get("psearch_nm")
            seq = item.get("seq")
            if nm and nm.strip().replace(" ", "") == target_name.strip().replace(" ", ""):
                return seq
        return None

    def get_condition_stocks(self, seq):
        if not seq: return []
        path = "/uapi/domestic-stock/v1/quotations/psearch-result"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "HHKST03900400",
            "custtype": "P"
        }
        params = { "user_id": self.hts_id, "seq": seq }
        try:
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=15)
            return [item.get("code") for item in res.json().get("output2", [])]
        except: return []

    def get_valuation_data(self, ticker):
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "FHKST01010100"
        }
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
        try:
            res = requests.get(f"{self.base_url}{path}", headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json().get('output', {})
                return {
                    "current_price": int(data.get('stck_prpr', 0) or 0),
                    "pbr": float(data.get('pbr', 0) or 0.0),
                    "per": float(data.get('per', 0) or 0.0),
                    "roe": round((float(data.get('pbr', 0))/float(data.get('per', 1)))*100, 2) if float(data.get('per', 0)) != 0 else 0
                }
        except: pass
        return None
