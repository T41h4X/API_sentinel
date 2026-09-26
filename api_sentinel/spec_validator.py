"""
API Sentinel - OpenAPI Specification Validator
Validates OpenAPI specifications (YAML or JSON) for syntax, structure, completeness,
and schema validity before use in monitoring or persistence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from api_sentinel.openapi_parser import OpenAPIParser


@dataclass
class SpecValidationResult:
    """Represents the outcome of validating an OpenAPI specification."""
    is_valid: bool
    summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def validate_openapi_content(
    content_str: str,
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validates an OpenAPI YAML or JSON specification string.

    Returns
    -------
    tuple[bool, dict | None, str | None]
        (is_valid, summary_dict, error_message)
    """
    result = validate_openapi_spec(content_str)
    return result.is_valid, result.summary, result.error


def validate_openapi_spec(
    spec_source: Union[str, Dict[str, Any]],
) -> SpecValidationResult:
    """
    Comprehensive validator for OpenAPI specifications.
    Accepts raw YAML/JSON content string, a filesystem path, or an already-parsed dict.
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Resolve content or dictionary
    data: Any = None

    if isinstance(spec_source, dict):
        data = spec_source
    elif isinstance(spec_source, str):
        content_str = spec_source.strip()
        if not content_str:
            return SpecValidationResult(
                is_valid=False,
                error="OpenAPI specification content cannot be empty.",
                errors=["OpenAPI specification content cannot be empty."],
            )

        # Check if spec_source is a path to an existing file
        if os.path.exists(spec_source) and os.path.isfile(spec_source):
            try:
                with open(spec_source, "r", encoding="utf-8") as f:
                    content_str = f.read().strip()
                if not content_str:
                    return SpecValidationResult(
                        is_valid=False,
                        error=f"Specification file '{spec_source}' is empty.",
                        errors=[f"Specification file '{spec_source}' is empty."],
                    )
            except Exception as exc:
                return SpecValidationResult(
                    is_valid=False,
                    error=f"Failed to read file '{spec_source}': {exc}",
                    errors=[f"Failed to read file '{spec_source}': {exc}"],
                )

        # Parse YAML or JSON (yaml.safe_load parses both)
        try:
            data = yaml.safe_load(content_str)
        except Exception as exc:
            err_msg = f"Invalid YAML/JSON syntax: {str(exc)}"
            return SpecValidationResult(
                is_valid=False,
                error=err_msg,
                errors=[err_msg],
            )
    else:
        return SpecValidationResult(
            is_valid=False,
            error=f"Unsupported specification source type: {type(spec_source).__name__}",
            errors=[f"Unsupported specification source type: {type(spec_source).__name__}"],
        )

    if not isinstance(data, dict):
        return SpecValidationResult(
            is_valid=False,
            error="OpenAPI specification must be a valid JSON/YAML object/dictionary.",
            errors=["OpenAPI specification must be a valid JSON/YAML object/dictionary."],
        )

    # 2. Validate OpenAPI / Swagger version
    version_str = data.get("openapi") or data.get("swagger")
    if not version_str:
        errors.append("Missing required OpenAPI version field ('openapi' or 'swagger').")
    elif not isinstance(version_str, str):
        errors.append("OpenAPI version field ('openapi' or 'swagger') must be a string.")

    # 3. Validate Info object
    info = data.get("info")
    if not isinstance(info, dict):
        errors.append("Missing or invalid 'info' section in OpenAPI specification.")
        title = "Untitled API"
        api_version = "1.0.0"
    else:
        if not info.get("title"):
            warnings.append("Specification 'info.title' is missing or empty.")
        if not info.get("version"):
            warnings.append("Specification 'info.version' is missing or empty.")
        title = str(info.get("title", "Untitled API"))
        api_version = str(info.get("version", "1.0.0"))

    # 4. Validate Paths object
    paths = data.get("paths")
    if paths is None:
        errors.append("Missing required 'paths' section in OpenAPI specification.")
    elif not isinstance(paths, dict):
        errors.append("The 'paths' section must be an object/dictionary of endpoint routes.")

    if errors:
        return SpecValidationResult(
            is_valid=False,
            error=errors[0],
            errors=errors,
            warnings=warnings,
        )

    # 5. Route structure, method, and schema reference check via OpenAPIParser
    endpoints_summary: List[Dict[str, Any]] = []
    valid_methods = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}

    try:
        parser = OpenAPIParser.from_dict(data)

        for path_template, path_item in parser.paths.items():
            if not isinstance(path_template, str) or not path_template.startswith("/"):
                warnings.append(f"Path '{path_template}' should begin with a forward slash '/'.")

            if isinstance(path_item, dict):
                methods = [
                    m.upper()
                    for m in path_item.keys()
                    if m.lower() in valid_methods
                ]
                endpoints_summary.append({
                    "path": path_template,
                    "methods": methods,
                    "summary": path_item.get("summary", ""),
                })
            else:
                warnings.append(f"Path item for '{path_template}' is not a valid object.")

        # Check component schemas
        components = data.get("components", {})
        schemas = components.get("schemas", {}) if isinstance(components, dict) else {}

        summary = {
            "title": title,
            "version": api_version,
            "openapi_version": str(version_str),
            "description": info.get("description", "") if isinstance(info, dict) else "",
            "paths_count": len(paths) if isinstance(paths, dict) else 0,
            "endpoints": endpoints_summary,
            "schemas_count": len(schemas) if isinstance(schemas, dict) else 0,
        }

        return SpecValidationResult(
            is_valid=True,
            summary=summary,
            error=None,
            errors=[],
            warnings=warnings,
        )

    except Exception as exc:
        err_msg = f"OpenAPI schema structure error: {str(exc)}"
        return SpecValidationResult(
            is_valid=False,
            error=err_msg,
            errors=[err_msg],
            warnings=warnings,
        )
