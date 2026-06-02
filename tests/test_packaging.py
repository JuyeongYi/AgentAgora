"""패키징 회귀 — 빌드된 휠에 dashboard_static 에셋이 포함되는지 검증.

소스 트리엔 dashboard_static가 늘 존재하므로(test_dashboard_static.py 참고),
이 버그는 *빌드 산출물*(휠)을 봐야 재현된다. pyproject의 package-data 글롭이
dashboard_static/** 를 빠뜨리면 휠에서 CSS/JS/vendor가 누락되고, uv tool 등으로
설치한 콘솔 스크립트(agent-agora)에선 static_dir.exists()가 False가 되어
/dashboard/static/* 가 전부 404 → 대시보드가 스타일 없이 깨진다.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_built_wheel_includes_dashboard_static(tmp_path):
    """빌드된 휠 안에 dashboard_static의 css·js·vendor 에셋이 들어 있어야 한다."""
    uv = shutil.which("uv")
    if not uv:
        pytest.skip("uv가 PATH에 없어 휠 빌드 불가")

    out = tmp_path / "dist"
    res = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(out)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"휠 빌드 실패:\n{res.stdout}\n{res.stderr}"

    wheels = list(out.glob("agent_agora-*.whl"))
    assert wheels, f"휠이 생성되지 않음: {[p.name for p in out.iterdir()]}"

    with zipfile.ZipFile(wheels[0]) as zf:
        names = set(zf.namelist())

    required = [
        "agent_agora/dashboard/dashboard_static/css/dashboard.css",
        "agent_agora/dashboard/dashboard_static/js/login.js",
        "agent_agora/dashboard/dashboard_static/js/dashboard.js",
        "agent_agora/dashboard/dashboard_static/vendor/tabulator.min.js",
        "agent_agora/dashboard/dashboard_static/vendor/tabulator.min.css",
    ]
    missing = [r for r in required if r not in names]
    assert not missing, (
        "휠에 dashboard_static 에셋 누락: "
        f"{missing}\n"
        "pyproject.toml [tool.setuptools.package-data] 의 agent_agora 글롭에 "
        "'dashboard_static/**/*' 가 포함됐는지 확인."
    )
