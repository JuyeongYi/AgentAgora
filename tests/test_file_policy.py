"""FilePolicy — 워커별 r/w gitignore 패턴 권한."""
from __future__ import annotations

import json

import pytest

from agent_agora.errors import AgoraError
from agent_agora.files import FilePolicy

_POLICY = json.dumps({
    "workers": {
        "Coder1": {"r": ["*"], "w": ["*.py", "*.md", "!secret_*.py"]},
        "Reviewer1": {"r": ["*.md"], "w": []},
        ".*": {"r": ["*.txt"], "w": []},
    },
})


def test_inactive_allows_all():
    fp = FilePolicy()
    assert fp.active is False
    assert fp.can_upload("anyone", "x.exe") is True
    assert fp.can_download("anyone", "x.exe") is True


def test_worker_upload_patterns():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_upload("Coder1", "app.py") is True
    assert fp.can_upload("Coder1", "notes.md") is True
    assert fp.can_upload("Coder1", "secret_key.py") is False  # ! negation
    assert fp.can_upload("Coder1", "data.bin") is False


def test_worker_download_patterns():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_download("Coder1", "anything.bin") is True   # r=["*"]
    assert fp.can_download("Reviewer1", "doc.md") is True
    assert fp.can_download("Reviewer1", "app.py") is False     # r=["*.md"]


def test_dotstar_catch_all_for_unlisted():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_download("Ghost", "readme.txt") is True   # .* catch-all r
    assert fp.can_download("Ghost", "app.py") is False
    assert fp.can_upload("Ghost", "app.py") is False        # .* catch-all w=[]


def test_missing_dimension_asymmetric_default():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"X": {"w": ["*.md"]}}}))
    # r 누락 → ["*"] → 전체 허용
    assert fp.can_download("X", "anything.bin") is True
    # w 명시
    assert fp.can_upload("X", "a.md") is True
    fp.load_json(json.dumps({"workers": {"Y": {"r": ["*.md"]}}}))
    # w 누락 → [] → 전부 거부
    assert fp.can_upload("Y", "a.md") is False


def test_no_fallback_unlisted_unrestricted():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"X": {"r": [], "w": []}}}))
    assert fp.can_upload("Unlisted", "x.exe") is True
    assert fp.can_download("Unlisted", "x.exe") is True


def test_load_json_rejects_bad():
    fp = FilePolicy()
    with pytest.raises(AgoraError) as ei:
        fp.load_json("not json")
    assert ei.value.code == "file_policy_invalid"


def test_regex_worker_key_matches_group():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"coder-.*": {"r": ["*.py"], "w": ["*.py"]}}}))
    assert fp.can_upload("coder-1", "app.py") is True
    assert fp.can_upload("coder-2", "app.py") is True
    assert fp.can_download("coder-9", "lib.py") is True


def test_regex_worker_key_fullmatch_not_partial():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {"coder-.*": {"r": ["*.py"], "w": ["*.py"]}}}))
    # 'decoder'는 coder 그룹 아님 — 매칭 항목 없음 → 무제한
    assert fp.can_upload("decoder", "anything.exe") is True


def test_multi_match_unions_permission():
    fp = FilePolicy()
    fp.load_json(json.dumps({"workers": {
        "coder-1": {"r": ["*.md"], "w": []},
        "coder-.*": {"r": [], "w": ["*.py"]},
    }}))
    # coder-1은 두 항목 모두에 매칭 — 업로드는 넓은 항목이, 다운로드는 좁은 항목이 허용 (OR)
    assert fp.can_upload("coder-1", "app.py") is True
    assert fp.can_download("coder-1", "notes.md") is True


def test_load_json_rejects_invalid_regex_key():
    fp = FilePolicy()
    with pytest.raises(AgoraError) as ei:
        fp.load_json(json.dumps({"workers": {"*": {"r": [], "w": []}}}))
    assert ei.value.code == "file_policy_invalid"


def test_load_json_rejects_fallback_field():
    fp = FilePolicy()
    with pytest.raises(AgoraError) as ei:
        fp.load_json(json.dumps({"workers": {}, "fallback": {"r": ["*"], "w": []}}))
    assert ei.value.code == "file_policy_invalid"
