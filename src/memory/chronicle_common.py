# -*- coding: utf-8 -*-
"""
Market Chronicles 공통 헬퍼.

chronicle_writer.py 와 backfill.py 사이에 100% 또는 거의 동일한 형태로
중복되어 있던 다음 유틸리티들을 단일 진입점으로 통합한다.

- report_rel_path(date_str): YYYY-MM-DD -> Drive 상대 경로.
- parse_guideline_summary(ai_text): AI 리포트 본문에서 행동 지침 한 줄 요약 추출.
- build_keyphrases(ai_text, *, vix, kospi_chg, kosdaq_chg):
  AI 키프레이즈 추출 결과에 매크로 트리거 phrase 를 덧붙여 반환.
- append_phrase_unique(phrase_list, phrase, subject, action, tone):
  키프레이즈 리스트에 중복 없이 항목을 추가.
- make_emitter(notify_fn): notify_fn 이 있으면 그것을, 없으면 print 를
  사용하는 메시지 송출 콜백 생성기.

본 모듈은 src/memory/drive_client 의 폴더 상수를 참조하므로 drive_client
와의 임포트 순환을 피하기 위해 함수 내부에서 lazy import 한다.
"""
from src.utils.macro_triggers import INDEX_SHOCK_PCT, VIX_WARN, _safe_float


def report_rel_path(date_str):
    """YYYY-MM-DD 문자열을 Drive 상의 크로니클 .md 상대 경로로 변환."""
    from src.memory import drive_client

    year, month, _ = date_str.split("-")
    return f"{drive_client.CHRONICLES_ROOT}/reports/{year}/{month}/{date_str}_chronicle.md"


def parse_guideline_summary(ai_text):
    """AI 리포트에서 '행동 지침' / '최종 행동' 라인을 우선 추출.

    해당 라인이 없으면 마지막 비공백 라인을 사용한다. 최대 300자.
    """
    for line in ai_text.splitlines():
        if "행동 지침" in line or "최종 행동" in line:
            return line.strip()[:300]
    line_list = [ln.strip() for ln in ai_text.splitlines() if ln.strip()]
    return line_list[-1][:300] if line_list else "행동 지침 요약 없음"


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
