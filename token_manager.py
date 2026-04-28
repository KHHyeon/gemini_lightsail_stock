# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime, timedelta
import market_hours

TOKEN_FILE = "token_info.json"

def get_access_token(app_key, secret_key, force=False):
    # 1. 강제 발급(08:00 스케줄러 등)이 아닐 경우, 23시간 이내 파일 캐시 재사용
    if not force and os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                issued_at = datetime.strptime(data['issued_at'], '%Y-%m-%d %H:%M:%S')
                
                # 23시간 이내면 서버 요청 없이 즉시 반환
                if datetime.now() < issued_at + timedelta(hours=23):
                    return data['access_token']
        except Exception as e:
            print(f"Log: [Token Manager] 파일 읽기 오류: {e}")

    # 2. 신규 발급 진행 전, 장이 열리는 날(영업일)인지 점검
    if not market_hours.is_market_open():
        print("Log: [Token Manager] 오늘은 휴장일입니다. 신규 토큰을 발급하지 않습니다.")
        # 테스트 등을 위해 기존 캐시 파일이 있다면 그대로 반환
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r") as f:
                    return json.load(f).get('access_token')
            except: pass
        return None

    # 3. 토큰 신규 발급 (영업일 확인됨)
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
