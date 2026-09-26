"""
Unit & Integration Tests for API Sentinel - Task 3 Dashboard & Reporting Layer
"""

import json
import os
import pytest
from fastapi.testclient import TestClient

from api_sentinel.validation_report import (
    AggregateReport,
    EndpointValidationResult,
    ValidationStatus,
)
from api_sentinel.diff_engine import DriftSeverity, DriftType
from api_sentinel.html_report import generate_html_report, export_json_report
from api_sentinel.dashboard.app import app
from api_sentinel.config import settings


@pytest.fixture
def sample_report() -> AggregateReport:
    return AggregateReport(
        title="Test Validation Report",
        results=[
            EndpointValidationResult(
                endpoint="/api/v1/test_pass",
                method="GET",
                status_code=200,
                validation_status=ValidationStatus.PASSED,
                severity=None,
                expected_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                actual_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                differences=[],
            ),
            EndpointValidationResult(
                endpoint="/api/v1/test_warn",
                method="POST",
                status_code=201,
                validation_status=ValidationStatus.WARNING,
                severity=DriftSeverity.WARNING,
                expected_schema={"type": "object", "properties": {"id": {"type": "integer"}}},
                actual_schema={"type": "object", "properties": {"id": {"type": "integer"}, "warn": {"type": "string"}}},
                differences=[
                    {
                        "issue_type": DriftType.EXTRA_FIELD.value,
                        "severity": DriftSeverity.WARNING.value,
                        "location": "response_body",
                        "message": "Extra field warn",
                    }
                ],
            ),
            EndpointValidationResult(
                endpoint="/api/v1/test_fail",
                method="DELETE",
                status_code=500,
                validation_status=ValidationStatus.FAILED,
                severity=DriftSeverity.ERROR,
                expected_schema={"type": "object", "properties": {"status": {"type": "string"}}},
                actual_schema={"type": "object"},
                differences=[
                    {
                        "issue_type": DriftType.MISSING_REQUIRED_FIELD.value,
                        "severity": DriftSeverity.ERROR.value,
                        "location": "response_body",
                        "message": "Missing field status",
                    }
                ],
            ),
        ],
    )


def test_validation_report_metrics(sample_report: AggregateReport):
    assert sample_report.total_endpoints == 3
    assert sample_report.passed_endpoints == 1
    assert sample_report.warning_count == 1
    assert sample_report.failed_endpoints == 1

    report_dict = sample_report.to_dict()
    assert report_dict["summary"]["total_endpoints"] == 3
    assert report_dict["summary"]["passed_endpoints"] == 1
    assert report_dict["summary"]["warning_count"] == 1
    assert report_dict["summary"]["failed_endpoints"] == 1


def test_validation_report_json_serialization(sample_report: AggregateReport):
    json_str = sample_report.to_json()
    reconstructed = AggregateReport.from_json(json_str)

    assert reconstructed.title == sample_report.title
    assert reconstructed.total_endpoints == sample_report.total_endpoints
    assert reconstructed.passed_endpoints == sample_report.passed_endpoints
    assert reconstructed.results[0].endpoint == "/api/v1/test_pass"
    assert reconstructed.results[1].validation_status == ValidationStatus.WARNING
    assert reconstructed.results[2].severity == DriftSeverity.ERROR


def test_html_report_generator(sample_report: AggregateReport, tmp_path):
    output_html_path = os.path.join(tmp_path, "report.html")
    html_content = generate_html_report(sample_report, output_path=output_html_path)

    assert "<!DOCTYPE html>" in html_content
    assert "API Sentinel" in html_content
    assert "/api/v1/test_pass" in html_content
    assert "/api/v1/test_fail" in html_content
    assert os.path.exists(output_html_path)

    with open(output_html_path, "r", encoding="utf-8") as f:
        saved_html = f.read()
    assert saved_html == html_content


def test_json_report_exporter(sample_report: AggregateReport, tmp_path):
    output_json_path = os.path.join(tmp_path, "report.json")
    json_content = export_json_report(sample_report, output_path=output_json_path)

    assert os.path.exists(output_json_path)
    loaded_data = json.loads(json_content)
    assert loaded_data["summary"]["total_endpoints"] == 3


def test_dashboard_fastapi_endpoints(sample_report: AggregateReport):
    with TestClient(app) as client:
        # Clear any preexisting test entries in the DB
        client.post("/api/report/clear")

        # Populate with sample_report items
        for res in sample_report.results:
            client.post(
                "/api/report/append",
                json={
                    "endpoint": res.endpoint,
                    "method": res.method,
                    "status_code": res.status_code,
                    "validation_status": res.validation_status.value,
                    "severity": res.severity.value if res.severity else None,
                    "expected_schema": res.expected_schema,
                    "actual_schema": res.actual_schema,
                    "differences": res.differences,
                },
            )

        # Test Dashboard Home
        resp_home = client.get("/")
        assert resp_home.status_code == 200
        assert "API Sentinel" in resp_home.text
        assert "/api/v1/test_pass" in resp_home.text

        # Test Endpoint Detail Page
        resp_detail = client.get("/endpoint/detail?index=1")
        assert resp_detail.status_code == 200
        assert "/api/v1/test_warn" in resp_detail.text
        assert "Extra field warn" in resp_detail.text

        # Test API Get Report
        resp_api = client.get("/api/report")
        assert resp_api.status_code == 200
        data = resp_api.json()
        assert data["summary"]["total_endpoints"] == 3

        # Test API Export JSON
        resp_export_json = client.get("/api/export/json")
        assert resp_export_json.status_code == 200
        assert "attachment; filename=\"validation_report.json\"" in resp_export_json.headers["content-disposition"]
        loaded_exported = json.loads(resp_export_json.content)
        assert loaded_exported["summary"]["total_endpoints"] == 3

        # Test API Export HTML
        resp_export_html = client.get("/api/export/html")
        assert resp_export_html.status_code == 200
        assert "attachment; filename=\"validation_report.html\"" in resp_export_html.headers["content-disposition"]
        assert "<!DOCTYPE html>" in resp_export_html.text

        # Test API Append Result
        append_data = {
            "endpoint": "/api/v1/live_stream",
            "method": "POST",
            "status_code": 200,
            "validation_status": "WARNING",
            "severity": "WARNING",
            "differences": [{"issue_type": "EXTRA_FIELD", "message": "Live drift detected"}],
        }
        resp_append = client.post("/api/report/append", json=append_data)
        assert resp_append.status_code == 200
        assert resp_append.json()["status"] == "success"

        # Verify appended record appears in latest report
        resp_after_append = client.get("/api/report")
        data_after = resp_after_append.json()
        assert data_after["summary"]["total_endpoints"] == 4
        assert data_after["results"][0]["endpoint"] == "/api/v1/live_stream"

        # Test Selective Persistence: ignores PASSED when enabled
        original_selective = settings.selective_persistence
        try:
            settings.selective_persistence = True
            passed_data = {
                "endpoint": "/api/v1/ignore_me",
                "method": "GET",
                "status_code": 200,
                "validation_status": "PASSED",
                "differences": [],
            }
            resp_skipped = client.post("/api/report/append", json=passed_data)
            assert resp_skipped.status_code == 200
            assert resp_skipped.json()["status"] == "skipped"
        finally:
            settings.selective_persistence = original_selective

        # Test API Clear Report
        resp_clear = client.post("/api/report/clear")
        assert resp_clear.status_code == 200
        assert resp_clear.json()["status"] == "cleared"
        assert resp_clear.json()["total_endpoints"] == 0

        # Verify DB is now empty
        resp_after_clear = client.get("/api/report")
        assert resp_after_clear.json()["summary"]["total_endpoints"] == 0


def test_timeline_computation_empty():
    report = AggregateReport(title="Empty Report", results=[])
    tl = report.timeline
    assert len(tl["bars"]) == 12
    assert all(b["status"] == "EMPTY" for b in tl["bars"])
    assert all(b["height_pct"] == 6 for b in tl["bars"])
    assert tl["end_label"] == "Now"


def test_timeline_computation_small(sample_report: AggregateReport):
    tl = sample_report.timeline
    assert len(tl["bars"]) == 12

    # sample_report has 3 results: pass, warn, fail (reverse order in timeline)
    # in sample_report.results: [0] PASSED, [1] WARNING, [2] FAILED
    # chronological order (reversed): [0] FAILED, [1] WARNING, [2] PASSED
    b0 = tl["bars"][0]
    b1 = tl["bars"][1]
    b2 = tl["bars"][2]

    assert b0["status"] == "FAILED"
    assert b0["height_pct"] == 40
    assert b1["status"] == "WARNING"
    assert b1["height_pct"] == 70
    assert b2["status"] == "PASSED"
    assert b2["height_pct"] == 100

    # Remaining 9 bars should be EMPTY
    for i in range(3, 12):
        assert tl["bars"][i]["status"] == "EMPTY"
        assert tl["bars"][i]["height_pct"] == 6


def test_timeline_computation_bucketing():
    # 24 results should partition into 12 buckets of 2 results each
    results = []
    for i in range(24):
        status = ValidationStatus.PASSED if i % 2 == 0 else ValidationStatus.FAILED
        results.append(
            EndpointValidationResult(
                endpoint=f"/api/v1/test_{i}",
                method="GET",
                status_code=200,
                validation_status=status,
            )
        )
    report = AggregateReport(results=results)
    tl = report.timeline
    assert len(tl["bars"]) == 12

    for b in tl["bars"]:
        assert b["total"] == 2
        assert b["passed"] == 1
        assert b["failed"] == 1
        assert b["status"] == "FAILED"
        assert b["pass_rate"] == 50
        assert b["height_pct"] == 50


def test_api_report_contains_timeline():
    client = TestClient(app)
    resp = client.get("/api/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "timeline" in data
    assert "bars" in data["timeline"]
    assert len(data["timeline"]["bars"]) == 12


def test_drift_statistics_endpoint_and_aggregation():
    """Test that recurring drift issues are aggregated with occurrence counts, timestamps, and stats API."""
    client = TestClient(app)
    client.post("/api/report/clear")

    drift_payload = {
        "endpoint": "/api/v1/users",
        "method": "POST",
        "status_code": 201,
        "validation_status": "FAILED",
        "severity": "ERROR",
        "differences": [
            {
                "issue_type": "MISSING_REQUIRED_FIELD",
                "severity": "ERROR",
                "location": "request_body",
                "message": "Missing required field 'email'",
                "expected": "email",
                "actual": None,
            },
            {
                "issue_type": "TYPE_MISMATCH",
                "severity": "ERROR",
                "location": "request_body",
                "message": "Type mismatch at $.age",
                "expected": "integer",
                "actual": "string",
            }
        ]
    }

    # Post first occurrence
    resp1 = client.post("/api/report/append", json=drift_payload)
    assert resp1.status_code == 200

    # Post second occurrence of the same issue
    resp2 = client.post("/api/report/append", json=drift_payload)
    assert resp2.status_code == 200

    # Fetch drift statistics
    stats_resp = client.get("/api/drift/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()

    assert stats["total_drift_occurrences"] == 4  # 2 diffs x 2 posts
    assert stats["distinct_drift_signatures"] == 2
    assert stats["endpoints_affected"] == 1

    top_drifts = stats["top_recurring_drifts"]
    assert len(top_drifts) == 2
    for item in top_drifts:
        assert item["occurrence_count"] == 2
        assert item["first_seen"] is not None
        assert item["last_seen"] is not None
        assert item["endpoint"] == "/api/v1/users"

    # Test clear
    clear_resp = client.post("/api/report/clear")
    assert clear_resp.status_code == 200

    stats_cleared = client.get("/api/drift/stats").json()
    assert stats_cleared["total_drift_occurrences"] == 0
    assert stats_cleared["distinct_drift_signatures"] == 0


def test_endpoints_explorer_catalog_and_view():
    """Test that Endpoints Explorer catalog page and JSON API return endpoints and status."""
    client = TestClient(app)

    # Test /api/endpoints JSON endpoint
    api_resp = client.get("/api/endpoints")
    assert api_resp.status_code == 200
    data = api_resp.json()
    assert "endpoints" in data
    assert data["total"] > 0
    endpoints = data["endpoints"]
    paths = [ep["endpoint"] for ep in endpoints]
    assert "/api/v1/users" in paths

    # Test /endpoints HTML page
    html_resp = client.get("/endpoints")
    assert html_resp.status_code == 200
    assert "Endpoints Explorer" in html_resp.text
    assert "/api/v1/users" in html_resp.text

    # Test /endpoint/explore endpoint-specific view
    explore_resp = client.get("/endpoint/explore?method=GET&endpoint=/api/v1/users")
    assert explore_resp.status_code == 200
    assert "Endpoint Detail" in explore_resp.text or "/api/v1/users" in explore_resp.text




