# -*- coding: utf-8 -*-
"""거래일·토큰 정책·단타 세션 영속화 단위 테스트.

실행: venv/bin/python3 tests/temp_test_market_calendar_and_token.py
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.utils.timekit import KST
from src.utils import market_calendar as mc
from src.core import token_manager as tm
from src.memory import scalp_session_store as store
from src.utils import slack_interface as si


class TestMarketCalendar(unittest.TestCase):
    def setUp(self):
        mc.load_holiday_date_set(reload=True)

    def test_weekend_not_trading_day(self):
        sat = datetime(2026, 5, 23, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(sat))

    def test_holiday_not_trading_day(self):
        holiday = datetime(2026, 1, 1, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(holiday))

    def test_weekday_non_holiday_is_trading_day(self):
        day = datetime(2026, 5, 22, 10, 0, tzinfo=KST)  # 금요일
        self.assertTrue(mc.is_trading_day(day))

    def test_market_hours_before_open(self):
        pre = datetime(2026, 5, 22, 8, 50, tzinfo=KST)
        self.assertFalse(mc.is_market_hours(pre))

    def test_market_hours_during_session(self):
        mid = datetime(2026, 5, 22, 10, 0, tzinfo=KST)
        self.assertTrue(mc.is_market_hours(mid))

    def test_first_trading_day_when_monday_holiday(self):
        # 2026-03-02 (월)은 삼일절 대체공휴일 → 거래일 아님.
        # 2026-03-03 (화)이 그 주의 첫 거래일.
        mon = datetime(2026, 3, 2, 9, 0, tzinfo=KST)
        tue = datetime(2026, 3, 3, 9, 0, tzinfo=KST)
        self.assertFalse(mc.is_first_trading_day_of_week(mon))
        self.assertTrue(mc.is_first_trading_day_of_week(tue))

    def test_substitute_holiday_2026_05_25_buddha(self):
        """2026-05-25 부처님오신날 대체공휴일 (5/24 일요일) — 거래일 아님."""
        day = datetime(2026, 5, 25, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))
        self.assertFalse(mc.is_market_hours(day))

    def test_substitute_holiday_2026_08_17_liberation(self):
        """2026-08-17 광복절 대체공휴일 (8/15 토요일) — 거래일 아님."""
        day = datetime(2026, 8, 17, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))

    def test_election_day_2026_06_03(self):
        """2026-06-03 제8회 전국동시지방선거 — 거래일 아님."""
        day = datetime(2026, 6, 3, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))

    def test_constitution_day_2026_07_17(self):
        """2026-07-17 제헌절 부활 — 거래일 아님."""
        day = datetime(2026, 7, 17, 10, 0, tzinfo=KST)
        self.assertFalse(mc.is_trading_day(day))

    def test_chuseok_2026_correct_dates(self):
        """2026 추석은 9/24~25 (목/금). 10/6~10/8 은 정상 거래일."""
        self.assertFalse(mc.is_trading_day(datetime(2026, 9, 24, 10, 0, tzinfo=KST)))
        self.assertFalse(mc.is_trading_day(datetime(2026, 9, 25, 10, 0, tzinfo=KST)))
        self.assertTrue(mc.is_trading_day(datetime(2026, 10, 6, 10, 0, tzinfo=KST)))
        self.assertTrue(mc.is_trading_day(datetime(2026, 10, 7, 10, 0, tzinfo=KST)))
        self.assertTrue(mc.is_trading_day(datetime(2026, 10, 8, 10, 0, tzinfo=KST)))

    def test_holiday_label_lookup(self):
        """get_holiday_label 이 사유 라벨을 정확히 반환."""
        label = mc.get_holiday_label(datetime(2026, 5, 25, 10, 0, tzinfo=KST))
        self.assertIsNotNone(label)
        self.assertIn("부처님오신날", label)
        # 거래일은 None
        self.assertIsNone(mc.get_holiday_label(datetime(2026, 5, 22, 10, 0, tzinfo=KST)))
        # 토/일은 "주말"
        self.assertEqual(
            mc.get_holiday_label(datetime(2026, 5, 23, 10, 0, tzinfo=KST)),
            "주말",
        )

    def test_holiday_load_status(self):
        """get_holiday_load_status 가 정상 dict 를 반환."""
        status = mc.get_holiday_load_status()
        self.assertTrue(status["loaded"])
        self.assertTrue(status["file_exists"])
        self.assertGreater(status["count"], 0)
        self.assertEqual(status["schema_version"], 2)

    def test_auto_discovery_guard_holiday(self):
        from src.execution.orchestrator import MarketOrchestrator
        from unittest.mock import MagicMock

        orch = MarketOrchestrator(MagicMock(), MagicMock(), {})
        with patch("src.execution.orchestrator.market_hours.is_trading_day", return_value=False):
            with patch.object(orch, "send_slack") as slack_mock:
                orch.auto_stock_discovery(KST)
        slack_mock.assert_not_called()


class TestTokenPolicy(unittest.TestCase):
    def setUp(self):
        self.token_path = tm._token_path()
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def tearDown(self):
        if os.path.exists(self.token_path):
            os.remove(self.token_path)

    def test_scheduled_skip_on_holiday(self):
        with patch("src.utils.market_calendar.is_trading_day", return_value=False):
            result = tm.issue_scheduled_token("k", "s")
        self.assertFalse(result["issued"])
        self.assertEqual(result["reason"], "not_trading_day")

    def test_on_demand_issues_when_cache_missing(self):
        with patch.object(tm, "_request_new_token", return_value="NEW_TOKEN") as req:
            token = tm.get_access_token("k", "s", context="on_demand")
        self.assertEqual(token, "NEW_TOKEN")
        req.assert_called_once()

    def test_scheduled_respects_min_interval(self):
        recent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        from src.utils.jsonio import write_local_json
        write_local_json(tm._token_path(), {
            "access_token": "OLD",
            "issued_at": recent,
        }, indent=2)
        with patch("src.utils.market_calendar.is_trading_day", return_value=True):
            with patch.object(tm, "_request_new_token") as req:
                result = tm.issue_scheduled_token("k", "s")
        self.assertFalse(result["issued"])
        self.assertEqual(result["reason"], "min_interval")
        req.assert_not_called()


class TestScalpSessionStore(unittest.TestCase):
    def setUp(self):
        self.drive_patcher = patch("src.utils.logger._use_drive_storage", return_value=False)
        self.drive_patcher.start()
        si.reset_weekly_budget_session()
        si.stop_scalp_trading()
        si.clear_scalp_position()
        self.session_file = os.path.join(ROOT, store.SCALP_SESSION_FILENAME)
        if os.path.exists(self.session_file):
            os.remove(self.session_file)

    def tearDown(self):
        self.drive_patcher.stop()
        if os.path.exists(self.session_file):
            os.remove(self.session_file)

    def test_persist_and_restore(self):
        si._scalp_session_dict["is_user_running"] = True
        si.set_weekly_budget(50_000, via="test")
        self.assertTrue(store.persist_scalp_session_from_module())
        loaded = store.load_scalp_session()
        self.assertIsInstance(loaded, dict)
        self.assertTrue(loaded.get("is_user_running"))
        self.assertEqual(loaded.get("amount"), 50_000)
        # 로컬 fallback 경로에도 기록 (Drive 비활성 테스트)
        self.assertTrue(os.path.exists(self.session_file))
        # 메모리만 초기화 (저장본은 유지)
        si._scalp_session_dict["is_user_running"] = False
        si._scalp_session_dict["amount"] = None
        result = store.restore_scalp_session_to_module()
        self.assertTrue(result["restored"])
        self.assertTrue(si.is_scalp_user_running())
        self.assertEqual(si.get_weekly_budget(), 50_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
