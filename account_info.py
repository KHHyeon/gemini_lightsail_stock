# -*- coding: utf-8 -*-
# File: ~/my_bot/account_info.py
import requests

def get_detailed_balance(base_url, app_key, secret_key, token, acc_no):
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = {
        "Content-Type": "application/json", 
        "authorization": f"Bearer {token}",
        "appkey": app_key, 
        "appsecret": secret_key, 
        "tr_id": "TTTC8434R"
    }
    params = {
        "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[8:],
        "AFHR_FLG": "N", "OFR_FLG": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", 
        "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    try:
        res = requests.get(f"{base_url}{path}", headers=headers, params=params, timeout=10)
        data = res.json()
        
        if data.get('rt_cd') == '0':
            summary = data.get('output2', [{}])[0]
            
            # 1. 원본 데이터 추출
            cash = summary.get('dnca_tot_amt', '0')
            pnl_amt = summary.get('evlu_pfls_smtl_amt', '0') # 평가손익합계금액
            purchase_amt = summary.get('pchs_amt_smtl_amt', '0') # 매입금액합계금액
            
            # 2. 수익률 결정 (데이터에 없으면 직접 계산)
            # 공식: (평가손익 / 매입금액) * 100
            raw_ratio = summary.get('evlu_pfls_rt') 
            
            if raw_ratio is None or float(raw_ratio) == 0:
                try:
                    pnl = float(pnl_amt)
                    purchase = float(purchase_amt)
                    if purchase > 0:
                        calc_ratio = (pnl / purchase) * 100
                        raw_ratio = str(calc_ratio)
                    else:
                        raw_ratio = "0.0"
                except:
                    raw_ratio = "0.0"

            return {
                "success": True, 
                "cash": cash,
                "total_pnl": pnl_amt,
                "total_ratio": raw_ratio,
                "items": data.get('output1', [])
            }
        return {"success": False, "msg": data.get('msg1')}
    except Exception as e: return {"success": False, "msg": str(e)}
