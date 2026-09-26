"""
API Sentinel - Interactive Dashboard Application
FastAPI web application for visualizing ValidationReport objects, endpoint statuses, schema diffs, and exporting reports.
"""

import json
import os
import yaml
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any, List
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api_sentinel.validation_report import (
    AggregateReport,
    EndpointValidationResult,
    ValidationStatus,
)
from api_sentinel.diff_engine import DriftSeverity, DriftType
from api_sentinel.openapi_parser import OpenAPIParser
from api_sentinel.openapi_generator import generate_openapi_yaml, generate_openapi_spec
from api_sentinel.html_report import generate_html_report, export_json_report
from api_sentinel.spec_validator import validate_openapi_content, validate_openapi_spec

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from api_sentinel.database.session import init_db, AsyncSessionLocal
from api_sentinel.database.models import ValidationReportRecord, DifferenceRecord, AggregatedDriftRecord
from api_sentinel.config import settings


# Package and root directories
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PKG_DIR = os.path.dirname(CURRENT_DIR)
ROOT_DIR = os.path.dirname(PKG_DIR)

TEMPLATES_CANDIDATES = [
    os.path.join(PKG_DIR, "templates"),
    os.path.join(ROOT_DIR, "templates"),
    os.path.join(CURRENT_DIR, "templates"),
]
TEMPLATES_DIR = next((p for p in TEMPLATES_CANDIDATES if os.path.isdir(p)), os.path.join(ROOT_DIR, "templates"))

STATIC_CANDIDATES = [
    os.path.join(PKG_DIR, "static"),
    os.path.join(ROOT_DIR, "static"),
    os.path.join(CURRENT_DIR, "static"),
]
STATIC_DIR = next((p for p in STATIC_CANDIDATES if os.path.isdir(p)), os.path.join(ROOT_DIR, "static"))
BASE_DIR = ROOT_DIR if os.path.isdir(os.path.join(ROOT_DIR, "templates")) else PKG_DIR

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

from api_sentinel import __version__

app = FastAPI(
    title="API Sentinel Dashboard",
    description="Real-time OpenAPI schema drift & validation dashboard",
    version=__version__,
    lifespan=lifespan,
)

# Mount static files and templates
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


async def fetch_aggregate_report() -> AggregateReport:
    """Fetches the latest reports from the database and constructs an AggregateReport."""
    report = AggregateReport(title="API Sentinel Schema Validation Report")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ValidationReportRecord)
            .options(selectinload(ValidationReportRecord.differences))
            .order_by(ValidationReportRecord.timestamp.desc())
            .limit(100)
        )
        records = result.scalars().all()
        
        for r in records:
            diffs = [{
                "issue_type": d.issue_type,
                "severity": d.severity,
                "location": d.location,
                "message": d.message,
                "expected": d.expected,
                "actual": d.actual
            } for d in r.differences]
            
            report.results.append(EndpointValidationResult(
                endpoint=r.endpoint,
                method=r.method,
                status_code=r.status_code,
                validation_status=ValidationStatus(r.validation_status),
                severity=DriftSeverity(r.severity) if r.severity else None,
                timestamp=r.timestamp.isoformat() if r.timestamp else datetime.now(timezone.utc).isoformat(),
                expected_schema=r.expected_schema,
                actual_schema=r.actual_schema,
                differences=diffs
            ))
            
    return report


@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Renders the dashboard home page with summary metrics, endpoint table, and top recurring drifts."""
    report = await fetch_aggregate_report()
    top_drifts = []
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            select(AggregatedDriftRecord)
            .order_by(AggregatedDriftRecord.occurrence_count.desc())
            .limit(10)
        )
        top_drifts = res.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"report": report, "top_drifts": top_drifts},
    )


async def fetch_endpoint_catalog() -> List[Dict[str, Any]]:
    """
    Constructs a catalog merging OpenAPI specification endpoints with runtime traffic telemetry.
    """
    spec_path = get_active_spec_path()
    spec_endpoints: Dict[Tuple[str, str], Dict[str, Any]] = {}

    if os.path.exists(spec_path):
        try:
            parser = OpenAPIParser.from_file(spec_path)
            for path_template, path_item in parser.paths.items():
                if isinstance(path_item, dict):
                    for method_key, op_data in path_item.items():
                        m_upper = method_key.upper()
                        if m_upper in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}:
                            key = (m_upper, path_template)
                            spec_endpoints[key] = {
                                "method": m_upper,
                                "path": path_template,
                                "summary": op_data.get("summary", "") if isinstance(op_data, dict) else "",
                                "description": op_data.get("description", "") if isinstance(op_data, dict) else "",
                                "is_documented": True,
                                "parameters": op_data.get("parameters", []) if isinstance(op_data, dict) else [],
                                "responses": list(op_data.get("responses", {}).keys()) if isinstance(op_data, dict) else [],
                            }
        except Exception:
            pass

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ValidationReportRecord)
            .options(selectinload(ValidationReportRecord.differences))
            .order_by(ValidationReportRecord.timestamp.desc())
        )
        records = result.scalars().all()

    telemetry: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(lambda: {
        "total_calls": 0,
        "passed_calls": 0,
        "warning_calls": 0,
        "failed_calls": 0,
        "last_checked": None,
        "last_status": None,
        "last_status_code": 200,
        "latest_expected_schema": None,
        "latest_actual_schema": None,
        "violations": [],
    })

    for r in records:
        key = (r.method.upper(), r.endpoint)
        t = telemetry[key]
        t["total_calls"] += 1
        if r.validation_status == "PASSED":
            t["passed_calls"] += 1
        elif r.validation_status == "WARNING":
            t["warning_calls"] += 1
        else:
            t["failed_calls"] += 1

        if not t["last_checked"] and r.timestamp:
            t["last_checked"] = r.timestamp.isoformat()
            t["last_status"] = r.validation_status
            t["last_status_code"] = r.status_code
            t["latest_expected_schema"] = r.expected_schema
            t["latest_actual_schema"] = r.actual_schema

        for d in r.differences:
            if len(t["violations"]) < 20:
                t["violations"].append({
                    "issue_type": d.issue_type,
                    "severity": d.severity,
                    "location": d.location,
                    "message": d.message,
                    "expected": d.expected,
                    "actual": d.actual,
                })

    all_keys = set(spec_endpoints.keys()) | set(telemetry.keys())
    catalog = []

    for m_upper, path_str in sorted(all_keys, key=lambda x: (x[1], x[0])):
        spec_info = spec_endpoints.get((m_upper, path_str), {
            "method": m_upper,
            "path": path_str,
            "summary": "Undocumented endpoint observed at runtime",
            "description": "",
            "is_documented": False,
            "parameters": [],
            "responses": [],
        })
        t_info = telemetry.get((m_upper, path_str), {
            "total_calls": 0,
            "passed_calls": 0,
            "warning_calls": 0,
            "failed_calls": 0,
            "last_checked": None,
            "last_status": "UNTESTED",
            "last_status_code": None,
            "latest_expected_schema": None,
            "latest_actual_schema": None,
            "violations": [],
        })

        total = t_info["total_calls"]
        if total == 0:
            status = "UNTESTED"
            pass_rate = 0
        else:
            pass_rate = round((t_info["passed_calls"] / total) * 100)
            if t_info["failed_calls"] > 0:
                status = "FAILED"
            elif t_info["warning_calls"] > 0:
                status = "WARNING"
            else:
                status = "PASSED"

        catalog.append({
            "method": m_upper,
            "endpoint": path_str,
            "summary": spec_info["summary"],
            "description": spec_info["description"],
            "is_documented": spec_info["is_documented"],
            "status": status,
            "total_calls": total,
            "passed_calls": t_info["passed_calls"],
            "warning_calls": t_info["warning_calls"],
            "failed_calls": t_info["failed_calls"],
            "pass_rate": pass_rate,
            "last_checked": t_info["last_checked"],
            "last_status_code": t_info["last_status_code"],
            "parameters": spec_info["parameters"],
            "responses": spec_info["responses"],
            "violations": t_info["violations"],
            "expected_schema": t_info["latest_expected_schema"],
            "actual_schema": t_info["latest_actual_schema"],
        })

    return catalog


@app.get("/endpoints", response_class=HTMLResponse)
async def endpoints_explorer_page(request: Request):
    """Renders the interactive Endpoints Explorer page with catalog and status metrics."""
    catalog = await fetch_endpoint_catalog()
    return templates.TemplateResponse(
        request=request,
        name="endpoints_explorer.html",
        context={"catalog": catalog},
    )


@app.get("/api/endpoints")
async def get_endpoints_catalog():
    """Returns the endpoint catalog as JSON."""
    catalog = await fetch_endpoint_catalog()
    return JSONResponse(content={"endpoints": catalog, "total": len(catalog)})


@app.get("/endpoint/explore", response_class=HTMLResponse)
async def endpoint_explore(request: Request, method: str = "GET", endpoint: str = "/api/v1/users"):
    """
    Renders the endpoint-specific inspection view displaying spec schema,
    historical drift violations, and runtime telemetry.
    """
    catalog = await fetch_endpoint_catalog()
    target = None
    for ep in catalog:
        if ep["method"].upper() == method.upper() and ep["endpoint"] == endpoint:
            target = ep
            break

    if target:
        res = EndpointValidationResult(
            endpoint=target["endpoint"],
            method=target["method"],
            status_code=target.get("last_status_code") or 200,
            validation_status=ValidationStatus(target["status"]) if target["status"] in {"PASSED", "WARNING", "FAILED"} else ValidationStatus.PASSED,
            severity=DriftSeverity.ERROR if target["status"] == "FAILED" else (DriftSeverity.WARNING if target["status"] == "WARNING" else None),
            timestamp=target.get("last_checked") or datetime.now(timezone.utc).isoformat(),
            expected_schema=target.get("expected_schema") or {},
            actual_schema=target.get("actual_schema") or {},
            differences=target.get("violations", []),
        )
    else:
        res = EndpointValidationResult(
            endpoint=endpoint,
            method=method.upper(),
            status_code=200,
            validation_status=ValidationStatus.PASSED,
            severity=None,
        )

    expected_json = json.dumps(res.expected_schema or {}, indent=2)
    actual_json = json.dumps(res.actual_schema or {}, indent=2)

    return templates.TemplateResponse(
        request=request,
        name="endpoint_detail.html",
        context={
            "res": res,
            "expected_schema_json": expected_json,
            "actual_schema_json": actual_json,
        },
    )


@app.get("/endpoint/detail", response_class=HTMLResponse)
async def endpoint_detail(request: Request, index: int = 0):
    """Renders the detailed view for a single endpoint schema validation result."""
    report = await fetch_aggregate_report()
    results = report.results

    if 0 <= index < len(results):
        res = results[index]
    else:
        res = EndpointValidationResult(
            endpoint="/api/unknown",
            method="GET",
            status_code=404,
            validation_status=ValidationStatus.FAILED,
            severity=DriftSeverity.ERROR,
        )

    expected_json = json.dumps(res.expected_schema or {}, indent=2)
    actual_json = json.dumps(res.actual_schema or {}, indent=2)

    return templates.TemplateResponse(
        request=request,
        name="endpoint_detail.html",
        context={
            "res": res,
            "expected_schema_json": expected_json,
            "actual_schema_json": actual_json,
        },
    )


@app.get("/api/report")
async def get_report_json():
    """Returns the active ValidationReport as JSON."""
    report = await fetch_aggregate_report()
    return JSONResponse(content=report.to_dict())


@app.get("/api/drift/stats")
async def get_drift_statistics():
    """Returns aggregated drift statistics, including occurrence counts, timestamps, and recurring signatures."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AggregatedDriftRecord)
            .order_by(AggregatedDriftRecord.occurrence_count.desc(), AggregatedDriftRecord.last_seen.desc())
            .limit(50)
        )
        records = result.scalars().all()

        items = [
            {
                "id": r.id,
                "endpoint": r.endpoint,
                "method": r.method,
                "issue_type": r.issue_type,
                "location": r.location,
                "message": r.message,
                "severity": r.severity,
                "occurrence_count": r.occurrence_count,
                "first_seen": r.first_seen.isoformat() if r.first_seen else None,
                "last_seen": r.last_seen.isoformat() if r.last_seen else None,
                "sample_expected": r.sample_expected,
                "sample_actual": r.sample_actual,
            }
            for r in records
        ]

        total_occurrences = sum(r.occurrence_count for r in records)
        unique_endpoints = len(set(r.endpoint for r in records))

        return {
            "total_drift_occurrences": total_occurrences,
            "distinct_drift_signatures": len(records),
            "endpoints_affected": unique_endpoints,
            "top_recurring_drifts": items,
        }


@app.post("/api/report/append")
async def append_report_result(data: dict):
    """Appends an individual EndpointValidationResult to the database and updates aggregated statistics."""
    if settings.selective_persistence:
        if data.get("validation_status") == ValidationStatus.PASSED.value:
            return {"status": "skipped", "reason": "selective persistence enabled, ignored PASSED"}

    try:
        ts = None
        if data.get("timestamp"):
            try:
                ts = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            except Exception:
                ts = datetime.now(timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            record = ValidationReportRecord(
                endpoint=data["endpoint"],
                method=data["method"].upper(),
                status_code=data.get("status_code", 200),
                validation_status=data["validation_status"],
                severity=data.get("severity") if data.get("severity") != "NONE" else None,
                timestamp=ts,
                expected_schema=data.get("expected_schema"),
                actual_schema=data.get("actual_schema"),
            )
            for diff in data.get("differences", []):
                diff_issue_type = diff.get("issue_type") or diff.get("diff_type")
                if hasattr(diff_issue_type, "value"):
                    diff_issue_type = diff_issue_type.value
                record.differences.append(DifferenceRecord(
                    issue_type=diff_issue_type,
                    severity=diff.get("severity"),
                    location=diff.get("location"),
                    message=diff.get("message"),
                    expected=str(diff.get("expected")) if diff.get("expected") is not None else None,
                    actual=str(diff.get("actual")) if diff.get("actual") is not None else None
                ))
            
            session.add(record)

            # Update aggregated drift history & statistics
            for diff in data.get("differences", []):
                issue_type = diff.get("issue_type") or diff.get("diff_type") or "DRIFT"
                if hasattr(issue_type, "value"):
                    issue_type = issue_type.value
                loc = diff.get("location") or "response_body"
                msg = diff.get("message") or ""
                sev = diff.get("severity") or "WARNING"
                if hasattr(sev, "value"):
                    sev = sev.value
                exp = str(diff.get("expected")) if diff.get("expected") is not None else None
                act = str(diff.get("actual")) if diff.get("actual") is not None else None

                agg_q = await session.execute(
                    select(AggregatedDriftRecord).where(
                        AggregatedDriftRecord.endpoint == data["endpoint"],
                        AggregatedDriftRecord.method == data["method"].upper(),
                        AggregatedDriftRecord.issue_type == issue_type,
                        AggregatedDriftRecord.location == loc,
                        AggregatedDriftRecord.message == msg,
                    )
                )
                agg_record = agg_q.scalars().first()
                if agg_record:
                    agg_record.occurrence_count += 1
                    agg_record.last_seen = ts
                    agg_record.severity = sev
                    if exp is not None:
                        agg_record.sample_expected = exp
                    if act is not None:
                        agg_record.sample_actual = act
                else:
                    new_agg = AggregatedDriftRecord(
                        endpoint=data["endpoint"],
                        method=data["method"].upper(),
                        issue_type=issue_type,
                        location=loc,
                        message=msg,
                        severity=sev,
                        occurrence_count=1,
                        first_seen=ts,
                        last_seen=ts,
                        sample_expected=exp,
                        sample_actual=act,
                    )
                    session.add(new_agg)
            
            # Retention policy cleanup
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
            await session.execute(delete(ValidationReportRecord).where(ValidationReportRecord.timestamp < cutoff_date))
            
            await session.commit()

        return {"status": "success"}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})


@app.post("/api/report")
async def receive_aggregate_report(data: dict):
    """Receives a batch AggregateReport or single result dictionary and persists it."""
    results = data.get("results", [])
    if not results and "endpoint" in data:
        results = [data]
    count = 0
    for r in results:
        res = await append_report_result(r)
        if isinstance(res, dict) and res.get("status") == "success":
            count += 1
    return {
        "status": "success",
        "results_processed": count,
        "total_endpoints": len(results),
    }


@app.post("/api/report/clear")
async def clear_report():
    """Clears all validation results and aggregated drift statistics from the database."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(DifferenceRecord))
            await session.execute(delete(ValidationReportRecord))
            await session.execute(delete(AggregatedDriftRecord))
            await session.commit()
        return {"status": "cleared", "total_endpoints": 0}
    except Exception as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})



@app.get("/api/export/json")
async def export_json():
    """Downloads the current ValidationReport as a formatted JSON file."""
    report = await fetch_aggregate_report()
    json_str = report.to_json()
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="validation_report.json"'},
    )


@app.get("/api/export/html")
async def export_html():
    """Downloads the current ValidationReport as a standalone HTML file."""
    report = await fetch_aggregate_report()
    html_str = generate_html_report(report)
    return Response(
        content=html_str,
        media_type="text/html",
        headers={"Content-Disposition": 'attachment; filename="validation_report.html"'},
    )


# ===========================================================================
# OpenAPI Documentation Management Helpers & Endpoints
# ===========================================================================

def get_active_spec_path() -> str:
    """Returns the absolute path to the active OpenAPI specification file."""
    path = getattr(settings, "openapi_spec_path", "openapi.yaml")
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)




@app.get("/openapi-docs", response_class=HTMLResponse)
async def openapi_docs_page(request: Request):
    """Renders the OpenAPI Documentation & Specification Management page."""
    spec_path = get_active_spec_path()
    content = ""
    if os.path.exists(spec_path):
        try:
            with open(spec_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            content = f"# Error reading active specification: {exc}"

    is_valid, summary, error = validate_openapi_content(content)

    return templates.TemplateResponse(
        request=request,
        name="openapi_docs.html",
        context={
            "spec_content": content,
            "spec_path": getattr(settings, "openapi_spec_path", "openapi.yaml"),
            "is_valid": is_valid,
            "summary": summary,
            "error": error,
        },
    )


@app.get("/api/openapi/current")
async def get_current_openapi_spec():
    """Returns the active OpenAPI specification content and parsed summary."""
    spec_path = get_active_spec_path()
    if not os.path.exists(spec_path):
        return JSONResponse(
            status_code=404,
            content={"status": "error", "message": f"Specification file not found at {spec_path}"},
        )

    try:
        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Failed to read file: {str(exc)}"},
        )

    is_valid, summary, error = validate_openapi_content(content)
    fmt = "json" if spec_path.endswith(".json") else "yaml"

    return {
        "content": content,
        "format": fmt,
        "path": getattr(settings, "openapi_spec_path", "openapi.yaml"),
        "valid": is_valid,
        "summary": summary,
        "error": error,
    }


@app.post("/api/openapi/generate")
async def generate_openapi_from_form(payload: Dict[str, Any]):
    """
    Generates a standard OpenAPI 3.0.3 YAML document from structured form inputs
    and validates it using the existing validate_openapi_content function.
    """
    try:
        yaml_content = generate_openapi_yaml(payload)
        is_valid, summary, error = validate_openapi_content(yaml_content)
        return {
            "status": "success" if is_valid else "invalid",
            "yaml": yaml_content,
            "valid": is_valid,
            "summary": summary,
            "error": error,
        }
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "valid": False,
                "message": f"Failed to generate OpenAPI specification: {str(exc)}",
                "error": str(exc),
            },
        )


@app.post("/api/openapi/validate")
async def validate_openapi_spec(payload: Dict[str, Any]):
    """Validates an OpenAPI specification document without saving."""
    content = payload.get("content", "")
    is_valid, summary, error = validate_openapi_content(content)
    return {
        "valid": is_valid,
        "summary": summary,
        "error": error,
    }


@app.post("/api/openapi/save")
async def save_active_openapi_spec(payload: Dict[str, Any]):
    """Validates and persists the active OpenAPI specification file."""
    content = payload.get("content", "")
    is_valid, summary, error = validate_openapi_content(content)

    if not is_valid:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"Cannot save invalid OpenAPI specification: {error}",
                "error": error,
            },
        )

    spec_path = get_active_spec_path()
    try:
        # Write validated content to active specification file
        with open(spec_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "status": "saved",
            "path": getattr(settings, "openapi_spec_path", "openapi.yaml"),
            "message": "Active OpenAPI specification successfully updated and persisted.",
            "summary": summary,
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Failed to save specification file: {str(exc)}"},
        )

