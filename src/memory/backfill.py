# -*- coding: utf-8 -*-
"""
Market Chronicles v3.1 - 과거 데이터 소급 구축 (Back-filling).

가동 즉시 Context Injection이 가능하도록, 최근 N일(기본 60일)의
변동성 장세를 사후 분석하여 마스터 인덱스를 선제 구축한다.

핵심 흐름:
    1. yfinance 일봉으로 ^KS11/^KQ11/^VIX 조회 -> 트리거 충족일 추출 (Scan)
    2. backfill_state.json 에 queue 보존 -> 사용자 승인 대기
    3. 1건씩 과거 시점 뉴스 수집 + AI 사후 분석 -> Drive 저장 + master_index 색인 (Backfill)
    4. 1건당 3초 대기, 실패 일자는 skipped 로 격리 후 다음 진행
"""
import time
import traceback
import uuid
from datetime import datetime, timezone, timedelta

from src.memory import drive_client
from src.strategy import ai_logic as ai_strategy

KST = timezone(timedelta(hours=9))

MASTER_INDEX_REL = drive_client.MASTER_INDEX_REL
BACKFILL_STATE_REL = f"{drive_client.CHRONICLES_ROOT}/_system/backfill_state.json"

DEFAULT_LOOKBACK_DAYS = 60
DEFAULT_DELAY_SECONDS = 3
KOSPI_TICKER = "^KS11"
KOSDAQ_TICKER = "^KQ11"
VIX_TICKER = "^VIX"


def _today_kst_date():
    return datetime.now(KST).date()


def _report_rel_path(date_str):
    y, m, _ = date_str.split("-")
    return f"{drive_client.CHRONICLES_ROOT}/reports/{y}/{m}/{date_str}_chronicle.md"


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_index_history(lookback_days):
    """yfinance로 코스피/코스닥/VIX 일봉을 받아 일자별 dict로 정리."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError(
            "yfinance 가 설치되어 있지 않습니다. requirements.txt 동기화 후 'pip install yfinance' 를 실행하세요."
        ) from exc

    period = "3mo" if lookback_days <= 80 else "6mo"
    series = {}
    for symbol in (KOSPI_TICKER, KOSDAQ_TICKER, VIX_TICKER):
        try:
            hist = yf.Ticker(symbol).history(period=period)
        except Exception as exc:
            print(f"Log: [Backfill] {symbol} 데이터 조회 실패: {exc}", flush=True)
            hist = None
        if hist is None or hist.empty:
            series[symbol] = []
            continue
        rows = []
        prev_close = None
        for idx_ts, row in hist.iterrows():
            try:
                close = float(row["Close"])
            except (KeyError, TypeError, ValueError):
                continue
            date_str = idx_ts.strftime("%Y-%m-%d")
            chg_pct = 0.0
            if prev_close and prev_close > 0:
                chg_pct = round(((close - prev_close) / prev_close) * 100, 2)
            rows.append({"date": date_str, "close": round(close, 2), "chg_pct": chg_pct})
            prev_close = close
        series[symbol] = rows
    return series


def _trigger_reason(kospi_chg, kosdaq_chg, vix_close):
    """T-Day 트리거(±1.5% 또는 VIX>=25)와 동일 규칙."""
    if vix_close >= 25.0:
        return True, f"VIX {vix_close:.1f}"
    if abs(kospi_chg) >= 1.5:
        return True, f"KOSPI {kospi_chg:+.2f}%"
    if abs(kosdaq_chg) >= 1.5:
        return True, f"KOSDAQ {kosdaq_chg:+.2f}%"
    return False, ""


def scan_event_days(lookback_days=DEFAULT_LOOKBACK_DAYS):
    """
    최근 lookback_days 거래일을 훑어 트리거 충족 일자를 추출한다.
    Returns: list[dict] - 각 항목: {date, trigger, kospi_close, kospi_chg, kosdaq_close, kosdaq_chg, vix_close}
    """
    series = _fetch_index_history(lookback_days)
    by_date = {}

    def _merge(symbol, rows, close_key, chg_key):
        for row in rows:
            entry = by_date.setdefault(row["date"], {"date": row["date"]})
            entry[close_key] = row["close"]
            entry[chg_key] = row["chg_pct"]

    _merge(KOSPI_TICKER, series.get(KOSPI_TICKER, []), "kospi_close", "kospi_chg")
    _merge(KOSDAQ_TICKER, series.get(KOSDAQ_TICKER, []), "kosdaq_close", "kosdaq_chg")
    for row in series.get(VIX_TICKER, []):
        entry = by_date.setdefault(row["date"], {"date": row["date"]})
        entry["vix_close"] = row["close"]

    today_str = _today_kst_date().isoformat()
    cutoff = (_today_kst_date() - timedelta(days=lookback_days)).isoformat()

    events = []
    for date_str in sorted(by_date.keys()):
        if date_str < cutoff or date_str > today_str:
            continue
        entry = by_date[date_str]
        kospi_chg = _safe_float(entry.get("kospi_chg"))
        kosdaq_chg = _safe_float(entry.get("kosdaq_chg"))
        vix_close = _safe_float(entry.get("vix_close"))
        ok, reason = _trigger_reason(kospi_chg, kosdaq_chg, vix_close)
        if not ok:
            continue
        events.append(
            {
                "date": date_str,
                "trigger": reason,
                "kospi_close": _safe_float(entry.get("kospi_close")),
                "kospi_chg": kospi_chg,
                "kosdaq_close": _safe_float(entry.get("kosdaq_close")),
                "kosdaq_chg": kosdaq_chg,
                "vix_close": vix_close,
            }
        )
    return events


def format_scan_report(events, lookback_days):
    """슬랙 발송용 스캔 결과 텍스트."""
    if not events:
        return (
            f"[Backfill 스캔 결과]\n"
            f"최근 {lookback_days}일 거래일 중 트리거(코스피/코스닥 ±1.5% 또는 VIX≥25)에 해당하는 날이 없었습니다.\n"
            f"별도 소급 작성이 필요 없습니다."
        )
    lines = [
        f"[Backfill 스캔 결과]",
        f"최근 {lookback_days}일간 총 {len(events)}일의 주요 변동성 장세를 확인했습니다.",
        "",
        "날짜 | 트리거 | KOSPI | KOSDAQ | VIX",
        "-" * 56,
    ]
    for ev in events:
        lines.append(
            f"{ev['date']} | {ev['trigger']:<14} | {ev['kospi_chg']:+.2f}% | {ev['kosdaq_chg']:+.2f}% | {ev['vix_close']:.1f}"
        )
    lines.append("")
    lines.append(
        "과거 데이터 소급 작성을 시작할까요? '확인' 또는 '!백필실행'을 입력하시면 진행합니다."
    )
    return "\n".join(lines)


def _load_state():
    try:
        return drive_client.read_json_relative(BACKFILL_STATE_REL) or {}
    except Exception:
        return {}


def _save_state(state):
    state["updated_at"] = datetime.now(KST).isoformat()
    drive_client.write_json_relative(BACKFILL_STATE_REL, state)


def save_scan_state(events, lookback_days):
    """스캔 결과를 Drive backfill_state.json 에 큐로 보존."""
    state = {
        "lookback_days": lookback_days,
        "scanned_at": datetime.now(KST).isoformat(),
        "queue": [ev["date"] for ev in events],
        "event_details": {ev["date"]: ev for ev in events},
        "processed": [],
        "skipped": [],
    }
    _save_state(state)
    return state


def get_state():
    return _load_state()


def _build_backfill_prompt(event, kr_news, us_news):
    return f"""
[Market Chronicles 백필링 - 과거 사후 분석]
대상 거래일: {event['date']}
트리거 사유: {event['trigger']}

[그날의 지수 스냅샷]
- KOSPI 종가 {event.get('kospi_close', 0):.2f} ({event.get('kospi_chg', 0):+.2f}%)
- KOSDAQ 종가 {event.get('kosdaq_close', 0):.2f} ({event.get('kosdaq_chg', 0):+.2f}%)
- VIX 종가 {event.get('vix_close', 0):.2f}

[참고 뉴스 (당시·이후 기록)]
- 국내: {kr_news}
- 해외: {us_news}

[작성 규칙]
1. 금융 전문 용어를 피하고 주식 초보자도 단번에 이해할 수 있는 일상 언어를 사용한다.
2. 문장을 짧게 끊고, 단정적인 어조를 사용한다.
3. 사후 통찰을 반영한다: "오늘({_today_kst_date().isoformat()}) 시점에서 돌이켜 보면 어떤 원인이 작용했는지, 이후 시장이 어떻게 반응했는지" 를 포함한다.
4. 과장 없이 데이터와 사실에 기반하여 작성한다.

[출력 양식]
## Intraday Flow (장중 흐름)
- 아침 / 점심 / 장마감의 지수·심리 변화 추정 (3~5줄)

## 사건과 원인 (사후 통찰 포함)
- 그날 시장을 흔든 핵심 뉴스·지표를 정리한다 (3~5줄)
- "지금 와서 보니" 추가로 확인된 인과·여파 (2~3줄)

## 미래 행동 지침 (핵심)
- "비슷한 뉴스·국면이 다시 발생하면 어떻게 대응한다" 를 기계적 룰로 3~5개 bullet
- 예: 신규 매수 중단, 비중 축소, 특정 섹터만 보수 매수 등

## 한 줄 요약
- 이날의 교훈 1문장
""".strip()


def _collect_news_for(event):
    """과거 시점 뉴스 키워드 수집. 실패해도 진행 가능하도록 안전 처리."""
    from src.data.crawler import news_crawler

    try:
        us_news = news_crawler.get_latest_news("US market " + event["date"], limit=5, search_type="macro")
    except Exception:
        us_news = []
    try:
        kr_news = news_crawler.get_latest_news("한국 증시 " + event["date"], limit=5, search_type="macro")
    except Exception:
        kr_news = []
    return us_news, kr_news


def _parse_guideline_summary(ai_text):
    for line in ai_text.splitlines():
        if "행동 지침" in line or "최종 행동" in line:
            return line.strip()[:300]
    lines = [ln.strip() for ln in ai_text.splitlines() if ln.strip()]
    return lines[-1][:300] if lines else "행동 지침 요약 없음"


def _build_keyphrases(ai_text, event):
    """
    v3.2: 단순 단어 집합 대신 [주체+동사] 결합 핵심 구문을 추출한다.
    이벤트 메타데이터(KOSPI/KOSDAQ 등락률, VIX)도 동일 포맷으로 합산하여 검색 정확도 향상.
    """
    from src.memory.keyphrase_extractor import extract_keyphrases

    phrases = extract_keyphrases(ai_text, max_phrases=12, ai_enabled=True)
    seen = {p.get("phrase") for p in phrases}

    def _append(phrase, subject, action, tone):
        if phrase in seen:
            return
        phrases.append(
            {"phrase": phrase, "subject": subject, "action": action, "tone": tone}
        )
        seen.add(phrase)

    if event.get("vix_close", 0) >= 25:
        _append(f"VIX {event['vix_close']:.0f} 경계", "VIX", "경계", "negative")
    kospi_chg = event.get("kospi_chg", 0)
    if kospi_chg <= -1.5:
        _append(f"코스피 급락 ({kospi_chg:+.2f}%)", "코스피", "하락", "negative")
    elif kospi_chg >= 1.5:
        _append(f"코스피 급등 ({kospi_chg:+.2f}%)", "코스피", "상승", "positive")
    kosdaq_chg = event.get("kosdaq_chg", 0)
    if kosdaq_chg <= -1.5:
        _append(f"코스닥 급락 ({kosdaq_chg:+.2f}%)", "코스닥", "하락", "negative")
    elif kosdaq_chg >= 1.5:
        _append(f"코스닥 급등 ({kosdaq_chg:+.2f}%)", "코스닥", "상승", "positive")

    return phrases[:15]


def _legacy_keyword_view(phrases):
    """검색 폴백/하위 호환용 단어 토큰 (keyphrases 기준 자동 파생)."""
    from src.memory.keyphrase_extractor import derive_tokens

    return derive_tokens(phrases)[:20]


def _build_regime(event):
    if event.get("vix_close", 0) >= 30:
        return f"극단적 공포 (VIX {event['vix_close']:.0f})"
    if event.get("vix_close", 0) >= 25:
        return f"공포 확대 (VIX {event['vix_close']:.0f})"
    chg = event.get("kospi_chg", 0)
    if abs(chg) >= 1.5:
        return f"코스피 {'급락' if chg < 0 else '급등'} ({chg:+.2f}%)"
    chg = event.get("kosdaq_chg", 0)
    if abs(chg) >= 1.5:
        return f"코스닥 {'급락' if chg < 0 else '급등'} ({chg:+.2f}%)"
    return "보통 국면"


def _write_chronicle_for_event(event):
    """1개 이벤트 데이를 처리하여 Drive 저장 + master_index 색인. 성공 시 summary 반환."""
    date_str = event["date"]
    rel_path = _report_rel_path(date_str)
    if drive_client.file_exists_relative(rel_path):
        return False, "이미 동일 일자의 크로니클이 존재합니다 (스킵)"

    us_news, kr_news = _collect_news_for(event)
    prompt = _build_backfill_prompt(event, kr_news, us_news)
    report_body = ai_strategy.generate_text(prompt)
    if not report_body or "AI" in report_body[:20] and "실패" in report_body:
        return False, "AI 리포트 생성 실패"

    header = (
        f"# Market Chronicle (Backfill) {date_str}\n\n"
        f"트리거: {event['trigger']}\n"
        f"작성일: {datetime.now(KST).isoformat()} (사후 소급)\n\n"
    )
    full_md = header + report_body
    drive_client.write_text_relative(rel_path, full_md, mime_type="text/markdown")

    summary = _parse_guideline_summary(report_body)
    keyphrases = _build_keyphrases(report_body, event)
    keywords = _legacy_keyword_view(keyphrases)
    regime = _build_regime(event)

    index = drive_client.read_json_relative(MASTER_INDEX_REL) or {"version": 1, "entries": []}
    index.setdefault("entries", []).append(
        {
            "id": str(uuid.uuid4())[:8],
            "date": date_str,
            "keyphrases": keyphrases,
            "keywords": keywords,
            "regime": regime,
            "guideline_summary": summary,
            "report_rel_path": rel_path,
            "trigger": event["trigger"],
            "source": "backfill",
        }
    )
    drive_client.write_json_relative(MASTER_INDEX_REL, index)
    return True, summary


def run_backfill(notify_fn=None, delay_sec=DEFAULT_DELAY_SECONDS):
    """
    저장된 queue 중 아직 처리하지 못한 일자를 1건씩 처리한다.

    notify_fn: 슬랙 등 알림 콜백(str). None 이면 print.
    delay_sec: 리포트 1건 완료 후 다음 호출까지 sleep 초.
    """
    def _emit(msg):
        if notify_fn:
            notify_fn(msg)
        else:
            print(msg, flush=True)

    if not drive_client.is_drive_enabled():
        _emit("[Backfill] Drive 가 비활성 상태입니다. 작업을 진행할 수 없습니다.")
        return {"started": 0, "ok": 0, "skipped": 0, "failed": 0}

    if drive_client.is_paused():
        _emit("[Backfill] Drive 가 Pause 상태입니다. 슬랙에 '완료' 를 입력해 해제한 뒤 다시 시도하세요.")
        return {"started": 0, "ok": 0, "skipped": 0, "failed": 0}

    if not drive_client.is_ready():
        ok, msg = drive_client.init_drive_or_pause(notify_fn)
        if not ok:
            _emit(f"[Backfill] Drive 초기화 실패: {msg}")
            return {"started": 0, "ok": 0, "skipped": 0, "failed": 0}

    state = _load_state()
    queue = state.get("queue") or []
    details = state.get("event_details") or {}
    processed = set(state.get("processed") or [])
    skipped_dates = {item["date"] for item in state.get("skipped", []) if isinstance(item, dict)}

    pending = [d for d in queue if d not in processed and d not in skipped_dates]
    if not pending:
        _emit("[Backfill] 처리할 대기 항목이 없습니다. 먼저 '!백필스캔'을 실행해 주세요.")
        return {"started": 0, "ok": 0, "skipped": 0, "failed": 0}

    _emit(
        f"[Backfill] 총 {len(pending)}건의 과거 시황 리포트 소급 작성을 시작합니다 "
        f"(건당 약 {delay_sec}초 대기)."
    )

    ok_cnt = 0
    skip_cnt = 0
    fail_cnt = 0

    for idx, date_str in enumerate(pending, 1):
        event = details.get(date_str)
        if not event:
            event = {"date": date_str, "trigger": "(트리거 정보 없음)"}

        _emit(f"[Backfill] ({idx}/{len(pending)}) {date_str} 처리 중... 트리거={event.get('trigger', '?')}")

        try:
            success, message = _write_chronicle_for_event(event)
        except drive_client.DrivePausedError as exc:
            _emit(
                f"[Backfill] Drive Pause 로 인해 작업이 중단되었습니다.\n"
                f"사유: {exc.reason}\n조치: {exc.action_required}\n"
                f"슬랙에 '완료' 입력 후 '!백필실행'으로 다시 시작하세요."
            )
            _save_state(
                {
                    **state,
                    "processed": sorted(processed),
                    "skipped": state.get("skipped", []),
                }
            )
            return {"started": idx, "ok": ok_cnt, "skipped": skip_cnt, "failed": fail_cnt}
        except Exception as exc:
            fail_cnt += 1
            err_msg = f"{type(exc).__name__}: {exc}"
            print(traceback.format_exc(), flush=True)
            state.setdefault("skipped", []).append(
                {"date": date_str, "reason": f"error:{err_msg[:200]}"}
            )
            _save_state(state)
            _emit(f"[Backfill] {date_str} 실패 (스킵): {err_msg}")
            time.sleep(max(0, delay_sec))
            continue

        if success:
            ok_cnt += 1
            processed.add(date_str)
            state["processed"] = sorted(processed)
            _save_state(state)
            _emit(f"[Backfill] {date_str} 완료: {message[:160]}")
        else:
            skip_cnt += 1
            state.setdefault("skipped", []).append(
                {"date": date_str, "reason": message[:200]}
            )
            _save_state(state)
            _emit(f"[Backfill] {date_str} 스킵: {message}")

        time.sleep(max(0, delay_sec))

    _emit(
        f"[Backfill] 종료. 완료 {ok_cnt}건 / 스킵 {skip_cnt}건 / 실패 {fail_cnt}건 / 총 {len(pending)}건 처리"
    )
    return {"started": len(pending), "ok": ok_cnt, "skipped": skip_cnt, "failed": fail_cnt}


def scan_and_save(lookback_days=DEFAULT_LOOKBACK_DAYS, notify_fn=None):
    """스캔 + 슬랙 보고 + Drive 큐 저장까지 한 번에 수행."""
    def _emit(msg):
        if notify_fn:
            notify_fn(msg)
        else:
            print(msg, flush=True)

    if not drive_client.is_drive_enabled():
        _emit("[Backfill] Drive 가 비활성 상태입니다. 스캔만 진행하고 큐 저장은 생략합니다.")
        events = scan_event_days(lookback_days)
        _emit(format_scan_report(events, lookback_days))
        return events

    if not drive_client.is_ready():
        ok, msg = drive_client.init_drive_or_pause(notify_fn)
        if not ok:
            _emit(f"[Backfill] Drive 초기화 실패: {msg}")
            return []

    events = scan_event_days(lookback_days)
    _emit(format_scan_report(events, lookback_days))
    if events:
        save_scan_state(events, lookback_days)
        _emit(
            f"[Backfill] 큐 저장 완료 ({len(events)}건). 진행하려면 '확인' 또는 '!백필실행' 을 입력하세요."
        )
    return events
