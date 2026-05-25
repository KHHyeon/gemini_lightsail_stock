# -*- coding: utf-8 -*-
"""Telegram Pipeline analysis 합성 + 가중치 폴백 단위 테스트 (임시).

실행:
    venv/bin/python tests/temp_test_telegram_analysis.py

시나리오:
    A) NVDA 호재 Mock -> analysis.related_kr_tickers 에 SUPPLIER 국내 종목 매핑.
    B) TSLA 가격 인하 Mock -> analysis.related_kr_tickers 에 RIVAL/CLIENT 매핑.
    C) SK하이닉스 가중치 시나리오: 국내 악재 + 해외 호재 동시 주입 시
       review_opinion_with_ai 가 해외 가중치를 따라 +1 delta 산출하는지 검증.
    D) 폴백 정책 시나리오: AI 응답이 모호("판단 보류")할 때 delta=0 +
       FALLBACK_REASON_AMBIGUOUS 사유로 폴백되는지 검증.

검증 완료 후 본 파일은 즉시 파기한다:
    rm tests/temp_test_telegram_analysis.py
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _print_header(title):
    line = "=" * 72
    print(f"\n{line}\n{title}\n{line}")


def _print_result(case, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {case}" + (f" | {detail}" if detail else ""))


def scenario_A_nvda_supplier():
    """A) NVDA 호재 -> SK하이닉스(000660) SUPPLIER 매핑."""
    _print_header("시나리오 A: NVDA 호재 -> 국내 SUPPLIER 매핑")
    from src.strategy import ai_logic
    from src.pipeline import telegram_pipeline as tp

    def fake_value_chain(symbol, context_text, sector_hint=None):
        if symbol == "NVDA":
            return {
                "related_kr_tickers": ["000660", "005930"],
                "value_chain_type": "SUPPLIER",
                "rationale": "NVIDIA HBM 수요는 SK하이닉스/삼성전자 메모리에 직결.",
            }
        return {"related_kr_tickers": [], "value_chain_type": None, "rationale": ""}

    orig_chain = ai_logic.analyze_value_chain
    ai_logic.analyze_value_chain = fake_value_chain

    raw_dict = {
        "channel_id": "@KiwoomResearch",
        "message_id": 5001,
        "posted_at": "2026-05-24T09:00:00+09:00",
        "raw_text": "NVDA 데이터센터 GPU 수요 폭발, 차세대 HBM3E 양산 본격화. 공급사 수혜 기대.",
    }

    try:
        normalized = tp.normalize_message(raw_dict)
    finally:
        ai_logic.analyze_value_chain = orig_chain

    fail_list = []
    if normalized is None:
        fail_list.append("normalize_message None 반환")
    else:
        analysis = normalized.get("analysis") or {}
        if analysis.get("category") != "OVERSEAS_STOCK":
            fail_list.append(f"category=OVERSEAS_STOCK 기대, 실제={analysis.get('category')!r}")
        if "000660" not in (analysis.get("related_kr_tickers") or []):
            fail_list.append(f"SK하이닉스(000660) 매핑 누락. 실제={analysis.get('related_kr_tickers')}")
        if analysis.get("value_chain_type") != "SUPPLIER":
            fail_list.append(f"value_chain_type=SUPPLIER 기대, 실제={analysis.get('value_chain_type')!r}")

    if not fail_list:
        print(f"  - category           : {normalized['analysis']['category']}")
        print(f"  - related_kr_tickers : {normalized['analysis']['related_kr_tickers']}")
        print(f"  - value_chain_type   : {normalized['analysis']['value_chain_type']}")

    _print_result("A. NVDA -> SUPPLIER 국내 매핑", not fail_list, "; ".join(fail_list))
    return not fail_list


def scenario_B_tsla_rival():
    """B) TSLA 가격 인하 -> 국내 RIVAL/CLIENT 매핑."""
    _print_header("시나리오 B: TSLA 가격 인하 -> RIVAL/CLIENT 매핑")
    from src.strategy import ai_logic
    from src.pipeline import telegram_pipeline as tp

    def fake_value_chain(symbol, context_text, sector_hint=None):
        if symbol == "TSLA":
            return {
                "related_kr_tickers": ["373220", "006400"],
                "value_chain_type": "CLIENT",
                "rationale": "테슬라 가격 인하는 LG에너지솔루션/삼성SDI 배터리 마진 압박.",
            }
        return {"related_kr_tickers": [], "value_chain_type": None, "rationale": ""}

    orig_chain = ai_logic.analyze_value_chain
    ai_logic.analyze_value_chain = fake_value_chain

    raw_dict = {
        "channel_id": "@OverseasResearch",
        "message_id": 5002,
        "posted_at": "2026-05-24T09:05:00+09:00",
        "raw_text": "TSLA Model Y 가격 추가 인하 단행. 배터리 단가 압박 확대 전망.",
    }

    try:
        normalized = tp.normalize_message(raw_dict)
    finally:
        ai_logic.analyze_value_chain = orig_chain

    fail_list = []
    if normalized is None:
        fail_list.append("normalize_message None 반환")
    else:
        analysis = normalized.get("analysis") or {}
        if analysis.get("category") != "OVERSEAS_STOCK":
            fail_list.append(f"category=OVERSEAS_STOCK 기대, 실제={analysis.get('category')!r}")
        if "373220" not in (analysis.get("related_kr_tickers") or []):
            fail_list.append(f"LG에너지솔루션(373220) 매핑 누락. 실제={analysis.get('related_kr_tickers')}")
        if analysis.get("value_chain_type") not in {"CLIENT", "RIVAL"}:
            fail_list.append(f"value_chain_type=CLIENT|RIVAL 기대, 실제={analysis.get('value_chain_type')!r}")

    if not fail_list:
        print(f"  - related_kr_tickers : {normalized['analysis']['related_kr_tickers']}")
        print(f"  - value_chain_type   : {normalized['analysis']['value_chain_type']}")

    _print_result("B. TSLA -> CLIENT/RIVAL 매핑", not fail_list, "; ".join(fail_list))
    return not fail_list


def scenario_C_sk_hynix_weight():
    """C) 국내 악재 + 해외 호재 동시 주입 시 해외 가중치 +1 산출."""
    _print_header("시나리오 C: SK하이닉스 - 국내 악재 vs 해외 호재 가중치 비교")
    from src.strategy import ai_logic

    # AI 응답을 명시적으로 모킹: 해외 가중치 우위 +1.
    def fake_generate(prompt, model_name=None):
        return "[+1]\n해외 필라델피아 반도체 지수 폭등이 메모리 수출주 SK하이닉스에 더 큰 가중치를 부여."

    orig_gen = ai_logic.generate_text
    ai_logic.generate_text = fake_generate

    telegram_insight_list = [{
        "source_channel": "@OverseasResearch",
        "text": "SOX(필라델피아 반도체 지수) 5% 폭등, AI 수요 재가속.",
        "analysis": {
            "category": "OVERSEAS_MARKET",
            "related_kr_tickers": ["000660", "005930"],
            "value_chain_type": None,
            "transmission_path": "필라델피아 반도체 지수 폭등이 환율을 통해 한국 메모리 수출주 수급 호조로 전이.",
        },
    }]
    domestic_news_list = [{
        "text": "한국 반도체 수출 둔화 우려, 중국 수요 부진 지속.",
        "analysis": {"category": "DOMESTIC_MARKET", "related_kr_tickers": ["000660"]},
    }]

    try:
        result = ai_logic.review_opinion_with_ai(
            "000660", "SK하이닉스", 72, "매수찬성",
            {"per": 8.5, "pbr": 1.4, "roe": 18.2},
            "단신: 외인 매수 전환",
            "테마: HBM/AI 메모리 대장",
            telegram_insight_list=telegram_insight_list,
            domestic_news_list=domestic_news_list,
        )
    finally:
        ai_logic.generate_text = orig_gen

    fail_list = []
    if result.get("delta") != 1:
        fail_list.append(f"delta=+1 기대, 실제={result.get('delta')!r}")
    if "해외" not in (result.get("reason") or ""):
        fail_list.append("reason 에 해외 가중치 결론 누락")

    if not fail_list:
        print(f"  - delta  : {result['delta']:+d}")
        print(f"  - reason : {result['reason']}")

    _print_result("C. 해외 호재 우위 +1 산출", not fail_list, "; ".join(fail_list))
    return not fail_list


def scenario_D_fallback_ambiguous():
    """D) AI 모호 응답 시 delta=0 + 폴백 사유 일관 로깅."""
    _print_header("시나리오 D: 모호 응답 -> 국내 펀더멘털 우선 폴백")
    from src.strategy import ai_logic

    def fake_generate(prompt, model_name=None):
        return "판단 보류\n추가 정보가 필요합니다."

    orig_gen = ai_logic.generate_text
    ai_logic.generate_text = fake_generate

    try:
        result = ai_logic.review_opinion_with_ai(
            "000660", "SK하이닉스", 72, "매수찬성",
            {"per": 8.5, "pbr": 1.4, "roe": 18.2},
            "단신 없음",
            "테마: HBM",
            telegram_insight_list=[],
            domestic_news_list=[],
        )
    finally:
        ai_logic.generate_text = orig_gen

    expected_reason = ai_logic.FALLBACK_REASON_AMBIGUOUS

    fail_list = []
    if result.get("delta") != 0:
        fail_list.append(f"delta=0 기대, 실제={result.get('delta')!r}")
    if result.get("reason") != expected_reason:
        fail_list.append(f"reason='{expected_reason}' 기대, 실제={result.get('reason')!r}")

    if not fail_list:
        print(f"  - delta  : {result['delta']}")
        print(f"  - reason : {result['reason']}")

    _print_result("D. 모호 응답 폴백", not fail_list, "; ".join(fail_list))
    return not fail_list


def main():
    a_ok = scenario_A_nvda_supplier()
    b_ok = scenario_B_tsla_rival()
    c_ok = scenario_C_sk_hynix_weight()
    d_ok = scenario_D_fallback_ambiguous()

    _print_header("최종 결과")
    print(f"  A. NVDA SUPPLIER 매핑      : {'PASS' if a_ok else 'FAIL'}")
    print(f"  B. TSLA CLIENT 매핑        : {'PASS' if b_ok else 'FAIL'}")
    print(f"  C. SK하이닉스 가중치 +1    : {'PASS' if c_ok else 'FAIL'}")
    print(f"  D. 모호 응답 폴백          : {'PASS' if d_ok else 'FAIL'}")

    if all([a_ok, b_ok, c_ok, d_ok]):
        print("\n[OK] 모든 시나리오 통과. 본 임시 스크립트는 즉시 파기하세요.")
        print("     삭제 명령: rm tests/temp_test_telegram_analysis.py")
        sys.exit(0)
    else:
        print("\n[FAIL] 하나 이상의 시나리오가 실패했습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
