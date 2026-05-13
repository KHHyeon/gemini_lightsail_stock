# -*- coding: utf-8 -*-
# File: ~/my_bot/slack_notifier.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

def send_slack_alert(message):
    """시스템의 치명적인 에러를 슬랙 채널로 긴급 송출합니다."""
    token = os.getenv("SLACK_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")
    
    if not token or not channel:
        print(f"Log: [Alert Failed] Slack 환경변수 누락. Msg: {message}")
        return
        
    url = "https://slack.com/api/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": channel,
        "text": f"*[System Emergency Alert]*\n{message}"
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=5)
    except Exception as e:
        print(f"Log: [Slack Alert Error] 알림 송출 실패: {str(e)}")
