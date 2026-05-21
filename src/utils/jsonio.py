# -*- coding: utf-8 -*-
"""
로컬 JSON 파일 읽기/쓰기 단일 진입점.

token_manager.py / oauth_token.py / drive_client.py / scripts/*.py 등에
산재되어 있던 `open() + json.load/dump` 직접 구현을 본 모듈로 통합한다.

Drive 상의 JSON 은 drive_client.read_json_relative / write_json_relative 를
사용해야 한다. 본 모듈은 오직 **로컬 파일 시스템** 의 JSON 만 다룬다.
"""
import json
import os


def read_local_json(path, default=None):
    """로컬 JSON 파일을 dict 로 읽어 반환.

    파일이 없거나 손상되었으면 default 를 그대로 반환한다(예외 미발생).
    """
    if not path or not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError):
        return default


def write_local_json(path, data, *, indent=2, ensure_dir=True):
    """로컬 JSON 파일에 data 를 저장.

    ensure_dir=True 이면 상위 폴더를 자동 생성한다.
    """
    if ensure_dir:
        parent_dir = os.path.dirname(os.path.abspath(path))
        if parent_dir and not os.path.isdir(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=indent)
