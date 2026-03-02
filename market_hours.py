# -*- coding: utf-8 -*-
# File: ~/my_bot/market_hours.py
from datetime import datetime
import pytz

def is_market_open():
    """
    Checks if the Korean Market is currently open.
    KST: Monday - Friday, 09:00 - 15:30
    """
    # Set timezone to KST
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    
    # Check if it's a weekend (5: Saturday, 6: Sunday)
    if now.weekday() >= 5:
        return False
    
    # Check time range (09:00 - 15:30)
    start_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    return start_time <= now <= end_time

def get_current_kst_time():
    kst = pytz.timezone('Asia/Seoul')
    return datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S KST')
