# -*- coding: utf-8 -*-
# File: ~/my_bot/trade_logger.py
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

def load_json_from_gdrive(filename):
    # main.py와 같은 루트 디렉토리를 참조하도록 경로 설정
    root_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    filepath = os.path.join(root_path, filename)
    if not os.path.exists(filepath): return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return None

def save_json_to_gdrive(data, filename):
    root_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    filepath = os.path.join(root_path, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def record_trade(ticker, name, action, price, quantity, reason, strategy_tag="UNKNOWN", purchase_date=None):
    trades = load_json_from_gdrive("paper_trades.json") or []
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    
    mode_type = "PAPER_ONLY"
    if "SMALL" in reason: mode_type = "SMALL"
    elif "NORMAL" in reason: mode_type = "NORMAL"
    
    now_kst = datetime.now(KST)
    if not purchase_date:
        purchase_date = now_kst.strftime("%Y-%m-%d %H:%M:%S")
    
    trade_record = {
        "timestamp": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": ticker, "name": name, "action": action,
        "price": price, "quantity": quantity, "reason": reason, 
        "mode_type": mode_type, "strategy_tag": strategy_tag
    }
    trades.append(trade_record)
    save_json_to_gdrive(trades, "paper_trades.json")
    
    if ticker not in portfolio:
        from src.data import collector
        macro = collector.get_macro_indicators()
        index_price = macro.get("KOSPI", 0.0)
        
        portfolio[ticker] = {
            "name": name, "quantity": 0, "avg_price": 0, "high_water_mark": 0, 
            "mode_type": mode_type, "reason": reason,
            "purchase_date": purchase_date,
            "strategy_tag": strategy_tag,
            "purchase_index_price": index_price
        }
        
    if action.upper() == "BUY":
        curr_qty = portfolio[ticker]["quantity"]
        curr_avg = portfolio[ticker].get("avg_price", 0)
        
        # 기존 보유량이 0이었다면 신규 진입이므로 매수일 갱신
        if curr_qty == 0:
            portfolio[ticker]["purchase_date"] = purchase_date
            
        total_value = (curr_qty * curr_avg) + (quantity * price)
        new_qty = curr_qty + quantity
        portfolio[ticker]["avg_price"] = total_value / new_qty if new_qty > 0 else 0
        portfolio[ticker]["quantity"] = new_qty
        portfolio[ticker]["high_water_mark"] = max(portfolio[ticker].get("high_water_mark", price), price)
        portfolio[ticker]["mode_type"] = mode_type 
        portfolio[ticker]["reason"] = reason 
        portfolio[ticker]["strategy_tag"] = strategy_tag
    elif action.upper() == "SELL":
        curr_qty = portfolio[ticker]["quantity"]
        new_qty = max(0, curr_qty - quantity)
        portfolio[ticker]["quantity"] = new_qty
        if new_qty == 0:
            del portfolio[ticker]
            
    save_json_to_gdrive(portfolio, "paper_portfolio.json")


