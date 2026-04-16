# tests/test_certs.py
from __future__ import annotations

from pathlib import Path

from agent_agora.certs import ensure_certs


class TestCerts:
    def test_creates_cert_and_key(self, tmp_path: Path) -> None:
        cert_path, key_path = ensure_certs(tmp_path)
        assert cert_path.exists()
        assert key_path.exists()
        assert cert_path.suffix == ".pem"
        assert key_path.suffix == ".pem"

    def test_reuses_existing_certs(self, tmp_path: Path) -> None:
        cert1, key1 = ensure_certs(tmp_path)
        content1 = cert1.read_bytes()
        cert2, key2 = ensure_certs(tmp_path)
        assert cert1 == cert2
        assert cert1.read_bytes() == content1

    def test_cert_is_valid_pem(self, tmp_path: Path) -> None:
        cert_path, _ = ensure_certs(tmp_path)
        content = cert_path.read_text()
        assert "BEGIN CERTIFICATE" in content
