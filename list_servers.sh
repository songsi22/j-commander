#!/bin/bash
# jhome 의 bin 에 있는 jeus.properties 파일에 JAVA_ARGS의 마지막에 -Djeus.console.table.width=230 를 추가하여 서버 이름이 길어도 잘 표현될 수 있도록 권장
# 명령어 존재 여부 확인 (optional, dsa가 alias나 function일 수도 있어서 command -v가 안 먹힐 수도 있음)
# if ! command -v dsa &> /dev/null; then
#     echo "[ERROR] 'dsa' command not found." >&2
#     exit 1
# fi

# dsa 실행 및 파싱
# 인자값 검증 (IP, PORT, USER, PASS)
if [ $# -lt 4 ]; then
    IP="127.0.0.1"
    PORT="10000"
    USER="user"
    PASS="password"
else
    IP=$1
    PORT=$2
    USER=$3
    PASS=$4
fi

# jeusadmin 명령어 조합
JEUS_CMD="jeusadmin -host $IP:$PORT -u $USER -p $PASS"

# 1. si 명령 실행 결과를 변수에 저장
# 2>&1 을 통해 에러 메시지도 캡처하여 디버깅에 도움을 줌
RAW_OUTPUT=$(jeusadmin -host "$IP:$PORT" -u "$USER" -p "$PASS" si 2>&1)
DSA_EXIT_CODE=$?

# Parsing 로직 개선: | 가 있는 라인만 추출
RESULT=$(echo "$RAW_OUTPUT" | grep "|" | egrep -v "adminServer|Status" | awk -F '|' '$2 !~ /^ *$/ {print $2, $3}')

if [ -z "$RESULT" ]; then
    echo "[ERROR] No servers found or JEUS error occurred." >&2
    echo "--- RAW OUTPUT START ---" >&2
    echo "$RAW_OUTPUT" >&2
    echo "--- RAW OUTPUT END ---" >&2
    exit 1
fi

# 결과 출력
echo "$RESULT"
