# -*- coding: utf-8 -*-
# File: ~/my_bot/macro_collector.py
import yfinance as yf
from datetime import datetime

def get_macro_trend(ticker_symbol):
    """
    1개월간의 데이터를 수집하여 현재, 1주전, 1달전 수치와 추세를 분석하여 반환합니다.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="1mo")
        if not hist.empty:
            closes = hist['Close']
            current = float(closes.iloc[-1])
            month_ago = float(closes.iloc[0])
            week_ago = float(closes.iloc[-5]) if len(closes) >= 5 else month_ago
            
            trend = "상승" if current > month_ago else "하락"
            if abs(current - month_ago) / month_ago < 0.01: 
                trend = "보합"
                
            return {
                "current": round(current, 2), 
                "week_ago": round(week_ago, 2), 
                "month_ago": round(month_ago, 2), 
                "trend": trend
            }
        print(f"Log: [Macro Warning] {ticker_symbol} 데이터가 비어있습니다.")
        return None
    except Exception as e:
        print(f"Log: [Macro Error] {ticker_symbol} 수집 실패: {str(e)}")
        return None

def get_macro_indicators():
    """
    환율, 미국 10년물 국채 금리, WTI 유가, 금 시세, VIX 지수의 1개월 추세를 수집합니다.
    """
    indicators = {
        "환율(USD/KRW)": get_macro_trend("KRW=X"),
        "미 국채 10년물 금리(%)": get_macro_trend("^TNX"),
        "WTI 원유(달러)": get_macro_trend("CL=F"),
        "국제 금(달러)": get_macro_trend("GC=F"),
        "VIX 공포지수": get_macro_trend("^VIX")
    }
    
    summary_lines = []
    summary_lines.append("[ 주요 매크로 지표 현황 ]")
    for name, data in indicators.items():
        if data:
            summary_lines.append(f"- {name}: 현재 {data['current']} / 1주전 {data['week_ago']} / 1달전 {data['month_ago']} (추세: {data['trend']})")
    
    # AI 요약용 텍스트와 하드스탑 판단용 개별 수치를 함께 반환
    vix_data = indicators.get("VIX 공포지수")
    wti_data = indicators.get("WTI 원유(달러)")
    us10y_data = indicators.get("미 국채 10년물 금리(%)")
    
    return {
        "ai_summary": "\n".join(summary_lines) if len(summary_lines) > 1 else "데이터 수집 실패",
        "VIX": vix_data["current"] if vix_data else 20.0,
        "WTI": wti_data["current"] if wti_data else 70.0,
        "US10Y": us10y_data["current"] if us10y_data else 4.0
    }
