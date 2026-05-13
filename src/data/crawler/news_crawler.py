# -*- coding: utf-8 -*-
# File: ~/my_bot/news_crawler.py
import requests
import warnings
import urllib.parse
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def get_latest_news(keyword, limit=10, search_type="stock"):
    """
    search_type="stock": 기존처럼 쌍따옴표("")와 키워드(특징주 등)를 붙여 엄격하게 검색.
    search_type="macro": 시황 뉴스를 위해 쌍따옴표 없이 유연하게 검색.
    """
    print(f"Log: [News Crawler] '{keyword}' 뉴스 수집 시작 (모드: {search_type}).", flush=True)
    
    if search_type == "stock":
        exact_match_name = f'"{keyword}"'
        encoded_name = urllib.parse.quote(exact_match_name)
        query = f"{encoded_name}+AND+(특징주+OR+주가+OR+실적)"
    else:
        # 매크로 모드: 띄어쓰기를 안전한 %20 형태로 인코딩
        query = urllib.parse.quote(keyword)
        
    # URL이 마크다운으로 변환되지 않도록 순수한 문자열로 조합
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        news_list = []
        
        for item in soup.find_all('item'):
            title_tag = item.find('title')
            if title_tag:
                clean_title = title_tag.text.strip()
                news_list.append(clean_title)
                if len(news_list) >= limit: break
                
        print(f"Log: [News Crawler] '{keyword}' 관련 최신 뉴스 {len(news_list)}개 확보.", flush=True)
        return news_list
    except Exception as e:
        print(f"Log: [News Crawler Error] {str(e)}", flush=True)
        return []
