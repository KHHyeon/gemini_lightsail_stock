# -*- coding: utf-8 -*-
import os, time, threading, schedule
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.core import token_manager, kis_api
from src.execution.orchestrator import MarketOrchestrator
from src.execution import risk_monitor as risk_manager
from src.utils import slack_interface

load_dotenv()
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
CHANNEL_ID = os.getenv("SLACK_CHANNEL")
DART_API_KEY = os.getenv("DART_API_KEY")
KST = timezone(timedelta(hours=9))

CONFIG = {
    "APP_KEY": APP_KEY,
    "SECRET_KEY": SECRET_KEY,
    "ACC_NO": ACC_NO,
    "URL": URL,
    "CHANNEL_ID": CHANNEL_ID,
    "DART_API_KEY": DART_API_KEY
}

app = App(token=os.getenv("SLACK_TOKEN"))
kis = kis_api.KISClient()
orchestrator = MarketOrchestrator(kis, app, CONFIG)


def _bootstrap_market_chronicles():
    try:
        from src.memory import drive_client

        drive_client.init_drive_or_pause(notify_fn=orchestrator.send_slack)
    except Exception as e:
        print(f"Log: [Chronicles Bootstrap] {e}", flush=True)


def run_scheduler():
    schedule.every().day.at("08:00").do(orchestrator.issue_daily_token)
    schedule.every().day.at("08:45").do(orchestrator.daily_routine)
    schedule.every().day.at("08:50").do(lambda: orchestrator.auto_stock_discovery(KST))
    schedule.every().day.at("10:00").do(orchestrator.deep_market_routine)
    schedule.every().day.at("11:45").do(orchestrator.noon_routine)
    schedule.every().day.at("14:20").do(orchestrator.alert_manual_stocks)
    schedule.every().day.at("14:30").do(orchestrator.afternoon_routine)
    schedule.every().day.at("15:35").do(orchestrator.chronicle_routine)
    schedule.every().monday.at("09:45").do(orchestrator.weekly_routine)
    
    schedule.every(30).minutes.do(lambda: risk_manager.run_risk_monitor(
        kis, URL, APP_KEY, SECRET_KEY, token_manager.get_access_token(APP_KEY, SECRET_KEY), 
        ACC_NO, app, CHANNEL_ID
    ))
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    print("Log: [System] Active KST", flush=True)
    _bootstrap_market_chronicles()
    slack_interface.register_slack_handlers(app, kis, CONFIG)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()

