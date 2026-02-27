"""Contract scanner — OpenAPI spec parser and Pydantic model AST extractor."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import yaml

from merovingian.config import ScannerConfig
from merovingian.models.contracts import Endpoint, RepoInfo
from merovingian.models.enums import ContractType


def scan_openapi(repo_path: Path, config: ScannerConfig) -> list[Endpoint]:
    """Scan a repository for OpenAPI spec files and extract endpoints."""
    repo_path = Path(repo_path)
    endpoints: list[Endpoint] = []

    for pattern in config.openapi_patterns:
        for spec_file in repo_path.rglob(pattern):
            endpoints.extend(_parse_openapi_file(spec_file, repo_path.name))

    return endpoints


def _parse_openapi_file(spec_file: Path, repo_name: str) -> list[Endpoint]:
    """Parse a single OpenAPI spec file into endpoints."""
    with open(spec_file) as f:
        spec = yaml.safe_load(f)

    if not isinstance(spec, dict):
        return []

    components_schemas = spec.get("components", {}).get("schemas", {})
    paths = spec.get("paths", {})
    endpoints: list[Endpoint] = []

    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            summary = operation.get("summary", "")
            request_schema = _extract_request_schema(operation, components_schemas)
            response_schema = _extract_response_schema(operation, components_schemas)

            endpoints.append(Endpoint(
                repo_name=repo_name,
                method=method.upper(),
                path=path_str,
                summary=summary or None,
                request_schema=json.dumps(request_schema) if request_schema else None,
                response_schema=json.dumps(response_schema) if response_schema else None,
            ))

    return endpoints


def _resolve_ref(
    ref: str, components_schemas: dict, _seen: set[str] | None = None
) -> dict:
    """Resolve a $ref to a schema dict, recursively with cycle detection."""
    if _seen is None:
        _seen = set()
    if ref in _seen:
        return {}  # cycle detected
    _seen.add(ref)

    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        return {}

    schema_name = ref[len(prefix):]
    resolved = components_schemas.get(schema_name, {})
    if not isinstance(resolved, dict):
        return {}

    # Recursively resolve nested $ref
    if "$ref" in resolved:
        return _resolve_ref(resolved["$ref"], components_schemas, _seen)

    return resolved


def _resolve_schema(schema: dict, components_schemas: dict) -> dict:
    """Resolve a schema that may use $ref, allOf, anyOf, or oneOf."""
    if "$ref" in schema:
        schema = _resolve_ref(schema["$ref"], components_schemas)

    # Merge allOf schemas (common pattern for inheritance/composition)
    if "allOf" in schema:
        merged: dict = {}
        merged_required: list[str] = []
        for sub_schema in schema["allOf"]:
            resolved = _resolve_schema(sub_schema, components_schemas)
            merged.update(resolved.get("properties", {}))
            merged_required.extend(resolved.get("required", []))
        return {
            "type": "object",
            "properties": merged,
            "required": merged_required,
        }

    # For anyOf/oneOf, take the first schema as representative
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema and schema[keyword]:
            return _resolve_schema(schema[keyword][0], components_schemas)

    return schema


def _schema_to_fields(schema: dict, components_schemas: dict) -> dict:
    """Convert an OpenAPI schema to a flat field dict: {name: {type, required, default}}."""
    schema = _resolve_schema(schema, components_schemas)

    if schema.get("type") != "object" and "properties" not in schema:
        return {}

    properties = schema.get("properties", {})
    required_fields = set(schema.get("required", []))
    fields: dict = {}

    for field_name, field_schema in properties.items():
        field_schema = _resolve_schema(field_schema, components_schemas)

        fields[field_name] = {
            "type": field_schema.get("type", "object"),
            "required": field_name in required_fields,
            "default": field_schema.get("default"),
        }

    return fields


def _extract_request_schema(operation: dict, components_schemas: dict) -> dict:
    """Extract request body schema from an operation."""
    request_body = operation.get("requestBody", {})
    if not isinstance(request_body, dict):
        return {}

    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})

    return _schema_to_fields(schema, components_schemas)


def _extract_response_schema(operation: dict, components_schemas: dict) -> dict:
    """Extract response schema from the primary success response."""
    responses = operation.get("responses", {})
    for status_code in ("200", "201", "202"):
        response = responses.get(status_code, {})
        if not isinstance(response, dict):
            continue
        content = response.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema", {})
        fields = _schema_to_fields(schema, components_schemas)
        if fields:
            return fields
    return {}


def scan_pydantic_models(repo_path: Path, config: ScannerConfig) -> list[Endpoint]:
    """Scan Python files for Pydantic BaseModel subclasses via AST."""
    repo_path = Path(repo_path)
    endpoints: list[Endpoint] = []

    for scan_dir in config.pydantic_scan_dirs:
        dir_path = repo_path / scan_dir
        if not dir_path.is_dir():
            continue
        for py_file in dir_path.rglob("*.py"):
            endpoints.extend(_parse_pydantic_file(py_file, repo_path))

    return endpoints


def _parse_pydantic_file(py_file: Path, repo_path: Path) -> list[Endpoint]:
    """Parse a Python file for BaseModel subclasses."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []

    relative = py_file.relative_to(repo_path)
    module_path = str(relative).replace("/", ".").replace("\\", ".").removesuffix(".py")
    repo_name = repo_path.name
    endpoints: list[Endpoint] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _inherits_basemodel(node):
            continue

        fields = _extract_class_fields(node)
        if not fields:
            continue

        schema_path = f"{module_path}.{node.name}"
        endpoints.append(Endpoint(
            repo_name=repo_name,
            method="SCHEMA",
            path=schema_path,
            summary=_get_docstring(node),
            response_schema=json.dumps(fields),
        ))

    return endpoints


def _inherits_basemodel(node: ast.ClassDef) -> bool:
    """Check if a class inherits from BaseModel (simple name check)."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "BaseModel":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
            return True
    return False


def _extract_class_fields(node: ast.ClassDef) -> dict:
    """Extract field names, types, and defaults from a class body."""
    fields: dict = {}
    for item in node.body:
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            field_name = item.target.id
            field_type = _annotation_to_str(item.annotation) if item.annotation else "Any"
            has_default = item.value is not None
            fields[field_name] = {
                "type": field_type,
                "required": not has_default,
                "default": None,
            }
    return fields


def _annotation_to_str(node: ast.expr) -> str:
    """Convert an AST annotation node to a string representation."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Attribute):
        value = _annotation_to_str(node.value)
        return f"{value}.{node.attr}"
    if isinstance(node, ast.Subscript):
        value = _annotation_to_str(node.value)
        slice_str = _annotation_to_str(node.slice)
        return f"{value}[{slice_str}]"
    if isinstance(node, ast.Tuple):
        parts = ", ".join(_annotation_to_str(e) for e in node.elts)
        return parts
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _annotation_to_str(node.left)
        right = _annotation_to_str(node.right)
        return f"{left} | {right}"
    return "Any"


def _get_docstring(node: ast.ClassDef) -> str | None:
    """Extract the docstring from a class definition."""
    if (
        node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    ):
        return node.body[0].value.value.strip()
    return None


def scan_repo(repo_info: RepoInfo, config: ScannerConfig) -> list[Endpoint]:
    """Scan a repository for contracts based on its type."""
    repo_path = Path(repo_info.path)
    if not repo_path.is_dir():
        return []

    if repo_info.contract_type == ContractType.OPENAPI:
        return scan_openapi(repo_path, config)
    elif repo_info.contract_type == ContractType.PYDANTIC:
        return scan_pydantic_models(repo_path, config)
    else:
        # Try both
        endpoints = scan_openapi(repo_path, config)
        endpoints.extend(scan_pydantic_models(repo_path, config))
        return endpoints


def compute_spec_hash(endpoints: list[Endpoint]) -> str:
    """Compute a deterministic SHA256 hash of sorted endpoint data."""
    canonical = sorted(
        (ep.method, ep.path, ep.request_schema or "", ep.response_schema or "")
        for ep in endpoints
    )
    data = json.dumps(canonical, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()
