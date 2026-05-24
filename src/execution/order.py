# -*- coding: utf-8 -*-
"""LIVE/PAPER 주문 집행. KIS POST 호출은 kis_api._call_kis 로 일원화.

v3.3.1 패치로 주문 입력 매개변수를 ``OrderRequest`` dataclass 로 묶고,
``OrderManager.submit(request)`` 을 신규 진입점으로 도입한다. 기존
``execute_order(ticker, name, ...)`` 위치 인자형 메서드는 호환 wrapper
로 유지되며, 내부적으로 ``OrderRequest`` 를 생성한 뒤 ``submit`` 을
호출한다. 신규 호출부는 ``OrderRequest`` + ``submit`` 사용을 권장한다.
"""
import os
from dataclasses import dataclass

from src.core.kis_api import _call_kis
from src.utils.logger import record_trade
from src.utils.timekit import kst_strftime


@dataclass(frozen=True)
class OrderRequest:
    """주문 요청 단일 데이터 구조.

    Attributes:
        ticker: 6자리 종목 코드.
        name: 종목명 (슬랙 메시지·로그 노출용).
        quantity: 주문 수량.
        current_price: 기준 가격 (모의 체결가·로그용. 실전 주문은 시장가 ``ORD_DVSN='01'``).
        side: ``"buy"`` 또는 ``"sell"``.
        reason: 사유 문자열. 슬랙·로그에 그대로 노출.
        mode_type: ``"NORMAL"`` / ``"SMALL"`` / ``"PAPER_ONLY"`` / ``"LIVE_MANUAL"``.
        strategy_tag: 전략 태그 (``"TRACK_A"``/``"TRACK_B"``/``"TRACK_C"``/``"MANUAL"``).
    """

    ticker: str
    name: str
    quantity: int
    current_price: int
    side: str
    reason: str
    mode_type: str = "NORMAL"
    strategy_tag: str = "UNKNOWN"


class OrderManager:
    def __init__(self, base_url, app_key, secret_key, token, acc_no):
        self.base_url = base_url
        self.app_key = app_key
        self.secret_key = secret_key
        self.token = token
        self.acc_no = acc_no

    def _resolve_mode(self, mode_type):
        """주문 모드 결정.

        - ``PAPER_ONLY`` → 항상 PAPER (수동 등록 종목 등 독립성 보장)
        - ``LIVE_MANUAL`` → 항상 LIVE (전체 환경변수와 무관 강제 실전 매도)
        - 그 외 (``SMALL`` / ``NORMAL``) → ``TRADING_MODE_SMALL`` /
          ``TRADING_MODE_NORMAL`` 환경변수를 따른다 (기본 ``"PAPER"``).
        """
        if mode_type == "SCALP":
            return os.getenv("TRADING_MODE_SCALP", "PAPER").upper()
        if mode_type == "PAPER_ONLY":
            return "PAPER"
        if mode_type == "LIVE_MANUAL":
            return "LIVE"
        env_var = "TRADING_MODE_SMALL" if mode_type == "SMALL" else "TRADING_MODE_NORMAL"
        return os.getenv(env_var, "PAPER").upper()

    def submit(self, request):
        """주문 집행 단일 진입점.

        Args:
            request: ``OrderRequest`` 인스턴스.

        Returns:
            dict: ``{"success": bool, "msg": str}``.
        """
        mode = self._resolve_mode(request.mode_type)
        action = "BUY" if request.side == "buy" else "SELL"
        now_str = kst_strftime("%Y-%m-%d %H:%M:%S")

        if mode == "LIVE":
            tr_id = "TTTC0802U" if request.side == "buy" else "TTTC0801U"
            payload = {
                "CANO": self.acc_no[:8],
                "ACNT_PRDT_CD": self.acc_no[8:],
                "PDNO": request.ticker,
                "ORD_DVSN": "01",
                "ORD_QTY": str(int(request.quantity)),
                "ORD_UNPR": "0",
            }
            data = _call_kis(
                self.base_url,
                self.app_key,
                self.secret_key,
                self.token,
                tr_id=tr_id,
                endpoint="/uapi/domestic-stock/v1/trading/order-cash",
                method="POST",
                custtype="P",
                json_body=payload,
                timeout=10,
            )
            if data is None:
                return {"success": False, "msg": "[실전 통신 에러] KIS API 호출 실패"}
            if data.get("rt_cd") == "0":
                record_trade(
                    request.ticker, request.name, action,
                    request.current_price, request.quantity,
                    f"[LIVE-{request.mode_type}] {request.reason}",
                    mode_type=request.mode_type,
                    strategy_tag=request.strategy_tag,
                    purchase_date=now_str,
                )
                return {
                    "success": True,
                    "msg": (
                        f"[실전 {action} 체결] {request.name}({request.ticker}) "
                        f"{request.quantity}주 시장가 주문 접수 완료\n"
                        f"- 사유: {request.reason}\n- 태그: {request.strategy_tag}"
                    ),
                }
            return {
                "success": False,
                "msg": f"[실전 주문 실패] {data.get('msg1', '알 수 없는 API 거부')}",
            }

        record_trade(
            request.ticker, request.name, action,
            request.current_price, request.quantity,
            f"[PAPER-{request.mode_type}] {request.reason}",
            mode_type=request.mode_type,
            strategy_tag=request.strategy_tag,
            purchase_date=now_str,
        )
        return {
            "success": True,
            "msg": (
                f"[모의 {action}] {request.name}({request.ticker}) "
                f"{request.quantity}주 @ {request.current_price}원\n"
                f"- 사유: {request.reason}\n- 태그: {request.strategy_tag}"
            ),
        }

    def execute_order(self, ticker, name, quantity, current_price, side, reason,
                      mode_type="NORMAL", strategy_tag="UNKNOWN"):
        """위치 인자형 호환 wrapper.

        v3.3.1 이전 호출부와의 하위 호환을 위해 유지한다. 내부적으로
        ``OrderRequest`` 를 생성한 뒤 ``submit`` 을 호출하며, 신규 호출부는
        ``submit(OrderRequest(...))`` 직접 사용을 권장한다.
        """
        request = OrderRequest(
            ticker=ticker,
            name=name,
            quantity=quantity,
            current_price=current_price,
            side=side,
            reason=reason,
            mode_type=mode_type,
            strategy_tag=strategy_tag,
        )
        return self.submit(request)

    def simulate_split_buy(self, ticker, name, total_budget, current_price, reason):
        if current_price <= 0:
            return {"success": False, "msg": "주가 데이터 오류"}

        daily_budget = total_budget / 10
        adjusted = False

        if daily_budget < current_price:
            daily_budget = current_price
            total_budget = daily_budget * 10
            adjusted = True

        qty = int(daily_budget // current_price)
        msg = f"{name} 분할 매수 승인. (1회차 {qty}주 대기)"

        if adjusted:
            msg += (
                f"\n[예산 자동 보정] 입력하신 예산이 적어, 최소 1주 매수를 위해 "
                f"총 예산이 {int(total_budget):,}원으로 상향 조정되었습니다."
            )

        return {"success": True, "msg": msg, "daily_budget": daily_budget}
