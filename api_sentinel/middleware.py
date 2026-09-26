"""
API Sentinel - Asynchronous FastAPI / ASGI Middleware
Intercepts every HTTP request/response pair and immediately streams the response back.
Offloads runtime data capture and validation to background tasks using asyncio.create_task.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Callable, Optional, Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .capture import (
    detect_auth_type,
    get_content_type,
    safe_parse_body,
    sanitize_headers,
    sanitize_query_params,
    sanitize_body,
)
from .diff_engine import APIDiffEngine, OpenAPISpecParser
from .reporter import SentinelReporter
from .runtime_data import RuntimeData
from .config import settings

logger = logging.getLogger("api_sentinel.middleware")


class APISentinelMiddleware(BaseHTTPMiddleware):
    """
    FastAPI / Starlette ASGI middleware for real-time runtime data collection
    and contract drift detection.
    """

    _DEFAULT_EXCLUSIONS: tuple[str, ...] = (
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
        "/health",
        "/metrics",
    )

    def __init__(
        self,
        app: ASGIApp,
        openapi_path: str = "openapi.yaml",
        enabled: bool = True,
        print_clean: bool = False,
        exclude_paths: Optional[Sequence[str]] = None,
        dashboard_url: Optional[str] = "http://127.0.0.1:8001",
    ) -> None:
        super().__init__(app)

        self.openapi_path = openapi_path
        self.enabled = enabled
        self.print_clean = print_clean
        self.dashboard_url = dashboard_url

        self.exclude_paths: tuple[str, ...] = self._DEFAULT_EXCLUSIONS + tuple(
            exclude_paths or ()
        )

        # Parse spec at startup
        self._parser = OpenAPISpecParser.from_file(openapi_path)
        self._diff_engine = APIDiffEngine(self._parser)
        self._reporter = SentinelReporter()

        logger.info(
            "APISentinelMiddleware initialised | spec=%s | enabled=%s | dashboard=%s",
            openapi_path,
            enabled,
            dashboard_url,
        )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and response, building RuntimeData and dispatching a background task.
        """
        if not self.enabled or self._is_excluded(request.url.path):
            return await call_next(request)

        # 1. Capture request body and metadata pre-execution
        try:
            request_body_bytes: bytes = await request.body()
        except Exception:
            logger.debug("APISentinelMiddleware: failed to buffer request body", exc_info=True)
            return await call_next(request)

        # Restore receive channel so downstream handlers can read body normally
        _cached_body = request_body_bytes

        async def _restore_receive() -> dict:
            return {"type": "http.request", "body": _cached_body, "more_body": False}

        request._receive = _restore_receive  # type: ignore[assignment]

        # Pre-capture request fields
        method = request.method
        endpoint = request.url.path
        query_parameters = dict(request.query_params)
        request_headers_raw = dict(request.headers)
        request_headers = sanitize_headers(request_headers_raw)
        
        # Detect auth type
        authentication_type = detect_auth_type(request_headers_raw, query_parameters)
        
        # Get content type
        request_content_type = get_content_type(request_headers_raw)
        request_body = safe_parse_body(_cached_body, request_content_type)

        # 2. Call upstream route handler
        response: Response = await call_next(request)

        # 3. Capture response body and metadata
        try:
            response_body_bytes = await self._buffer_response_body(response)
        except Exception:
            logger.debug("APISentinelMiddleware: failed to buffer response body", exc_info=True)
            return response

        # Post-capture response and routing fields
        path_parameters = dict(request.path_params)
        status_code = response.status_code
        response_headers_raw = dict(response.headers)
        response_headers = sanitize_headers(response_headers_raw)
        response_content_type = get_content_type(response_headers_raw)
        response_body = safe_parse_body(response_body_bytes, response_content_type)

        # Reconstruct response to send to client immediately
        headers = dict(response.headers)
        headers.pop("content-length", None)
        reconstructed = Response(
            content=response_body_bytes,
            status_code=status_code,
            headers=headers,
            media_type=response.media_type,
        )

        # 4. Construct RuntimeData
        runtime_data = RuntimeData(
            method=method,
            endpoint=endpoint,
            path_parameters=path_parameters,
            query_parameters=query_parameters,
            request_headers=request_headers,
            request_body=request_body,
            authentication_type=authentication_type,
            status_code=status_code,
            response_headers=response_headers,
            response_body=response_body,
        )

        # 5. Fire-and-forget background processing
        asyncio.create_task(
            self._process_captured_data(runtime_data),
            name=f"sentinel:capture:{method}:{endpoint}",
        )

        return reconstructed

    async def _process_captured_data(self, data: RuntimeData) -> None:
        """
        Background task to process the captured runtime data and update dashboard.
        """
        try:
            # Output structured capture information log
            logger.info(
                "Captured RuntimeData: method=%s, endpoint=%s, status_code=%d, auth=%s",
                data.method,
                data.endpoint,
                data.status_code,
                data.authentication_type,
            )

            # Validate against spec
            if self._diff_engine:
                op_match = self._parser.get_operation(data.endpoint, data.method)
                matched_path = op_match[0] if op_match else None
                
                issues = await self._diff_engine.analyze_payload_async(
                    method=data.method,
                    raw_path=data.endpoint,
                    matched_path=matched_path,
                    status_code=data.status_code,
                    query_params=data.query_parameters,
                    request_body=data.request_body,
                    response_body=data.response_body,
                    reporter=self._reporter,
                    print_clean=self.print_clean,
                )

                if self.dashboard_url:
                    await self._post_to_dashboard(data, matched_path, issues)
        except Exception:
            logger.error("Error in Sentinel capture background task", exc_info=True)

    async def _post_to_dashboard(self, data: RuntimeData, matched_path: Optional[str], issues: list) -> None:
        """Asynchronously posts single validation result to the dashboard."""
        if not self.dashboard_url:
            return
        try:
            from api_sentinel.validation_report import ValidationStatus
            from api_sentinel.diff_engine import DriftSeverity

            has_error = any(getattr(i, 'severity', None) == DriftSeverity.ERROR for i in issues)
            has_warning = any(getattr(i, 'severity', None) == DriftSeverity.WARNING for i in issues)

            if has_error:
                status = ValidationStatus.FAILED
                sev = DriftSeverity.ERROR
            elif has_warning:
                status = ValidationStatus.WARNING
                sev = DriftSeverity.WARNING
            else:
                status = ValidationStatus.PASSED
                sev = None

            raw_diffs = []
            for i in issues:
                raw_diffs.append({
                    "issue_type": i.issue_type.value if hasattr(i.issue_type, 'value') else str(i.issue_type),
                    "severity": i.severity.value if hasattr(i.severity, 'value') else str(i.severity),
                    "location": getattr(i, 'location', 'response_body'),
                    "message": getattr(i, 'message', ''),
                    "expected": getattr(i, 'expected', None),
                    "actual": sanitize_body(getattr(i, 'actual', None)),
                })

            op = self._parser.get_operation(data.endpoint, data.method)
            expected_schema = None
            if op:
                _, op_dict = op
                resp_info = op_dict.get("responses", {}).get(str(data.status_code), {})
                expected_schema = resp_info.get("content", {}).get("application/json", {}).get("schema")

            actual_schema = data.response_body if isinstance(data.response_body, (dict, list)) else {}
            masked_actual_schema = sanitize_body(actual_schema)

            payload = {
                "endpoint": matched_path or data.endpoint,
                "method": data.method.upper(),
                "status_code": data.status_code,
                "validation_status": status.value,
                "severity": sev.value if sev else "NONE",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "expected_schema": expected_schema,
                "actual_schema": masked_actual_schema,
                "differences": raw_diffs,
            }

            import urllib.request
            import json

            req_data = json.dumps(payload).encode("utf-8")
            url = f"{self.dashboard_url.rstrip('/')}/api/report/append"
            req = urllib.request.Request(
                url,
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            def _send():
                try:
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        pass
                except Exception:
                    pass

            await asyncio.to_thread(_send)
        except Exception:
            pass


    def _is_excluded(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.exclude_paths)

    @staticmethod
    async def _buffer_response_body(response: Response) -> bytes:
        chunks: list[bytes] = []
        body_iterator = getattr(response, "body_iterator", None)

        if body_iterator is not None:
            async for chunk in body_iterator:
                if isinstance(chunk, str):
                    chunks.append(chunk.encode("utf-8"))
                else:
                    chunks.append(chunk)
        else:
            raw = getattr(response, "body", b"")
            chunks.append(raw if isinstance(raw, bytes) else raw.encode("utf-8"))

        return b"".join(chunks)
