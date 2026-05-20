# Market Chronicles (v3.0) 설정 가이드

## 환경 변수 (.env)

**기존 프로젝트 변수 (권장, 이미 사용 중이면 그대로 사용)**

```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
GDRIVE_FOLDER_ID=your_shared_folder_id
GOOGLE_API_KEY=...                    # Gemini용 (Drive와 별개)

# 서비스 계정 + 개인 Drive 공유 폴더(Quant_Logs 등) 사용 시 필수
GDRIVE_TRANSFER_OWNERSHIP_EMAIL=you@gmail.com

# Google Workspace 공유 드라이브(팀 드라이브) 사용 시
# GDRIVE_USE_SHARED_DRIVE=1
# GDRIVE_SHARED_DRIVE_ID=0ABC...        # 선택
```

### 서비스 계정 storage quota 403 오류

에러: `Service Accounts do not have storage quota`

**원인:** SA는 용량이 0이라, 생성 시점에 업로드가 거부됩니다 (생성 후 소유권 이전으로는 해결 불가).

**해결 (택1):**

| 환경 | 방법 |
|------|------|
| **개인 Gmail** (Quant_Logs) | `python scripts/drive_oauth_setup.py` 로 OAuth 토큰 생성 (권장) |
| **Google Workspace** | `GDRIVE_DELEGATED_USER_EMAIL=user@company.com` + Admin Domain-Wide Delegation |
| **팀 드라이브** | `GDRIVE_USE_SHARED_DRIVE=1` |

OAuth 설정:

```bash
GOOGLE_DRIVE_OAUTH_CLIENT_FILE=/path/to/client_secret.json
# 실행 후 생성: drive_oauth_token.json
```

**신규 별칭 (동일 의미, 둘 중 하나만 있어도 됨)**

```bash
GOOGLE_DRIVE_ENABLED=1
GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=... # = GOOGLE_APPLICATION_CREDENTIALS
GOOGLE_DRIVE_ROOT_FOLDER_ID=...     # = GDRIVE_FOLDER_ID
```

```bash
# 방법 B: OAuth (개인 Drive, 선택)
GOOGLE_DRIVE_OAUTH_CLIENT_FILE=/path/to/client_secret.json
GOOGLE_DRIVE_ROOT_FOLDER_NAME=AutoStockBot_Data   # GDRIVE_FOLDER_ID 미설정 시만
```

## 폴더 구조 자동 생성 (임시 스크립트)

```bash
python scripts/drive_folder_bootstrap.py
```

연결 성공 시 `MarketChronicles/`, `app_data/` 하위 폴더와 `master_index.json`을 생성한다.

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
