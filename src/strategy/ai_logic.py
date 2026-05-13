# -*- coding: utf-8 -*-
import os
from google import genai

def get_gemini_client():
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key: return None
    return genai.Client(api_key=api_key)

def generate_text(prompt, model_name=None):
    client = get_gemini_client()
    if not client: return "AI 설정 오류"
    if model_name is None: model_name = os.getenv("AI_MODEL_NAME", "gemini-2.5-flash")
    try:
        response = client.models.generate_content(model=model_name, contents=prompt)
        return response.text.strip()
    except Exception as e:
        print(f"Log: [AI Error] {e}")
        return "AI 리포트 생성 실패"

def infer_news_keywords():
    prompt = "현재 주식시장에서 가장 중요한 핵심 키워드(산업, 매크로 등)를 미국용 1개, 한국용 1개만 쉼표로 구분하여 알려줘. (예: 금리인하, 반도체)"
    return generate_text(prompt)

def get_daily_market_report(macro, us_news, kr_news, research_reports, extra):
    prompt = f"""
    [절대 규칙]
    1. 스마트폰에서 읽기 쉽도록 문장을 아주 짧고 명확하게 끊어서 작성하세요.
    2. 전문 용어를 배제하고 핵심 팩트만 전달하세요.
    
    데이터: 매크로({macro}), 뉴스({us_news}/{kr_news}), 리포트({research_reports})
    
    [출력 양식]
    [ 핵심 매크로 ]
    - (핵심 지표 수치만 간결히 나열)
    
    [ 시장 흐름 요약 ]
    - (오늘 시장이 왜 이런 흐름인지 2~3줄 요약)
    
    [ 주목할 섹터 ]
    - (유망 산업 키워드 2개 명시)
    
        [ 최종 행동 지침 ]
    - 행동: (아래 중 택 1: [적극매수] / [보수적 매수] / [관망] / [비중축소] / [전량매도])
    - 근거: (행동의 원리와 근거를 초보자도 알기 쉽게 1~2줄로 설명)
    - 대상 섹터: (명시)
    """
    return generate_text(prompt)

def get_deep_market_report(macro, kr_news, research_reports):
    prompt = f"""
    10:00 기준 한국 시장 자금 흐름을 분석합니다. 스마트폰 가독성을 위해 간결하게 작성하세요.
    
    [출력 양식]
    [ 10:00 자금 흐름 ]
    - (수급 쏠림 및 주도 섹터 2~3줄 요약)
    
        [ 최종 행동 지침 ]
    - 행동: (아래 중 택 1: [적극매수] / [보수적 매수] / [관망] / [비중축소] / [전량매도])
    - 근거: (행동의 원리와 근거를 초보자도 알기 쉽게 1~2줄로 설명)
    - 대상 섹터: (명시)
    """
    return generate_text(prompt)

def get_weekly_portfolio_report(portfolio, news_dict):
    prompt = f"보유 종목({portfolio})의 투자 이유 유효성을 뉴스({news_dict}) 기반으로 냉정히 점검하세요. 스마트폰 가독성을 위해 짧은 개조식으로 작성."
    return generate_text(prompt)

def get_monthly_portfolio_report(portfolio, news_dict):
    prompt = f"포트폴리오({portfolio}) 및 뉴스({news_dict}) 분석. 성장주/가치주 트렌드 및 리밸런싱 가이드를 모바일 가독성에 맞춰 짧게 작성."
    return generate_text(prompt)

def get_quarterly_portfolio_report(portfolio, news_dict):
    prompt = f"포트폴리오({portfolio}) 기업 실적 훼손 여부 점검. 훼손 시 매도 권고. 모바일에서 읽기 편하게 핵심만 작성."
    return generate_text(prompt)

def get_theme_stock_narrative(target_theme, name, ticker, fundamentals):
    prompt = f"'{name}'이 '{target_theme}'의 진짜 성장주인지 재무({fundamentals}) 바탕으로 2문장 이내 핵심만 요약."
    return generate_text(prompt)

def get_emergency_news_check(name, news_text):
    prompt = f"""
    [긴급 팩트체크] 
    종목 '{name}'의 최신 뉴스입니다: {news_text}
    위 뉴스 내용 중 횡령, 배임, 대규모 유상증자, 어닝쇼크 등 치명적인 돌발 악재가 존재합니까?
    치명적 악재가 있다면 [위험], 없다면 [통과]라고 첫 줄에 반드시 명시하고 1문장으로 이유를 적어주세요.
    """
    return generate_text(prompt)

def get_ai_investment_report(ticker, stock_name, chart_30d, macro, pf, valuation, theme_context, recent_news):
    prompt = f"""
    스마트폰 가독성을 극대화하여 아래 종목을 분석하세요.
    종목: {stock_name}({ticker}) | 밸류: {valuation} | 뉴스: {recent_news}
    
    [특수 섹터 규칙]
    만약 이 기업이 금융업(은행, 증권, 보험, 지주)이라면 NPL(부실채권비율), CET1(보통주자본비율) 등의 리스크 맥락과 총주주환원율(배당 및 자사주) 의지를 파악하여 [상승조건]에 '주주환원 정책 지속성'을 포함하세요.
    
        마지막 줄은 반드시 아래 양식을 지키세요:
    [한줄요약] [의견: 매수적극찬성/매수찬성/매수주의/매수반대/매수적극반대 중 택1] 매수사유 및 행동근거 | [상승조건] 팩트 (200자 이내) | [손절조건] 악재수치 (200자 이내)
    """
    return generate_text(prompt)

def check_fundamental_damage(ticker, stock_name, chart_30d, macro, valuation, theme_context):
    prompt = f"""
    투자 훼손 여부 진단. 모바일 가독성을 위해 짧게 작성.
    종목: {stock_name}({ticker}) | 매수이유: {theme_context} | 뉴스: {valuation}
    
    파괴 시 [펀더멘털훼손], 유지 시 [보유유지]를 서두에 적고 2문장 내외로 설명.
    """
    return generate_text(prompt)

def match_naver_themes(keyword, theme_list):
    prompt = f"키워드 '{keyword}'와 일치하는 네이버 공식 테마를 아래 목록에서 최대 3개 골라 쉼표로 나열.\n{', '.join(theme_list)}"
    res = generate_text(prompt)
    return [t for t in [x.strip() for x in res.split(',')] if t in theme_list]

def get_quick_rating(ticker, name, news_text, strategy_type, val):
    prompt = f"""
    스마트폰 가독성을 위해 아주 짧고 명확하게 5단계 등급과 이유를 판정하세요.
    종목: {name} / 전략: {strategy_type} / 재무: PER {val.get('per')}, ROE {val.get('roe')}% / 뉴스: {news_text}
    
    [결과 양식] (반드시 아래 두 줄만 출력)
    등급: [매수추천 / 매수 / 관망 / 매수주의 / 매수반대 중 택 1]
    사유: [기사 및 재무 팩트 기반 1문장 요약]
    """
    return generate_text(prompt)

def get_dividend_risk_check(ticker, name, news_text, val):
    prompt = f"""
    배당주 컷 위험을 검증합니다. 스마트폰 가독성을 위해 아주 짧고 명확하게 출력하세요. 
    종목: {name} / 재무: PER {val.get('per')}, PBR {val.get('pbr')} / 뉴스: {news_text}
    
    [결과 양식] (반드시 아래 두 줄만 출력)
    등급: [매수추천 / 매수 / 관망 / 매수주의 / 매수반대 중 택 1]
    사유: [배당 삭감 위험성 유무 등 팩트 기반 1문장 요약]
    """
    return generate_text(prompt)
