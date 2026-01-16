#!/bin/bash

# 사용법 및 인자값 검증
if [ $# -lt 6 ]; then
    echo "Usage: $0 {start|stop|restart|status} server_names IP PORT USER PASS"
    exit 1
fi

ACTION=$1
SERVER_NAMES=$2 # 쉼표로 구분된 서버 리스트
IP=$3
PORT=$4
USER=$5
PASS=$6
MAX_WAIT=60     # 최대 대기 시간 (초)

# jeusadmin 명령어 조합
JEUS_CMD="jeusadmin -host $IP:$PORT -u $USER -p $PASS"

# 1. 특정 서버의 상태를 가져오는 함수 (Status만 추출)
get_status() {
    local server_name="$1"
    # 제공해주신 명령어를 기반으로 Status 추출
    local status=$(jeusadmin -host "$IP:$PORT" -u "$USER" -p "$PASS" "si -server $server_name" 2> /dev/null | grep "|" | egrep -v "adminServer|Status" | awk -F '|' '$2 !~ /^ *$/ {print $3}' | tr -d ' ' | sed 's/([^)]*)//g')
    echo "$status"
}

# 2. 상태 변경 대기 함수 (Polling 방식 적용)
# 사용법: wait_for_status "서버이름" "기대하는상태"
wait_for_status() {
    local server="$1"
    local target_status="$2"
    local elapsed=0

    echo "[INFO] $server 상태가 $target_status 될 때까지 대기 중 (최대 ${MAX_WAIT}초)..."
    
    while [ $elapsed -lt $MAX_WAIT ]; do
        local current_status=$(get_status "$server")
        
        if [ "$current_status" == "$target_status" ]; then
            return 0 # 성공
        fi
        
        sleep 1
        ((elapsed++))
    done
    
    return 1 # 타임아웃 실패
}

# 3. 서버 시작 로직
start_server() {
    local server="$1"
    echo "----------------------------------------"
    echo "[INFO] $server 시작 시도 중..."
    
    # 시작 전 현재 상태 확인
    local current_status=$(get_status "$server")
    if [ "$current_status" == "RUNNING" ]; then
        echo "[INFO] $server 는 이미 RUNNING 상태입니다."
        return 0
    fi

    # 시작 명령어 실행 (에러 숨김)
    jeusadmin -host "$IP:$PORT" -u "$USER" -p "$PASS" "start-server $server" > /dev/null 2>&1
    
    # Polling으로 RUNNING 상태 대기
    if wait_for_status "$server" "RUNNING"; then
        echo "[SUCCESS] $server 가 정상적으로 시작되었습니다."
        return 0
    else
        local final_status=$(get_status "$server")
        echo "[ERROR] $server 시작 실패 또는 시간 초과. (현재 상태: $final_status)"
        return 1
    fi
}

# 4. 서버 중지 로직
stop_server() {
    local server="$1"
    echo "----------------------------------------"
    echo "[INFO] $server 중지 시도 중 (-f)..."
    
    local current_status=$(get_status "$server")
    if [ "$current_status" == "SHUTDOWN" ]; then
        echo "[INFO] $server 는 이미 SHUTDOWN 상태입니다."
        return 0
    fi
    
    # 중지 명령어 실행 (에러 숨김)
    $JEUS_CMD "stop-server $server -f" > /dev/null 2>&1
    
    # Polling으로 SHUTDOWN 상태 대기
    if wait_for_status "$server" "SHUTDOWN"; then
        echo "[SUCCESS] $server 가 정상적으로 중지되었습니다."
        return 0
    else
        local final_status=$(get_status "$server")
        echo "[ERROR] $server 중지 실패 또는 시간 초과. (현재 상태: $final_status)"
        return 1
    fi
}

# 메인 실행 로직
IFS=',' read -ra ADDR <<< "$SERVER_NAMES" # 쉼표 기준 배열 변환

for SERVER in "${ADDR[@]}"; do
    # 공백 제거
    SERVER=$(echo "$SERVER" | xargs)
    
    if [ -z "$SERVER" ]; then
        continue
    fi

    case $ACTION in
        start)
            start_server "$SERVER"
            ;;
        stop)
            stop_server "$SERVER"
            ;;
        restart)
            # 조건 1: 중지 후 성공 여부에 따라 시작
            if stop_server "$SERVER"; then
                # 조건 2: SHUTDOWN 정상 확인 후 시작
                start_server "$SERVER"
            else
                echo "[SKIP] $SERVER 가 정상적으로 종료되지 않아 시작 명령을 수행하지 않습니다."
            fi
            ;;
        status)
            STATUS=$(get_status "$SERVER")
            echo "[STATUS] $SERVER : $STATUS"
            ;;
        *)
            echo "Usage: $0 {start|stop|restart|status} server_name1,server_name2"
            exit 1
            ;;
    esac
done
