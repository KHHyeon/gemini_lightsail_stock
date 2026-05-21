# -*- coding: utf-8 -*-
"""
KIS Open API 호출 클라이언트.

v3.3 리팩토링으로 ``_call_kis`` 단일 호출 헬퍼를 도입하여 헤더 구성·요청
실행·예외/타임아웃 처리·응답 파싱 패턴의 중복을 제거한다.

본 모듈은 두 가지 진입점을 제공한다.

1. 모듈 함수 ``_call_kis(base_url, app_key, secret_key, token, tr_id,
   endpoint, params, ...)`` — 외부 함수형 호출자(account_info.py /
   chart.py / screener.py 등)가 KISClient 인스턴스 없이도 동일 헬퍼를
   재사용할 수 있도록 한 ``thin`` 함수.

2. 인스턴스 메서드 ``KISClient._call_kis(tr_id, endpoint, params, ...)`` —
   self.base_url / self.app_key / self.secret_key / self.token 을 자동
   주입하여 KISClient 내부 메서드들이 단일 호출 패턴을 공유하도록 한다.
"""
import os

import requests
from dotenv import load_dotenv

load_dotenv()

KIS_BASE_URL = "https://openapi.koreainvestment.com:9443"
DEFAULT_TIMEOUT_SEC = 5


def _build_kis_headers(app_key, secret_key, token, tr_id, custtype=None):
    """KIS REST API 표준 헤더 구성."""
    header_map = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": tr_id,
    }
    if custtype:
        header_map["custtype"] = custtype
    return header_map


def _call_kis(
    base_url,
    app_key,
    secret_key,
    token,
    tr_id,
    endpoint,
    params=None,
    *,
    method="GET",
    custtype=None,
    timeout=DEFAULT_TIMEOUT_SEC,
    json_body=None,
):
    """KIS API 단일 호출 헬퍼 (모듈 함수형).

    Args:
        base_url: KIS API 베이스 URL (예: 'https://openapi.koreainvestment.com:9443').
        app_key / secret_key / token: KIS 인증 키 3종.
        tr_id: 거래 ID (예: 'TTTC8908R').
        endpoint: '/uapi/...' 형태의 경로.
        params: GET query string dict (생략 가능).
        method: 'GET' 또는 'POST'.
        custtype: 'P' 등 추가 헤더 (조건검색에 사용).
        timeout: 요청 타임아웃 초.
        json_body: POST 시 body. method='POST' 일 때만 사용.

    Returns:
        dict|None: 응답 JSON. 네트워크/HTTP 오류 시 None.
    """
    headers = _build_kis_headers(app_key, secret_key, token, tr_id, custtype=custtype)
    url = f"{base_url}{endpoint}"
    try:
        if method.upper() == "POST":
            res = requests.post(url, headers=headers, json=json_body, timeout=timeout)
        else:
            res = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
        if res.status_code != 200:
            return None
        try:
            return res.json()
        except ValueError:
            return None
    except requests.RequestException:
        return None


class KISClient:
    """KIS REST API 호출 클라이언트 (단일 인스턴스 권장)."""

    def __init__(self):
        self.base_url = KIS_BASE_URL
        self.app_key = os.getenv("APP_KEY")
        self.secret_key = os.getenv("SECRET_KEY")
        self.acc_no = os.getenv("ACCOUNT_NO")
        raw_id = os.getenv("HTS_ID") or ""
        self.hts_id = raw_id.replace('"', "").replace("'", "").strip()
        self.token = None

    def set_token(self, token):
        self.token = token

    def _call_kis(self, tr_id, endpoint, params=None, *, method="GET",
                  custtype=None, timeout=DEFAULT_TIMEOUT_SEC, json_body=None):
        """인스턴스 컨텍스트(base_url/keys/token)를 자동 주입하는 헬퍼."""
        return _call_kis(
            self.base_url,
            self.app_key,
            self.secret_key,
            self.token,
            tr_id,
            endpoint,
            params=params,
            method=method,
            custtype=custtype,
            timeout=timeout,
            json_body=json_body,
        )

    def get_psbl_cash(self):
        if not self.token:
            return 0
        params = {
            "CANO": self.acc_no[:8],
            "ACNT_PRDT_CD": self.acc_no[8:],
            "PDNO": "",
            "ORD_UNPR": "",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        data = self._call_kis(
            "TTTC8908R", "/uapi/domestic-stock/v1/trading/inquire-psbl-order", params
        )
        if not data:
            return 0
        return int((data.get("output") or {}).get("ord_psbl_cash", "0") or 0)

    def get_real_holding_qty(self, ticker, test_mode="LIVE"):
        if not self.acc_no or not self.token:
            return 0, 0.0
        tr_id = "TTTC8434R" if test_mode == "LIVE" else "VTTC8434R"
        params = {
            "CANO": self.acc_no[:8],
            "ACNT_PRDT_CD": self.acc_no[8:],
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._call_kis(
            tr_id, "/uapi/domestic-stock/v1/trading/inquire-balance", params
        )
        if not data:
            return 0, 0.0
        for item in data.get("output1", []) or []:
            if item.get("pdno") == ticker:
                qty = int(item.get("hldg_qty", "0") or 0)
                avg_price = float(item.get("pchs_avg_pric", "0") or 0.0)
                return qty, avg_price
        return 0, 0.0

    def get_condition_list(self):
        data = self._call_kis(
            "HHKST03900300",
            "/uapi/domestic-stock/v1/quotations/psearch-title",
            {"user_id": self.hts_id},
            custtype="P",
            timeout=10,
        )
        if not data:
            return []
        if data.get("rt_cd") not in ["0", "1"]:
            return []
        return data.get("output2") or data.get("output") or []

    def find_condition_seq(self, target_name):
        condition_list = self.get_condition_list()
        if not condition_list:
            return None
        target_norm = target_name.strip().replace(" ", "")
        for item in condition_list:
            nm = item.get("condition_nm") or item.get("psearch_nm")
            seq = item.get("seq")
            if nm and nm.strip().replace(" ", "") == target_norm:
                return seq
        return None

    def get_condition_stocks(self, seq):
        if not seq:
            return []
        data = self._call_kis(
            "HHKST03900400",
            "/uapi/domestic-stock/v1/quotations/psearch-result",
            {"user_id": self.hts_id, "seq": seq},
            custtype="P",
            timeout=15,
        )
        if not data:
            return []
        return [item.get("code") for item in data.get("output2", []) or []]

    def get_valuation_data(self, ticker):
        data = self._call_kis(
            "FHKST01010100",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
        )
        if not data:
            return None
        output = data.get("output") or {}
        per_value = float(output.get("per", 0) or 0.0)
        return {
            "current_price": int(output.get("stck_prpr", 0) or 0),
            "pbr": float(output.get("pbr", 0) or 0.0),
            "per": per_value,
            "roe": (
                round((float(output.get("pbr", 0)) / per_value) * 100, 2)
                if per_value != 0
                else 0
            ),
        }

    def get_valuation_metrics(self, ticker):
        """FHKST03010300: 가치지표 (EPS / BPS / PER / PBR / ROE / 배당수익률)."""
        data = self._call_kis(
            "FHKST03010300",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
        )
        if not data:
            return None
        output = data.get("output") or {}
        return {
            "eps": float(output.get("eps", 0) or 0.0),
            "bps": float(output.get("bps", 0) or 0.0),
            "per": float(output.get("per", 0) or 0.0),
            "pbr": float(output.get("pbr", 0) or 0.0),
            "roe": float(output.get("roe", 0) or 0.0),
            "dvd_yld": float(output.get("dvd_yld", 0) or 0.0),
        }

    def get_growth_metrics(self, ticker):
        """FHKST03010400: 성장성 지표 (매출액증가율, 영업이익증가율)."""
        data = self._call_kis(
            "FHKST03010400",
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
        )
        if not data:
            return None
        output = data.get("output") or {}
        return {
            "sales_growth": float(output.get("gr_sales", 0) or 0.0),
            "op_growth": float(output.get("gr_op_profit", 0) or 0.0),
        }
