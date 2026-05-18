import time
from datetime import datetime
from src.utils import helpers as market_hours
from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive
from src.execution.order import OrderManager



def run_risk_monitor(kis_client, base_url, app_key, secret_key, token, acc_no, app, channel_id):
    if not market_hours.is_market_open(): return

    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio: return

    from src.data import collector
    macro = collector.get_macro_indicators()
    current_index = macro.get("KOSPI", 0.0)

    order_mgr = OrderManager(base_url, app_key, secret_key, token, acc_no)
    split_orders = load_json_from_gdrive("split_orders.json") or {}
    
    keys_to_delete = []
    messages = []
    portfolio_updated = False
    split_orders_updated = False

    now_dt = datetime.now()

    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0: continue
        
        avg_price = info.get("avg_price", 0)
        mode_type = info.get("mode_type", "PAPER_ONLY") 
        
        val = kis_client.get_valuation_data(ticker)
        if not val: continue
        current_price = int(val.get("current_price", 0))
        if current_price <= 0: continue
        
        # 0. 상대 강도(RS) 계산 및 손절선 결정
        purchase_index = info.get("purchase_index_price", current_index)
        stock_perf = (current_price / avg_price) if avg_price > 0 else 1.0
        index_perf = (current_index / purchase_index) if purchase_index > 0 else 1.0
        rs = stock_perf / index_perf
        
        # 지수보다 강한 종목(RS > 1.0)은 주도주로 판단, 손절선 -17%로 완화
        stop_loss_limit = 0.83 if rs > 1.0 else 0.90
        
        # 0-1. 보유일수 관리 (20일 타임아웃)
        purchase_date_str = info.get("purchase_date", "")
        days_held = 0
        if purchase_date_str:
            try:
                purchase_dt = datetime.strptime(purchase_date_str, "%Y-%m-%d %H:%M:%S")
                days_held = (now_dt - purchase_dt).days
            except: pass
            
        if days_held >= 20 and stock_perf < 1.03: # 20일 지났는데 수익률 3% 미만
             messages.append(f"[타임아웃 알림] {info.get('name')} {days_held}일째 보유 중이나 성과 미흡. 교체 매매를 검토하세요.")

        high_water_mark = info.get("high_water_mark", avg_price)
        if current_price > high_water_mark:
            info["high_water_mark"] = current_price
            high_water_mark = current_price
            portfolio_updated = True
        
        sell_reason = ""
        # 1. 지수 연동형 유연 손절 (-10% or -17%)
        if avg_price > 0 and current_price <= avg_price * stop_loss_limit:
            rs_label = "주도주(RS>1)" if rs > 1.0 else "일반"
            sell_reason = f"방어선 이탈 (손절선 {int((1-stop_loss_limit)*100)}% 적용 | {rs_label})"
            
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
