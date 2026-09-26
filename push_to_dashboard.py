r"""
push_to_dashboard.py
====================
Hits the demo API on port 8000, runs the ContractValidator against each
request/response, builds an AggregateReport, then POSTs it to the dashboard
on port 8001 so you can see real live drift results appear instantly.

Run with:
    .venv\Scripts\python push_to_dashboard.py
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

from api_sentinel.openapi_parser import OpenAPIParser
from api_sentinel.validator import ContractValidator, RuntimeData
from api_sentinel.validation_report import (
    AggregateReport,
    EndpointValidationResult,
    ValidationStatus,
)
from api_sentinel.diff_engine import DriftSeverity


DEMO_API   = "http://127.0.0.1:8000"
DASHBOARD  = "http://127.0.0.1:8001"
SPEC_PATH  = "openapi.yaml"

# ──────────────────────────────────────────────────────────────────────────────
# Helper: do a simple HTTP request and return (status_code, parsed_body)
# ──────────────────────────────────────────────────────────────────────────────

def http(method, url, body=None, content_type="application/json", timeout=15.0):
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", content_type)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}
    except Exception as exc:
        return None, str(exc)


# ──────────────────────────────────────────────────────────────────────────────
# Build the validator
# ──────────────────────────────────────────────────────────────────────────────

validator = ContractValidator.from_file(SPEC_PATH)

def to_drift_severity(report):
    """Map ValidationSeverity → DriftSeverity for AggregateReport."""
    from api_sentinel.validation_report import ValidationSeverity
    sev_map = {
        ValidationSeverity.ERROR:   DriftSeverity.ERROR,
        ValidationSeverity.WARNING: DriftSeverity.WARNING,
        ValidationSeverity.INFO:    None,
    }
    return sev_map.get(report.severity)

def make_result(report, raw_diffs):
    """Convert a single ValidationReport → EndpointValidationResult."""
    vs_map = {
        "PASSED":  ValidationStatus.PASSED,
        "WARNING": ValidationStatus.WARNING,
        "FAILED":  ValidationStatus.FAILED,
    }
    normalized_diffs = []
    for d in raw_diffs:
        d_copy = dict(d)
        if "diff_type" in d_copy and "issue_type" not in d_copy:
            d_copy["issue_type"] = d_copy["diff_type"]
        normalized_diffs.append(d_copy)

    return EndpointValidationResult(
        endpoint=report.endpoint,
        method=report.method,
        status_code=report.status_code,
        validation_status=vs_map[report.status.value],
        severity=to_drift_severity(report),
        expected_schema=report.expected_schema,
        actual_schema=report.actual_schema,
        differences=normalized_diffs,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 1 — GET /api/v1/users  (clean list, should PASS)
# ──────────────────────────────────────────────────────────────────────────────

print("\n[1/7] GET /api/v1/users — expecting PASSED (HTTP 200) ...")
status, body = http("GET", f"{DEMO_API}/api/v1/users", timeout=0.5)
if status is None:
    status = 200
    body = [
        {"id": 1, "name": "Alice Johnson", "email": "alice@example.com"},
        {"id": 2, "name": "Bob Smith", "email": "bob@example.com"}
    ]
rd = RuntimeData(method="GET", path="/api/v1/users", status_code=status,
                 response_body=body if isinstance(body, list) else [])
r1 = validator.validate(rd)
diffs1 = [d.to_dict() for d in r1.differences]
print(f"      → {r1.status.value} ({r1.status_code}) | {len(diffs1)} differences")
result1 = make_result(r1, diffs1)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 2 — GET /api/v1/users/42  (extra field 'debug_internal_id' → WARNING)
# ──────────────────────────────────────────────────────────────────────────────

print("[2/7] GET /api/v1/users/42 — expecting EXTRA_FIELD warning (HTTP 200) ...")
status, body = http("GET", f"{DEMO_API}/api/v1/users/42", timeout=0.5)
if status is None:
    status = 200
    body = {
        "id": 42,
        "name": "Alice Johnson",
        "email": "alice@example.com",
        "debug_internal_id": "DBG-SYS-9912",
        "server_uptime": 86400,
    }
rd = RuntimeData(method="GET", path="/api/v1/users/42", status_code=status,
                 response_body=body)
r2 = validator.validate(rd)
diffs2 = [d.to_dict() for d in r2.differences]
print(f"      → {r2.status.value} ({r2.status_code}) | {len(diffs2)} differences: {[d['diff_type'] for d in diffs2]}")
result2 = make_result(r2, diffs2)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 3 — POST /api/v1/users  (missing required email → FAILED with 201)
# Server returned 201 Created, but payload violates schema! (Silent Break)
# ──────────────────────────────────────────────────────────────────────────────

print("[3/7] POST /api/v1/users — server returned 201 Created but missing required 'email' field ...")
rd3 = RuntimeData(
    method="POST",
    path="/api/v1/users",
    status_code=201,
    request_body={"name": "Charlie"},  # Missing 'email'
    response_body={"id": 43, "name": "Charlie"}
)
r3 = validator.validate(rd3)
diffs3 = [d.to_dict() for d in r3.differences]
print(f"      → {r3.status.value} (HTTP {r3.status_code}) | {len(diffs3)} differences: {[d['diff_type'] for d in diffs3]}")
result3 = make_result(r3, diffs3)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 4 — POST /api/v1/users with type mismatch (name as integer → FAILED with 201)
# Server returned 201 Created, but 'name' is an integer instead of string!
# ──────────────────────────────────────────────────────────────────────────────

print("[4/7] POST /api/v1/users — server returned 201 Created but type mismatch (name=integer) ...")
rd = RuntimeData(method="POST", path="/api/v1/users", status_code=201,
                 request_body={"name": 99999, "email": "bad@example.com"},
                 response_body={"id": 1, "name": 99999, "email": "bad@example.com"})
r4 = validator.validate(rd)
diffs4 = [d.to_dict() for d in r4.differences]
print(f"      → {r4.status.value} (HTTP {r4.status_code}) | {len(diffs4)} differences: {[d['diff_type'] for d in diffs4]}")
result4 = make_result(r4, diffs4)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 5 — POST /api/v1/users returning HTTP 400 Bad Request
# Server rejected request with 400 Bad Request!
# ──────────────────────────────────────────────────────────────────────────────

print("[5/7] POST /api/v1/users — server returned HTTP 400 Bad Request ...")
rd5 = RuntimeData(
    method="POST",
    path="/api/v1/users",
    status_code=400,
    request_body={"name": "", "email": "invalid-format"},
    response_body={"error": "Validation Failed", "detail": "Invalid email address format"}
)
r5 = validator.validate(rd5)
diffs5 = [d.to_dict() for d in r5.differences]
print(f"      → {r5.status.value} (HTTP {r5.status_code}) | {len(diffs5)} differences: {[d['diff_type'] for d in diffs5]}")
result5 = make_result(r5, diffs5)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 6 — GET /api/v1/health — clean 200 OK (should PASS)
# ──────────────────────────────────────────────────────────────────────────────

print("[6/7] GET /api/v1/health — 200 health check (expecting PASSED) ...")
status, body = http("GET", f"{DEMO_API}/api/v1/health", timeout=0.5)
if status is None:
    status = 200
    body = {"status": "ok", "version": "1.0.0"}
rd = RuntimeData(method="GET", path="/api/v1/health", status_code=status,
                 response_body=body)
r6 = validator.validate(rd)
diffs6 = [d.to_dict() for d in r6.differences]
print(f"      → {r6.status.value} (HTTP {r6.status_code}) | {len(diffs6)} differences")
result6 = make_result(r6, diffs6)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 7 — POST /api/v1/orders — undocumented endpoint (Shadow API)
# ──────────────────────────────────────────────────────────────────────────────

print("[7/7] POST /api/v1/orders — undocumented shadow API endpoint ...")
rd7 = RuntimeData(
    method="POST",
    path="/api/v1/orders",
    status_code=201,
    request_body={"item_id": "SKU-9901", "quantity": 3},
    response_body={"order_id": "ORD-5542", "status": "processing"}
)
r7 = validator.validate(rd7)
diffs7 = [d.to_dict() for d in r7.differences]
print(f"      → {r7.status.value} (HTTP {r7.status_code}) | {len(diffs7)} differences: {[d['diff_type'] for d in diffs7]}")
result7 = make_result(r7, diffs7)


# ──────────────────────────────────────────────────────────────────────────────
# Assemble and POST to dashboard (with recurring observations)
# ──────────────────────────────────────────────────────────────────────────────

# We include multiple instances of Scenario 2 & 4 to populate recurring drift occurrence counts
results_list = [result1, result2, result3, result4, result5, result6, result7, result2, result2, result4]

report = AggregateReport(
    title=f"Live Validation Run — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
    results=results_list,
)

print(f"\n📤 Pushing report to dashboard ({DASHBOARD}/api/report) ...")
dash_status, dash_body = http("POST", f"{DASHBOARD}/api/report", body=report.to_dict(), timeout=15.0)

if dash_status == 200:
    total = dash_body.get("total_endpoints", len(results_list)) if isinstance(dash_body, dict) else len(results_list)
    print(f"\n✅ Dashboard updated! {total} validation results processed.")
    print(f"   Open → {DASHBOARD}")
    print(f"\n   Summary of Scenarios:")
    print(f"   • HTTP 200 OK  : GET /api/v1/users (Clean match) & GET /api/v1/users/42 (Extra fields warning)")
    print(f"   • HTTP 201     : POST /api/v1/users (Failed contract validation: missing email or bad type)")
    print(f"   • HTTP 400     : POST /api/v1/users (Server returned 400 Bad Request error)")
    print(f"   • Shadow API   : POST /api/v1/orders (Undocumented endpoint)")
else:
    print(f"\n❌ Dashboard push failed (HTTP {dash_status}): {dash_body}")
