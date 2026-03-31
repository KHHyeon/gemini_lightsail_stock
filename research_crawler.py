# -*- coding: utf-8 -*-
# File: ~/my_bot/research_crawler.py
import requests
from bs4 import BeautifulSoup

def get_latest_industry_reports(limit=5):
    """네이버 금융 리서치 센터에서 최신 산업분석 리포트 제목과 증권사 의견을 긁어옵니다."""
    url = "https://finance.naver.com/research/industry_list.naver"
    reports = []
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        res.encoding = 'euc-kr'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 네이버 리서치 테이블(type_1) 파싱
        table = soup.find('table', {'class': 'type_1'})
        if not table: return reports
        
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            # 정상적인 데이터 행은 td가 6개 존재함 (분류, 제목, 증권사, 첨부, 등록일, 조회수)
            if len(tds) >= 3:
                industry = tds[0].text.strip()
                title_tag = tds[1].find('a')
                broker = tds[2].text.strip()
                
                if title_tag and industry:
                    title = title_tag.text.strip()
                    reports.append(f"[{industry} 산업] {title} (출처: {broker})")
                    
            if len(reports) >= limit: break
    except Exception as e:
        print(f"Log: [Research Crawler Error] {e}")
        
    return reports
