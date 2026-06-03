from agent_agora.provisioning import manifest


def _ok():
    return {
        "version": 1,
        "spawn_dir": "C:/work/team",
        "server_url": "http://127.0.0.1:8420/mcp",
        "team": [
            {"id": "Coder1", "role": "coder", "description": "코딩", "allow": ["Reviewer1"]},
            {"id": "Reviewer1", "role": "reviewer", "description": "리뷰", "allow": ["*"]},
        ],
    }


def test_valid_manifest_passes_and_normalizes_star():
    m, errors = manifest.validate(_ok())
    assert errors == []
    # "*"는 ".*"로 정규화된다.
    assert m["team"][1]["allow"] == [".*"]
    assert m["team"][0]["allow"] == ["Reviewer1"]


def test_wrong_version_errors():
    data = _ok(); data["version"] = 2
    _, errors = manifest.validate(data)
    assert any("version" in e for e in errors)


def test_duplicate_id_errors():
    data = _ok(); data["team"][1]["id"] = "Coder1"
    _, errors = manifest.validate(data)
    assert any("중복" in e for e in errors)


def test_bad_id_format_errors():
    data = _ok(); data["team"][0]["id"] = "bad id!"
    _, errors = manifest.validate(data)
    assert any("형식" in e for e in errors)


def test_missing_required_key_errors():
    data = _ok(); del data["team"][0]["role"]
    _, errors = manifest.validate(data)
    assert any("필수 키" in e for e in errors)


def test_allow_to_unknown_literal_id_warns_not_errors():
    data = _ok(); data["team"][0]["allow"] = ["GhostWorker"]
    m, errors = manifest.validate(data)
    assert errors == []
    assert any("GhostWorker" in w for w in m["warnings"])


def test_server_launcher_defaults_true():
    m, errors = manifest.validate(_ok())
    assert errors == []
    assert m["server_launcher"] is True


def test_server_launcher_false_preserved_and_roundtrips():
    import json
    data = _ok()
    data["server_launcher"] = False
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["server_launcher"] is False
    out = json.loads(manifest.dumps(m))
    assert out["server_launcher"] is False


def test_run_all_defaults_true():
    m, errors = manifest.validate(_ok())
    assert errors == []
    assert m["run_all"] is True


def test_run_all_false_preserved():
    data = _ok()
    data["run_all"] = False
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["run_all"] is False


def test_persona_none_preserved():
    data = _ok()
    data["team"][0]["persona"] = "none"
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["team"][0]["persona"] == "none"
    assert m["team"][1].get("persona") is None   # 미지정은 None(role 매핑)


def test_persona_roundtrips_through_dumps():
    data = _ok()
    data["team"][0]["persona"] = "none"
    m, _ = manifest.validate(data)
    import json
    out = json.loads(manifest.dumps(m))
    assert out["team"][0]["persona"] == "none"
    assert "persona" not in out["team"][1]   # None은 직렬화에서 생략


def test_marketplace_defaults_to_github():
    m, errors = manifest.validate(_ok())
    assert errors == []
    assert m["marketplace"] == {"type": "github", "repo": manifest.DEFAULT_MARKETPLACE_REPO}


def test_marketplace_github_explicit():
    data = _ok()
    data["marketplace"] = {"type": "github", "repo": "owner/Repo"}
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["marketplace"] == {"type": "github", "repo": "owner/Repo"}


def test_marketplace_directory_explicit():
    data = _ok()
    data["marketplace"] = {"type": "directory", "path": "C:/repo/plugin"}
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["marketplace"] == {"type": "directory", "path": "C:/repo/plugin"}


def test_legacy_marketplace_path_maps_to_directory():
    data = _ok()
    data["marketplace_path"] = "C:/old/plugin"
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["marketplace"] == {"type": "directory", "path": "C:/old/plugin"}


def test_marketplace_bad_shape_errors():
    data = _ok()
    data["marketplace"] = {"type": "github"}   # repo 누락
    _, errors = manifest.validate(data)
    assert any("marketplace" in e for e in errors)


def test_allow_regex_pattern_passes_without_warning():
    data = _ok()
    data["team"][0]["allow"] = ["sp-.*"]
    data["team"][1]["allow"] = []
    m, errors = manifest.validate(data)
    assert errors == []
    assert m["warnings"] == []
