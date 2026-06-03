"""allow 목록 → comm-matrix.csv(행=to, 열=from, 정사각 NxN). 선택적 서버 POST.

방향은 comm_matrix.CommMatrix._weights[to_pat][from_pat] 규약을 따른다. 노드 집합은
워커 id들 + allow에 등장한 비-id 정규식. operator는 매트릭스 무시(항상 allow)라 노드에
넣지 않는다.
"""
from __future__ import annotations

import re
import urllib.request


def _nodes(team: list[dict]) -> list[str]:
    ids = [m["id"] for m in team]
    extra: list[str] = []
    for m in team:
        for tok in m.get("allow", []):
            if tok not in ids and tok not in extra:
                extra.append(tok)
    return ids + extra


def _allows(to_node: str, allow: list[str]) -> bool:
    """allow가 to_node를 허용하는가. 리터럴 동일 또는 정규식 fullmatch."""
    for pat in allow:
        if pat == to_node:
            return True
        try:
            if re.fullmatch(pat, to_node):
                return True
        except re.error:
            continue
    return False


def build_csv(team: list[dict]) -> str:
    """team(각 {id, allow}) → comm-matrix.csv 문자열. 행=to, 열=from."""
    nodes = _nodes(team)
    allow_by_id = {m["id"]: list(m.get("allow", [])) for m in team}
    lines = [",".join(nodes)]
    for to in nodes:                       # 행 = 수신자(to)
        row = []
        for frm in nodes:                  # 열 = 발신자(from)
            w = 0
            if frm in allow_by_id and _allows(to, allow_by_id[frm]):
                w = 1
            row.append(str(w))
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def post_to_server(server_url: str, csv_text: str, token: str, *, timeout: float = 5.0) -> int:
    """서버 /admin/comm-matrix에 CSV를 POST. HTTP 상태코드 반환. 서버 URL은 .../mcp
    형태이므로 베이스로 환원해 /admin/comm-matrix를 붙인다."""
    base = server_url.rsplit("/mcp", 1)[0].rstrip("/")
    req = urllib.request.Request(
        f"{base}/admin/comm-matrix",
        data=csv_text.encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/csv"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status
