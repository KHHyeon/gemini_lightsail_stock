# -*- coding: utf-8 -*-
import time
from datetime import datetime
from src.core import token_manager
from src.data import collector as macro_collector, chart as chart_data
from src.data.crawler import news_crawler, research_crawler, stock_info_crawler
from src.strategy import ai_logic as ai_strategy, screener as quant_screener
from src.execution.order import OrderManager
from src.utils import helpers as market_hours
from src.utils.logger import load_json_from_gdrive, save_json_to_gdrive

class MarketOrchestrator:
    def __init__(self, kis, app, config):
        self.kis = kis
        self.app = app
        self.config = config # APP_KEY, SECRET_KEY, URL, CHANNEL_ID, etc.

    def send_slack(self, text):
        if self.config.get("CHANNEL_ID"):
            self.app.client.chat_postMessage(channel=self.config["CHANNEL_ID"], text=text)

    def issue_daily_token(self):
        if not market_hours.is_market_open(): return
        token = token_manager.get_access_token(self.config["APP_KEY"], self.config["SECRET_KEY"], force=True)
        self.kis.set_token(token)
        self.send_slack("[System] 08:00 KIS API 일일 접근 토큰 갱신 완료.")

    def get_parsed_keywords(self):
        kw_text = ai_strategy.infer_news_keywords()
        kws = [k.strip() for k in kw_text.split(',')] if kw_text else []
        us_kw = kws[0] if len(kws) > 0 else "미국증시"
        kr_kw = kws[1] if len(kws) > 1 else "한국증시"
        return us_kw, kr_kw

    def daily_routine(self):
        if not market_hours.is_market_open(): return
        self.send_slack("[System] 일일 시황 브리핑 작성을 시작합니다.")
        macro = macro_collector.get_macro_indicators()
        us_kw, kr_kw = self.get_parsed_keywords()
        us_news = news_crawler.get_latest_news(us_kw, limit=5, search_type="macro")
        kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
        research_reports = research_crawler.get_latest_industry_reports(limit=8)
        report = ai_strategy.get_daily_market_report(macro, us_news, kr_news, research_reports, "특이사항 없음")
        self.send_slack(f"[일간 마감 브리핑]\n\n{report}")

    def chronicle_routine(self):
        """15:35 T-Day Market Chronicles (지수 급변/VIX 경계 시)."""
        self.send_slack("[System] Market Chronicles T-Day 분석을 시작합니다.")
        macro = macro_collector.get_macro_indicators()
        us_kw, kr_kw = self.get_parsed_keywords()
        us_news = news_crawler.get_latest_news(us_kw, limit=8, search_type="macro")
        kr_news = news_crawler.get_latest_news(kr_kw, limit=8, search_type="macro")
        from src.memory import chronicle_writer, lifecycle

        ok, msg = chronicle_writer.write_chronicle_for_today(
            macro, us_news, kr_news, notify_fn=self.send_slack
        )
        if not ok:
            self.send_slack(f"[Market Chronicles] {msg}")
        lifecycle.purge_expired_temp_files(notify_fn=self.send_slack)

    def deep_market_routine(self):
        if not market_hours.is_market_open(): return
        self.send_slack("[System] 10:00 장 초반 자금 흐름 기반 심층 시황 보고를 시작합니다.")
        macro = macro_collector.get_macro_indicators()
        _, kr_kw = self.get_parsed_keywords()
        kr_news = news_crawler.get_latest_news(kr_kw, limit=5, search_type="macro")
        research_reports = research_crawler.get_latest_industry_reports(limit=5)
        report = ai_strategy.get_deep_market_report(macro, kr_news, research_reports)
        self.send_slack(f"[10:00 심층 시황 및 전략]\n\n{report}")

    def auto_stock_discovery(self, kst):
        if datetime.now(kst).weekday() >= 5: return
        token = token_manager.get_access_token(self.config["APP_KEY"], self.config["SECRET_KEY"])
        self.kis.set_token(token)
        
        # 조건식 이름과 TRACK 매핑
        track_mapping = {
            "기대주_발굴": "TRACK_A",
            "배당주_발굴": "TRACK_B",
            "낙폭과대_발굴": "TRACK_C"
        }
        
        for condition_name, track_tag in track_mapping.items():
            raw_stocks = quant_screener.run_condition_screener(self.kis, condition_name)
            if not raw_stocks: continue
            
            passed_stocks = quant_screener.run_3track_screener(condition_name, raw_stocks, self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token)
            macro = macro_collector.get_macro_indicators()

            if not passed_stocks:
                self.send_slack(f"[ Track: {condition_name} ]\n- 2차 검증을 통과한 종목이 없습니다.")
                continue

            msg = [f"[ Track: {condition_name} ({track_tag}) ]\n"]
            for s in passed_stocks[:5]:
                name, _, _ = stock_info_crawler.get_stock_info_naver(s['ticker'])
                news = news_crawler.get_latest_news(name, limit=3)
                
                # AI 정밀 리스크 스캔
                bad_news_check = ai_strategy.get_sudden_bad_news(s['ticker'], name, " ".join(news))
                if "[위험]" in bad_news_check:
                    msg.append(f"- {name} ({s['ticker']}) [제외]\n  ㄴ 사유: {bad_news_check}\n")
                    continue
                
                # 종목 등급 및 사유 생성
                if condition_name == "배당주_발굴":
                    rating = ai_strategy.get_dividend_risk_check(s['ticker'], name, news, s, macro=macro)
                else:
                    rating = ai_strategy.get_quick_rating(s['ticker'], name, news, condition_name, s, macro=macro)
                    
                details_str = ", ".join(s.get('score_details', []))
                msg.append(f"- {name} ({s['ticker']})\n  ㄴ 검증: {details_str}\n  ㄴ AI판정: {rating}\n")
                
                # 자동 매수 등록 (예: 100만원 예산, 10일 분할)
                if "[매수추천]" in rating or "[매수]" in rating:
                    split_orders = load_json_from_gdrive("split_orders.json") or {}
                    oid = f"auto_{s['ticker']}_{datetime.now().strftime('%m%d%H%M')}"
                    if not any(v['ticker'] == s['ticker'] for v in split_orders.values()):
                        split_orders[oid] = {
                            "ticker": s['ticker'], "name": name, "daily_budget": 100000, 
                            "remaining_days": 10, "reason": f"AI 자동발굴 ({condition_name})", 
                            "mode_type": "NORMAL", "score": s.get("score", 0),
                            "strategy_tag": track_tag
                        }
                        save_json_to_gdrive(split_orders, "split_orders.json")
                        msg.append(f"  ㄴ [자동등록] {track_tag} 전략으로 분할매수 시작.")

            self.send_slack("\n".join(msg))



    def weekly_routine(self):
        if not market_hours.is_market_open(): return
        self.send_slack("[System] 주간 투자 이유(상승조건) 유효성 진단을 시작합니다.")
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=3, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_weekly_portfolio_report(portfolio, news_dict)
        self.send_slack(f"[주간 이유 확인 리포트]\n\n{report}")

    def monthly_routine(self):
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=4, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_monthly_portfolio_report(portfolio, news_dict)
        self.send_slack(f"[월간 시장 트렌드 및 리밸런싱 리포트]\n\n{report}")

    def quarterly_routine(self):
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return
        news_dict = {info["name"]: news_crawler.get_latest_news(info["name"], limit=5, search_type="stock") for info in portfolio.values() if info.get("quantity", 0) > 0}
        report = ai_strategy.get_quarterly_portfolio_report(portfolio, news_dict)
        self.send_slack(f"[분기 핵심 실적 및 펀더멘털 점검 리포트]\n\n{report}")

    def alert_manual_stocks(self):
        if not market_hours.is_market_open(): return
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return
        
        token = token_manager.get_access_token(self.config["APP_KEY"], self.config["SECRET_KEY"])
        messages = []
        
        for ticker, info in portfolio.items():
            if "수동등록" in info.get("reason", ""):
                val = self.kis.get_valuation_data(ticker)
                if not val or int(val.get("current_price", 0)) <= 0: continue
                current_price = int(val["current_price"])
                
                chart_data_list = chart_data.get_daily_ohlcv(self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token, ticker, count=5)
                if not chart_data_list or len(chart_data_list) < 5: continue
                
                ma5 = sum(day['close'] for day in chart_data_list) / 5
                if current_price <= ma5 * 1.03:
                    messages.append(f"- {info['name']}({ticker}) : 현재가 {current_price:,}원 (5일선 {int(ma5):,}원 부근)")
                    
        if messages:
            self.send_slack("[수동 등록 종목 매수 타점 알림]\n현재 아래 수동 종목들이 매수 타이밍(눌림목)에 진입했습니다. 최종 매수 여부를 직접 결정해 주십시오.\n" + "\n".join(messages))

    def daily_fundamental_stop_loss(self):
        if not market_hours.is_market_open(): return
        portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
        if not portfolio: return
        
        split_orders = load_json_from_gdrive("split_orders.json") or {}
        split_orders_updated = False
        
        token = token_manager.get_access_token(self.config["APP_KEY"], self.config["SECRET_KEY"])
        order_mgr = OrderManager(self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token, self.config["ACC_NO"])
        macro = macro_collector.get_macro_indicators()
        
        keys_to_delete, messages = [], []
        portfolio_updated = False
        
        for ticker, info in portfolio.items():
            qty = info.get("quantity", 0)
            if qty <= 0: continue
            
            name, mode_type, avg_price = info.get("name", ticker), info.get("mode_type", "PAPER_ONLY"), info.get("avg_price", 0)
            high_water_mark = info.get("high_water_mark", avg_price)
            
            val = self.kis.get_valuation_data(ticker)
            if not val or int(val.get("current_price", 0)) <= 0: continue
            current_price = int(val["current_price"])
            
            if current_price > high_water_mark:
                info["high_water_mark"] = current_price
                high_water_mark = current_price
                portfolio_updated = True
                
            trigger_reason, report_comment = None, ""
            
            if avg_price > 0 and current_price <= avg_price * 0.90:
                trigger_reason = "원금 방어선(-10%) 이탈 (기계적 손절)"
            elif avg_price > 0 and high_water_mark > avg_price and current_price <= high_water_mark * 0.90:
                trigger_reason = "최고점 대비 하락선(-10%) 이탈 (추적 익절/손절)"
            else:
                chart_30d = chart_data.get_daily_ohlcv(self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token, ticker, count=30)
                report = ai_strategy.check_fundamental_damage(ticker, name, chart_30d, macro, val, info.get("reason", ""))
                if "[펀더멘털훼손]" in report:
                    trigger_reason = "AI 팩트체크: 투자 이유 훼손 (치명적 악재 발생)"
                    report_comment = f"\n- 코멘트: {report}"
            
            if trigger_reason:
                res = order_mgr.execute_order(ticker, name, qty, current_price, "sell", trigger_reason, mode_type)
                messages.append(res["msg"] + report_comment)
                keys_to_delete.append(ticker)
                
                split_keys_to_delete = [oid for oid, s_info in split_orders.items() if s_info["ticker"] == ticker]
                for k in split_keys_to_delete:
                    del split_orders[k]
                    split_orders_updated = True
                if split_keys_to_delete:
                    messages.append(f"  └── [연쇄 조치] {name} 3중 방어막 가동에 따라 대기 중인 잔여 분할 매수 스케줄 강제 취소.")
                time.sleep(3)
        
        for k in keys_to_delete: del portfolio[k]
        if keys_to_delete or portfolio_updated: save_json_to_gdrive(portfolio, "paper_portfolio.json")
        if split_orders_updated: save_json_to_gdrive(split_orders, "split_orders.json")
        if messages: self.send_slack("[3중 철통 방어막 및 AI 팩트 진단 결과]\n" + "\n\n".join(messages))

    def execute_daily_split_buys(self, check_news=False):
        if not market_hours.is_market_open(): return
        macro_buy = macro_collector.get_macro_indicators()
        try:
            vix = float(macro_buy.get("VIX", 20.0))
            wti = float(macro_buy.get("WTI", 70.0))
            us10y = float(macro_buy.get("US10Y", 4.0))
        except: vix, wti, us10y = 20.0, 70.0, 4.0
            
        shutdown_reason, half_buy_reason = "", ""
        if vix >= 30.0: shutdown_reason = f"VIX 지수 위험 ({vix})"
        elif vix >= 25.0: half_buy_reason = f"VIX 지수 경계 ({vix})"
        if wti >= 95.0: shutdown_reason = f"WTI 유가 위험 ({wti})"
        elif wti >= 90.0: half_buy_reason = f"WTI 유가 경계 ({wti})"
        if us10y >= 4.8: shutdown_reason = f"미 국채 10년물 금리 위험 ({us10y}%)"
        elif us10y >= 4.5: half_buy_reason = f"미 국채 금리 경계 ({us10y}%)"
            
        if shutdown_reason:
            self.send_slack(f"[Macro Shutdown 발동]\n{shutdown_reason}\n오늘의 신규 분할 매수를 전면 중단(Skip)합니다.")
            return

        split_orders = load_json_from_gdrive("split_orders.json") or {}
        if not split_orders: return
        
        token = token_manager.get_access_token(self.config["APP_KEY"], self.config["SECRET_KEY"])
        order_mgr = OrderManager(self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token, self.config["ACC_NO"])
        messages, keys_to_delete = [], []
        if half_buy_reason: messages.append(f"[Macro Alert] {half_buy_reason}\n선제적 리스크 관리를 위해 오늘 매수 예산은 50%로 축소됩니다.")
        
        for oid, info in split_orders.items():
            ticker, name = info["ticker"], info["name"]
            daily_budget = info["daily_budget"]
            if half_buy_reason: daily_budget /= 2
            
            if check_news:
                recent_news = news_crawler.get_latest_news(name, limit=3, search_type="stock")
                news_check = ai_strategy.get_emergency_news_check(name, " ".join(recent_news))
                if "[위험]" in news_check:
                    messages.append(f"[정오 긴급 스캔] {name}({ticker}) 돌발 악재 감지: 매수 스킵.\n사유: {news_check}")
                    continue
            
            val = self.kis.get_valuation_data(ticker)
            if not val or int(val.get("current_price", 0)) <= 0: continue
            current_price = int(val["current_price"])
            chart_data_list = chart_data.get_daily_ohlcv(self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token, ticker, count=5)
            if not chart_data_list or len(chart_data_list) < 5: continue
            
            ma5 = sum(day['close'] for day in chart_data_list) / 5
            threshold = 1.05 if info.get("score", 0) >= 85 else 1.03
            
            if current_price <= ma5 * threshold:
                qty = int(daily_budget // current_price)
                if qty > 0:
                    res = order_mgr.execute_order(ticker, name, qty, current_price, "buy", f"{info['reason']} ({11-info['remaining_days']}/10회차)", info.get("mode_type", "PAPER_ONLY"), strategy_tag=info.get("strategy_tag", "UNKNOWN"))

                    messages.append(res["msg"])
                    info["remaining_days"] -= 1
                else:
                    messages.append(f"[예산 부족] {name}({ticker}): 스킵 ({11-info['remaining_days']}/10회차)")
                    info["remaining_days"] -= 1
            else:
                messages.append(f"[매수 보류] {name}({ticker}): 단기 과열 스킵 [현재가 {current_price:,}원 > 기준가 {int(ma5*threshold):,}원].")

            if info["remaining_days"] <= 0:
                keys_to_delete.append(oid)
                messages.append(f"  └── [알림] {name} 10회 분할 매수 스케줄 최종 종료.")
                
        for k in keys_to_delete: del split_orders[k]
        if messages or keys_to_delete: save_json_to_gdrive(split_orders, "split_orders.json")
        if messages: self.send_slack("[자동 분할 매수 데몬]\n" + "\n".join(messages))

    def scan_and_register_intraday_stocks(self, token):
        # 당일 거래량 급증 및 주도주 실시간 스캔 (HTS 조건식 연동)
        self.send_slack("[System] 정오의 보초: 당일 주도주 실시간 스캔을 시작합니다.")
        
        candidates = quant_screener.run_condition_screener(self.kis, "당일_주도주_발굴")
        if not candidates:
            self.send_slack("- 현재 시간 기준 발굴된 당일 주도주가 없습니다.")
            return

        passed = quant_screener.run_unified_screener(candidates, self.config["URL"], self.config["APP_KEY"], self.config["SECRET_KEY"], token)
        # 70점 이상의 우량주만 선별
        top_picks = [p for p in passed if p.get('score', 0) >= 70]
        
        if not top_picks:
            self.send_slack("- 조건(70점)을 통과한 당일 주도주가 없습니다.")
            return

        split_orders = load_json_from_gdrive("split_orders.json") or {}
        split_orders_updated = False
        messages = []

        for s in top_picks[:3]: # 너무 많지 않게 최대 3개만
            ticker, name = s['ticker'], s['name']
            
            # 이미 매수 진행 중이거나 보유 중인 종목 제외
            if ticker in split_orders: continue
            portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
            if ticker in portfolio and portfolio[ticker].get("quantity", 0) > 0: continue

            # AI 정밀 검증
            news = news_crawler.get_latest_news(name, limit=3, search_type="stock")
            macro_noon = macro_collector.get_macro_indicators()
            rating = ai_strategy.get_quick_rating(ticker, name, news, "당일주도주", s, macro=macro_noon)
            
            if "[매수추천]" in rating or "[매수]" in rating:
                # 자동 편입 (기본 예산 100만원 가정 또는 계좌 잔고 기반 설정 가능)
                # 여기서는 안전을 위해 기본 100만원 예산으로 10일 분할 매수 설정
                total_budget = 1000000 
                daily_budget = total_budget // 10
                
                oid = f"auto_{ticker}_{datetime.now().strftime('%m%d%H%M')}"
                reason = f"정오 보초 발굴 | {rating}"
                
                split_orders[oid] = {
                    "ticker": ticker, "name": name, "daily_budget": daily_budget, 
                    "remaining_days": 10, "reason": reason, "mode_type": "NORMAL", "score": s.get("score", 0)
                }
                split_orders_updated = True
                messages.append(f"- {name}({ticker}) [스코어: {s['score']}점] 자동 매수 편입 완료.\n  ㄴ 사유: {rating}")
        
        if split_orders_updated:
            save_json_to_gdrive(split_orders, "split_orders.json")
        
        if messages:
            self.send_slack("[정오 보초: 신규 주도주 발굴 결과]\n" + "\n".join(messages))
        else:
            self.send_slack("- 정밀 검증(AI)을 통과한 신규 주도주가 없습니다.")

    def noon_routine(self):
        if not market_hours.is_market_open(): return
        self.send_slack("[System] 11:45 정오의 보초 및 자동 분할 매수를 시작합니다.")
        
        token = token_manager.get_access_token(self.config["APP_KEY"], self.config["SECRET_KEY"])
        self.kis.set_token(token)
        
        # 1. 당일 급등 주도주 스캔 및 등록
        self.scan_and_register_intraday_stocks(token)
        
        # 2. 기존 분할 매수 집행 (뉴스 악재 스캔 포함)
        self.execute_daily_split_buys(check_news=True)

    def afternoon_routine(self):
        if not market_hours.is_market_open(): return
        self.send_slack("[System] 14:30 장 마감 전 안전 진단(3중 방어막)을 시작합니다.")
        self.daily_fundamental_stop_loss()
