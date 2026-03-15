# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
import os
import json
import concurrent.futures
import time
from google import genai
from dotenv import load_dotenv
import news_crawler

load_dotenv()

def get_ai_investment_report(ticker, stock_name, chart_30d, macro, paper_portfolio, valuation):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Log: [Error] API 키 누락."

    client = genai.Client(api_key=api_key)
    
    latest_news = news_crawler.get_latest_news(stock_name, limit=10)
    news_summary = "\n".join([f"- {news}" for news in latest_news]) if latest_news else "뉴스 데이터 없음"
    
    chart_summary = "차트 데이터 없음"
    if chart_30d and len(chart_30d) > 0:
        try:
            sorted_chart = sorted(chart_30d, key=lambda x: x['date'])
            oldest, newest = sorted_chart[0], sorted_chart[-1]
            start_price, end_price = oldest['close'], newest['close']
            highest = max([day['high'] for day in sorted_chart])
            lowest = min([day['low'] for day in sorted_chart])
            pct = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            chart_summary = (
                f"분석 기간: {oldest['date']} ~ {newest['date']} ({len(sorted_chart)}일)\n"
                f"- 시작가: {start_price:,}원 -> 현재가: {end_price:,}원 (수익률: {pct:+.2f}%)\n"
                f"- 최고가: {highest:,}원 / 최저가: {lowest:,}원"
            )
        except Exception as e:
            chart_summary = f"차트 요약 오류: {str(e)}"
    
    # [수정] 프롬프트 최상단에 [한줄요약] 작성을 엄격히 강제
    system_instruction = """
    당신은 100% 수치와 팩트 기반으로 판단하는 수석 퀀트 개발자입니다.
    제공된 뉴스 헤드라인, 차트 요약, 밸류에이션(배당률 포함), 매크로 지표를 종합하여 분석하십시오.
    [출력 규칙]
    1. 맨 첫 줄은 반드시 "[한줄요약] "으로 시작하여, 매수 또는 기각의 핵심 사유를 30자 이내로 압축할 것. (예: [한줄요약] 배당 매력 저하 및 단기 수급 악화로 관망 요망)
    2. 그 다음 줄부터 "[핵심 논리] "를 작성하여 상세 의견을 제시할 것.
    3. Section 1 (펀더멘털 & 뉴스 센티먼트) 작성.
    4. Section 2 (매매 및 리스크 관리) 작성.
    5. Section 3 (치명적인 반대 근거 2가지) 날카롭게 지적할 것.
    """

    user_prompt = f"""
    분석 대상 종목: {stock_name} ({ticker})
    
    [실시간 투자 지표 (Valuation & 배당)]
    {json.dumps(valuation, ensure_ascii=False) if valuation else '데이터 없음'}
    
    [실시간 뉴스 센티먼트 (최근 헤드라인 10건)]
    {news_summary}
    
    [시장 데이터 (차트 요약)]
    {chart_summary}
    
    [거시 경제 지표 (Macro)]
    {json.dumps(macro, ensure_ascii=False) if macro else '데이터 없음'}
    
    [내 잔고 상황]
    {json.dumps(paper_portfolio.get(ticker, '미보유 종목'), ensure_ascii=False)}
    """

    def call_gemini():
        return client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=user_prompt,
            config={'system_instruction': system_instruction}
        )

    print(f"Log: [AI Task] Gemini 2.5 Flash 응답 대기 시작 (최대 60초)", flush=True)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_gemini)
        elapsed = 0
        while elapsed < 60:
            try:
                response = future.result(timeout=5)
                print(f"Log: [AI Task] {elapsed}초 만에 AI 응답 수신 완료!", flush=True)
                return response.text
            except concurrent.futures.TimeoutError:
                elapsed += 5
                print(f"Log: [AI Task] 대기 중... ({elapsed}초)", flush=True)
        return "[AI Error] 구글 서버 60초 초과 타임아웃."
