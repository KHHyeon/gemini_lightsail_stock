# -*- coding: utf-8 -*-
# File: ~/my_bot/news_crawler.py
import requests
import warnings
import urllib.parse
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def get_latest_news(stock_name, limit=10):
    """
    URL 인코딩 및 Exact Match("") 기법을 적용하여 
    특수기호(&)가 포함되거나 이름이 비슷한 종목의 뉴스를 엄격하게 분리하여 수집합니다.
    """
    print(f"Log: [News Crawler] '{stock_name}' 엄격한 뉴스 수집 시작.", flush=True)
    
    # 1. 검색어를 쌍따옴표로 묶어 정확도(Exact Match) 강제
    exact_match_name = f'"{stock_name}"'
    
    # 2. 특수기호(& 등)가 URL을 깨뜨리지 않도록 안전하게 인코딩
    encoded_name = urllib.parse.quote(exact_match_name)
    
    # 3. 구글 검색 연산자 적용 (예: "KT&G" AND (특징주 OR 주가 OR 실적))
    query = f"{encoded_name}+AND+(특징주+OR+주가+OR+실적)"
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        news_list = []
        
        for item in soup.find_all('item'):
            title_tag = item.find('title')
            if title_tag:
                clean_title = " ".join(title_tag.text.strip().split())
                if clean_title not in news_list:
                    news_list.append(clean_title)
                    
            if len(news_list) >= limit:
                break
                
        print(f"Log: [News Crawler] {len(news_list)}개의 뉴스를 확보했습니다.", flush=True)
        return news_list
    except Exception as e:
        print(f"Log: [News Crawler Error] {str(e)}", flush=True)
        return [f"[Error] 뉴스 수집 실패: {str(e)}"]
