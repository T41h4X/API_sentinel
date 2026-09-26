"""Tests for API Sentinel CLI commands, Configuration, and Database layer."""

import os
import sys
import pytest
from unittest.mock import patch
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from api_sentinel import __version__
from api_sentinel.cli import main, run_validate, run_dashboard, run_check
from api_sentinel.config import Settings
from api_sentinel.database.session import init_db, AsyncSessionLocal
from api_sentinel.database.models import ValidationReportRecord, DifferenceRecord


# ---------------------------------------------------------------------------
# CLI Tests
# ---------------------------------------------------------------------------

class TestCLI:
    """Tests for the api-sentinel CLI."""

    def test_version_command(self, capsys):
        with patch.object(sys, "argv", ["api-sentinel", "version"]):
            main()
        captured = capsys.readouterr()
        assert f"API Sentinel v{__version__}" in captured.out

    def test_validate_command_valid_spec(self, capsys):
        spec_path = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")
        with patch.object(sys, "argv", ["api-sentinel", "validate", "--spec", spec_path]):
            main()
        captured = capsys.readouterr()
        assert "valid OpenAPI specification" in captured.out
        assert "/api/v1/users" in captured.out

    def test_validate_command_missing_file(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            run_validate("non_existent_spec_file.yaml")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: Specification file not found" in captured.out

    def test_validate_command_invalid_syntax(self, tmp_path, capsys):
        bad_spec = tmp_path / "bad.yaml"
        bad_spec.write_text("openapi: 3.0.3\npaths: [this is invalid")
        with pytest.raises(SystemExit) as exc_info:
            run_validate(str(bad_spec))
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Validation failed" in captured.out

    def test_dashboard_command_invocation(self):
        with patch("uvicorn.run") as mock_uvicorn:
            run_dashboard(host="127.0.0.1", port=9999, reload=False)
            mock_uvicorn.assert_called_once_with(
                "api_sentinel.dashboard.app:app", host="127.0.0.1", port=9999, reload=False
            )

    def test_main_help_when_no_args(self, capsys):
        with patch.object(sys, "argv", ["api-sentinel"]):
            main()
        captured = capsys.readouterr()
        assert "usage:" in captured.out or "API Sentinel" in captured.out

    def test_check_command_spec_only_success(self, capsys):
        spec_path = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["api-sentinel", "check", "--spec", spec_path]):
                main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "valid with" in captured.out
        assert "Specification check passed" in captured.out

    def test_check_command_with_passing_traffic(self, tmp_path, capsys):
        import json
        spec_path = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")
        traffic_file = tmp_path / "traffic.json"
        traffic_data = [
            {
                "method": "GET",
                "path": "/api/v1/users",
                "status_code": 200,
                "response_body": [
                    {"id": 1, "name": "Alice", "email": "alice@example.com"}
                ]
            }
        ]
        traffic_file.write_text(json.dumps(traffic_data))

        with pytest.raises(SystemExit) as exc_info:
            run_check(spec_path=spec_path, traffic_path=str(traffic_file), fail_on="error")
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "CONTRACT CHECK" in captured.out
        assert "PASSED" in captured.out

    def test_check_command_with_failing_traffic(self, tmp_path, capsys):
        import json
        spec_path = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")
        traffic_file = tmp_path / "failing_traffic.json"
        # Missing required name and email
        traffic_data = [
            {
                "method": "GET",
                "path": "/api/v1/users",
                "status_code": 200,
                "response_body": [
                    {"id": 1}
                ]
            }
        ]
        traffic_file.write_text(json.dumps(traffic_data))

        with pytest.raises(SystemExit) as exc_info:
            run_check(spec_path=spec_path, traffic_path=str(traffic_file), fail_on="error")
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.out

    def test_check_command_json_output(self, tmp_path, capsys):
        import json
        spec_path = os.path.join(os.path.dirname(__file__), "..", "openapi.yaml")
        traffic_file = tmp_path / "traffic.json"
        traffic_data = [
            {
                "method": "GET",
                "path": "/api/v1/users",
                "status_code": 200,
                "response_body": [
                    {"id": 1, "name": "Bob", "email": "bob@example.com"}
                ]
            }
        ]
        traffic_file.write_text(json.dumps(traffic_data))

        with pytest.raises(SystemExit) as exc_info:
            run_check(spec_path=spec_path, traffic_path=str(traffic_file), json_output=True)
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "PASSED"
        assert data["records_analyzed"] == 1



# ---------------------------------------------------------------------------
# Configuration Tests
# ---------------------------------------------------------------------------

class TestConfiguration:
    """Tests for pydantic Settings and environment variable parsing."""

    def test_default_settings(self):
        s = Settings()
        assert s.retention_days == 30
        assert s.selective_persistence is False
        assert "password" in s.masked_fields
        assert s.openapi_spec_path == "openapi.yaml"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SENTINEL_RETENTION_DAYS", "60")
        monkeypatch.setenv("SENTINEL_SELECTIVE_PERSISTENCE", "true")
        monkeypatch.setenv("SENTINEL_OPENAPI_SPEC_PATH", "custom_spec.yaml")
        s = Settings()
        assert s.retention_days == 60
        assert s.selective_persistence is True
        assert s.openapi_spec_path == "custom_spec.yaml"


# ---------------------------------------------------------------------------
# Database Layer Tests
# ---------------------------------------------------------------------------

class TestDatabaseModels:
    """Tests for database tables, records, and cascade relationships."""

    @pytest.mark.asyncio
    async def test_init_db_and_cascade_delete(self):
        await init_db()

        async with AsyncSessionLocal() as session:
            # Create report with nested difference
            report = ValidationReportRecord(
                endpoint="/api/v1/test_cascade",
                method="POST",
                status_code=400,
                validation_status="FAILED",
                severity="ERROR",
            )
            report.differences.append(
                DifferenceRecord(
                    issue_type="TYPE_MISMATCH",
                    severity="ERROR",
                    location="response_body",
                    message="Expected integer, got string",
                )
            )
            session.add(report)
            await session.commit()
            report_id = report.id

        # Verify persisted with difference
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ValidationReportRecord)
                .options(selectinload(ValidationReportRecord.differences))
                .where(ValidationReportRecord.id == report_id)
            )
            fetched = result.scalar_one_or_none()
            assert fetched is not None
            assert len(fetched.differences) == 1
            assert fetched.differences[0].issue_type == "TYPE_MISMATCH"

            # Delete parent report
            await session.delete(fetched)
            await session.commit()

        # Verify orphan difference was cascade-deleted
        async with AsyncSessionLocal() as session:
            diff_result = await session.execute(
                select(DifferenceRecord).where(DifferenceRecord.report_id == report_id)
            )
            assert diff_result.scalar_one_or_none() is None
