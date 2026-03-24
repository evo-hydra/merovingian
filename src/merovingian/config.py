"""Layered configuration: .merovingian/config.toml -> MEROVINGIAN_* env vars -> defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def _default_data_dir() -> Path:
    """Return the default data directory (XDG-compliant).

    Merovingian is a cross-repo tool, so data lives in a user-level
    directory rather than per-project.

    Resolution order:
      1. $MEROVINGIAN_DATA_DIR (explicit override)
      2. $XDG_DATA_HOME/merovingian
      3. ~/.local/share/merovingian
    """
    env_dir = os.environ.get("MEROVINGIAN_DATA_DIR")
    if env_dir:
        return Path(env_dir)

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "merovingian"

    return Path.home() / ".local" / "share" / "merovingian"


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
    http_methods: tuple[str, ...] = (
        "get", "post", "put", "patch", "delete", "head", "options", "trace",
    )
    success_status_codes: tuple[str, ...] = (
        "200", "201", "202", "203", "204", "206",
    )
    json_content_types: tuple[str, ...] = (
        "application/json",
        "application/vnd.api+json",
        "text/json",
    )


@dataclass(frozen=True, slots=True)
class McpConfig:
    """MCP server configuration."""

    default_query_limit: int = 50
    audit_summary_max_length: int = 200


@dataclass(frozen=True, slots=True)
class MerovingianConfig:
    """Top-level configuration container."""

    data_dir: Path = field(default_factory=_default_data_dir)
    store: StoreConfig = field(default_factory=StoreConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    mcp: McpConfig = field(default_factory=McpConfig)

    @property
    def merovingian_dir(self) -> Path:
        """Directory for Merovingian data files."""
        return self.data_dir

    @property
    def db_path(self) -> Path:
        """Full path to the SQLite database."""
        return self.merovingian_dir / self.store.db_name

    @classmethod
    def load(cls, data_dir: Path | None = None) -> MerovingianConfig:
        """Load config: TOML file -> env vars -> defaults."""
        resolved_dir = Path(data_dir) if data_dir else _default_data_dir()
        toml_path = resolved_dir / "config.toml"

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

        return cls(data_dir=resolved_dir, store=store, scanner=scanner, mcp=mcp)
