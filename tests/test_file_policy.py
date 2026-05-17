"""FilePolicy — 워커별 r/w gitignore 패턴 권한."""
from __future__ import annotations

import json

import pytest

from agent_agora.errors import AgoraError
from agent_agora.file_policy import FilePolicy

_POLICY = json.dumps({
    "workers": {
        "Coder1": {"r": ["*"], "w": ["*.py", "*.md", "!secret_*.py"]},
        "Reviewer1": {"r": ["*.md"], "w": []},
    },
    "fallback": {"r": ["*.txt"], "w": []},
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


def test_fallback_for_unlisted():
    fp = FilePolicy()
    fp.load_json(_POLICY)
    assert fp.can_download("Ghost", "readme.txt") is True   # fallback r
    assert fp.can_download("Ghost", "app.py") is False
    assert fp.can_upload("Ghost", "app.py") is False        # fallback w=[]


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
