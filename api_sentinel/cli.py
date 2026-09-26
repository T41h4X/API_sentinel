"""
API Sentinel - Command Line Interface (CLI)
Provides terminal commands to start the dashboard, validate specs, and inspect health.
"""

import argparse
import sys
import os

from api_sentinel import __version__


def run_dashboard(host: str = "127.0.0.1", port: int = 8001, reload: bool = False):
    """Launches the API Sentinel interactive dashboard server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is required to run the dashboard. Install it with: pip install uvicorn")
        sys.exit(1)

    print(f"Starting API Sentinel Dashboard on http://{host}:{port} ...")
    uvicorn.run("api_sentinel.dashboard.app:app", host=host, port=port, reload=reload)


def run_validate(spec_path: str):
    """Validates an OpenAPI YAML or JSON specification file."""
    if not os.path.exists(spec_path):
        print(f"Error: Specification file not found: {spec_path}")
        sys.exit(1)

    try:
        from api_sentinel.spec_validator import validate_openapi_spec
        result = validate_openapi_spec(spec_path)
        if not result.is_valid:
            print(f"Validation failed for '{spec_path}': {result.error}")
            sys.exit(1)

        summary = result.summary or {}
        endpoints = [ep["path"] for ep in summary.get("endpoints", [])]
        print(f"Success: '{spec_path}' is a valid OpenAPI specification!")
        print(f"Found {len(endpoints)} documented endpoint(s):")
        for ep in endpoints:
            print(f"  • {ep}")
    except Exception as exc:
        print(f"Validation failed for '{spec_path}': {exc}")
        sys.exit(1)


def run_check(
    spec_path: str = "openapi.yaml",
    traffic_path: str = None,
    fail_on: str = "error",
    fail_on_warning: bool = False,
    fail_on_drift: bool = False,
    output_path: str = None,
    json_output: bool = False,
):
    """
    Validates API contracts against an OpenAPI specification for CI/CD pipelines.
    Exits with code 0 on success, or code 1 if violations exceed the fail threshold.
    """
    import json
    from api_sentinel.spec_validator import validate_openapi_spec

    if not os.path.exists(spec_path):
        print(f"Error: Specification file not found: {spec_path}")
        sys.exit(1)

    spec_res = validate_openapi_spec(spec_path)
    if not spec_res.is_valid:
        print(f"Contract Check FAILED: Invalid OpenAPI spec '{spec_path}': {spec_res.error}")
        sys.exit(1)

    endpoints = [ep["path"] for ep in (spec_res.summary or {}).get("endpoints", [])]

    if not traffic_path:
        # If no traffic file is provided, spec validation is the contract check
        if json_output:
            print(json.dumps({
                "status": "PASSED",
                "spec": spec_path,
                "endpoints_count": len(endpoints),
                "endpoints": endpoints,
                "message": "OpenAPI specification is valid."
            }, indent=2))
        else:
            print(f"Success: OpenAPI specification '{spec_path}' is valid with {len(endpoints)} endpoint(s).")
            print("No traffic file specified (--traffic). Specification check passed.")
        sys.exit(0)

    if not os.path.exists(traffic_path):
        print(f"Error: Traffic file not found: {traffic_path}")
        sys.exit(1)

    try:
        with open(traffic_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content.startswith("["):
                records = json.loads(content)
            elif content.startswith("{"):
                try:
                    parsed = json.loads(content)
                    records = parsed if isinstance(parsed, list) else [parsed]
                except json.JSONDecodeError:
                    records = [json.loads(line) for line in content.splitlines() if line.strip()]
            else:
                records = [json.loads(line) for line in content.splitlines() if line.strip()]
    except Exception as exc:
        print(f"Error reading traffic file '{traffic_path}': {exc}")
        sys.exit(1)

    from api_sentinel.validator import ContractValidator, RuntimeData

    validator = ContractValidator.from_file(spec_path)
    all_reports = []
    total_errors = 0
    total_warnings = 0
    total_info = 0
    all_differences = []

    for item in records:
        path = item.get("path") or item.get("endpoint") or "/"
        method = (item.get("method") or "GET").upper()
        status_code = int(item.get("status_code", 200))
        query_params = item.get("query_params") or item.get("query_parameters") or {}
        req_body = item.get("request_body")
        res_body = item.get("response_body")
        req_ct = item.get("request_content_type", "application/json")
        res_ct = item.get("response_content_type", "application/json")
        path_params = item.get("path_params") or item.get("path_parameters") or {}

        rt_data = RuntimeData(
            method=method,
            path=path,
            status_code=status_code,
            query_params=query_params,
            request_body=req_body,
            response_body=res_body,
            request_content_type=req_ct,
            response_content_type=res_ct,
            path_params=path_params,
        )
        report = validator.validate(rt_data)
        all_reports.append(report)
        total_errors += report.error_count
        total_warnings += report.warning_count
        total_info += report.info_count
        for diff in report.differences:
            all_differences.append({
                "endpoint": report.endpoint,
                "method": report.method,
                "status_code": report.status_code,
                "diff_type": diff.diff_type.value if hasattr(diff.diff_type, "value") else str(diff.diff_type),
                "severity": diff.severity.value if hasattr(diff.severity, "value") else str(diff.severity),
                "location": diff.location,
                "json_path": diff.json_path,
                "message": diff.message,
            })

    effective_fail_on = "drift" if fail_on_drift else ("warning" if fail_on_warning else fail_on.lower())
    if effective_fail_on == "drift":
        failed = (total_errors + total_warnings + total_info) > 0
    elif effective_fail_on == "warning":
        failed = (total_errors + total_warnings) > 0
    else:  # "error"
        failed = total_errors > 0

    overall_status = "FAILED" if failed else "PASSED"

    if json_output:
        result_payload = {
            "status": overall_status,
            "spec": spec_path,
            "traffic_file": traffic_path,
            "records_analyzed": len(records),
            "summary": {
                "errors": total_errors,
                "warnings": total_warnings,
                "info": total_info,
            },
            "differences": all_differences,
        }
        print(json.dumps(result_payload, indent=2))
    else:
        print("=" * 60)
        print("              API SENTINEL CONTRACT CHECK")
        print("=" * 60)
        print(f"Spec File:         {spec_path}")
        print(f"Traffic File:      {traffic_path}")
        print(f"Traffic Records:   {len(records)}")
        print(f"Overall Status:    {overall_status}")
        print(f"Violations:        {total_errors} errors, {total_warnings} warnings, {total_info} info")
        print(f"Policy:            --fail-on={effective_fail_on}")
        print("-" * 60)

        if all_differences:
            print("Detected Contract Violations / Schema Drift:")
            for d in all_differences:
                sev = f"[{d['severity']}]"
                print(f"  {sev:<9} {d['method']} {d['endpoint']} -> {d['location']}: {d['message']}")
        else:
            print("No contract violations detected. All runtime payloads match the specification.")

        print("=" * 60)

    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as out_f:
                json.dump({
                    "status": overall_status,
                    "spec": spec_path,
                    "traffic_file": traffic_path,
                    "records_analyzed": len(records),
                    "summary": {
                        "errors": total_errors,
                        "warnings": total_warnings,
                        "info": total_info,
                    },
                    "differences": all_differences,
                }, out_f, indent=2)
            if not json_output:
                print(f"Report saved to: {output_path}")
        except Exception as exc:
            print(f"Warning: Failed to save output report to '{output_path}': {exc}")

    if failed:
        if not json_output:
            print(f"\n[FAIL] Contract check failed based on policy --fail-on={effective_fail_on}")
        sys.exit(1)
    else:
        if not json_output:
            print(f"\n[PASS] Contract check passed! No violations exceeding threshold ({effective_fail_on}).")
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        prog="api-sentinel",
        description="API Sentinel - Real-time OpenAPI Schema Drift Detection & Telemetry Dashboard",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"API Sentinel v{__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: dashboard
    dash_parser = subparsers.add_parser("dashboard", help="Start the interactive monitoring dashboard")
    dash_parser.add_argument("--host", default="127.0.0.1", help="Host address to bind (default: 127.0.0.1)")
    dash_parser.add_argument("-p", "--port", type=int, default=8001, help="Port to bind (default: 8001)")
    dash_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    # Command: validate
    val_parser = subparsers.add_parser("validate", help="Validate an OpenAPI specification file")
    val_parser.add_argument("--spec", default="openapi.yaml", help="Path to OpenAPI spec file (default: openapi.yaml)")

    # Command: check (CI/CD Contract Check)
    chk_parser = subparsers.add_parser("check", help="Run contract verification against an OpenAPI specification")
    chk_parser.add_argument("--spec", default="openapi.yaml", help="Path to OpenAPI spec file (default: openapi.yaml)")
    chk_parser.add_argument("--traffic", default=None, help="Path to JSON/JSONL file containing captured HTTP traffic")
    chk_parser.add_argument("--fail-on", choices=["error", "warning", "drift"], default="error", help="Violation severity threshold to fail CI (default: error)")
    chk_parser.add_argument("--fail-on-warning", action="store_true", help="Fail if any warning or error is detected")
    chk_parser.add_argument("--fail-on-drift", action="store_true", help="Fail on any drift or schema difference (error, warning, or info)")
    chk_parser.add_argument("--output", default=None, help="Save report results to a file (JSON)")
    chk_parser.add_argument("--json", action="store_true", dest="json_output", help="Output results in JSON format")

    # Command: version
    subparsers.add_parser("version", help="Print API Sentinel version")

    args = parser.parse_args()

    if args.command == "dashboard":
        run_dashboard(host=args.host, port=args.port, reload=args.reload)
    elif args.command == "validate":
        run_validate(args.spec)
    elif args.command == "check":
        run_check(
            spec_path=args.spec,
            traffic_path=args.traffic,
            fail_on=args.fail_on,
            fail_on_warning=args.fail_on_warning,
            fail_on_drift=args.fail_on_drift,
            output_path=args.output,
            json_output=args.json_output,
        )
    elif args.command == "version":
        print(f"API Sentinel v{__version__}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

