"""대시보드 데모 시드 — 실제 Claude 워커 없이 브로커에 가짜 트래픽을 넣어
대시보드 패널(인스턴스·대화·검색·메트릭·comm-matrix)을 채운다.

브로커가 떠 있어야 한다(start-broker.bat). stdlib만 사용.

사용: ../.venv/Scripts/python.exe seed-demo.py [--url http://127.0.0.1:8420]

참고: 플로우 뷰의 in-flight 엣지와 coverage는 워커↔워커 expect_result 메시지가 필요해
실제 워커(start-all.bat)를 띄워야 채워진다 — 시드는 운영자 dispatch까지만 만든다.
워커 설명(description)은 HTTP 헤더로 가므로 ASCII만 — 헤더는 latin-1만 인코딩 가능.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

# description은 HTTP 헤더(X-Agora-Description)로 전달되므로 ASCII만(latin-1 제약).
WORKERS = [
    ("Orchestrator", "orchestrator", "team coordination"),
    ("Planner", "planner", "design and planning"),
    ("Coder", "coder", "implementation"),
    ("Reviewer", "reviewer", "code review"),
    ("Tester", "tester", "testing"),
    ("Writer", "writer", "docs"),
]

# 검색·대화·메트릭을 채울 운영자 dispatch 샘플.
DISPATCHES = [
    ("Coder", "rocket engine 텔레메트리 파서를 구현해줘"),
    ("Coder", "메모리 누수 의심 — sample 루프의 deque 확인"),
    ("Reviewer", "PR #42 리뷰 부탁 (coder→writer 게이트)"),
    ("Tester", "FTS5 검색 라운드트립 테스트 추가"),
    ("Planner", "다음 스프린트 백로그 정리"),
    ("Writer", "릴리스 노트 초안 작성"),
]

COMM_MATRIX_CSV = (
    "(?i)orchestrator.*,(?i)planner.*,(?i)coder.*,(?i)tester.*,(?i)reviewer.*,(?i)writer.*\n"
    "1,1,1,1,1,1\n"
    "1,0,0,0,0,0\n"
    "1,0,0,1,1,0\n"
    "1,0,1,0,0,0\n"
    "1,0,1,1,0,0\n"
    "1,0,0,0,1,0\n"
)


def _req(method, url, *, headers=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    h = dict(headers or {})
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def main(argv=None):
    p = argparse.ArgumentParser(prog="seed-demo")
    p.add_argument("--url", default="http://127.0.0.1:8420")
    p.add_argument("--operator", default="demo")
    args = p.parse_args(argv)
    base = args.url.rstrip("/")

    # 헬스 체크
    s, _ = _req("GET", base + "/dashboard/auth-mode")
    if s != 200:
        print(f"[seed] 브로커 응답 없음({base}) — start-broker.bat 먼저 실행하세요.",
              file=sys.stderr)
        return 1

    # 1) 워커 자동 등록 — Mcp-Session-Id + X-Agora-Instance-Id 헤더로 미들웨어가 등록.
    for name, role, desc in WORKERS:
        _req("GET", base + "/dashboard/auth-mode", headers={
            "Mcp-Session-Id": f"seed-sess-{name}",
            "X-Agora-Instance-Id": name,
            "X-Agora-Role": role,
            "X-Agora-Description": desc,
        })
    print(f"[seed] 워커 {len(WORKERS)}개 등록")

    # 2) comm-matrix 적용(매트릭스 뷰 + 플로우 정적 엣지)
    s, _ = _req("POST", base + "/dashboard/comm-matrix",
                headers={"X-Agora-Operator-User": args.operator},
                body={"csv": COMM_MATRIX_CSV})
    print(f"[seed] comm-matrix 적용 ({s})")

    # 3) 운영자 dispatch(대화·메시지·검색·메트릭)
    n = 0
    for to, text in DISPATCHES:
        s, _ = _req("POST", base + "/dashboard/dispatch",
                    headers={"X-Agora-Operator-User": args.operator},
                    body={"to": to, "schema": "operator_message", "payload": {"text": text}})
        if s == 201:
            n += 1
    print(f"[seed] 운영자 dispatch {n}/{len(DISPATCHES)}건")

    print(f"[seed] 완료 — 대시보드: {base}/dashboard")
    print("[seed] (플로우 in-flight·coverage는 실제 워커 expect_result가 필요 — start-all.bat)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
