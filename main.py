# -*- coding: utf-8 -*-
import os, time, threading, schedule
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.core import kis_api
from src.execution.orchestrator import MarketOrchestrator
from src.execution import risk_monitor as risk_manager
from src.utils import slack_interface
from src.utils.timekit import KST

load_dotenv()
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
    """주간 첫 거래일(월요일) 여부. 공휴일 보정은 후속."""
    from src.utils.timekit import now_kst
    current = now if now is not None else now_kst()
    return current.weekday() == 0


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
    schedule.every().day.at("08:00").do(orchestrator.issue_daily_token)
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
    
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    print("Log: [System] Active KST", flush=True)
    _bootstrap_market_chronicles()
    slack_interface.register_slack_handlers(app, kis, CONFIG, orchestrator)
    threading.Thread(target=run_scheduler, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()

