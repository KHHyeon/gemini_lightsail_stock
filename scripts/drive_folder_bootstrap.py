# -*- coding: utf-8 -*-
"""
[임시] Google Drive 연결 테스트 및 Market Chronicles 폴더 구조 자동 생성.

사용법 (프로젝트 루트에서):
    python scripts/drive_folder_bootstrap.py
    python scripts/drive_folder_bootstrap.py --env-file .env

필요 .env (기존 프로젝트 변수명 지원):
    GOOGLE_APPLICATION_CREDENTIALS=서비스계정.json 경로
    GDRIVE_FOLDER_ID=공유된 루트 폴더 ID
    (선택) GOOGLE_API_KEY=Gemini용 (Drive 연결과 무관, 설정 여부만 표시)

완료 후 삭제해도 됩니다.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load_env(env_file):
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("[WARN] python-dotenv 미설치. 시스템 환경 변수만 사용합니다.")
        return
    path = env_file or os.path.join(ROOT, ".env")
    if os.path.isfile(path):
        load_dotenv(path, override=True)
        print(f"  .env 로드: {path}")
    else:
        print(f"  [WARN] .env 파일 없음: {path}")
        print("  시스템 환경 변수 또는 --credentials / --folder-id 인자를 사용하세요.")


def _mask(s, show=4):
    if not s:
        return "(미설정)"
    if len(s) <= show * 2:
        return "*" * len(s)
    return s[:show] + "..." + s[-show:]


def _check_env():
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip() or os.getenv(
        "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", ""
    ).strip()
    folder_id = os.getenv("GDRIVE_FOLDER_ID", "").strip() or os.getenv(
        "GOOGLE_DRIVE_ROOT_FOLDER_ID", ""
    ).strip()
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()

    print("=== 환경 변수 점검 (값은 마스킹) ===")
    print(f"  GOOGLE_APPLICATION_CREDENTIALS: {_mask(creds_path)}")
    if creds_path:
        print(f"    파일 존재: {os.path.isfile(creds_path)}")
    print(f"  GDRIVE_FOLDER_ID: {_mask(folder_id)}")
    print(f"  GOOGLE_API_KEY: {'설정됨' if api_key else '미설정'} (Gemini용)")
    transfer = os.getenv("GDRIVE_TRANSFER_OWNERSHIP_EMAIL", "").strip()
    shared = os.getenv("GDRIVE_USE_SHARED_DRIVE", "").strip()
    print(f"  GDRIVE_TRANSFER_OWNERSHIP_EMAIL: {_mask(transfer) if transfer else '(미설정)'}")
    print(f"  GDRIVE_USE_SHARED_DRIVE: {shared or '0'}")
    print()

    if not creds_path:
        print("[FAIL] 서비스 계정 JSON 경로가 없습니다.")
        return False
    if not os.path.isfile(creds_path):
        print(f"[FAIL] 인증 파일을 찾을 수 없습니다: {creds_path}")
        return False
    if not folder_id:
        print("[FAIL] GDRIVE_FOLDER_ID 가 없습니다.")
        return False
    return True


def _test_connection():
    from src.memory import drive_client

    print("=== Drive API 연결 테스트 ===")
    try:
        svc = drive_client._get_service()
        root_id = drive_client.get_root_folder_id_env()
        meta = svc.files().get(
            fileId=root_id,
            fields="id,name,mimeType",
            **drive_client._shared_drive_kwargs(),
        ).execute()
        print(f"  [OK] 루트 폴더 접근: name={meta.get('name')}, id={meta.get('id')}")

        mode = drive_client.get_auth_mode()
        print(f"  인증 모드: {mode}")
        if mode == "sa_plain":
            owner = drive_client.get_folder_owner_email(svc, root_id)
            print()
            print("  [WARN] 서비스 계정 단독 모드는 파일 생성이 불가합니다.")
            print("  개인 Gmail (권장):")
            print("    python scripts/drive_oauth_setup.py")
            print("  Google Workspace:")
            print(f"    GDRIVE_DELEGATED_USER_EMAIL={owner or 'user@company.com'}")
            print("    + Admin Domain-Wide Delegation 설정")
        return svc, root_id
    except Exception as e:
        print(f"  [FAIL] {e}")
        print(
            "  힌트: 서비스 계정 이메일을 GDRIVE_FOLDER_ID 폴더에 '편집자'로 공유했는지 확인하세요."
        )
        return None, None


def _log(msg):
    print(msg, flush=True)


def _bootstrap_folders(svc, root_id):
    from src.memory import drive_client

    mode = drive_client.get_auth_mode()
    if mode == "sa_plain":
        drive_client._raise_storage_quota_help()

    _log("")
    _log("=== Market Chronicles 폴더 구조 생성 ===")
    _log(f"  인증 모드: {mode}")
    _log("  [1/3] MarketChronicles 트리 생성 중...")
    manifest = drive_client._ensure_chronicle_structure(svc, root_id, force_refresh=True)
    _log("  [2/3] app_data 폴더 생성 중...")
    if not manifest:
        manifest = drive_client._load_manifest_cached(svc, root_id)
    drive_client._ensure_path_folders(
        svc, root_id, [drive_client.APP_DATA_PREFIX], manifest=manifest, save_manifest=True
    )
    _log("  [3/3] manifest 확인 중...")
    paths = manifest.get("paths", {})

    _log(f"  루트 ID: {root_id}")
    _log("  생성/확인된 경로:")
    for key in sorted(paths.keys()):
        _log(f"    - {key}")

    index_folder = f"{drive_client.CHRONICLES_ROOT}/index"
    if index_folder in paths:
        _log(f"  [OK] {drive_client.MASTER_INDEX_REL}")
    else:
        _log(f"  [WARN] {index_folder} 미확인 - Drive 에서 폴더 구조 확인")

    _log("")
    _log("[완료] Drive 연결 및 폴더 구조 준비가 끝났습니다.")


def main():
    parser = argparse.ArgumentParser(description="Drive 연결 테스트 및 폴더 구조 생성")
    parser.add_argument("--env-file", default=None, help=".env 경로 (기본: 프로젝트 루트/.env)")
    parser.add_argument("--credentials", default=None, help="서비스 계정 JSON 경로")
    parser.add_argument("--folder-id", default=None, help="GDRIVE 루트 폴더 ID")
    args = parser.parse_args()

    print("Market Chronicles Drive Bootstrap (임시 스크립트)\n")
    _load_env(args.env_file)
    if args.credentials:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.credentials
    if args.folder_id:
        os.environ["GDRIVE_FOLDER_ID"] = args.folder_id

    if not _check_env():
        sys.exit(1)

    from src.memory.oauth_token import check_oauth_token_status, ensure_oauth_token_valid

    ost = check_oauth_token_status()
    if ost["exists"]:
        print("=== OAuth 토큰 ===")
        print(f"  {ost['message']}")
        if ost["needs_reauth"] and not ost["valid"]:
            print("  [FAIL] 재인증: python scripts/drive_oauth_setup.py --no-browser")
            sys.exit(1)
        ensure_oauth_token_valid(verbose=True)
        print()

    result = _test_connection()
    if not result[0]:
        sys.exit(1)
    _bootstrap_folders(result[0], result[1])


if __name__ == "__main__":
    main()
