# -*- coding: utf-8 -*-
# File: ~/my_bot/news_crawler.py
import requests
import warnings
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# BeautifulSoup의 XML 파싱 경고문 숨기기
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

def get_latest_news(ticker, limit=10):
    """
    구글 뉴스 RSS 피드를 활용하여 100% 안정적으로 뉴스를 긁어옵니다.
    """
    print(f"Log: [News Crawler] {ticker} 종목의 최신 뉴스 헤드라인 수집을 시작합니다 (Google News).", flush=True)
    url = f"https://news.google.com/rss/search?q={ticker}+주식&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return ["[News Crawler Error] 구글 뉴스 RSS 접근 실패"]
            
        soup = BeautifulSoup(res.text, 'html.parser')
        news_list = []
        
        items = soup.find_all('item')
        for item in items:
            title_tag = item.find('title')
            if title_tag:
                title = title_tag.text.strip()
                clean_title = " ".join(title.split())
                if clean_title not in news_list:
                    news_list.append(clean_title)
                    
            if len(news_list) >= limit:
                break
                
        print(f"Log: [News Crawler] {len(news_list)}개의 최신 뉴스를 성공적으로 확보했습니다.", flush=True)
        return news_list
        
    except Exception as e:
        print(f"Log: [News Crawler Error] 치명적 에러: {str(e)}", flush=True)
        return [f"[Error] 뉴스 수집 중 예외 발생: {str(e)}"]
