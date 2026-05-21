# -*- coding: utf-8 -*-
"""KIS 일봉 OHLCV 조회 - kis_api._call_kis 단일 진입점을 사용."""
from datetime import timedelta

from src.core.kis_api import _call_kis
from src.utils.timekit import now_kst


def get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=30):
    """한국투자증권 API로 최근 N일 일봉 데이터를 받아온다.

    Returns:
        list[dict]|None: 과거->현재 순서. 실패 시 None.
    """
    today_dt = now_kst()
    today_str = today_dt.strftime("%Y%m%d")
    start_str = (today_dt - timedelta(days=100)).strftime("%Y%m%d")

    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": ticker,
        "fid_input_date_1": start_str,
        "fid_input_date_2": today_str,
        "fid_period_div_code": "D",
        "fid_org_adj_prc": "1",
    }

    data = _call_kis(
        base_url,
        app_key,
        secret_key,
        token,
        tr_id="FHKST03010100",
        endpoint="/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
        params=params,
        custtype="P",
        timeout=10,
    )
    if not data:
        return None
    if data.get("rt_cd") != "0":
        print(f"Log: [Chart] {ticker} API 응답 에러: {data.get('msg1')}")
        return None

    raw_charts = data.get("output2") or []
    selected = raw_charts[:count]
    refined_list = []
    for day in selected:
        try:
            refined_list.append(
                {
                    "date": day["stck_bsop_date"],
                    "open": int(day["stck_oprc"]),
                    "high": int(day["stck_hgpr"]),
                    "low": int(day["stck_lwpr"]),
                    "close": int(day["stck_clpr"]),
                    "volume": int(day["acml_vol"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    refined_list.reverse()
    return refined_list
