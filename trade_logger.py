# -*- coding: utf-8 -*-
# File: ~/my_bot/trade_logger.py
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def load_json_from_gdrive(filename):
    if not os.path.exists(filename): return None
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return None

def save_json_to_gdrive(data, filename):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def record_trade(ticker, name, action, price, quantity, reason):
    trades = load_json_from_gdrive("paper_trades.json") or []
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    
    mode_type = "PAPER_ONLY"
    if "SMALL" in reason: mode_type = "SMALL"
    elif "NORMAL" in reason: mode_type = "NORMAL"
    
    trade_record = {
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": ticker, "name": name, "action": action,
        "price": price, "quantity": quantity, "reason": reason, "mode_type": mode_type
    }
    trades.append(trade_record)
    save_json_to_gdrive(trades, "paper_trades.json")
    
    if ticker not in portfolio:
        portfolio[ticker] = {"name": name, "quantity": 0, "avg_price": 0, "high_water_mark": 0, "mode_type": mode_type, "reason": "기록 없음"}
        
    if action.upper() == "BUY":
        curr_qty = portfolio[ticker]["quantity"]
        curr_avg = portfolio[ticker].get("avg_price", 0)
        total_value = (curr_qty * curr_avg) + (quantity * price)
        new_qty = curr_qty + quantity
        portfolio[ticker]["avg_price"] = total_value / new_qty if new_qty > 0 else 0
        portfolio[ticker]["quantity"] = new_qty
        portfolio[ticker]["high_water_mark"] = max(portfolio[ticker].get("high_water_mark", price), price)
        portfolio[ticker]["mode_type"] = mode_type 
        # [수정] 짤림 방지: reason 전체를 저장 (글자 수 제한 제거)
        portfolio[ticker]["reason"] = reason 
    elif action.upper() == "SELL":
        curr_qty = portfolio[ticker]["quantity"]
        new_qty = max(0, curr_qty - quantity)
        portfolio[ticker]["quantity"] = new_qty
        if new_qty == 0:
            del portfolio[ticker]
            
    save_json_to_gdrive(portfolio, "paper_portfolio.json")
