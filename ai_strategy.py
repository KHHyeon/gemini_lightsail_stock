# -*- coding: utf-8 -*-
# File: ~/my_bot/ai_strategy.py
import os
import json
import concurrent.futures
import time
import re
from google import genai
from dotenv import load_dotenv
import news_crawler

load_dotenv()

# .env에서 모델명을 동적으로 불러옵니다. (기본값: flash)
MODEL_NAME = os.getenv("AI_MODEL_NAME", "gemini-3-flash-preview")

def clean_text(text):
    if not text: return text
    return re.sub(r'[^\U00000000-\U0000FFFF]', '', text)

def infer_news_keywords():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return "미국 나스닥 빅테크 시황", "한국 코스피 시총상위 시황"
    
    client = genai.Client(api_key=api_key)
    system_instruction = """
    당신은 금융 뉴스 검색 전문가입니다.
    오늘의 '미국 빅테크 주가'와 '한국 코스피 시총 상위주'의 변동 사유를 파악하기 위해, 구글 뉴스에 검색할 가장 직관적이고 포괄적인 검색어 2개를 도출하십시오.
    [출력 규칙] 반드시 "미국검색어|한국검색어" 형식으로만 출력하십시오. (예: 미국 나스닥 빅테크 시황|한국 코스피 대형주 시황)
    이모지나 부연 설명은 절대 금지합니다.
    """
    
    def call_gemini():
        return client.models.generate_content(
            model=MODEL_NAME, contents="오늘 최적의 뉴스 검색어 2개를 추출해주세요.", config={'system_instruction': system_instruction}
        )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_gemini)
        try:
            result = clean_text(future.result(timeout=15).text).strip()
            if "|" in result:
                us_kw, kr_kw = result.split("|", 1)
                return us_kw.strip(), kr_kw.strip()
        except Exception as e:
            print(f"Log: [AI Keyword Error] {str(e)}", flush=True)
            pass
            
    return "미국 나스닥 빅테크 시황", "한국 코스피 시총상위 시황"

def get_ai_investment_report(ticker, stock_name, chart_30d, macro, paper_portfolio, valuation):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return "Log: [Error] API 키 누락."
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
    
    system_instruction = """
    당신은 100% 수치와 팩트 기반으로 판단하는 수석 퀀트 개발자입니다.
    제공된 뉴스 헤드라인, 차트 요약, 밸류에이션(배당률 포함), 매크로 지표를 종합하여 분석하십시오.
    [출력 규칙]
    1. 맨 첫 줄은 반드시 "[한줄요약] "으로 시작하여, 핵심 사유를 30자 이내로 압축할 것.
    2. 그 다음 줄부터 "[핵심 논리] "를 작성할 것.
    3. Section 1 (펀더멘털 & 뉴스 센티먼트) 작성.
    4. Section 2 (매매 및 리스크 관리) 작성.
    5. Section 3 (치명적인 반대 근거 2가지) 작성.
    6. [중요] 인코딩 에러를 유발하므로 이모지(Emoji) 및 특수기호는 절대 사용하지 말고 순수 텍스트로만 작성할 것.
    """

    user_prompt = f"""
    분석 대상 종목: {stock_name} ({ticker})
    [실시간 투자 지표 (Valuation & 배당)]\n{json.dumps(valuation, ensure_ascii=False) if valuation else '데이터 없음'}
    [실시간 뉴스 센티먼트]\n{news_summary}
    [시장 데이터 (차트 요약)]\n{chart_summary}
    [거시 경제 지표 (Macro)]\n{json.dumps(macro, ensure_ascii=False) if macro else '데이터 없음'}
    [내 잔고 상황]\n{json.dumps(paper_portfolio.get(ticker, '미보유 종목'), ensure_ascii=False)}
    """

    def call_gemini():
        return client.models.generate_content(
            model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}
        )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_gemini)
        try:
            return clean_text(future.result(timeout=60).text)
        except concurrent.futures.TimeoutError:
            return "[AI Error] 서버 60초 초과 타임아웃 (응답 지연)."
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                return "[경고] [AI 접근 제한] 429 할당량 초과 (Rate Limit). API 호출 한도를 다 썼습니다."
            elif "403" in error_msg:
                return "[경고] [AI 접근 제한] 403 권한 없음 (API 키 오류 또는 차단됨)."
            elif "400" in error_msg:
                return "[경고] [AI 접근 제한] 400 안전 필터 차단 (정책 위반 단어 포함)."
            else:
                return f"[AI Error] 알 수 없는 오류: {error_msg}"

def get_daily_market_report(macro, us_news, kr_news, disclosures):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return "API 키가 누락되었습니다."
    client = genai.Client(api_key=api_key)
    
    us_news_str = "\n".join([f"- {n}" for n in us_news]) if us_news else "관련 뉴스 없음"
    kr_news_str = "\n".join([f"- {n}" for n in kr_news]) if kr_news else "관련 뉴스 없음"
    
    system_instruction = """
    당신은 펀드 매니저에게 매일 아침 브리핑을 제공하는 수석 매크로/퀀트 애널리스트입니다.
    
    [출력 포맷]
    *[글로벌 매크로 점검]*
    - 환율, 10년물 금리 마감가, 유가 수치와 시장 상/하방 압력 요약.
    *[빅테크 & 시총상위 변동 사유]*
    - 주가 변동 핵심 사유 요약.
    *[보유 종목 공시 확인]*
    - DART 공시 호재/악재 분석.
    
    [중요] 인코딩 에러를 피하기 위해 이모지(Emoji) 및 특수문자는 절대 사용하지 마십시오.
    """

    user_prompt = f"""
    [거시 경제 마감 지표]\n{json.dumps(macro, ensure_ascii=False)}
    [미국 빅테크 동향 뉴스]\n{us_news_str}
    [한국 코스피 시총상위 동향 뉴스]\n{kr_news_str}
    [보유 종목 최근 24시간 DART 공시]\n{json.dumps(disclosures, ensure_ascii=False)}
    """

    def call_gemini():
        return client.models.generate_content(
            model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}
        )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_gemini)
        try:
            return clean_text(future.result(timeout=45).text)
        except concurrent.futures.TimeoutError:
            return "[AI Error] 일일 시황 분석 타임아웃 (서버 응답 지연)."
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                return "[경고] [AI 접근 제한] 429 할당량 초과 (Rate Limit)."
            elif "403" in error_msg:
                return "[경고] [AI 접근 제한] 403 권한 없음 (API 키 오류 또는 차단됨)."
            elif "400" in error_msg:
                return "[경고] [AI 접근 제한] 400 안전 필터 차단."
            else:
                return f"[AI Error] 알 수 없는 오류: {error_msg}"

def get_weekly_portfolio_report(portfolio_details, news_dict):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key: return "API 키가 누락되었습니다."
    client = genai.Client(api_key=api_key)

    system_instruction = """
    당신은 퀀트 포트폴리오 매니저입니다.
    
    [핵심 미션]
    1. 각 종목별로 주가 변동 이유를 최신 뉴스와 결합하여 진단.
    2. 최초 매수 사유(투자 아이디어)의 유효성 평가.
    
    [중요] 인코딩 에러를 피하기 위해 이모지(Emoji) 및 특수문자는 절대 사용하지 마십시오.
    """
    
    user_prompt = f"[포트폴리오 현황 (수익률 및 최초 매수 사유)]\n{json.dumps(portfolio_details, ensure_ascii=False)}\n\n[보유 종목 주간 뉴스 센티먼트]\n{json.dumps(news_dict, ensure_ascii=False)}"

    def call_gemini():
        return client.models.generate_content(
            model=MODEL_NAME, contents=user_prompt, config={'system_instruction': system_instruction}
        )

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(call_gemini)
        try:
            return clean_text(future.result(timeout=60).text)
        except concurrent.futures.TimeoutError:
            return "[AI Error] 주간 포트폴리오 분석 타임아웃."
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg:
                return "[경고] [AI 접근 제한] 429 할당량 초과 (Rate Limit)."
            elif "403" in error_msg:
                return "[경고] [AI 접근 제한] 403 권한 없음."
            elif "400" in error_msg:
                return "[경고] [AI 접근 제한] 400 안전 필터 차단."
            else:
                return f"[AI Error] 알 수 없는 오류: {error_msg}"
