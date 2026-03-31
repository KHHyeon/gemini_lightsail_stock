# -*- coding: utf-8 -*-
# File: ~/my_bot/theme_crawler.py
import requests
from bs4 import BeautifulSoup
import time

def get_all_naver_themes():
    """네이버 금융의 1~7페이지에 있는 모든 공식 테마(약 250개) 명칭과 링크를 긁어옵니다."""
    url = "https://finance.naver.com/sise/theme.naver"
    themes = {}
    try:
        for page in range(1, 8):
            res = requests.get(f"{url}?page={page}", headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            res.encoding = 'euc-kr'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            for tr in soup.find_all('tr'):
                td = tr.find('td', {'class': 'col_type1'})
                if not td: continue
                a_tag = td.find('a')
                if not a_tag: continue
                
                name = a_tag.text.strip()
                href = a_tag.get('href', '')
                if href:
                    themes[name] = "https://finance.naver.com" + href
            time.sleep(0.2)
    except Exception as e:
        print(f"Log: [Theme Crawler] Menu fetch error: {e}")
    return themes

def get_stocks_by_theme_link(theme_link, theme_name):
    """특정 테마 페이지에 접속하여 소속된 모든 종목을 긁어옵니다."""
    stocks = []
    try:
        res = requests.get(theme_link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')

        for tr in soup.find_all('tr'):
            td = tr.find('td', {'class': 'name'})
            if not td: continue
            a_tag = td.find('a')
            if not a_tag: continue
            
            stock_name = a_tag.text.strip()
            href = a_tag.get('href', '')
            if 'code=' in href:
                ticker = href.split('code=')[-1]
                if ticker and ticker.isdigit():
                    stocks.append({'name': stock_name, 'ticker': ticker, 'target_theme': theme_name})
    except Exception as e:
        print(f"Log: [Theme Crawler] Stocks error: {e}")
    return stocks
