# -*- coding: utf-8 -*-
import os
import time
import schedule
from dotenv import load_dotenv
from slack_sdk import WebClient

# Import Custom Modules
import market_hours
import token_manager
import account_info

# Load environment variables from .env
load_dotenv()

# --- Configuration ---
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"

SLACK_TOKEN = os.getenv("SLACK_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")

# Initialize Slack Client
SLACK = WebClient(token=SLACK_TOKEN)

def daily_job():
    """
    Main task executed every minute.
    1. Token Management
    2. Market Status Check
    3. Portfolio Reporting
    """
    try:
        # Step 1: Manage Token
        token = token_manager.get_access_token(APP_KEY, SECRET_KEY)
        if not token:
            print("Log: [Critical] Failed to retrieve access token.")
            return

        # Step 2: Check Market Status
        if market_hours.is_market_open():
            current_time = market_hours.get_current_kst_time()
            print(f"Log: [OPEN] Market is active. ({current_time})")
            
            # Fetch Detailed Balance
            balance = account_info.get_detailed_balance(URL, APP_KEY, SECRET_KEY, token, ACC_NO)
            
            if balance:
                # Constructing Slack Report (Using standard text to avoid encoding issues)
                report = [
                    "*Daily Portfolio Report*",
                    f"Time: {current_time}",
                    "--------------------------------",
                    f"Cash: {int(float(balance['cash'])):,} KRW",
                    f"Total Eval: {int(float(balance['total_eval'])):,} KRW",
                    f"Total P/L: {int(float(balance['total_pnl'])):,} KRW ({balance['total_ratio']}%)",
                    "--------------------------------",
                    "Holdings:"
                ]
                
                if not balance['items']:
                    report.append("- No stocks in portfolio.")
                else:
                    for item in balance['items']:
                        pnl_val = float(item['pnl_amount'])
                        status = "[UP]" if pnl_val > 0 else "[DOWN]"
                        item_str = f"{status} {item['name']} ({item['symbol']})\n" \
                                   f"  Qty: {item['qty']} | P/L: {int(pnl_val):,} ({item['pnl_ratio']}%)"
                        report.append(item_str)
                
                # Send to Slack
                SLACK.chat_postMessage(channel=SLACK_CHANNEL, text="\n".join(report))
                print("Log: Detailed report sent to Slack.")
            else:
                print("Log: [Error] Failed to fetch balance data.")
        
        else:
            # Market Closed Log
            current_time = market_hours.get_current_kst_time()
            print(f"Log: [CLOSED] Market is currently closed. ({current_time})")

    except Exception as e:
        print(f"Log: [Exception] Error in daily_job: {str(e)}")

# --- Scheduler Setup ---
schedule.every(1).minutes.do(daily_job)

if __name__ == "__main__":
    startup_msg = "[System] Modularized Stock Bot Started on Lightsail."
    print(f"Log: {startup_msg}")
    
    try:
        SLACK.chat_postMessage(channel=SLACK_CHANNEL, text=startup_msg)
    except Exception as e:
        print(f"Log: Slack startup notification failed - {e}")

    # Initial execution
    daily_job()
    
    while True:
        schedule.run_pending()
        time.sleep(1)
