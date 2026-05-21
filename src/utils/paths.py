# -*- coding: utf-8 -*-
"""
프로젝트 경로 단일 진입점.

drive_client.py / oauth_token.py 등에서 중복으로 정의되던 _project_root()
구현을 한 곳으로 통합한다.
"""
import os


_THIS_FILE = os.path.abspath(__file__)


def project_root():
    """프로젝트 루트 절대 경로 반환.

    본 파일이 `<root>/src/utils/paths.py` 에 위치한다는 전제 하에
    상위 3단계(`paths.py -> utils -> src -> <root>`)를 거슬러 올라간다.
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(_THIS_FILE)))
