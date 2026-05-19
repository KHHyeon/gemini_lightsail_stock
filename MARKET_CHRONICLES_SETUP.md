# Market Chronicles (v3.0) 설정 가이드

## 환경 변수 (.env)

```bash
# Drive 활성화 (0이면 로컬 JSON 폴백만 사용)
GOOGLE_DRIVE_ENABLED=1

# 방법 A: 서비스 계정 (서버 권장)
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
GOOGLE_DRIVE_ROOT_FOLDER_ID=           # 선택: 미설정 시 AutoStockBot_Data 폴더 자동 생성

# 방법 B: OAuth (개인 Drive)
GOOGLE_DRIVE_OAUTH_CLIENT_FILE=/path/to/client_secret.json

# 선택
GOOGLE_DRIVE_ROOT_FOLDER_NAME=AutoStockBot_Data
```

## 서비스 계정 사용 시

1. Google Cloud Console에서 Drive API 활성화
2. 서비스 계정 JSON 발급
3. Drive 루트 폴더를 서비스 계정 이메일과 **편집자**로 공유
4. `GOOGLE_DRIVE_ROOT_FOLDER_ID`에 해당 폴더 ID 설정 (권장)

## 슬랙 명령

- `!크로니클` : T-Day 크로니클 수동 작성 (트리거 충족 시)
- `완료` : Drive Pause 상태 해제 및 재검증

## 스케줄

- **15:35** : T-Day 크로니클 + 임시 파일 TTL 정리
