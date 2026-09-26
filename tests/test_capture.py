"""
Tests for api_sentinel.capture and middleware data collection
"""

import pytest
from api_sentinel.capture import (
    detect_auth_type,
    sanitize_headers,
    sanitize_query_params,
    sanitize_body,
    safe_parse_body,
    get_content_type,
)
from api_sentinel.runtime_data import RuntimeData


class TestRuntimeDataCollection:
    """Tests for the auth detection, header sanitization, and data capture structures."""

    def test_auth_type_bearer_token(self):
        """Detect Bearer Token from Authorization header."""
        headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"}
        query = {}
        assert detect_auth_type(headers, query) == "Bearer Token"

    def test_auth_type_api_key_header(self):
        """Detect API Key from x-api-key or api-key headers."""
        headers1 = {"x-api-key": "my-secret-key"}
        headers2 = {"api-key": "my-secret-key"}
        headers3 = {"apikey": "my-secret-key"}
        headers4 = {"Authorization": "ApiKey my-secret-key"}
        
        assert detect_auth_type(headers1, {}) == "API Key"
        assert detect_auth_type(headers2, {}) == "API Key"
        assert detect_auth_type(headers3, {}) == "API Key"
        assert detect_auth_type(headers4, {}) == "API Key"

    def test_auth_type_api_key_query(self):
        """Detect API Key from query parameters."""
        headers = {}
        query1 = {"api_key": "my-secret-key"}
        query2 = {"apikey": "my-secret-key"}
        query3 = {"api-key": "my-secret-key"}
        
        assert detect_auth_type(headers, query1) == "API Key"
        assert detect_auth_type(headers, query2) == "API Key"
        assert detect_auth_type(headers, query3) == "API Key"

    def test_auth_type_anonymous(self):
        """Fallback to Anonymous when no auth info is present."""
        headers = {"Content-Type": "application/json"}
        query = {"page": "1"}
        assert detect_auth_type(headers, query) == "Anonymous"

    def test_sanitize_headers(self):
        """Ensure sensitive headers are redacted, leaving others unchanged."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer mytoken123",
            "Cookie": "session=abcde12345",
            "x-api-key": "secretapikey",
            "X-Normal-Header": "normalvalue"
        }
        
        sanitized = sanitize_headers(headers)
        
        # Verify normal headers are kept intact
        assert sanitized["Content-Type"] == "application/json"
        assert sanitized["X-Normal-Header"] == "normalvalue"
        
        # Verify sensitive headers are redacted
        assert sanitized["Authorization"] == "Bearer [REDACTED]"
        assert sanitized["Cookie"] == "[REDACTED]"
        assert sanitized["x-api-key"] == "[REDACTED]"

    def test_get_content_type(self):
        """Verify extraction of media type from content-type header."""
        assert get_content_type({"Content-Type": "application/json; charset=utf-8"}) == "application/json"
        assert get_content_type({"content-type": "text/html"}) == "text/html"
        assert get_content_type({}) == "application/json"  # Fallback

    def test_safe_parse_body(self):
        """Verify body parsing for JSON and raw text."""
        # JSON parsing
        json_bytes = b'{"name": "Alice", "age": 30}'
        parsed_json = safe_parse_body(json_bytes, "application/json")
        assert parsed_json == {"name": "Alice", "age": 30}
        
        # Plain text
        text_bytes = b"hello world"
        parsed_text = safe_parse_body(text_bytes, "text/plain")
        assert parsed_text == "hello world"
        
        # Empty body
        assert safe_parse_body(b"", "application/json") is None

    def test_runtime_data_instantiation(self):
        """Test instantiation and dictionary serialization of RuntimeData."""
        data = RuntimeData(
            method="POST",
            endpoint="/api/v1/users",
            path_parameters={},
            query_parameters={"send_email": True},
            request_headers={"Authorization": "Bearer [REDACTED]"},
            request_body={"name": "Alice"},
            authentication_type="Bearer Token",
            status_code=201,
            response_headers={"Content-Type": "application/json"},
            response_body={"id": 1, "name": "Alice"}
        )
        
        assert data.method == "POST"
        assert data.authentication_type == "Bearer Token"
        assert data.timestamp is not None
        
        dict_data = data.to_dict()
        assert dict_data["method"] == "POST"
        assert dict_data["authentication_type"] == "Bearer Token"
        assert "timestamp" in dict_data

    def test_sanitize_query_params(self):
        """Ensure sensitive query parameters like token and api_key are redacted."""
        params = {
            "page": "1",
            "token": "my-secret-token",
            "api_key": "12345",
            "sort": "desc"
        }
        sanitized = sanitize_query_params(params)
        assert sanitized["page"] == "1"
        assert sanitized["sort"] == "desc"
        assert sanitized["token"] == "[REDACTED]"
        assert sanitized["api_key"] == "[REDACTED]"

    def test_sanitize_body_nested(self):
        """Ensure nested dictionary and list fields with sensitive keys are redacted."""
        body = {
            "user": {
                "name": "Bob",
                "password": "supersecretpassword",
                "nested": {
                    "token": "nested-token",
                    "safe_val": 42
                }
            },
            "keys": [
                {"secret": "hidden1", "label": "public1"},
                {"secret": "hidden2", "label": "public2"}
            ]
        }
        sanitized = sanitize_body(body)
        assert sanitized["user"]["name"] == "Bob"
        assert sanitized["user"]["password"] == "[REDACTED]"
        assert sanitized["user"]["nested"]["token"] == "[REDACTED]"
        assert sanitized["user"]["nested"]["safe_val"] == 42
        assert sanitized["keys"][0]["secret"] == "[REDACTED]"
        assert sanitized["keys"][0]["label"] == "public1"
        assert sanitized["keys"][1]["secret"] == "[REDACTED]"

