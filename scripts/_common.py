# -*- coding: utf-8 -*-
"""
scripts/*.py 공통 부트스트랩.

종전에 backfill_chronicles / drive_oauth_setup / drive_oauth_refresh /
drive_folder_bootstrap 4개 스크립트에 중복되어 있던 다음 3가지 패턴을
본 모듈로 단일화한다.

1. ``setup_script_path()`` — 프로젝트 루트를 sys.path 에 삽입하여
   ``from src.memory import ...`` 등 패키지 임포트가 동작하게 한다.
2. ``load_env_file(env_file=None, *, verbose=False)`` — .env 파일 로드.
   ``python-dotenv`` 미설치 시 안전 fallback. ``env_file`` 미지정 시
   프로젝트 루트의 ``.env`` 를 자동 탐색한다.
3. ``print_flush(msg)`` — print(..., flush=True) 단축형. 백그라운드 실행
   (LightSail systemd / SSH disown) 환경에서 stdout 버퍼링을 방지한다.

사용 예시 (scripts/*.py 상단):
    from _common import setup_script_path
    setup_script_path()  # 반드시 src.* 임포트보다 먼저 호출

    from _common import load_env_file, print_flush  # noqa: E402
"""
import os
import sys


_SCRIPT_FILE = os.path.abspath(__file__)
PROJECT_ROOT = os.path.dirname(os.path.dirname(_SCRIPT_FILE))


def setup_script_path():
    """프로젝트 루트를 sys.path 에 등록.

    이 함수가 호출되기 전에는 ``from src.* import ...`` 가 실패할 수 있다.
    """
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)
    return PROJECT_ROOT


def load_env_file(env_file=None, *, verbose=False):
    """프로젝트 ``.env`` 파일을 로드한다.

    Args:
        env_file: 명시적 .env 경로. None 이면 프로젝트 루트의 ``.env`` 사용.
        verbose: True 면 로드 결과를 stdout 에 보고한다.

    Returns:
        bool: 실제 로드 성공 여부.
    """
    target = env_file or os.path.join(PROJECT_ROOT, ".env")
    try:
        from dotenv import load_dotenv
    except ImportError:
        if verbose:
            print("[WARN] python-dotenv 미설치. 시스템 환경 변수만 사용합니다.")
        return False
    if os.path.isfile(target):
        load_dotenv(target, override=True)
        if verbose:
            print(f"  .env 로드: {target}")
        return True
    if verbose:
        print(f"  [WARN] .env 파일 없음: {target}")
    return False


def print_flush(msg):
    """stdout 버퍼링 회피용 print 단축형."""
    print(msg, flush=True)
