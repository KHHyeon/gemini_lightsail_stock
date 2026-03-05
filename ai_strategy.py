# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
from google import genai
import os
import json
from dotenv import load_dotenv

load_dotenv()

def get_ai_investment_report(ticker_symbol, chart_data, macro_data, portfolio_data):
    """
    사용자의 Section 1~3 투자 프로토콜을 AI에게 주입하여 심층 보고서를 생성합니다.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return "Log: [Error] GOOGLE_API_KEY가 설정되지 않았습니다."

    client = genai.Client(api_key=api_key)
    
    # [Section 1~3] 투자 원칙 및 페르소나 주입
    system_instruction = """
    당신은 엄격하고 냉철한 수석 펀드매니저입니다. 아래의 [투자 프로토콜]을 반드시 준수하여 분석하십시오.

    [Section 1. 분석 원칙: 미인대회와 기본기]
    1. 3차 사고: 시장의 기대치와 현재 주가의 위치(거래량, 상대 강도)를 대조할 것.
    2. 매크로 연동: 환율, 금리, 유가가 해당 산업 및 종목의 비용/매출에 미치는 경로를 분석할 것.
    3. 가치 평가: PBR = PER × ROE 공식을 사용하여 현재 밸류에이션의 적정성을 판단할 것.
    4. 배당 매력: 현재 시장 금리 대비 배당 수익률과 이익 성장성을 비교할 것.

    [Section 2. 매매 및 생존 규칙]
    - 매수: 확신이 들더라도 반드시 '10일 분할 매수' 관점에서 접근할 것.
    - 손절: 기본 -10%를 준수하되, 강세 종목은 -15~17%까지 유연하게 적용.
    - 시간 손절: 8주간 주가 반응이 없을 시 기회비용 차원에서 정리를 고려할 것.
    - 추적 손절매: 주가 상승 시 수익 보존을 위해 손절 라인을 상향할 것.

    [Section 3. 확증 편향 제거]
    - "왜 지금 사야 하는가?"에 대한 시급성을 논할 것.
    - "내가 틀렸다면 무엇 때문인가?"를 자문할 것.
    - 반드시 내 논리를 무너뜨릴 수 있는 강력한 '반대 근거(Anti-thesis)'를 최소 1개 이상 제시할 것.

    [출력 형식]
    - 반드시 한국어로 작성하십시오.
    - 서론: 현재 주가 및 매크로 상황 요약.
    - 본론: PBR/ROE 분석 및 기술적 위치.
    - 결론: 매수/홀딩/매도 의견 및 분할 매수 전략.
    - 비판: 강력한 반대 근거(Anti-thesis) 명시.
    """

    user_prompt = f"""
    분석 대상: {ticker_symbol}
    
    [입력 데이터]
    1. 최근 30일 차트 데이터: {json.dumps(chart_data)}
    2. 매크로 지표 (환율, 금리, 유가 등): {json.dumps(macro_data)}
    3. 현재 계좌/포트폴리오 상황: {json.dumps(portfolio_data)}
    
    위 데이터를 바탕으로 당신의 투자 원칙에 따라 심층 리포트를 작성하십시오.
    """

    try:
        # Gemini 1.5 Pro 모델 사용하여 깊이 있는 분석 수행
        response = client.models.generate_content(
            model="gemini-1.5-pro",
            contents=user_prompt,
            config={'system_instruction': system_instruction}
        )
        return response.text
    except Exception as e:
        return f"Log: [AI Error] 분석 중 오류 발생: {str(e)}"
