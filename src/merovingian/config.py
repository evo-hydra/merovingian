"""Layered configuration: .merovingian/config.toml -> MEROVINGIAN_* env vars -> defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(frozen=True, slots=True)
class StoreConfig:
    """SQLite store configuration."""

    db_name: str = "merovingian.db"


@dataclass(frozen=True, slots=True)
class ScannerConfig:
    """Contract scanner configuration."""

    openapi_patterns: tuple[str, ...] = (
        "openapi.yaml",
        "openapi.json",
        "swagger.yaml",
        "swagger.json",
    )
    pydantic_scan_dirs: tuple[str, ...] = ("src", "app", "lib")


@dataclass(frozen=True, slots=True)
class McpConfig:
    """MCP server configuration."""

    default_query_limit: int = 50


@dataclass(frozen=True, slots=True)
class MerovingianConfig:
    """Top-level configuration container."""

    project_path: Path = field(default_factory=Path.cwd)
    store: StoreConfig = field(default_factory=StoreConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    mcp: McpConfig = field(default_factory=McpConfig)

    @property
    def merovingian_dir(self) -> Path:
        """Directory for Merovingian data files."""
        return self.project_path / ".merovingian"

    @property
    def db_path(self) -> Path:
        """Full path to the SQLite database."""
        return self.merovingian_dir / self.store.db_name

    @classmethod
    def load(cls, project_path: Path | None = None) -> MerovingianConfig:
        """Load config: TOML file -> env vars -> defaults."""
        project = Path(project_path) if project_path else Path.cwd()
        toml_path = project / ".merovingian" / "config.toml"

        toml_data: dict = {}
        if toml_path.is_file():
            with open(toml_path, "rb") as f:
                toml_data = tomllib.load(f)

        store_data = toml_data.get("store", {})
        scanner_data = toml_data.get("scanner", {})
        mcp_data = toml_data.get("mcp", {})

        _store_defaults = StoreConfig()
        _scanner_defaults = ScannerConfig()
        _mcp_defaults = McpConfig()

        store = StoreConfig(
            db_name=os.environ.get(
                "MEROVINGIAN_DB_NAME",
                store_data.get("db_name", _store_defaults.db_name),
            ),
        )

        openapi_patterns = scanner_data.get(
            "openapi_patterns", _scanner_defaults.openapi_patterns
        )
        pydantic_scan_dirs = scanner_data.get(
            "pydantic_scan_dirs", _scanner_defaults.pydantic_scan_dirs
        )
        scanner = ScannerConfig(
            openapi_patterns=tuple(openapi_patterns),
            pydantic_scan_dirs=tuple(pydantic_scan_dirs),
        )

        mcp = McpConfig(
            default_query_limit=int(
                os.environ.get(
                    "MEROVINGIAN_DEFAULT_QUERY_LIMIT",
                    mcp_data.get("default_query_limit", _mcp_defaults.default_query_limit),
                )
            ),
        )

        return cls(project_path=project, store=store, scanner=scanner, mcp=mcp)
