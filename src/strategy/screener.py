# -*- coding: utf-8 -*-
import time
import requests
from bs4 import BeautifulSoup
import io
from contextlib import redirect_stdout

from src.core.kis_api import _call_kis
from src.data import chart as chart_data



def get_naver_dividend(ticker):
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            dvr_tag = soup.find('em', id='_dvr')
            if dvr_tag: return float(dvr_tag.text.strip().replace(',', ''))
    except: pass
    return 0.0

def calculate_rsi(ohlcv, period=14):
    if len(ohlcv) < period + 1: return 50.0
    deltas = []
    for i in range(1, len(ohlcv)):
        deltas.append(ohlcv[i]['close'] - ohlcv[i-1]['close'])
    
    up = [d if d > 0 else 0 for d in deltas]
    down = [abs(d) if d < 0 else 0 for d in deltas]
    
    avg_up = sum(up[-period:]) / period
    avg_down = sum(down[-period:]) / period
    
    if avg_down == 0: return 100.0
    rs = avg_up / avg_down
    return 100.0 - (100.0 / (1+rs))

def calculate_envelope_bottom(ohlcv, period=20, spread=15.0):
    if len(ohlcv) < period: return 0.0
    closes = [x['close'] for x in ohlcv[-period:]]
    sma = sum(closes) / period
    return sma * (1 - (spread / 100.0))

def check_contrarian_signal(ohlcv):
    """
    [낙폭과대_발굴] 2차 검증: 하락 진정 변곡점 확인 (도지 캔들 또는 거래량 급감)
    HTS 1차 필터링(RSI, 이격도 등)을 통과한 종목에 대해 정밀 타점을 잡음
    """
    if not ohlcv or len(ohlcv) < 5: return False, ""
    
    curr = ohlcv[-1]
    prev = ohlcv[-2]
    
    # 1. 도지 캔들 판정 (몸통이 전체 변동폭의 1.5% 이내)
    body_size = abs(curr['open'] - curr['close'])
    total_size = curr['high'] - curr['low'] if curr['high'] != curr['low'] else 1
    is_doji = (body_size / total_size) <= 0.015
    
    # 2. 거래량 급감 판정 (최근 5일 평균 대비 50% 이하 또는 전일 대비 50% 이하)
    avg_vol_5d = sum([x['volume'] for x in ohlcv[-6:-1]]) / 5
    is_vol_drop = (curr['volume'] < avg_vol_5d * 0.5) or (curr['volume'] < prev['volume'] * 0.5)
    
    if is_doji or is_vol_drop:
        reason = "도지캔들" if is_doji else "거래량급감"
        if is_doji and is_vol_drop: reason = "도지+거래량급감"
        return True, f"변곡점확인({reason})"
        
    return False, ""

def validate_contrarian_track(val, ohlcv, mkt_cap):
    """
    [낙폭과대_발굴] 2차 검증 로직
    HTS에서 1차 필터링된 종목을 대상으로 파이썬에서만 가능한 정밀 분석 수행
    """
    # 1. 기술적 변곡점 정밀 확인 (도지/거래량)
    is_signal, signal_desc = check_contrarian_signal(ohlcv)
    if not is_signal: return False, []
    
    details = [f"낙폭과대우량주(시총:{mkt_cap/1e8:.0f}억)", signal_desc]
    
    # 2. 실시간 뉴스/공시 리스크 마이닝 (2차 검증의 핵심)
    # 이 부분은 ai_logic.py 또는 news_crawler.py와 연동하여 호출됨
    
    return True, details


def validate_growth_track(val, ohlcv, growth_metrics):
    """ [기대주_발굴] 2차 검증 로직 """
    if not ohlcv or len(ohlcv) < 60: return False, []
    details = []
    
    # 재무: ROE 10%+, 영업이익증가율 10%+, PER 20배 이하
    sales_g, op_g, _ = growth_metrics
    if val['roe'] < 10.0 or op_g < 10.0 or val['per'] > 20.0 or val['per'] <= 0:
        return False, []
    
    # 기술적: 정배열 (1 > 20 > 60), 20일 이격도 95~105%
    curr_close = ohlcv[-1]['close']
    ma20 = sum([x['close'] for x in ohlcv[-20:]]) / 20
    ma60 = sum([x['close'] for x in ohlcv[-60:]]) / 60
    
    is_bullish = curr_close > ma20 > ma60
    disparity_20 = (curr_close / ma20) * 100
    is_pullback = 95.0 <= disparity_20 <= 105.0
    
    if is_bullish and is_pullback:
        details.append(f"성장성(ROE:{val['roe']:.1f}/OPG:{op_g:.1f})")
        details.append(f"정배열눌림목(이격:{disparity_20:.1f}%)")
        return True, details
    return False, []

def validate_value_track(val, ohlcv):
    """ [배당주_발굴] 2차 검증 로직 """
    if not ohlcv or len(ohlcv) < 120: return False, []
    details = []
    
    # 가치: 시가배당률 3.5%+, PER 13배 이하, PBR 1배 이하
    if val['dvd_yld'] < 3.5 or val['per'] > 13.0 or val['pbr'] > 1.0 or val['per'] <= 0:
        return False, []
    
    # 기술적: 120일 이격도 95~105% (장기 바닥권)
    curr_close = ohlcv[-1]['close']
    ma120 = sum([x['close'] for x in ohlcv[-120:]]) / 120
    disparity_120 = (curr_close / ma120) * 100
    
    if 95.0 <= disparity_120 <= 105.0:
        details.append(f"고배당가치(배당:{val['dvd_yld']:.1f}/PBR:{val['pbr']:.2f})")
        details.append(f"장기바닥권(이격120:{disparity_120:.1f}%)")
        return True, details
    return False, []

def get_market_cap(base_url, app_key, secret_key, token, ticker):
    """ 시가총액 조회 (FHKST01010100 활용, 단위: 원). """
    data = _call_kis(
        base_url,
        app_key,
        secret_key,
        token,
        tr_id="FHKST01010100",
        endpoint="/uapi/domestic-stock/v1/quotations/inquire-price",
        params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
    )
    if not data:
        return 0
    try:
        return int((data.get("output") or {}).get("hts_avls", "0") or 0) * 1000000
    except (TypeError, ValueError):
        return 0

def run_3track_screener(track_name, raw_candidates, base_url, app_key, secret_key, token):
    """ HTS 트랙별 특화 스크리너 """
    if not raw_candidates: return []
    final_list = []
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        stock_name = c.get("name", ticker)
        
        # 1. 공통 데이터 수집
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        if val["current_price"] <= 0: continue
        
        # 유동성 체크 (5일 평균 거래대금 10억~30억 이상)
        min_tr_amount = 3000000000 if track_name in ["기대주_발굴", "낙폭과대_발굴"] else 1000000000
        if val["tr_amount"] < min_tr_amount: continue
        
        ohlcv = chart_data.get_daily_ohlcv(base_url, app_key, secret_key, token, ticker, count=130)
        if not ohlcv: continue
        
        passed = False
        details = []
        
        # 2. 트랙별 개별 검증
        if track_name == "기대주_발굴":
            growth_metrics = get_kis_growth_metrics(base_url, app_key, secret_key, token, ticker)
            passed, details = validate_growth_track(val, ohlcv, growth_metrics)
        
        elif track_name == "배당주_발굴":
            passed, details = validate_value_track(val, ohlcv)
            
        elif track_name == "낙폭과대_발굴":
            mkt_cap = get_market_cap(base_url, app_key, secret_key, token, ticker)
            passed, details = validate_contrarian_track(val, ohlcv, mkt_cap)


        
        if passed:
            # 수급 데이터 추가 (최종 점수 반영용)
            frgn, orgn = get_smart_money_accumulation(base_url, app_key, secret_key, token, ticker)
            if frgn > 0 or orgn > 0: details.append("수급유입 확인")
            
            c.update({
                "current_price": val["current_price"], "pbr": val["pbr"], "per": val["per"], 
                "roe": val["roe"], "dvd_yld": val["dvd_yld"],
                "score_details": details, "track": track_name
            })
            final_list.append(c)
            
    return final_list


def get_basic_valuation(base_url, app_key, secret_key, token, ticker):
    """주가/PER/PBR/거래대금 + ROE/배당수익률 (FHKST01010100 + FHKST03010300)."""
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
    endpoint = "/uapi/domestic-stock/v1/quotations/inquire-price"

    res_val = {
        "current_price": 0,
        "pbr": 0.0,
        "per": 0.0,
        "roe": 0.0,
        "tr_amount": 0,
        "dvd_yld": 0.0,
    }

    time.sleep(0.1)
    data1 = _call_kis(
        base_url, app_key, secret_key, token,
        tr_id="FHKST01010100", endpoint=endpoint, params=params,
    )
    if data1:
        output = data1.get("output") or {}
        try:
            res_val["current_price"] = int(output.get("stck_prpr", "0") or 0)
            res_val["pbr"] = float(output.get("pbr", "0") or 0.0)
            res_val["per"] = float(output.get("per", "0") or 0.0)
            res_val["tr_amount"] = int(output.get("acml_tr_pbmn", "0") or 0)
        except (TypeError, ValueError):
            pass

    time.sleep(0.1)
    data2 = _call_kis(
        base_url, app_key, secret_key, token,
        tr_id="FHKST03010300", endpoint=endpoint, params=params,
    )
    if data2:
        output = data2.get("output") or {}
        try:
            res_val["roe"] = float(output.get("roe", "0") or 0.0)
            res_val["dvd_yld"] = float(output.get("dvd_yld", "0") or 0.0)
        except (TypeError, ValueError):
            pass

    return res_val

def get_smart_money_accumulation(base_url, app_key, secret_key, token, ticker):
    """외국인/기관 일별 순매수 누적 합 (FHKST01010900)."""
    time.sleep(0.2)
    data = _call_kis(
        base_url, app_key, secret_key, token,
        tr_id="FHKST01010900",
        endpoint="/uapi/domestic-stock/v1/quotations/inquire-investor",
        params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
    )
    if not data:
        return 0, 0
    frgn_net = 0
    orgn_net = 0
    for day in data.get("output2", []) or []:
        try:
            frgn_net += int(day.get("frgn_ntby_qty", "0") or 0)
            orgn_net += int(day.get("orgn_ntby_qty", "0") or 0)
        except (TypeError, ValueError):
            continue
    return frgn_net, orgn_net


def get_kis_growth_metrics(base_url, app_key, secret_key, token, ticker):
    """성장성 지표 (FHKST03010400). Returns: (sales_growth, op_growth, turnaround)."""
    time.sleep(0.1)
    data = _call_kis(
        base_url, app_key, secret_key, token,
        tr_id="FHKST03010400",
        endpoint="/uapi/domestic-stock/v1/quotations/inquire-price",
        params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
    )
    if not data:
        return 0.0, 0.0, False
    output = data.get("output") or {}
    try:
        sales_growth = float(output.get("gr_sales", "0") or 0.0)
        op_growth = float(output.get("gr_op_profit", "0") or 0.0)
    except (TypeError, ValueError):
        return 0.0, 0.0, False
    return sales_growth, op_growth, (op_growth > 100)

def run_condition_screener(kis_client, target_condition_name):
    print(f"Log: [Screener] '{target_condition_name}' 탐색 시작...")
    seq = kis_client.find_condition_seq(target_condition_name)
    if not seq:
        print(f"Log: [Error] '{target_condition_name}' 조건식을 HTS 목록에서 찾을 수 없습니다.")
        return []
        
    tickers = kis_client.get_condition_stocks(seq)
    if not tickers:
        print(f"Log: [Info] '{target_condition_name}' 조건에 맞는 종목이 현재 시장에 없습니다.")
        return []

    results = []
    for ticker in tickers:
        results.append({"ticker": ticker, "name": ticker})
    print(f"Log: [Screener] 조건식 확인 완료. 종목 추출 중...")
    return results

_FINANCIAL_NAME_KEYWORD_LIST = ['지주', '은행', '증권', '보험', '금융']


def _is_financial_name(stock_name):
    return any(kw in (stock_name or "") for kw in _FINANCIAL_NAME_KEYWORD_LIST)


# =====================================================================
# 5축 GARP 펀더멘털 채점 (Greenblatt Magic Formula + Peter Lynch GARP +
# Piotroski F-Score 의 핵심 인자 결합)
# Doc/features/ai_investment_decision/03_ai_investment_decision_state_logic.md §2 참조.
# =====================================================================

# 유동성 보류 컷. 기존 10억 하드컷 → 1억으로 완화 + 미달 시 분석보류 라벨 처리.
# (10억 컷은 `run_3track_screener` 의 자동발굴 트랙에서 별도 유지.)
SCORE_LIQUIDITY_HOLD_KRW = 100_000_000


def _score_value(per, pbr, is_financial):
    """Value 축 (최대 20점). Magic Formula 의 Earnings Yield 대용.

    PER ≤ 0 (적자) 인 비금융주는 PBR 만 평가 + 적자 패널티 명시.
    금융주는 PER 의미가 약해 ROE 가산점으로 대체 → 본 함수에서는 PBR 만 평가.
    """
    pts = 0
    details = []

    if pbr and pbr > 0:
        if pbr <= 0.7:
            pts += 10
            details.append(f"저PBR({pbr:.2f}/+10)")
        elif pbr <= 1.0:
            pts += 7
            details.append(f"PBR({pbr:.2f}/+7)")
        elif pbr <= 1.5:
            pts += 4
            details.append(f"PBR({pbr:.2f}/+4)")
        elif pbr <= 2.5:
            pts += 1
            details.append(f"PBR({pbr:.2f}/+1)")

    if not is_financial:
        if per and per > 0:
            if per <= 8.0:
                pts += 10
                details.append(f"저PER({per:.1f}/+10)")
            elif per <= 12.0:
                pts += 7
                details.append(f"PER({per:.1f}/+7)")
            elif per <= 18.0:
                pts += 4
                details.append(f"PER({per:.1f}/+4)")
            elif per <= 25.0:
                pts += 1
                details.append(f"PER({per:.1f}/+1)")
        elif per is not None and per <= 0:
            details.append("적자(PER<=0)")

    return min(pts, 20), details


def _score_quality(roe, is_financial):
    """Quality 축 (최대 20점, 금융주 30점). ROE 절대값 단계 가점."""
    pts = 0
    details = []
    if roe is None:
        return 0, details

    if roe >= 20.0:
        pts = 20
        tag = "+20"
    elif roe >= 15.0:
        pts = 15
        tag = "+15"
    elif roe >= 10.0:
        pts = 10
        tag = "+10"
    elif roe >= 8.0:
        pts = 6
        tag = "+6"
    elif roe >= 5.0:
        pts = 3
        tag = "+3"
    elif roe >= 0.0:
        pts = 1
        tag = "+1"
    else:
        return 0, ["적자 ROE"]

    details.append(f"ROE({roe:.1f}%/{tag})")

    if is_financial and roe >= 8.0:
        pts += 10
        details.append("금융주 ROE 보너스(+10)")

    return pts, details


def _score_growth(sales_growth, op_growth, turnaround):
    """Growth 축 (최대 20점). Lynch GARP."""
    pts = 0
    details = []

    if sales_growth is not None:
        if sales_growth >= 10.0:
            pts += 5
            details.append(f"매출성장({sales_growth:.1f}%/+5)")
        elif sales_growth >= 5.0:
            pts += 3
            details.append(f"매출성장({sales_growth:.1f}%/+3)")
        elif sales_growth >= 0.0:
            pts += 1
            details.append(f"매출성장({sales_growth:.1f}%/+1)")

    if op_growth is not None:
        if op_growth >= 20.0:
            pts += 10
            details.append(f"영업이익성장({op_growth:.1f}%/+10)")
        elif op_growth >= 10.0:
            pts += 6
            details.append(f"영업이익성장({op_growth:.1f}%/+6)")
        elif op_growth >= 0.0:
            pts += 3
            details.append(f"영업이익성장({op_growth:.1f}%/+3)")

    if turnaround:
        pts += 5
        details.append("턴어라운드(+5)")

    return min(pts, 20), details


def _score_momentum(chart_ohlcv):
    """Momentum 축 (최대 20점). 60일선/20일선 정배열."""
    if not chart_ohlcv or len(chart_ohlcv) < 60:
        return 0, []

    closes = [day['close'] for day in chart_ohlcv]
    current = closes[0]
    ma20 = sum(closes[:20]) / 20
    ma60 = sum(closes[:60]) / 60

    pts = 0
    details = []
    if current >= ma60:
        pts += 10
        details.append("종가>=60일선(+10)")
    if current >= ma20:
        pts += 5
        details.append("종가>=20일선(+5)")
    if ma20 > ma60:
        pts += 5
        details.append("정배열 20>60(+5)")
    return min(pts, 20), details


def _score_smart_money(frgn_net, orgn_net):
    """Smart Money 축 (최대 20점). 외국인·기관 순매수 부호."""
    has_frgn = frgn_net is not None and frgn_net > 0
    has_orgn = orgn_net is not None and orgn_net > 0
    if has_frgn and has_orgn:
        return 20, ["외/기 동반 순매수(+20)"]
    if has_frgn or has_orgn:
        side = "외국인" if has_frgn else "기관"
        return 10, [f"{side} 순매수(+10)"]
    return 0, ["수급 약세"]


def score_single_ticker(ticker, name, base_url, app_key, secret_key, token,
                        target_theme=None):
    """단일 종목 펀더멘털 스코어링 (5축 GARP, 임계값 필터 미적용).

    `!ai매수` / `!수동등록` / `!발굴` 세 진입점 모두 본 함수를 사용한다.
    데이터 부족(주가 미상 / 유동성 미달) 시 ``score=None`` 으로 분석보류 라벨로
    유도한다 (기존처럼 0점/매수반대로 표시하지 않는다).

    Args:
        ticker: 종목코드(6자리).
        name: 종목명(금융업 분류 키워드 판별용).
        base_url/app_key/secret_key/token: KIS 인증.
        target_theme: 외부에서 지정한 테마명. ``None`` 이면 산출 결과(금융/성장) 사용.

    Returns:
        dict:
            - score: int | None (None 이면 분석보류)
            - score_breakdown: dict | None
            - score_details: list[str]
            - unscorable_reason: str | None
            - target_theme: str
            - current_price/pbr/per/roe: 원본 수치
            - is_financial: bool
    """
    is_financial = _is_financial_name(name)
    resolved_theme = target_theme or ("우량 금융주" if is_financial else "가치성장 대장주")

    base = {
        "score": None,
        "score_breakdown": None,
        "score_details": [],
        "unscorable_reason": None,
        "target_theme": resolved_theme,
        "current_price": 0,
        "pbr": 0.0,
        "per": 0.0,
        "roe": 0.0,
        "is_financial": is_financial,
    }

    if not ticker:
        base["unscorable_reason"] = "ticker_missing"
        return base

    val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
    base["current_price"] = val.get("current_price", 0)
    base["pbr"] = val.get("pbr", 0.0)
    base["per"] = val.get("per", 0.0)
    base["roe"] = val.get("roe", 0.0)

    if val["current_price"] <= 0:
        base["unscorable_reason"] = "price_unavailable"
        return base

    if val["tr_amount"] < SCORE_LIQUIDITY_HOLD_KRW:
        print(
            f"Log: [Liquidity Hold] {name}({ticker}) 거래대금 "
            f"{val['tr_amount']:,} < {SCORE_LIQUIDITY_HOLD_KRW:,} → 분석보류"
        )
        base["unscorable_reason"] = "liquidity_too_low"
        return base

    roe = val.get("roe", 0.0) or 0.0
    if roe <= 0 and val["per"] > 0 and val["pbr"] > 0:
        # KIS ROE 누락 보정: PBR/PER 근사값.
        roe = round((val["pbr"] / val["per"]) * 100, 2)
    base["roe"] = roe

    sales_growth, op_growth, turnaround = (0.0, 0.0, False)
    if not is_financial:
        sales_growth, op_growth, turnaround = get_kis_growth_metrics(
            base_url, app_key, secret_key, token, ticker
        )

    chart_60d = chart_data.get_daily_ohlcv(
        base_url, app_key, secret_key, token, ticker, count=60
    )

    frgn_net, orgn_net = get_smart_money_accumulation(
        base_url, app_key, secret_key, token, ticker
    )

    val_pts, val_details = _score_value(val["per"], val["pbr"], is_financial)
    qual_pts, qual_details = _score_quality(roe, is_financial)
    growth_pts, growth_details = _score_growth(sales_growth, op_growth, turnaround)
    mom_pts, mom_details = _score_momentum(chart_60d)
    sm_pts, sm_details = _score_smart_money(frgn_net, orgn_net)

    # 금융주는 Growth 데이터가 빈 경우가 많으므로 Quality 보너스로 보전.
    # (Quality 가 이미 +10 보너스를 가져가지만, Growth 0점이 의견에 미치는
    #  과소평가를 막기 위해 final 합산 시 max 100 클램프.)
    score = min(val_pts + qual_pts + growth_pts + mom_pts + sm_pts, 100)

    details = []
    details.extend(val_details)
    details.extend(qual_details)
    details.extend(growth_details)
    details.extend(mom_details)
    details.extend(sm_details)

    base["score"] = score
    base["score_breakdown"] = {
        "value": val_pts,
        "quality": qual_pts,
        "growth": growth_pts,
        "momentum": mom_pts,
        "smart_money": sm_pts,
    }
    base["score_details"] = details
    return base


def run_unified_screener(raw_candidates, base_url, app_key, secret_key, token):
    """다종목 스코어링. 비금융 50점 / 금융 65점 이상만 통과.

    v1.3: 임계값을 5축 채점 평균 분포에 맞게 비금융 60→50, 금융 80→65 로 조정.
    분석보류(score=None) 종목은 자동 제외된다.
    """
    if not raw_candidates:
        return []
    final_list = []

    for c in raw_candidates:
        ticker = c.get("ticker")
        stock_name = c.get("name", ticker)
        if not ticker:
            continue

        scored = score_single_ticker(
            ticker, stock_name, base_url, app_key, secret_key, token,
            target_theme=c.get("target_theme"),
        )
        if scored is None or scored.get("score") is None:
            continue

        threshold = 65 if scored["is_financial"] else 50
        if scored["score"] < threshold:
            continue

        c.update({
            "current_price": scored["current_price"],
            "pbr": scored["pbr"],
            "per": scored["per"],
            "roe": scored["roe"],
            "score": scored["score"],
            "score_breakdown": scored["score_breakdown"],
            "score_details": scored["score_details"],
            "target_theme": scored["target_theme"],
        })
        final_list.append(c)

    final_list.sort(key=lambda x: x.get("score", 0), reverse=True)
    return final_list

def run_screener(raw_candidates, base_url, app_key, secret_key, token, benchmark_rate):
    if not raw_candidates: return []
    final_list = []
    min_dividend = round(benchmark_rate * 0.8, 2)
    
    for c in raw_candidates:
        ticker = c.get("ticker")
        val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
        if val["current_price"] <= 0 or val["tr_amount"] < 1000000000: continue
        
        div_yield = get_naver_dividend(ticker)
        if div_yield <= 0: div_yield = val.get("dvd_yld", 0.0) # 네이버 실패 시 KIS 데이터 활용
        
        if div_yield < min_dividend: continue
        
        roe = val.get("roe", 0.0)
        if roe <= 0: roe = round((val["pbr"] / val["per"]) * 100, 2) if val["per"] > 0 else 0
        
        if val["pbr"] > 0 and val["per"] > 0:
            if val["pbr"] >= 2.0 or roe <= 0: continue
            
            c.update({
                "current_price": val["current_price"], 
                "pbr": val["pbr"], 
                "per": val["per"], 
                "roe": roe, 
                "div_yield": div_yield
            })
            final_list.append(c)
            
    final_list.sort(key=lambda x: x.get("div_yield", 0), reverse=True)
    print(f"Log: [Screener] 총 {len(final_list)}개 종목 발굴 완료.")
    return final_list
