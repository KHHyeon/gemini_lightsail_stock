# -*- coding: utf-8 -*-
import requests
import json

def get_detailed_balance(base_url, app_key, secret_key, token, acc_no):
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{base_url}{path}"
    tr_id = "VTTC8434R" if "vts" in base_url else "TTTC8434R"

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": tr_id,
        "custtype": "P",
    }

    params = {
        "CANO": acc_no[:8], "ASIT_CD": acc_no[8:],
        "AFHR_FLG": "N", "ODR_MTHD": "02", "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        data = res.json()
        
        # 어떤 결과가 오든 무조건 터미널에 찍습니다.
        print(f"\n[KIS API 응답 원본] {data}", flush=True)

        if data.get('rt_cd') == '0':
            output2 = data.get('output2', [])
            summary = output2[0] if output2 else {}
            return {
                "cash": summary.get('dnca_tot_amt', '0'),
                "total_ratio": summary.get('evlu_pfls_rt', '0.0'),
                "items": data.get('output1', [])
            }
        else:
            print(f"에러 메시지: {data.get('msg1')}", flush=True)
            return None
    except Exception as e:
        print(f"심각한 오류 발생: {str(e)}", flush=True)
        return None
