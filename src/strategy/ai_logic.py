# -*- coding: utf-8 -*-
import os
import re

from google import genai

from src.utils import macro_triggers as _mt

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


def generate_text_with_chronicle(prompt, macro=None, news_snippets=None, model_name=None):
    """Market Chronicles Context Injection 후 Gemini 호출.

    v3.4: extract_market_context 가 dict (context_tags_list / regime /
    main_actor_keyword / sentiment / phrases_list) 를 반환한다.
    build_context_injection_block 에 dict 그대로 전달하여 3블록 압축 출력을 받는다.
    """
    try:
        from src.memory.context_retriever import build_context_injection_block, extract_market_context

        if macro is not None:
            query_dict = extract_market_context(macro, news_snippets)
            block = build_context_injection_block(query_dict)
            if block:
                prompt = f"{block}\n\n{prompt}"
    except Exception as e:
        print(f"Log: [Chronicles Inject Skip] {e}")
    return generate_text(prompt, model_name)

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
    news_snippets = list(us_news or []) + list(kr_news or [])
    return generate_text_with_chronicle(prompt, macro=macro, news_snippets=news_snippets)

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
    return generate_text_with_chronicle(prompt, macro=macro, news_snippets=kr_news)

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


def build_theme_context_entry(ticker, name, target_theme, score, score_details, val):
    """`theme_context.json[ticker]` 값을 단일 규칙으로 생성한다.

    `!ai매수`, `!수동등록`, `!발굴` 세 진입점이 모두 본 함수를 사용해야 한다.

    Args:
        ticker: 종목코드.
        name: 종목명.
        target_theme: 테마명 또는 진입점별 폴백 라벨.
        score: 펀더멘털 점수(int).
        score_details: 점수 내역 리스트 (예: ["차트 정배열(+20)", ...]).
        val: 재무 데이터 dict (``pbr``, ``per`` 등 키 사용).

    Returns:
        str: ``"[테마: {target_theme} | 총점: {score}]\\n{narrative}"`` 포맷.
    """
    details_text = ", ".join(score_details) if score_details else ""
    fundamentals = {
        "score": score,
        "details": details_text,
        "pbr": val.get("pbr") if isinstance(val, dict) else None,
        "per": val.get("per") if isinstance(val, dict) else None,
    }
    narrative = get_theme_stock_narrative(target_theme, name, ticker, fundamentals)
    return f"[테마: {target_theme} | 총점: {score}]\n{narrative}"


def register_theme_context(ticker, name, target_theme, score, score_details, val):
    """`build_theme_context_entry` 결과를 `theme_context.json` 에 저장하고 반환한다.

    저장 실패(드라이브 연결 끊김 등)는 상위에서 처리한다.
    """
    from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive

    entry = build_theme_context_entry(
        ticker, name, target_theme, score, score_details, val
    )
    theme_memory = load_json_from_gdrive("theme_context.json") or {}
    theme_memory[ticker] = entry
    save_json_to_gdrive(theme_memory, "theme_context.json")
    return entry


def review_opinion_with_ai(ticker, name, score, code_label, val, news, theme_context):
    """코드가 산출한 의견 라벨에 대한 AI sanity 검토.

    LLM 은 의견 라벨을 재선택할 수 없으며, ``±1`` 단계 보정 제안만 입력으로 사용된다.

    Returns:
        dict: ``{"delta": int (-1|0|+1), "reason": str}``. 파싱 실패 시 delta=0.
    """
    prompt = (
        "[에이전트: 펀더멘털 검토관]\n"
        f"종목: {name}({ticker}) | 코드 산출 점수: {score} | 코드 산출 의견: {code_label}\n"
        f"재무: {val}\n"
        f"테마 맥락: {theme_context}\n"
        f"뉴스/공시: {news}\n\n"
        "코드가 산출한 의견 라벨의 타당성을 검토하세요. 반드시 아래 두 줄만 출력:\n"
        "1줄: [유지] / [+1] / [-1] 중 1개 (의견 라벨 변경 폭은 ±1단계 이내)\n"
        "2줄: 사유 1문장"
    )
    res = generate_text(prompt) or ""
    lines = [ln.strip() for ln in res.strip().splitlines() if ln.strip()]
    head = lines[0] if lines else ""
    reason = lines[1] if len(lines) > 1 else ""

    if "+1" in head:
        delta = 1
    elif "-1" in head:
        delta = -1
    else:
        delta = 0

    return {"delta": delta, "reason": reason or head}


def _extract_section(report_text, head_label):
    """LLM 본문 리포트에서 단일 라벨 줄을 추출한다.

    예) ``head_label="[근거]"`` 이면 ``"[근거] ... "`` 라인의 ``...`` 만 반환.
    추출 실패 시 ``"(자동 추출 실패)"`` 반환.
    """
    if not report_text:
        return "(자동 추출 실패)"
    pat = re.compile(
        rf"{re.escape(head_label)}\s*(.+?)(?=\n\[|\n\n|$)",
        re.DOTALL,
    )
    m = pat.search(report_text)
    if not m:
        return "(자동 추출 실패)"
    return m.group(1).strip().splitlines()[0].strip() or "(자동 추출 실패)"

def get_emergency_news_check(name, news_text):
    prompt = f"""
    [긴급 팩트체크] 
    종목 '{name}'의 최신 뉴스입니다: {news_text}
    위 뉴스 내용 중 횡령, 배임, 대규모 유상증자, 어닝쇼크 등 치명적인 돌발 악재가 존재합니까?
    치명적 악재가 있다면 [위험], 없다면 [통과]라고 첫 줄에 반드시 명시하고 1문장으로 이유를 적어주세요.
    """
    return generate_text(prompt)

def get_multi_agent_investment_report(
    ticker, stock_name, chart_30d, macro, pf, valuation, theme_context, recent_news,
    *, fundamental_score, fundamental_details=None
):
    """멀티 에이전트 투자 리포트. v3.5 부터 의견 라벨은 코드가 결정한다.

    - 코드: ``derive_opinion_from_score(fundamental_score)`` → ``opinion_code``
    - AI 검토: ``review_opinion_with_ai`` → ``delta`` (±1 단계 이내)
    - 코드: ``adjust_opinion_label(opinion_code, delta)`` → ``opinion_final``
    - LLM: 분석가/리스크 의견 + 근거/상승/손절 텍스트만 생성.
    - 코드: ``[한줄요약]`` 라인 직접 조립.

    Returns:
        tuple[str, dict]: ``(report_text, meta)``.
            ``meta`` 키: ``score``, ``opinion_code``, ``opinion_final``,
            ``opinion_delta``, ``ai_review_reason``.
    """
    opinion_code = _mt.derive_opinion_from_score(fundamental_score)
    review = review_opinion_with_ai(
        ticker, stock_name, fundamental_score, opinion_code,
        valuation, recent_news, theme_context,
    )
    delta = int(review.get("delta", 0) or 0)
    opinion_final = _mt.adjust_opinion_label(opinion_code, delta)

    base_prompt = f"""
    [에이전트: 데이터 분석가]
    종목: {stock_name}({ticker}) | 재무데이터: {valuation} | 뉴스/공시: {recent_news}

    위 데이터를 바탕으로 다음 두 섹션을 아주 간결한 개조식으로 작성하세요:
    1. [ 재무현황 ]: PER, PBR, ROE 및 주요 재무 건전성 요약
    2. [ 최신이슈분석 ]: 최근 뉴스 및 공시 중 핵심 모멘텀 또는 리스크
    """
    base_analysis = generate_text(base_prompt)

    analyst_prompt = f"""
    [에이전트: 성장주 전문 분석가]
    기초분석: {base_analysis}
    테마맥락: {theme_context} | 차트: {chart_30d}

    위 데이터를 바탕으로 이 종목의 강력한 매수 논리(분석가 의견)를 2~3줄 내외로 작성하세요.
    """
    analyst_opinion = generate_text(analyst_prompt)

    risk_prompt = f"""
    [에이전트: 악마의 대변인 (리스크 관리자)]
    분석가 의견: {analyst_opinion}
    재무/이슈: {base_analysis}

    분석가의 논리를 반박하고, 투자자가 반드시 경계해야 할 핵심 리스크를 2~3줄 내외로 작성하세요.
    """
    risk_opinion = generate_text(risk_prompt)

    details_text = ", ".join(fundamental_details) if fundamental_details else ""
    final_prompt = f"""
    [에이전트: 투자심의위원회]
    종목: {stock_name}({ticker})
    펀더멘털 점수: {fundamental_score} ({details_text})
    시스템 확정 의견: {opinion_final} (코드 산출 {opinion_code}, AI 보정 {delta:+d})
    데이터: {base_analysis}
    의견: 분석가({analyst_opinion}), 리스크관리자({risk_opinion})

    아래 양식에 맞춰 최종 리포트를 작성하세요.
    의견 라벨은 시스템이 [{opinion_final}] 로 확정했으니 라벨을 재선택하지 마세요.
    LLM 은 '근거 설명 / 상승 조건 / 손절 조건' 세 항목 텍스트만 생성합니다.

    [출력 양식]
    {base_analysis}

    [ 핵심요약 ]
    - (분석가와 리스크 관리자의 의견을 종합한 1줄 핵심 포인트)

    [ 분석가 의견 ]
    - {analyst_opinion}

    [ 리스크 관리자 반박 ]
    - {risk_opinion}

    [근거] (밸류에이션/성장성/이슈를 통합한 1~2문장 설명)
    [상승조건] (상승 시나리오 1줄)
    [손절조건] (손절 트리거 1줄)
    """
    news_flat = recent_news if isinstance(recent_news, list) else [str(recent_news)]
    body = generate_text_with_chronicle(final_prompt, macro=macro, news_snippets=news_flat)

    rationale = _extract_section(body, "[근거]")
    upside = _extract_section(body, "[상승조건]")
    downside = _extract_section(body, "[손절조건]")

    summary_line = (
        f"[한줄요약] [의견: {opinion_final}] | "
        f"[점수: {fundamental_score} ({opinion_code} → 보정 {delta:+d})] | "
        f"[근거] {rationale} | [상승조건] {upside} | [손절조건] {downside}"
    )

    cleaned_body = re.sub(r"\[한줄요약\].*$", "", body or "", flags=re.DOTALL).rstrip()
    full_report = f"{cleaned_body}\n\n{summary_line}"
    meta = {
        "score": fundamental_score,
        "opinion_code": opinion_code,
        "opinion_final": opinion_final,
        "opinion_delta": delta,
        "ai_review_reason": review.get("reason", ""),
    }
    return full_report, meta

def check_fundamental_damage(ticker, stock_name, chart_30d, macro, valuation, theme_context):
    prompt = f"""
    투자 훼손 여부 진단. 모바일 가독성을 위해 짧게 작성.
    종목: {stock_name}({ticker}) | 매수이유: {theme_context} | 뉴스: {valuation}
    
    파괴 시 [펀더멘털훼손], 유지 시 [보유유지]를 서두에 적고 2문장 내외로 설명.
    """
    return generate_text(prompt)

def get_sudden_bad_news(ticker, stock_name, recent_news):
    prompt = f"""
    [에이전트: 치명적 악재 스캐너]
    종목: {stock_name}({ticker}) | 최근뉴스: {recent_news}
    
    위 뉴스/공시 목록을 텍스트 마이닝하여 다음 항목 중 하나라도 해당하는지 판단하세요:
    - 상장폐지 사유 발생, 관리종목 지정 우려
    - 횡령 및 배임 (경영진 관련)
    - 감사의견 거절 또는 부적정
    - 대규모 유상증자 (제3자 배정 제외)
    - 임상 실패 (바이오 섹터인 경우)
    - 어닝 쇼크 (시장 기대치 30% 이상 하회)
    
    위와 같은 '치명적인 돌발 악재'가 있다면 반드시 [위험] 이라고 적고 이유를 1줄로 설명하세요.
    해당사항이 없거나 통상적인 변동이라면 [안전] 이라고만 적으세요.
    """
    return generate_text(prompt)


def match_naver_themes(keyword, theme_list):
    prompt = f"키워드 '{keyword}'와 일치하는 네이버 공식 테마를 아래 목록에서 최대 3개 골라 쉼표로 나열.\n{', '.join(theme_list)}"
    res = generate_text(prompt)
    return [t for t in [x.strip() for x in res.split(',')] if t in theme_list]

def get_quick_rating(ticker, name, news_text, strategy_type, val, macro=None):
    prompt = f"""
    스마트폰 가독성을 위해 아주 짧고 명확하게 5단계 등급과 이유를 판정하세요.
    종목: {name} / 전략: {strategy_type} / 재무: PER {val.get('per')}, ROE {val.get('roe')}% / 뉴스: {news_text}
    
    [결과 양식] (반드시 아래 두 줄만 출력)
    등급: [매수추천 / 매수 / 관망 / 매수주의 / 매수반대 중 택 1]
    사유: [기사 및 재무 팩트 기반 1문장 요약]
    """
    snippets = [news_text] if isinstance(news_text, str) else list(news_text or [])
    if macro is None:
        from src.data import collector
        macro = collector.get_macro_indicators()
    return generate_text_with_chronicle(prompt, macro=macro, news_snippets=snippets)

def get_dividend_risk_check(ticker, name, news_text, val, macro=None):
    prompt = f"""
    배당주 컷 위험을 검증합니다. 스마트폰 가독성을 위해 아주 짧고 명확하게 출력하세요. 
    종목: {name} / 재무: PER {val.get('per')}, PBR {val.get('pbr')} / 뉴스: {news_text}
    
    [결과 양식] (반드시 아래 두 줄만 출력)
    등급: [매수추천 / 매수 / 관망 / 매수주의 / 매수반대 중 택 1]
    사유: [배당 삭감 위험성 유무 등 팩트 기반 1문장 요약]
    """
    if macro is None:
        from src.data import collector
        macro = collector.get_macro_indicators()
    snippets = [news_text] if isinstance(news_text, str) else list(news_text or [])
    return generate_text_with_chronicle(prompt, macro=macro, news_snippets=snippets)
