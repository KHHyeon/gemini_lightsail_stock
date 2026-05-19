# -*- coding: utf-8 -*-
"""
Google Drive API 클라이언트.
- Market Chronicles 데이터는 Drive에만 저장한다.
- OAuth 토큰 파일은 인증 전용이며 시장 데이터가 아니다.
"""
import io
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SCOPES = ["https://www.googleapis.com/auth/drive"]
CHRONICLES_ROOT = "MarketChronicles"
APP_DATA_PREFIX = "app_data"
PAUSE_REL_PATH = f"{CHRONICLES_ROOT}/_system/pause_state.json"
MANIFEST_REL_PATH = f"{CHRONICLES_ROOT}/_system/folder_manifest.json"
MASTER_INDEX_REL = f"{CHRONICLES_ROOT}/index/master_index.json"

_DRIVE_SERVICE = None
_FOLDER_CACHE = None


class DrivePausedError(Exception):
    """사용자 개입 대기 중."""

    def __init__(self, reason, action_required):
        self.reason = reason
        self.action_required = action_required
        super().__init__(reason)


class DriveNotConfiguredError(Exception):
    pass


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_service_account_path():
    """서비스 계정 JSON 경로 (신규·레거시 env 모두 지원)."""
    return (
        os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", "").strip()
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    )


def get_root_folder_id_env():
    """Drive 루트 폴더 ID (신규·레거시 env 모두 지원)."""
    return (
        os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_ID", "").strip()
        or os.getenv("GDRIVE_FOLDER_ID", "").strip()
    )


def is_drive_configured():
    sa = get_service_account_path()
    oauth = os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "").strip()
    return bool(sa or oauth)


def is_drive_enabled():
    return os.getenv("GOOGLE_DRIVE_ENABLED", "1").strip() not in ("0", "false", "False")


def _get_service():
    global _DRIVE_SERVICE
    if _DRIVE_SERVICE is not None:
        return _DRIVE_SERVICE
    if not is_drive_configured():
        raise DriveNotConfiguredError(
            "GOOGLE_APPLICATION_CREDENTIALS 또는 GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE 미설정"
        )

    sa_path = get_service_account_path()
    if sa_path and os.path.isfile(sa_path):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        _DRIVE_SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
        return _DRIVE_SERVICE

    oauth_path = os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "").strip()
    if not oauth_path or not os.path.isfile(oauth_path):
        raise DriveNotConfiguredError("Drive 인증 파일을 찾을 수 없습니다.")

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_path = os.path.join(_project_root(), "drive_oauth_token.json")
    creds = None
    if os.path.isfile(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(oauth_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    _DRIVE_SERVICE = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _DRIVE_SERVICE


def _now_iso():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def get_pause_state():
    if not is_drive_enabled() or not is_drive_configured():
        return None
    try:
        return read_json_relative(PAUSE_REL_PATH)
    except Exception:
        return None


def is_paused():
    state = get_pause_state()
    if state and state.get("paused"):
        return True
    local = os.path.join(_project_root(), ".drive_pause_local.json")
    if os.path.isfile(local):
        try:
            with open(local, "r", encoding="utf-8") as f:
                return bool(json.load(f).get("paused"))
        except Exception:
            pass
    return False


def pause(reason, action_required):
    state = {
        "paused": True,
        "reason": reason,
        "action_required": action_required,
        "since": _now_iso(),
    }
    write_json_relative(PAUSE_REL_PATH, state)
    return state


def clear_pause():
    write_json_relative(
        PAUSE_REL_PATH,
        {"paused": False, "cleared_at": _now_iso()},
    )


def try_resume_after_user_ack():
    """사용자 '완료' 응답 후 Drive 재검사."""
    if not is_drive_configured():
        return "[Drive] 인증이 설정되지 않았습니다. GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE 등을 확인하세요."
    try:
        svc = _get_service()
        root_id = _resolve_root_folder_id(svc)
        _ensure_chronicle_structure(svc, root_id, force_refresh=True)
        clear_pause()
        _clear_local_pause_flag()
        global _FOLDER_CACHE
        _FOLDER_CACHE = None
        return f"[Drive] 연결 및 폴더 검증 완료. (root: {root_id})"
    except Exception as e:
        pause(str(e), "Drive 권한·폴더·용량을 확인한 뒤 다시 '완료'를 입력하세요.")
        return f"[Drive] 재검사 실패: {e}"


def _check_pause_guard():
    if is_paused():
        state = get_pause_state() or {}
        raise DrivePausedError(
            state.get("reason", "대기 중"),
            state.get("action_required", "슬랙에 '완료'를 입력하세요."),
        )


def is_ready():
    if not is_drive_enabled() or not is_drive_configured():
        return False
    if is_paused():
        return False
    try:
        svc = _get_service()
        _resolve_root_folder_id(svc)
        return True
    except Exception:
        return False


def _resolve_root_folder_id(svc):
    env_id = get_root_folder_id_env()
    if env_id:
        return env_id
    manifest = _load_manifest_local()
    if manifest and manifest.get("root_folder_id"):
        return manifest["root_folder_id"]
    folder_name = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_NAME", "AutoStockBot_Data")
    q = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    res = svc.files().list(q=q, fields="files(id,name)", pageSize=5).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    created = svc.files().create(body=meta, fields="id").execute()
    return created["id"]


def _load_manifest_local():
    global _FOLDER_CACHE
    if _FOLDER_CACHE is not None:
        return _FOLDER_CACHE
    try:
        _FOLDER_CACHE = read_json_relative(MANIFEST_REL_PATH) or {}
    except Exception:
        _FOLDER_CACHE = {}
    return _FOLDER_CACHE


def _save_manifest(manifest):
    global _FOLDER_CACHE
    _FOLDER_CACHE = manifest
    write_json_relative(MANIFEST_REL_PATH, manifest)


def _find_child_folder(svc, parent_id, name):
    q = (
        f"'{parent_id}' in parents and name='{name}' "
        "and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(svc, parent_id, name):
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    return svc.files().create(body=meta, fields="id").execute()["id"]


def _ensure_path_folders(svc, root_id, parts):
    manifest = _load_manifest_local() or {}
    if manifest.get("root_folder_id") != root_id:
        manifest = {"root_folder_id": root_id, "paths": {}}
    paths = manifest.setdefault("paths", {})
    current = root_id
    built = []
    for part in parts:
        built.append(part)
        key = "/".join(built)
        if key in paths:
            current = paths[key]
            continue
        fid = _find_child_folder(svc, current, part)
        if not fid:
            fid = _create_folder(svc, current, part)
        paths[key] = fid
        current = fid
    _save_manifest(manifest)
    return current


def _ensure_chronicle_structure(svc, root_id, force_refresh=False):
    if force_refresh:
        global _FOLDER_CACHE
        _FOLDER_CACHE = None
    parts = [
        CHRONICLES_ROOT,
        f"{CHRONICLES_ROOT}/index",
        f"{CHRONICLES_ROOT}/_system",
        f"{CHRONICLES_ROOT}/temp",
        f"{CHRONICLES_ROOT}/temp/tech",
    ]
    y, m = datetime.now(KST).strftime("%Y"), datetime.now(KST).strftime("%m")
    parts.append(f"{CHRONICLES_ROOT}/reports")
    parts.append(f"{CHRONICLES_ROOT}/reports/{y}")
    parts.append(f"{CHRONICLES_ROOT}/reports/{y}/{m}")
    for p in parts:
        segs = p.split("/")
        _ensure_path_folders(svc, root_id, segs)
    if not file_exists_relative(MASTER_INDEX_REL):
        write_json_relative(MASTER_INDEX_REL, {"version": 1, "entries": []})


def _folder_id_for_relative(rel_path):
    _check_pause_guard()
    svc = _get_service()
    root_id = _resolve_root_folder_id(svc)
    _ensure_chronicle_structure(svc, root_id)
    parts = rel_path.split("/")
    filename = parts[-1]
    parent_parts = parts[:-1]
    parent_id = _ensure_path_folders(svc, root_id, parent_parts) if parent_parts else root_id
    return parent_id, filename


def _find_file_in_parent(svc, parent_id, filename):
    q = f"'{parent_id}' in parents and name='{filename}' and trashed=false"
    res = svc.files().list(q=q, fields="files(id,name,mimeType)", pageSize=5).execute()
    files = res.get("files", [])
    return files[0] if files else None


def file_exists_relative(rel_path):
    try:
        svc = _get_service()
        root_id = _resolve_root_folder_id(svc)
        parts = rel_path.split("/")
        parent_id = _ensure_path_folders(svc, root_id, parts[:-1])
        return _find_file_in_parent(svc, parent_id, parts[-1]) is not None
    except Exception:
        return False


def read_text_relative(rel_path):
    _check_pause_guard()
    svc = _get_service()
    parent_id, filename = _folder_id_for_relative(rel_path)
    f = _find_file_in_parent(svc, parent_id, filename)
    if not f:
        return None
    content = svc.files().get_media(fileId=f["id"]).execute()
    return content.decode("utf-8")


def write_text_relative(rel_path, text, mime_type="text/plain"):
    _check_pause_guard()
    svc = _get_service()
    parent_id, filename = _folder_id_for_relative(rel_path)
    data = io.BytesIO(text.encode("utf-8"))
    media = None
    try:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(data, mimetype=mime_type, resumable=False)
    except ImportError:
        raise DriveNotConfiguredError("google-api-python-client 설치 필요")

    existing = _find_file_in_parent(svc, parent_id, filename)
    if existing:
        svc.files().update(fileId=existing["id"], media_body=media).execute()
        return existing["id"]
    meta = {"name": filename, "parents": [parent_id]}
    created = svc.files().create(body=meta, media_body=media, fields="id").execute()
    return created["id"]


def read_json_relative(rel_path):
    raw = read_text_relative(rel_path)
    if raw is None:
        return None
    return json.loads(raw)


def write_json_relative(rel_path, data):
    write_text_relative(rel_path, json.dumps(data, ensure_ascii=False, indent=2), mime_type="application/json")


def read_app_json(filename):
    """paper_portfolio.json 등 앱 데이터."""
    rel = f"{APP_DATA_PREFIX}/{filename}"
    return read_json_relative(rel)


def write_app_json(filename, data):
    rel = f"{APP_DATA_PREFIX}/{filename}"
    _check_pause_guard()
    svc = _get_service()
    root_id = _resolve_root_folder_id(svc)
    _ensure_path_folders(svc, root_id, [APP_DATA_PREFIX])
    write_json_relative(rel, data)


def list_files_under(relative_folder_prefix):
    _check_pause_guard()
    svc = _get_service()
    root_id = _resolve_root_folder_id(svc)
    parts = relative_folder_prefix.rstrip("/").split("/")
    folder_id = _ensure_path_folders(svc, root_id, parts)
    q = f"'{folder_id}' in parents and trashed=false"
    items = []
    page_token = None
    while True:
        res = svc.files().list(
            q=q,
            fields="nextPageToken, files(id,name,createdTime,modifiedTime,mimeType)",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        items.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return items


def delete_file_by_id(file_id):
    _check_pause_guard()
    svc = _get_service()
    svc.files().delete(fileId=file_id).execute()


def init_drive_or_pause(notify_fn=None):
    """시작 시 Drive 초기화. 실패 시 Pause 및 알림."""
    if not is_drive_enabled():
        return False, "Drive 비활성(GOOGLE_DRIVE_ENABLED=0)"
    if not is_drive_configured():
        return False, "Drive 미설정"
    try:
        svc = _get_service()
        root_id = _resolve_root_folder_id(svc)
        _ensure_chronicle_structure(svc, root_id)
        if is_paused():
            clear_pause()
        return True, f"Drive 준비 완료 (root={root_id})"
    except Exception as e:
        msg = (
            f"[Market Chronicles] Google Drive 연결 실패.\n"
            f"사유: {e}\n"
            f"조치: 서비스 계정 JSON 경로·GOOGLE_DRIVE_ROOT_FOLDER_ID·폴더 공유 권한을 확인한 뒤 슬랙에 '완료'를 입력하세요."
        )
        try:
            pause(str(e), "Drive 인증·폴더·용량 확인 후 슬랙에 '완료' 입력")
        except Exception:
            _write_local_pause_flag(str(e))
        if notify_fn:
            notify_fn(msg)
        return False, str(e)


def _write_local_pause_flag(reason):
    path = os.path.join(_project_root(), ".drive_pause_local.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"paused": True, "reason": reason, "since": _now_iso()}, f, ensure_ascii=False)


def _clear_local_pause_flag():
    path = os.path.join(_project_root(), ".drive_pause_local.json")
    if os.path.isfile(path):
        os.remove(path)
