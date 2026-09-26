"""Tests for api_sentinel.openapi_parser module."""

import os
import pytest
from api_sentinel.openapi_parser import (
    OpenAPIParser,
    extract_path_params,
    load_openapi_spec,
    match_route,
)


SPEC_PATH = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")


class TestLoadOpenAPISpec:
    """Tests for the load_openapi_spec function."""

    def test_load_yaml(self):
        spec = load_openapi_spec(SPEC_PATH)
        assert spec["openapi"] == "3.0.3"
        assert "paths" in spec
        assert "components" in spec

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_openapi_spec("nonexistent.yaml")


class TestMatchRoute:
    """Tests for the match_route function."""

    def test_exact_match(self):
        paths = ["/api/v1/users", "/api/v1/users/{id}"]
        assert match_route("/api/v1/users", paths) == "/api/v1/users"

    def test_parameterized_match(self):
        paths = ["/api/v1/users", "/api/v1/users/{id}"]
        assert match_route("/api/v1/users/42", paths) == "/api/v1/users/{id}"
        assert match_route("/api/v1/users/abc-def", paths) == "/api/v1/users/{id}"

    def test_no_match(self):
        paths = ["/api/v1/users", "/api/v1/users/{id}"]
        assert match_route("/api/v1/posts", paths) is None

    def test_trailing_slash(self):
        paths = ["/api/v1/users"]
        assert match_route("/api/v1/users/", paths) == "/api/v1/users"


class TestExtractPathParams:
    """Tests for the extract_path_params function."""

    def test_single_param(self):
        result = extract_path_params("/api/v1/users/42", "/api/v1/users/{id}")
        assert result == {"id": "42"}

    def test_multiple_params(self):
        result = extract_path_params(
            "/api/v1/users/42/posts/99",
            "/api/v1/users/{user_id}/posts/{post_id}",
        )
        assert result == {"user_id": "42", "post_id": "99"}

    def test_no_params(self):
        result = extract_path_params("/api/v1/users", "/api/v1/users")
        assert result == {}

    def test_uuid_param(self):
        result = extract_path_params(
            "/api/v1/users/550e8400-e29b-41d4-a716-446655440000",
            "/api/v1/users/{id}",
        )
        assert result == {"id": "550e8400-e29b-41d4-a716-446655440000"}


class TestOpenAPIParser:
    """Tests for the OpenAPIParser class."""

    @pytest.fixture
    def parser(self):
        return OpenAPIParser.from_file(SPEC_PATH)

    def test_from_file(self, parser):
        assert parser.paths is not None
        assert "/api/v1/users" in parser.paths
        assert "/api/v1/users/{id}" in parser.paths
        assert "/api/v1/auth/login" in parser.paths

    def test_match_route(self, parser):
        assert parser.match_route("/api/v1/users") == "/api/v1/users"
        assert parser.match_route("/api/v1/users/42") == "/api/v1/users/{id}"
        assert parser.match_route("/unknown") is None

    def test_get_operation(self, parser):
        result = parser.get_operation("/api/v1/users", "get")
        assert result is not None
        template, operation = result
        assert template == "/api/v1/users"
        assert "responses" in operation

    def test_get_operation_not_found(self, parser):
        assert parser.get_operation("/unknown", "get") is None
        assert parser.get_operation("/api/v1/users", "delete") is None

    def test_get_available_methods(self, parser):
        methods = parser.get_available_methods("/api/v1/users")
        assert "GET" in methods
        assert "POST" in methods

    def test_get_query_params(self, parser):
        params = parser.get_query_params("/api/v1/users", "get")
        param_names = [p["name"] for p in params]
        assert "role" in param_names
        assert "limit" in param_names

    def test_get_path_params(self, parser):
        params = parser.get_path_params("/api/v1/users/42", "get")
        param_names = [p["name"] for p in params]
        assert "id" in param_names

    def test_get_request_body_schema(self, parser):
        schema = parser.get_request_body_schema("/api/v1/users", "post")
        assert schema is not None
        assert schema["type"] == "object"
        assert "name" in schema.get("properties", {})
        assert "email" in schema.get("properties", {})

    def test_get_response_schema(self, parser):
        schema = parser.get_response_schema("/api/v1/users", "get", 200)
        assert schema is not None
        assert schema["type"] == "array"
        assert "items" in schema

    def test_get_response_schema_not_found(self, parser):
        schema = parser.get_response_schema("/api/v1/users", "get", 500)
        assert schema is None

    def test_get_response_status_codes(self, parser):
        codes = parser.get_response_status_codes("/api/v1/users", "get")
        assert "200" in codes

    def test_get_response_content_types(self, parser):
        types = parser.get_response_content_types("/api/v1/users", "get", 200)
        assert "application/json" in types

    def test_resolve_ref(self, parser):
        ref_schema = {"$ref": "#/components/schemas/UserResponse"}
        resolved = parser.resolve_ref(ref_schema)
        assert resolved["type"] == "object"
        assert "id" in resolved.get("properties", {})
        assert "name" in resolved.get("properties", {})

    def test_is_request_body_required(self, parser):
        assert parser.is_request_body_required("/api/v1/users", "post") is True
        assert parser.is_request_body_required("/api/v1/users", "get") is False

    def test_from_dict(self):
        spec_data = {
            "openapi": "3.0.3",
            "paths": {
                "/test": {
                    "get": {
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            },
            "components": {"schemas": {}},
        }
        parser = OpenAPIParser.from_dict(spec_data)
        assert parser.match_route("/test") == "/test"


class TestSpecValidator:
    """Tests for the standalone OpenAPI specification validator."""

    def test_validate_empty_string(self):
        from api_sentinel.spec_validator import validate_openapi_spec
        res = validate_openapi_spec("")
        assert not res.is_valid
        assert "cannot be empty" in res.error

    def test_validate_invalid_yaml(self):
        from api_sentinel.spec_validator import validate_openapi_spec
        res = validate_openapi_spec("openapi: 3.0.3\npaths: [unclosed")
        assert not res.is_valid
        assert "Invalid YAML/JSON syntax" in res.error

    def test_validate_missing_version(self):
        from api_sentinel.spec_validator import validate_openapi_spec
        res = validate_openapi_spec("info: {title: 'Test', version: '1.0'}\npaths: {}")
        assert not res.is_valid
        assert "Missing required OpenAPI version" in res.error

    def test_validate_valid_spec(self):
        from api_sentinel.spec_validator import validate_openapi_spec
        res = validate_openapi_spec(SPEC_PATH)
        assert res.is_valid
        assert res.summary["title"] == "Target API Specification"
        assert res.summary["paths_count"] > 0
        assert len(res.summary["endpoints"]) > 0
