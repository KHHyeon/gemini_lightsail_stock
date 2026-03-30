# -*- coding: utf-8 -*-
# File: ~/my_bot/trade_logger.py
import json
import os
import io
import time
from datetime import datetime, timezone, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# 한국 표준시(KST) 설정
KST = timezone(timedelta(hours=9))

FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def get_file_id(service, filename, retries=3):
    """지정된 폴더 내에서 파일 이름으로 파일 ID를 검색합니다. (통신 지연 대비 재시도 추가)"""
    query = f"name='{filename}' and '{FOLDER_ID}' in parents and trashed=false"
    for i in range(retries):
        try:
            results = service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            items = results.get('files', [])
            if items:
                return items[0]['id']
            return None
        except Exception as e:
            if i == retries - 1:
                print(f"Log: [GDrive Search Error] 파일 검색 완전 실패: {str(e)}", flush=True)
                return None
            time.sleep(1)
    return None

def load_json_from_gdrive(filename):
    """구글 드라이브에서 JSON 데이터를 메모리로 읽어옵니다."""
    try:
        service = get_drive_service()
        file_id = get_file_id(service, filename)
        if not file_id:
            return None
        
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        fh.seek(0)
        return json.loads(fh.read().decode('utf-8'))
    except Exception as e:
        print(f"Log: [GDrive Load Error] {filename} 로드 실패: {str(e)}", flush=True)
        return None

def save_json_to_gdrive(data, filename):
    """구글 드라이브에 JSON 데이터를 업로드/업데이트합니다."""
    try:
        service = get_drive_service()
        file_id = get_file_id(service, filename)
        
        json_bytes = json.dumps(data, indent=4, ensure_ascii=False).encode('utf-8')
        media = MediaIoBaseUpload(io.BytesIO(json_bytes), mimetype='application/json', resumable=True)
        
        if file_id:
            try:
                service.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
            except Exception as e:
                print(f"Log: [GDrive Update Error] [경고] {filename} 업데이트 중 403 에러 발생 (버전 기록 폭발 의심): {str(e)}", flush=True)
        else:
            try:
                print(f"Log: [GDrive] {filename} 파일을 찾지 못해 새로 생성을 시도합니다.", flush=True)
                file_metadata = {'name': filename, 'parents': [FOLDER_ID]}
                service.files().create(body=file_metadata, media_body=media, supportsAllDrives=True).execute()
            except Exception as e:
                print(f"Log: [GDrive Create Error] [경고] {filename} 생성 중 403 용량 에러 발생: {str(e)}", flush=True)
    except Exception as e:
        print(f"Log: [GDrive Save System Error] {str(e)}", flush=True)

def record_trade(ticker, name, action, price, quantity, reason):
    """모의 매매 내역을 구글 드라이브에 기록하고 가상 포트폴리오를 업데이트합니다."""
    trade_record = {
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "ticker": ticker,
        "name": name,
        "action": action,
        "price": price,
        "quantity": quantity,
        "total_amount": price * quantity,
        "reason": reason
    }
    
    log_filename = "paper_trades.json"
    history = load_json_from_gdrive(log_filename) or []
    history.append(trade_record)
    save_json_to_gdrive(history, log_filename)
        
    portfolio_filename = "paper_portfolio.json"
    portfolio = load_json_from_gdrive(portfolio_filename) or {}
            
    if ticker not in portfolio:
        portfolio[ticker] = {"name": name, "quantity": 0, "avg_price": 0.0}
        
    current_qty = portfolio[ticker]["quantity"]
    current_avg = portfolio[ticker]["avg_price"]
    
    if action == "BUY":
        new_qty = current_qty + quantity
        new_avg = ((current_qty * current_avg) + (quantity * price)) / new_qty
        portfolio[ticker]["quantity"] = new_qty
        portfolio[ticker]["avg_price"] = new_avg
    elif action == "SELL":
        new_qty = max(0, current_qty - quantity)
        portfolio[ticker]["quantity"] = new_qty
        if new_qty == 0:
            portfolio[ticker]["avg_price"] = 0.0
            
    save_json_to_gdrive(portfolio, portfolio_filename)
        
    return trade_record
