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


def compute_daily_ma20(daily_ohlcv_list):
    """일봉 리스트에서 20일 이동평균(종가) 산출."""
    if not daily_ohlcv_list or len(daily_ohlcv_list) < 20:
        return None
    closes = [float(it.get("close", 0) or 0) for it in daily_ohlcv_list[-20:]]
    if any(c <= 0 for c in closes):
        return None
    return sum(closes) / 20.0


def get_intraday_minute_ohlcv(base_url, app_key, secret_key, token, ticker):
    """KIS 당일 분봉(1분) OHLCV 조회.

    TR: FHKST03010200 / inquire-time-itemchartprice

    Returns:
        list[dict]|None: 과거->현재 순. 키: time(HHMMSS), open, high, low, close, volume, tr_amount.
    """
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": ticker,
        "fid_input_hour_1": "",
        "fid_pw_data_incu_yn": "Y",
        "fid_etc_cls_code": "",
    }
    data = _call_kis(
        base_url,
        app_key,
        secret_key,
        token,
        tr_id="FHKST03010200",
        endpoint="/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
        params=params,
        custtype="P",
        timeout=10,
    )
    if not data or data.get("rt_cd") != "0":
        msg = (data or {}).get("msg1", "no response")
        print(f"Log: [Chart] {ticker} 분봉 API 오류: {msg}")
        return None

    raw_list = data.get("output2") or []
    refined_list = []
    prev_acml_tr = None
    for row in reversed(raw_list):
        try:
            close = int(row.get("stck_prpr") or row.get("stck_clpr") or 0)
            volume = int(row.get("cntg_vol") or 0)
            acml_tr = int(float(row.get("acml_tr_pbmn") or 0))
            if acml_tr > 0 and prev_acml_tr is not None and acml_tr >= prev_acml_tr:
                tr_amount = acml_tr - prev_acml_tr
            else:
                tr_amount = int(close * volume)
            prev_acml_tr = acml_tr if acml_tr > 0 else prev_acml_tr
            refined_list.append({
                "time": str(row.get("stck_cntg_hour") or ""),
                "open": int(row.get("stck_oprc") or close),
                "high": int(row.get("stck_hgpr") or close),
                "low": int(row.get("stck_lwpr") or close),
                "close": close,
                "volume": volume,
                "tr_amount": max(tr_amount, 0),
            })
        except (TypeError, ValueError, KeyError):
            continue
    return refined_list if refined_list else None


def resample_minute_to_3min(minute_ohlcv_list):
    """1분봉 리스트를 3분봉으로 집계 (과거->현재).

    Returns:
        list[dict]: open/high/low/close/volume/tr_amount 포함 3분봉.
    """
    if not minute_ohlcv_list:
        return []

    bucket_map = {}
    order_list = []

    for bar in minute_ohlcv_list:
        time_str = str(bar.get("time") or "")
        digits = "".join(ch for ch in time_str if ch.isdigit())
        if len(digits) < 4:
            continue
        hh = int(digits[:2])
        mm = int(digits[2:4])
        bucket_idx = (hh * 60 + mm) // 3
        key = (hh, bucket_idx)
        if key not in bucket_map:
            bucket_map[key] = {
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": 0,
                "tr_amount": 0,
            }
            order_list.append(key)
        else:
            b = bucket_map[key]
            b["high"] = max(b["high"], bar["high"])
            b["low"] = min(b["low"], bar["low"])
            b["close"] = bar["close"]
        bucket_map[key]["volume"] += int(bar.get("volume", 0) or 0)
        bucket_map[key]["tr_amount"] += int(bar.get("tr_amount", 0) or 0)

    return [bucket_map[k] for k in order_list]


def get_3min_ohlcv_for_ticker(base_url, app_key, secret_key, token, ticker):
    """분봉 조회 후 3분봉으로 변환하는 편의 함수."""
    minute_list = get_intraday_minute_ohlcv(
        base_url, app_key, secret_key, token, ticker,
    )
    if not minute_list:
        return None
    bars_3min = resample_minute_to_3min(minute_list)
    return bars_3min if bars_3min else None

