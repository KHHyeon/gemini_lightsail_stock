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

def get_ai_investment_report(ticker, chart_30d, macro, paper_portfolio, valuation):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Log: [Error] API 키가 설정되지 않았습니다. .env 파일을 확인해 주세요."

    client = genai.Client(api_key=api_key)
    
    # 1. 실시간 뉴스 수집
    latest_news = news_crawler.get_latest_news(ticker, limit=10)
    news_summary = "\n".join([f"- {news}" for news in latest_news]) if latest_news else "뉴스 데이터 없음"
    
    # 2. 30일 차트 데이터 수학적 요약 (AI가 읽기 편하게 가공)
    chart_summary = "차트 데이터 없음"
    if chart_30d and len(chart_30d) > 0:
        try:
            # 날짜순 정렬 (오름차순: 과거 -> 최신)
            sorted_chart = sorted(chart_30d, key=lambda x: x['date'])
            oldest = sorted_chart[0]
            newest = sorted_chart[-1]
            
            start_price = oldest['close']
            end_price = newest['close']
            highest = max([day['high'] for day in sorted_chart])
            lowest = min([day['low'] for day in sorted_chart])
            
            price_change_pct = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            chart_summary = (
                f"분석 기간: {oldest['date']} ~ {newest['date']} ({len(sorted_chart)}일)\n"
                f"- 시작가: {start_price:,}원 -> 현재가(종가): {end_price:,}원 (수익률: {price_change_pct:+.2f}%)\n"
                f"- 기간 내 최고가: {highest:,}원 / 최저가: {lowest:,}원"
            )
        except Exception as e:
            chart_summary = f"차트 요약 오류: {str(e)}"
    
    # 3. 시스템 인스트럭션
    system_instruction = """
    당신은 사용자의 투자 가이드를 100% 코드로 구현하고 실행하는 [수석 퀀트 개발자 겸 포트폴리오 매니저]입니다.
    인간의 편향(FOMO)을 제거하고, 제공된 객관적 수치(데이터)와 뉴스 팩트 위주로 분석하십시오.

    [투자 프로토콜 (반드시 준수할 4가지 레이어)]
    Layer 1: 3차 사고 & 기대 예측 (Beauty Contest)
    - 실시간 뉴스 헤드라인을 분석하여 시장 소음, 오너 리스크, 횡령/배임 등 치명적 악재가 있는지 최우선 확인.
    - 단순히 좋은 회사가 아니라 '남들이 열광할 산업'인지 판단할 것.

    Layer 2: 이유 있는 주가 상승 (Momentum)
    - 제공된 차트 요약 데이터를 바탕으로 수급 우위와 모멘텀을 확인할 것.

    Layer 3: 거시 경제 & 저평가 분석 (Valuation)
    - 매크로 지표 흐름 확인 및 PBR < (PER * ROE) 공식을 적용하여 수치상 저평가인지 판단.

    Layer 4: 배당 성장 (Income)
    - 배당수익률이 시장금리보다 높은지 비교.

    [매매 및 리스크 관리 실행 지침]
    - 분할 매수: 투자금을 10일간 균등 분할 매수하는 것을 기본값으로 설정.
    - 3중 매도 필터: -10% 손절, 8주 시간 손절, 주가 20% 상승 시 추적 손절매 적용.

    [출력 형식 (절대 규칙)]
    1. 맨 첫 줄은 반드시 "[핵심 논리] "로 시작하여, 짧게 한 줄 의견을 낼 것.
    2. 그 다음 줄부터 Section 1 (펀더멘털 & 뉴스 센티먼트 종합 분석) 작성.
    3. Section 2 (매매 및 리스크 관리 검토) 작성.
    4. Section 3 (치명적인 반대 근거): 당장 매수하면 안 되는 이유 2가지를 가장 날카롭게 지적(Devil's Advocate). 절대 요약하지 말 것.
    """

    # 4. 유저 프롬프트
    user_prompt = f"""
    분석 대상 종목코드: {ticker}
    
    [실시간 투자 지표 (Valuation)]
    {json.dumps(valuation, ensure_ascii=False) if valuation else '데이터 없음'}
    
    [실시간 뉴스 센티먼트 (최근 헤드라인 10건)]
    {news_summary}
    
    [시장 데이터 (차트 요약)]
    {chart_summary}
    
    [거시 경제 지표 (Macro)]
    {json.dumps(macro, ensure_ascii=False) if macro else '데이터 없음'}
    
    [내 잔고 상황]
    {json.dumps(paper_portfolio.get(ticker, '미보유 종목'), ensure_ascii=False)}
    
    위 데이터를 바탕으로 당신의 투자 원칙에 따라 '수치 기반'의 심층 리포트를 작성하십시오.
    """

    def call_gemini_api():
        return client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=user_prompt,
            config={'system_instruction': system_instruction}
        )

    print(f"Log: [AI Task] Gemini 2.5 Flash 모델에 분석을 요청했습니다. (최대 60초 대기)", flush=True)
    
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_gemini_api)
        elapsed = 0
        while elapsed < 60:
            try:
                response = future.result(timeout=5)
                print(f"Log: [AI Task] {elapsed}초 만에 AI 응답 수신 완료!", flush=True)
                return response.text
            except concurrent.futures.TimeoutError:
                elapsed += 5
                print(f"Log: [AI Task] Gemini 2.5 Flash 응답 대기 중... ({elapsed}초 경과)", flush=True)
        
        return "[AI System Error] 구글 서버 응답 지연 (60초 초과 타임아웃). 서버 부하가 심하거나 모델 응답이 지연되고 있습니다."
