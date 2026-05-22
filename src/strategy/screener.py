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


def score_single_ticker(ticker, name, base_url, app_key, secret_key, token,
                        target_theme=None):
    """단일 종목 펀더멘털 스코어링 헬퍼 (임계값 필터 미적용).

    `run_unified_screener` 의 종목별 산출 로직을 단일 함수로 분리한 것이며,
    `!ai매수` / `!수동등록` / `!발굴` 세 진입점 모두 본 함수를 사용한다.
    데이터 부재(주가/거래대금 미달) 시 ``None`` 반환.

    Args:
        ticker: 종목코드(6자리).
        name: 종목명(금융업 분류 키워드 판별용).
        base_url/app_key/secret_key/token: KIS 인증.
        target_theme: 외부에서 지정한 테마명. ``None`` 이면 산출 결과(금융/성장) 사용.

    Returns:
        dict | None: ``score``, ``score_details``, ``target_theme``,
        ``current_price``, ``pbr``, ``per``, ``roe``, ``is_financial``.
    """
    if not ticker:
        return None

    is_financial = _is_financial_name(name)

    val = get_basic_valuation(base_url, app_key, secret_key, token, ticker)
    if val["current_price"] <= 0:
        return None

    if val["tr_amount"] < 1000000000:
        print(f"Log: [Liquidity Filter] {name} 탈락 (거래대금 부족)")
        return None

    score = 0
    details = []

    chart_60d = chart_data.get_daily_ohlcv(
        base_url, app_key, secret_key, token, ticker, count=60
    )
    if chart_60d and len(chart_60d) >= 60:
        current_close = chart_60d[0]['close']
        ma60 = sum(day['close'] for day in chart_60d) / 60
        if current_close >= ma60:
            score += 20
            details.append("차트 정배열(+20)")

    frgn, orgn = get_smart_money_accumulation(
        base_url, app_key, secret_key, token, ticker
    )
    if frgn > 0 or orgn > 0:
        score += 30
        details.append("수급 유입(+30)")

    if is_financial:
        if val["pbr"] > 0 and val["pbr"] <= 1.0:
            score += 20
            details.append("저PBR(+20)")

        roe = val.get("roe", 0.0)
        if roe <= 0:
            roe = round((val["pbr"] / val["per"]) * 100, 2) if val["per"] > 0 else 0
        if roe >= 8.0:
            score += 30
            details.append("ROE 8% 이상(+30)")

        resolved_theme = target_theme or "우량 금융주"
    else:
        sales_growth, op_growth, turnaround = get_kis_growth_metrics(
            base_url, app_key, secret_key, token, ticker
        )
        if sales_growth >= 10.0:
            score += 25
            details.append("매출성장(+25)")
        if op_growth >= 15.0 or turnaround:
            score += 25
            details.append("이익성장/턴어라운드(+25)")

        roe = val.get("roe", 0.0)
        resolved_theme = target_theme or "가치성장 대장주"

    return {
        "score": score,
        "score_details": details,
        "target_theme": resolved_theme,
        "current_price": val["current_price"],
        "pbr": val["pbr"],
        "per": val["per"],
        "roe": roe,
        "is_financial": is_financial,
    }


def run_unified_screener(raw_candidates, base_url, app_key, secret_key, token):
    """다종목 스코어링. 비금융 60점 / 금융 80점 이상만 통과."""
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
        if scored is None:
            continue

        threshold = 80 if scored["is_financial"] else 60
        if scored["score"] < threshold:
            continue

        c.update({
            "current_price": scored["current_price"],
            "pbr": scored["pbr"],
            "per": scored["per"],
            "roe": scored["roe"],
            "score": scored["score"],
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
