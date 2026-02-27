"""Tests for the contract scanner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from merovingian.config import ScannerConfig
from merovingian.core.scanner import (
    compute_spec_hash,
    scan_openapi,
    scan_pydantic_models,
    scan_repo,
)
from merovingian.models.contracts import Endpoint, RepoInfo
from merovingian.models.enums import ContractType

SAMPLE_OPENAPI = """\
openapi: "3.0.0"
info:
  title: User Service
  version: "1.0.0"
paths:
  /users:
    get:
      summary: List users
      responses:
        "200":
          content:
            application/json:
              schema:
                type: object
                properties:
                  users:
                    type: array
                required:
                  - users
    post:
      summary: Create user
      requestBody:
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateUser'
      responses:
        "201":
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
  /users/{id}:
    get:
      summary: Get user by ID
      responses:
        "200":
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: integer
        name:
          type: string
        email:
          type: string
      required:
        - id
        - name
    CreateUser:
      type: object
      properties:
        name:
          type: string
        email:
          type: string
      required:
        - name
"""

SAMPLE_PYDANTIC_SOURCE = '''\
from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    """Create a new user."""

    name: str
    email: str
    age: int = 0


class UserResponse(BaseModel):
    """User response model."""

    id: int
    name: str
    email: Optional[str] = None
'''


@pytest.fixture
def openapi_repo(tmp_path):
    """Create a repo with an OpenAPI spec."""
    (tmp_path / "openapi.yaml").write_text(SAMPLE_OPENAPI)
    return tmp_path


@pytest.fixture
def pydantic_repo(tmp_path):
    """Create a repo with Pydantic models."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "models.py").write_text(SAMPLE_PYDANTIC_SOURCE)
    return tmp_path


class TestOpenAPIScanning:
    def test_scan_finds_endpoints(self, openapi_repo):
        config = ScannerConfig()
        endpoints = scan_openapi(openapi_repo, config)
        assert len(endpoints) == 3

    def test_endpoint_methods(self, openapi_repo):
        config = ScannerConfig()
        endpoints = scan_openapi(openapi_repo, config)
        methods = {ep.method for ep in endpoints}
        assert methods == {"GET", "POST"}

    def test_endpoint_paths(self, openapi_repo):
        config = ScannerConfig()
        endpoints = scan_openapi(openapi_repo, config)
        paths = {ep.path for ep in endpoints}
        assert "/users" in paths
        assert "/users/{id}" in paths

    def test_ref_resolution(self, openapi_repo):
        config = ScannerConfig()
        endpoints = scan_openapi(openapi_repo, config)
        # POST /users should have request schema from $ref
        post = [ep for ep in endpoints if ep.method == "POST"][0]
        assert post.request_schema is not None
        schema = json.loads(post.request_schema)
        assert "name" in schema
        assert schema["name"]["required"] is True

    def test_response_schema(self, openapi_repo):
        config = ScannerConfig()
        endpoints = scan_openapi(openapi_repo, config)
        get_user = [ep for ep in endpoints if ep.path == "/users/{id}"][0]
        assert get_user.response_schema is not None
        schema = json.loads(get_user.response_schema)
        assert "id" in schema
        assert "name" in schema

    def test_summary(self, openapi_repo):
        config = ScannerConfig()
        endpoints = scan_openapi(openapi_repo, config)
        get_users = [ep for ep in endpoints if ep.path == "/users" and ep.method == "GET"][0]
        assert get_users.summary == "List users"

    def test_no_spec_file(self, tmp_path):
        config = ScannerConfig()
        endpoints = scan_openapi(tmp_path, config)
        assert endpoints == []

    def test_json_spec(self, tmp_path):
        import yaml as yaml_mod
        spec = yaml_mod.safe_load(SAMPLE_OPENAPI)
        (tmp_path / "openapi.json").write_text(json.dumps(spec))
        config = ScannerConfig()
        endpoints = scan_openapi(tmp_path, config)
        assert len(endpoints) == 3


class TestPydanticScanning:
    def test_scan_finds_models(self, pydantic_repo):
        config = ScannerConfig()
        endpoints = scan_pydantic_models(pydantic_repo, config)
        assert len(endpoints) == 2

    def test_method_is_schema(self, pydantic_repo):
        config = ScannerConfig()
        endpoints = scan_pydantic_models(pydantic_repo, config)
        assert all(ep.method == "SCHEMA" for ep in endpoints)

    def test_model_paths(self, pydantic_repo):
        config = ScannerConfig()
        endpoints = scan_pydantic_models(pydantic_repo, config)
        paths = {ep.path for ep in endpoints}
        assert any("UserCreate" in p for p in paths)
        assert any("UserResponse" in p for p in paths)

    def test_field_extraction(self, pydantic_repo):
        config = ScannerConfig()
        endpoints = scan_pydantic_models(pydantic_repo, config)
        create = [ep for ep in endpoints if "UserCreate" in ep.path][0]
        schema = json.loads(create.response_schema)
        assert "name" in schema
        assert schema["name"]["type"] == "str"
        assert schema["name"]["required"] is True
        assert "age" in schema
        assert schema["age"]["required"] is False

    def test_docstring_as_summary(self, pydantic_repo):
        config = ScannerConfig()
        endpoints = scan_pydantic_models(pydantic_repo, config)
        create = [ep for ep in endpoints if "UserCreate" in ep.path][0]
        assert create.summary == "Create a new user."

    def test_no_pydantic_files(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "empty.py").write_text("x = 1\n")
        config = ScannerConfig()
        endpoints = scan_pydantic_models(tmp_path, config)
        assert endpoints == []

    def test_syntax_error_file(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "bad.py").write_text("def foo(:\n")
        config = ScannerConfig()
        endpoints = scan_pydantic_models(tmp_path, config)
        assert endpoints == []


class TestScanRepo:
    def test_openapi_type(self, openapi_repo):
        config = ScannerConfig()
        repo = RepoInfo(name=openapi_repo.name, path=str(openapi_repo),
                        contract_type=ContractType.OPENAPI)
        endpoints = scan_repo(repo, config)
        assert len(endpoints) == 3

    def test_pydantic_type(self, pydantic_repo):
        config = ScannerConfig()
        repo = RepoInfo(name=pydantic_repo.name, path=str(pydantic_repo),
                        contract_type=ContractType.PYDANTIC)
        endpoints = scan_repo(repo, config)
        assert len(endpoints) == 2

    def test_auto_detect(self, tmp_path):
        """When no type specified, tries both scanners."""
        (tmp_path / "openapi.yaml").write_text(SAMPLE_OPENAPI)
        src = tmp_path / "src"
        src.mkdir()
        (src / "models.py").write_text(SAMPLE_PYDANTIC_SOURCE)

        config = ScannerConfig()
        repo = RepoInfo(name=tmp_path.name, path=str(tmp_path))
        endpoints = scan_repo(repo, config)
        assert len(endpoints) == 5  # 3 OpenAPI + 2 Pydantic

    def test_nonexistent_path(self):
        config = ScannerConfig()
        repo = RepoInfo(name="ghost", path="/nonexistent/path")
        endpoints = scan_repo(repo, config)
        assert endpoints == []


class TestSpecHash:
    def test_deterministic(self):
        eps = [
            Endpoint(repo_name="svc", method="GET", path="/a"),
            Endpoint(repo_name="svc", method="POST", path="/b"),
        ]
        h1 = compute_spec_hash(eps)
        h2 = compute_spec_hash(eps)
        assert h1 == h2

    def test_order_independent(self):
        eps1 = [
            Endpoint(repo_name="svc", method="GET", path="/a"),
            Endpoint(repo_name="svc", method="POST", path="/b"),
        ]
        eps2 = [
            Endpoint(repo_name="svc", method="POST", path="/b"),
            Endpoint(repo_name="svc", method="GET", path="/a"),
        ]
        assert compute_spec_hash(eps1) == compute_spec_hash(eps2)

    def test_different_endpoints_different_hash(self):
        eps1 = [Endpoint(repo_name="svc", method="GET", path="/a")]
        eps2 = [Endpoint(repo_name="svc", method="GET", path="/b")]
        assert compute_spec_hash(eps1) != compute_spec_hash(eps2)

    def test_sha256_length(self):
        eps = [Endpoint(repo_name="svc", method="GET", path="/a")]
        h = compute_spec_hash(eps)
        assert len(h) == 64
