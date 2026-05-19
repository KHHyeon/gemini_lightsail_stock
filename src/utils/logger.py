# -*- coding: utf-8 -*-
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def _root_path():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _local_filepath(filename):
    return os.path.join(_root_path(), filename)


def _load_local(filename):
    filepath = _local_filepath(filename)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_local(data, filename):
    filepath = _local_filepath(filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def _use_drive_storage():
    try:
        from src.memory import drive_client

        return drive_client.is_drive_enabled() and drive_client.is_ready()
    except Exception:
        return False


def load_json_from_gdrive(filename):
    if _use_drive_storage():
        try:
            from src.memory import drive_client

            data = drive_client.read_app_json(filename)
            if data is not None:
                return data
        except Exception as e:
            print(f"Log: [Drive Read Fallback] {filename}: {e}")
    return _load_local(filename)


def save_json_to_gdrive(data, filename):
    if _use_drive_storage():
        try:
            from src.memory import drive_client

            drive_client.write_app_json(filename, data)
            return
        except Exception as e:
            print(f"Log: [Drive Write Fallback] {filename}: {e}")
    _save_local(data, filename)


def record_trade(ticker, name, action, price, quantity, reason, strategy_tag="UNKNOWN", purchase_date=None):
    trades = load_json_from_gdrive("paper_trades.json") or []
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}

    mode_type = "PAPER_ONLY"
    if "SMALL" in reason:
        mode_type = "SMALL"
    elif "NORMAL" in reason:
        mode_type = "NORMAL"

    now_kst = datetime.now(KST)
    if not purchase_date:
        purchase_date = now_kst.strftime("%Y-%m-%d %H:%M:%S")

    trade_record = {
        "timestamp": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": ticker,
        "name": name,
        "action": action,
        "price": price,
        "quantity": quantity,
        "reason": reason,
        "mode_type": mode_type,
        "strategy_tag": strategy_tag,
    }
    trades.append(trade_record)
    save_json_to_gdrive(trades, "paper_trades.json")

    if ticker not in portfolio:
        from src.data import collector

        macro = collector.get_macro_indicators()
        index_price = macro.get("KOSPI", 0.0)

        portfolio[ticker] = {
            "name": name,
            "quantity": 0,
            "avg_price": 0,
            "high_water_mark": 0,
            "mode_type": mode_type,
            "reason": reason,
            "purchase_date": purchase_date,
            "strategy_tag": strategy_tag,
            "purchase_index_price": index_price,
        }

    if action.upper() == "BUY":
        curr_qty = portfolio[ticker]["quantity"]
        curr_avg = portfolio[ticker].get("avg_price", 0)

        if curr_qty == 0:
            portfolio[ticker]["purchase_date"] = purchase_date

        total_value = (curr_qty * curr_avg) + (quantity * price)
        new_qty = curr_qty + quantity
        portfolio[ticker]["avg_price"] = total_value / new_qty if new_qty > 0 else 0
        portfolio[ticker]["quantity"] = new_qty
        portfolio[ticker]["high_water_mark"] = max(
            portfolio[ticker].get("high_water_mark", price), price
        )
        portfolio[ticker]["mode_type"] = mode_type
        portfolio[ticker]["reason"] = reason
        portfolio[ticker]["strategy_tag"] = strategy_tag
    elif action.upper() == "SELL":
        curr_qty = portfolio[ticker]["quantity"]
        new_qty = max(0, curr_qty - quantity)
        portfolio[ticker]["quantity"] = new_qty
        if new_qty == 0:
            portfolio[ticker]["avg_price"] = 0
            portfolio[ticker]["high_water_mark"] = 0

    save_json_to_gdrive(portfolio, "paper_portfolio.json")
