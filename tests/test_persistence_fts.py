"""기능2 — FTS5 전문 검색 백엔드 (messages_fts + 트리거 + backfill + search_messages)."""
import datetime
import json

import pytest

from agent_agora.storage.persistence import Persistence, _SCHEMA_V1


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _insert_message(p, cmd, conv, source, target, text):
    now = _now()
    p.conn.execute(
        "INSERT OR IGNORE INTO conversations "
        "(conversation_id,status,started_at,last_message_at,kind) "
        "VALUES (?,'open',?,?,'direct')", (conv, now, now))
    p.conn.execute(
        "INSERT INTO messages (command_id,target,conversation_id,source,created_at,"
        "expect_result,delivered_as,dispatch_kind,closing,priority,priority_rank,"
        "payload,reply_only) VALUES (?,?,?,?,?,0,'primary','direct',0,'normal',1,?,0)",
        (cmd, target, conv, source, now,
         json.dumps({"text": text, "msgtype": "status_report"})))


def test_trigger_syncs_new_message_insert(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    if not p.fts_available:
        pytest.skip("FTS5 unavailable in this SQLite build")
    _insert_message(p, "c1", "conv1", "W1", "W2", "rocket engine telemetry")
    res = p.search_messages("engine")
    assert any(r["command_id"] == "c1" for r in res)
    r = next(r for r in res if r["command_id"] == "c1")
    assert r["conversation_id"] == "conv1" and r["source"] == "W1"
    assert r["target"] == "W2" and "created_at" in r and "snippet" in r


def test_migrate_creates_fts_and_backfills_existing_rows(tmp_path):
    # FTS/트리거가 없는 상태에서 먼저 메시지를 넣고, migrate()가 backfill하는지 검증.
    p = Persistence(tmp_path / "agora.db")
    p.conn.executescript(_SCHEMA_V1)  # base 테이블만 (FTS 없음)
    _insert_message(p, "old1", "convX", "Coder1", "Reviewer1", "legacy payload words")
    p.migrate()  # FTS 설정 + 기존 행 backfill
    if not p.fts_available:
        pytest.skip("FTS5 unavailable in this SQLite build")
    res = p.search_messages("legacy")
    assert any(r["command_id"] == "old1" for r in res)


def test_search_messages_empty_query_returns_empty(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    assert p.search_messages("") == []
    assert p.search_messages("   ") == []


def test_search_messages_special_chars_no_error(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    _insert_message(p, "c2", "conv2", "W1", "W2", "hello world")
    # 따옴표 불균형 — escape 안 하면 FTS5 구문 에러. 예외 없이 결과 반환해야.
    res = p.search_messages('hello "W1')
    assert isinstance(res, list)


def test_fts_indexes_values_not_keys(tmp_path):
    """본문 정밀화 — payload의 값만 인덱싱하고 키 이름(text/msgtype)은 매칭 안 함."""
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    if not p.fts_available:
        pytest.skip("FTS5 unavailable")
    _insert_message(p, "cv", "convV", "W1", "W2", "rocket engine")
    # 값은 매칭
    assert any(r["command_id"] == "cv" for r in p.search_messages("engine"))
    assert any(r["command_id"] == "cv" for r in p.search_messages("status_report"))  # msgtype의 값
    # 키 이름은 매칭 안 됨(노이즈 제거)
    assert not any(r["command_id"] == "cv" for r in p.search_messages("msgtype"))
    assert not any(r["command_id"] == "cv" for r in p.search_messages("text"))


def test_fts_trigger_survives_malformed_payload(tmp_path):
    """비-JSON payload가 와도 트리거가 dispatch 트랜잭션을 깨지 않는다(json_valid 가드)."""
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    if not p.fts_available:
        pytest.skip("FTS5 unavailable")
    now = _now()
    p.conn.execute(
        "INSERT OR IGNORE INTO conversations "
        "(conversation_id,status,started_at,last_message_at,kind) "
        "VALUES (?,'open',?,?,'direct')", ("convBad", now, now))
    # payload가 유효 JSON이 아님 — INSERT가 예외 없이 성공해야
    p.conn.execute(
        "INSERT INTO messages (command_id,target,conversation_id,source,created_at,"
        "expect_result,delivered_as,dispatch_kind,closing,priority,priority_rank,"
        "payload,reply_only) VALUES (?,?,?,?,?,0,'primary','direct',0,'normal',1,?,0)",
        ("cbad", "W2", "convBad", "W1", now, "not-json raw text scanword"))
    # 폴백으로 raw 텍스트가 인덱싱돼 검색 가능
    assert any(r["command_id"] == "cbad" for r in p.search_messages("scanword"))


def test_search_like_fallback_when_fts_unavailable(tmp_path):
    p = Persistence(tmp_path / "agora.db")
    p.migrate()
    _insert_message(p, "c3", "conv3", "W1", "W2", "fallback scan term")
    # FTS 비가용 가정 → LIKE 폴백 경로
    p._fts_available = False
    res = p.search_messages("fallback")
    assert any(r["command_id"] == "c3" for r in res)
