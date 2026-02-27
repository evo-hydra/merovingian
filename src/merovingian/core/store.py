"""SQLite-backed store with WAL mode and FTS5 search."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from merovingian.models.contracts import (
    AuditEntry,
    ContractChange,
    Consumer,
    ContractVersion,
    Endpoint,
    Feedback,
    ImpactReport,
    RepoInfo,
)
from merovingian.models.enums import ContractType, FeedbackOutcome, TargetType

SCHEMA_VERSION = "1"

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS merovingian_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS repos (
    name           TEXT PRIMARY KEY,
    path           TEXT NOT NULL,
    contract_type  TEXT,
    registered_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS endpoints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_name       TEXT NOT NULL REFERENCES repos(name) ON DELETE CASCADE,
    method          TEXT NOT NULL,
    path            TEXT NOT NULL,
    summary         TEXT,
    request_schema  TEXT,
    response_schema TEXT,
    UNIQUE(repo_name, method, path)
);
CREATE INDEX IF NOT EXISTS idx_endpoints_repo ON endpoints(repo_name);

CREATE TABLE IF NOT EXISTS consumers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    consumer_repo   TEXT NOT NULL,
    producer_repo   TEXT NOT NULL,
    endpoint_method TEXT NOT NULL,
    endpoint_path   TEXT NOT NULL,
    registered_at   TEXT NOT NULL,
    UNIQUE(consumer_repo, producer_repo, endpoint_method, endpoint_path)
);
CREATE INDEX IF NOT EXISTS idx_consumers_producer ON consumers(producer_repo);
CREATE INDEX IF NOT EXISTS idx_consumers_consumer ON consumers(consumer_repo);

CREATE TABLE IF NOT EXISTS contract_versions (
    version_id  TEXT PRIMARY KEY,
    repo_name   TEXT NOT NULL REFERENCES repos(name) ON DELETE CASCADE,
    spec_hash   TEXT NOT NULL,
    endpoints   TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_repo_time ON contract_versions(repo_name, captured_at);

CREATE TABLE IF NOT EXISTS impact_reports (
    report_id          TEXT PRIMARY KEY,
    repo_name          TEXT NOT NULL REFERENCES repos(name) ON DELETE CASCADE,
    breaking_changes   TEXT NOT NULL,
    non_breaking_changes TEXT NOT NULL,
    consumer_count     INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_repo_time ON impact_reports(repo_name, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   TEXT NOT NULL,
    target_type TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name      TEXT NOT NULL,
    parameters     TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS endpoint_fts USING fts5(
    path, summary,
    content='endpoints',
    content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS endpoint_fts_ai AFTER INSERT ON endpoints BEGIN
    INSERT INTO endpoint_fts(rowid, path, summary)
    VALUES (new.id, new.path, COALESCE(new.summary, ''));
END;

CREATE TRIGGER IF NOT EXISTS endpoint_fts_ad AFTER DELETE ON endpoints BEGIN
    INSERT INTO endpoint_fts(endpoint_fts, rowid, path, summary)
    VALUES ('delete', old.id, old.path, COALESCE(old.summary, ''));
END;

CREATE TRIGGER IF NOT EXISTS endpoint_fts_au AFTER UPDATE ON endpoints BEGIN
    INSERT INTO endpoint_fts(endpoint_fts, rowid, path, summary)
    VALUES ('delete', old.id, old.path, COALESCE(old.summary, ''));
    INSERT INTO endpoint_fts(rowid, path, summary)
    VALUES (new.id, new.path, COALESCE(new.summary, ''));
END;
"""


def _iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 string."""
    return dt.isoformat()


def _parse_iso(s: str) -> datetime:
    """Parse ISO 8601 string to datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class MerovingianStore:
    """SQLite-backed store for cross-repository dependency intelligence."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> MerovingianStore:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        """Open the database connection and initialize schema."""
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._ensure_schema_version()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Guarded access to the connection."""
        if self._conn is None:
            raise RuntimeError("Store is not open")
        return self._conn

    def _ensure_schema_version(self) -> None:
        cur = self.conn.execute(
            "SELECT value FROM merovingian_meta WHERE key='schema_version'"
        )
        row = cur.fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO merovingian_meta(key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
            self.conn.commit()
        else:
            existing = row[0]
            if existing != SCHEMA_VERSION:
                self._run_migrations(existing)

    def _run_migrations(self, from_version: str) -> None:
        """Run schema migrations from from_version to SCHEMA_VERSION."""
        migrations: dict[str, str] = {
            # "1": "ALTER TABLE ...; UPDATE merovingian_meta SET value='2' WHERE key='schema_version';",
        }
        current = from_version
        while current != SCHEMA_VERSION:
            if current not in migrations:
                raise RuntimeError(
                    f"Cannot migrate database from schema v{current} to v{SCHEMA_VERSION}. "
                    f"No migration path found. Back up and recreate the database."
                )
            self.conn.executescript(migrations[current])
            self.conn.commit()
            cur = self.conn.execute(
                "SELECT value FROM merovingian_meta WHERE key='schema_version'"
            )
            row = cur.fetchone()
            current = row[0] if row else SCHEMA_VERSION

    # --- Meta ---

    def get_meta(self, key: str) -> str | None:
        """Get a metadata value by key."""
        cur = self.conn.execute(
            "SELECT value FROM merovingian_meta WHERE key=?", (key,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Set a metadata value."""
        self.conn.execute(
            "INSERT OR REPLACE INTO merovingian_meta(key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()

    # --- Repos ---

    def register_repo(self, repo: RepoInfo) -> None:
        """Register a repository."""
        self.conn.execute(
            "INSERT OR REPLACE INTO repos(name, path, contract_type, registered_at) "
            "VALUES (?, ?, ?, ?)",
            (repo.name, repo.path, repo.contract_type.value if repo.contract_type else None,
             _iso(repo.registered_at)),
        )
        self.conn.commit()

    def unregister_repo(self, name: str) -> bool:
        """Unregister a repository. Returns True if it existed."""
        cur = self.conn.execute("DELETE FROM repos WHERE name=?", (name,))
        self.conn.commit()
        return cur.rowcount > 0

    def get_repo(self, name: str) -> RepoInfo | None:
        """Get a repository by name."""
        cur = self.conn.execute(
            "SELECT name, path, contract_type, registered_at FROM repos WHERE name=?",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return RepoInfo(
            name=row[0],
            path=row[1],
            contract_type=ContractType(row[2]) if row[2] else None,
            registered_at=_parse_iso(row[3]),
        )

    def list_repos(self) -> list[RepoInfo]:
        """List all registered repositories."""
        cur = self.conn.execute(
            "SELECT name, path, contract_type, registered_at FROM repos ORDER BY name"
        )
        return [
            RepoInfo(
                name=r[0], path=r[1],
                contract_type=ContractType(r[2]) if r[2] else None,
                registered_at=_parse_iso(r[3]),
            )
            for r in cur.fetchall()
        ]

    # --- Endpoints ---

    def save_endpoints(self, endpoints: list[Endpoint]) -> int:
        """Bulk upsert endpoints. Returns count saved."""
        if not endpoints:
            return 0
        self.conn.executemany(
            "INSERT OR REPLACE INTO endpoints"
            "(repo_name, method, path, summary, request_schema, response_schema) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (ep.repo_name, ep.method, ep.path, ep.summary,
                 ep.request_schema, ep.response_schema)
                for ep in endpoints
            ],
        )
        self.conn.commit()
        return len(endpoints)

    def get_endpoints(self, repo_name: str) -> list[Endpoint]:
        """Get all endpoints for a repository."""
        cur = self.conn.execute(
            "SELECT repo_name, method, path, summary, request_schema, response_schema "
            "FROM endpoints WHERE repo_name=? ORDER BY method, path",
            (repo_name,),
        )
        return [
            Endpoint(
                repo_name=r[0], method=r[1], path=r[2],
                summary=r[3], request_schema=r[4], response_schema=r[5],
            )
            for r in cur.fetchall()
        ]

    def search_endpoints(self, query: str, limit: int = 50) -> list[Endpoint]:
        """Full-text search across endpoint paths and summaries."""
        cur = self.conn.execute(
            "SELECT e.repo_name, e.method, e.path, e.summary, "
            "e.request_schema, e.response_schema "
            "FROM endpoint_fts f JOIN endpoints e ON f.rowid = e.id "
            "WHERE endpoint_fts MATCH ? LIMIT ?",
            (query, limit),
        )
        return [
            Endpoint(
                repo_name=r[0], method=r[1], path=r[2],
                summary=r[3], request_schema=r[4], response_schema=r[5],
            )
            for r in cur.fetchall()
        ]

    def delete_endpoints(self, repo_name: str) -> int:
        """Delete all endpoints for a repository. Returns count deleted."""
        cur = self.conn.execute(
            "DELETE FROM endpoints WHERE repo_name=?", (repo_name,)
        )
        self.conn.commit()
        return cur.rowcount

    # --- Consumers ---

    def add_consumer(self, consumer: Consumer) -> None:
        """Register a consumer relationship."""
        self.conn.execute(
            "INSERT OR REPLACE INTO consumers"
            "(consumer_repo, producer_repo, endpoint_method, endpoint_path, registered_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (consumer.consumer_repo, consumer.producer_repo,
             consumer.endpoint_method, consumer.endpoint_path,
             _iso(consumer.registered_at)),
        )
        self.conn.commit()

    def remove_consumer(
        self, consumer_repo: str, producer_repo: str, method: str, path: str
    ) -> bool:
        """Remove a consumer relationship. Returns True if it existed."""
        cur = self.conn.execute(
            "DELETE FROM consumers WHERE consumer_repo=? AND producer_repo=? "
            "AND endpoint_method=? AND endpoint_path=?",
            (consumer_repo, producer_repo, method, path),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_consumers_of(self, producer_repo: str, method: str, path: str) -> list[Consumer]:
        """Get consumers of a specific endpoint."""
        cur = self.conn.execute(
            "SELECT consumer_repo, producer_repo, endpoint_method, endpoint_path, registered_at "
            "FROM consumers WHERE producer_repo=? AND endpoint_method=? AND endpoint_path=?",
            (producer_repo, method, path),
        )
        return [
            Consumer(
                consumer_repo=r[0], producer_repo=r[1],
                endpoint_method=r[2], endpoint_path=r[3],
                registered_at=_parse_iso(r[4]),
            )
            for r in cur.fetchall()
        ]

    def get_consumers_of_repo(self, producer_repo: str) -> list[Consumer]:
        """Get all consumers of any endpoint in a repository."""
        cur = self.conn.execute(
            "SELECT consumer_repo, producer_repo, endpoint_method, endpoint_path, registered_at "
            "FROM consumers WHERE producer_repo=? ORDER BY consumer_repo",
            (producer_repo,),
        )
        return [
            Consumer(
                consumer_repo=r[0], producer_repo=r[1],
                endpoint_method=r[2], endpoint_path=r[3],
                registered_at=_parse_iso(r[4]),
            )
            for r in cur.fetchall()
        ]

    # --- Contract Versions ---

    def save_version(self, version: ContractVersion) -> None:
        """Save a contract version snapshot."""
        endpoints_json = json.dumps([
            {
                "repo_name": ep.repo_name, "method": ep.method, "path": ep.path,
                "summary": ep.summary, "request_schema": ep.request_schema,
                "response_schema": ep.response_schema,
            }
            for ep in version.endpoints
        ])
        self.conn.execute(
            "INSERT INTO contract_versions(version_id, repo_name, spec_hash, endpoints, captured_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (version.version_id, version.repo_name, version.spec_hash,
             endpoints_json, _iso(version.captured_at)),
        )
        self.conn.commit()

    def get_latest_version(self, repo_name: str) -> ContractVersion | None:
        """Get the most recent contract version for a repository."""
        cur = self.conn.execute(
            "SELECT version_id, repo_name, spec_hash, endpoints, captured_at "
            "FROM contract_versions WHERE repo_name=? ORDER BY captured_at DESC LIMIT 1",
            (repo_name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_version(row)

    def list_versions(self, repo_name: str, limit: int = 50) -> list[ContractVersion]:
        """List contract versions for a repository, newest first."""
        cur = self.conn.execute(
            "SELECT version_id, repo_name, spec_hash, endpoints, captured_at "
            "FROM contract_versions WHERE repo_name=? ORDER BY captured_at DESC LIMIT ?",
            (repo_name, limit),
        )
        return [self._row_to_version(r) for r in cur.fetchall()]

    def _row_to_version(self, row: tuple) -> ContractVersion:
        endpoints_data = json.loads(row[3])
        endpoints = tuple(
            Endpoint(
                repo_name=ep["repo_name"], method=ep["method"], path=ep["path"],
                summary=ep.get("summary"), request_schema=ep.get("request_schema"),
                response_schema=ep.get("response_schema"),
            )
            for ep in endpoints_data
        )
        return ContractVersion(
            version_id=row[0], repo_name=row[1], spec_hash=row[2],
            endpoints=endpoints, captured_at=_parse_iso(row[4]),
        )

    # --- Impact Reports ---

    def save_report(self, report: ImpactReport) -> None:
        """Save an impact report."""
        breaking_json = json.dumps([
            {
                "repo_name": bc.repo_name, "endpoint_method": bc.endpoint_method,
                "endpoint_path": bc.endpoint_path, "change_kind": bc.change_kind.value,
                "severity": bc.severity.value, "description": bc.description,
                "affected_consumers": list(bc.affected_consumers),
            }
            for bc in report.breaking_changes
        ])
        non_breaking_json = json.dumps([
            {
                "repo_name": bc.repo_name, "endpoint_method": bc.endpoint_method,
                "endpoint_path": bc.endpoint_path, "change_kind": bc.change_kind.value,
                "severity": bc.severity.value, "description": bc.description,
                "affected_consumers": list(bc.affected_consumers),
            }
            for bc in report.non_breaking_changes
        ])
        self.conn.execute(
            "INSERT INTO impact_reports"
            "(report_id, repo_name, breaking_changes, non_breaking_changes, consumer_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (report.report_id, report.repo_name, breaking_json, non_breaking_json,
             report.consumer_count, _iso(report.created_at)),
        )
        self.conn.commit()

    def get_report(self, report_id: str) -> ImpactReport | None:
        """Get an impact report by ID."""
        cur = self.conn.execute(
            "SELECT report_id, repo_name, breaking_changes, non_breaking_changes, "
            "consumer_count, created_at FROM impact_reports WHERE report_id=?",
            (report_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_report(row)

    def list_reports(self, repo_name: str, limit: int = 50) -> list[ImpactReport]:
        """List impact reports for a repository, newest first."""
        cur = self.conn.execute(
            "SELECT report_id, repo_name, breaking_changes, non_breaking_changes, "
            "consumer_count, created_at FROM impact_reports "
            "WHERE repo_name=? ORDER BY created_at DESC LIMIT ?",
            (repo_name, limit),
        )
        return [self._row_to_report(r) for r in cur.fetchall()]

    def _row_to_report(self, row: tuple) -> ImpactReport:
        from merovingian.models.enums import ChangeKind, Severity

        def _parse_changes(data: list[dict]) -> tuple[ContractChange, ...]:
            return tuple(
                ContractChange(
                    repo_name=c["repo_name"],
                    endpoint_method=c["endpoint_method"],
                    endpoint_path=c["endpoint_path"],
                    change_kind=ChangeKind(c["change_kind"]),
                    severity=Severity(c["severity"]),
                    description=c["description"],
                    affected_consumers=tuple(c.get("affected_consumers", ())),
                )
                for c in data
            )

        breaking = _parse_changes(json.loads(row[2]))
        non_breaking = _parse_changes(json.loads(row[3]))
        return ImpactReport(
            report_id=row[0], repo_name=row[1],
            breaking_changes=breaking, non_breaking_changes=non_breaking,
            consumer_count=row[4], created_at=_parse_iso(row[5]),
        )

    # --- Feedback ---

    def save_feedback(self, fb: Feedback) -> None:
        """Save feedback."""
        self.conn.execute(
            "INSERT INTO feedback(target_id, target_type, outcome, context, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (fb.target_id, fb.target_type, fb.outcome, fb.context, _iso(fb.created_at)),
        )
        self.conn.commit()

    def list_feedback(self, limit: int = 50) -> list[Feedback]:
        """List recent feedback entries."""
        cur = self.conn.execute(
            "SELECT target_id, target_type, outcome, context, created_at "
            "FROM feedback ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [
            Feedback(
                target_id=r[0],
                target_type=TargetType(r[1]),
                outcome=FeedbackOutcome(r[2]),
                context=r[3],
                created_at=_parse_iso(r[4]),
            )
            for r in cur.fetchall()
        ]

    # --- Audit ---

    def log_audit(self, entry: AuditEntry) -> None:
        """Log an audit entry."""
        self.conn.execute(
            "INSERT INTO audit_log(tool_name, parameters, result_summary, created_at) "
            "VALUES (?, ?, ?, ?)",
            (entry.tool_name, entry.parameters, entry.result_summary, _iso(entry.created_at)),
        )
        self.conn.commit()

    def query_audit(
        self,
        tool_name: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """Query the audit log with optional filters."""
        clauses: list[str] = []
        params: list[str | int] = []
        if tool_name:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if since:
            clauses.append("created_at >= ?")
            params.append(_iso(since))

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self.conn.execute(
            f"SELECT tool_name, parameters, result_summary, created_at "
            f"FROM audit_log{where} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        )
        return [
            AuditEntry(
                tool_name=r[0], parameters=r[1],
                result_summary=r[2], created_at=_parse_iso(r[3]),
            )
            for r in cur.fetchall()
        ]
