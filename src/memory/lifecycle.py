# -*- coding: utf-8 -*-
"""Drive 임시 기술 데이터 30일 TTL 정리."""
from datetime import datetime, timezone, timedelta

from src.memory import drive_client

KST = timezone(timedelta(hours=9))
TEMP_TECH_PREFIX = f"{drive_client.CHRONICLES_ROOT}/temp/tech"
TTL_DAYS = 30


def purge_expired_temp_files(notify_fn=None):
    if not drive_client.is_ready():
        return 0, "Drive 미준비"

    try:
        files = drive_client.list_files_under(TEMP_TECH_PREFIX)
    except Exception as e:
        return 0, str(e)

    cutoff = datetime.now(KST) - timedelta(days=TTL_DAYS)
    deleted = 0
    for f in files:
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        mod = f.get("modifiedTime") or f.get("createdTime")
        if not mod:
            continue
        try:
            mod_dt = datetime.fromisoformat(mod.replace("Z", "+00:00")).astimezone(KST)
        except ValueError:
            continue
        if mod_dt < cutoff:
            try:
                drive_client.delete_file_by_id(f["id"])
                deleted += 1
            except Exception:
                pass

    msg = f"임시 파일 {deleted}건 삭제 (TTL {TTL_DAYS}일)"
    if notify_fn and deleted > 0:
        notify_fn(f"[Market Chronicles] {msg}")
    return deleted, msg
