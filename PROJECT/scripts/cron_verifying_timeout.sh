#!/usr/bin/env bash
# 장애 대응 크론: VERIFYING 타임아웃 처리
# - 판정 규칙(verifying_timeout_minutes) 초과 건을 UNFIT/ERROR로 처리 후 FE 콜백 전송
# 사용법:
#   CRON_SECRET=xxx API_BASE_URL=https://api.example.com ./cron_verifying_timeout.sh
#   또는 X-Admin-Key 사용: ADMIN_API_KEY=xxx API_BASE_URL=... ./cron_verifying_timeout.sh
# crontab 예: */10 * * * * CRON_SECRET=xxx API_BASE_URL=https://api.example.com /path/to/cron_verifying_timeout.sh >> /var/log/gems_cron.log 2>&1

API_BASE_URL="${API_BASE_URL:-http://localhost:8000}"
API_BASE_URL="${API_BASE_URL%/}"

if [[ -z "$API_BASE_URL" ]]; then
  echo "$(date '+%Y-%m-%dT%H:%M:%S') ERROR: API_BASE_URL is empty (curl exit 3 = URL malformed)"
  exit 1
fi

CURL_EXIT=0
if [[ -n "$CRON_SECRET" ]]; then
  RESP=$(curl -s -w "\n%{http_code}" -X POST \
    -H "X-Cron-Secret: $CRON_SECRET" \
    -H "Content-Type: application/json" \
    "$API_BASE_URL/api/v1/admin/jobs/cron/verifying-timeout") || CURL_EXIT=$?
elif [[ -n "$ADMIN_API_KEY" ]]; then
  RESP=$(curl -s -w "\n%{http_code}" -X POST \
    -H "X-Admin-Key: $ADMIN_API_KEY" \
    -H "Content-Type: application/json" \
    "$API_BASE_URL/api/v1/admin/jobs/process-verifying-timeout") || CURL_EXIT=$?
else
  echo "$(date '+%Y-%m-%dT%H:%M:%S') ERROR: set CRON_SECRET or ADMIN_API_KEY"
  exit 1
fi

if [[ "$CURL_EXIT" -ne 0 ]]; then
  echo "$(date '+%Y-%m-%dT%H:%M:%S') ERROR: curl failed exit=$CURL_EXIT (3=URL malformed, 6=unreachable, 7=refused). API_BASE_URL length=${#API_BASE_URL}"
  exit 1
fi

# 맥(BSD) head는 -n -1 미지원 → sed로 마지막 줄 제외
BODY=$(echo "$RESP" | sed '$d')
CODE=$(echo "$RESP" | tail -n 1)
echo "$(date '+%Y-%m-%dT%H:%M:%S') POST verifying-timeout HTTP $CODE $BODY"
if [[ "$CODE" -ge 400 ]] || [[ "$CODE" -lt 200 ]]; then
  exit 1
fi
exit 0
