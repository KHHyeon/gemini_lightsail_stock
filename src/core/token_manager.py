# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime, timedelta

TOKEN_FILE = "token_info.json"

def get_access_token(app_key, secret_key, force=False):
    if not force and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                issued_at = datetime.strptime(data['issued_at'], '%Y-%m-%d %H:%M:%S')
                
                if datetime.now() < issued_at + timedelta(hours=24):
                    return data['access_token']
        except Exception as e:
            print(f"Log: [Token Manager] 파일 읽기 오류: {e}")

    print("Log: KIS 서버에 새 토큰을 요청합니다.")
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": secret_key
    }
    
    try:
        res = requests.post(url, json=body, timeout=10)
        res.raise_for_status()
        token = res.json().get("access_token")
        
        if token:
            token_info = {
                "access_token": token,
                "issued_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            with open(TOKEN_FILE, "w") as f:
                json.dump(token_info, f)
            return token
    except Exception as e:
        print(f"Log: [Token Manager] 발급 실패: {e}")
    
    return None
