# Merovingian

Cross-repository dependency intelligence for AI agents via MCP.

Merovingian maps cross-repo dependencies — API contracts, shared schemas, consumer relationships — and detects breaking changes before they propagate. It answers: **"What else will break if I change this?"**

Part of the [EvoIntel](https://github.com/evo-hydra) stack (Anno, Sentinel, Seraph, Niobe, Merovingian).

## Features

- **OpenAPI spec parsing** — detects endpoints, request/response schemas, `$ref` resolution (recursive, with cycle detection), `allOf`/`anyOf`/`oneOf` support
- **Pydantic model extraction** — AST-parses Python files for BaseModel subclasses, no runtime imports needed
- **Direction-aware breaking change detection** — request vs response changes have opposite breaking semantics
- **Consumer registry** — track which services consume which endpoints
- **Dependency graph** — visualize producer/consumer relationships across repos
- **Contract versioning** — deterministic SHA256 spec hashing, version history with diff tracking
- **MCP interface** — 8 tools for AI agent consumption
- **CLI** — 12 commands via Typer with Rich output

## Installation

```bash
pip install merovingian
pip install merovingian[mcp]  # with MCP server support
```

## Quick Start

```bash
# Register repositories
merovingian register user-service /path/to/user-service --type openapi
merovingian register billing-service /path/to/billing-service

# Scan for contracts
merovingian scan user-service

# Register consumer relationships
merovingian add-consumer billing-service user-service GET /users/{id}

# Check for breaking changes
merovingian breaking user-service

# Full impact assessment with consumer mapping
merovingian impact user-service

# View dependency graph
merovingian graph

# Contract version history
merovingian contracts user-service
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `register <name> <path>` | Register a repository for scanning |
| `unregister <name>` | Remove a registered repository |
| `repos` | List all registered repositories |
| `scan <repo>` | Scan and update endpoints |
| `consumers` | List consumer relationships |
| `add-consumer <consumer> <producer> <method> <path>` | Register a consumer |
| `breaking <repo>` | Check for breaking changes |
| `impact <repo>` | Full impact assessment with consumer mapping |
| `contracts <repo>` | View contract version history |
| `graph` | View dependency graph |
| `feedback <target_id> <outcome>` | Submit feedback |
| `audit` | View audit log |

## MCP Server

Add to your Claude Code configuration (`~/.claude.json`):

```json
{
  "mcpServers": {
    "merovingian": {
      "command": "merovingian-mcp",
      "args": []
    }
  }
}
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `merovingian_register` | Register a repository for contract scanning |
| `merovingian_consumers` | List consumers of endpoints |
| `merovingian_breaking` | Check for breaking changes |
| `merovingian_impact` | Full impact assessment with consumer mapping |
| `merovingian_contracts` | List contract versions |
| `merovingian_graph` | Query the dependency graph |
| `merovingian_feedback` | Submit feedback on assessments |
| `merovingian_audit` | Query the audit log |

## Breaking Change Detection

Merovingian classifies changes with direction-aware logic:

**Breaking (blocks consumers):**
- Endpoint removed
- Required field added to request body
- Response field removed
- Field type changed (non-widening)
- Optional field made required in request

**Warning:**
- Type widened (e.g., `integer` → `number`)
- Required field made optional in response

**Info (non-breaking):**
- Endpoint added
- Optional field added to request
- Response field added
- Summary/description changed

## Configuration

Merovingian uses layered configuration: TOML file → environment variables → defaults.

Create `.merovingian/config.toml` in your project root:

```toml
[store]
db_name = "merovingian.db"

[scanner]
openapi_patterns = ["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"]
pydantic_scan_dirs = ["src", "app", "lib"]

[mcp]
default_query_limit = 50
```

## License

MIT
