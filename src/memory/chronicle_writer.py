# -*- coding: utf-8 -*-
"""T-Day 크로니클 리포트 작성 및 마스터 인덱스 갱신."""
import re
import uuid
from datetime import datetime, timezone, timedelta

from src.memory import drive_client
from src.strategy import ai_logic as ai_strategy

KST = timezone(timedelta(hours=9))
MASTER_INDEX_REL = drive_client.MASTER_INDEX_REL


def should_write_chronicle(macro):
    """코스피/코스닥 +-1.5% 또는 VIX>=25."""
    try:
        vix = float(macro.get("VIX", 0) or 0)
    except (TypeError, ValueError):
        vix = 0.0
    if vix >= 25:
        return True, f"VIX {vix:.1f}"

    for key, label in (("KOSPI_CHG", "KOSPI"), ("KOSDAQ_CHG", "KOSDAQ")):
        try:
            chg = float(macro.get(key, 0) or 0)
        except (TypeError, ValueError):
            chg = 0.0
        if abs(chg) >= 1.5:
            return True, f"{label} {chg:+.2f}%"
    return False, ""


def _report_rel_path(date_str):
    y, m, _ = date_str.split("-")
    return f"{drive_client.CHRONICLES_ROOT}/reports/{y}/{m}/{date_str}_chronicle.md"


def _parse_guideline_summary(ai_text):
    for line in ai_text.splitlines():
        if "행동 지침" in line or "최종 행동" in line:
            return line.strip()[:300]
    lines = [ln.strip() for ln in ai_text.splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "행동 지침 요약 없음"


def _extract_keywords_from_report(ai_text, macro):
    kws = set()
    kws |= set(re.findall(r"[가-힣]{2,}", ai_text)[:30])
    try:
        if float(macro.get("VIX", 0) or 0) >= 25:
            kws.add("VIX경계")
    except (TypeError, ValueError):
        pass
    for key in ("KOSPI_CHG", "KOSDAQ_CHG"):
        try:
            chg = float(macro.get(key, 0) or 0)
            if abs(chg) >= 1.5:
                kws.add("지수급변")
        except (TypeError, ValueError):
            pass
    return sorted(kws)[:20]


def _build_chronicle_prompt(macro, us_news, kr_news, trigger_reason):
    macro_text = macro.get("ai_summary", str(macro))
    return f"""
    오늘 장 마감 후 '시장 크로니클' 리포트를 작성한다.
    트리거 사유: {trigger_reason}

    [절대 규칙]
    1. 금융 전문 용어를 쓰지 말고, 주식 초보자도 이해하는 쉬운 일상 언어로 작성한다.
    2. 문장은 짧게 끊는다.

    [데이터]
    매크로: {macro_text}
    해외 뉴스: {us_news}
    국내 뉴스: {kr_news}

    [출력 양식]
    ## Intraday Flow (장중 흐름)
    - 아침 / 점심 / 장마감 지수·심리 변화 (3~5줄)

    ## 사건과 원인
    - 핵심 뉴스·지표와 시장 반응 연결 (3~5줄)

    ## 미래 행동 지침 (핵심)
    - "비슷한 뉴스·국면이 다시 오면 우리는 어떻게 할 것인가"를 기계적 룰로 3~5개 bullet
    - 예: 신규 매수 중단, 비중 축소, 특정 섹터만 보수 매수 등

    ## 한 줄 요약
    - 오늘 장의 교훈 1문장
    """


def write_chronicle_for_today(macro, us_news, kr_news, notify_fn=None):
    """
    크로니클 작성. Drive 미준비 시 Pause 후 False 반환.
    notify_fn: 슬랙 등 알림 콜백 (문자열 1개 인자)
    """
    ok, reason = should_write_chronicle(macro)
    if not ok:
        return False, "크로니클 트리거 조건 미충족"

    if not drive_client.is_drive_enabled():
        return False, "Drive 비활성"

    if drive_client.is_paused():
        return False, "Drive Pause 상태"

    if not drive_client.is_ready():
        success, msg = drive_client.init_drive_or_pause(notify_fn)
        if not success:
            return False, msg

    today = datetime.now(KST).strftime("%Y-%m-%d")
    rel_path = _report_rel_path(today)
    if drive_client.file_exists_relative(rel_path):
        return False, f"오늘({today}) 크로니클이 이미 존재합니다."

    prompt = _build_chronicle_prompt(macro, us_news, kr_news, reason)
    report_body = ai_strategy.generate_text(prompt)
    if not report_body or "AI" in report_body[:20] and "실패" in report_body:
        return False, "AI 리포트 생성 실패"

    header = f"# Market Chronicle {today}\n\n트리거: {reason}\n\n"
    full_md = header + report_body

    try:
        drive_client.write_text_relative(rel_path, full_md, mime_type="text/markdown")
    except drive_client.DrivePausedError as e:
        if notify_fn:
            notify_fn(f"[Chronicles Pause] {e.reason}\n조치: {e.action_required}")
        return False, str(e)

    summary = _parse_guideline_summary(report_body)
    keywords = _extract_keywords_from_report(report_body, macro)
    regime = ""
    try:
        vix = float(macro.get("VIX", 0) or 0)
        if vix >= 25:
            regime = f"VIX {vix:.0f} 공포 구간"
    except (TypeError, ValueError):
        pass

    index = drive_client.read_json_relative(MASTER_INDEX_REL) or {"version": 1, "entries": []}
    index.setdefault("entries", []).append(
        {
            "id": str(uuid.uuid4())[:8],
            "date": today,
            "keywords": keywords,
            "regime": regime,
            "guideline_summary": summary,
            "report_rel_path": rel_path,
            "trigger": reason,
        }
    )
    drive_client.write_json_relative(MASTER_INDEX_REL, index)

    if notify_fn:
        notify_fn(
            f"[Market Chronicles] T-Day 리포트 저장 완료 ({today})\n"
            f"트리거: {reason}\n"
            f"요약: {summary}"
        )
    return True, summary
