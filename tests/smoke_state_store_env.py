# -*- coding: utf-8 -*-
"""Phase 2 — .env 경유 + DB 파일 영속성 smoke test.

- load_dotenv() 가 state_store import 전에 호출되었을 때 .env 의 값이 적용되는지 검증.
- DB 파일을 한 번 쓰고, 두 번째 프로세스(import context 재구성) 에서 읽혀지는지 검증.

룰 §3: 실제 운영 .env 의 내용을 분석하지 않는다. 본 테스트는 격리된 임시 디렉터리에
임시 .env 를 생성하여 동작만 검증한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _write_temp_env(tmpdir: Path, db_path: Path, backend: str) -> Path:
    """임시 .env 작성. 실제 .env 와 충돌 방지를 위해 별도 경로 사용."""
    env_path = tmpdir / ".env"
    env_path.write_text(
        textwrap.dedent(
            f"""
            STATE_STORE_BACKEND={backend}
            STATE_STORE_DB_PATH={db_path.as_posix()}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return env_path


_SUBPROCESS_BODY = """
import os, sys
sys.path.insert(0, {proj!r})
from dotenv import load_dotenv
load_dotenv({env_path!r})
from src.storage import state_store
backend_name = type(state_store._backend).__name__
print('BACKEND=' + backend_name)
if backend_name == '_SQLiteBackend':
    {body}
"""


def _run_subprocess(env_path: Path, body: str) -> str:
    """별도 프로세스에서 dotenv 로드 후 state_store 동작 결과 capture."""
    code = _SUBPROCESS_BODY.format(
        proj=str(PROJECT_ROOT),
        env_path=str(env_path),
        body=body,
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"subprocess 실패 ({proc.returncode}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def _check_env_sqlite_routing(tmpdir: Path) -> None:
    """[1/3] .env 에 STATE_STORE_BACKEND=sqlite 명시 시 _SQLiteBackend 선택."""
    db_path = tmpdir / "smoke.db"
    env_path = _write_temp_env(tmpdir, db_path, "sqlite")
    out = _run_subprocess(env_path, "print('OK_SQLITE')")
    assert "BACKEND=_SQLiteBackend" in out, out
    assert db_path.exists(), "DB 파일이 생성되어야 함"
    print("[1/3] .env 경유 sqlite 진입 + DB 파일 생성 OK")


def _check_env_drive_routing(tmpdir: Path) -> None:
    """[2/3] .env 가 backend=drive (또는 미설정) 일 때 _DriveBackend 보존."""
    db_path = tmpdir / "smoke_drive.db"
    env_path = _write_temp_env(tmpdir, db_path, "drive")
    out = _run_subprocess(env_path, "pass")
    assert "BACKEND=_DriveBackend" in out, out
    assert not db_path.exists(), "drive 모드에서는 DB 파일 미생성"
    print("[2/3] .env 경유 drive 보존 OK")


def _check_persistence_across_processes(tmpdir: Path) -> None:
    """[3/3] write 후 새 프로세스에서 동일 값 read."""
    db_path = tmpdir / "persist.db"
    env_path = _write_temp_env(tmpdir, db_path, "sqlite")

    write_body = textwrap.dedent(
        """
        state_store.save_portfolio({'005930': {'name': '삼성', 'qty': 10}})
        state_store.replace_trades([{'timestamp': '2026-06-02 10:00:00', 'ticker': '005930', 'action': 'BUY', 'price': 70000, 'quantity': 10}])
        state_store._backend.close()
        print('OK_WRITE')
        """
    ).strip()
    out_write = _run_subprocess(env_path, write_body)
    assert "OK_WRITE" in out_write, out_write

    read_body = textwrap.dedent(
        """
        p = state_store.get_portfolio()
        t = state_store.list_trades()
        assert p == {'005930': {'name': '삼성', 'qty': 10}}, p
        assert len(t) == 1 and t[0]['ticker'] == '005930', t
        state_store._backend.close()
        print('OK_READ')
        """
    ).strip()
    out_read = _run_subprocess(env_path, read_body)
    assert "OK_READ" in out_read, out_read
    print("[3/3] DB 파일 영속성 (write -> 새 프로세스 read) OK")


def main() -> None:
    tmpdir_obj = tempfile.TemporaryDirectory()
    tmpdir = Path(tmpdir_obj.name)
    try:
        _check_env_sqlite_routing(tmpdir)
        _check_env_drive_routing(tmpdir)
        _check_persistence_across_processes(tmpdir)
        print("\nALL OK")
    finally:
        try:
            tmpdir_obj.cleanup()
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
