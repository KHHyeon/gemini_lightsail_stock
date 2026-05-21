# -*- coding: utf-8 -*-
"""Drive 임시 기술 데이터 30일 TTL 정리."""
from datetime import datetime, timedelta

from src.memory import drive_client
from src.utils.timekit import KST, now_kst

TEMP_TECH_PREFIX = f"{drive_client.CHRONICLES_ROOT}/temp/tech"
TTL_DAYS = 30


def purge_expired_temp_files(notify_fn=None):
    if not drive_client.is_ready():
        return 0, "Drive 미준비"

    try:
        file_list = drive_client.list_files_under(TEMP_TECH_PREFIX)
    except Exception as e:
        return 0, str(e)

    cutoff_dt = now_kst() - timedelta(days=TTL_DAYS)
    deleted_count = 0
    for file_meta in file_list:
        if file_meta.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        modified_iso = file_meta.get("modifiedTime") or file_meta.get("createdTime")
        if not modified_iso:
            continue
        try:
            modified_dt = datetime.fromisoformat(
                modified_iso.replace("Z", "+00:00")
            ).astimezone(KST)
        except ValueError:
            continue
        if modified_dt < cutoff_dt:
            try:
                drive_client.delete_file_by_id(file_meta["id"])
                deleted_count += 1
            except Exception:
                pass

    msg = f"임시 파일 {deleted_count}건 삭제 (TTL {TTL_DAYS}일)"
    if notify_fn and deleted_count > 0:
        notify_fn(f"[Market Chronicles] {msg}")
    return deleted_count, msg
