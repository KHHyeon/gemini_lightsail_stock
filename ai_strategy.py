# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
from google import genai
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_ai_investment_report(ticker_symbol, chart_data, macro_data, portfolio_data, valuation_data):
    """
    PBR, PER, ROE 및 차트 데이터를 바탕으로 심층 보고서를 생성합니다.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Log: [Error] GOOGLE_API_KEY가 설정되지 않았습니다."

    client = genai.Client(api_key=api_key)
    
    system_instruction = """
    당신은 엄격하고 냉철한 수석 펀드매니저입니다. 아래의 [투자 프로토콜]을 반드시 준수하여 분석하십시오.

    [Section 1. 분석 원칙: 미인대회와 기본기]
    1. 3차 사고: 시장의 기대치와 현재 주가의 위치(거래량, 상대 강도)를 대조할 것.
    2. 매크로 연동: 환율, 금리, 유가가 종목 매출/비용에 미치는 경로 분석.
    3. 가치 평가: 제공된 PBR, PER, ROE 수치를 바탕으로 현재 가치가 적정한지 논리적으로 증명할 것.
    4. 배당 매력: 시장 금리 대비 배당 수익률 비교.

    [Section 2. 매매 및 생존 규칙]
    - 매수: 반드시 '10일 분할 매수' 관점에서 접근할 것.
    - 손절: 기본 -10% 준수 (강세 종목은 -15~17%까지).
    - 시간 손절: 8주간 반응 없을 시 정리 고려.

    [Section 3. 확증 편향 제거]
    - 반드시 내 논리를 무너뜨릴 수 있는 '반대 근거(Anti-thesis)'를 명시할 것.
    """

    user_prompt = f"""
    분석 대상: {ticker_symbol}
    
    [실시간 투자 지표]
    - PBR: {valuation_data.get('pbr')}
    - PER: {valuation_data.get('per')}
    - 계산된 ROE: {valuation_data.get('roe')}%
    - 현재가: {valuation_data.get('current_price')}원
    
    [시장 데이터]
    - 최근 30일 OHLCV 차트: {json.dumps(chart_data)}
    - 매크로 지표: {json.dumps(macro_data)}
    - 내 잔고 상황: {json.dumps(portfolio_data)}
    
    위 데이터를 바탕으로 당신의 투자 원칙에 따라 '수치 기반'의 심층 리포트를 작성하십시오.
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config={'system_instruction': system_instruction}
        )
        return response.text
    except Exception as e:
        if "429" in str(e):
            return "⚠️ [Quota Limit] API 사용량 초과. 1분 뒤 다시 시도해 주세요."
        return f"Log: [AI Error] {str(e)}"
