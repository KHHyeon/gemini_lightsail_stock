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
        self.token = None

    def set_token(self, token):
        self.token = token

    def get_valuation_data(self, ticker):
        """
        특정 종목의 PBR, PER, ROE 등의 투자지표를 가져옵니다.
        """
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{self.base_url}{path}"
        
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "FHKST01010100"
        }
        
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": ticker
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            
            if data.get('rt_cd') == '0':
                output = data.get('output', {})
                pbr = float(output.get('pbr', 0))
                per = float(output.get('per', 0))
                
                # ROE 계산 공식: (PBR / PER) * 100
                roe = round((pbr / per) * 100, 2) if per != 0 else 0
                
                return {
                    "pbr": pbr,
                    "per": per,
                    "roe": roe,
                    "current_price": output.get('stck_prpr')
                }
            return None
        except Exception as e:
            print(f"Log: [KIS API] 지표 수집 중 오류: {e}")
            return None
