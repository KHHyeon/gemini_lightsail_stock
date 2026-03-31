# -*- coding: utf-8 -*-
import os
from trade_logger import load_json_from_gdrive, save_json_to_gdrive
from order_manager import OrderManager

def run_risk_monitor(kis_client, base_url, app_key, secret_key, token, acc_no, app, channel_id):
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return

    order_mgr = OrderManager(base_url, app_key, secret_key, token, acc_no)
    keys_to_delete = []
    messages = []

    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0:
            keys_to_delete.append(ticker)
            continue
        
        avg_price = info.get("avg_price", 0)
        # [핵심 보완] 과거 장부라 모드 기록이 없으면 절대 실전으로 팔지 않도록 PAPER_ONLY 선언
        mode_type = info.get("mode_type", "PAPER_ONLY") 
        
        val = kis_client.get_valuation_data(ticker)
        if not val: continue
        current_price = int(val.get("current_price", 0))
        if current_price <= 0: continue
        
        ratio = ((current_price - avg_price) / avg_price) * 100.0
        
        high_water_mark = info.get("high_water_mark", avg_price)
        if current_price > high_water_mark:
            info["high_water_mark"] = current_price
            high_water_mark = current_price
        
        drop_from_high = ((current_price - high_water_mark) / high_water_mark) * 100.0
        
        sell_reason = ""
        if ratio <= -10.0:
            sell_reason = f"하드스탑 손절 (-10% 도달) [수익률: {ratio:.2f}%]"
        elif ratio >= 10.0 and drop_from_high <= -5.0:
            sell_reason = f"추적 익절 (고점 대비 -5% 하락) [수익률: {ratio:.2f}%]"
            
        if sell_reason:
            res = order_mgr.execute_order(ticker, info.get("name", ticker), qty, current_price, "sell", sell_reason, mode_type)
            messages.append(res['msg'])
            keys_to_delete.append(ticker)
            
    for k in keys_to_delete:
        if k in portfolio: del portfolio[k]
        
    if keys_to_delete or messages:
        save_json_to_gdrive(portfolio, "paper_portfolio.json")
        if app and channel_id and messages:
            app.client.chat_postMessage(channel=channel_id, text="*[Risk Manager 발동 (리스크 방어막)]*\n" + "\n".join(messages))
