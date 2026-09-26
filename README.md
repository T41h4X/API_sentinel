# API Sentinel 🛡️

[![PyPI version](https://img.shields.io/pypi/v/api-drift-detector.svg)](https://pypi.org/project/api-drift-detector/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.95+-009688.svg)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenAPI 3.x](https://img.shields.io/badge/OpenAPI-3.x-green.svg)](https://swagger.io/specification/)

**API Sentinel** (`api-drift-detector`) is an asynchronous API contract monitoring and schema-drift detection system for FastAPI and ASGI applications. It intercepts runtime traffic, compares request and response payloads against your OpenAPI specification in real-time, surfaces contract violations, aggregates recurring drift statistics, and provides CI/CD contract gating.

```text
OpenAPI Specification
        ↓
Expected API Contract
        ↓
   API Sentinel   ←──  Runtime API Traffic (Zero-Latency Async Interception)
        ↓
Schema Drift Engine  (Missing fields, Extra fields, Type mismatches, Shadow APIs)
        ↓
Persistent History & Interactive Dashboard / CI/CD Gating
```

---

## 🚀 Key Features

1. **⚡ Zero-Latency Async Interception**
   * Uses non-blocking background tasks (`asyncio.create_task`) and response stream buffering. API requests and responses stream immediately to clients without waiting for contract validation.

2. **🔍 Comprehensive Schema Drift Engine**
   * Detects missing required fields, undocumented extra fields, data type mismatches, enum violations, array item violations, and undocumented query/path parameters.
   * Detects **Shadow APIs** (runtime endpoints invoked in production that are missing from the OpenAPI documentation).
   * Detects **Undocumented Status Codes** (e.g. server returning uncontracted 400 or 500 error envelopes).

3. **🔒 Sensitive Data Masking**
   * Automatically redacts sensitive fields (passwords, tokens, API keys, secrets, authorization headers, private keys, credit cards) across request/response headers, query parameters, and deeply nested JSON bodies before persistence or display.

4. **🧬 Dynamic Multi-Payload Schema Inference**
   * Inactive or evolving APIs can be inferred dynamically on the fly.
   * Merges multiple observed payloads to infer unified JSON schemas with type unions (`string | null`), optional fields, and per-path field observation frequency rates.

5. **📋 OpenAPI Specification Validation**
   * Built-in validator verifying syntax, OpenAPI versions (`3.0.x`, `3.1.x`), path templates, route compilation, and schema definitions.
   * Usable via CLI (`api-sentinel validate`) and programmatic Python imports.

6. **📈 Recurring Schema Drift History & Aggregation**
   * Tracks cumulative occurrence counts, first-seen timestamps, last-seen timestamps, and representative sample payloads for recurring drifts.
   * Dedicated API endpoint `/api/drift/stats` and recurring drift widget on the dashboard.

7. **🧭 Unified Endpoint Explorer**
   * Merges your OpenAPI specification catalog with live runtime traffic telemetry.
   * Filter between:
     * **All Endpoints**
     * **Documented & Observed**
     * **Spec Only (Unseen)**: Endpoints documented in spec with 0 traffic calls.
     * **Undocumented Traffic**: Shadow APIs receiving traffic without spec documentation.
   * Search, method filtering, and side-by-side spec vs. runtime inferred schema detail view.

8. **🤖 CI/CD Contract Check CLI**
   * Dedicated command `api-sentinel check --spec openapi.yaml --traffic <file>` to validate API contracts in automated deployment pipelines.
   * Returns exit code `0` on success and non-zero exit code `1` when violations breach policy (`--fail-on error`, `--fail-on warning`, `--fail-on drift`).
   * Includes ready-to-use GitHub Actions workflow (`.github/workflows/ci.yml`).

9. **📊 Real-Time Developer Dashboard**
   * Modern dark-mode interface with live metrics, pass/fail timeline charts, recent validation logs, and JSON/HTML export capabilities.

10. **💾 Database Persistence**
    * Automatically records all validation results, schema diffs, and recurring drift records to SQLite via SQLAlchemy (`aiosqlite`), persisting telemetry across server restarts.

11. **🪄 OpenAPI Specification Wizard**
    * Visual browser-based interface to design, edit, preview, test, and save OpenAPI specifications without touching raw YAML.

---

## 📦 Installation

### From PyPI (Recommended):
```bash
pip install api-drift-detector
```

### From GitHub:
```bash
pip install git+https://github.com/T41h4X/API_sentinel.git
```

---

## ⚡ Quick Start

### 1. Start the Sentinel Dashboard (Terminal 1)
```bash
api-sentinel dashboard
```
Open **[http://127.0.0.1:8001](http://127.0.0.1:8001)** to monitor incoming traffic and contract drifts.

### 2. Attach Middleware to Your FastAPI App (Terminal 2)
```python
from fastapi import FastAPI
from api_sentinel import APISentinelMiddleware

app = FastAPI(title="My Service")

# Register Sentinel Middleware
app.add_middleware(
    APISentinelMiddleware,
    openapi_path="openapi.yaml",            # Path to your OpenAPI spec
    dashboard_url="http://127.0.0.1:8001",  # Dashboard address
    enabled=True,
    print_clean=True,
)

@app.get("/api/v1/users/{user_id}")
async def get_user(user_id: int):
    # Any schema mismatch or undocumented fields will trigger live alerts!
    return {"id": user_id, "name": "Alice"}
```

Run your FastAPI application:
```bash
uvicorn app:app --reload --port 8000
```

Any request sent to `http://127.0.0.1:8000/api/v1/users/42` is validated asynchronously and streamed directly into your dashboard.

---

## 💻 Command Line Interface (CLI)

The CLI is available as both `api-sentinel` and `api-drift-detector`:

```bash
# 1. Start the interactive dashboard
api-sentinel dashboard --host 127.0.0.1 --port 8001

# 2. Validate OpenAPI specification syntax and structure
api-sentinel validate --spec openapi.yaml

# 3. Run CI/CD contract check (spec check)
api-sentinel check --spec openapi.yaml

# 4. Run CI/CD contract check against captured traffic payloads
api-sentinel check --spec openapi.yaml --traffic traffic.json --fail-on error

# 5. Output contract check results in JSON format
api-sentinel check --spec openapi.yaml --json

# 6. Check installed version
api-sentinel version
```

---

## 🤖 CI/CD Integration (GitHub Actions)

Add this workflow to your repository (`.github/workflows/ci.yml`):

```yaml
name: API Sentinel Contract Check

on: [push, pull_request]

jobs:
  contract-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install api-drift-detector
      - name: Validate OpenAPI Contract
        run: api-sentinel validate --spec openapi.yaml
      - name: Check Contract Violations
        run: api-sentinel check --spec openapi.yaml --fail-on error
```

---

## ⚙️ Configuration

Configure API Sentinel via environment variables (prefixed with `SENTINEL_`) or a `.env` file:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `SENTINEL_DATABASE_URL` | `sqlite+aiosqlite:///./sentinel.db` | SQLAlchemy SQLite database connection string |
| `SENTINEL_RETENTION_DAYS` | `30` | Days to retain validation records before automated cleanup |
| `SENTINEL_MASKED_FIELDS` | `["password", "token", "credit_card", "authorization", "secret", "api_key", "apikey", "access_token", "private_key"]` | Fields masked as `[REDACTED]` |
| `SENTINEL_SELECTIVE_PERSISTENCE` | `false` | When `true`, only saves `WARNING` and `FAILED` validation results |
| `SENTINEL_OPENAPI_SPEC_PATH` | `openapi.yaml` | Default OpenAPI specification file path |

---

## 🧪 Testing

Run the full automated test suite:
```bash
pytest -v
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
