# -*- coding: utf-8 -*-
# File: ~/my_bot/stock_finder.py
import requests
from bs4 import BeautifulSoup
import re

def get_high_dividend_candidates(url, app_key, secret_key, token, benchmark_rate):
    """
    접근이 막힌 pykrx를 영구히 폐기하고, 네이버 금융의 코스피 시가총액 상위 페이지를 
    직접 스크래핑하여 KOSPI 100 동적 유니버스를 완벽하게 추출합니다.
    (kis api 파라미터는 호환성을 위해 유지합니다.)
    """
    print("Log: [Stock Finder] KOSPI 시가총액 상위 100대 대장주 웹 스크래핑을 시작합니다.")
    candidates = []
    
    # 봇 차단 방지를 위한 User-Agent 헤더
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # 1페이지(1~50위)와 2페이지(51~100위)를 순차적으로 스크래핑
        for page in [1, 2]:
            naver_url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
            res = requests.get(naver_url, headers=headers, timeout=10)
            
            if res.status_code != 200:
                print(f"Log: [Stock Finder Error] 네이버 시가총액 페이지 접근 실패 (상태 코드: {res.status_code})")
                continue
                
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 시가총액 데이터가 담긴 메인 테이블 추출
            table = soup.find('table', {'class': 'type_2'})
            if not table:
                continue
                
            rows = table.find('tbody').find_all('tr')
            
            for row in rows:
                tds = row.find_all('td')
                # 빈 줄이나 구분선 등 무의미한 행 스킵
                if len(tds) < 5:
                    continue
                    
                # 종목명과 링크가 포함된 a 태그 추출
                a_tag = row.find('a', href=True)
                if not a_tag or 'code=' not in a_tag['href']:
                    continue
                    
                name = a_tag.text.strip()
                
                # 리츠, 스팩, 우선주 등 가치평가가 불가능한 특수 종목 사전 차단
                if "리츠" in name or "스팩" in name or name.endswith("우") or name.endswith("우B"):
                    continue
                    
                # href 속성에서 6자리 종목코드(Ticker) 추출
                ticker_match = re.search(r'code=(\d+)', a_tag['href'])
                if not ticker_match:
                    continue
                    
                ticker = ticker_match.group(1)
                
                candidates.append({
                    "ticker": ticker,
                    "name": name
                })
                
        print(f"Log: [Stock Finder] 스크래핑 완료. 순수 KOSPI 대장주 {len(candidates)}개를 확보하여 2차 퀀트 스캐너로 전달합니다.")
        return candidates
        
    except Exception as e:
        print(f"Log: [Stock Finder Error] 스크래핑 엔진 치명적 에러: {str(e)}")
        return []

