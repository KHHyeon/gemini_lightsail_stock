# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup

def get_stock_info_naver(ticker):
    """네이버 금융에서 종목명, 배당수익률, ETF 여부를 확인합니다."""
    name, div, is_etf = ticker, 0.0, False
    try:
        url = f"https://finance.naver.com/item/main.naver?code={ticker}"
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 종목명 추출
        title = soup.find('title')
        if title: name = title.text.split(':')[0].strip()
        
        # 배당수익률 추출
        dvr = soup.find('em', id='_dvr')
        if dvr: div = float(dvr.text.strip().replace(',', ''))
        
        # ETF 키워드 판별
        etf_keywords = ['KODEX', 'TIGER', 'KBSTAR', 'ACE', 'ARIRANG', 'HANARO', 'KOSEF', 'SOL', 'TIMEFOLIO', '히어로즈']
        name_upper = name.upper()
        if any(kw in name_upper for kw in etf_keywords) or 'ETN' in name_upper or 'ETF' in name_upper:
            is_etf = True
    except Exception as e:
        print(f"Log: [Stock Info Crawler Error] {ticker}: {e}")
        
    return name, div, is_etf
