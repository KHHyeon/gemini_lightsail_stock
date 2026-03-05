# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
from google import genai
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_ai_investment_report(ticker_symbol, chart_data, macro_data, portfolio_data):
    """
    최신 google-genai SDK를 사용하여 사용자의 투자 프로토콜을 집행합니다.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Log: [Error] GOOGLE_API_KEY is missing."

    # 최신 클라이언트 설정
    client = genai.Client(api_key=api_key)
    
    # Section 1~3 투자 원칙 주입
    system_instruction = f"""
    당신은 엄격한 수석 펀드매니저입니다. 아래 원칙을 반드시 준수하십시오.

    [Section 1. 분석 원칙]
    1. 3차 사고: 타인의 기대를 예측하고 상대 강도와 거래량을 체크할 것.
    2. 매크로: 환율, 금리, 유가가 해당 종목에 미치는 경로 분석.
    3. 심층 분석: 기술적 위치 평가 및 기본적 분석($PBR = PER \\times ROE$) 수행.
    4. 배당: 시장금리 대비 매력도 및 이익 성장 확인.

    [Section 2. 매매 및 생존 규칙]
    - 10일 분할 매수 원칙 적용.
    - 손절: 기본 -10%. (강세 종목 -15~17% 적용). 8주간 무반응 시 시간 손절.
    - 추적 손절매: 주가 상승 시 손절 가격 상향 조정.

    [Section 3. 편향 제거]
    - "왜 지금인가?", "무엇이 틀리면 팔 것인가?" 명시.
    - 반대 근거(Anti-thesis): 내 논리를 무너뜨릴 비판적 데이터를 최소 1개 제시.
    """

    user_prompt = f"""
    종목: {ticker_symbol}
    차트(30일): {json.dumps(chart_data)}
    매크로: {json.dumps(macro_data)}
    포트폴리오: {json.dumps(portfolio_data)}
    
    위 데이터를 바탕으로 [Output Format]에 맞춰 한국어로 보고서를 작성하십시오.
    """

    try:
        # 모델 호출 (Gemini 1.5 Pro 사용)
        response = client.models.generate_content(
            model="gemini-1.5-pro",
            contents=user_prompt,
            config={'system_instruction': system_instruction}
        )
        return response.text
    except Exception as e:
        return f"Log: [AI Error] 분석 실패: {str(e)}"
