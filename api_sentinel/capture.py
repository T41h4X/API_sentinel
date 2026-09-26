"""
API Sentinel - Capture Utilities
Extracts runtime request/response details, detects auth, and sanitizes sensitive headers.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple, Sequence


def detect_auth_type(headers: Dict[str, str], query_params: Dict[str, Any]) -> str:
    """
    Detect the authentication type based on headers and query parameters.
    Returns: "Bearer Token", "API Key", or "Anonymous"
    """
    # Normalize headers to lowercase keys for comparison
    headers_lower = {k.lower(): v for k, v in headers.items()}
    
    auth_header = headers_lower.get("authorization", "").strip()
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            return "Bearer Token"
        if auth_header.lower().startswith("apikey "):
            return "API Key"

    # API Keys are commonly passed in x-api-key or api-key headers, or in query parameters
    has_api_key_header = any(
        k in headers_lower for k in ("x-api-key", "api-key", "apikey")
    )
    # Normalize query param keys to lowercase for case-insensitive comparison
    query_params_lower = {k.lower(): v for k, v in query_params.items()}
    has_api_key_query = any(
        k in query_params_lower for k in ("api_key", "apikey", "api-key")
    )
    
    if has_api_key_header or has_api_key_query:
        return "API Key"
        
    return "Anonymous"


def _get_effective_masked_fields(extra_masked_fields: Optional[Sequence[str]] = None) -> set[str]:
    """Combine default sensitive keys with configured and extra masked fields."""
    try:
        from api_sentinel.config import settings
        configured = set(f.lower() for f in settings.masked_fields)
    except Exception:
        configured = {"password", "token", "credit_card", "authorization", "secret", "api_key", "apikey"}
    
    if extra_masked_fields:
        configured.update(f.lower() for f in extra_masked_fields)
    return configured


def sanitize_headers(
    headers: Dict[str, str], extra_masked_fields: Optional[Sequence[str]] = None
) -> Dict[str, str]:
    """
    Mask or remove sensitive credential data from headers before storing.
    Redacts Authorization headers, cookies, API keys, etc.
    """
    sanitized = {}
    sensitive_keys = {
        "authorization", "cookie", "set-cookie", "x-api-key", "api-key", 
        "apikey", "proxy-authorization", "token", "session", "session-id"
    } | _get_effective_masked_fields(extra_masked_fields)
    
    for k, v in headers.items():
        k_lower = k.lower()
        if k_lower in sensitive_keys:
            if k_lower == "authorization":
                # Redact credential part, keep prefix/scheme if possible (e.g. Bearer [REDACTED])
                parts = v.strip().split(" ", 1)
                if len(parts) == 2:
                    sanitized[k] = f"{parts[0]} [REDACTED]"
                else:
                    sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
            
    return sanitized


def sanitize_query_params(
    query_params: Dict[str, Any], extra_masked_fields: Optional[Sequence[str]] = None
) -> Dict[str, Any]:
    """
    Mask sensitive credential values in query parameters.
    """
    masked_fields = _get_effective_masked_fields(extra_masked_fields)
    sanitized: Dict[str, Any] = {}
    for k, v in query_params.items():
        if k.lower() in masked_fields:
            sanitized[k] = "[REDACTED]"
        else:
            sanitized[k] = v
    return sanitized


def sanitize_body(
    data: Any, extra_masked_fields: Optional[Sequence[str]] = None
) -> Any:
    """
    Recursively sanitize dictionaries and lists to mask sensitive fields.
    """
    masked_fields = _get_effective_masked_fields(extra_masked_fields)

    def _mask(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: "[REDACTED]" if k.lower() in masked_fields else _mask(v)
                for k, v in obj.items()
            }
        elif isinstance(obj, list):
            return [_mask(item) for item in obj]
        return obj

    return _mask(data)


def get_content_type(headers: Dict[str, str]) -> str:
    """Extract Content-Type from headers, excluding charset or parameters."""
    headers_lower = {k.lower(): v for k, v in headers.items()}
    content_type_header = headers_lower.get("content-type", "")
    if content_type_header:
        return content_type_header.split(";")[0].strip()
    return "application/json"  # Default fallback


def safe_parse_body(body_bytes: bytes, content_type: str) -> Optional[Any]:
    """
    Safely decode and parse the request or response body.
    Supports parsing JSON bodies; returns raw string or None for other content types.
    """
    if not body_bytes:
        return None
        
    try:
        decoded = body_bytes.decode("utf-8")
        if "json" in content_type:
            return json.loads(decoded)
        return decoded
    except Exception:
        return None
