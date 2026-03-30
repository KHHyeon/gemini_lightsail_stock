# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
import os, json, concurrent.futures, time, re
from google import genai
from dotenv import load_dotenv
import news_crawler
from slack_notifier import send_slack_alert

load_dotenv()
MODEL_NAME = os.getenv("AI_MODEL_NAME", "gemini-3-flash-preview")

def clean_text(text):
    if not text: return text
    return re.sub(r'[^\U00000000-\U0000FFFF]', '', text)

def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    return genai.Client(api_key=api_key) if api_key else None

def handle_ai_error(e, context=""):
    error_msg = str(e)
    if "429" in error_msg:
        alert = f"[AI API 접근 제한] 429 할당량 초과 발생. ({context})"
        send_slack_alert(alert)
        return alert
    elif "403" in error_msg:
        alert = f"[AI API 접근 제한] 403 권한 없음 또는 API 키 만료. ({context})"
        send_slack_alert(alert)
        return alert
    elif "400" in error_msg:
        return f"[AI API 에러] 400 안전 필터 차단. ({context})"
    else:
        return f"[AI Error] {context} 중 알 수 없는 오류: {error_msg[:50]}"

def infer_news_keywords():
    client = get_gemini_client()
    default_us, default_kr = "나스닥 마감", "코스피 시황"
    if not client: return default_us, default_kr
    
    system_instruction = """
    당신은 금융 뉴스 검색 전문가입니다.
    오늘 미국 증시와 한국 코스피의 전반적인 마감/시황을 파악하기 위한 구글 뉴스 검색어 2개를 도출하십시오.
    [출력 규칙] 반드시 "미국검색어|한국검색어" 형식으로만 출력하십시오. 검색어는 무조건 '2단어 이하'로. 이모지 금지.
    """
    try:
        res = client.models.generate_content(model=MODEL_NAME, contents="오늘 최적의 뉴스 검색어 2개를 추출해주세요.", config={'system_instruction': system_instruction})
        result = clean_text(res.text).strip()
        if "|" in result: return result.split("|", 1)[0].strip(), result.split("|", 1)[1].strip()
    except Exception as e:
        handle_ai_error(e, "검색어 추론")
    return default_us, default_kr

def get_trending_themes():
    client = get_gemini_client()
    if not client: return "AI 반도체, K-뷰티"
    system_instruction = "당신은 한국 주식시장 트렌드 분석가입니다. 최근 가장 자금이 몰리고 있는 주도 테마(섹터) 2~3가지를 콤마로 구분하여 단어로만 답변하십시오. 이모지 및 부가설명 절대 금지."
    try:
        res = client.models.generate_content(model=MODEL_NAME, contents="현재 강력하게 상승중인 테마 2~3개 추출", config={'system_instruction': system_instruction})
        return clean_text(res.text).strip()
    except Exception as e:
        handle_ai_error(e, "주도 테마 추론")
        return "AI 반도체, 저PBR 밸류업"

def get_theme_universe(theme_keywords):
    client = get_gemini_client()
    if not client: return []
    system_instruction = f"""
    당신은 한국 주식시장 섹터 애널리스트입니다. 입력된 단일 테마 '{theme_keywords}'와 실질적으로 관련하여 비즈니스를 영위하는 한국 코스피/코스닥 상장사 15개를 선별하십시오.
    [출력 규칙] 반드시 JSON 배열 형식으로만 출력. 코드블록 금지. 이모지 금지.
    [ {{"name": "종목명", "ticker": "6자리숫자코드"}}, ... ]
    """
    try:
        res = client.models.generate_content(model=MODEL_NAME, contents=f"'{theme_keywords}' 관련 주식 15개 JSON 반환", config={'system_instruction': system_instruction})
        text = clean_text(res.text).replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        handle_ai_error(e, f"테마({theme_keywords}) 유니버스 생성")
        return []

def get_theme_stock_narrative(theme, stock_name, ticker, fundamentals):
    client = get_gemini_client()
    if not client: return "내러티브 분석 실패"
    system_instruction = f"""
    당신은 퀀트 펀드매니저입니다. 이 종목({stock_name})이 '{theme}' 테마와 어떤 관련이 있으며, 제공된 실적을 바탕으로 성장이 정당화되는지 3줄 이내로 핵심만 요약하십시오. 이모지 금지.
    """
    try:
        res = client.models.generate_content(model=MODEL_NAME, contents=f"재무데이터: {json.dumps(fundamentals, ensure_ascii=False)}", config={'system_instruction': system_instruction})
        return clean_text(res.text).strip()
    except Exception as e:
        return handle_ai_error(e, f"{stock_name} 내러티브 생성")

def get_ai_investment_report(ticker, stock_name, chart_30d, macro, paper_portfolio, valuation, theme_context=""):
    client = get_gemini_client()
    if not client: return "[Error] API 키 누락."
    
    latest_news = news_crawler.get_latest_news(stock_name, limit=5)
    news_summary = "\n".join([f"- {news}" for news in latest_news]) if latest_news else "뉴스 데이터 없음"
    chart_summary = "차트 데이터 없음"
    if chart_30d and len(chart_30d) > 0:
        start_price, end_price = chart_30d[0]['close'], chart_30d[-1]['close']
        pct = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
        chart_summary = f"- 시작가: {start_price:,}원 -> 현재가: {end_price:,}원 (수익률: {pct:+.2f}%)"
    
    system_instruction = "당신은 팩트 기반 수석 퀀트 개발자입니다. [출력 규칙] 1. 첫 줄은 '[한줄요약] '으로 압축. 2. '[핵심 논리] '. 이모지 절대 금지."
    narrative_injection = f"\n[사전 테마 진단 리포트 (중요 검토 대상)]\n{theme_context}\n" if theme_context else ""
    user_prompt = f"분석 대상 종목: {stock_name} ({ticker}){narrative_injection}\n[지표]\n{valuation}\n[뉴스]\n{news_summary}\n[차트]\n{chart_summary}\n[매크로]\n{macro}"
    
    try:
        res = client.models.generate_content(model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction})
        return clean_text(res.text)
    except Exception as e:
        return handle_ai_error(e, f"{stock_name} 종목 분석 리포트")

def get_daily_market_report(macro, us_news, kr_news, disclosures):
    client = get_gemini_client()
    if not client: return "API 에러"
    us_news_str = "\n".join([f"- {n}" for n in us_news]) if us_news else "[주의] 오늘 수집된 미국 관련 최신 뉴스가 없습니다."
    kr_news_str = "\n".join([f"- {n}" for n in kr_news]) if kr_news else "[주의] 오늘 수집된 한국 관련 최신 뉴스가 없습니다."
    system_instruction = "수석 퀀트 애널리스트. 뉴스가 없다면 지어내지 말고 팩트만 명시하십시오. 이모지 금지."
    user_prompt = f"[매크로]\n{macro}\n[미국뉴스]\n{us_news_str}\n[한국뉴스]\n{kr_news_str}\n[공시]\n{disclosures}"
    try:
        return clean_text(client.models.generate_content(model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}).text)
    except Exception as e:
        return handle_ai_error(e, "일일 시장 브리핑")

def get_weekly_portfolio_report(portfolio_details, news_dict):
    client = get_gemini_client()
    if not client: return "API 에러"
    system_instruction = "당신은 퀀트 펀드매니저입니다. 포트폴리오 진단. 이모지 금지."
    user_prompt = f"포트폴리오: {portfolio_details}\n뉴스: {news_dict}"
    try:
        return clean_text(client.models.generate_content(model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}).text)
    except Exception as e:
        return handle_ai_error(e, "주간 브리핑")

def get_monthly_portfolio_report(portfolio_details, news_dict):
    client = get_gemini_client()
    if not client: return "API 에러"
    system_instruction = "당신은 수석 펀드매니저입니다. 월간 리포트 작성. 이모지 금지."
    user_prompt = f"포트폴리오: {portfolio_details}\n월간 주요 뉴스: {news_dict}"
    try:
        return clean_text(client.models.generate_content(model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}).text)
    except Exception as e:
        return handle_ai_error(e, "월간 브리핑")

def get_quarterly_portfolio_report(portfolio_details, news_dict):
    client = get_gemini_client()
    if not client: return "API 에러"
    system_instruction = "당신은 헤지펀드 총괄 책임자입니다. 분기 리포트 작성. 이모지 금지."
    user_prompt = f"포트폴리오: {portfolio_details}\n분기 주요 뉴스: {news_dict}"
    try:
        return clean_text(client.models.generate_content(model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}).text)
    except Exception as e:
        return handle_ai_error(e, "분기 브리핑")
