# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime, timedelta

TOKEN_FILE = "token_info.json"

def get_access_token(app_key, secret_key, force=False):
    # 1. 파일 캐시 확인 (강제가 아닐 경우 24시간 만료 여부 체크)
    if not force and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                issued_at = datetime.strptime(data['issued_at'], '%Y-%m-%d %H:%M:%S')
                
                # 24시간 이내면 서버 요청 없이 즉시 반환
                if datetime.now() < issued_at + timedelta(hours=24):
                    return data['access_token']
        except Exception as e:
            print(f"Log: [Token Manager] 파일 읽기 오류: {e}")

    # 2. 토큰 신규 발급 진행 
    # (스케줄러의 강제 발급이거나, 24시간이 초과되어 여기까지 도달했다면 휴일 여부와 무관하게 발급)
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
            # 신규 토큰 저장
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
