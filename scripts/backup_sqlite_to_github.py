"""SQLite -> GitHub backup orphan branch 백업 스크립트.

봇 내부 ``schedule`` 잡(``src.storage.backup_scheduler``)이 daemon thread
에서 본 모듈의 ``run_backup_cycle`` 을 호출하거나, 운영자가 CLI 로 직접
실행한다. 단일 백업 사이클은 10단계로 구성되며, ``VACUUM INTO`` 로
일관된 스냅샷을 추출하고 gzip 압축 후 별도 작업 디렉터리에 single-branch
clone 된 ``backup`` orphan 브랜치에 commit + push 한다.

흐름 상세: Doc/features/data_persistence/03_data_persistence_state_logic.md §13.4

종료 코드:
    0 - 정상 (회전 실패는 WARN 으로 분류, exit 0 유지).
    1 - VACUUM INTO 실패 (P4E1).
    2 - gzip 실패 (P4E2).
    3 - git push 실패 (P4E3).
"""
from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Literal, Optional


# scripts/_common.py 경로 활성화 (sys.path 등록).
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from _common import setup_script_path, load_env_file, print_flush  # noqa: E402

setup_script_path()
load_env_file(verbose=False)


# KST 타임존 (Asia/Seoul). zoneinfo 미가용 환경 대비 timezone(UTC+9) 폴백.
try:
    from zoneinfo import ZoneInfo

    _KST = ZoneInfo("Asia/Seoul")
except Exception:
    _KST = timezone(timedelta(hours=9))


_VALID_KIND_LIST = ("daily", "weekly", "monthly")


def _kst_now() -> datetime:
    """KST 현재 시각."""
    return datetime.now(_KST)


def _format_kst_stamp(dt: datetime) -> str:
    """KST 기준 ``YYYYMMDD-HHMM`` 형식 타임스탬프 생성."""
    return dt.astimezone(_KST).strftime("%Y%m%d-%H%M")


def _parse_stamp_to_kst(stamp: str) -> Optional[datetime]:
    """``autostock-YYYYMMDD-HHMM.db.gz`` 또는 ``YYYYMMDD-HHMM`` 에서
    KST datetime 복원. 형식 불일치 시 None.
    """
    raw = stamp
    if raw.startswith("autostock-"):
        raw = raw[len("autostock-"):]
    if raw.endswith(".db.gz"):
        raw = raw[: -len(".db.gz")]
    try:
        dt = datetime.strptime(raw, "%Y%m%d-%H%M")
    except ValueError:
        return None
    return dt.replace(tzinfo=_KST)


def _resolve_slack_notifier(no_slack: bool) -> Optional[Callable[[str], None]]:
    """슬랙 알림 callable 반환. ``--no-slack`` 또는 토큰 없으면 None.

    ``scripts/migrate_drive_to_sqlite.py`` 와 동일 패턴 (DRY 원칙).
    """
    if no_slack:
        return None
    try:
        from slack_sdk import WebClient
    except ImportError:
        return None

    token = os.getenv("SLACK_TOKEN") or os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL")
    if not token or not channel:
        return None
    client = WebClient(token=token)

    def _notify(text: str) -> None:
        client.chat_postMessage(channel=channel, text=text)

    return _notify


def _send_slack(text: str, notify_fn: Optional[Callable[[str], None]]) -> None:
    """슬랙 전송. notify_fn 가 None 이면 무동작. 슬랙 실패는 백업 결과 무효화 안 함."""
    if not callable(notify_fn):
        return
    try:
        notify_fn(text)
    except Exception:
        pass


def _build_remote_url_with_token(repo_url: str, token: str) -> str:
    """HTTPS URL 에 PAT 끼워넣기. SSH URL 은 그대로 반환.

    토큰 노출 방지를 위해 stdout/슬랙에는 본 함수 결과를 직접 쓰지 않는다.
    """
    if not repo_url:
        return repo_url
    if repo_url.startswith("git@"):
        return repo_url
    if not token:
        return repo_url
    if repo_url.startswith("https://"):
        rest = repo_url[len("https://"):]
        return f"https://x-access-token:{token}@{rest}"
    if repo_url.startswith("http://"):
        rest = repo_url[len("http://"):]
        return f"http://x-access-token:{token}@{rest}"
    return repo_url


def _redact_token(text: str, token: Optional[str]) -> str:
    """문자열에 PAT 가 노출되어 있으면 ``***`` 로 마스킹."""
    if not token:
        return text
    return text.replace(token, "***")


def _run_git(
    args: List[str],
    *,
    cwd: str,
    env: Optional[Dict[str, str]] = None,
    check: bool = True,
    capture_output: bool = True,
    timeout: Optional[float] = 300.0,
) -> subprocess.CompletedProcess:
    """``git`` subprocess 실행 단축형.

    안전 가드 (Phase 4 Step 2 핵심): ``GIT_CEILING_DIRECTORIES`` 환경변수로
    git 이 ``cwd`` 의 **상위 디렉터리**에서 .git 을 찾지 못하도록 차단한다.
    ``cwd`` 자체에 .git 이 없는데 git add/commit 등을 호출하면 git 이 상위
    디렉터리(예: ``/home/ubuntu/my_bot/.git``)로 올라가 봇 본체 repo 를 오염
    시키는 사고를 막는다 (Phase 4 Step 2 smoke 1차 실행에서 실측 발견).

    clone / init 은 ``cwd`` 에 새 .git 을 생성하므로 ceiling 영향 무관.

    Args:
        args: ``["clone", url, dest]`` 등 git 인자 리스트 (앞에 ``git`` 미포함).
        cwd: 작업 디렉터리.
        env: 추가 환경변수 (None 이면 부모 env 복사 + ceiling 자동 추가).
        check: True 면 returncode != 0 시 ``CalledProcessError`` 발생.
        capture_output: stdout/stderr 캡처 여부.
        timeout: 초 단위 타임아웃.

    Returns:
        ``subprocess.CompletedProcess``.
    """
    cmd_list = ["git"] + list(args)
    parent_of_cwd = os.path.dirname(os.path.abspath(cwd))
    if env is None:
        full_env: Dict[str, str] = dict(os.environ)
    else:
        full_env = dict(env)
    full_env.setdefault("GIT_CEILING_DIRECTORIES", parent_of_cwd)
    return subprocess.run(
        cmd_list,
        cwd=cwd,
        env=full_env,
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
    )


def _ensure_git_user_config(repo_dir: str) -> None:
    """백업 작업 디렉터리에 git user.name / user.email 설정 (local scope).

    글로벌 git config 는 변경하지 않는다 (워크스페이스 룰 준수).
    """
    user_name = os.getenv("BACKUP_GIT_USER_NAME", "autostock-backup-bot")
    user_email = os.getenv(
        "BACKUP_GIT_USER_EMAIL",
        "autostock-backup-bot@users.noreply.github.com",
    )
    _run_git(["config", "user.name", user_name], cwd=repo_dir, check=False)
    _run_git(["config", "user.email", user_email], cwd=repo_dir, check=False)


def _is_clone_branch_missing(stderr_text: str) -> bool:
    """``git clone --branch`` 실패 stderr 에 '원격 브랜치 미존재' 신호가 있는지 점검."""
    text = (stderr_text or "").lower()
    needle_list = (
        "remote branch",
        "couldn't find remote",
        "not found in upstream",
        "warning: could not find remote branch",
    )
    return any(n in text for n in needle_list)


def _setup_repo_dir(
    repo_dir: str,
    *,
    repo_url: str,
    branch: str,
    token: str,
    notify_fn: Optional[Callable[[str], None]] = None,
) -> None:
    """백업 작업 디렉터리 부트스트랩 (Step 2/10). idempotent.

    동작 정책:
        1. ``repo_dir/.git`` 가 이미 있으면 user.name/email 만 보정 후 즉시 반환.
        2. ``repo_dir`` 이 빈 디렉터리거나 부분 잔존이면 정리 후 재시도.
        3. ``git clone --single-branch --branch <BRANCH>`` 시도.
        4. 원격에 브랜치가 없으면 (P4F2 예외 분기) ``git init`` + ``orphan`` 신설 +
           빈 commit + 첫 push 로 원격 브랜치 생성.
    """
    git_dir = os.path.join(repo_dir, ".git")
    parent_dir = os.path.dirname(os.path.abspath(repo_dir)) or "."
    os.makedirs(parent_dir, exist_ok=True)

    if os.path.isdir(git_dir):
        _ensure_git_user_config(repo_dir)
        return

    if os.path.exists(repo_dir):
        if not os.path.isdir(repo_dir):
            raise RuntimeError(
                f"BACKUP_REPO_DIR ({repo_dir}) 가 디렉터리가 아닙니다."
            )
        try:
            shutil.rmtree(repo_dir)
        except OSError:
            pass

    remote_url = _build_remote_url_with_token(repo_url, token)
    branch_missing = False
    try:
        _run_git(
            [
                "clone", "--single-branch", "--branch", branch, "--depth", "1",
                remote_url, repo_dir,
            ],
            cwd=parent_dir,
        )
    except subprocess.CalledProcessError as exc:
        if _is_clone_branch_missing(exc.stderr or ""):
            branch_missing = True
        else:
            raise

    if not branch_missing and os.path.isdir(os.path.join(repo_dir, ".git")):
        worktree_files = [
            n for n in os.listdir(repo_dir) if n != ".git"
        ]
        if worktree_files:
            _ensure_git_user_config(repo_dir)
            return
        branch_missing = True

    if not branch_missing and not os.path.isdir(os.path.join(repo_dir, ".git")):
        branch_missing = True

    if not branch_missing:
        _ensure_git_user_config(repo_dir)
        return

    if callable(notify_fn):
        _send_slack(
            f"[Backup INFO] backup 브랜치 미존재 — orphan 신설 시도 ({branch}).",
            notify_fn,
        )
    if os.path.isdir(repo_dir):
        try:
            shutil.rmtree(repo_dir)
        except OSError:
            pass
    os.makedirs(repo_dir, exist_ok=True)

    init_proc = subprocess.run(
        ["git", "init", "--initial-branch", branch],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if init_proc.returncode != 0:
        _run_git(["init"], cwd=repo_dir)
        _run_git(["checkout", "-b", branch], cwd=repo_dir, check=False)

    _ensure_git_user_config(repo_dir)
    _run_git(["remote", "remove", "origin"], cwd=repo_dir, check=False)
    _run_git(["remote", "add", "origin", remote_url], cwd=repo_dir)

    readme_path = os.path.join(repo_dir, "README.md")
    if not os.path.exists(readme_path):
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(
                "# autostock backup branch\n\n"
                "본 브랜치는 SQLite 자동 백업 전용 orphan 브랜치이다. "
                "Doc/features/data_persistence/03_data_persistence_state_logic.md §13 참조.\n"
            )
    gitignore_path = os.path.join(repo_dir, ".gitignore")
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, "w", encoding="utf-8") as fh:
            fh.write("staging/\n")
    _run_git(["add", "README.md", ".gitignore"], cwd=repo_dir)
    _run_git(
        ["commit", "-m", "[backup] init orphan branch"], cwd=repo_dir, check=False,
    )
    _run_git(["push", "-u", "origin", branch], cwd=repo_dir)


def _git_fetch_reset(repo_dir: str, *, branch: str) -> None:
    """remote 우선 동기화 (Step 3/10). local 변경 강제 폐기."""
    _run_git(["fetch", "origin", branch], cwd=repo_dir)
    _run_git(["reset", "--hard", f"origin/{branch}"], cwd=repo_dir)


def _vacuum_into(db_path: str, output_path: str, *, retry_after_s: float = 60.0) -> None:
    """``VACUUM INTO`` 로 라이브 DB 의 일관된 스냅샷을 ``output_path`` 에 추출.

    실패 시 1회 재시도 후 그래도 실패하면 예외 전파 (P4E1).
    """
    import sqlite3

    parent_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(parent_dir, exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)

    last_exc: Optional[Exception] = None
    for attempt in range(2):
        try:
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(f"VACUUM INTO '{output_path}'")
                return
            finally:
                conn.close()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if attempt == 0:
                print_flush(
                    f"  [WARN] VACUUM INTO 실패 (1차): {exc}. {int(retry_after_s)}s 후 재시도."
                )
                time.sleep(retry_after_s)
                continue
            raise
    if last_exc is not None:
        raise last_exc


def _gzip_file(src_path: str, dst_path: str, *, compresslevel: int = 6) -> int:
    """``src_path`` 를 gzip 으로 ``dst_path`` 에 압축. 압축본 크기 반환.

    compresslevel 6: 균형(속도/비율). 9 는 느려서 미채택.
    """
    parent_dir = os.path.dirname(os.path.abspath(dst_path))
    os.makedirs(parent_dir, exist_ok=True)
    with open(src_path, "rb") as src, gzip.open(
        dst_path, "wb", compresslevel=compresslevel,
    ) as dst:
        shutil.copyfileobj(src, dst)
    return os.path.getsize(dst_path)


def _list_kind_files(repo_dir: str, kind: str) -> List[str]:
    """``repo_dir/{kind}/`` 의 ``autostock-*.db.gz`` 파일명 목록 (정렬 오름차순)."""
    target_dir = os.path.join(repo_dir, kind)
    if not os.path.isdir(target_dir):
        return []
    file_list: List[str] = []
    for name in os.listdir(target_dir):
        if not name.endswith(".db.gz"):
            continue
        if not name.startswith("autostock-"):
            continue
        file_list.append(name)
    file_list.sort()
    return file_list


def _retention_cutoff(kind: str, now_kst: datetime) -> datetime:
    """보관 정책 cutoff (kind 별 보존 기간 만료 시각). cutoff 이전 파일은 회전 대상."""
    if kind == "daily":
        days = int(os.getenv("BACKUP_RETENTION_DAILY", "30"))
        return now_kst - timedelta(days=days)
    if kind == "weekly":
        weeks = int(os.getenv("BACKUP_RETENTION_WEEKLY", "12"))
        return now_kst - timedelta(weeks=weeks)
    if kind == "monthly":
        months = int(os.getenv("BACKUP_RETENTION_MONTHLY", "12"))
        return now_kst - timedelta(days=months * 31)
    return now_kst


def _rotate_files(
    repo_dir: str,
    *,
    kind: str,
    now_kst: datetime,
) -> List[str]:
    """보관 정책에 따라 cutoff 이전 파일을 ``git rm`` 한다.

    Returns:
        회전된 파일명 목록 (rel_path).
    """
    cutoff_dt = _retention_cutoff(kind, now_kst)
    rotated_list: List[str] = []
    for filename in _list_kind_files(repo_dir, kind):
        stamp_dt = _parse_stamp_to_kst(filename)
        if stamp_dt is None:
            continue
        if stamp_dt < cutoff_dt:
            rel_path = f"{kind}/{filename}"
            try:
                _run_git(["rm", rel_path], cwd=repo_dir)
                rotated_list.append(rel_path)
            except subprocess.CalledProcessError:
                continue
    return rotated_list


def _git_push_with_retry(
    repo_dir: str,
    *,
    branch: str,
    token: str,
) -> str:
    """``git push origin {branch}`` (Step 9/10).

    실패 시 ``git pull --rebase`` 후 재시도 1회 (P4E3).
    그래도 실패하면 예외 전파.
    """
    try:
        _run_git(["push", "origin", branch], cwd=repo_dir)
    except subprocess.CalledProcessError as exc:
        stderr_msg = _redact_token(exc.stderr or "", token)
        print_flush(f"  [WARN] git push 1차 실패: {stderr_msg.strip()[:200]}")
        _run_git(["pull", "--rebase", "origin", branch], cwd=repo_dir)
        _run_git(["push", "origin", branch], cwd=repo_dir)
    head_proc = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_dir)
    return (head_proc.stdout or "").strip()


def _promote_monthly_from_daily(
    repo_dir: str, *, stamp: str,
) -> Optional[str]:
    """일간 백업 1개를 monthly/ 디렉터리로 복사 (월간 승격, Step 4/10 변형).

    Returns:
        승격된 monthly rel_path. 일간 백업 미존재 시 None.
    """
    daily_files = _list_kind_files(repo_dir, "daily")
    if not daily_files:
        return None
    source_file = daily_files[-1]
    monthly_rel = f"monthly/autostock-{stamp}.db.gz"
    monthly_abs = os.path.join(repo_dir, monthly_rel)
    monthly_dir = os.path.dirname(monthly_abs)
    os.makedirs(monthly_dir, exist_ok=True)
    shutil.copy(os.path.join(repo_dir, "daily", source_file), monthly_abs)
    return monthly_rel


def run_backup_cycle(
    *,
    kind: Literal["daily", "weekly", "monthly"],
    db_path: str,
    repo_dir: str,
    notify_fn: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """단일 백업 사이클을 수행한다 (10단계).

    Returns:
        result dict (사양 §02 §9.3 참조).
    """
    if kind not in _VALID_KIND_LIST:
        raise ValueError(f"kind 는 {_VALID_KIND_LIST} 중 하나여야 합니다 (현재: {kind!r}).")

    repo_url = os.getenv("BACKUP_REPO_URL", "")
    token = os.getenv("BACKUP_GITHUB_TOKEN", "")
    branch = os.getenv("BACKUP_BRANCH", "backup")
    started_at = time.monotonic()
    now_kst = _kst_now()
    stamp = _format_kst_stamp(now_kst)

    repo_dir = os.path.abspath(repo_dir)
    src_db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    result: Dict[str, Any] = {
        "kind": kind,
        "stamp": stamp,
        "src_db_path": db_path,
        "src_db_size": src_db_size,
        "vacuum_db_size": 0,
        "gz_size": 0,
        "gz_file_rel": "",
        "commit_sha": "",
        "rotated_files_list": [],
        "elapsed_ms": 0,
        "status": "ok",
    }

    print_flush(f"[Step 1/10] kind={kind} stamp={stamp} db_path={db_path} repo_dir={repo_dir}")

    if not os.path.exists(db_path):
        message = (
            f"[Backup FAIL] {kind} {stamp} | step=preflight | err=DB 파일 미존재: {db_path}\n"
            "운영자 조치: STATE_STORE_DB_PATH 점검 또는 SQLite 마이그레이션 선행 실행."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "preflight_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        return result

    print_flush(f"[Step 2/10] backup repo_dir 부트스트랩")
    try:
        _setup_repo_dir(
            repo_dir,
            repo_url=repo_url,
            branch=branch,
            token=token,
            notify_fn=notify_fn,
        )
    except subprocess.CalledProcessError as exc:
        message = (
            f"[Backup FAIL] {kind} {stamp} | step=setup_repo | "
            f"err={_redact_token((exc.stderr or '').strip()[:200], token)}\n"
            "운영자 조치: BACKUP_REPO_URL / BACKUP_GITHUB_TOKEN 점검 (PAT scope=repo)."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "setup_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(3)

    print_flush(f"[Step 3/10] git fetch + reset --hard origin/{branch}")
    try:
        _git_fetch_reset(repo_dir, branch=branch)
    except subprocess.CalledProcessError as exc:
        message = (
            f"[Backup FAIL] {kind} {stamp} | step=fetch_reset | "
            f"err={_redact_token((exc.stderr or '').strip()[:200], token)}\n"
            "운영자 조치: 네트워크 / PAT 만료 점검."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "fetch_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(3)

    if kind == "monthly":
        print_flush(f"[Step 4/10] monthly 승격 (daily/ 최신 1개 복사)")
        promoted_rel = _promote_monthly_from_daily(repo_dir, stamp=stamp)
        if promoted_rel is None:
            message = (
                f"[Backup INFO] monthly {stamp} skip — daily 백업 미존재. "
                "다음 월간 트리거 시 재시도."
            )
            print_flush(message)
            _send_slack(message, notify_fn)
            result["status"] = "skip_no_daily"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            return result
        gz_rel_path = promoted_rel
        gz_abs_path = os.path.join(repo_dir, gz_rel_path)
        result["vacuum_db_size"] = 0
        result["gz_size"] = os.path.getsize(gz_abs_path)
        result["gz_file_rel"] = gz_rel_path
        print_flush(f"  promoted {promoted_rel} ({result['gz_size']} bytes)")
    else:
        print_flush(f"[Step 4/10] VACUUM INTO staging/")
        staging_path = os.path.join(repo_dir, "staging", f"autostock-{stamp}.db")
        try:
            _vacuum_into(db_path, staging_path)
        except Exception as exc:
            message = (
                f"[Backup FAIL] {kind} {stamp} | step=vacuum_into | "
                f"err={type(exc).__name__}: {exc}\n"
                "운영자 조치: SQLite 라이브 락 / 디스크 여유 점검 후 재시도."
            )
            print_flush(message)
            traceback.print_exc()
            _send_slack(message, notify_fn)
            result["status"] = "vacuum_failed"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            sys.exit(1)
        result["vacuum_db_size"] = os.path.getsize(staging_path)
        print_flush(f"  staging .db {result['vacuum_db_size']} bytes")

        print_flush(f"[Step 5/10] gzip + 이동 ({kind}/)")
        gz_rel_path = f"{kind}/autostock-{stamp}.db.gz"
        gz_abs_path = os.path.join(repo_dir, gz_rel_path)
        try:
            result["gz_size"] = _gzip_file(staging_path, gz_abs_path)
        except Exception as exc:
            message = (
                f"[Backup FAIL] {kind} {stamp} | step=gzip | "
                f"err={type(exc).__name__}: {exc}\n"
                "운영자 조치: 디스크 여유 점검."
            )
            print_flush(message)
            traceback.print_exc()
            _send_slack(message, notify_fn)
            result["status"] = "gzip_failed"
            result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
            try:
                if os.path.exists(staging_path):
                    os.remove(staging_path)
            except Exception:
                pass
            sys.exit(2)
        try:
            os.remove(staging_path)
        except OSError:
            pass
        result["gz_file_rel"] = gz_rel_path
        print_flush(f"  gz {gz_rel_path} ({result['gz_size']} bytes)")

    if dry_run:
        print_flush(f"[Step 6/10] dry-run 모드: 회전 시뮬레이션만 수행")
        rotated_list = _rotate_files(repo_dir, kind=kind, now_kst=now_kst)
        result["rotated_files_list"] = rotated_list
        for rel_path in rotated_list:
            print_flush(f"  (sim) git rm {rel_path}")
        if rotated_list:
            try:
                _run_git(["reset", "HEAD", "--", "."], cwd=repo_dir, check=False)
                _run_git(["checkout", "--", "."], cwd=repo_dir, check=False)
            except Exception:
                pass
        try:
            if os.path.exists(gz_abs_path):
                os.remove(gz_abs_path)
        except Exception:
            pass
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        result["elapsed_ms"] = elapsed_ms
        message = (
            f"[Backup DRY-RUN OK] {kind} {stamp} | gz={result['gz_size']//1024}KB | "
            f"rotated={len(rotated_list)} | elapsed={elapsed_ms//1000}s"
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        return result

    print_flush(f"[Step 7/10] git add + commit")
    try:
        _run_git(["add", gz_rel_path], cwd=repo_dir)
        _run_git(
            ["commit", "-m", f"[backup] {kind} {stamp}"],
            cwd=repo_dir,
            check=False,
        )
    except subprocess.CalledProcessError as exc:
        message = (
            f"[Backup FAIL] {kind} {stamp} | step=commit | "
            f"err={_redact_token((exc.stderr or '').strip()[:200], token)}"
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "commit_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(3)

    print_flush(f"[Step 8/10] 보관 정책 회전 (kind={kind})")
    rotated_list: List[str] = []
    rotate_warn = False
    try:
        rotated_list = _rotate_files(repo_dir, kind=kind, now_kst=now_kst)
        result["rotated_files_list"] = rotated_list
        if rotated_list:
            _run_git(
                [
                    "commit", "-m",
                    f"[backup] rotate {kind} -{len(rotated_list)}",
                ],
                cwd=repo_dir,
                check=False,
            )
            for rel_path in rotated_list:
                print_flush(f"  rotated {rel_path}")
        else:
            print_flush(f"  rotate 대상 0건")
    except Exception as exc:
        rotate_warn = True
        print_flush(f"  [WARN] rotate 실패: {exc}")
        traceback.print_exc()

    print_flush(f"[Step 9/10] git push origin {branch}")
    try:
        commit_sha = _git_push_with_retry(repo_dir, branch=branch, token=token)
        result["commit_sha"] = commit_sha
    except subprocess.CalledProcessError as exc:
        message = (
            f"[Backup FAIL] {kind} {stamp} | step=git_push | "
            f"err={_redact_token((exc.stderr or '').strip()[:200], token)}\n"
            "운영자 조치: BACKUP_GITHUB_TOKEN 만료 가능. PAT 재발급 후 .env 갱신 + 봇 재기동. "
            "staging/.db.gz 는 보존되어 다음 회차에 재시도됩니다."
        )
        print_flush(message)
        _send_slack(message, notify_fn)
        result["status"] = "push_failed"
        result["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
        sys.exit(3)

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    result["elapsed_ms"] = elapsed_ms

    print_flush(f"[Step 10/10] 결과 보고")
    if rotate_warn:
        message = (
            f"[Backup WARN] {kind} {stamp} OK / rotate FAIL — "
            f"백업 자체는 성공. 다음 회차 재시도."
        )
    else:
        message = (
            f"[Backup OK] {kind} {stamp} | gz={result['gz_size']//1024}KB | "
            f"rotated={len(rotated_list)} | elapsed={elapsed_ms//1000}s"
        )
    print_flush(message)
    _send_slack(message, notify_fn)
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SQLite -> GitHub backup orphan branch 백업 스크립트",
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=list(_VALID_KIND_LIST),
        help="백업 종류 (daily/weekly/monthly).",
    )
    parser.add_argument(
        "--db-path",
        default=os.getenv("STATE_STORE_DB_PATH", "data/sqlite/autostock.db"),
        help="SQLite DB 파일 경로 (기본: STATE_STORE_DB_PATH 또는 data/sqlite/autostock.db).",
    )
    parser.add_argument(
        "--repo-dir",
        default=os.getenv("BACKUP_REPO_DIR", "data/backup_repo"),
        help="백업 작업 디렉터리 (기본: BACKUP_REPO_DIR 또는 data/backup_repo).",
    )
    parser.add_argument(
        "--no-slack",
        action="store_true",
        help="슬랙 보고 생략 (로컬 검증용).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="VACUUM INTO + gzip + 회전 시뮬레이션. git commit/push 미실행.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    notify_fn = _resolve_slack_notifier(args.no_slack)
    try:
        result = run_backup_cycle(
            kind=args.kind,
            db_path=args.db_path,
            repo_dir=args.repo_dir,
            notify_fn=notify_fn,
            dry_run=args.dry_run,
        )
    except SystemExit:
        raise
    except Exception as exc:
        message = (
            f"[Backup FAIL] uncaught | kind={args.kind} | "
            f"err={type(exc).__name__}: {exc}"
        )
        print_flush(message)
        traceback.print_exc()
        _send_slack(message, notify_fn)
        return 3

    status = result.get("status", "ok")
    if status in {"ok", "skip_no_daily"}:
        return 0
    if status == "vacuum_failed":
        return 1
    if status == "gzip_failed":
        return 2
    if status in {"setup_failed", "fetch_failed", "commit_failed", "push_failed"}:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
