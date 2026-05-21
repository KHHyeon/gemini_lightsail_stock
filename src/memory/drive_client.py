# -*- coding: utf-8 -*-
"""
Google Drive API 클라이언트.
- Market Chronicles 데이터는 Drive에만 저장한다.
- OAuth 토큰 파일은 인증 전용이며 시장 데이터가 아니다.
"""
import io
import json
import os

from src.utils.paths import project_root
from src.utils.timekit import KST  # noqa: F401  (외부 모듈이 drive_client.KST 로 참조)

SCOPES = ["https://www.googleapis.com/auth/drive"]
CHRONICLES_ROOT = "MarketChronicles"
APP_DATA_PREFIX = "app_data"
PAUSE_REL_PATH = f"{CHRONICLES_ROOT}/_system/pause_state.json"
MANIFEST_REL_PATH = f"{CHRONICLES_ROOT}/_system/folder_manifest.json"
MASTER_INDEX_REL = f"{CHRONICLES_ROOT}/index/master_index.json"

_DRIVE_SERVICE = None
_FOLDER_CACHE = None
_AUTH_MODE = None  # oauth | delegation | shared_drive | sa_plain


class DrivePausedError(Exception):
    """사용자 개입 대기 중."""

    def __init__(self, reason, action_required):
        self.reason = reason
        self.action_required = action_required
        super().__init__(reason)


class DriveNotConfiguredError(Exception):
    pass


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


def uses_shared_drive():
    """Google Workspace 공유 드라이브(팀 드라이브) 사용 여부."""
    flag = os.getenv("GDRIVE_USE_SHARED_DRIVE", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    return bool(os.getenv("GDRIVE_SHARED_DRIVE_ID", "").strip())


def get_transfer_owner_email():
    """레거시: 소유권 이전 대상 (생성 전 위임이 우선)."""
    return os.getenv("GDRIVE_TRANSFER_OWNERSHIP_EMAIL", "").strip()


def get_delegated_user_email():
    """
    서비스 계정이 이 사용자로 동작 (Domain-Wide Delegation, Workspace).
    개인 @gmail.com 은 불가 -> OAuth 사용.
    """
    return (
        os.getenv("GDRIVE_DELEGATED_USER_EMAIL", "").strip()
        or get_transfer_owner_email()
    )


def get_auth_mode():
    return _AUTH_MODE


def _oauth_token_path():
    from src.memory.oauth_token import get_token_path

    return get_token_path()


def _load_oauth_credentials():
    """OAuth 사용자 토큰 (만료 시 refresh 후 파일 저장)."""
    from src.memory.oauth_token import ensure_oauth_token_valid

    return ensure_oauth_token_valid(verbose=False)


def _build_drive_service(creds):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    timeout = int(os.getenv("GOOGLE_DRIVE_HTTP_TIMEOUT", "60"))
    http = httplib2.Http(timeout=timeout)
    authorized = AuthorizedHttp(creds, http=http)
    return build("drive", "v3", http=authorized, cache_discovery=False)


def _shared_drive_kwargs():
    if not uses_shared_drive():
        return {}
    kw = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
    drive_id = os.getenv("GDRIVE_SHARED_DRIVE_ID", "").strip()
    if drive_id:
        kw["driveId"] = drive_id
        kw["corpora"] = "drive"
    return kw


def _transfer_ownership_if_needed(svc, file_id):
    """sa_plain 모드에서만 사용 (생성 후 이전은 대부분 실패하므로 비권장)."""
    if _AUTH_MODE in ("oauth", "delegation", "shared_drive"):
        return
    email = get_transfer_owner_email()
    if not email:
        _raise_storage_quota_help()
    svc.permissions().create(
        fileId=file_id,
        body={"type": "user", "role": "owner", "emailAddress": email},
        transferOwnership=True,
        **_shared_drive_kwargs(),
    ).execute()


def _raise_storage_quota_help():
    raise DriveNotConfiguredError(
        "서비스 계정은 Drive 저장 용량이 없어 파일을 만들 수 없습니다.\n"
        "해결 1 (개인 Gmail): python scripts/drive_oauth_setup.py 실행 후 OAuth 토큰 생성\n"
        "해결 2 (Workspace): GDRIVE_DELEGATED_USER_EMAIL=사용자@회사도메인 + 관리자 콘솔 Domain-Wide Delegation\n"
        "해결 3: Quant_Logs 를 공유 드라이브로 옮기고 GDRIVE_USE_SHARED_DRIVE=1"
    )


def _assert_can_create_files():
    if _AUTH_MODE == "sa_plain" and not uses_shared_drive():
        _raise_storage_quota_help()


def get_folder_owner_email(svc, folder_id):
    """루트 폴더 소유자 이메일 (설정 힌트용)."""
    try:
        meta = svc.files().get(
            fileId=folder_id,
            fields="owners(emailAddress)",
            **_shared_drive_kwargs(),
        ).execute()
        owners = meta.get("owners") or []
        if owners:
            return owners[0].get("emailAddress", "")
    except Exception:
        pass
    return ""


def _get_service():
    global _DRIVE_SERVICE, _AUTH_MODE
    if _DRIVE_SERVICE is not None:
        return _DRIVE_SERVICE
    if not is_drive_configured():
        raise DriveNotConfiguredError(
            "GOOGLE_APPLICATION_CREDENTIALS 또는 GOOGLE_DRIVE_OAUTH_CLIENT_FILE 미설정"
        )

    if uses_shared_drive():
        _AUTH_MODE = "shared_drive"

    oauth_creds = _load_oauth_credentials()
    if oauth_creds:
        _AUTH_MODE = "oauth"
        _DRIVE_SERVICE = _build_drive_service(oauth_creds)
        return _DRIVE_SERVICE

    sa_path = get_service_account_path()
    delegate = get_delegated_user_email()

    if sa_path and os.path.isfile(sa_path):
        from google.oauth2 import service_account

        if delegate:
            _AUTH_MODE = "delegation"
            creds = service_account.Credentials.from_service_account_file(
                sa_path, scopes=SCOPES, subject=delegate
            )
            _DRIVE_SERVICE = _build_drive_service(creds)
            return _DRIVE_SERVICE

        _AUTH_MODE = "sa_plain"
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        _DRIVE_SERVICE = _build_drive_service(creds)
        return _DRIVE_SERVICE

    oauth_path = os.getenv("GOOGLE_DRIVE_OAUTH_CLIENT_FILE", "").strip()
    if not oauth_path or not os.path.isfile(oauth_path):
        raise DriveNotConfiguredError(
            "Drive 인증 없음. SA JSON 또는 OAuth client_secret.json 이 필요합니다."
        )

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(oauth_path, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(_oauth_token_path(), "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    _AUTH_MODE = "oauth"
    _DRIVE_SERVICE = _build_drive_service(creds)
    return _DRIVE_SERVICE


def _now_iso():
    from src.utils.timekit import kst_strftime

    return kst_strftime("%Y-%m-%d %H:%M:%S")


def _local_pause_path():
    return os.path.join(project_root(), ".drive_pause_local.json")


def _read_local_pause_state():
    path = _local_pause_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def is_paused():
    """Pause 검사 (Drive API 호출 없음 - read 재귀 방지)."""
    local = _read_local_pause_state()
    return bool(local and local.get("paused"))


def get_pause_state():
    if not is_drive_enabled() or not is_drive_configured():
        return _read_local_pause_state()
    if is_paused():
        return _read_local_pause_state()
    try:
        return _read_json_direct(PAUSE_REL_PATH)
    except Exception:
        return _read_local_pause_state()


def pause(reason, action_required):
    state = {
        "paused": True,
        "reason": reason,
        "action_required": action_required,
        "since": _now_iso(),
    }
    _write_local_pause_flag(reason, action_required)
    try:
        write_json_relative(PAUSE_REL_PATH, state)
    except Exception:
        pass
    return state


def clear_pause():
    _clear_local_pause_flag()
    try:
        write_json_relative(
            PAUSE_REL_PATH,
            {"paused": False, "cleared_at": _now_iso()},
        )
    except Exception:
        pass


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
    if _FOLDER_CACHE and _FOLDER_CACHE.get("root_folder_id"):
        return _FOLDER_CACHE["root_folder_id"]
    folder_name = os.getenv("GOOGLE_DRIVE_ROOT_FOLDER_NAME", "AutoStockBot_Data")
    q = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        "and trashed=false"
    )
    res = svc.files().list(
        q=q, fields="files(id,name)", pageSize=5, **_shared_drive_kwargs()
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    created = svc.files().create(body=meta, fields="id", **_shared_drive_kwargs()).execute()
    return created["id"]


def _load_manifest_cached(svc, root_id):
    """manifest 읽기 (재귀 없음)."""
    global _FOLDER_CACHE
    if _FOLDER_CACHE is not None and _FOLDER_CACHE.get("root_folder_id") == root_id:
        return _FOLDER_CACHE

    manifest = {"root_folder_id": root_id, "paths": {}}
    try:
        sys_parts = [CHRONICLES_ROOT, "_system"]
        parent_id = root_id
        for part in sys_parts:
            fid = _find_child_folder(svc, parent_id, part)
            if not fid:
                break
            parent_id = fid
        else:
            f = _find_file_in_parent(svc, parent_id, "folder_manifest.json")
            if f:
                raw = svc.files().get_media(fileId=f["id"]).execute()
                manifest = json.loads(raw.decode("utf-8"))
                manifest.setdefault("root_folder_id", root_id)
    except Exception:
        pass

    _FOLDER_CACHE = manifest
    return manifest


def _persist_manifest(svc, root_id, manifest):
    """manifest 저장 (재귀 없음)."""
    global _FOLDER_CACHE
    _FOLDER_CACHE = manifest
    parent_id = _ensure_path_folders(svc, root_id, [CHRONICLES_ROOT, "_system"], manifest=manifest, save_manifest=False)
    body = json.dumps(manifest, ensure_ascii=False, indent=2)
    _write_bytes_to_parent(svc, parent_id, "folder_manifest.json", body.encode("utf-8"), "application/json")


def _write_bytes_to_parent(svc, parent_id, filename, data_bytes, mime_type):
    _assert_can_create_files()
    from googleapiclient.http import MediaIoBaseUpload

    stream = io.BytesIO(data_bytes)
    media = MediaIoBaseUpload(stream, mimetype=mime_type, resumable=False)
    existing = _find_file_in_parent(svc, parent_id, filename)
    api_kw = _shared_drive_kwargs()
    if existing:
        svc.files().update(fileId=existing["id"], media_body=media, **api_kw).execute()
        return existing["id"]
    meta = {"name": filename, "parents": [parent_id]}
    file_id = svc.files().create(
        body=meta, media_body=media, fields="id", **api_kw
    ).execute()["id"]
    _transfer_ownership_if_needed(svc, file_id)
    return file_id


def _escape_query_value(value):
    return str(value).replace("'", "\\'")


def _find_child_folder(svc, parent_id, name):
    q = (
        f"'{parent_id}' in parents and name='{_escape_query_value(name)}' "
        "and mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = svc.files().list(
        q=q, fields="files(id)", pageSize=1, **_shared_drive_kwargs()
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(svc, parent_id, name):
    _assert_can_create_files()
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    file_id = svc.files().create(body=meta, fields="id", **_shared_drive_kwargs()).execute()["id"]
    _transfer_ownership_if_needed(svc, file_id)
    return file_id


def _ensure_path_folders(svc, root_id, parts, manifest=None, save_manifest=True):
    if manifest is None:
        manifest = _load_manifest_cached(svc, root_id)
    if manifest.get("root_folder_id") != root_id:
        manifest = {"root_folder_id": root_id, "paths": manifest.get("paths", {})}

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

    if save_manifest:
        _persist_manifest(svc, root_id, manifest)
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
    from src.utils.timekit import now_kst

    today_kst_dt = now_kst()
    y, m = today_kst_dt.strftime("%Y"), today_kst_dt.strftime("%m")
    parts.append(f"{CHRONICLES_ROOT}/reports")
    parts.append(f"{CHRONICLES_ROOT}/reports/{y}")
    parts.append(f"{CHRONICLES_ROOT}/reports/{y}/{m}")
    manifest = _load_manifest_cached(svc, root_id)
    for p in parts:
        _ensure_path_folders(svc, root_id, p.split("/"), manifest=manifest, save_manifest=False)
    index_parts = MASTER_INDEX_REL.split("/")
    parent_id = _ensure_path_folders(
        svc, root_id, index_parts[:-1], manifest=manifest, save_manifest=False
    )
    if not _find_file_in_parent(svc, parent_id, index_parts[-1]):
        _write_bytes_to_parent(
            svc,
            parent_id,
            index_parts[-1],
            json.dumps({"version": 1, "entries": []}, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
        )
    _persist_manifest(svc, root_id, manifest)
    return manifest


def _folder_id_for_relative(rel_path, svc=None, root_id=None):
    _check_pause_guard()
    if svc is None:
        svc = _get_service()
    if root_id is None:
        root_id = _resolve_root_folder_id(svc)
    parts = rel_path.split("/")
    filename = parts[-1]
    parent_parts = parts[:-1]
    manifest = _load_manifest_cached(svc, root_id)
    parent_id = (
        _ensure_path_folders(svc, root_id, parent_parts, manifest=manifest, save_manifest=False)
        if parent_parts
        else root_id
    )
    return svc, root_id, parent_id, filename


def _find_file_in_parent(svc, parent_id, filename):
    q = (
        f"'{parent_id}' in parents and name='{_escape_query_value(filename)}' "
        "and trashed=false"
    )
    res = svc.files().list(
        q=q, fields="files(id,name,mimeType)", pageSize=5, **_shared_drive_kwargs()
    ).execute()
    files = res.get("files", [])
    return files[0] if files else None


def file_exists_relative(rel_path):
    try:
        svc, root_id, parent_id, filename = _folder_id_for_relative(rel_path)
        return _find_file_in_parent(svc, parent_id, filename) is not None
    except Exception:
        return False


def _read_text_direct(rel_path, svc=None, root_id=None):
    """Pause guard 없이 Drive 파일 읽기."""
    if svc is None:
        svc = _get_service()
    if root_id is None:
        root_id = _resolve_root_folder_id(svc)
    svc, root_id, parent_id, filename = _folder_id_for_relative(rel_path, svc=svc, root_id=root_id)
    f = _find_file_in_parent(svc, parent_id, filename)
    if not f:
        return None
    content = svc.files().get_media(fileId=f["id"]).execute()
    return content.decode("utf-8")


def _read_json_direct(rel_path, svc=None, root_id=None):
    raw = _read_text_direct(rel_path, svc=svc, root_id=root_id)
    if raw is None:
        return None
    return json.loads(raw)


def read_text_relative(rel_path):
    _check_pause_guard()
    return _read_text_direct(rel_path)


def write_text_relative(rel_path, text, mime_type="text/plain"):
    _check_pause_guard()
    svc, root_id, parent_id, filename = _folder_id_for_relative(rel_path)
    _write_bytes_to_parent(svc, parent_id, filename, text.encode("utf-8"), mime_type)


def read_json_relative(rel_path):
    _check_pause_guard()
    return _read_json_direct(rel_path)


def write_json_relative(rel_path, data):
    write_text_relative(rel_path, json.dumps(data, ensure_ascii=False, indent=2), mime_type="application/json")


def read_app_json(filename):
    """paper_portfolio.json 등 앱 데이터."""
    rel = f"{APP_DATA_PREFIX}/{filename}"
    return read_json_relative(rel)


def write_app_json(filename, data):
    rel = f"{APP_DATA_PREFIX}/{filename}"
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
            **_shared_drive_kwargs(),
        ).execute()
        items.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break
    return items


def delete_file_by_id(file_id):
    _check_pause_guard()
    svc = _get_service()
    svc.files().delete(fileId=file_id, **_shared_drive_kwargs()).execute()


def delete_file_relative(rel_path):
    """상대 경로에 위치한 파일을 Drive 에서 안전하게 삭제.

    Returns:
        True  - 실제 삭제 수행.
        False - 파일이 처음부터 없거나 이미 삭제됨 (idempotent).

    내부적으로 _folder_id_for_relative -> _find_file_in_parent ->
    delete_file_by_id 를 묶어 호출하며, 404 / notFound 응답은 '이미 삭제됨'
    으로 간주한다. backfill 등 호출자가 _ prefix private 함수를 직접
    참조하지 않도록 캡슐화한 진입점이다.
    """
    try:
        svc, _root_id, parent_id, filename = _folder_id_for_relative(rel_path)
        found = _find_file_in_parent(svc, parent_id, filename)
    except Exception as exc:
        print(f"Log: [Drive Delete] {rel_path} 조회 실패: {exc}", flush=True)
        return False

    if not found:
        return False
    file_id = found.get("id") if isinstance(found, dict) else str(found)
    if not file_id:
        return False

    try:
        delete_file_by_id(file_id)
        return True
    except Exception as exc:
        msg = str(exc)
        if "404" in msg or "notFound" in msg or "File not found" in msg:
            return False
        print(f"Log: [Drive Delete] {rel_path} 삭제 실패: {exc}", flush=True)
        return False


def read_master_index():
    """master_index.json 을 안전하게 읽어 dict 로 반환.

    파일이 없거나 비어 있으면 기본 스키마 `{"version": 1, "entries": []}` 반환.
    """
    data = read_json_relative(MASTER_INDEX_REL)
    if not data:
        return {"version": 1, "entries": []}
    data.setdefault("version", 1)
    data.setdefault("entries", [])
    return data


def append_index_entry(entry_dict):
    """master_index.json 의 entries 리스트에 항목을 append 한 뒤 저장.

    Returns:
        dict: 갱신된 인덱스 전체.
    """
    index_dict = read_master_index()
    index_dict["entries"].append(entry_dict)
    write_master_index(index_dict)
    return index_dict


def write_master_index(index_dict):
    """master_index.json 전체를 덮어쓴다.

    backfill.reset / backfill.reindex 와 같이 entries 를 일괄 필터링·수정한
    뒤 통째로 저장하는 경우 본 헬퍼를 사용한다.
    """
    write_json_relative(MASTER_INDEX_REL, index_dict)


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


def _write_local_pause_flag(reason, action_required=""):
    path = _local_pause_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "paused": True,
                "reason": reason,
                "action_required": action_required,
                "since": _now_iso(),
            },
            f,
            ensure_ascii=False,
        )


def _clear_local_pause_flag():
    path = _local_pause_path()
    if os.path.isfile(path):
        os.remove(path)
