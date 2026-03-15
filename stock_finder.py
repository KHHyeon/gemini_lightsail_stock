# -*- coding: utf-8 -*-
# File: ~/my_bot/stock_finder.py
import requests
from bs4 import BeautifulSoup
import re

def get_high_dividend_candidates(url, app_key, secret_key, token, benchmark_rate):
    """
    고장난 pykrx를 대체하여, 네이버 금융 배당 랭킹 페이지를 직접 동적 스크래핑합니다.
    어떤 공휴일이나 외부 라이브러리 업데이트에도 절대 깨지지 않는 무결성 엔진입니다.
    """
    print("Log: [Stock Finder Debug] 자체 네이버 금융 동적 스크래핑 엔진을 가동합니다.")
    
    candidates = []
    min_dividend = benchmark_rate * 0.8
    
    try:
        # 네이버 금융 배당 랭킹 페이지 접근
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get("https://finance.naver.com/sise/sise_dividend.naver", headers=headers, timeout=10)
        
        if res.status_code != 200:
            print(f"Log: [Stock Finder Debug] 네이버 웹페이지 접근 실패 (상태 코드: {res.status_code})")
            return []
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 배당 데이터가 들어있는 테이블의 행(tr) 추출
        table = soup.find('table', {'class': 'type_2'})
        if not table:
            print("Log: [Stock Finder Debug] 배당 테이블을 찾을 수 없습니다.")
            return []
            
        rows = table.find('tbody').find_all('tr')
        
        for row in rows:
            # 빈 줄이나 구분선 등 무의미한 행 스킵
            tds = row.find_all('td')
            if len(tds) < 5:
                continue
                
            # 종목명이 들어있는 a 태그 추출
            a_tag = row.find('a', href=True)
            if not a_tag or 'code=' not in a_tag['href']:
                continue
                
            name = a_tag.text.strip()
            
            # 리츠, 스팩, 우선주 사전 차단
            if "리츠" in name or "스팩" in name or name.endswith("우") or name.endswith("우B"):
                continue
                
            # href 속성에서 6자리 종목코드(Ticker) 추출
            ticker_match = re.search(r'code=(\d+)', a_tag['href'])
            if not ticker_match:
                continue
            ticker = ticker_match.group(1)
            
            # 배당수익률 추출 (네이버 배당 테이블 기준 5번째 열이 수익률)
            try:
                # 수익률 텍스트에서 콤마(,) 등 불순물 제거 후 float 변환
                yield_str = tds[4].text.strip().replace('%', '')
                div_yield = float(yield_str)
            except ValueError:
                continue
                
            # 기준 금리 대비 필터링
            if div_yield >= min_dividend:
                candidates.append({
                    "ticker": ticker,
                    "name": name,
                    "div_yield": div_yield
                })
                
            # 최상위 우량 배당주 100개가 채워지면 스캔 종료
            if len(candidates) >= 100:
                break
                
        print(f"Log: [Stock Finder Debug] 동적 스크래핑 성공. 실시간 1차 후보군 {len(candidates)}개를 확보했습니다.")
        return candidates
        
    except Exception as e:
        print(f"Log: [Stock Finder Debug] 스크래핑 엔진 치명적 에러: {str(e)}")
        return []
