#!/usr/bin/env python3
"""
Cookie Acquisition Subprocess Script

This script is executed as a subprocess to acquire ALB sticky session cookies
from a specific Fargate container. It uses process isolation to ensure
independent TCP connection pools for multi-job environments.

Usage:
    python3 cookie_acquisition_subprocess.py <alb_dns> <expected_ip> <session_id>

Architecture:
    - Runs in isolated subprocess with independent TCP connection pool
    - ALB Round Robin distributes requests across containers
    - Session ID validation ensures correct container match
    - Returns JSON result via stdout
"""

import sys
import json
import time


def acquire_cookie(alb_dns: str, expected_ip: str, session_id: str, max_attempts: int = 40) -> int:
    """
    Acquire sticky session cookie from the target container.

    Args:
        alb_dns: ALB DNS endpoint
        expected_ip: Expected container private IP
        session_id: Session ID to validate
        max_attempts: Maximum number of attempts (default: 40)

    Returns:
        0 on success, 1 on failure
    """
    import requests

    # Subprocess 시작 로그
    print(f"[Subprocess] 🚀 Starting cookie acquisition", file=sys.stderr)
    print(f"[Subprocess]    Target: {alb_dns}", file=sys.stderr)
    print(f"[Subprocess]    Expected IP: {expected_ip}", file=sys.stderr)
    print(f"[Subprocess]    Session ID: {session_id}", file=sys.stderr)

    # Health check with session validation
    # Check every 5s for up to 3.3 minutes (40 checks * 5s = 200s)
    # Increased from 24 to 40 to account for ALB health check delay
    container_ready = False
    cookie_value = None

    for health_check in range(1, max_attempts + 1):
        try:
            # 매 시도마다 로그 (첫 10회 + 이후 5회마다)
            if health_check <= 10 or health_check % 5 == 1:
                print(f"[Subprocess] Attempt {health_check}/{max_attempts}: Sending request to {alb_dns}/container-info", file=sys.stderr)

            session = requests.Session()

            # /container-info에 세션 ID 포함하여 요청
            response = session.get(
                f"http://{alb_dns}/container-info",
                params={"session_id": session_id},
                timeout=5
            )

            # HTTP 응답 상태 로그
            if health_check <= 10 or health_check % 5 == 1:
                print(f"[Subprocess]    Response: HTTP {response.status_code}", file=sys.stderr)

            if response.status_code == 200:
                data = response.json()
                actual_ip = data.get('private_ip', 'unknown')
                known_sessions = data.get('known_sessions', [])

                # IP 및 세션 검증 상세 로그
                if health_check <= 10 or health_check % 5 == 1:
                    print(f"[Subprocess]    Container IP: {actual_ip} (expected: {expected_ip})", file=sys.stderr)
                    print(f"[Subprocess]    Known sessions: {known_sessions}", file=sys.stderr)
                    print(f"[Subprocess]    Session match: {session_id in known_sessions}", file=sys.stderr)

                # 올바른 컨테이너인지 검증:
                # 1. IP 일치 확인
                # 2. 이 컨테이너가 우리 세션 ID를 알고 있는지 확인
                if actual_ip == expected_ip and session_id in known_sessions:
                    # 올바른 컨테이너! Cookie 획득
                    cookie_value = session.cookies.get('AWSALB', '')
                    if cookie_value:
                        print(f"[Subprocess] ✅ Cookie acquired at attempt {health_check}!", file=sys.stderr)
                        print(f"[Subprocess]    Container IP: {actual_ip}", file=sys.stderr)
                        print(f"[Subprocess]    Session ID: {session_id}", file=sys.stderr)
                        print(f"[Subprocess]    Cookie: {cookie_value[:20]}...", file=sys.stderr)
                        container_ready = True
                        result = {
                            "success": True,
                            "cookie": cookie_value,
                            "attempt": health_check,
                            "ip": actual_ip,
                            "session_id": session_id
                        }
                        print(json.dumps(result))
                        session.close()
                        return 0
                    else:
                        print(f"[Subprocess] ⚠️  IP/Session match but no AWSALB cookie!", file=sys.stderr)
                else:
                    # 잘못된 컨테이너 - Cookie 버리고 재시도
                    if health_check <= 10 or health_check % 5 == 1:
                        if actual_ip != expected_ip:
                            print(f"[Subprocess]    ❌ IP mismatch: {actual_ip} != {expected_ip}", file=sys.stderr)
                        if session_id not in known_sessions:
                            print(f"[Subprocess]    ❌ Session not found in container", file=sys.stderr)
                    session.cookies.clear()
            else:
                # Non-200 response
                if health_check <= 10 or health_check % 5 == 1:
                    print(f"[Subprocess]    ⚠️  HTTP {response.status_code}", file=sys.stderr)

            session.close()
        except Exception as e:
            # 모든 예외 상세 로깅
            print(f"[Subprocess] [Attempt {health_check}] ❌ Exception: {type(e).__name__}: {str(e)}", file=sys.stderr)
            import traceback
            if health_check <= 3:  # 처음 3번은 traceback 출력
                print(f"[Subprocess] Traceback: {traceback.format_exc()}", file=sys.stderr)

        if health_check < max_attempts:
            if health_check == 10:
                print(f"[Subprocess] 🕐 10 attempts completed, continuing...", file=sys.stderr)
            elif health_check == 20:
                print(f"[Subprocess] 🕐 20 attempts completed, continuing...", file=sys.stderr)
            elif health_check == 30:
                print(f"[Subprocess] 🕐 30 attempts completed, final 10 attempts...", file=sys.stderr)
            time.sleep(5)

    # If container is not ready or session not found after 200 seconds, fail
    print(f"[Subprocess] ❌ TIMEOUT after {max_attempts} attempts ({max_attempts * 5} seconds)", file=sys.stderr)
    result = {
        "success": False,
        "error": f"Failed to acquire cookie from correct container (IP: {expected_ip}, Session: {session_id}) after {max_attempts * 5} seconds"
    }
    print(json.dumps(result))
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 4:
        error_result = {
            "success": False,
            "error": "Invalid arguments. Usage: cookie_acquisition_subprocess.py <alb_dns> <expected_ip> <session_id>"
        }
        print(json.dumps(error_result))
        sys.exit(1)

    alb_dns = sys.argv[1]
    expected_ip = sys.argv[2]
    session_id = sys.argv[3]

    sys.exit(acquire_cookie(alb_dns, expected_ip, session_id))
