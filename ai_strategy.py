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

def generate_text(prompt, model_name=None):
    client = get_gemini_client()
    if not client: return "AI 설정 오류: GOOGLE_API_KEY 누락"
    
    if model_name is None:
        model_name = os.getenv("AI_MODEL_NAME", "gemini-2.5-flash")
        
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
    prompt = "현재 글로벌 거시경제와 한국 주식시장에서 가장 중요한 핵심 키워드(산업, 매크로 등)를 미국용 1개, 한국용 1개만 쉼표로 구분하여 알려줘. 부가 설명 없이 오직 '단어, 단어' 형태로만 대답해. 예시: 금리인하, 반도체"
    raw_text = generate_text(prompt)
    
    # 쉼표를 기준으로 분리하고 공백 제거
    parts = [p.strip() for p in raw_text.split(',')]
    
    # AI가 쉼표를 누락하거나 예상치 못한 형식으로 대답했을 경우를 위한 방어 로직 (Fallback)
    if len(parts) >= 2:
        return parts[0], parts[1]
    else:
        print(f"Log: [AI Parsing Warning] 예상치 못한 형태의 키워드 반환: {raw_text}. 기본 키워드로 대체합니다.")
        return "미국증시", "한국증시"

def get_daily_market_report(macro, us_news, kr_news, research_reports, extra):
    prompt = f"""
    당신은 친절하면서도 예리한 퀀트 애널리스트입니다.
    
    [절대 규칙]
    1. 어려운 금융 전문 용어 사용을 엄격히 금지합니다. 주식 초보자도 직관적으로 이해할 수 있는 쉬운 일상 용어로 완벽히 순화해서 작성하세요.
    2. 뉴스의 주관적인 감정이나 자극적인 제목은 무시하고, 오직 '객관적 사실'만 추출하여 요약하세요.
    3. 이모지는 절대 사용하지 마세요.
    
    아래 데이터를 분석하여 일일 마감 시황 보고서를 작성하세요.
    - 매크로 지표: {macro}
    - 주요 뉴스: {us_news} / {kr_news}
    - 여의도 증권사 산업 리포트: {research_reports}
    - 특이사항: {extra}
    
    [출력 양식]
    [ 핵심 매크로 지표 ]
    (전달받은 매크로 지표 중 미 국채 10년물 금리, WTI 원유 가격, 금 가격, 환율, VIX 등 주요 수치를 절대 숨기지 말고 직관적인 목록 형태로 정확히 나열하세요.)
    
    [ 오늘의 시장 흐름 ]
    (위의 매크로 수치들과 주요 뉴스의 '객관적 팩트'를 엮어서 오늘 시장이 왜 이런 흐름을 보였는지 쉽게 설명)
    
    [ 주목할 산업 테마 키워드 ]
    (증권사 산업 리포트를 분석하여, 앞으로 돈이 몰릴 것 같은 유망한 산업 키워드 2~3개를 명확하게 추천. 짧은 명사형이어야 함)
    
    [ 내일의 투자 전략 ]
    (내일 어떻게 대응해야 할지 냉정하고 쉬운 조언)
    """
    return generate_text(prompt)

def get_weekly_portfolio_report(portfolio, news_dict):
    prompt = f"""
    다음은 현재 보유 중인 모의투자 포트폴리오 현황과 종목별 최신 뉴스입니다.
    이번 주 리포트는 단순한 수익률 성과 분석이 아닙니다.
    
    [절대 규칙]
    1. 각 종목별로 최초 매수 시 기록했던 '투자 이유(상승 조건)'가 현재도 팩트(객관적 사실) 기반으로 유효한지 냉정하게 점검하세요.
    2. 뉴스의 주관적 감정이나 논조는 철저히 배제하고, 오직 확정된 사실(수주, 실적 등)만 추출하여 평가하세요.
    3. 점검 결과를 바탕으로 해당 종목의 전략 수정 및 보완(유지, 비중 축소, 손절 등)을 명확히 제시하세요.
    4. 초보자도 이해할 수 있는 쉬운 용어로 3단락 이내로 작성하세요.
    이모지 사용 금지.
    
    포트폴리오: {portfolio}
    뉴스: {news_dict}
    """
    return generate_text(prompt)

def get_monthly_portfolio_report(portfolio, news_dict):
    prompt = f"""
    다음은 월간 포트폴리오 현황과 관련 뉴스입니다.
    
    [절대 규칙]
    1. 현재 시장의 매크로 흐름과 뉴션을 분석하여, 시장의 관심이 '성장주'로 향하고 있는지 '가치주'로 향하고 있는지 팩트 기반으로 판별하세요.
    2. 판별된 트렌드를 바탕으로 현재 포트폴리오의 자산 비중이 적절한지 평가하고, 어떻게 리밸런싱(비중 조절)해야 할지 구체적인 가이드를 제시하세요.
    3. 초보자도 단번에 이해할 수 있는 쉬운 일상 언어로 작성하세요.
    이모지 사용 금지.
    
    포트폴리오: {portfolio}
    뉴스: {news_dict}
    """
    return generate_text(prompt)

def get_quarterly_portfolio_report(portfolio, news_dict):
    prompt = f"""
    다음은 분기 포트폴리오 현황과 관련 뉴스입니다.
    
    [절대 규칙]
    1. 분기 실적 시즌을 맞이하여, 각 기업의 핵심 펀더멘털 지표(영업이익, 잉여현금흐름(FCF), ROE 등)가 훼손되지 않고 유지되고 있는지 팩트 기반으로 점검하세요.
    2. 뉴스의 과장된 수사나 논조는 배제하고, 확정된 실적 수치만으로 전망 유지 여부를 냉정하게 판단하세요.
    3. 실적이 꺾인 종목은 가차 없이 매도(교체)를 권고하고, 성장세가 유지되는 종목은 보유를 지시하세요.
    4. 어려운 금융 용어를 풀어서 쉬운 말로 설명하세요.
    이모지 사용 금지.
    
    포트폴리오: {portfolio}
    뉴스: {news_dict}
    """
    return generate_text(prompt)

def get_theme_stock_narrative(target_theme, name, ticker, fundamentals):
    prompt = f"""
    당신은 성장 잠재력을 중시하는 애널리스트입니다. 
    종목 '{name}({ticker})'이(가) '{target_theme}' 테마에 어떻게 연관되어 있으며, 
    현재 재무 상태(총점: {fundamentals.get('score', 'N/A')}, PBR: {fundamentals.get('pbr', 'N/A')})를 고려할 때 
    단순한 테마성 껍데기인지, 아니면 크게 성장할 진짜 유망주인지 어려운 용어 없이 3문장 이내로 평가하세요.
    이모지 사용 금지.
    """
    return generate_text(prompt)

def get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context, recent_news):
    prompt = f"""
    당신은 '비대칭적 손익비'를 추구하는 실전 헤지펀드 매니저입니다.
    
    종목: {stock_name}({ticker})
    최근 30일 차트요약: {chart_30d[-1] if chart_30d else '데이터 없음'}
    거시경제: {macro}
    밸류에이션: {valuation}
    테마 컨텍스트: {theme_context}
    [중요] 최신 핵심 뉴스 (상승 촉매제 판별용): {recent_news}
    
    [절대 규칙]
    1. 어려운 금융 전문 용어를 절대 쓰지 말고, 일상 언어로 설명하세요.
    2. 제공된 '최신 핵심 뉴스'를 검토할 때 기자의 주관적인 감정, 긍정/부정적 논조, 자극적인 제목은 완전히 무시하세요. 오직 '객관적 사실(실제 수주 계약, 확정된 실적 수치, 공식적인 법안 통과 등)'만을 추출하여 상승 촉매제로 삼으십시오.
    3. 분석 후 최종 투자 의견을 [적극찬성], [찬성], [반대], [적극반대] 중 하나로 글의 서두에 명확히 제시하세요.
    4. 마지막 줄에 반드시 다음 형식으로 팩트 기반의 구체적인 요약을 작성하세요.
       '[한줄요약] [투자의견] 뉴스와 가치를 종합한 매수사유 | [상승조건] (어떤 팩트/실적/이벤트가 발생해야 하는가) | [손절조건] (정확히 어떤 팩트/수치가 악화되거나 실적이 깨지면 팔 것인가)'
    5. '상방잠재력', '거시환경 개선' 같은 추상적인 단어를 엄격히 금지합니다. 측정 가능하고 구체적인 조건을 반드시 명시하세요.
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
    1. 주가 하락 등 '단기 노이즈'나 언론의 부정적인 '논조'는 철저히 무시하세요.
    2. 제공된 '초기 매수이유 및 설정된 손절조건'을 꼼꼼히 읽고, 설정했던 구체적인 악재가 현재 시점에서 '객관적 사실(팩트)'로 발생했는지 냉정하게 대조하세요.
    3. 사전에 정의된 [손절조건]이 팩트로 확인되어 기업 본질이 파괴되었다면 서두에 [펀더멘털훼손] 이라고 쓰세요.
    4. 아직 팩트 기반의 손절조건에 도달하지 않았고 기대했던 잠재력이 살아있다면 [보유유지] 라고 쓰세요.
    5. 그 뒤에 왜 그렇게 판단했는지 초기 손절조건과 현재 지표(사실)를 대조하여 3문장 이내로 설명하세요.
    이모지 사용 금지.
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
        model_name = os.getenv("AI_MODEL_NAME", "gemini-2.5-flash")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        matched = [t.strip() for t in response.text.split(',') if t.strip()]
        valid_themes = [t for t in matched if t in theme_list]
        return valid_themes
    except Exception as e:
        print(f"Log: [AI Router Error] {e}")
        return []

