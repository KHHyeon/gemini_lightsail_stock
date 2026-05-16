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

def register_slack_handlers(app, kis, config):
    
    @app.message(re.compile(r"^!명령어", re.IGNORECASE))
    def cmd_help(message, say):
        help_text = """[ 봇 명령어 매뉴얼 ]
- !잔고 : 실계좌 현금 및 포트폴리오 요약 조회
- !기대주테스트 : 기대주 발굴 (60점 커트 + AI 5단계 검증)
- !배당주테스트 : 배당주 발굴 (AI 배당컷 5단계 검증)
- !발굴 [배당률/테마] : 기존 100점 만점 펀더멘탈 스크리닝
- !ai매수 [코드] [예산] : 정밀 분석 후 10일 분할매수 세팅
- !수동등록 [코드] : 내 보유종목 방어막 감시망에 편입
- !일일보고 / !주간보고 / !월간보고 / !분기보고 : 각종 리포트 수동 생성
- !초기화 : 장부 및 주문 데이터 초기화"""
        say(help_text)

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
            if c['ticker'] not in seen:
                seen.add(c['ticker']); unique_candidates.append(c)
        if not unique_candidates: return say(f"[Error] {keyword_msg} 소속 종목을 추출하지 못했습니다.")
        say(f"[System] 총 {len(unique_candidates)}개 종목 대상 100점 만점 펀더멘털 스크리닝을 시작합니다.")
        token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
        passed_stocks = quant_screener.run_unified_screener(unique_candidates, config["URL"], config["APP_KEY"], config["SECRET_KEY"], token)
        if not passed_stocks: return say(f"[결과] {keyword_msg} 관련 종목 중 펀더멘털 스코어 60점 이상 대장주가 없습니다.")
        theme_memory = load_json_from_gdrive("theme_context.json") or {}
        report_msg = [f"[ 100점 만점 펀더멘털 검증 완료 ({len(passed_stocks)}종목 합격) ]"]
        for p in passed_stocks:
            ticker, name, target_theme = p['ticker'], p['name'], p['target_theme']
            fundamentals = {"score": p.get('score', 0), "details": ', '.join(p.get('score_details', [])), "pbr": p.get("pbr"), "per": p.get("per")}
            narrative = ai_strategy.get_theme_stock_narrative(target_theme, name, ticker, fundamentals)
            theme_memory[ticker] = f"[테마: {target_theme} | 총점: {p.get('score', 0)}]\n{narrative}"
            report_msg.append(f"\n[ {name} ({ticker}) - {target_theme} | 현재가: {p.get('current_price', 0):,}원 ]\n  - 펀더멘털 총점: {p.get('score', 0)}점\n  - 획득 내역: {fundamentals['details']}\n  - [AI 팩트체크]\n{narrative}")
        save_json_to_gdrive(theme_memory, "theme_context.json")
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

    @app.message(re.compile(r"^!ai매수", re.IGNORECASE))
    def ai_buy_stock(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        parts = text.split()
        if len(parts) < 3: return say("[Error] 사용법: !ai매수 [종목코드] [총예산]")
        ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
        budget = int(re.sub(r'[^\d]', '', parts[2]))
        
        def bg_task():
            try:
                name, div, is_etf = stock_info_crawler.get_stock_info_naver(ticker)
                if is_etf: return say(f"[거절] {name}({ticker})은(는) ETF 종목입니다.")
                actual_mode = os.getenv("TRADING_MODE_NORMAL", "PAPER").upper()
                say(f"[System] {name}({ticker}) AI 보고서 작성 중... ({actual_mode})")
                token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
                kis.set_token(token)
                val = kis.get_valuation_data(ticker)
                if not val or int(val.get("current_price", 0)) <= 0: return say(f"[에러] {name} 주가 데이터를 가져오지 못했습니다.")
                val.update({"div_yield": div, "name": name})
                chart_30d = chart_data.get_daily_ohlcv(config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, ticker, count=30)
                macro = macro_collector.get_macro_indicators()
                pf = load_json_from_gdrive("paper_portfolio.json") or {}
                theme_mem = load_json_from_gdrive("theme_context.json") or {}
                news = news_crawler.get_latest_news(name, limit=5, search_type="stock")
                passed = quant_screener.run_unified_screener([{"ticker": ticker, "name": name}], config["URL"], config["APP_KEY"], config["SECRET_KEY"], token)
                score = passed[0].get("score", 0) if passed else 0
                report = ai_strategy.get_ai_investment_report(ticker, name, chart_30d, macro, pf, val, theme_mem.get(ticker, ""), news)
                oid = str(uuid.uuid4())
                sum_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
                pending_orders[oid] = {"ticker": ticker, "total_budget": budget, "current_price": int(val.get("current_price", 0)), "stock_name": name, "mode_type": "NORMAL", "reason": sum_match.group(1).strip() if sum_match else "AI 분석 완료", "score": score}
                say(f"[System] {name}({ticker}) 최종 AI 리포트\n\n{report}")
                say(blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": f"최종 10일 분할매수({actual_mode}) 승인을 내려주십시오."}}, {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": f"승인 ({actual_mode} 매수)"}, "style": "primary", "action_id": "approve_buy", "value": oid}, {"type": "button", "text": {"type": "plain_text", "text": "기각 (취소)"}, "style": "danger", "action_id": "reject_buy", "value": oid}]}], text="승인 대기 중")
            except Exception as e: say(f"[Error] AI 매수 보고서 에러: {e}")
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
            split_orders[str(uuid.uuid4())] = {"ticker": order["ticker"], "name": order["stock_name"], "daily_budget": res["daily_budget"], "remaining_days": 10, "reason": reason, "mode_type": order["mode_type"], "score": order.get("score", 0)}
            save_json_to_gdrive(split_orders, "split_orders.json")
            respond(text=f"[Success] <@{body['user']['id']}> 님이 승인했습니다.\n{res['msg']}", replace_original=True)
        else: respond(text=f"[Fail] {res['msg']}", replace_original=True)

    @app.action("reject_buy")
    def action_reject_buy(ack, body, respond):
        ack(); (pending_orders.pop(body["actions"][0]["value"]) if body["actions"][0]["value"] in pending_orders else None)
        respond(text=f"[Notice] <@{body['user']['id']}> 님이 매수를 기각했습니다.", replace_original=True)

    @app.message(re.compile(r"^!수동등록", re.IGNORECASE))
    def manual_register_stock(message, say):
        text = re.sub(r'<[^|>]*\|([^>]+)>|<([^>]+)>', r'\1', message.get("text", ""))
        parts = text.split()
        if len(parts) < 2: return say("[Error] 사용법: !수동등록 [종목코드]")
        ticker = re.sub(r'[^A-Za-z0-9]', '', parts[1])[:6].upper()
        say(f"[System] {ticker} 수동 등록 및 AI 팩트체크를 시작합니다...")
        def bg_task():
            token = token_manager.get_access_token(config["APP_KEY"], config["SECRET_KEY"])
            kis.set_token(token)
            qty, avg_price, found_mode = 0, 0.0, "PAPER_ONLY"
            for m in ["LIVE", "PAPER"]:
                q, a = kis.get_real_holding_qty(ticker, m)
                if q > 0: qty, avg_price, found_mode = q, a, ("LIVE_MANUAL" if m == "LIVE" else "PAPER_ONLY"); break
            if qty <= 0:
                say(f"[알림] 잔고 미보유 종목. 관심 종목으로 등록."); val = kis.get_valuation_data(ticker); avg_price = float(val.get("current_price", "0")) if val else 0.0
            name, div, is_etf = stock_info_crawler.get_stock_info_naver(ticker)
            if is_etf: return say(f"[거절] {name}은(는) ETF입니다.")
            val = kis.get_valuation_data(ticker); val.update({"div_yield": div, "name": name})
            chart_30d = chart_data.get_daily_ohlcv(config["URL"], config["APP_KEY"], config["SECRET_KEY"], token, ticker, count=30)
            macro = macro_collector.get_macro_indicators()
            news = news_crawler.get_latest_news(name, limit=5, search_type="stock")
            portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
            report = ai_strategy.get_ai_investment_report(ticker, name, chart_30d, macro, portfolio, val, "수동 발굴", news)
            sum_match = re.search(r'\[한줄요약\](.*)', report, re.DOTALL)
            reason = f"수동등록 | {sum_match.group(1).strip() if sum_match else 'AI 팩트체크 완료'}"
            portfolio[ticker] = {"name": name, "quantity": qty, "avg_price": avg_price, "high_water_mark": max(portfolio.get(ticker, {}).get("high_water_mark", avg_price), avg_price), "mode_type": found_mode, "reason": reason, "buy_date": datetime.now().strftime("%Y-%m-%d")}
            save_json_to_gdrive(portfolio, "paper_portfolio.json")
            say(f"[Success] {name}({ticker}) 등록 완료.\n\n{report}")
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
