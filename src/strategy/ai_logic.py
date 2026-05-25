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


# 정성적 가중치 판단 모호 시 폴백 사유 상수 (운영 로깅 일관성 확보)
FALLBACK_REASON_AMBIGUOUS = "AI 가중치 판단 모호 - 국내 펀더멘털 점수 우선 반영"


def review_opinion_with_ai(
    ticker, name, score, code_label, val, news, theme_context,
    *, telegram_insight_list=None, domestic_news_list=None,
    max_abs_delta=None,
):
    """코드가 산출한 의견 라벨에 대한 AI sanity 검토 + 정성적 가중치 평가.

    LLM 은 의견 라벨을 재선택하지 못하며, ±max_abs_delta 단계(기본 ±2) 보정만
    제안한다. 텔레그램 해외 변수와 국내 뉴스 변수가 동시 주입될 때, 종목
    비즈니스 모델(수출주/내수주/기술주 등)에 맞춰 두 변수 사이의 정성적
    가중치를 비교하여 delta 산출의 핵심 근거로 사용한다.

    분석보류(score=None 또는 code_label==OPINION_LABEL_HOLD) 인 경우 AI 호출을
    스킵하고 ``delta=0`` 으로 반환한다 — 보류 라벨은 보정 대상이 아니다.

    [폴백 정책]
    - AI 응답 파싱 실패/타임아웃/모호한 경우 → ``delta=0`` + FALLBACK_REASON_AMBIGUOUS.
    - ±2 토큰은 강한 정성적 근거가 있을 때만 사용. 명확하지 않으면 [유지].

    Args:
        ticker/name/score/code_label/val/news/theme_context: 기존 sanity 인자.
        telegram_insight_list: 텔레그램 파이프라인 dict 리스트.
        domestic_news_list: 국내 시황/뉴스 dict 리스트.
        max_abs_delta: 보정 폭 최대 절대값. ``None`` 이면 ``_mt.MAX_OPINION_DELTA``.

    Returns:
        dict: {"delta": int, "reason": str}
    """
    if max_abs_delta is None:
        max_abs_delta = getattr(_mt, "MAX_OPINION_DELTA", 2)
    try:
        max_abs_delta = int(max_abs_delta)
    except (TypeError, ValueError):
        max_abs_delta = 2
    max_abs_delta = max(1, min(max_abs_delta, 4))

    # 분석보류 라벨은 보정 대상이 아니다 — AI 호출 자체를 스킵하여 토큰 절약.
    if code_label == getattr(_mt, "OPINION_LABEL_HOLD", "분석보류") or score is None:
        return {"delta": 0, "reason": "분석보류 - AI 보정 미적용"}

    telegram_block = _format_external_context_block(
        telegram_insight_list, head_label="[해외 변수 (텔레그램)]"
    )
    domestic_block = _format_external_context_block(
        domestic_news_list, head_label="[국내 변수 (뉴스/수급)]"
    )

    if max_abs_delta >= 2:
        token_guide = (
            "4) 의견 라벨 변경 폭은 ±2단계 이내. 기본은 ±1, ±2 는 강한 정성적 근거"
            "(어닝 쇼크/패러다임 전환/임상 실패 등)에 한해 사용한다.\n"
        )
        token_set = "[유지] / [+1] / [-1] / [+2] / [-2]"
    else:
        token_guide = "4) 의견 라벨 변경 폭은 ±1단계 이내로 제한된다.\n"
        token_set = "[유지] / [+1] / [-1]"

    prompt = (
        "[에이전트: 정성적 가중치 검토관]\n"
        f"종목: {name}({ticker}) | 코드 산출 점수: {score} | 코드 산출 의견: {code_label}\n"
        f"재무: {val}\n"
        f"테마 맥락: {theme_context}\n"
        f"단신 뉴스/공시: {news}\n"
        f"{telegram_block}\n"
        f"{domestic_block}\n\n"
        "[지시]\n"
        "1) 위 데이터에는 텔레그램(해외 글로벌 리더/매크로 전이)과 국내 뉴스(수급/섹터)가 동시 주입될 수 있다.\n"
        "2) 대상 종목의 비즈니스 모델 특성(수출주/내수주/기술주/금융주 등)에 맞춰 두 변수의 정성적 가중치를 비교하라.\n"
        "3) 상충 시(예: 해외 호재 vs 국내 악재) 가중치가 높은 쪽을 따라 delta 를 결정하라.\n"
        f"{token_guide}"
        "5) 명확한 가중치 비교 결론을 낼 수 없으면 반드시 [유지] 를 선택하라.\n\n"
        "[출력 형식 - 반드시 아래 두 줄만 출력]\n"
        f"1줄: {token_set} 중 1개\n"
        "2줄: 정성적 가중치 비교 결론이 포함된 사유 1문장"
    )

    try:
        res = generate_text(prompt) or ""
    except Exception as exc:
        print(f"Log: [ReviewOpinion] AI 호출 캡슐화: {exc}")
        return {"delta": 0, "reason": FALLBACK_REASON_AMBIGUOUS}

    lines = [ln.strip() for ln in res.strip().splitlines() if ln.strip()]
    head = lines[0] if lines else ""
    reason = lines[1] if len(lines) > 1 else ""

    if _is_ambiguous_response(res, head):
        print(f"Log: [ReviewOpinion] 모호 응답 폴백 (raw={res[:80]!r})")
        return {"delta": 0, "reason": FALLBACK_REASON_AMBIGUOUS}

    # ±2/±1 토큰 순으로 우선 매칭 (큰 값 우선 — '+2' 가 '+1' 보다 먼저 매칭).
    if "+2" in head and max_abs_delta >= 2:
        delta = 2
    elif "-2" in head and max_abs_delta >= 2:
        delta = -2
    elif "+1" in head:
        delta = 1
    elif "-1" in head:
        delta = -1
    elif "유지" in head:
        delta = 0
    else:
        print(f"Log: [ReviewOpinion] 정규식 미일치 폴백 (head={head!r})")
        return {"delta": 0, "reason": FALLBACK_REASON_AMBIGUOUS}

    # 안전 클램프 — 모델이 가이드를 무시하고 ±2 를 사용한 경우 대비.
    if delta > max_abs_delta:
        delta = max_abs_delta
    elif delta < -max_abs_delta:
        delta = -max_abs_delta

    return {"delta": delta, "reason": reason or head}


def _format_external_context_block(insight_list, *, head_label):
    """외부 파이프라인 인사이트 리스트를 프롬프트 블록 문자열로 압축한다.

    토큰 효율을 위해 항목당 1줄(category, related_kr_tickers, transmission_path)만
    노출한다. 비어 있으면 헤더만 반환한다.
    """
    if not insight_list:
        return f"{head_label} (없음)"

    line_list = [head_label]
    for idx, item in enumerate(insight_list, start=1):
        if not isinstance(item, dict):
            continue
        analysis = item.get("analysis") or {}
        category = analysis.get("category") or item.get("category", "")
        related_list = analysis.get("related_kr_tickers") or item.get("related_kr_tickers", [])
        path = analysis.get("transmission_path") or item.get("transmission_path", "")
        text = (item.get("text") or "")[:120]
        line_list.append(
            f"  - #{idx} ({category}) related={related_list} path={path} | text={text}"
        )
    return "\n".join(line_list) if len(line_list) > 1 else f"{head_label} (없음)"


_AMBIGUOUS_KEYWORD_LIST = [
    "판단 보류", "판단보류", "보류", "추가 정보 필요", "정보 부족",
    "불확실", "결정 불가", "확정 불가", "ambiguous", "uncertain",
    "ai 설정 오류", "ai 리포트 생성 실패",
]


def _is_ambiguous_response(raw_text, head):
    """AI 응답이 명백히 모호하거나 시스템 에러 토큰을 포함하는지 판정."""
    if not raw_text or not raw_text.strip():
        return True
    lowered = raw_text.lower()
    for kw in _AMBIGUOUS_KEYWORD_LIST:
        if kw in lowered:
            return True
    # head 라인에 결정 토큰(유지/+1/-1/+2/-2)이 전혀 없는 경우도 모호로 간주.
    if not any(token in head for token in ["유지", "+1", "-1", "+2", "-2"]):
        # 결정 토큰 없음 -> 호출자에서 정규식 미일치 폴백 경로로 처리하도록 False 반환.
        return False
    return False


def analyze_value_chain(symbol, context_text, *, sector_hint=None):
    """해외 글로벌 리더 종목 -> 국내 밸류체인(Supplier/Rival/Client) 맵핑.

    상태 비저장(stateless) AI 헬퍼. 텔레그램 파이프라인 정규화 단계에서 호출된다.
    AI 미설정 / 호출 실패 / 파싱 실패 시 빈 결과를 반환하며 예외를 던지지 않는다.

    Args:
        symbol: 해외 종목 식별자 (예: "NVDA", "TSLA", "TSMC").
        context_text: 메시지 본문(원문 또는 핵심 요약).
        sector_hint: 섹터 힌트(있으면 정확도 향상).

    Returns:
        dict:
            - related_kr_tickers: list[str]  (국내 6자리 종목코드)
            - value_chain_type: "SUPPLIER" | "RIVAL" | "CLIENT" | None
            - rationale: str (간단 사유)
    """
    empty_result = {
        "related_kr_tickers": [],
        "value_chain_type": None,
        "rationale": "",
    }
    if not symbol or not context_text:
        return empty_result

    prompt = (
        "[에이전트: 글로벌 밸류체인 분석가]\n"
        f"해외 종목: {symbol}\n"
        f"섹터 힌트: {sector_hint or '(없음)'}\n"
        f"맥락 텍스트: {context_text[:600]}\n\n"
        "위 해외 종목과 직접 연관된 국내 상장 종목을 최대 3개까지 매핑하라.\n"
        "관계 유형은 다음 중 하나로 분류한다: SUPPLIER(공급망), RIVAL(경쟁사), CLIENT(전방산업/고객).\n\n"
        "[출력 형식 - 반드시 아래 세 줄만 출력, 다른 텍스트 금지]\n"
        "1줄: TICKERS=종목코드1,종목코드2,종목코드3 (6자리 숫자만, 모르면 TICKERS=)\n"
        "2줄: RELATION=SUPPLIER 또는 RIVAL 또는 CLIENT 또는 NONE\n"
        "3줄: REASON=1문장 사유"
    )

    try:
        raw = generate_text(prompt) or ""
    except Exception as exc:
        print(f"Log: [ValueChain] AI 호출 캡슐화: {exc}")
        return empty_result

    if not raw or "AI 설정 오류" in raw or "AI 리포트 생성 실패" in raw:
        return empty_result

    tickers_match = re.search(r"TICKERS\s*=\s*([0-9,\s]*)", raw)
    relation_match = re.search(r"RELATION\s*=\s*([A-Z]+)", raw)
    reason_match = re.search(r"REASON\s*=\s*(.+)", raw)

    related_kr_tickers = []
    if tickers_match:
        for token in tickers_match.group(1).split(","):
            cleaned = re.sub(r"[^0-9]", "", token)
            if len(cleaned) == 6:
                related_kr_tickers.append(cleaned)
        # 중복 제거 + 순서 유지
        seen_set = set()
        dedup_list = []
        for t in related_kr_tickers:
            if t not in seen_set:
                seen_set.add(t)
                dedup_list.append(t)
        related_kr_tickers = dedup_list[:3]

    relation = (relation_match.group(1).strip().upper() if relation_match else "")
    value_chain_type = relation if relation in {"SUPPLIER", "RIVAL", "CLIENT"} else None

    rationale = reason_match.group(1).strip().splitlines()[0] if reason_match else ""

    return {
        "related_kr_tickers": related_kr_tickers,
        "value_chain_type": value_chain_type,
        "rationale": rationale,
    }


def extract_transmission_path(context_text, *, max_sentences=3):
    """해외 시황 -> 전이 매개체 -> 국내 섹터 수급 3단계 추론.

    상태 비저장(stateless) AI 헬퍼. 결과는 최대 max_sentences 문장의 단일 문자열.
    AI 실패 시 빈 문자열을 반환한다.
    """
    if not context_text:
        return ""

    prompt = (
        "[에이전트: 매크로 전이 분석가]\n"
        f"해외 시황 맥락: {context_text[:600]}\n\n"
        "위 해외 시황이 국내 증시에 미치는 영향을 다음 3단계 논리로 추론하라:\n"
        "  1) 현상(해외에서 벌어진 일)\n"
        "  2) 전이 매개체(환율/금리/원자재/심리 중 1~2가지)\n"
        "  3) 내일 국내 섹터 수급 전망\n\n"
        f"[출력 규약] 반드시 {max_sentences}문장 이내. 각 단계는 1문장씩. 다른 헤더/번호 없이 평문으로만 출력."
    )

    try:
        raw = generate_text(prompt) or ""
    except Exception as exc:
        print(f"Log: [TransmissionPath] AI 호출 캡슐화: {exc}")
        return ""

    if not raw or "AI 설정 오류" in raw or "AI 리포트 생성 실패" in raw:
        return ""

    # 문장 단위로 잘라서 max_sentences 제한.
    sentence_list = re.split(r"(?<=[\.!?\u3002])\s+", raw.strip())
    sentence_list = [s.strip() for s in sentence_list if s.strip()]
    return " ".join(sentence_list[:max_sentences])


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
    *, fundamental_score, fundamental_details=None,
    unscorable_reason=None, telegram_insights_list=None,
):
    """멀티 에이전트 투자 리포트. v1.3 (5축 GARP) 채점과 정합.

    - 코드: ``derive_opinion_from_score(fundamental_score)`` → ``opinion_code``
      (``score=None`` 이면 ``OPINION_LABEL_HOLD``)
    - AI 검토: ``review_opinion_with_ai`` → ``delta`` (±2 단계 이내).
      보류 라벨인 경우 AI 호출 스킵.
    - 코드: ``adjust_opinion_label(opinion_code, delta)`` → ``opinion_final``
    - LLM: 분석가/리스크 의견 + 근거/상승/손절 텍스트만 생성.
    - 코드: ``[한줄요약]`` 라인 직접 조립 (보류일 때 별도 양식).

    Returns:
        tuple[str, dict]: ``(report_text, meta)``.
            ``meta`` 키: ``score``, ``opinion_code``, ``opinion_final``,
            ``opinion_delta``, ``ai_review_reason``, ``unscorable_reason``.
    """
    opinion_code = _mt.derive_opinion_from_score(fundamental_score)
    review = review_opinion_with_ai(
        ticker, stock_name, fundamental_score, opinion_code,
        valuation, recent_news, theme_context,
        telegram_insight_list=telegram_insights_list,
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

    if opinion_code == getattr(_mt, "OPINION_LABEL_HOLD", "분석보류"):
        reason_tag = unscorable_reason or "데이터 부족"
        summary_line = (
            f"[한줄요약] [의견: {opinion_final} - {reason_tag}] | "
            f"[점수: N/A] | [근거] {rationale} | "
            f"[상승조건] {upside} | [손절조건] {downside}"
        )
    else:
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
        "unscorable_reason": unscorable_reason,
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
