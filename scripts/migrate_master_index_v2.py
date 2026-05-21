#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Master Index v1 -> v2 마이그레이션 스크립트 (v3.4).

SYS §7.5 / DETAIL CHRONICLES §7 의 4단계 절차:
  1. Scan  : Drive 의 master_index.json (version=1) 을 읽어, v1 의 엔트리별
             자유형 ``regime`` / ``keywords`` / ``keyphrases`` / ``guideline_summary``
             를 추출하고 1차 매핑 결과를 큐로 분류한다.
  2. Backup: 변환 직전 ``master_index.json`` 전체를
             ``MarketChronicles/_system/backups/master_index_v1_<KST>.json`` 으로 복사.
  3. AI 보강: 1차 매핑 결정 불가 또는 v3.2 ``keyphrases`` 미보유 엔트리에 대해
             AI 1회 호출로 ``phrases_list`` 보강 + ``market_state`` 4필드 산출
             (``chronicle_common.derive_market_state``) + ``context_tags_list``
             산출 (``chronicle_common.derive_context_tags``).
  4. Apply : 모든 엔트리를 v2 평탄화 dict 로 정렬한 뒤
             ``drive_client.write_master_index({"version": 2, "entries": [...]})`` 단일 호출.

명령행 사용:
  python scripts/migrate_master_index_v2.py --dry-run
  python scripts/migrate_master_index_v2.py --apply
  python scripts/migrate_master_index_v2.py --apply --no-ai
  python scripts/migrate_master_index_v2.py --apply --limit 5
  python scripts/migrate_master_index_v2.py --apply --delay-sec 5

자동 실행 진입점 (``AUTO_MIGRATE_V2=1`` 시 drive_client.read_master_index 가 호출):
  migrate_in_process(ai_enabled=True, delay_sec=3) -> summary_dict
"""
import argparse
import time
import traceback
from collections import Counter

from _common import load_env_file, print_flush, setup_script_path

setup_script_path()
load_env_file(verbose=True)

from src.memory import chronicle_common, drive_client  # noqa: E402
from src.memory.keyphrase_extractor import extract_keyphrases  # noqa: E402
from src.utils.macro_triggers import (  # noqa: E402
    REGIME_SIDEWAYS,
    _safe_float,
    map_regime_from_text,
)
from src.utils.timekit import kst_iso_now, kst_strftime  # noqa: E402


def _is_v2_entry(entry):
    """이미 v2 평탄화 4필드를 모두 보유한 엔트리인지 판정."""
    if not isinstance(entry, dict):
        return False
    if "market_state" not in entry or "context_tags_list" not in entry:
        return False
    if "action_preview" not in entry:
        return False
    return True


def _scan_v1_entries(entries_list):
    """v1 엔트리를 분류한다.

    Returns:
        dict: ``{"v2_already": list, "v1_resolved": list, "v1_ai_needed": list}``
            모두 ``(idx, entry_dict)`` 튜플 리스트.
    """
    result = {"v2_already": [], "v1_resolved": [], "v1_ai_needed": []}

    for idx, entry in enumerate(entries_list or []):
        if not isinstance(entry, dict):
            result["v1_ai_needed"].append((idx, entry or {}))
            continue
        if _is_v2_entry(entry):
            result["v2_already"].append((idx, entry))
            continue

        regime_text = entry.get("regime") or ""
        mapped = map_regime_from_text(regime_text)
        phrases_v1 = entry.get("keyphrases") or []
        if mapped and phrases_v1:
            result["v1_resolved"].append((idx, entry))
        else:
            result["v1_ai_needed"].append((idx, entry))

    return result


def _coerce_action_preview(entry, body_fallback):
    """기존 ``guideline_summary`` 또는 본문에서 200자 슬라이싱한 ``action_preview`` 추출."""
    legacy = entry.get("action_preview") or entry.get("guideline_summary")
    if legacy:
        return str(legacy)[:200]
    if body_fallback:
        try:
            return chronicle_common.parse_action_preview(body_fallback)
        except Exception:
            return body_fallback[:200]
    return ""


def _regex_fallback_main_actor(entry):
    """v1 ``keyphrases`` 의 최빈 subject 로 main_actor 폴백."""
    phrases_v1 = entry.get("keyphrases") or []
    if not phrases_v1:
        return ""
    subj_counter = Counter()
    for ph in phrases_v1:
        if isinstance(ph, dict) and ph.get("subject"):
            subj_counter[str(ph["subject"]).strip()] += 1
    if not subj_counter:
        return ""
    return subj_counter.most_common(1)[0][0]


def _regex_fallback_context_tags(entry, market_state_dict, max_tags=6):
    """v1 ``keywords`` + ``regime_label`` 단어를 ``_`` 결합 태그로 단순 변환."""
    raw_keywords = entry.get("keywords") or []
    tag_set = set()
    tag_list = []
    for kw in raw_keywords:
        if not kw:
            continue
        token = str(kw).replace(" ", "_").strip("_")
        if not token or token in tag_set:
            continue
        tag_set.add(token)
        tag_list.append(token)
        if len(tag_list) >= max_tags - 1:
            break

    regime_label = (market_state_dict or {}).get("regime_label") or ""
    if regime_label:
        label_token = (
            regime_label.split(" ")[0].split("(")[0].strip().replace(" ", "_")
        )
        if label_token and label_token not in tag_set:
            tag_set.add(label_token)
            tag_list.append(label_token)
    return tag_list[:max_tags]


def _build_v2_entry_from_v1(
    entry_v1, *, ai_enabled=True, body_cache=None, emit=print_flush
):
    """v1 엔트리 1건을 v2 평탄화 dict 로 변환한다.

    실패 시에도 최대한 정규식 폴백으로 채워 빈 dict 가 나오지 않도록 한다.
    """
    body_text = ""
    rel_path = entry_v1.get("report_rel_path")
    if rel_path:
        if body_cache is not None and rel_path in body_cache:
            body_text = body_cache[rel_path]
        else:
            try:
                body_text = drive_client.read_text_relative(rel_path) or ""
            except Exception as exc:
                emit(f"  [WARN] 본문 읽기 실패 ({rel_path}): {exc}")
                body_text = ""
            if body_cache is not None:
                body_cache[rel_path] = body_text

    phrases_list = entry_v1.get("keyphrases") or []
    needs_ai = not phrases_list
    if needs_ai and ai_enabled and body_text.strip():
        try:
            phrases_list = extract_keyphrases(body_text, max_phrases=12, ai_enabled=True)
        except Exception as exc:
            emit(f"  [WARN] AI keyphrase 추출 실패, 정규식 폴백 진행: {exc}")
            phrases_list = []

    regime_label_legacy = entry_v1.get("regime") or ""
    market_state_dict = chronicle_common.derive_market_state(
        phrases_list,
        vix=_safe_float(entry_v1.get("vix_close"), default=0.0),
        kospi_chg=_safe_float(entry_v1.get("kospi_chg"), default=0.0),
        kosdaq_chg=_safe_float(entry_v1.get("kosdaq_chg"), default=0.0),
        regime_label_override=regime_label_legacy or None,
    )

    mapped_enum = map_regime_from_text(regime_label_legacy)
    if mapped_enum:
        market_state_dict["regime"] = mapped_enum
    elif not market_state_dict.get("regime"):
        market_state_dict["regime"] = REGIME_SIDEWAYS

    if not market_state_dict.get("main_actor"):
        market_state_dict["main_actor"] = _regex_fallback_main_actor(entry_v1)

    context_tags_list = chronicle_common.derive_context_tags(
        phrases_list, market_state_dict
    )
    if not context_tags_list:
        context_tags_list = _regex_fallback_context_tags(entry_v1, market_state_dict)

    action_preview = _coerce_action_preview(entry_v1, body_text)

    v2_entry = {
        "id": entry_v1.get("id"),
        "date": entry_v1.get("date"),
        "trigger": entry_v1.get("trigger", ""),
        "market_state": market_state_dict,
        "context_tags_list": context_tags_list,
        "action_preview": action_preview,
        "phrases_list": phrases_list,
        "embedding_vector": None,
        "report_rel_path": rel_path,
        "source": entry_v1.get("source", "backfill"),
        "migrated_at": kst_iso_now(),
    }
    if entry_v1.get("reindexed_at"):
        v2_entry["reindexed_at"] = entry_v1["reindexed_at"]
    return v2_entry


def _backup_master_index(emit):
    """현재 master_index.json 전체를 Drive 백업 폴더에 복사."""
    raw_index = drive_client._read_json_direct(drive_client.MASTER_INDEX_REL)
    if raw_index is None:
        emit("  [INFO] master_index.json 파일이 없습니다. 백업 생략.")
        return None
    ts = kst_strftime("%Y%m%d_%H%M%S")
    backup_rel = f"{drive_client.CHRONICLES_ROOT}/_system/backups/master_index_v1_{ts}.json"
    drive_client.write_json_relative(backup_rel, raw_index)
    emit(f"  [OK] 백업 완료: {backup_rel}")
    return backup_rel


def _emit_scan_report(scan_result_dict, emit):
    emit(
        f"  v2 이미 적용: {len(scan_result_dict['v2_already'])}건 / "
        f"v1 1차 매핑 성공: {len(scan_result_dict['v1_resolved'])}건 / "
        f"v1 AI 보강 필요: {len(scan_result_dict['v1_ai_needed'])}건"
    )


def _build_summary(v2_entries_list, ai_call_count):
    regime_counter = Counter()
    tag_total = 0
    for entry in v2_entries_list:
        regime = (entry.get("market_state") or {}).get("regime")
        if regime:
            regime_counter[regime] += 1
        tag_total += len(entry.get("context_tags_list") or [])
    avg_tags = round(tag_total / max(1, len(v2_entries_list)), 2)
    return {
        "total": len(v2_entries_list),
        "ai_calls": ai_call_count,
        "regime_dist": dict(regime_counter),
        "avg_context_tags": avg_tags,
    }


def _print_summary(summary_dict, emit):
    emit("[Migrate v2] === 마이그레이션 결과 요약 ===")
    emit(f"  처리 엔트리: {summary_dict['total']}건")
    emit(f"  AI 호출 횟수: {summary_dict['ai_calls']}건")
    emit(f"  context_tags_list 평균 태그 수: {summary_dict['avg_context_tags']}")
    emit("  regime 분포:")
    for regime, count in sorted(summary_dict["regime_dist"].items()):
        emit(f"    - {regime}: {count}")


def migrate_in_process(
    *, ai_enabled=True, delay_sec=3, limit=None, dry_run=False, emit=print_flush
):
    """In-process 진입점 (AUTO_MIGRATE_V2=1 자동 모드와 CLI 모두 공용).

    Args:
        ai_enabled: True 면 v1 엔트리 중 keyphrases 미보유 항목에 AI 1회 호출.
        delay_sec: AI 호출 사이 대기 초.
        limit: 처리 엔트리 수 상한 (None=무제한, 테스트용).
        dry_run: True 면 Backup/Apply 단계를 건너뛰고 변환 결과만 stdout 보고.
        emit: 로그 콜백 (기본 print_flush).

    Returns:
        dict: 처리 결과 요약 (``total``, ``ai_calls``, ``regime_dist``,
        ``avg_context_tags``).
    """
    emit("[Migrate v2] === 1단계: Scan ===")
    raw_index = drive_client._read_json_direct(drive_client.MASTER_INDEX_REL) or {}
    detected_version = raw_index.get("version", 1)
    entries_v1_list = raw_index.get("entries") or []
    emit(f"  현재 master_index.json: version={detected_version}, "
         f"entries={len(entries_v1_list)}")

    if detected_version == drive_client.MASTER_INDEX_EXPECTED_VERSION:
        emit("  [INFO] 이미 version=2 입니다. 마이그레이션 불필요.")
        return _build_summary(entries_v1_list, 0)

    scan_result_dict = _scan_v1_entries(entries_v1_list)
    _emit_scan_report(scan_result_dict, emit)

    if dry_run:
        emit("[Migrate v2] === DRY-RUN 종료 (Backup / Apply 단계 미실행) ===")
        sample_iter = (
            scan_result_dict["v1_resolved"][:3] + scan_result_dict["v1_ai_needed"][:3]
        )
        emit("  변환 미리보기 (최대 6건, AI 호출 없음):")
        for _idx, entry in sample_iter:
            preview_v2 = _build_v2_entry_from_v1(
                entry, ai_enabled=False, body_cache={}, emit=lambda _m: None
            )
            ms = preview_v2.get("market_state") or {}
            tag_text = " / ".join((preview_v2.get("context_tags_list") or [])[:4])
            emit(
                f"    - {preview_v2.get('date')} | regime={ms.get('regime')} "
                f"| tags=[{tag_text}] | action={preview_v2.get('action_preview', '')[:60]}..."
            )
        return {
            "total": len(entries_v1_list),
            "ai_calls": 0,
            "regime_dist": {},
            "avg_context_tags": 0.0,
        }

    emit("[Migrate v2] === 2단계: Backup ===")
    _backup_master_index(emit)

    emit("[Migrate v2] === 3단계: AI 보강 + 변환 ===")
    new_entries_list = []
    ai_call_count = 0
    body_cache = {}
    work_list = []
    for idx, entry in enumerate(entries_v1_list or []):
        work_list.append((idx, entry))
    if limit is not None:
        work_list = work_list[: int(limit)]

    for n, (idx, entry) in enumerate(work_list, 1):
        if _is_v2_entry(entry):
            new_entries_list.append(entry)
            continue

        date_str = (entry or {}).get("date", "?")
        emit(f"  ({n}/{len(work_list)}) {date_str} 변환 중...")
        needs_ai = not (entry or {}).get("keyphrases")
        try:
            v2_entry = _build_v2_entry_from_v1(
                entry or {},
                ai_enabled=ai_enabled and needs_ai,
                body_cache=body_cache,
                emit=emit,
            )
        except Exception as exc:
            emit(f"  [ERR] {date_str} 변환 실패, 원본 보존: {exc}")
            print_flush(traceback.format_exc())
            new_entries_list.append(entry)
            continue
        new_entries_list.append(v2_entry)
        if needs_ai and ai_enabled:
            ai_call_count += 1
            time.sleep(max(0, delay_sec))

    emit("[Migrate v2] === 4단계: Apply ===")
    drive_client.write_master_index(
        {
            "version": drive_client.MASTER_INDEX_EXPECTED_VERSION,
            "entries": new_entries_list,
        }
    )
    emit(f"  [OK] master_index.json 갱신 완료 (version=2, entries={len(new_entries_list)})")

    summary_dict = _build_summary(new_entries_list, ai_call_count)
    _print_summary(summary_dict, emit)
    return summary_dict


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Master Index v1 -> v2 마이그레이션 (v3.4)"
    )
    parser.add_argument("--dry-run", action="store_true", help="변환 결과만 stdout 보고 (Backup/Apply 미실행)")
    parser.add_argument("--apply", action="store_true", help="실제 Drive 에 변환 결과 덮어쓰기")
    parser.add_argument("--no-ai", action="store_true", help="AI 호출 비활성 (정규식 폴백만 사용)")
    parser.add_argument("--limit", type=int, default=None, help="처리 엔트리 수 상한 (테스트용)")
    parser.add_argument("--delay-sec", type=int, default=3, help="AI 호출 사이 대기 초 (기본 3)")
    return parser.parse_args()


def main():
    args = _parse_args()
    if not args.dry_run and not args.apply:
        print_flush(
            "[Migrate v2] --dry-run 또는 --apply 를 지정하세요.\n"
            "  예: python scripts/migrate_master_index_v2.py --dry-run"
        )
        return 1

    if not drive_client.is_drive_configured():
        print_flush("[Migrate v2] Drive 인증이 설정되어 있지 않습니다. .env 를 확인하세요.")
        return 1

    if not drive_client.is_ready():
        ok, msg = drive_client.init_drive_or_pause()
        if not ok:
            print_flush(f"[Migrate v2] Drive 초기화 실패: {msg}")
            return 1

    migrate_in_process(
        ai_enabled=not args.no_ai,
        delay_sec=args.delay_sec,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
