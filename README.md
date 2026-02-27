# Merovingian

Cross-repository dependency intelligence for AI agents via MCP.

Merovingian maps cross-repo dependencies — API contracts, shared schemas, consumer relationships — and detects breaking changes before they propagate.

## Installation

```bash
pip install merovingian
pip install merovingian[mcp]  # with MCP server support
```

## Quick Start

```bash
# Register repositories
merovingian register user-service /path/to/user-service --type openapi
merovingian register billing-service /path/to/billing-service --type openapi

# Scan for contracts
merovingian scan user-service

# Register consumer relationships
merovingian add-consumer billing-service user-service GET /users/{id}

# Check for breaking changes
merovingian breaking user-service

# Full impact assessment
merovingian impact user-service

# View dependency graph
merovingian graph
```

## MCP Server

Add to your Claude Code configuration:

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

## License

MIT
