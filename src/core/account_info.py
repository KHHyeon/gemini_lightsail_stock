# -*- coding: utf-8 -*-
"""KIS 계좌 잔고 조회 - kis_api._call_kis 단일 진입점을 사용."""
from src.core.kis_api import _call_kis


def get_detailed_balance(base_url, app_key, secret_key, token, acc_no):
    """잔고 상세 조회 (TTTC8434R). 실패 시 {success:False, msg} 반환."""
    params = {
        "CANO": acc_no[:8],
        "ACNT_PRDT_CD": acc_no[8:],
        "AFHR_FLG": "N",
        "OFR_FLG": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    data = _call_kis(
        base_url,
        app_key,
        secret_key,
        token,
        tr_id="TTTC8434R",
        endpoint="/uapi/domestic-stock/v1/trading/inquire-balance",
        params=params,
        timeout=10,
    )
    if not data:
        return {"success": False, "msg": "KIS API 호출 실패"}
    if data.get("rt_cd") != "0":
        return {"success": False, "msg": data.get("msg1")}

    summary = (data.get("output2") or [{}])[0]
    cash = summary.get("dnca_tot_amt", "0")
    pnl_amt = summary.get("evlu_pfls_smtl_amt", "0")
    purchase_amt = summary.get("pchs_amt_smtl_amt", "0")
    raw_ratio = summary.get("evlu_pfls_rt")

    if raw_ratio is None or float(raw_ratio or 0) == 0:
        try:
            pnl = float(pnl_amt)
            purchase = float(purchase_amt)
            raw_ratio = str((pnl / purchase) * 100) if purchase > 0 else "0.0"
        except (TypeError, ValueError):
            raw_ratio = "0.0"

    return {
        "success": True,
        "cash": cash,
        "total_pnl": pnl_amt,
        "total_ratio": raw_ratio,
        "items": data.get("output1", []),
    }
