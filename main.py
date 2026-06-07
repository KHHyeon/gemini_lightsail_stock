# -*- coding: utf-8 -*-
# .env 의 값을 import 시점에 결정하는 모듈(예: src.storage.state_store 의
# STATE_STORE_BACKEND 환경변수 분기)이 있으므로, load_dotenv() 는 다른 import
# 보다 반드시 먼저 호출해야 한다.
from dotenv import load_dotenv
load_dotenv()

import os, time, threading, schedule
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.core import kis_api
from src.execution.orchestrator import MarketOrchestrator
from src.execution import risk_monitor as risk_manager
from src.utils import slack_interface
from src.utils.timekit import KST
APP_KEY = os.getenv("APP_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ACC_NO = os.getenv("ACCOUNT_NO")
URL = "https://openapi.koreainvestment.com:9443"
CHANNEL_ID = os.getenv("SLACK_CHANNEL")
DART_API_KEY = os.getenv("DART_API_KEY")

CONFIG = {
    "APP_KEY": APP_KEY,
    "SECRET_KEY": SECRET_KEY,
    "ACC_NO": ACC_NO,
    "URL": URL,
    "CHANNEL_ID": CHANNEL_ID,
    "DART_API_KEY": DART_API_KEY
}

app = App(token=os.getenv("SLACK_TOKEN"))
kis = kis_api.KISClient()
orchestrator = MarketOrchestrator(kis, app, CONFIG)


def _bootstrap_market_chronicles():
    try:
        from src.memory import drive_client
        from src.memory.oauth_token import check_oauth_token_status, ensure_oauth_token_valid

        drive_client.register_oauth_notifier(orchestrator.send_slack)
        st = check_oauth_token_status()
        if st["exists"]:
            creds = ensure_oauth_token_valid(verbose=True)
            if creds is None and st["needs_reauth"]:
                orchestrator.send_slack(
                    "[OAuth] Drive 토큰 만료. 서버에서 "
                    "python scripts/drive_oauth_setup.py --no-browser 실행 필요"
                )
        drive_client.init_drive_or_pause(notify_fn=orchestrator.send_slack)
    except Exception as e:
        print(f"Log: [Chronicles Bootstrap] {e}", flush=True)


def _bootstrap_market_calendar_status():
    """기동 시 휴장일 파일 로드 상태와 오늘 거래일 여부를 슬랙으로 1회 알림.

    `data/krx_holidays.json` 누락 시 가드가 무력화되는 사태를 사용자가
    즉시 인지할 수 있도록 가시화한다. (조용한 SKIP 만 발생하는 기존 동작은
    공휴일에 자동매매가 잘못 진행되는 사고를 늦게 감지시키는 원인이었다.)
    """
    try:
        from src.utils import market_calendar as mc

        status = mc.get_holiday_load_status()
        is_trading = mc.is_trading_day()
        label = mc.get_holiday_label()
        if not status.get("file_exists"):
            msg = (
                "[Calendar][경고] data/krx_holidays.json 미존재. 공휴일/대체공휴일 "
                "차단 불가 (주말만 제외). 서버 git pull 또는 KRX_HOLIDAYS_EXTRA env 배포 필요."
            )
        else:
            if is_trading:
                msg = (
                    f"[Calendar] 휴장일 {status.get('count')}건 로드 "
                    f"(schema v{status.get('schema_version')}). 오늘은 거래일."
                )
            else:
                reason = label or ("주말" if label == "주말" else "휴장일")
                msg = (
                    f"[Calendar] 휴장일 {status.get('count')}건 로드 "
                    f"(schema v{status.get('schema_version')}). 오늘은 {reason} - "
                    "자동 매매/시황 routine SKIP, 정기보고만 수동 실행 가능."
                )
        orchestrator.send_slack(msg)
        print(f"Log: [Calendar] {msg}", flush=True)
    except Exception as exc:
        print(f"Log: [Calendar Bootstrap] {exc}", flush=True)


def _bootstrap_scalp_backtest():
    """기동 시 형태 백테스트 1회 실행 후 세션에 게이트 결과 반영."""
    try:
        from src.strategy import scalp_backtest
        from src.utils import slack_interface as si

        cached = scalp_backtest.load_persisted_result()
        if cached and cached.get("run_at"):
            result = cached
        else:
            result = scalp_backtest.run_and_persist(n_days=60)
        si.set_backtest_gate_result(result)
        print(
            f"Log: [ScalpBacktest] passes_gate={result.get('passes_gate')} "
            f"win_rate={result.get('win_rate')} total_return={result.get('total_return')}",
            flush=True,
        )
        return result
    except Exception as exc:
        print(f"Log: [ScalpBacktest] bootstrap failed: {exc}", flush=True)
        return None


def _is_first_trading_day(now=None):
    """주간 첫 거래일 여부 (공휴일 보정)."""
    from src.utils.market_calendar import is_first_trading_day_of_week
    return is_first_trading_day_of_week(now)


def _calendar_daily_notice():
    """매일 08:30 KST — 평일 휴장일이면 슬랙 1회 안내, 그 외엔 침묵.

    Doc/features/market_calendar/03_market_calendar_state_logic.md §3 참조.
    공휴일에 routine 들이 조용히 SKIP 되어 운영자가 인지하지 못하는 사태를
    방지한다. 토/일은 노이즈 회피를 위해 침묵한다.
    """
    try:
        from datetime import datetime as _dt
        from src.utils import market_calendar as mc
        from src.utils.timekit import now_kst

        current = now_kst()
        if current.weekday() >= 5:
            return
        if mc.is_trading_day(current):
            return
        label = mc.get_holiday_label(current) or "휴장일"
        orchestrator.send_slack(
            f"[Calendar] 오늘({current.strftime('%Y-%m-%d')}) 휴장 — 사유: {label}. "
            "자동 매매/시황 routine SKIP. 필요 시 수동 정기보고만 실행 가능."
        )
    except Exception as exc:
        print(f"Log: [Calendar Daily Notice] {exc}", flush=True)


def _scalp_pre_job():
    if not _is_first_trading_day():
        return
    orchestrator.scalp_pre_routine()


def _scalp_open_fallback_job():
    if not _is_first_trading_day():
        return
    orchestrator.scalp_force_default_at_open()


def _scalp_intraday_job():
    """장중 3분 주기: S_PRE 폴백 -> 포지션 없으면 S0 스캔, 있으면 S4 리스크 감시."""
    from src.utils import helpers as market_hours
    from src.utils import slack_interface as si
    from src.strategy import scalp_logic

    if not market_hours.is_market_open():
        return
    if scalp_logic.is_force_liquidation_time():
        return
    if not si.is_scalp_user_running():
        return
    if si.get_scalp_lifecycle() == si.SCALP_LIFECYCLE_PRE and si.get_weekly_budget() is None:
        si.try_budget_fallback_during_intraday()
        if si.get_weekly_budget() is None:
            return
    if si.has_scalp_position():
        orchestrator.scalp_risk_monitor_cycle()
    else:
        orchestrator.scalp_scan_cycle()


def run_scheduler():
    bt_result = _bootstrap_scalp_backtest()
    try:
        from src.memory import scalp_session_store
        scalp_session_store.bootstrap_scalp_session()
    except Exception as exc:
        print(f"Log: [ScalpSession] bootstrap failed: {exc}", flush=True)
    schedule.every().day.at("08:00").do(orchestrator.issue_daily_token)
    schedule.every().day.at("08:30").do(_calendar_daily_notice)
    schedule.every().day.at("08:45").do(orchestrator.daily_routine)
    schedule.every().day.at("08:50").do(lambda: orchestrator.auto_stock_discovery(KST))
    schedule.every().day.at("10:00").do(orchestrator.deep_market_routine)
    schedule.every().day.at("11:45").do(orchestrator.noon_routine)
    schedule.every().day.at("14:20").do(orchestrator.alert_manual_stocks)
    schedule.every().day.at("14:30").do(orchestrator.afternoon_routine)
    schedule.every().day.at("15:35").do(orchestrator.chronicle_routine)
    schedule.every().monday.at("09:45").do(orchestrator.weekly_routine)

    # 단타 스케줄: job 은 항상 등록, 실행 시 백테스트 PASS + 진행 ON 가드
    schedule.every().monday.at("08:30").do(_scalp_pre_job)
    schedule.every().monday.at("09:00").do(_scalp_open_fallback_job)
    schedule.every().day.at("15:10").do(orchestrator.scalp_force_liquidation)
    schedule.every(3).minutes.do(_scalp_intraday_job)
    if bt_result and bt_result.get("passes_gate"):
        print("Log: [ScalpSchedule] 백테스트 PASS - !단타시작 으로 진행 활성화 가능", flush=True)
    else:
        print("Log: [ScalpSchedule] 백테스트 FAIL - !단타백테스트 후 재시도 필요", flush=True)
    
    schedule.every(30).minutes.do(lambda: risk_manager.run_risk_monitor(
        kis, CONFIG, orchestrator.send_slack
    ))

    # Phase 4: SQLite -> GitHub backup orphan branch 자동 백업.
    # BACKUP_ENABLED=false (기본값) 면 schedule 등록 0건 -> Phase 1~3 회귀 0.
    # 상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §13.
    try:
        from src.storage.backup_scheduler import register_backup_jobs
        register_backup_jobs(schedule, notify_fn=orchestrator.send_slack)
    except Exception as exc:
        print(f"Log: [BACKUP] register_backup_jobs failed: {exc}", flush=True)

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    print("Log: [System] Active KST", flush=True)
    _bootstrap_market_chronicles()
    _bootstrap_market_calendar_status()
    slack_interface.register_slack_handlers(app, kis, CONFIG, orchestrator)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()

