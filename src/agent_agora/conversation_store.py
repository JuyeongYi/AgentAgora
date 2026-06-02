"""ConversationStore — conversation lifecycle state, extracted from Dispatcher.

자체 락 없음 — 변형 메서드는 호출자(Dispatcher)가 _lock을 잡은 상태에서 호출한다.
읽기 메서드(status·list_conversations·conv_id_of·source_of·get)는 락 없이 호출 가능
(기존 conversation_status/conversations_list 동작 보존)."""
from __future__ import annotations

import datetime
import uuid
from typing import Any

from agent_agora.storage.persistence import Persistence


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ConversationStore:
    def __init__(self, persistence: Persistence) -> None:
        self._persistence = persistence
        self._conversations: dict[str, dict[str, Any]] = {}
        self._conversation_of: dict[str, str] = {}   # cmd_id -> conv_id
        self._message_source: dict[str, str] = {}    # cmd_id -> source

    # --- 라이프사이클 (Dispatcher의 _new_conversation_state 등에서 본문 이동) ---

    def new_state(self, kind: str) -> dict[str, Any]:
        now = _now_iso()
        return {
            "status": "open",
            "kind": kind,
            "participants": {},  # instance_id -> {"role": "primary"|"cc", "delivered": bool}
            "closed_by": [],
            "started_at": now,
            "last_message_at": now,
            "message_count": 0,
            "closed_at": None,
        }

    def add_participant(self, state: dict, instance_id: str, role: str, delivered: bool = True) -> bool:
        """Returns True if newly added."""
        if instance_id in state["participants"]:
            return False
        state["participants"][instance_id] = {"role": role, "delivered": delivered}
        return True

    def maybe_close(self, conv_id: str, state: dict) -> bool:
        """Check if all primary delivered participants have sent closing. Returns True if just closed."""
        if state["status"] == "closed":
            return False
        primaries = {
            iid for iid, info in state["participants"].items()
            if info["role"] == "primary" and info["delivered"]
        }
        closed_by = set(state["closed_by"])
        if primaries and primaries <= closed_by:
            state["status"] = "closed"
            state["closed_at"] = _now_iso()
            return True
        return False

    def resolve_conversation_id(
        self,
        conversation_id: str | None,
        in_reply_to: str | None,
    ) -> tuple[str, bool, bool]:
        """Returns (conv_id, is_new, substituted)."""
        if conversation_id is not None:
            existing = self._conversations.get(conversation_id)
            if existing is not None and existing["status"] == "closed":
                return str(uuid.uuid4()), True, True
            if existing is None:
                # We may want to create a new entry with this caller-provided id
                return conversation_id, True, False
            return conversation_id, False, False
        if in_reply_to is not None:
            inherited = self._conversation_of.get(in_reply_to)
            if inherited is None:
                inherited = self._persistence.lookup_conversation_for(in_reply_to)
            if inherited is not None:
                existing = self._conversations.get(inherited)
                if existing is None or existing["status"] != "closed":
                    return inherited, inherited not in self._conversations, False
        return str(uuid.uuid4()), True, False

    # --- dict 접근자 ---

    def get(self, conv_id: str) -> dict[str, Any] | None:
        return self._conversations.get(conv_id)

    def put(self, conv_id: str, state: dict[str, Any]) -> None:
        self._conversations[conv_id] = state

    def has(self, conv_id: str) -> bool:
        return conv_id in self._conversations

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        """conversation (conv_id, state) 쌍 전체 — sweep 순회용 (읽기, 락 불필요)."""
        return list(self._conversations.items())

    def conv_id_of(self, cmd_id: str) -> str | None:
        return self._conversation_of.get(cmd_id)

    def source_of(self, cmd_id: str) -> str | None:
        return self._message_source.get(cmd_id)

    def record_command(self, cmd_id: str, conv_id: str, source: str) -> None:
        self._conversation_of[cmd_id] = conv_id
        self._message_source[cmd_id] = source

    def set_conv_of(self, cmd_id: str, conv_id: str) -> None:
        """복원 경로용 — conv_id만 기록(source 없이)."""
        self._conversation_of[cmd_id] = conv_id

    def evict(self, conv_ids: list[str]) -> None:
        """GC — 닫힌 conversation과 그에 매인 cmd 캐시를 비운다."""
        victim = set(conv_ids)
        for cid in conv_ids:
            self._conversations.pop(cid, None)
        stale = [c for c, v in self._conversation_of.items() if v in victim]
        for c in stale:
            self._conversation_of.pop(c, None)
            self._message_source.pop(c, None)

    # --- 읽기 (Dispatcher의 conversation_status / conversations_list 본문 이동) ---

    def status(self, conv_id: str) -> dict[str, Any]:
        state = self._conversations.get(conv_id)
        if state is None:
            return {"error": "unknown_conversation"}
        participants = [
            {"instance_id": iid, "role": info["role"]}
            for iid, info in state["participants"].items()
        ]
        return {
            "conversation_id": conv_id,
            "kind": state["kind"],
            "status": state["status"],
            "participants": participants,
            "started_at": state["started_at"],
            "last_message_at": state["last_message_at"],
            "closed_at": state.get("closed_at"),
            "closed_by": list(state["closed_by"]),
            "message_count": state["message_count"],
        }

    def list_conversations(
        self,
        participant: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        limit = min(max(1, limit), 1000)
        items: list[tuple[str, dict]] = []
        for conv_id, state in self._conversations.items():
            if participant is not None and participant not in state["participants"]:
                continue
            if status is not None and state["status"] != status:
                continue
            items.append((conv_id, state))
        items.sort(key=lambda kv: kv[1]["last_message_at"], reverse=True)
        return [
            {
                "conversation_id": cid,
                "kind": s["kind"],
                "status": s["status"],
                "started_at": s["started_at"],
                "last_message_at": s["last_message_at"],
                "message_count": s["message_count"],
            }
            for cid, s in items[:limit]
        ]
