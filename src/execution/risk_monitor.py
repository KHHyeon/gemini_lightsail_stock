# -*- coding: utf-8 -*-
import time
from src.utils import helpers as market_hours
from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive
from src.execution.order import OrderManager


def run_risk_monitor(kis_client, base_url, app_key, secret_key, token, acc_no, app, channel_id):
    if not market_hours.is_market_open(): return

    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return

    order_mgr = OrderManager(base_url, app_key, secret_key, token, acc_no)
    split_orders = load_json_from_gdrive("split_orders.json") or {}
    
    keys_to_delete = []
    messages = []
    portfolio_updated = False
    split_orders_updated = False

    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0: continue
        
        avg_price = info.get("avg_price", 0)
        mode_type = info.get("mode_type", "PAPER_ONLY") 
        
        val = kis_client.get_valuation_data(ticker)
        if not val: continue
        current_price = int(val.get("current_price", 0))
        if current_price <= 0: continue
        
        high_water_mark = info.get("high_water_mark", avg_price)
        if current_price > high_water_mark:
            info["high_water_mark"] = current_price
            high_water_mark = current_price
            portfolio_updated = True
        
        sell_reason = ""
        # 1. 기계적 하드스탑 (-10%)
        if avg_price > 0 and current_price <= avg_price * 0.90:
            sell_reason = "원금 방어선 이탈 (기계적 손절 -10%)"
        # 2. 추적 익절/손절 (고점 대비 -10% 원복)
        elif avg_price > 0 and high_water_mark > avg_price and current_price <= high_water_mark * 0.90:
            sell_reason = "최고점 대비 하락선 이탈 (추적 매도 -10%)"
            
        if sell_reason:
            res = order_mgr.execute_order(ticker, info.get("name", ticker), qty, current_price, "sell", sell_reason, mode_type)
            messages.append(res['msg'])
            keys_to_delete.append(ticker)
            
            split_keys_to_delete = [oid for oid, s_info in split_orders.items() if s_info["ticker"] == ticker]
            for k in split_keys_to_delete:
                del split_orders[k]
                split_orders_updated = True
            if split_keys_to_delete:
                messages.append(f"  └── [연쇄 조치] {info.get('name', ticker)} 장중 방어막 가동으로 대기 분할매수 파기.")
                
        time.sleep(0.2)
            
    for k in keys_to_delete:
        if k in portfolio: del portfolio[k]
        
    if keys_to_delete or portfolio_updated:
        save_json_to_gdrive(portfolio, "paper_portfolio.json")
    if split_orders_updated:
        save_json_to_gdrive(split_orders, "split_orders.json")
        
    if app and channel_id and messages:
        app.client.chat_postMessage(channel=channel_id, text="[Risk Manager 실시간 방어막 가동]\n" + "\n\n".join(messages))
