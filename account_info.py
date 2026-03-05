# -*- coding: utf-8 -*-
import requests

def get_detailed_balance(base_url, app_key, secret_key, token, acc_no):
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{base_url}{path}"
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "TTTC8434R" #
    }
    
    # v1 파라미터 구조 유지
    params = {
        "CANO": acc_no[:8],
        "ACNT_PRDT_CD": acc_no[8:],
        "AFHR_FLG": "N",
        "OFR_FLG": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        data = res.json()
        
        if data.get('rt_cd') == '0':
            # 안전한 데이터 추출
            summary = data.get('output2', [{}])[0]
            return {
                "success": True,
                "cash": summary.get('dnca_tot_amt', '0'),
                "total_eval": summary.get('tot_evlu_amt', '0'),
                "total_pnl": summary.get('evlu_pfls_smtl_amt', '0'),
                "total_ratio": summary.get('evlu_pfls_rt', '0.0'),
                "items": data.get('output1', [])
            }
        else:
            return {
                "success": False, 
                "msg": data.get('msg1'), 
                "rt_cd": data.get('rt_cd')
            }
    except Exception as e:
        return {"success": False, "msg": str(e), "rt_cd": "999"}
