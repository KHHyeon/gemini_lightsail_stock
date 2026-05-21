# -*- coding: utf-8 -*-
"""실시간 리스크 모니터 (30분 주기 손절·추적 익절 방어막).

v3.3 리팩토링:
- 인자 8개(`kis_client, base_url, app_key, secret_key, token, acc_no, app,
  channel_id`)를 ``kis_client + config dict + send_slack`` 3-인자로 축소.
- 슬랙 송출을 ``orchestrator.send_slack`` 단일 게이트웨이로 통합 (이전의
  ``app.client.chat_postMessage`` 직접 호출 제거).
"""
import time

from src.core import token_manager
from src.execution.order import OrderManager, OrderRequest
from src.utils import helpers as market_hours
from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive
from src.utils.timekit import now_kst


def run_risk_monitor(kis_client, config, send_slack):
    """포트폴리오 손절·추적 익절 검사.

    Args:
        kis_client: KISClient (token 은 본 함수가 새로 발급).
        config: 전역 설정 dict. 필요 키: APP_KEY / SECRET_KEY / URL / ACC_NO.
        send_slack: text 1-인자 callable. 일반적으로 ``orchestrator.send_slack``.
    """
    if not market_hours.is_market_open():
        return

    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    if not portfolio:
        return

    from src.data import collector
    macro = collector.get_macro_indicators()
    current_index = macro.get("KOSPI", 0.0)

    app_key = config["APP_KEY"]
    secret_key = config["SECRET_KEY"]
    base_url = config["URL"]
    acc_no = config["ACC_NO"]
    token = token_manager.get_access_token(app_key, secret_key)
    kis_client.set_token(token)

    order_mgr = OrderManager(base_url, app_key, secret_key, token, acc_no)
    split_orders = load_json_from_gdrive("split_orders.json") or {}

    keys_to_delete_list = []
    message_list = []
    portfolio_updated = False
    split_orders_updated = False

    now_dt = now_kst().replace(tzinfo=None)

    for ticker, info in portfolio.items():
        qty = info.get("quantity", 0)
        if qty <= 0:
            continue

        avg_price = info.get("avg_price", 0)
        mode_type = info.get("mode_type", "PAPER_ONLY")

        val = kis_client.get_valuation_data(ticker)
        if not val:
            continue
        current_price = int(val.get("current_price", 0))
        if current_price <= 0:
            continue

        purchase_index = info.get("purchase_index_price", current_index)
        stock_perf = (current_price / avg_price) if avg_price > 0 else 1.0
        index_perf = (current_index / purchase_index) if purchase_index > 0 else 1.0
        rs_value = stock_perf / index_perf

        stop_loss_limit = 0.83 if rs_value > 1.0 else 0.90

        purchase_date_str = info.get("purchase_date", "")
        days_held = 0
        if purchase_date_str:
            try:
                from datetime import datetime

                purchase_dt = datetime.strptime(purchase_date_str, "%Y-%m-%d %H:%M:%S")
                days_held = (now_dt - purchase_dt).days
            except (TypeError, ValueError):
                pass

        if days_held >= 20 and stock_perf < 1.03:
            message_list.append(
                f"[타임아웃 알림] {info.get('name')} {days_held}일째 보유 중이나 성과 미흡. "
                "교체 매매를 검토하세요."
            )

        high_water_mark = info.get("high_water_mark", avg_price)
        if current_price > high_water_mark:
            info["high_water_mark"] = current_price
            high_water_mark = current_price
            portfolio_updated = True

        sell_reason = ""
        if avg_price > 0 and current_price <= avg_price * stop_loss_limit:
            rs_label = "주도주(RS>1)" if rs_value > 1.0 else "일반"
            sell_reason = (
                f"방어선 이탈 (손절선 {int((1 - stop_loss_limit) * 100)}% 적용 | {rs_label})"
            )
        elif (
            avg_price > 0
            and high_water_mark > avg_price
            and current_price <= high_water_mark * 0.90
        ):
            sell_reason = "최고점 대비 하락선 이탈 (추적 매도 -10%)"

        if sell_reason:
            res = order_mgr.submit(OrderRequest(
                ticker=ticker, name=info.get("name", ticker),
                quantity=qty, current_price=current_price, side="sell",
                reason=sell_reason, mode_type=mode_type,
            ))
            message_list.append(res["msg"])
            keys_to_delete_list.append(ticker)

            split_keys_to_delete = [
                oid for oid, s_info in split_orders.items()
                if s_info["ticker"] == ticker
            ]
            for k in split_keys_to_delete:
                del split_orders[k]
                split_orders_updated = True
            if split_keys_to_delete:
                message_list.append(
                    f"  └── [연쇄 조치] {info.get('name', ticker)} 장중 방어막 가동으로 "
                    "대기 분할매수 파기."
                )

        time.sleep(0.2)

    for k in keys_to_delete_list:
        if k in portfolio:
            del portfolio[k]

    if keys_to_delete_list or portfolio_updated:
        save_json_to_gdrive(portfolio, "paper_portfolio.json")
    if split_orders_updated:
        save_json_to_gdrive(split_orders, "split_orders.json")

    if message_list and callable(send_slack):
        send_slack("[Risk Manager 실시간 방어막 가동]\n" + "\n\n".join(message_list))
