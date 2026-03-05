# -*- coding: utf-8 -*-
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

    def get_current_price(self, ticker):
        """
        Fetch the current price of a specific stock
        """
        path = "/uapi/domestic-stock/v1/quotations/inquire-price"
        url = f"{self.base_url}{path}"
        
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "tr_id": "FHKST01010100" # TR ID for Current Price
        }
        
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": ticker
        }


        res = requests.get(url, headers=headers, params=params)
        return res.json()
