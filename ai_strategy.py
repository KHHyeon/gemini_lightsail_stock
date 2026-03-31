# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
import os
from google import genai

def get_gemini_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Log: [AI Error] GOOGLE_API_KEY가 환경변수에 없습니다. (.env 파일을 확인하세요)")
        return None
    return genai.Client(api_key=api_key)

def generate_text(prompt, model_name='gemini-2.5-flash'):
    client = get_gemini_client()
    if not client: return "AI 설정 오류: GOOGLE_API_KEY 누락"
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Log: [AI Generation Error] {e}")
        return "AI 리포트 생성 실패"

def infer_news_keywords():
    prompt = "현재 글로벌 거시경제와 한국 주식시장에서 가장 중요한 핵심 키워드(산업, 매크로 등)를 미국용 1개, 한국용 1개만 쉼표로 구분하여 알려줘. 예시: 금리인하, 반도체"
    res = generate_text(prompt)
    parts = [p.strip() for p in res.split(',')]
    if len(parts) >= 2: return parts[0], parts[1]
    return "연준", "삼성전자"

def get_daily_market_report(macro, us_news, kr_news, research_reports, extra):
    prompt = f"""
    당신은 친절하면서도 예리한 퀀트 애널리스트입니다.
    
    [절대 규칙]
    1. 어려운 금융 전문 용어 사용을 엄격히 금지합니다. 주식 초보자도 직관적으로 이해할 수 있는 쉬운 일상 용어로 완벽히 순화해서 작성하세요.
    2. 이모지는 절대 사용하지 마세요.
    
    아래 데이터를 분석하여 일일 마감 시황 보고서를 작성하세요.
    - 매크로 지표: {macro}
    - 주요 뉴스: {us_news} / {kr_news}
    - 여의도 증권사 산업 리포트: {research_reports}
    - 특이사항: {extra}
    
    [출력 양식]
    [ 핵심 매크로 지표 ]
    (전달받은 매크로 지표 중 미 국채 10년물 금리, WTI 원유 가격, 금 가격, 환율, VIX 등 주요 수치를 절대 숨기지 말고 직관적인 목록 형태로 정확히 나열하세요.)
    
    [ 오늘의 시장 흐름 ]
    (위의 매크로 수치들과 주요 뉴스를 엮어서 오늘 시장이 왜 이런 흐름을 보였는지 쉽게 설명)
    
    [ 주목할 산업 테마 키워드 ]
    (증권사 산업 리포트를 분석하여, 앞으로 돈이 몰릴 것 같은 유망한 산업 키워드 2~3개를 명확하게 추천. 짧은 명사형이어야 함)
    
    [ 내일의 투자 전략 ]
    (내일 어떻게 대응해야 할지 냉정하고 쉬운 조언)
    """
    return generate_text(prompt)

def get_weekly_portfolio_report(portfolio, news_dict):
    prompt = f"다음은 현재 모의투자 포트폴리오와 관련 뉴스입니다. 주간 성과를 분석하고, 다음 주 포지션 유지/축소에 대한 조언을 3단락으로 작성하세요. 쉬운 용어만 사용하세요. 포트폴리오: {portfolio}, 뉴스: {news_dict}"
    return generate_text(prompt)

def get_monthly_portfolio_report(portfolio, news_dict):
    prompt = f"다음은 월간 포트폴리오 현황과 뉴스입니다. 지난 한 달간의 성과를 리뷰하고, 자산 배분 전략의 맹점을 쉬운 언어로 지적하세요. 포트폴리오: {portfolio}"
    return generate_text(prompt)

def get_quarterly_portfolio_report(portfolio, news_dict):
    prompt = f"다음은 분기 포트폴리오 현황입니다. 거시 경제 흐름 변화와 연동하여 분기별 포트폴리오 교체 전략을 쉬운 말로 제시하세요. 포트폴리오: {portfolio}"
    return generate_text(prompt)

def get_theme_stock_narrative(target_theme, name, ticker, fundamentals):
    prompt = f"""
    당신은 성장 잠재력을 중시하는 애널리스트입니다. 
    종목 '{name}({ticker})'이(가) '{target_theme}' 테마에 어떻게 연관되어 있으며, 
    현재 재무 상태(총점: {fundamentals.get('score', 'N/A')}, PBR: {fundamentals.get('pbr', 'N/A')})를 고려할 때 
    단순한 테마성 껍데기인지, 아니면 크게 성장할 진짜 유망주인지 어려운 용어 없이 3문장 이내로 평가하세요.
    """
    return generate_text(prompt)

def get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context):
    prompt = f"""
    당신은 '비대칭적 손익비'를 추구하는 실전 헤지펀드 매니저입니다.
    
    종목: {stock_name}({ticker})
    최근 30일 차트요약: {chart_30d[-1] if chart_30d else '데이터 없음'}
    거시경제: {macro}
    밸류에이션: {valuation}
    테마 컨텍스트: {theme_context}
    
    [절대 규칙]
    1. 어려운 금융 전문 용어를 절대 쓰지 말고, 일상 언어로 설명하세요.
    2. 분석 후 최종 투자 의견을 [적극찬성], [찬성], [반대], [적극반대] 중 하나로 글의 서두에 명확히 제시하세요.
    3. 마지막 줄에 반드시 다음 형식으로 팩트 기반의 구체적인 요약을 작성하세요.
       '[한줄요약] [투자의견] 구체적 매수사유 | [상승조건] (어떤 실적/매크로/이벤트가 발생해야 하는가) | [손절조건] (정확히 어떤 매크로 수치가 악화되거나 실적이 깨지면 팔 것인가)'
    4. '상방잠재력', '거시환경 개선' 같은 추상적인 단어를 엄격히 금지합니다. 'WTI 90불 돌파 시', '영업이익 적자 전환 시', '미 국채 금리 4.5% 돌파 시' 등 측정 가능하고 구체적인 조건을 반드시 명시하세요.
    이모지 사용 금지.
    """
    return generate_text(prompt)

def check_fundamental_damage(ticker, stock_name, chart_30d, macro, valuation, theme_context):
    prompt = f"""
    당신은 기업의 본질적 가치와 성장 스토리를 믿는 장기 투자자입니다.
    현재 포트폴리오에 보유 중인 종목의 '투자 아이디어 훼손 여부'를 진단해야 합니다.
    
    종목: {stock_name}({ticker})
    최근 30일 차트요약: {chart_30d[-1] if chart_30d else '데이터 없음'}
    현재 거시경제: {macro}
    현재 밸류에이션: {valuation}
    [중요] 초기 매수이유 및 설정된 손절조건: {theme_context}
    
    [절대 규칙]
    1. 주가 하락 등 '단기 노이즈'는 무시하세요.
    2. 제공된 '초기 매수이유 및 설정된 손절조건'을 꼼꼼히 읽고, 사용자가 설정했던 그 구체적인 악재(예: WTI 특정 가격 돌파, 특정 거시지표 악화 등)가 현재 시점에서 실제로 발생했는지 냉정하게 대조하세요.
    3. 사전에 정의된 [손절조건]에 명확히 도달했거나 기업 본질이 파괴되었다면 서두에 [펀더멘털훼손] 이라고 쓰세요.
    4. 아직 손절조건에 도달하지 않았고 기대했던 잠재력이 살아있다면 [보유유지] 라고 쓰세요.
    5. 그 뒤에 왜 그렇게 판단했는지 초기 손절조건과 현재 지표를 대조하여 3문장 이내로 설명하세요.
    """
    return generate_text(prompt)

def match_naver_themes(keyword, theme_list):
    prompt = f"""
    사용자가 '{keyword}'와(과) 관련된 주식 테마를 찾고 있습니다.
    아래는 네이버 금융에서 공식적으로 제공하는 테마 목록입니다.
    
    [네이버 공식 테마 목록]
    {', '.join(theme_list)}
    
    위 목록 중에서 사용자의 검색어와 가장 의미가 일치하는 테마를 최대 3개만 골라주세요.
    반드시 위 목록에 존재하는 정확한 텍스트로만 답변해야 하며, 여러 개일 경우 쉼표(,)로 구분해 주세요.
    설명이나 부가적인 말은 절대 하지 마세요.
    """
    client = get_gemini_client()
    if not client: return []
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        matched = [t.strip() for t in response.text.split(',') if t.strip()]
        valid_themes = [t for t in matched if t in theme_list]
        return valid_themes
    except Exception as e:
        print(f"Log: [AI Router Error] {e}")
        return []
