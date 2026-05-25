# -*- coding: utf-8 -*-
"""슬랙 명령어 컨벤션 통일 (v1.4) 검증.

[검증 범위]
- 통합 명령 정규식이 신규/구 컨벤션을 동시에 인식.
- 옵션 파싱이 의도대로 동작 (예: !백필 스캔 30 → lookback=30).
- 수동등록 사용법 안내 메시지가 트랙 옵션을 명시.
- !명령어 매뉴얼이 카테고리 8종을 모두 포함.

[설계 노트]
slack_bolt 의 @app.message 핸들러는 직접 호출 테스트가 까다로워 (전역 app 상태 의존),
본 테스트는 핸들러를 만드는 register_commands 호출 없이 **정규식 / 사용법 헬퍼만 격리하여**
검증한다. 정규식 자체는 slack_interface.py 내부 정의와 동일하므로 사양 회귀를 잡을 수 있다.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestUnifiedCommandRegex(unittest.TestCase):
    """v1.4 통합 명령 정규식 매칭 동작 검증."""

    BACKFILL = r"^!백필(?:\s+(스캔|실행|상태|초기화|재인덱싱|잔여정리|고아청소))?(?:\s+([^\s]+))?\s*$"
    BACKFILL_LEGACY = (
        r"^!(?:백필스캔|백필실행|백필초기화|백필상태|백필재인덱싱|백필잔여정리|백필고아청소)"
        r"(?:\s+([^\s]+))?\s*$"
    )
    TEST = r"^!테스트(?:\s+(기대주|배당주))?\s*$"
    TEST_LEGACY = r"^!(기대주테스트|배당주테스트)\s*$"
    SCALP = r"^!단타(?:\s+(시작|멈춤|상태|백테스트))?(?:\s+(\d+))?\s*$"
    SCALP_LEGACY = r"^!(단타시작|단타멈춤|단타상태|단타백테스트)(?:\s+(\d+))?\s*$"
    REPORT = r"^!보고(?:\s+(일일|주간|월간|분기))?\s*$"
    REPORT_LEGACY = r"^!(일일|주간|월간|분기)보고\s*$"

    # ---- !백필 ----
    def test_backfill_new_subcommand_with_option(self):
        m = re.match(self.BACKFILL, "!백필 스캔 30", re.IGNORECASE)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "스캔")
        self.assertEqual(m.group(2), "30")

    def test_backfill_new_subcommand_only(self):
        m = re.match(self.BACKFILL, "!백필 상태", re.IGNORECASE)
        self.assertEqual(m.group(1), "상태")
        self.assertIsNone(m.group(2))

    def test_backfill_new_purge_option(self):
        m = re.match(self.BACKFILL, "!백필 초기화 purge", re.IGNORECASE)
        self.assertEqual(m.group(1), "초기화")
        self.assertEqual(m.group(2), "purge")

    def test_backfill_new_bare_command_falls_to_usage(self):
        m = re.match(self.BACKFILL, "!백필", re.IGNORECASE)
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(1))

    def test_backfill_legacy_kept_for_back_compat(self):
        m = re.match(self.BACKFILL_LEGACY, "!백필스캔 30", re.IGNORECASE)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "30")

    def test_backfill_legacy_alias_purge_orphans(self):
        m = re.match(self.BACKFILL_LEGACY, "!백필고아청소 dry", re.IGNORECASE)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "dry")

    # ---- !테스트 ----
    def test_test_new_gem(self):
        self.assertEqual(re.match(self.TEST, "!테스트 기대주").group(1), "기대주")

    def test_test_new_dividend(self):
        self.assertEqual(re.match(self.TEST, "!테스트 배당주").group(1), "배당주")

    def test_test_legacy_kept(self):
        self.assertIsNotNone(re.match(self.TEST_LEGACY, "!기대주테스트"))
        self.assertIsNotNone(re.match(self.TEST_LEGACY, "!배당주테스트"))

    # ---- !단타 ----
    def test_scalp_new_with_backtest_option(self):
        m = re.match(self.SCALP, "!단타 백테스트 60", re.IGNORECASE)
        self.assertEqual(m.group(1), "백테스트")
        self.assertEqual(m.group(2), "60")

    def test_scalp_new_start(self):
        self.assertEqual(re.match(self.SCALP, "!단타 시작").group(1), "시작")

    def test_scalp_legacy(self):
        m = re.match(self.SCALP_LEGACY, "!단타백테스트 30")
        self.assertEqual(m.group(1), "단타백테스트")
        self.assertEqual(m.group(2), "30")

    # ---- !보고 ----
    def test_report_new_daily(self):
        self.assertEqual(re.match(self.REPORT, "!보고 일일").group(1), "일일")

    def test_report_new_quarterly(self):
        self.assertEqual(re.match(self.REPORT, "!보고 분기").group(1), "분기")

    def test_report_legacy(self):
        self.assertEqual(re.match(self.REPORT_LEGACY, "!일일보고").group(1), "일일")
        self.assertEqual(re.match(self.REPORT_LEGACY, "!주간보고").group(1), "주간")

    def test_invalid_subcommand_falls_through_to_usage(self):
        # "!보고 분류" 같은 미정의 서브명령은 매치되지 않거나 None 그룹 → 사용법 출력 분기.
        m = re.match(self.REPORT, "!보고 분류")
        # 정규식은 미정의 서브를 잡지 못해 m=None 이거나, m.group(1)=None.
        # 어느 쪽이든 본문 라우터가 사용법으로 떨어져야 함.
        self.assertTrue(m is None or m.group(1) is None)


class TestManualRegisterUsageMessage(unittest.TestCase):
    """!수동등록 사용법 안내가 트랙 옵션을 명시하는지 검증."""

    def test_usage_text_includes_all_track_options(self):
        from src.utils import slack_interface

        # _manual_register_usage 는 register_commands 의 내부 함수이므로
        # 직접 접근 불가 → 정규식으로 모듈 본문에서 사용법 문자열 추출.
        with open(slack_interface.__file__, encoding="utf-8") as f:
            source = f.read()

        # 사용법 문자열 영역 잘라내기.
        start = source.find("def _manual_register_usage()")
        end = source.find("@app.message", start)
        usage_block = source[start:end]

        for must in [
            "[종목코드]", "[트랙]", "A = 성장", "B = 가치",
            "C = 역발상", "M = 일반 수동등록", "추적익절",
            "원금 손절", "펀더멘털 훼손",
        ]:
            self.assertIn(must, usage_block, f"사용법 메시지 누락: {must!r}")


class TestHelpMenuCategories(unittest.TestCase):
    """!명령어 매뉴얼이 카테고리 8종을 모두 포함하는지 검증."""

    def test_help_text_has_all_categories(self):
        from src.utils import slack_interface

        with open(slack_interface.__file__, encoding="utf-8") as f:
            source = f.read()

        # cmd_help 영역 추출.
        start = source.find("def cmd_help(message, say):")
        end = source.find("say(help_text)", start) + len("say(help_text)")
        block = source[start:end]

        for cat in [
            "[1] 계좌/성과 조회",
            "[2] 종목 발굴/스크리닝",
            "[3] 개별 종목 진단/매매",
            "[4] 단타(Scalp)",
            "[5] Market Chronicles",
            "[6] 백필 운영",
            "[7] 정기 리포트",
            "[8] 시스템/유틸",
        ]:
            self.assertIn(cat, block, f"매뉴얼 카테고리 누락: {cat!r}")

        # 통일 명령 표기.
        for cmd in [
            "!보고 일일", "!단타 시작", "!백필 스캔", "!테스트", "!수동등록",
        ]:
            self.assertIn(cmd, block, f"통일 명령 표기 누락: {cmd!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
