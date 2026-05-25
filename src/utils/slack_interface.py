# -*- coding: utf-8 -*-
import re, uuid, os, threading
from datetime import datetime
from src.core import token_manager
from src.data.crawler import news_crawler, theme_crawler, stock_info_crawler, research_crawler
from src.data import collector as macro_collector, chart as chart_data
from src.strategy import ai_logic as ai_strategy, screener as quant_screener, finder as stock_finder
from src.execution.order import OrderManager
from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive

pending_orders = {}

# =====================================================================
# 주간 단타 예산 세션 (S_PRE -> S0 전이용)
# =====================================================================
# orchestrator/scalp_logic 가 import 후 set/get 으로 접근한다.
# 멀티프로세스를 가정하지 않으므로 모듈 전역 dict 로 충분.
DEFAULT_WEEKLY_BUDGET = 50_000
SCALP_LIFECYCLE_STOPPED = "STOPPED"
SCALP_LIFECYCLE_PRE = "S_PRE"
SCALP_LIFECYCLE_SCANNING = "S0"
SCALP_LIFECYCLE_FILTERED = "S1"
SCALP_LIFECYCLE_VALIDATING = "S2"
SCALP_LIFECYCLE_EXECUTED = "S3"
SCALP_LIFECYCLE_RISK = "S4"
SCALP_LIFECYCLE_LIQUIDATED = "S5"

_scalp_session_dict = {
    "amount": None,
    "is_pending_custom": False,
    "set_via": None,
    "set_at": None,
    "lifecycle": SCALP_LIFECYCLE_STOPPED,
    "is_user_running": False,
    "backtest_passed": False,
    "last_backtest": None,
    "started_at": None,
    "stopped_at": None,
    "position": None,
    "budget_requested_at": None,
    "hts_condition_name": None,
}

# 예산 무응답 폴백: 장 개시 09:00 또는 요청 후 N분 경과
DEFAULT_BUDGET_TIMEOUT_MIN = 30


def _persist_scalp_session():
    """scalp_session.json 동기 저장 (실패 시 로그만)."""
    try:
        from src.memory import scalp_session_store
        scalp_session_store.persist_scalp_session_from_module()
    except Exception as exc:
        print(f"Log: [ScalpSession] persist failed: {exc}")


def _touch_session_time(key):
    from src.utils.timekit import kst_iso_now
    _scalp_session_dict[key] = kst_iso_now()


def set_backtest_gate_result(result_dict):
    """백테스트 결과를 세션에 반영."""
    if not isinstance(result_dict, dict):
        return
    _scalp_session_dict["backtest_passed"] = bool(result_dict.get("passes_gate"))
    _scalp_session_dict["last_backtest"] = {
        "run_at": result_dict.get("run_at"),
        "passes_gate": result_dict.get("passes_gate"),
        "win_rate": result_dict.get("win_rate"),
        "avg_return": result_dict.get("avg_return"),
        "total_return": result_dict.get("total_return"),
        "total_trades": result_dict.get("total_trades"),
        "gate_reason": result_dict.get("gate_reason"),
    }
    _persist_scalp_session()


def is_backtest_passed():
    return bool(_scalp_session_dict.get("backtest_passed"))


def is_scalp_user_running():
    return bool(_scalp_session_dict.get("is_user_running"))


def is_scalp_schedule_enabled():
    """스케줄러 등록 조건: 백테스트 통과 + 사용자 단타 진행 ON."""
    return is_backtest_passed() and is_scalp_user_running()


def get_scalp_lifecycle():
    return _scalp_session_dict.get("lifecycle") or SCALP_LIFECYCLE_STOPPED


def set_scalp_lifecycle(state_code):
    _scalp_session_dict["lifecycle"] = str(state_code)


def get_scalp_position():
    pos = _scalp_session_dict.get("position")
    return dict(pos) if isinstance(pos, dict) else None


def set_scalp_position(position_dict):
    """단타 보유 포지션 세션 적재 (동시 1종목)."""
    if not isinstance(position_dict, dict):
        return None
    _scalp_session_dict["position"] = dict(position_dict)
    set_scalp_lifecycle(SCALP_LIFECYCLE_RISK)
    _persist_scalp_session()
    return get_scalp_position()


def update_scalp_position(**fields):
    pos = get_scalp_position()
    if not pos:
        return None
    pos.update(fields)
    _scalp_session_dict["position"] = pos
    _persist_scalp_session()
    return pos


def clear_scalp_position():
    _scalp_session_dict["position"] = None
    if is_scalp_user_running() and get_weekly_budget() is not None:
        set_scalp_lifecycle(SCALP_LIFECYCLE_SCANNING)
    _persist_scalp_session()
    return True


def has_scalp_position():
    pos = get_scalp_position()
    return bool(pos and int(pos.get("qty", 0) or 0) > 0)


def get_scalp_condition_name():
    """`.env` SCALP_CONDITION_NAME (기본: 당일_주도주_발굴)."""
    return (os.getenv("SCALP_CONDITION_NAME") or "당일_주도주_발굴").strip()


def check_hts_condition_registered(kis_client):
    """HTS 종목조건검색식 등록 여부 확인 (KIS psearch API).

    Returns:
        dict: ``{"ok": bool, "reason": str, "condition_name": str, "seq": str|None}``.
    """
    name = get_scalp_condition_name()
    if not name:
        return {"ok": False, "reason": "SCALP_CONDITION_NAME 환경변수 미설정", "condition_name": ""}
    if kis_client is None:
        return {"ok": False, "reason": "KIS 클라이언트 없음", "condition_name": name}
    if not getattr(kis_client, "hts_id", None):
        return {"ok": False, "reason": "HTS_ID 미설정 - .env 확인 필요", "condition_name": name}
    if not getattr(kis_client, "token", None):
        return {"ok": False, "reason": "KIS 토큰 미발급 - HTS 조건식 조회 불가", "condition_name": name}
    seq = kis_client.find_condition_seq(name)
    if not seq:
        return {
            "ok": False,
            "reason": f"HTS 조건식 미등록: '{name}' (HTS 저장 후 SCALP_CONDITION_NAME 확인)",
            "condition_name": name,
            "seq": None,
        }
    return {"ok": True, "reason": "ok", "condition_name": name, "seq": seq}


def _budget_timeout_minutes():
    try:
        return max(1, int(os.getenv("SCALP_BUDGET_TIMEOUT_MIN", str(DEFAULT_BUDGET_TIMEOUT_MIN))))
    except (TypeError, ValueError):
        return DEFAULT_BUDGET_TIMEOUT_MIN


def _budget_fallback_timeout_reached(now=None):
    """예산 요청 후 타임아웃(기본 30분) 경과 여부."""
    from src.utils.timekit import now_kst, parse_iso_to_kst
    requested_at = _scalp_session_dict.get("budget_requested_at")
    if not requested_at:
        return False
    req_dt = parse_iso_to_kst(requested_at)
    if req_dt is None:
        return False
    current = now if now is not None else now_kst()
    if current.tzinfo is None:
        current = current.replace(tzinfo=req_dt.tzinfo)
    elapsed_min = (current - req_dt).total_seconds() / 60.0
    return elapsed_min >= _budget_timeout_minutes()


def start_scalp_trading(*, via="slack", kis_client=None, app=None, channel_id=None):
    """단타 진행 시작. 백테스트 PASS + HTS 조건식 등록 필수.

    시작 시 항상 예산을 초기화하고 S_PRE 로 진입한 뒤 Block Kit 예산 메시지를 보낸다.
    (멈춤 후 재시작 포함 - 이전 예산 재사용하지 않음)
    """
    if not is_backtest_passed():
        return {
            "ok": False,
            "reason": "백테스트 게이트 미통과. !단타백테스트 실행 후 재시도",
        }
    if kis_client is None:
        return {"ok": False, "reason": "KIS 클라이언트 없음 - HTS 조건식 확인 불가"}
    hts = check_hts_condition_registered(kis_client)
    if not hts.get("ok"):
        return {"ok": False, "reason": hts.get("reason", "HTS 조건식 확인 실패")}

    reset_weekly_budget_session()
    _scalp_session_dict["is_user_running"] = True
    _scalp_session_dict["hts_condition_name"] = hts.get("condition_name")
    _touch_session_time("started_at")
    _touch_session_time("budget_requested_at")
    set_scalp_lifecycle(SCALP_LIFECYCLE_PRE)

    budget_prompt = request_weekly_budget_via_slack(
        app=app, channel_id=channel_id, reset_budget=False,
    )
    _persist_scalp_session()
    return {
        "ok": True,
        "lifecycle": SCALP_LIFECYCLE_PRE,
        "via": via,
        "hts_condition": hts.get("condition_name"),
        "budget_prompt_sent": bool(budget_prompt.get("sent")),
        "budget_prompt_reason": budget_prompt.get("reason"),
    }


def stop_scalp_trading(*, via="slack"):
    """단타 진행 중단."""
    _scalp_session_dict["is_user_running"] = False
    set_scalp_lifecycle(SCALP_LIFECYCLE_STOPPED)
    _touch_session_time("stopped_at")
    _persist_scalp_session()
    return {"ok": True, "lifecycle": SCALP_LIFECYCLE_STOPPED, "via": via}


def format_scalp_status_text():
    """슬랙/터미널용 단타 상태 요약 문자열."""
    bt = _scalp_session_dict.get("last_backtest") or {}
    budget = get_weekly_budget()
    lines = [
        "[ 단타(Scalp) 상태 ]",
        f"- 진행: {'ON' if is_scalp_user_running() else 'OFF'}",
        f"- 라이프사이클: {get_scalp_lifecycle()}",
        f"- 주간 예산: {f'{budget:,}원' if budget else '미설정'}",
        f"- 예산 설정 경로: {_scalp_session_dict.get('set_via') or '-'}",
        f"- 백테스트 통과: {'YES' if is_backtest_passed() else 'NO'}",
        f"- HTS 조건식: {_scalp_session_dict.get('hts_condition_name') or get_scalp_condition_name()}",
    ]
    if bt:
        lines.append(
            f"- 최근 백테스트: win_rate={bt.get('win_rate', 0):.2%}, "
            f"avg={float(bt.get('avg_return') or 0):.4f}, "
            f"total={float(bt.get('total_return') or 0):.4f} "
            f"({bt.get('gate_reason', '-')})"
        )
    lines.append(
        f"- 스케줄 활성: {'YES' if is_scalp_schedule_enabled() else 'NO'} "
        "(백테스트 통과 + 진행 ON 필요)"
    )
    pos = get_scalp_position()
    if pos:
        lines.append(
            f"- 보유: {pos.get('name', pos.get('ticker'))}({pos.get('ticker')}) "
            f"{pos.get('qty')}주 @ {int(pos.get('avg_price', 0)):,}원 "
            f"half_sold={'Y' if pos.get('half_sold') else 'N'}"
        )
    else:
        lines.append("- 보유: 없음")
    return "\n".join(lines)


def get_scalp_session_state():
    """전체 세션 스냅샷."""
    snap = dict(_scalp_session_dict)
    snap["schedule_enabled"] = is_scalp_schedule_enabled()
    return snap


def set_weekly_budget(amount_int, *, via="default"):
    """확정된 주간 단타 예산을 세션에 안전하게 적재.

    Args:
        amount_int: 예산 금액(int|str). 정수 변환 실패 시 적재 거부.
        via: 적재 경로 라벨 ("default" | "custom" | "fallback_timeout").

    Returns:
        int|None: 적재된 금액(KRW). 거부 시 None.
    """
    try:
        amount = int(amount_int)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    from src.utils.timekit import kst_iso_now
    _scalp_session_dict["amount"] = amount
    _scalp_session_dict["is_pending_custom"] = False
    _scalp_session_dict["set_via"] = str(via)
    _scalp_session_dict["set_at"] = kst_iso_now()
    if is_scalp_user_running():
        set_scalp_lifecycle(SCALP_LIFECYCLE_SCANNING)
    _persist_scalp_session()
    return amount


def get_weekly_budget():
    """적재된 주간 단타 예산 반환. 미확정 시 None."""
    return _scalp_session_dict.get("amount")


def reset_weekly_budget_session():
    """S_PRE 재진입 시 예산 필드만 초기화 (진행/백테스트 상태 유지)."""
    _scalp_session_dict["amount"] = None
    _scalp_session_dict["is_pending_custom"] = False
    _scalp_session_dict["set_via"] = None
    _scalp_session_dict["set_at"] = None


def get_weekly_budget_session_state():
    """세션 스냅샷 조회(테스트/디버깅). 하위 호환 alias."""
    return get_scalp_session_state()


def _build_weekly_budget_blocks():
    """주간 단타 예산 + 진행 제어 Block Kit 메시지 블록 생성."""
    running_label = "ON" if is_scalp_user_running() else "OFF"
    bt_label = "통과" if is_backtest_passed() else "미통과"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "*[ 주간 단타 설정 ]*\n"
                    "예산을 선택하세요. *단타 시작/재시작 시마다 예산을 다시 확인*합니다.\n"
                    f"현재 진행: *{running_label}* | 백테스트: *{bt_label}*\n"
                    f"무응답 시: 09:00 KST 또는 요청 후 {_budget_timeout_minutes()}분 뒤 기본 5만원 자동 적용."
                ),
            },
        },
        {
            "type": "actions",
            "block_id": "scalp_budget_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "기본 5만원"},
                    "style": "primary",
                    "action_id": "budget_default",
                    "value": str(DEFAULT_WEEKLY_BUDGET),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "직접 입력"},
                    "action_id": "budget_custom",
                    "value": "custom",
                },
            ],
        },
        {
            "type": "actions",
            "block_id": "scalp_control_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "단타 진행"},
                    "style": "primary",
                    "action_id": "scalp_start",
                    "value": "start",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "단타 멈춤"},
                    "style": "danger",
                    "action_id": "scalp_stop",
                    "value": "stop",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "상태 확인"},
                    "action_id": "scalp_status",
                    "value": "status",
                },
            ],
        },
    ]


def request_weekly_budget_via_slack(app=None, channel_id=None, *, reset_budget=True):
    """단타 예산 입력 Block Kit 메시지 발송.

    Args:
        app: slack_bolt App.
        channel_id: 송신 채널 ID.
        reset_budget: True 이면 예산 필드 초기화 (월요일 08:30 스케줄용).
            False 이면 ``start_scalp_trading`` 직후 재요청 시 사용.
    """
    if reset_budget:
        reset_weekly_budget_session()
    _touch_session_time("budget_requested_at")
    _persist_scalp_session()
    blocks = _build_weekly_budget_blocks()
    resolved_channel = channel_id or os.getenv("SLACK_CHANNEL") or os.getenv("SLACK_CHANNEL_ID") or ""

    if app is None:
        return {"sent": False, "blocks": blocks, "channel": resolved_channel, "reason": "app=None"}
    if not resolved_channel:
        return {"sent": False, "blocks": blocks, "channel": None, "reason": "channel 미지정"}

    try:
        client = getattr(app, "client", None)
        if client is None or not hasattr(client, "chat_postMessage"):
            return {"sent": False, "blocks": blocks, "channel": resolved_channel, "reason": "client 없음"}
        client.chat_postMessage(
            channel=resolved_channel,
            text="[주간 단타 예산 입력 요청]",
            blocks=blocks,
        )
        return {"sent": True, "blocks": blocks, "channel": resolved_channel, "reason": "ok"}
    except Exception as exc:
        # A-Type: 전송 실패해도 폴백 흐름이 진행되어야 하므로 예외를 흡수.
        return {
            "sent": False,
            "blocks": blocks,
            "channel": resolved_channel,
            "reason": f"송신 예외 격리: {type(exc).__name__}: {exc}",
        }


def handle_budget_slack_interaction(payload_dict):
    """슬랙 인터랙티브 페이로드를 파싱하여 단타 예산 세션을 갱신.

    오케스트레이터/슬랙 핸들러 양측이 동일 진입점을 쓰도록 외부 노출한다.
    페이로드 종류:
        - ``actions[0].action_id == "budget_default"``: 기본 5만원 적재.
        - ``actions[0].action_id == "budget_custom"``: ``is_pending_custom=True`` 플래그
          만 켜고, 후속 텍스트/모달 입력을 기다린다.
        - ``view.callback_id == "budget_custom_modal_submit"``: 모달 제출 금액 적재.
        - 일반 메시지 페이로드(``event.text`` 에 숫자만 포함)도 ``is_pending_custom``
          상태에서는 금액으로 파싱.

    Args:
        payload_dict: 슬랙 페이로드 dict (Mock 가능).

    Returns:
        dict: ``{"status": "ok"|"pending"|"ignored"|"error", "amount": int|None, "via": str}``.
    """
    if not isinstance(payload_dict, dict):
        return {"status": "error", "amount": None, "via": "invalid_payload"}

    actions = payload_dict.get("actions") or []
    if actions:
        first = actions[0] if isinstance(actions[0], dict) else {}
        action_id = first.get("action_id")
        if action_id == "budget_default":
            value = first.get("value") or DEFAULT_WEEKLY_BUDGET
            amount = set_weekly_budget(value, via="default")
            return {"status": "ok", "amount": amount, "via": "default"}
        if action_id == "budget_custom":
            _scalp_session_dict["is_pending_custom"] = True
            return {"status": "pending", "amount": None, "via": "custom_wait"}

    view = payload_dict.get("view") or {}
    if view.get("callback_id") == "budget_custom_modal_submit":
        state_values = ((view.get("state") or {}).get("values") or {})
        # 임의 block_id 하위 input action 값을 탐색
        raw_text = None
        for _bid, blk in state_values.items():
            if not isinstance(blk, dict):
                continue
            for _aid, item in blk.items():
                if isinstance(item, dict) and item.get("type") == "plain_text_input":
                    raw_text = item.get("value")
                    break
            if raw_text is not None:
                break
        if raw_text is None:
            return {"status": "error", "amount": None, "via": "custom_modal_empty"}
        digits = re.sub(r"[^\d]", "", str(raw_text))
        if not digits:
            return {"status": "error", "amount": None, "via": "custom_modal_invalid"}
        amount = set_weekly_budget(digits, via="custom")
        return {"status": "ok", "amount": amount, "via": "custom"}

    event = payload_dict.get("event") or {}
    raw_text = event.get("text")
    if raw_text and _scalp_session_dict.get("is_pending_custom"):
        digits = re.sub(r"[^\d]", "", str(raw_text))
        if digits:
            amount = set_weekly_budget(digits, via="custom")
            return {"status": "ok", "amount": amount, "via": "custom"}
        return {"status": "error", "amount": None, "via": "custom_text_invalid"}

    return {"status": "ignored", "amount": None, "via": "no_match"}


def force_default_budget_if_idle(*, mode="timeout"):
    """S_PRE 무응답 폴백: 기본 5만원 강제 적재.

    Args:
        mode: ``"timeout"`` (요청 후 N분) | ``"open_0900"`` (09:00 정시 스케줄).

    Returns:
        dict: ``{"applied": bool, "amount": int|None, "via": str}``.
    """
    if get_weekly_budget() is not None:
        return {"applied": False, "amount": get_weekly_budget(), "via": "already_set"}
    if not is_scalp_user_running():
        return {"applied": False, "amount": None, "via": "not_running"}
    if get_scalp_lifecycle() != SCALP_LIFECYCLE_PRE:
        return {"applied": False, "amount": None, "via": "not_s_pre"}

    if mode == "open_0900":
        eligible = True
    elif mode == "timeout":
        eligible = _budget_fallback_timeout_reached()
    else:
        eligible = False

    if not eligible:
        return {"applied": False, "amount": None, "via": "not_due"}

    amount = set_weekly_budget(DEFAULT_WEEKLY_BUDGET, via="fallback_timeout")
    set_scalp_lifecycle(SCALP_LIFECYCLE_SCANNING)
    return {"applied": True, "amount": amount, "via": "fallback_timeout"}


def try_budget_fallback_during_intraday():
    """장중 3분 job: S_PRE + 무응답 시 30분 타임아웃 폴백."""
    return force_default_budget_if_idle(mode="timeout")


def handle_scalp_control_interaction(payload_dict, *, kis_client=None, app=None, channel_id=None):
    """단타 진행/멈춤/상태확인 슬랙 액션 처리."""
    if not isinstance(payload_dict, dict):
        return {"status": "error", "reason": "invalid_payload"}
    actions = payload_dict.get("actions") or []
    if not actions:
        return {"status": "ignored"}
    action_id = (actions[0] or {}).get("action_id")
    if action_id == "scalp_start":
        result = start_scalp_trading(
            via="slack_button", kis_client=kis_client, app=app, channel_id=channel_id,
        )
        return {"status": "ok" if result.get("ok") else "error", **result}
    if action_id == "scalp_stop":
        result = stop_scalp_trading(via="slack_button")
        return {"status": "ok", **result}
    if action_id == "scalp_status":
        return {"status": "ok", "text": format_scalp_status_text()}
    return {"status": "ignored"}

def register_slack_handlers(app, kis, config, orchestrator):
    """슬랙 명령 핸들러 등록.

    Args:
        app: slack_bolt App.
        kis: KISClient.
        config: 전역 설정 dict (APP_KEY/SECRET_KEY/URL/CHANNEL_ID 등).
        orchestrator: MarketOrchestrator. 백필/크로니클/슬랙 송출의 단일
            게이트웨이로 사용된다. v3.3 리팩토링으로 모든 슬랙 핸들러가
            ``src.memory.backfill`` 을 직접 import 하지 않고 본 orchestrator
            의 backfill_* 메서드를 경유한다(라우팅 정합).
    """

    @app.message(re.compile(r"^!명령어", re.IGNORECASE))
    def cmd_help(message, say):
        help_text = """[ 봇 명령어 매뉴얼 ]
- !잔고 : 실계좌 현금 및 포트폴리오 요약 조회
- !HTS스캔 : 3-Track(기대주/배당주/낙폭과대) 통합 스캔 및 검증
- !타점분석 [코드] : 특정 종목의 도지/거래량 정밀 타점 진단
- !역발상 : RSI 과매도 및 하락 진정 패턴 포착 스캔
- !발굴 [배당률/테마] : 기존 100점 만점 펀더멘털 스크리닝
- !ai매수 [코드] [예산] : 정밀 분석 후 10일 분할매수 세팅
- !수동등록 [코드] [트랙] : 내 보유종목 방어막 감시망에 편입 (트랙: A, B, C, M)
- !성과 : AI vs 수동 트랙별 승률 및 수익률 비교 리포트
- !일일보고 / !주간보고 / !월간보고 / !분기보고 : 각종 리포트 수동 생성
- !초기화 : 장부 및 주문 데이터 초기화
- !크로니클 : T-Day 시장 크로니클 수동 작성 (트리거 충족 시)
- !백필스캔 [일수] : 최근 N일(기본 60) 변동성 장세 스캔 + 후보 보고
- !백필실행 [건당대기초] : 저장된 백필 큐 1건씩 소급 작성 (기본 3초)
- !백필초기화 [purge] : 기존 백필 결과 정리 (purge 입력 시 .md 리포트까지 삭제)
- !백필재인덱싱 [건당대기초] : 기존 .md 보존, keyphrases 만 v3.2 포맷으로 재추출
- !백필상태 : reports 트리와 master_index 정합 상태 진단 (읽기 전용)
- !백필잔여정리 [dry] : master_index 외부의 백필 .md 만 정리 (dry 입력 시 미실행 보고)
- !단타시작 / !단타멈춤 / !단타상태 : 단타(Scalp) 진행 제어 및 상태 조회
- !단타백테스트 [일수] : 형태 기반 백테스트 실행 (기본 60일, 가격 무관)
- 확인 : 직전 백필 스캔 결과를 그대로 실행
- 완료 : Google Drive Pause 해제 후 재검증"""
        say(help_text)

    @app.message(re.compile(r"^완료\s*$"))
    def cmd_drive_resume(message, say):
        from src.memory import drive_client

        result = drive_client.try_resume_after_user_ack()
        say(result)

    @app.message(re.compile(r"^!백필스캔(?:\s+(\d+))?\s*$", re.IGNORECASE))
    def cmd_backfill_scan(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        m = re.match(r"^!백필스캔(?:\s+(\d+))?\s*$", text, re.IGNORECASE)
        lookback = int(m.group(1)) if (m and m.group(1)) else 60
        say(f"[System] 최근 {lookback}일 변동성 장세 스캔을 시작합니다...")
        threading.Thread(
            target=lambda: orchestrator.backfill_scan(lookback_days=lookback),
            daemon=True,
        ).start()

    @app.message(re.compile(r"^!백필실행(?:\s+(\d+))?\s*$", re.IGNORECASE))
    def cmd_backfill_run(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        m = re.match(r"^!백필실행(?:\s+(\d+))?\s*$", text, re.IGNORECASE)
        delay_sec = int(m.group(1)) if (m and m.group(1)) else 3
        say(f"[System] 저장된 백필 큐를 실행합니다 (건당 {delay_sec}초 대기).")
        threading.Thread(
            target=lambda: orchestrator.backfill_run(delay_sec=delay_sec),
            daemon=True,
        ).start()

    @app.message(re.compile(r"^!백필초기화(?:\s+(purge))?\s*$", re.IGNORECASE))
    def cmd_backfill_reset(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        m = re.match(r"^!백필초기화(?:\s+(purge))?\s*$", text, re.IGNORECASE)
        purge = bool(m and m.group(1))
        warn = " (리포트 .md 까지 삭제)" if purge else " (master_index 엔트리·state만 제거, .md 보존)"
        say(f"[System] 백필 초기화를 시작합니다.{warn}")
        threading.Thread(
            target=lambda: orchestrator.backfill_reset(delete_reports=purge),
            daemon=True,
        ).start()

    @app.message(re.compile(r"^!백필상태\s*$", re.IGNORECASE))
    def cmd_backfill_diagnose(message, say):
        say("[System] reports 트리와 master_index 정합 상태를 진단합니다 (읽기 전용).")
        threading.Thread(target=orchestrator.backfill_diagnose, daemon=True).start()

    @app.message(re.compile(r"^!백필(?:잔여정리|고아청소)(?:\s+(dry))?\s*$", re.IGNORECASE))
    def cmd_backfill_purge_leftover(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        m = re.match(r"^!백필(?:잔여정리|고아청소)(?:\s+(dry))?\s*$", text, re.IGNORECASE)
        dry = bool(m and m.group(1))
        say(
            "[System] master_index 외부의 백필 표식 .md (인덱스 미등록 잔여 파일) 만 정리합니다. "
            + ("(드라이런: 미삭제 보고)" if dry else "(실삭제)")
        )
        threading.Thread(
            target=lambda: orchestrator.backfill_purge_leftover(dry_run=dry),
            daemon=True,
        ).start()

    @app.message(re.compile(r"^!백필재인덱싱(?:\s+(\d+))?\s*$", re.IGNORECASE))
    def cmd_backfill_reindex(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        m = re.match(r"^!백필재인덱싱(?:\s+(\d+))?\s*$", text, re.IGNORECASE)
        delay_sec = int(m.group(1)) if (m and m.group(1)) else 3
        say(
            f"[System] 백필 엔트리 재인덱싱을 시작합니다 (.md 보존, keyphrases 재추출, "
            f"건당 {delay_sec}초 대기)."
        )
        threading.Thread(
            target=lambda: orchestrator.backfill_reindex(delay_sec=delay_sec),
            daemon=True,
        ).start()

    @app.message(re.compile(r"^(확인)\s*$"))
    def cmd_backfill_confirm(message, say):
        from src.memory import drive_client

        if not drive_client.is_drive_enabled() or not drive_client.is_ready():
            return say("[Info] Drive 가 준비되지 않았습니다. '!백필스캔' 또는 '완료' 명령을 먼저 사용하세요.")

        state = orchestrator.backfill_get_state()
        queue = state.get("queue") or []
        processed = set(state.get("processed") or [])
        skipped_dates = {it.get("date") for it in state.get("skipped", []) if isinstance(it, dict)}
        pending = [d for d in queue if d not in processed and d not in skipped_dates]
        if not pending:
            return say(
                "[Info] 현재 대기 중인 백필 큐가 없습니다. 먼저 '!백필스캔' 을 실행해 주세요."
            )

        say(f"[System] '확인' 응답 수신. 대기 중인 {len(pending)}건의 백필을 실행합니다 (건당 3초 대기).")
        threading.Thread(
            target=lambda: orchestrator.backfill_run(delay_sec=3),
            daemon=True,
        ).start()

    @app.message(re.compile(r"^!크로니클", re.IGNORECASE))
    def cmd_chronicle_manual(message, say):
        say("[System] Market Chronicles 수동 작성을 시작합니다.")

        def bg_task():
            from src.memory import chronicle_writer

            macro = macro_collector.get_macro_indicators()
            us_kw, kr_kw = ai_strategy.infer_news_keywords().split(",")[:2]
            us_news = news_crawler.get_latest_news(us_kw.strip() or "미국증시", limit=8, search_type="macro")
            kr_news = news_crawler.get_latest_news(kr_kw.strip() or "한국증시", limit=8, search_type="macro")
            ok, msg = chronicle_writer.write_chronicle_for_today(macro, us_news, kr_news, notify_fn=say)
            if ok:
                say(f"[완료] 크로니클 저장: {msg}")
            else:
                say(f"[결과] {msg}")

        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!HTS스캔", re.IGNORECASE))
    def cmd_hts_scan_all(message, say):
        say("[System] HTS 3-Track(기대주/배당주/낙폭과대) 통합 정밀 스캔을 시작합니다...")
        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            
            tracks = {
                "기대주_발굴": "TRACK_A (성장)",
                "배당주_발굴": "TRACK_B (가치)",
                "낙폭과대_발굴": "TRACK_C (역발상)"
            }
            
            summary = ["[ HTS 3-Track 통합 스캔 결과 ]\n"]
            
            for cond_name, display_name in tracks.items():
                raw = quant_screener.run_condition_screener(kis, cond_name)
                if not raw:
                    summary.append(f"* {display_name}: 후보 없음")
                    continue
                
                passed = quant_screener.run_3track_screener(cond_name, raw, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token)
                if not passed:
                    summary.append(f"* {display_name}: 2차 검증 통과 종목 없음")
                    continue
                
                summary.append(f"* {display_name}: {len(passed)}종목 포착")
                for s in passed[:3]:
                    summary.append(f"  ㄴ {s['name']}({s['ticker']}): {', '.join(s['score_details'])}")
                summary.append("")
                
            say("\n".join(summary))
        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!타점분석", re.IGNORECASE))
    def cmd_timing_check(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        parts = text.split()
        if len(parts) < 2: return say("[Error] 사용법: !타점분석 [종목코드]")
        ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
        
        say(f"[System] {ticker} 종목의 기술적 정밀 타점(Doji/Volume)을 분석합니다...")
        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            ohlcv = chart_data.get_daily_ohlcv(config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, ticker, count=30)
            if not ohlcv or len(ohlcv) < 5: return say(f"[Error] {ticker} 차트 데이터를 불러올 수 없습니다.")
            
            curr = ohlcv[-1]
            prev = ohlcv[-2]
            
            rsi = quant_screener.calculate_rsi(ohlcv)
            body_size = abs(curr['open'] - curr['close'])
            total_size = curr['high'] - curr['low'] if curr['high'] != curr['low'] else 1
            body_ratio = (body_size / total_size) * 100
            
            avg_vol_5d = sum([x['volume'] for x in ohlcv[-6:-1]]) / 5
            vol_ratio_avg = (curr['volume'] / avg_vol_5d) * 100
            vol_ratio_prev = (curr['volume'] / prev['volume']) * 100
            
            is_signal, signal_desc = quant_screener.check_contrarian_signal(ohlcv)
            
            status = "\\U0001F4E2 [타점 진단 결과]"
            if is_signal:
                status = "\\U0001F6A8 [타점 포착!]"
            
            report = f"{status}\n- 종목코드: {ticker}\n- 현재 RSI(14): {rsi:.1f} {'(과매도)' if rsi <= 35 else ''}\n- 캔들 몸통 비중: {body_ratio:.2f}% {'(도지형)' if body_ratio <= 1.5 else ''}\n- 거래량 분석:\n  ㄴ 5일 평균 대비: {vol_ratio_avg:.1f}%\n  ㄴ 전일 대비: {vol_ratio_prev:.1f}%\n- 최종 판정: {signal_desc if is_signal else '시그널 없음'}"
            say(report)
        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!성과", re.IGNORECASE))
    def cmd_performance(message, say):
        say("[System] 전략 트랙별 성과 분석 리포트를 생성합니다...")
        def bg_task():
            trades = load_json_from_gdrive("paper_trades.json") or []
            if not trades: return say("[결과] 거래 기록이 없어 성과를 분석할 수 없습니다.")
            
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            
            msg = ["[ 전략별 성과 비교 리포트 ]\n"]
            all_tags = set([t.get("strategy_tag", "UNKNOWN") for t in trades])
            for tag in sorted(all_tags):
                tag_trades = [t for t in trades if t.get("strategy_tag") == tag and t["action"] == "BUY"]
                if not tag_trades: continue
                total_ret, win_count, trade_count = 0.0, 0, 0
                for t in tag_trades:
                    ticker, buy_price = t["ticker"], t["price"]
                    if buy_price <= 0: continue
                    val = kis.get_valuation_data(ticker)
                    curr_price = int(val["current_price"]) if val else buy_price
                    ret = (curr_price - buy_price) / buy_price
                    total_ret += ret
                    if ret > 0: win_count += 1
                    trade_count += 1
                avg_ret = (total_ret / trade_count) * 100 if trade_count > 0 else 0
                win_rate = (win_count / trade_count) * 100 if trade_count > 0 else 0
                tag_name = "AI-기대주(A)" if tag == "TRACK_A" else "AI-배당주(B)" if tag == "TRACK_B" else "AI-낙폭과대(C)" if tag == "TRACK_C" else "수동매수" if tag == "MANUAL" else tag
                msg.append(f"* {tag_name} :\n  - 평균 수익률: {avg_ret:+.2f}%\n  - 승률: {win_rate:.1f}% ({win_count}/{trade_count}건)")
            say("\n".join(msg))
        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!기대주테스트", re.IGNORECASE))
    def cmd_test_gem(message, say):
        say("[System] 기대주 발굴 중입니다 (기준: 60점 이상)...")
        def task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            stocks = quant_screener.run_condition_screener(kis, "기대주_발굴")
            if not stocks: return say("[결과] 조건식 통과 종목이 없습니다.")
            passed_gem = quant_screener.run_unified_screener(stocks, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token)
            top_gems = [p for p in passed_gem if p.get('score', 0) >= 60]
            if not top_gems: return say("[결과] 60점 이상 펀더멘털 대장주가 없습니다.")
            output = ["[ 기대주 (60점 이상) 테스트 결과 ]\n"]
            for s in top_gems[:5]:
                name, _, _ = stock_info_crawler.get_stock_info_naver(s['ticker'])
                news = news_crawler.get_latest_news(name, limit=2)
                rating = ai_strategy.get_quick_rating(s['ticker'], name, news, "기대주", s)
                output.append(f"- {name} ({s['ticker']}) [{s.get('score')}점]\n{rating}\n")
            say("\n".join(output))
        threading.Thread(target=task, daemon=True).start()

    @app.message(re.compile(r"^!배당주테스트", re.IGNORECASE))
    def cmd_test_div(message, say):
        say("[System] 배당주 스캔 및 AI 위험 검증 중...")
        def task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            stocks = quant_screener.run_condition_screener(kis, "배당주_발굴")
            if not stocks: return say("[결과] 조건식 통과 종목이 없습니다.")
            output = ["[ 배당 가치주 테스트 결과 ]\n"]
            for s in stocks[:5]:
                name, _, _ = stock_info_crawler.get_stock_info_naver(s['ticker'])
                news = news_crawler.get_latest_news(name, limit=2)
                val = kis.get_valuation_data(s['ticker']) or {}
                rating = ai_strategy.get_dividend_risk_check(s['ticker'], name, news, val)
                output.append(f"- {name} ({s['ticker']})\n{rating}\n")
            say("\n".join(output))
        threading.Thread(target=task, daemon=True).start()

    @app.message(re.compile(r"^!역발상", re.IGNORECASE))
    def contrarian_scan(message, say):
        say("[System] RSI 과매도 및 하락 진정 패턴(도지/거래량 급감) 기반 3단계 교차 검증 스캔을 시작합니다...")
        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            candidates = quant_screener.run_condition_screener(kis, "기대주_발굴")
            if not candidates: return say("[결과] 분석 대상 후보 종목이 없습니다.")
            tech_passed = []
            for c in candidates:
                ticker, name = c['ticker'], c['name']
                ohlcv = chart_data.get_daily_ohlcv(config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, ticker, count=30)
                is_signal, tech_reason = quant_screener.check_contrarian_signal(ohlcv)
                if is_signal: tech_passed.append({"ticker": ticker, "name": name, "tech_reason": tech_reason})
            if not tech_passed: return say("[결과] 현재 하락 진정 패턴(도지/거래량 급감)이 포착된 과매도 종목이 없습니다.")
            say(f"[System] 기술적 반등 시그널 포착({len(tech_passed)}종목). 2단계 펀더멘털(70점 이상) 검증 중...")
            fund_passed = quant_screener.run_unified_screener(tech_passed, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token)
            safe_candidates = [p for p in fund_passed if p.get('score', 0) >= 70]
            if not safe_candidates: return say("[결과] 기술적 지표는 양호하나, 펀더멘털(70점 미만) 안전 마진을 충족하는 우량주가 없습니다.")
            say(f"[System] 펀더멘털 우량주 선별 완료({len(safe_candidates)}종목). 3단계 AI 돌발 악재 뉴스 스캔 중...")
            final_matched = []
            for s in safe_candidates:
                ticker, name = s['ticker'], s['name']
                news = news_crawler.get_latest_news(name, limit=10, search_type="stock")
                risk_res = ai_strategy.check_sudden_bad_news(ticker, name, news)
                if "[위험]" not in risk_res: final_matched.append(f"- {name}({ticker}): {s['tech_reason']} (펀더멘털 {s['score']}점, AI 안전)")
                else: say(f"[주의] {name}({ticker}) 패턴은 좋으나 돌발 악재 감지: {risk_res.replace('[위험]', '').strip()}")
            if not final_matched: return say("[결과] 모든 필터를 통과한 '진짜 바닥' 종목이 현재 시장에 없습니다.")
            msg = ["[ 역발상 3중 필터 저가 매수 포착 ]\n"] + final_matched
            msg.append("\n* 3중 필터: RSI/도지(기술적) + 70점 이상(재무) + 뉴스 클린(AI)")
            say("\n".join(msg))
        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!잔고", re.IGNORECASE))
    def cmd_balance(message, say):
        say("[System] KIS 실전 계좌 및 AI 가상 장부 현황을 조회합니다...")
        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            cash_balance = kis.get_psbl_cash()
            portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
            split_orders = load_json_from_gdrive("split_orders.json") or {}
            msg = ["[ 현재 계좌 및 포트폴리오 현황 ]", f"KIS 실계좌 매수 가능 현금: {cash_balance:,}원\n"]
            if not portfolio: msg.append("텅~ (현재 장부에 감시 중인 보유 종목이 없습니다.)")
            else:
                msg.append("[ 보유 종목 리스크 감시 현황 ]")
                for ticker, info in portfolio.items():
                    qty, avg_price = info.get("quantity", 0), info.get("avg_price", 0)
                    val = kis.get_valuation_data(ticker)
                    curr_price = int(val.get("current_price", 0)) if val else 0
                    if curr_price > 0 and avg_price > 0:
                        ret_pct = ((curr_price - avg_price) / avg_price) * 100
                        ret_str = f"+{ret_pct:.2f}%" if ret_pct > 0 else f"{ret_pct:.2f}%"
                        msg.append(f"- {info['name']}({ticker}) [{info.get('mode_type', 'PAPER')}] : {qty}주 | 평단 {avg_price:,.0f}원 -> 현재 {curr_price:,}원 ({ret_str})\n  내러티브: {info.get('reason', '')}\n")
                    elif qty == 0:
                        msg.append(f"- {info['name']}({ticker}) : 관심 등록 종목 (0주 보유 중)\n  내러티브: {info.get('reason', '')}\n")
            if split_orders:
                msg.append("\n[ 10일 분할 매수 진행 중 ]")
                for oid, info in split_orders.items():
                    msg.append(f"- {info['name']} : {11 - info['remaining_days']}/10회차 진행 중 (1일 예산 {info['daily_budget']:,.0f}원)\n  내러티브: {info.get('reason', '')}\n")
            say("\n".join(msg))
        threading.Thread(target=bg_task, daemon=True).start()

    def execute_unified_scan(say, candidates, keyword_msg):
        unique_candidates = []
        seen = set()
        for c in candidates:
            if c['ticker'] not in seen: seen.add(c['ticker']); unique_candidates.append(c)
        if not unique_candidates: return say(f"[Error] {keyword_msg} 소속 종목을 추출하지 못했습니다.")
        say(f"[System] 총 {len(unique_candidates)}개 종목 대상 100점 만점 펀더멘털 스크리닝을 시작합니다.")
        token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
        passed_stocks = quant_screener.run_unified_screener(unique_candidates, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token)
        if not passed_stocks: return say(f"[결과] {keyword_msg} 관련 종목 중 펀더멘털 스코어 60점 이상 대장주가 없습니다.")
        report_msg = [f"[ 100점 만점 펀더멘털 검증 완료 ({len(passed_stocks)}종목 합격) ]"]
        for p in passed_stocks:
            ticker, name, target_theme = p['ticker'], p['name'], p['target_theme']
            score = p.get('score', 0)
            score_details = p.get('score_details', [])
            details_text = ", ".join(score_details)
            entry = ai_strategy.register_theme_context(
                ticker, name, target_theme, score, score_details, p,
            )
            narrative = entry.split("\n", 1)[1] if "\n" in entry else entry
            report_msg.append(
                f"\n[ {name} ({ticker}) - {target_theme} | 현재가: {p.get('current_price', 0):,}원 ]"
                f"\n  - 펀더멘털 총점: {score}점"
                f"\n  - 획득 내역: {details_text}"
                f"\n  - [AI 팩트체크]\n{narrative}"
            )
        say("\n".join(report_msg))

    @app.message(re.compile(r"^!발굴", re.IGNORECASE))
    def cmd_discover_merged(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        parts = text.split(" ", 1)
        if len(parts) < 2 or parts[1].strip().replace('.', '', 1).isdigit():
            bm_rate = float(parts[1].strip()) if len(parts) > 1 and parts[1].strip().replace('.', '', 1).isdigit() else 4.0
            say(f"[System] 목표 배당률 {bm_rate}% 이상 고배당 가치주 스캐닝을 시작합니다.")
            def bg_task_div():
                token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
                candidates = stock_finder.get_high_dividend_candidates(config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, bm_rate)
                passed_stocks = quant_screener.run_screener(candidates, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, bm_rate)
                if not passed_stocks: return say("[결과] 통과한 가치주가 없습니다.")
                report_msg = [f"[ 배당 가치주 발굴 완료 ({len(passed_stocks)}종목) ]"]
                for p in passed_stocks: report_msg.append(f"- {p['name']}({p['ticker']}): 현재가 {p.get('current_price', 0):,}원, 배당 {p['div_yield']}%, PBR {p['pbr']}, ROE {p['roe']}%")
                say("\n".join(report_msg))
            threading.Thread(target=bg_task_div, daemon=True).start()
        else:
            keyword = parts[1].strip()
            def bg_task_theme():
                say(f"[System] '{keyword}' 키워드를 네이버 공식 테마 메뉴판과 대조합니다...")
                all_themes = theme_crawler.get_all_naver_themes()
                if not all_themes: return say("[Error] 네이버 테마 메뉴판을 긁어오지 못했습니다.")
                matched_names = ai_strategy.match_naver_themes(keyword, list(all_themes.keys()))
                if not matched_names: return say(f"[결과] '{keyword}'와 일치하는 공식 테마를 찾지 못했습니다.")
                say(f"[System] AI 라우팅 완료. 매핑된 테마: {', '.join(matched_names)}\n해당 테마 전 종목 100점 스코어링 시작...")
                all_candidates = []
                for t_name in matched_names: all_candidates.extend(theme_crawler.get_stocks_by_theme_link(all_themes[t_name], t_name))
                execute_unified_scan(say, all_candidates, keyword)
            threading.Thread(target=bg_task_theme, daemon=True).start()

    def _build_single_stock_report(ticker, fallback_theme, strategy_label, say):
        """`!ai매수`/`!수동등록` 공통 리포트 생성 헬퍼.

        세 진입점이 동일 흐름을 따르도록 통합한다:
        1) 종목 메타 조회(ETF 차단 포함)
        2) ``score_single_ticker`` 로 펀더멘털 점수 산출
        3) ``register_theme_context`` 로 ``theme_context.json`` 단일 규칙 저장
        4) ``get_multi_agent_investment_report`` 호출(``fundamental_score`` 전달)

        Returns:
            dict: 실패 시 ``{"ok": False}``. 성공 시 ``ok=True`` 와 함께
                ``report``, ``score``, ``ctx_text``, ``val``, ``target_theme``,
                ``opinion_code``, ``opinion_final``, ``opinion_delta``,
                ``ai_review_reason`` 키를 포함.
        """
        failure = {"ok": False}
        try:
            name, div, is_etf = stock_info_crawler.get_stock_info_naver(ticker)
            if is_etf:
                say(f"[거절] {name}({ticker})은(는) ETF 종목입니다.")
                return failure

            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            val = kis.get_valuation_data(ticker) or {}
            if int(val.get("current_price", 0) or 0) <= 0:
                say(f"[에러] {name} 주가 데이터를 가져오지 못했습니다.")
                return failure
            val.update({"div_yield": div, "name": name})

            scored = quant_screener.score_single_ticker(
                ticker, name, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token,
            )
            if scored is None:
                score, score_details = 0, []
                target_theme = fallback_theme
            else:
                score = scored["score"]
                score_details = scored["score_details"]
                target_theme = scored["target_theme"] or fallback_theme
                val.setdefault("pbr", scored["pbr"])
                val.setdefault("per", scored["per"])
                val.setdefault("roe", scored["roe"])

            ctx_text = ai_strategy.register_theme_context(
                ticker, name, target_theme, score, score_details, val,
            )

            chart_30d = chart_data.get_daily_ohlcv(
                config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, ticker, count=30,
            )
            macro = macro_collector.get_macro_indicators()
            portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
            news = news_crawler.get_latest_news(name, limit=5, search_type="stock")

            report, meta = ai_strategy.get_multi_agent_investment_report(
                ticker, name, chart_30d, macro, portfolio, val, ctx_text, news,
                fundamental_score=score, fundamental_details=score_details,
            )
            return {
                "ok": True,
                "report": report,
                "score": score,
                "ctx_text": ctx_text,
                "val": val,
                "target_theme": target_theme,
                "opinion_code": meta.get("opinion_code"),
                "opinion_final": meta.get("opinion_final"),
                "opinion_delta": meta.get("opinion_delta", 0),
                "ai_review_reason": meta.get("ai_review_reason", ""),
            }
        except Exception as exc:
            say(f"[Error] {strategy_label} 분석 중 오류: {exc}")
            return failure

    @app.message(re.compile(r"^!ai매수", re.IGNORECASE))
    def ai_buy_stock(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        parts = text.split()
        if len(parts) < 3: return say("[Error] 사용법: !ai매수 [종목코드] [총예산]")
        ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
        budget = int(re.sub(r'[^\d]', '', parts[2]))
        def bg_task():
            try:
                result = _build_single_stock_report(
                    ticker, fallback_theme="AI매수(단일종목)", strategy_label="AI매수",
                    say=say,
                )
                if not result.get("ok"):
                    return
                report = result["report"]
                val = result["val"]
                score = result["score"]
                name = val.get("name", ticker)
                actual_mode = os.getenv("TRADING_MODE_NORMAL", "PAPER").upper()
                say(f"[System] {name}({ticker}) AI 보고서 작성 중... ({actual_mode})")

                oid = str(uuid.uuid4())
                sum_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
                pending_orders[oid] = {
                    "ticker": ticker, "total_budget": budget,
                    "current_price": int(val.get("current_price", 0)),
                    "stock_name": name, "mode_type": "NORMAL",
                    "reason": sum_match.group(1).strip() if sum_match else "AI 분석 완료",
                    "score": score,
                    "opinion": result.get("opinion_final"),
                    "opinion_code": result.get("opinion_code"),
                    "opinion_delta": result.get("opinion_delta", 0),
                }
                say(f"[System] {name}({ticker}) 최종 AI 리포트\n\n{report}")
                say(
                    blocks=[
                        {"type": "section", "text": {"type": "mrkdwn", "text": f"최종 10일 분할매수({actual_mode}) 승인을 내려주십시오."}},
                        {"type": "actions", "elements": [
                            {"type": "button", "text": {"type": "plain_text", "text": f"승인 ({actual_mode} 매수)"}, "style": "primary", "action_id": "approve_buy", "value": oid},
                            {"type": "button", "text": {"type": "plain_text", "text": "기각 (취소)"}, "style": "danger", "action_id": "reject_buy", "value": oid},
                        ]},
                    ],
                    text="승인 대기 중",
                )
            except Exception as e:
                say(f"[Error] AI 매수 보고서 에러: {e}")
        threading.Thread(target=bg_task, daemon=True).start()

    @app.action("approve_buy")
    def action_approve_buy(ack, body, respond):
        ack()
        oid = body["actions"][0]["value"]
        if oid not in pending_orders: return respond(text="[Error] 만료된 주문입니다.", replace_original=False)
        order = pending_orders.pop(oid)
        token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
        reason = f"AI 승인 | {order.get('reason', '사유 누락')}"
        res = OrderManager(config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, config["ACC_NO"]).simulate_split_buy(order["ticker"], order["stock_name"], order["total_budget"], order["current_price"], f"{reason} (1/10회차 대기)")
        if res["success"]:
            split_orders = load_json_from_gdrive("split_orders.json") or {}
            split_orders[str(uuid.uuid4())] = {
                "ticker": order["ticker"], "name": order["stock_name"],
                "daily_budget": res["daily_budget"], "remaining_days": 10,
                "reason": reason, "mode_type": order["mode_type"],
                "score": order.get("score", 0),
                "opinion": order.get("opinion"),
                "opinion_code": order.get("opinion_code"),
                "opinion_delta": order.get("opinion_delta", 0),
            }
            save_json_to_gdrive(split_orders, "split_orders.json")
            respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n{res['msg']}", replace_original=True)
        else: respond(text=f"[Fail] {res['msg']}", replace_original=True)

    @app.action("reject_buy")
    def action_reject_buy(ack, body, respond):
        ack(); (pending_orders.pop(body["actions"][0]["value"]) if body["actions"][0]["value"] in pending_orders else None)
        respond(text=f"[Notice] <@{body['user']['id']}> 님이 매수를 기각했습니다.", replace_original=True)

    @app.action("budget_default")
    def action_budget_default(ack, body, respond):
        """주간 단타 예산 - '기본 5만원' 버튼."""
        ack()
        result = handle_budget_slack_interaction(body)
        if result.get("status") == "ok":
            respond(
                text=f"[Success] 주간 단타 예산 {result['amount']:,}원 으로 확정되었습니다. S0 스캐닝으로 전이합니다.",
                replace_original=True,
            )
        else:
            respond(text=f"[Error] 예산 적재 실패: {result}", replace_original=False)

    @app.action("budget_custom")
    def action_budget_custom(ack, body, client, respond):
        """주간 단타 예산 - '직접 입력' 버튼. 모달을 띄워 금액을 받는다."""
        ack()
        handle_budget_slack_interaction(body)  # is_pending_custom=True
        trigger_id = body.get("trigger_id")
        try:
            client.views_open(
                trigger_id=trigger_id,
                view={
                    "type": "modal",
                    "callback_id": "budget_custom_modal_submit",
                    "title": {"type": "plain_text", "text": "단타 예산 입력"},
                    "submit": {"type": "plain_text", "text": "확정"},
                    "close": {"type": "plain_text", "text": "취소"},
                    "blocks": [
                        {
                            "type": "input",
                            "block_id": "budget_input_block",
                            "label": {"type": "plain_text", "text": "주간 단타 예산 (KRW)"},
                            "element": {
                                "type": "plain_text_input",
                                "action_id": "budget_input_value",
                                "placeholder": {"type": "plain_text", "text": "예: 70000"},
                            },
                        }
                    ],
                },
            )
        except Exception as exc:
            respond(text=f"[Warn] 모달 열기 실패({type(exc).__name__}). 채팅에 숫자만 입력해 주세요.", replace_original=False)

    @app.view("budget_custom_modal_submit")
    def view_budget_custom_submit(ack, body, client):
        """직접 입력 모달 제출 처리."""
        ack()
        result = handle_budget_slack_interaction(body)
        user_id = (body.get("user") or {}).get("id") or ""
        channel_id = config.get("CHANNEL_ID") or os.getenv("SLACK_CHANNEL") or ""
        if result.get("status") == "ok" and channel_id:
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"[Success] <@{user_id}> 님이 단타 예산을 {result['amount']:,}원으로 확정했습니다. S0 스캐닝으로 전이합니다.",
                )
            except Exception:
                pass

    @app.action("scalp_start")
    def action_scalp_start(ack, body, respond):
        ack()
        token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
        kis.set_token(token)
        result = handle_scalp_control_interaction(
            body, kis_client=kis, app=app, channel_id=config.get("CHANNEL_ID"),
        )
        if result.get("ok"):
            respond(
                text=f"[Success] 단타 진행 ON ({result.get('lifecycle')}). 예산 Block Kit 확인.\n{format_scalp_status_text()}",
                replace_original=False,
            )
        else:
            respond(text=f"[Error] {result.get('reason', '시작 실패')}", replace_original=False)

    @app.action("scalp_stop")
    def action_scalp_stop(ack, body, respond):
        ack()
        handle_scalp_control_interaction(body)
        respond(
            text=f"[Notice] 단타 진행 OFF.\n{format_scalp_status_text()}",
            replace_original=False,
        )

    @app.action("scalp_status")
    def action_scalp_status(ack, body, respond):
        ack()
        respond(text=format_scalp_status_text(), replace_original=False)

    @app.message(re.compile(r"^!단타시작\s*$", re.IGNORECASE))
    def cmd_scalp_start(message, say):
        token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
        kis.set_token(token)
        result = start_scalp_trading(
            via="slack_cmd", kis_client=kis, app=app, channel_id=config.get("CHANNEL_ID"),
        )
        if result.get("ok"):
            say(
                f"[Success] 단타 진행 ON ({result.get('lifecycle')}). 예산 Block Kit 확인.\n"
                f"{format_scalp_status_text()}"
            )
        else:
            say(f"[Error] {result.get('reason')}")

    @app.message(re.compile(r"^!단타멈춤\s*$", re.IGNORECASE))
    def cmd_scalp_stop(message, say):
        stop_scalp_trading(via="slack_cmd")
        say(f"[Notice] 단타 진행 OFF.\n{format_scalp_status_text()}")

    @app.message(re.compile(r"^!단타상태\s*$", re.IGNORECASE))
    def cmd_scalp_status(message, say):
        say(format_scalp_status_text())

    @app.message(re.compile(r"^!단타백테스트(?:\s+(\d+))?\s*$", re.IGNORECASE))
    def cmd_scalp_backtest(message, say):
        text = message.get("text", "")
        m = re.match(r"^!단타백테스트(?:\s+(\d+))?\s*$", text, re.IGNORECASE)
        n_days = int(m.group(1)) if (m and m.group(1)) else 60
        say(f"[System] 형태 기반 단타 백테스트 실행 중 (n_days={n_days}, 가격 무관)...")

        def bg_task():
            from src.strategy import scalp_backtest
            result = scalp_backtest.run_and_persist(n_days=n_days)
            set_backtest_gate_result(result)
            status = "PASS" if result.get("passes_gate") else "FAIL"
            say(
                f"[백테스트 {status}] trades={result.get('total_trades')}, "
                f"win_rate={result.get('win_rate', 0):.2%}, "
                f"avg={float(result.get('avg_return') or 0):.4f}, "
                f"total={float(result.get('total_return') or 0):.4f}\n"
                f"- {result.get('gate_reason')}\n"
                f"- 스케줄 등록 조건: 백테스트 PASS + !단타시작(진행 ON)"
            )

        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!수동등록", re.IGNORECASE))
    def manual_register_stock(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        parts = text.split()
        if len(parts) < 2: return say("[Error] 사용법: !수동등록 [종목코드] [트랙(A/B/C/M)]")
        ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
        track_map = {"A": "TRACK_A", "B": "TRACK_B", "C": "TRACK_C", "M": "MANUAL"}
        raw_track = parts[2].upper() if len(parts) > 2 else "M"
        strategy_tag = track_map.get(raw_track, "MANUAL")
        say(f"[System] {ticker} 수동 등록({strategy_tag}) 및 AI 팩트체크를 시작합니다...")

        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            qty, avg_price = 0, 0.0
            for m in ["LIVE", "PAPER"]:
                q, a = kis.get_real_holding_qty(ticker, m)
                if q > 0:
                    qty, avg_price = q, a
                    break
            if qty <= 0:
                say(f"[알림] 잔고 미보유 종목. 관심 종목으로 등록.")
                val0 = kis.get_valuation_data(ticker)
                avg_price = float(val0.get("current_price", "0")) if val0 else 0.0

            result = _build_single_stock_report(
                ticker, fallback_theme="수동등록(단일종목)", strategy_label="수동등록",
                say=say,
            )
            if not result.get("ok"):
                return
            report = result["report"]
            val = result["val"]
            name = val.get("name", ticker)

            sum_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
            reason = f"수동등록 | {sum_match.group(1).strip() if sum_match else 'AI 팩트체크 완료'}"
            from src.utils import logger
            logger.record_trade(
                ticker, name, "BUY", avg_price, qty, reason,
                mode_type="PAPER_ONLY", strategy_tag=strategy_tag,
            )
            say(f"[Success] {name}({ticker}) {strategy_tag} 등록 완료.\n\n{report}")
        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!(일일|주간|월간|분기)보고", re.IGNORECASE))
    def cmd_reports(message, say):
        text = message.get("text", "")
        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"]); kis.set_token(token)
            macro = macro_collector.get_macro_indicators()
            portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
            if "!일일" in text:
                us_kw, kr_kw = ai_strategy.infer_news_keywords().split(',')[:2]
                report = ai_strategy.get_daily_market_report(macro, news_crawler.get_latest_news(us_kw, limit=5, search_type="macro"), news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro"), research_crawler.get_latest_industry_reports(limit=8), "수동 요청")
            else:
                if not portfolio: return say("[결과] 보유 종목이 없습니다.")
                news_dict = {i["name"]: news_crawler.get_latest_news(i["name"], limit=5, search_type="stock") for i in portfolio.values() if i.get("quantity", 0) > 0}
                if "!주간" in text: report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
                elif "!월간" in text: report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
                else: report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
            say(report)
        threading.Thread(target=bg_task, daemon=True).start()

    @app.message(re.compile(r"^!초기화", re.IGNORECASE))
    def reset_data(message, say):
        for f in ["paper_trades.json", "paper_portfolio.json", "split_orders.json", "theme_context.json"]: save_json_to_gdrive({} if "trades" not in f else [], f)
        say("[System] 데이터 초기화 완료.")
