# -*- coding: utf-8 -*-
"""
유사 시장 국면 행동 지침 검색 및 AI 프롬프트 주입.

v3.4 변경점 (DETAIL CHRONICLES §4.3.2 / §5.1.2):
- Master Index v2 ``entry_dict`` 평탄화 구조에 맞춰 점수화를 재설계.
- 1순위: ``context_tags_list`` 자카드 (+10/+6/+3, 이미지 §5.1.2 의 "0.1초 판단" 핵심).
- 2~3순위: ``market_state.regime`` enum 정확 일치(+5) / 인접 그룹(+2).
- 4~5순위: ``market_state.main_actor`` 부분 일치(+1.5) / ``sentiment`` 일치(+1.5).
- 6순위: ``phrases_list`` 자카드 보조 폴백(+4/+2) — ``context_tags_list`` 매칭이
  단계 1-A 임계 미달일 때만 발동, AI 가독성 영역에는 노출하지 않는다.
- 7순위: 최근성 보너스 (+2/+1/+0.3).
- 8순위: ``embedding_vector`` 코사인 (v3.5 예약, v3.4 단계에서는 항상 0 가산).
- v1 의 ``keywords`` 폴백 경로는 완전 제거 (v3.4 가동 전제는 v2 마이그레이션 완료).
- ``build_context_injection_block`` 출력은 3블록(헤더/태그/지침) 으로 압축하며,
  ``phrases_list`` 와 ``embedding_vector`` 는 비노출.
"""
import re
from datetime import date as _date

from src.memory import drive_client
from src.utils.macro_triggers import (
    REGIME_ENUM_SET,
    REGIME_NEIGHBOR_MAP,
    REGIME_SIDEWAYS,
    VIX_WARN,
    _safe_float,
    resolve_regime,
)
from src.utils.timekit import now_kst

MASTER_INDEX_REL = drive_client.MASTER_INDEX_REL
STOPWORDS = {"및", "등", "의", "이", "가", "을", "를", "에", "에서", "으로", "the", "and", "of"}

# v3.4 가중치 (DETAIL CHRONICLES §4.3.2)
WEIGHT_TAGS_HIGH = 10.0
WEIGHT_TAGS_MID = 6.0
WEIGHT_TAGS_LOW = 3.0
WEIGHT_REGIME_EXACT = 5.0
WEIGHT_REGIME_NEIGHBOR = 2.0
WEIGHT_MAIN_ACTOR_MATCH = 1.5
WEIGHT_SENTIMENT_MATCH = 1.5
WEIGHT_PHRASES_HIGH = 4.0
WEIGHT_PHRASES_MID = 2.0
WEIGHT_RECENCY_30D = 2.0
WEIGHT_RECENCY_90D = 1.0
WEIGHT_RECENCY_180D = 0.3

# 단계 1-A/B/C 자카드 임계값
TAGS_THRESHOLD_HIGH = 0.5
TAGS_THRESHOLD_MID = 0.3
TAGS_THRESHOLD_LOW = 0.15

# 단계 6 보조 폴백 임계값 (phrases_list 자카드)
PHRASES_FALLBACK_THRESHOLD_HIGH = 0.6
PHRASES_FALLBACK_THRESHOLD_MID = 0.35

# 단계 5 sentiment 동의어 매핑. 쿼리 측·엔트리 측 모두 정규화 후 비교한다.
_SENTIMENT_SYNONYM_MAP = {
    "위험 회피 극대화": {"극단적 위험회피", "패닉", "극심한 위험회피"},
    "위험 회피 강화": {"공포 확대"},
    "위험 회피 우위": {"공포", "방어 우위"},
    "쇼크 충격 흡수 중": {"갭다운 충격"},
    "위험 선호 우위": {"낙관", "강세"},
    "낙관 극대화": {"과열 낙관", "탐욕"},
    "기술적 매수 우위": {"반등 우위", "기술적 반등 우위"},
    "관망 우위": {"중립", "혼조"},
    "관망 / 약세 우위": {"방어 우위 (관망)"},
    "관망 / 강세 우위": {"강세 우위 (관망)"},
}


def _tokenize(text):
    if not text:
        return set()
    tokens = re.findall(r"[가-힣a-zA-Z0-9]+", str(text).lower())
    return {t for t in tokens if len(t) >= 2 and t not in STOPWORDS}


def _coerce_phrase(item):
    """str 또는 dict 형태의 phrase 입력을 dict 표준 포맷으로 정규화."""
    if isinstance(item, dict):
        return {
            "phrase": str(item.get("phrase", "")),
            "subject": str(item.get("subject", "")),
            "action": str(item.get("action", "")),
            "tone": str(item.get("tone", "neutral")).lower() or "neutral",
        }
    return {"phrase": str(item or ""), "subject": "", "action": "", "tone": "neutral"}


def _jaccard(set_a, set_b):
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / max(1, len(set_a | set_b))


def _phrase_jaccard(query_phrases_list, entry_phrases_list):
    """phrases_list (보조) 의 토큰 자카드 평균."""
    q_tokens = set()
    for qp in query_phrases_list or []:
        q_tokens |= _tokenize(_coerce_phrase(qp).get("phrase", ""))
    e_tokens = set()
    for ep in entry_phrases_list or []:
        e_tokens |= _tokenize(_coerce_phrase(ep).get("phrase", ""))
    return _jaccard(q_tokens, e_tokens)


def _recency_bonus(date_str):
    if not date_str:
        return 0.0
    try:
        d = _date.fromisoformat(str(date_str)[:10])
    except Exception:
        return 0.0
    # v1.1 (2026-05-25): Market Chronicles 의 모든 기준 시간은 KST.
    # 서버가 UTC 일 때 _date.today() 가 KST 와 9시간 차이로 age 가 어긋나는 버그 정정.
    age = (now_kst().date() - d).days
    if age < 0:
        return 0.0
    if age <= 30:
        return WEIGHT_RECENCY_30D
    if age <= 90:
        return WEIGHT_RECENCY_90D
    if age <= 180:
        return WEIGHT_RECENCY_180D
    return 0.0


def _normalize_sentiment(text):
    """sentiment 문자열 정규화 (공백·괄호 제거 후 비교용 키 반환)."""
    if not text:
        return ""
    return re.sub(r"\s+", "", str(text)).strip()


def _sentiment_matches(query_sentiment, entry_sentiment):
    """단계 5 sentiment 일치 판정 (정확 일치 또는 동의어 매핑 일치)."""
    if not query_sentiment or not entry_sentiment:
        return False
    q_norm = _normalize_sentiment(query_sentiment)
    e_norm = _normalize_sentiment(entry_sentiment)
    if q_norm == e_norm:
        return True
    for canonical, synonyms in _SENTIMENT_SYNONYM_MAP.items():
        c_norm = _normalize_sentiment(canonical)
        synonym_norm_set = {_normalize_sentiment(s) for s in synonyms}
        if q_norm in synonym_norm_set and e_norm == c_norm:
            return True
        if e_norm in synonym_norm_set and q_norm == c_norm:
            return True
    return False


# ---------------------------------------------------------------------------
# 쿼리 측 시장 컨텍스트 추출 (v3.4)
# ---------------------------------------------------------------------------

# 1차 매크로 트리거 기반 default sentiment 매핑. 점수화 단계 5 의 query 측
# 입력으로 사용한다.
_DEFAULT_QUERY_SENTIMENT_MAP = {
    "PANIC_SELL": "위험 회피 극대화",
    "FEAR_EXTREME": "위험 회피 강화",
    "FEAR_RISING": "위험 회피 우위",
    "SHOCK_OPEN": "쇼크 충격 흡수 중",
    "BULLISH_RALLY": "위험 선호 우위",
    "GREED_EXTREME": "낙관 극대화",
    "TECH_REBOUND": "기술적 매수 우위",
    "SIDEWAYS": "관망 우위",
}

# 1차 매크로 트리거 기반 default main_actor 토큰 사전. extract_market_context
# 의 폴백 산출에 사용한다 (뉴스 본문이 없을 때).
_DEFAULT_QUERY_MAIN_ACTOR_TOKEN_MAP = {
    "PANIC_SELL": "외국인",
    "FEAR_EXTREME": "외국인",
    "FEAR_RISING": "기관",
    "SHOCK_OPEN": "외국인",
    "BULLISH_RALLY": "기관",
    "GREED_EXTREME": "개인",
    "TECH_REBOUND": "기관",
    "SIDEWAYS": "",
}


def extract_market_context(macro, news_snippets=None):
    """현재 시장 컨텍스트를 분석하여 v3.4 쿼리 4종을 반환한다.

    Returns:
        dict: ``{"context_tags_list": list[str], "regime": str (enum),
                 "main_actor_keyword": str, "sentiment": str,
                 "phrases_list": list[dict] (보조 매칭용)}``.
    """
    from src.memory import chronicle_common
    from src.memory.keyphrase_extractor import extract_query_phrases

    news_snippets = news_snippets or []
    macro_dict = macro if isinstance(macro, dict) else {}

    phrases_list = extract_query_phrases(news_snippets=news_snippets, macro=macro_dict)

    vix_value = _safe_float(macro_dict.get("VIX", 20.0), default=20.0)
    kospi_chg = _safe_float(macro_dict.get("KOSPI_CHG", 0))
    kosdaq_chg = _safe_float(macro_dict.get("KOSDAQ_CHG", 0))
    open_chg = macro_dict.get("OPEN_CHG")
    prev_regime = macro_dict.get("PREV_REGIME")

    if vix_value >= VIX_WARN:
        chronicle_common.append_phrase_unique(
            phrases_list, f"VIX {vix_value:.0f} 경계", "VIX", "경계", "negative"
        )

    regime = resolve_regime(
        vix_value, kospi_chg, kosdaq_chg, open_chg=open_chg, prev_regime=prev_regime
    )

    market_state_dict = chronicle_common.derive_market_state(
        phrases_list,
        vix=vix_value,
        kospi_chg=kospi_chg,
        kosdaq_chg=kosdaq_chg,
        open_chg=open_chg,
        prev_regime=prev_regime,
    )
    context_tags_list = chronicle_common.derive_context_tags(
        phrases_list, market_state_dict
    )

    main_actor_keyword = market_state_dict.get("main_actor", "")
    if not main_actor_keyword:
        main_actor_keyword = _DEFAULT_QUERY_MAIN_ACTOR_TOKEN_MAP.get(regime, "")

    sentiment = market_state_dict.get("sentiment", "")
    if not sentiment:
        sentiment = _DEFAULT_QUERY_SENTIMENT_MAP.get(regime, "")

    return {
        "context_tags_list": context_tags_list,
        "regime": regime,
        "main_actor_keyword": main_actor_keyword,
        "sentiment": sentiment,
        "phrases_list": phrases_list,
    }


# ---------------------------------------------------------------------------
# 점수화 (v3.4 8단계, DETAIL CHRONICLES §4.3.2)
# ---------------------------------------------------------------------------


def _score_entry(entry, query):
    """v3.4 8단계 가중치 점수.

    Args:
        entry: ``master_index.json`` 의 v2 엔트리 dict.
        query: ``extract_market_context`` 결과 dict.

    Returns:
        float: 합산 점수.
    """
    score = 0.0

    market_state_dict = entry.get("market_state") or {}
    entry_tags_set = set(entry.get("context_tags_list") or [])
    query_tags_set = set(query.get("context_tags_list") or [])

    tags_sim = _jaccard(query_tags_set, entry_tags_set)
    matched_tags_level = 0
    if tags_sim >= TAGS_THRESHOLD_HIGH:
        score += WEIGHT_TAGS_HIGH
        matched_tags_level = 3
    elif tags_sim >= TAGS_THRESHOLD_MID:
        score += WEIGHT_TAGS_MID
        matched_tags_level = 2
    elif tags_sim >= TAGS_THRESHOLD_LOW:
        score += WEIGHT_TAGS_LOW
        matched_tags_level = 1

    query_regime = query.get("regime")
    entry_regime = market_state_dict.get("regime")
    if query_regime and entry_regime and query_regime in REGIME_ENUM_SET:
        if query_regime == entry_regime:
            score += WEIGHT_REGIME_EXACT
        elif entry_regime in (REGIME_NEIGHBOR_MAP.get(query_regime) or []):
            score += WEIGHT_REGIME_NEIGHBOR

    query_main_actor = (query.get("main_actor_keyword") or "").strip()
    entry_main_actor = (market_state_dict.get("main_actor") or "").strip()
    if query_main_actor and entry_main_actor:
        if query_main_actor in entry_main_actor or entry_main_actor in query_main_actor:
            score += WEIGHT_MAIN_ACTOR_MATCH

    if _sentiment_matches(query.get("sentiment", ""), market_state_dict.get("sentiment", "")):
        score += WEIGHT_SENTIMENT_MATCH

    if matched_tags_level <= 1:
        phrase_sim = _phrase_jaccard(
            query.get("phrases_list") or [], entry.get("phrases_list") or []
        )
        if phrase_sim >= PHRASES_FALLBACK_THRESHOLD_HIGH:
            score += WEIGHT_PHRASES_HIGH
        elif phrase_sim >= PHRASES_FALLBACK_THRESHOLD_MID:
            score += WEIGHT_PHRASES_MID

    score += _recency_bonus(entry.get("date"))

    return score


# ---------------------------------------------------------------------------
# 공개 검색 API
# ---------------------------------------------------------------------------


def search_similar_guidelines(
    query_context_tags_list=None,
    query_regime=None,
    *,
    query_main_actor_keyword="",
    query_sentiment="",
    query_phrases_list=None,
    top_n=3,
    min_score=3.0,
    query_dict=None,
):
    """v3.4 시그니처.

    Args:
        query_context_tags_list: ``extract_market_context`` 의 ``context_tags_list``.
        query_regime: ``extract_market_context`` 의 ``regime`` enum.
        query_main_actor_keyword: 쿼리 측 주도 세력 (부분 일치 비교용).
        query_sentiment: 쿼리 측 sentiment 라벨.
        query_phrases_list: 보조 의미 매칭용 phrase 리스트 (단계 6).
        top_n: 반환 최대 갯수.
        min_score: 점수 임계 (기본 3.0, ``context_tags_list`` Low 단계 통과 컷).
        query_dict: ``extract_market_context`` 의 반환 dict 전체를 그대로 받는
            진입점 (위 5개 키워드 인자보다 우선). 호출부가 단일 dict 만
            관리해도 되도록 제공한다.

    Returns:
        list[dict]: 점수 상위 항목들. 각 항목은 검색 결과 표시용 평탄 dict.
    """
    if not drive_client.is_ready():
        return []
    try:
        index = drive_client.read_master_index()
    except Exception:
        return []

    if query_dict is None:
        query_dict = {
            "context_tags_list": query_context_tags_list or [],
            "regime": query_regime,
            "main_actor_keyword": query_main_actor_keyword,
            "sentiment": query_sentiment,
            "phrases_list": query_phrases_list or [],
        }

    ranked = []
    for entry in index.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        sc = _score_entry(entry, query_dict)
        if sc >= min_score:
            ranked.append((sc, entry))
    ranked.sort(key=lambda x: x[0], reverse=True)

    results = []
    for sc, entry in ranked[:top_n]:
        market_state_dict = entry.get("market_state") or {}
        results.append(
            {
                "date": entry.get("date"),
                "score": round(sc, 2),
                "regime": market_state_dict.get("regime"),
                "regime_label": market_state_dict.get("regime_label", ""),
                "main_actor": market_state_dict.get("main_actor", ""),
                "sentiment": market_state_dict.get("sentiment", ""),
                "context_tags_list": entry.get("context_tags_list") or [],
                "action_preview": entry.get("action_preview", ""),
                "report_rel_path": entry.get("report_rel_path"),
            }
        )
    return results


def build_context_injection_block(query, top_n=3):
    """3블록 압축 출력 (DETAIL CHRONICLES §4.3.2).

    Args:
        query: ``extract_market_context`` 의 반환 dict, 또는 v3.2 호환을 위한
            ``(query_phrases_list, regime)`` 튜플.
        top_n: 컨텍스트 블록에 포함할 최대 엔트리 수.

    Returns:
        str: 슬랙·프롬프트 주입용 한국어 문자열. 빈 결과면 빈 문자열.
    """
    if isinstance(query, tuple) and len(query) >= 2:
        legacy_phrases_list, legacy_regime = query[0], query[1]
        if isinstance(legacy_regime, str) and legacy_regime in REGIME_ENUM_SET:
            regime = legacy_regime
        else:
            regime = REGIME_SIDEWAYS
        query_dict = {
            "context_tags_list": [],
            "regime": regime,
            "main_actor_keyword": "",
            "sentiment": "",
            "phrases_list": legacy_phrases_list or [],
        }
    elif isinstance(query, dict):
        query_dict = query
    else:
        return ""

    entries = search_similar_guidelines(query_dict=query_dict, top_n=top_n)
    if not entries:
        return ""

    lines = [
        "[필수 준수 배경 지식 - Market Chronicles]",
        "아래는 과거 유사 시장 국면에서 확정한 행동 지침이다. 현재 판단 시 반드시 참고하라.",
    ]
    for i, e in enumerate(entries, 1):
        header_parts = [
            f"지침 {i}",
            f"({e.get('date', '?')})",
            f"점수 {e.get('score', 0)}",
        ]
        regime_label = e.get("regime_label") or e.get("regime") or ""
        if regime_label:
            header_parts.append(f"시장 상태: {regime_label}")
        main_actor = e.get("main_actor") or ""
        if main_actor:
            header_parts.append(main_actor)
        sentiment = e.get("sentiment") or ""
        if sentiment:
            header_parts.append(sentiment)
        lines.append("--- " + " | ".join(header_parts) + " ---")

        tag_text = " / ".join((e.get("context_tags_list") or [])[:6]) or "(태그 없음)"
        lines.append(f"태그: {tag_text}")
        lines.append(f"지침: {e.get('action_preview') or '(요약 없음)'}")
        lines.append("")
    return "\n".join(lines).strip()
