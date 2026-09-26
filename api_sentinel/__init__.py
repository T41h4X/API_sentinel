"""
API Sentinel - Real-time OpenAPI Schema Drift Detection & Runtime Schema Generator
"""

__version__ = "0.1.3"

from api_sentinel.diff_engine import (
    APIDiffEngine,
    DriftIssue,
    DriftSeverity,
    DriftType,
    OpenAPISpecParser,
    load_openapi_spec,
    match_route,
)
from api_sentinel.cli import run_check
from api_sentinel.inferencer import SchemaInferencer, infer_json_schema, infer_multi_json_schema
from api_sentinel.middleware import APISentinelMiddleware
from api_sentinel.reporter import SentinelReporter
from api_sentinel.spec_validator import SpecValidationResult, validate_openapi_spec, validate_openapi_content
from api_sentinel.validation_report import (
    AggregateReport,
    EndpointValidationResult,
    ValidationReport,
    ValidationStatus,
)

__all__ = [
    "APISentinelMiddleware",
    "APIDiffEngine",
    "OpenAPISpecParser",
    "SchemaInferencer",
    "SentinelReporter",
    "AggregateReport",
    "ValidationReport",
    "EndpointValidationResult",
    "ValidationStatus",
    "DriftIssue",
    "DriftSeverity",
    "DriftType",
    # Standalone utility functions
    "infer_json_schema",
    "infer_multi_json_schema",
    "load_openapi_spec",
    "match_route",
    "validate_openapi_spec",
    "validate_openapi_content",
    "SpecValidationResult",
    "run_check",
]