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
    # Plan 2 — bot routing codes
    "no_route": "[agora] msgtype '{msgtype}'를 구독하는 봇이 없고 target도 없습니다.",
    "unhandled_schema": "[agora] 봇 {bot}는 msgtype '{msgtype}'를 구독하지 않습니다.",
    "bot_emit_not_a_bot": "[agora] agora.bot_emit은 봇만 호출할 수 있습니다.",
    "description_required": "[agora] 봇 mode는 description이 필수입니다.",
    "subscribe_required": "[agora] bot-handler는 구독 schema가 비어있을 수 없습니다.",
    "cannot_subscribe_conversation": "[agora] conversation kind schema '{name}'는 봇이 구독할 수 없습니다.",
    "schema_kind_not_bot_task": "[agora] 봇이 등록하는 schema '{name}'는 kind가 'bot-task'여야 합니다.",
    # comm-matrix codes
    "comm_denied": "[agora] comm_denied: {from_} -> {to} (통신 매트릭스가 이 쌍의 dispatch를 금지함).",
    "comm_matrix_shape_mismatch": "[agora] comm-matrix CSV shape 불일치: {detail}",
    "comm_matrix_invalid_cell": "[agora] comm-matrix CSV 셀 오류: {detail}",
    # file codes
    "file_too_large": "[agora] 파일이 너무 큽니다: {size} bytes (상한 {limit}).",
    "file_upload_denied": "[agora] file_upload_denied: {worker}는 '{name}'을 공유할 수 없습니다 (파일 권한 정책).",
    "file_download_denied": "[agora] file_download_denied: {worker}는 '{name}'을 받을 수 없습니다 (파일 권한 정책).",
    "unknown_file": "[agora] unknown_file: file_id '{file_id}'를 찾을 수 없습니다.",
    "file_policy_invalid": "[agora] file-policy.json 오류: {detail}",
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
