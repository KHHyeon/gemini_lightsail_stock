# -*- coding: utf-8 -*-
# File: ~/my_bot/backtester.py
import os
from dotenv import load_dotenv

load_dotenv()

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from trade_logger import load_json_from_gdrive

class ThemeBacktester:
    def __init__(self, tickers, start_date, end_date, initial_capital=10000000):
        self.tickers = [t if t.endswith(".KS") or t.endswith(".KQ") else f"{t}.KS" for t in tickers]
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.data = {}

    def fetch_data(self):
        print(f"[Backtester] {len(self.tickers)}개 종목 최근 1년 데이터 다운로드 중...")
        for ticker in self.tickers:
            df = yf.download(ticker, start=self.start_date, end=self.end_date, progress=False)
            if not df.empty:
                self.data[ticker] = df
            else:
                print(f"  └ 경고: {ticker} 데이터를 불러오지 못했습니다. (.KQ 확인 필요)")
        print(f"[Backtester] 총 {len(self.data)}개 종목 데이터 확보 완료.\n")

    def run_simulation(self):
        if not self.data:
            print("백테스트할 유효한 주가 데이터가 없습니다.")
            return

        capital_per_stock = self.initial_capital / len(self.data)
        results = []

        print("--- [시뮬레이션 시작: 리스크 매니지먼트 3중 필터 적용] ---")
        for ticker, df in self.data.items():
            try:
                buy_price = df['Close'].iloc[0]
                if isinstance(buy_price, pd.Series): buy_price = buy_price.item()
                
                qty = int(capital_per_stock // buy_price)
                invested_amount = qty * buy_price
                if qty == 0: continue
                
                highest_price = buy_price
                sell_price = 0
                sell_reason = "보유중 (기간 종료)"

                for i in range(1, len(df)):
                    current_price = df['Close'].iloc[i]
                    if isinstance(current_price, pd.Series): current_price = current_price.item()
                    
                    high_price_today = df['High'].iloc[i]
                    if isinstance(high_price_today, pd.Series): high_price_today = high_price_today.item()

                    if high_price_today > highest_price:
                        highest_price = high_price_today

                    profit_rate = ((current_price - buy_price) / buy_price) * 100
                    peak_profit_rate = ((highest_price - buy_price) / buy_price) * 100
                    drawdown_from_peak = ((current_price - highest_price) / highest_price) * 100

                    # 1. 원금 손절 (-10%)
                    if profit_rate <= -10.0:
                        sell_price = current_price
                        sell_reason = f"원금 손절 (-10% 도달)"
                        break
                    
                    # 2. 시간 손절 (56일/8주 경과, 수익률 5% 미만)
                    if i >= 56 and profit_rate < 5.0:
                        sell_price = current_price
                        sell_reason = f"시간 손절 (8주 경과)"
                        break
                    
                    # 3. 추적 손절 (고점 20% 이상 달성 후 5% 하락)
                    if peak_profit_rate >= 20.0 and drawdown_from_peak <= -5.0:
                        sell_price = current_price
                        sell_reason = f"추적 익절 (고점대비 5% 하락)"
                        break

                if sell_price == 0:
                    sell_price = df['Close'].iloc[-1]
                    if isinstance(sell_price, pd.Series): sell_price = sell_price.item()

                final_amount = qty * sell_price
                pnl_pct = ((final_amount - invested_amount) / invested_amount) * 100 if invested_amount > 0 else 0
                
                results.append({
                    "Ticker": ticker,
                    "Buy Price": round(buy_price),
                    "Sell Price": round(sell_price),
                    "Return (%)": round(pnl_pct, 2),
                    "Reason": sell_reason,
                    "Final Amount": final_amount,
                    "Invested": invested_amount
                })
            except Exception as e:
                print(f"  └ 에러: {ticker} 시뮬레이션 중 오류 발생 ({str(e)})")

        if not results:
            print("시뮬레이션 결과가 없습니다.")
            return

        print("\n--- [과거 1년 백테스트 결과] ---")
        total_invested = sum([r['Invested'] for r in results])
        total_final = sum([r['Final Amount'] for r in results])
        
        remaining_cash = self.initial_capital - total_invested
        total_equity = total_final + remaining_cash
        
        total_return = ((total_equity - self.initial_capital) / self.initial_capital) * 100
        
        for r in results:
            print(f"- {r['Ticker']}: 수익률 {r['Return (%)']:+.2f}% | 사유: {r['Reason']}")
            
        print(f"\n* 테스트 기간: {self.start_date} ~ {self.end_date}")
        print(f"* 초기 자본: {self.initial_capital:,} 원")
        print(f"* 최종 자본: {int(total_equity):,} 원")
        print(f"* 총 계좌 수익률: {total_return:+.2f}%")

if __name__ == "__main__":
    print("Log: [System] 구글 드라이브에서 현재 보유 종목을 불러옵니다...")
    portfolio = load_json_from_gdrive("paper_portfolio.json") or {}
    
    current_tickers = [ticker for ticker, info in portfolio.items() if info.get("quantity", 0) > 0]
    
    if not current_tickers:
        print("현재 포트폴리오에 보유 중인 종목이 없습니다. 백테스트를 종료합니다.")
    else:
        names = [portfolio[t].get("name", t) for t in current_tickers]
        print(f"발견된 보유 종목 ({len(current_tickers)}개): {', '.join(names)}")
        
        # [수정] 테마주 사이클에 맞춰 현재 시간부터 정확히 1년(365일) 전으로 세팅
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=365)
        
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")
        
        print(f"\n=== 퀀트 전략 단기(1년) 트렌드 백테스트 ({start_str} ~ {end_str}) ===")
        tester = ThemeBacktester(current_tickers, start_str, end_str)
        tester.fetch_data()
        tester.run_simulation()
