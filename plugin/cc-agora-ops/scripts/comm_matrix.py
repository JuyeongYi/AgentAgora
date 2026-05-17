"""/agora-comm-matrix implementation — operator comm-matrix admin client.

Calls the token-gated /admin/comm-matrix endpoint (comm-matrix governance spec).
``build_request`` is pure (testable); ``main`` performs the HTTP call.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

DEFAULT_SERVER_URL = "http://127.0.0.1:8420"


def build_request(
    *, action: str, server_url: str, token: str | None, csv: str | None,
) -> tuple[str, str, dict[str, str], str | None]:
    """Return (method, url, headers, body) for the admin call.

    action='get' → GET (no body). action='post' → POST with the CSV body.
    Raises ValueError when the token is missing or a POST has no CSV.
    """
    if not token:
        raise ValueError(
            "AGORA_ADMIN_TOKEN is not set — the server must run with that env var "
            "and the operator must export the same token.")
    url = server_url.rstrip("/") + "/admin/comm-matrix"
    headers = {"Authorization": f"Bearer {token}"}
    if action == "get":
        return "GET", url, headers, None
    if action == "post":
        if csv is None:
            raise ValueError("post action requires a csv file argument")
        return "POST", url, headers, csv
    raise ValueError(f"unknown action: {action!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agora-comm-matrix")
    p.add_argument("csv_path", nargs="?", default=None,
                   help="CSV file to POST. Omit to GET the current matrix.")
    p.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    args = p.parse_args(argv)

    token = os.environ.get("AGORA_ADMIN_TOKEN")
    action = "post" if args.csv_path else "get"
    csv = None
    if action == "post":
        csv = open(args.csv_path, encoding="utf-8").read()
    try:
        method, url, headers, body = build_request(
            action=action, server_url=args.server_url, token=token, csv=csv)
    except ValueError as e:
        print(f"[cc-agora-ops] {e}", file=sys.stderr)
        return 1

    data = body.encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            print(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        if e.code == 401:
            print("[cc-agora-ops] 401 Unauthorized — AGORA_ADMIN_TOKEN이 서버 토큰과 "
                  "일치하지 않습니다.", file=sys.stderr)
        elif e.code == 400:
            print(f"[cc-agora-ops] 400 — CSV 오류: {detail}", file=sys.stderr)
        else:
            print(f"[cc-agora-ops] HTTP {e.code}: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
