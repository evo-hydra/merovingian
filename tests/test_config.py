"""Tests for configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from merovingian.config import MerovingianConfig, McpConfig, ScannerConfig, StoreConfig


class TestStoreConfig:
    def test_defaults(self):
        cfg = StoreConfig()
        assert cfg.db_name == "merovingian.db"

    def test_frozen(self):
        cfg = StoreConfig()
        with pytest.raises(AttributeError):
            cfg.db_name = "other.db"  # type: ignore[misc]


class TestScannerConfig:
    def test_defaults(self):
        cfg = ScannerConfig()
        assert "openapi.yaml" in cfg.openapi_patterns
        assert "src" in cfg.pydantic_scan_dirs

    def test_tuple_type(self):
        cfg = ScannerConfig()
        assert isinstance(cfg.openapi_patterns, tuple)
        assert isinstance(cfg.pydantic_scan_dirs, tuple)


class TestMcpConfig:
    def test_defaults(self):
        cfg = McpConfig()
        assert cfg.default_query_limit == 50


class TestMerovingianConfig:
    def test_defaults(self):
        cfg = MerovingianConfig()
        assert isinstance(cfg.store, StoreConfig)
        assert isinstance(cfg.scanner, ScannerConfig)
        assert isinstance(cfg.mcp, McpConfig)

    def test_merovingian_dir(self, tmp_path):
        cfg = MerovingianConfig(project_path=tmp_path)
        assert cfg.merovingian_dir == tmp_path / ".merovingian"

    def test_db_path(self, tmp_path):
        cfg = MerovingianConfig(project_path=tmp_path)
        assert cfg.db_path == tmp_path / ".merovingian" / "merovingian.db"

    def test_load_defaults(self, tmp_path):
        cfg = MerovingianConfig.load(tmp_path)
        assert cfg.project_path == tmp_path
        assert cfg.store.db_name == "merovingian.db"

    def test_load_from_toml(self, tmp_path):
        toml_dir = tmp_path / ".merovingian"
        toml_dir.mkdir()
        toml_file = toml_dir / "config.toml"
        toml_file.write_text(
            '[store]\ndb_name = "custom.db"\n\n'
            "[mcp]\ndefault_query_limit = 100\n"
        )

        cfg = MerovingianConfig.load(tmp_path)
        assert cfg.store.db_name == "custom.db"
        assert cfg.mcp.default_query_limit == 100

    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        toml_dir = tmp_path / ".merovingian"
        toml_dir.mkdir()
        toml_file = toml_dir / "config.toml"
        toml_file.write_text('[store]\ndb_name = "from_toml.db"\n')

        monkeypatch.setenv("MEROVINGIAN_DB_NAME", "from_env.db")

        cfg = MerovingianConfig.load(tmp_path)
        assert cfg.store.db_name == "from_env.db"

    def test_env_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MEROVINGIAN_DEFAULT_QUERY_LIMIT", "200")

        cfg = MerovingianConfig.load(tmp_path)
        assert cfg.mcp.default_query_limit == 200

    def test_scanner_config_from_toml(self, tmp_path):
        toml_dir = tmp_path / ".merovingian"
        toml_dir.mkdir()
        toml_file = toml_dir / "config.toml"
        toml_file.write_text(
            '[scanner]\nopenapi_patterns = ["api.yaml"]\npydantic_scan_dirs = ["models"]\n'
        )

        cfg = MerovingianConfig.load(tmp_path)
        assert cfg.scanner.openapi_patterns == ("api.yaml",)
        assert cfg.scanner.pydantic_scan_dirs == ("models",)
