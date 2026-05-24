# -*- coding: utf-8 -*-
"""Telegram Pipeline 임시 검증 스크립트.

실행:
    python tests/temp_test_telegram.py

목적:
    1) 에러 격리: 강제 예외 발생 시 호출자에게 예외가 전파되지 않고 빈 결과를
       반환하는지 검증한다.
    2) 파이프라인 흐름: 더미 raw 메시지를 주입한 상태에서 run_ingestion() 의
       반환값이 telegram_ingestion_result_dict 스키마를 정확히 따르는지 검증.
    3) 의존성 단방향: 본 스크립트 실행 중 market_chronicles 관련 모듈이 단 한
       번도 import 되지 않는지 sys.modules 스냅샷으로 검증.

검증 완료 후 본 파일은 즉시 파기한다(아래 본문 마지막 안내 참조).
"""

from __future__ import annotations

import os
import sys
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# 스크립트 시작 시점의 sys.modules 스냅샷 (시나리오 3 비교 기준)
_BASELINE_MODULE_NAME_SET = set(sys.modules.keys())


def _print_header(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


def _print_result(case_label, ok, detail=""):
    status_text = "PASS" if ok else "FAIL"
    suffix = f" | {detail}" if detail else ""
    print(f"[{status_text}] {case_label}{suffix}")


def scenario_1_error_isolation():
    """시나리오 1: 강제 예외 발생 시 시스템 중단 없이 빈 리스트 반환."""
    _print_header("시나리오 1: 에러 격리 (Exception -> 빈 리스트)")

    from src.core import telegram_client

    fail_reason_list = []

    # 1-A: _fetch_single_channel 에서 예외 발생 -> fetch_new_messages 는 [] 반환
    original_fetch_single = telegram_client._fetch_single_channel
    original_is_configured = telegram_client.is_configured

    def _boom(channel_id, last_id):
        raise RuntimeError("강제 주입 예외 (boom)")

    try:
        telegram_client.is_configured = lambda: True
        telegram_client._fetch_single_channel = _boom

        result_list = telegram_client.fetch_new_messages(["c1", "c2"], {"c1": 0})
        if not isinstance(result_list, list):
            fail_reason_list.append("fetch_new_messages 반환 타입이 list 아님")
        if result_list != []:
            fail_reason_list.append(f"빈 리스트가 아닌 결과 반환: {result_list!r}")
    except Exception:
        fail_reason_list.append("fetch_new_messages 가 예외를 호출자에게 전파함")
        traceback.print_exc()
    finally:
        telegram_client._fetch_single_channel = original_fetch_single
        telegram_client.is_configured = original_is_configured

    _print_result(
        "1-A. telegram_client.fetch_new_messages 예외 격리",
        not fail_reason_list,
        "; ".join(fail_reason_list) if fail_reason_list else "빈 리스트 반환 확인",
    )

    # 1-B: run_ingestion 내부에서 예외 발생 -> status=transient_error 로 격리
    from src.pipeline import telegram_pipeline

    sub_fail_reason_list = []
    original_is_configured_pipe = telegram_client.is_configured
    original_load_default = telegram_pipeline._load_default_channel_id_list
    original_load_last_id = telegram_pipeline._load_last_id_map

    def _boom_load_last_id():
        raise RuntimeError("강제 주입 예외 (last_id_map 로드 실패)")

    try:
        telegram_client.is_configured = lambda: True
        telegram_pipeline._load_default_channel_id_list = lambda: ["c1"]
        telegram_pipeline._load_last_id_map = _boom_load_last_id

        result_dict = telegram_pipeline.run_ingestion()
    except Exception:
        sub_fail_reason_list.append("run_ingestion 이 예외를 호출자에게 전파함")
        traceback.print_exc()
        result_dict = None
    finally:
        telegram_client.is_configured = original_is_configured_pipe
        telegram_pipeline._load_default_channel_id_list = original_load_default
        telegram_pipeline._load_last_id_map = original_load_last_id

    if result_dict is None:
        sub_fail_reason_list.append("결과 dict 자체가 반환되지 않음")
    else:
        if result_dict.get("status") != "transient_error":
            sub_fail_reason_list.append(f"status='transient_error' 기대, 실제={result_dict.get('status')!r}")
        if result_dict.get("message_list") != []:
            sub_fail_reason_list.append("message_list 가 빈 리스트가 아님")

    _print_result(
        "1-B. telegram_pipeline.run_ingestion 예외 격리",
        not sub_fail_reason_list,
        "; ".join(sub_fail_reason_list) if sub_fail_reason_list else "status=transient_error 확인",
    )

    return not fail_reason_list and not sub_fail_reason_list


def scenario_2_pipeline_flow():
    """시나리오 2: 더미 메시지 주입 후 telegram_ingestion_result_dict 스키마 검증."""
    _print_header("시나리오 2: 파이프라인 흐름 + 반환 스키마 검증")

    from src.core import telegram_client
    from src.pipeline import telegram_pipeline

    fail_reason_list = []

    dummy_raw_message_list = [
        {
            "channel_id": "test_channel_alpha",
            "message_id": 1001,
            "posted_at": "2026-05-24T09:30:00+09:00",
            "raw_text": "[리서치] 반도체 업황 회복 기대, 외국인 매수 집중",
        },
        {
            "channel_id": "test_channel_alpha",
            "message_id": 1003,
            "posted_at": "2026-05-24T09:31:10+09:00",
            "raw_text": "  공백 정상화 테스트  ",
        },
        # 의도적 파싱 실패 케이스 (raw_text 누락) -> skipped_count 1 증가 기대
        {
            "channel_id": "test_channel_beta",
            "message_id": 2001,
            "posted_at": "2026-05-24T09:32:00+09:00",
            "raw_text": "",
        },
        # 정상 메시지 1건
        {
            "channel_id": "test_channel_beta",
            "message_id": 2005,
            "posted_at": "2026-05-24T09:33:00+09:00",
            "raw_text": "환율 변동 확대, 수출주 변동성 주의",
        },
    ]

    original_is_configured = telegram_client.is_configured
    original_fetch_new = telegram_client.fetch_new_messages
    original_load_default = telegram_pipeline._load_default_channel_id_list
    original_load_last_id = telegram_pipeline._load_last_id_map

    try:
        telegram_client.is_configured = lambda: True
        telegram_client.fetch_new_messages = lambda channel_id_list, last_id_map: dummy_raw_message_list
        telegram_pipeline._load_default_channel_id_list = lambda: ["test_channel_alpha", "test_channel_beta"]
        telegram_pipeline._load_last_id_map = lambda: {"test_channel_alpha": 1000, "test_channel_beta": 2000}

        result_dict = telegram_pipeline.run_ingestion()
    finally:
        telegram_client.is_configured = original_is_configured
        telegram_client.fetch_new_messages = original_fetch_new
        telegram_pipeline._load_default_channel_id_list = original_load_default
        telegram_pipeline._load_last_id_map = original_load_last_id

    expected_key_set = {"status", "message_list", "last_id_map", "skipped_count", "note"}
    actual_key_set = set(result_dict.keys()) if isinstance(result_dict, dict) else set()
    missing_key_set = expected_key_set - actual_key_set
    if missing_key_set:
        fail_reason_list.append(f"누락 키: {sorted(missing_key_set)}")

    if result_dict.get("status") != "ok":
        fail_reason_list.append(f"status='ok' 기대, 실제={result_dict.get('status')!r}")

    message_list = result_dict.get("message_list") or []
    if len(message_list) != 3:
        fail_reason_list.append(f"message_list 길이 3 기대, 실제={len(message_list)}")

    if result_dict.get("skipped_count") != 1:
        fail_reason_list.append(f"skipped_count=1 기대, 실제={result_dict.get('skipped_count')!r}")

    msg_key_set = {"source_channel", "message_id", "posted_at", "text", "keyword_list"}
    for idx, msg_dict in enumerate(message_list):
        diff = msg_key_set - set(msg_dict.keys())
        if diff:
            fail_reason_list.append(f"message[{idx}] 누락 키: {sorted(diff)}")

    last_id_map = result_dict.get("last_id_map") or {}
    if last_id_map.get("test_channel_alpha") != 1003:
        fail_reason_list.append(f"last_id_map.alpha=1003 기대, 실제={last_id_map.get('test_channel_alpha')!r}")
    if last_id_map.get("test_channel_beta") != 2005:
        fail_reason_list.append(f"last_id_map.beta=2005 기대, 실제={last_id_map.get('test_channel_beta')!r}")

    if not fail_reason_list:
        print(f"  - status         : {result_dict['status']}")
        print(f"  - message count  : {len(message_list)}")
        print(f"  - skipped_count  : {result_dict['skipped_count']}")
        print(f"  - last_id_map    : {result_dict['last_id_map']}")
        print(f"  - first message  : {message_list[0]}")

    _print_result(
        "2. run_ingestion 흐름 및 반환 스키마",
        not fail_reason_list,
        "; ".join(fail_reason_list) if fail_reason_list else "스키마 5 키 및 값 정합 확인",
    )

    return not fail_reason_list


def scenario_3_dependency_direction():
    """시나리오 3: 의존성 단방향 (market_chronicles 미 import) 검증."""
    _print_header("시나리오 3: 의존성 단방향 (market_chronicles 미 import)")

    forbidden_substring_list = [
        "chronicle_writer",
        "chronicle_common",
        "context_retriever",
        "src.memory.backfill",
    ]

    leaked_module_list = []
    for module_name in sys.modules.keys():
        for forbidden in forbidden_substring_list:
            if forbidden in module_name:
                leaked_module_list.append(module_name)
                break

    detail_text = (
        f"누설 모듈={leaked_module_list}" if leaked_module_list
        else "market_chronicles 계열 모듈 미 import 확인"
    )
    _print_result(
        "3. market_chronicles 계열 모듈 미 import",
        not leaked_module_list,
        detail_text,
    )

    expected_loaded_list = ["src.core.telegram_client", "src.pipeline.telegram_pipeline"]
    missing_loaded_list = [m for m in expected_loaded_list if m not in sys.modules]
    if missing_loaded_list:
        _print_result(
            "3-보조. 필수 모듈 로드 확인",
            False,
            f"미로드 모듈={missing_loaded_list}",
        )
        return False

    _print_result(
        "3-보조. 필수 모듈 로드 확인",
        True,
        f"로드 확인={expected_loaded_list}",
    )
    return not leaked_module_list


def main():
    print(f"[INFO] baseline modules count = {len(_BASELINE_MODULE_NAME_SET)}")

    s1_ok = scenario_1_error_isolation()
    s2_ok = scenario_2_pipeline_flow()
    s3_ok = scenario_3_dependency_direction()

    _print_header("최종 결과")
    print(f"  시나리오 1 (에러 격리)        : {'PASS' if s1_ok else 'FAIL'}")
    print(f"  시나리오 2 (파이프라인 흐름)  : {'PASS' if s2_ok else 'FAIL'}")
    print(f"  시나리오 3 (의존성 단방향)    : {'PASS' if s3_ok else 'FAIL'}")

    if s1_ok and s2_ok and s3_ok:
        print("\n[OK] 모든 시나리오 통과. 본 임시 스크립트는 즉시 파기하세요.")
        print("     삭제 명령: rm tests/temp_test_telegram.py && rmdir tests 2>/dev/null || true")
        sys.exit(0)
    else:
        print("\n[FAIL] 하나 이상의 시나리오가 실패했습니다. 위 로그를 확인하세요.")
        sys.exit(1)


if __name__ == "__main__":
    main()
