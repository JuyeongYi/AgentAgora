"""v4 agora error codes + Korean messages (spec §4.5)."""
from __future__ import annotations


# code -> str.format template. {placeholders} filled by AgoraError kwargs.
# Plan 1: schema 관련 코드. 봇 관련 코드는 Plan 2에서 추가된다.
ERROR_MESSAGES: dict[str, str] = {
    "payload_missing_msgtype": "[agora] payload에 msgtype이 없습니다. 모든 메시지는 msgtype이 필수입니다.",
    "unknown_msgtype": "[agora] msgtype '{msgtype}'는 registry에 없습니다.",
    "schema_violation": "[agora] schema_violation: {detail}",
    "schema_immutable": "[agora] schema '{name}'는 다른 body로 이미 등록됨.",
    "schema_missing_msgtype": "[agora] schema '{name}' body에 msgtype property가 없습니다. (결정 20)",
}


class AgoraError(ValueError):
    """agora 도메인 에러. .code로 에러 코드를, str()로 한국어 메시지를 노출한다.

    ValueError 서브클래스 — server.py의 기존 ``except (NotRegisteredError, ValueError)``
    경로가 그대로 잡아 ``{"error": str(e)}``로 직렬화한다.
    """

    def __init__(self, code: str, **fmt: object) -> None:
        self.code = code
        template = ERROR_MESSAGES.get(code, "[agora] {code}")
        try:
            message = template.format(code=code, **fmt)
        except (KeyError, IndexError):
            message = template
        super().__init__(message)
