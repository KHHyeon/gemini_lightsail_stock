# -*- coding: utf-8 -*-
# File: ~/my_bot/token_manager.py
import os
import json
import requests
from datetime import datetime, timedelta

TOKEN_FILE = "token_info.json"

def get_access_token(app_key, secret_key):
    """
    Manages Token Persistence. Returns a valid token.
    """
    # 1. Try to load from local file
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                issued_at = datetime.strptime(data['issued_at'], '%Y-%m-%d %H:%M:%S')
                
                # If valid (within 23 hours), reuse it
                if datetime.now() < issued_at + timedelta(hours=23):
                    return data['access_token']
        except Exception as e:
            print(f"Log: Token file read error - {e}")

    # 2. If no valid token, request new one
    print("Log: Requesting a new Access Token...")
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": secret_key
    }
    
    res = requests.post(url, json=body)
    new_token = res.json().get("access_token")
    
    if new_token:
        # Save to file
        token_info = {
            "access_token": new_token,
            "issued_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_info, f)
        return new_token
    
    return None
