# -*- coding: utf-8 -*-
# File: ~/my_bot/account_info.py
import requests

def get_detailed_balance(base_url, app_key, secret_key, token, acc_no):
    """
    Fetches detailed balance including profit/loss for each holding.
    """
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{base_url}{path}"
    
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": secret_key,
        "tr_id": "TTTC8434R"
    }
    
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
        "CTX_AREA_NK100": ""
    }

    res = requests.get(url, headers=headers, params=params)
    data = res.json()
    
    if data.get('rt_cd') == '0':
        # Summary Information
        summary = data['output2'][0]
        total_eval_amt = summary['tot_evlu_amt'] # Total Evaluation Amount
        total_pnl = summary['evlu_pfls_smtl_amt'] # Total Profit/Loss Amount
        pnl_ratio = summary['evlu_pfls_rt'] # Total Profit/Loss Ratio
        cash = summary['dnca_tot_amt'] # Cash available
        
        # Individual Holdings
        holdings = []
        for stock in data['output1']:
            if int(stock['hldg_qty']) > 0: # Only include stocks you actually own
                holdings.append({
                    "name": stock['prdt_name'],
                    "symbol": stock['pdno'],
                    "qty": stock['hldg_qty'],
                    "avg_price": stock['pchs_avg_pric'],
                    "current_price": stock['prpr'],
                    "pnl_amount": stock['evlu_pfls_amt'],
                    "pnl_ratio": stock['evlu_pfls_rt']
                })
                
        return {
            "cash": cash,
            "total_eval": total_eval_amt,
            "total_pnl": total_pnl,
            "total_ratio": pnl_ratio,
            "items": holdings
        }
    else:
        print(f"Error: {data.get('msg1')}")
        return None
