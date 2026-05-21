# -*- coding: utf-8 -*-
"""
Market Chronicles 공통 헬퍼.

chronicle_writer.py 와 backfill.py 사이에 100% 또는 거의 동일한 형태로
중복되어 있던 다음 유틸리티들을 단일 진입점으로 통합한다.

- report_rel_path(date_str): YYYY-MM-DD -> Drive 상대 경로.
- parse_action_preview(ai_text) / parse_guideline_summary(ai_text):
  AI 리포트 본문에서 행동 지침 한 줄 요약 추출. v3.4 부터 200자 슬라이싱
  ``parse_action_preview`` 를 1차 진입점으로 사용하며, 이전 명칭
  ``parse_guideline_summary`` 는 호환 alias 로 유지한다.
- build_keyphrases(ai_text, *, vix, kospi_chg, kosdaq_chg):
  AI 키프레이즈 추출 결과에 매크로 트리거 phrase 를 덧붙여 반환.
- derive_market_state(phrases_list, *, vix, kospi_chg, kosdaq_chg, ...):
  v3.4 ``market_state`` dict 산출 (regime/regime_label/main_actor/sentiment).
- derive_context_tags(phrases_list, market_state_dict):
  v3.4 ``context_tags_list`` (짧은 [주체_동사] 결합 태그 4~6개) 산출.
- append_phrase_unique(phrase_list, phrase, subject, action, tone):
  키프레이즈 리스트에 중복 없이 항목을 추가.
- make_emitter(notify_fn): notify_fn 이 있으면 그것을, 없으면 print 를
  사용하는 메시지 송출 콜백 생성기.

본 모듈은 src/memory/drive_client 의 폴더 상수를 참조하므로 drive_client
와의 임포트 순환을 피하기 위해 함수 내부에서 lazy import 한다.
"""
from collections import Counter

from src.utils.macro_triggers import (
    INDEX_SHOCK_PCT,
    REGIME_BULLISH_RALLY,
    REGIME_FEAR_EXTREME,
    REGIME_FEAR_RISING,
    REGIME_GREED_EXTREME,
    REGIME_PANIC_SELL,
    REGIME_SHOCK_OPEN,
    REGIME_SIDEWAYS,
    REGIME_TECH_REBOUND,
    VIX_WARN,
    _safe_float,
    resolve_regime,
)


def report_rel_path(date_str):
    """YYYY-MM-DD 문자열을 Drive 상의 크로니클 .md 상대 경로로 변환."""
    from src.memory import drive_client

    year, month, _ = date_str.split("-")
    return f"{drive_client.CHRONICLES_ROOT}/reports/{year}/{month}/{date_str}_chronicle.md"


def parse_action_preview(ai_text):
    """AI 리포트에서 '행동 지침' / '최종 행동' 라인을 우선 추출 (v3.4 기본).

    해당 라인이 없으면 마지막 비공백 라인을 사용한다. 최대 200자
    (DETAIL CHRONICLES §5.1.2(1) ``action_preview`` 룰).
    """
    for line in ai_text.splitlines():
        if "행동 지침" in line or "최종 행동" in line:
            return line.strip()[:200]
    line_list = [ln.strip() for ln in ai_text.splitlines() if ln.strip()]
    return line_list[-1][:200] if line_list else "행동 지침 요약 없음"


def parse_guideline_summary(ai_text):
    """v3.3 호환 alias. 신규 호출부는 ``parse_action_preview`` 사용을 권장.

    내부적으로 ``parse_action_preview`` 를 호출하므로 슬라이싱은 200자.
    300자 컷이 필요한 외부 호출이 있으면 본 함수 호출 후 호출부에서
    추가 컷을 진행하지 않아도 된다 (대부분의 사용처는 한 줄 요약만 사용).
    """
    return parse_action_preview(ai_text)


def append_phrase_unique(phrase_list, phrase, subject, action, tone):
    """phrase_list 에 dict 항목을 중복 없이 추가.

    중복 판정은 `phrase` 문자열 기준이다.
    """
    for existing in phrase_list:
        if existing.get("phrase") == phrase:
            return
    phrase_list.append(
        {"phrase": phrase, "subject": subject, "action": action, "tone": tone}
    )


def build_keyphrases(ai_text, *, vix=0.0, kospi_chg=0.0, kosdaq_chg=0.0,
                     max_phrases=12, ai_enabled=True, hard_limit=15):
    """AI 키프레이즈 추출 + 매크로 트리거 phrase 부착.

    호출부(chronicle_writer / backfill)는 macro dict 또는 event dict 의
    형태가 다르므로, 본 함수는 정규화된 키워드 인자만 받는다.

    Args:
        ai_text: AI 리포트 본문.
        vix: 당시 VIX 종가.
        kospi_chg: 당시 KOSPI 등락률 (%).
        kosdaq_chg: 당시 KOSDAQ 등락률 (%).
        max_phrases: keyphrase_extractor 의 1차 추출 상한.
        ai_enabled: AI 1차 추출 사용 여부 (False 면 정규식 폴백만).
        hard_limit: 최종 반환 phrase 갯수 상한.

    Returns:
        list[dict]: keyphrase 항목 (phrase/subject/action/tone).
    """
    from src.memory.keyphrase_extractor import extract_keyphrases

    phrase_list = extract_keyphrases(ai_text, max_phrases=max_phrases, ai_enabled=ai_enabled)

    vix_v = _safe_float(vix)
    kospi_v = _safe_float(kospi_chg)
    kosdaq_v = _safe_float(kosdaq_chg)

    if vix_v >= VIX_WARN:
        if vix_v > 0:
            label = f"VIX {vix_v:.0f} 경계"
        else:
            label = f"VIX {VIX_WARN:.0f} 이상 경계"
        append_phrase_unique(phrase_list, label, "VIX", "경계", "negative")

    for chg_value, index_label in ((kospi_v, "코스피"), (kosdaq_v, "코스닥")):
        if chg_value <= -INDEX_SHOCK_PCT:
            append_phrase_unique(
                phrase_list,
                f"{index_label} 급락 ({chg_value:+.2f}%)",
                index_label,
                "하락",
                "negative",
            )
        elif chg_value >= INDEX_SHOCK_PCT:
            append_phrase_unique(
                phrase_list,
                f"{index_label} 급등 ({chg_value:+.2f}%)",
                index_label,
                "상승",
                "positive",
            )

    return phrase_list[:hard_limit]


# ---------------------------------------------------------------------------
# v3.4 Master Index v2 산출 헬퍼 (DETAIL CHRONICLES §5.1.2 / §5.1.3)
# ---------------------------------------------------------------------------

# regime enum -> 자유형 한국어 라벨 매핑. ``market_state.regime_label`` 의
# 기본값 (v1 자유형 보존 데이터가 없을 때) 으로 사용한다.
_REGIME_LABEL_DEFAULT_MAP = {
    REGIME_PANIC_SELL: "강한 하락장 (Panic)",
    REGIME_FEAR_EXTREME: "공포 확대 (Extreme Fear)",
    REGIME_FEAR_RISING: "공포 상승 (Fear Rising)",
    REGIME_SHOCK_OPEN: "갭다운 쇼크 개장",
    REGIME_BULLISH_RALLY: "강세 랠리",
    REGIME_GREED_EXTREME: "과열 (Extreme Greed)",
    REGIME_TECH_REBOUND: "기술적 반등",
    REGIME_SIDEWAYS: "횡보 / 관망",
}

# regime + dominant_tone -> sentiment 자유형 라벨 매핑. 점수화 단계 5 의
# 동의어 매칭 비용을 줄이기 위해 라벨을 표준화한다.
_SENTIMENT_LABEL_MAP = {
    REGIME_PANIC_SELL: "위험 회피 극대화",
    REGIME_FEAR_EXTREME: "위험 회피 강화",
    REGIME_FEAR_RISING: "위험 회피 우위",
    REGIME_SHOCK_OPEN: "쇼크 충격 흡수 중",
    REGIME_BULLISH_RALLY: "위험 선호 우위",
    REGIME_GREED_EXTREME: "낙관 극대화",
    REGIME_TECH_REBOUND: "기술적 매수 우위",
    REGIME_SIDEWAYS: "관망 우위",
}


def _dominant_tone(phrases_list):
    """phrases_list 의 ``tone`` 다수결을 반환. 동수·빈 리스트는 ``'neutral'``."""
    if not phrases_list:
        return "neutral"
    counter = Counter(ph.get("tone", "neutral") for ph in phrases_list)
    top_two_list = counter.most_common(2)
    if len(top_two_list) >= 2 and top_two_list[0][1] == top_two_list[1][1]:
        return "neutral"
    return top_two_list[0][0]


def _top_subjects(phrases_list, top_n=3):
    """phrases_list 의 ``subject`` 빈도 상위 ``top_n`` 개 리스트 반환."""
    if not phrases_list:
        return []
    counter = Counter(
        ph.get("subject", "").strip() for ph in phrases_list if ph.get("subject")
    )
    return [subject for subject, _ in counter.most_common(top_n)]


def derive_market_state(
    phrases_list,
    *,
    vix=0.0,
    kospi_chg=0.0,
    kosdaq_chg=0.0,
    open_chg=None,
    prev_regime=None,
    regime_label_override=None,
):
    """v3.4 ``market_state`` dict (4-필드) 산출.

    DETAIL CHRONICLES §5.1.2(2) 정의. ``regime`` 은
    ``macro_triggers.resolve_regime`` 으로 결정하고, ``regime_label`` 은
    호출부가 v1 자유형 문자열을 보존하기 위해 ``regime_label_override`` 를
    명시하면 우선 사용, 그 외에는 enum 매핑 기본 라벨을 사용한다.

    Args:
        phrases_list: ``build_keyphrases`` 산출 결과 (list[dict]).
        vix / kospi_chg / kosdaq_chg / open_chg: 매크로 입력 (resolve_regime 위임).
        prev_regime: 직전 영업일 regime enum (옵션).
        regime_label_override: v1 자유형 라벨 보존 시 사용.

    Returns:
        dict: ``{"regime": enum, "regime_label": str, "main_actor": str,
                  "sentiment": str}``.
    """
    regime = resolve_regime(
        vix, kospi_chg, kosdaq_chg, open_chg=open_chg, prev_regime=prev_regime
    )
    regime_label = regime_label_override or _REGIME_LABEL_DEFAULT_MAP.get(
        regime, regime
    )

    top_subject_list = _top_subjects(phrases_list, top_n=3)
    if top_subject_list:
        main_actor_subject = top_subject_list[0]
        action_counter = Counter(
            ph.get("action", "").strip()
            for ph in phrases_list
            if ph.get("subject") == main_actor_subject and ph.get("action")
        )
        if action_counter:
            main_actor = f"{main_actor_subject} {action_counter.most_common(1)[0][0]}".strip()
        else:
            main_actor = main_actor_subject
    else:
        main_actor = ""

    sentiment = _SENTIMENT_LABEL_MAP.get(regime, "")
    tone = _dominant_tone(phrases_list)
    if regime == REGIME_SIDEWAYS and tone == "negative":
        sentiment = "관망 / 약세 우위"
    elif regime == REGIME_SIDEWAYS and tone == "positive":
        sentiment = "관망 / 강세 우위"

    return {
        "regime": regime,
        "regime_label": regime_label,
        "main_actor": main_actor,
        "sentiment": sentiment,
    }


def derive_context_tags(phrases_list, market_state_dict, max_tags=6):
    """v3.4 ``context_tags_list`` 산출.

    DETAIL CHRONICLES §5.1.2(1) 의 [주체_동사] 결합 짧은 태그 4~6개.
    ``phrases_list`` 의 (subject, action) 쌍을 빈도 순으로 묶어 ``_`` 결합
    토큰으로 압축한다. ``market_state.regime_label`` 의 핵심 단어도 1개
    추가하여 시장 성격을 한 태그로 표면화한다.

    Args:
        phrases_list: ``build_keyphrases`` 산출 결과.
        market_state_dict: ``derive_market_state`` 결과.
        max_tags: 최종 태그 갯수 상한 (기본 6).

    Returns:
        list[str]: 짧은 결합 태그 리스트 (중복 제거, 최대 ``max_tags`` 개).
    """
    tag_list = []
    seen_set = set()

    if not phrases_list:
        phrases_list = []

    pair_counter = Counter()
    for phrase in phrases_list:
        subject = (phrase.get("subject") or "").strip()
        action = (phrase.get("action") or "").strip()
        if not subject or not action:
            continue
        pair_counter[(subject, action)] += 1

    for (subject, action), _count in pair_counter.most_common(max_tags):
        tag = f"{subject}_{action}".replace(" ", "")
        if tag in seen_set:
            continue
        seen_set.add(tag)
        tag_list.append(tag)
        if len(tag_list) >= max_tags - 1:
            break

    regime = (market_state_dict or {}).get("regime")
    regime_label_tag_map = {
        REGIME_PANIC_SELL: "패닉셀_확산",
        REGIME_FEAR_EXTREME: "공포_극대화",
        REGIME_FEAR_RISING: "공포_상승",
        REGIME_SHOCK_OPEN: "갭다운_쇼크",
        REGIME_BULLISH_RALLY: "강세_랠리",
        REGIME_GREED_EXTREME: "과열_탐욕",
        REGIME_TECH_REBOUND: "기술적_반등",
        REGIME_SIDEWAYS: "횡보_관망",
    }
    regime_tag = regime_label_tag_map.get(regime)
    if regime_tag and regime_tag not in seen_set:
        seen_set.add(regime_tag)
        tag_list.append(regime_tag)

    return tag_list[:max_tags]


def make_emitter(notify_fn):
    """notify_fn 이 있으면 그것으로, 없으면 print 로 메시지를 송출.

    backfill.py 내 동일 패턴이 6회 반복되던 `_emit` 클로저를 통합한다.
    """
    def _emit(msg):
        if notify_fn:
            notify_fn(msg)
        else:
            print(msg, flush=True)

    return _emit
