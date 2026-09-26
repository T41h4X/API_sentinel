# API Sentinel — How to Run & Complete Demo Guide 🛡️

This guide covers everything you need to run, test, and demonstrate the full capabilities of **API Sentinel** (`api-drift-detector`).

---

## 📋 Prerequisites
- **Python 3.10+** (Tested on Python 3.10, 3.11, 3.12, 3.13)
- Windows Command Prompt or PowerShell (or bash on Linux/macOS)

---

## ⚡ Method 1: Quick Start (Recommended for Windows)

The easiest way to start everything and see live results:

### 1. One-Time Setup (Virtual Environment)
In your terminal, inside the project folder:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

### 2. Start Everything in One Click
Double-click or run:
```cmd
start_all.cmd
```
*What this does automatically:*
1. Starts the Monitored API server on **`http://127.0.0.1:8000`**
2. Starts the Interactive Dashboard on **`http://127.0.0.1:8001`**
3. Runs validation scenarios and pushes live drift issues to the dashboard
4. Launches your default web browser to the dashboard

### 3. Generate New Drift Issues During Live Demo
To trigger additional validation scenarios and increase recurring drift counts:
```cmd
push_issues.cmd
```
*(or run `python push_to_dashboard.py`)*

### 4. Stop All Services Cleanly
When you finish testing or demonstrating:
```cmd
stop_all.cmd
```

---

## 💻 Method 2: Manual Step-by-Step Terminal Execution

If you prefer running services in separate terminal windows:

### Terminal 1: Start the Interactive Dashboard
```powershell
.\.venv\Scripts\Activate.ps1
uvicorn dashboard.app:app --reload --host 127.0.0.1 --port 8001
```
* Dashboard will be live at: **[http://127.0.0.1:8001](http://127.0.0.1:8001)**

### Terminal 2: Start the Monitored Demo API
```powershell
.\.venv\Scripts\Activate.ps1
uvicorn example_app:app --reload --host 127.0.0.1 --port 8000
```
* API Swagger UI will be live at: **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

### Terminal 3: Inject Live Traffic & Validation Scenarios
```powershell
.\.venv\Scripts\Activate.ps1
python push_to_dashboard.py
```

---

## 🎬 How to Demonstrate the Whole Project (Faculty / Team Walkthrough)

Follow these 7 steps to showcase all major features of API Sentinel:

### Step 1: The Contract Foundation (OpenAPI Specification)
1. Open the Monitored API Swagger UI: **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**
2. Explain: The API is expected to strictly conform to `openapi.yaml`.
3. In terminal, demonstrate the built-in specification validator:
   ```powershell
   api-sentinel validate --spec openapi.yaml
   ```
   *Show that it parses routes, schemas, and verifies valid OpenAPI 3.0.x / 3.1.x syntax.*

---

### Step 2: The Monitoring Dashboard
1. Open the Dashboard: **[http://127.0.0.1:8001](http://127.0.0.1:8001)**
2. Point out:
   - **KPI Summary Cards**: Total Analyzed Requests, Passed, Warnings, and Failed.
   - **Compliance Pass Rate**: Real-time percentage of contract adherence.
   - **Recent Validation Reports Table**: Live logs of every intercepted request/response cycle.

---

### Step 3: Trigger Live Schema Drift Scenarios
Run:
```powershell
python push_to_dashboard.py
```
Explain the scenarios being executed against the contract:
- **Scenario 1 (HTTP 200 — PASSED)**: Clean response matching the `UserResponse` schema 100%.
- **Scenario 2 (HTTP 200 — WARNING)**: Server returned undocumented extra fields `debug_internal_id` and `server_uptime` (`EXTRA_FIELD`).
- **Scenario 3 (HTTP 201 — FAILED)**: Server returned `201 Created`, but omitted the mandatory `email` field (`REQUIRED_FIELD_VIOLATION`). *Highlight that this catches silent production bugs where the HTTP code is 201 but clients crash.*
- **Scenario 4 (HTTP 201 — FAILED)**: Field `name` was returned as an integer instead of a string (`TYPE_MISMATCH`).
- **Scenario 5 (HTTP 400 — FAILED)**: Server returned an undocumented `400 Bad Request` status code (`UNDOCUMENTED_STATUS_CODE`).
- **Scenario 6 (HTTP 201 — FAILED)**: Traffic sent to `/api/v1/orders` which is completely missing from the specification (`UNDOCUMENTED_ENDPOINT` / Shadow API detection).

---

### Step 4: Recurring Schema Drift History & Statistics
1. Scroll down to the **"Recurring Schema Drift History"** table on the dashboard home page.
2. Demonstrate:
   - Cumulative **Occurrence Count** for recurring drifts (e.g. `debug_internal_id` observed 3+ times).
   - **First Seen** and **Last Seen** timestamps tracking drift duration.
   - Severity badges (`WARNING` vs `ERROR`) and exact JSON locations.

---

### Step 5: Unified Endpoint Explorer
1. Click **"Endpoint Explorer"** in the sidebar navigation or visit:
   👉 **[http://127.0.0.1:8001/endpoints](http://127.0.0.1:8001/endpoints)**
2. Demonstrate:
   - **Filter Tabs**:
     - *All*: Complete catalog of documented and runtime endpoints.
     - *Documented & Observed*: Active endpoints matching spec.
     - *Spec Only (Unseen)*: Documented endpoints with 0 runtime traffic (`POST /api/v1/auth/login`).
     - *Undocumented Traffic*: Shadow endpoints detected live without spec entry (`POST /api/v1/orders`).
   - **Client-side Search**: Type `users` or `orders` into the search box to filter instantly.
   - Click **"View Spec & Telemetry"** on any endpoint to compare expected schema vs runtime inferred schema.

---

### Step 6: Sensitive Data Masking
1. Explain that API Sentinel automatically redacts sensitive data before persisting or displaying logs.
2. In the dashboard reports, show that values for fields like `password`, `token`, `secret`, `api_key`, and `access_token` are masked as `[REDACTED]` or `***MASKED***`.

---

### Step 7: CI/CD Pipeline Contract Verification
Demonstrate how API Sentinel runs in automated GitHub Actions / CI/CD pipelines to prevent broken deployments:

1. **Verify spec in CI**:
   ```powershell
   api-sentinel check --spec openapi.yaml
   ```
   *Exits with code 0 on success.*

2. **Verify JSON Output mode**:
   ```powershell
   api-sentinel check --spec openapi.yaml --json
   ```

3. **Check Exit Code**:
   ```powershell
   $LASTEXITCODE
   ```
   *Returns `0` for clean pass, or `1` if contract violations breach policy (`--fail-on error` or `--fail-on warning`).*

4. Show `.github/workflows/ci.yml` in your repository as proof of automated CI validation.

---

## 🗄️ Database & Persistence Verification
- **Database File**: `sentinel.db` (SQLite in project root).
- **Persistence Test**:
  1. Note the numbers on the dashboard.
  2. Stop the dashboard (`Ctrl + C`).
  3. Restart it with `uvicorn dashboard.app:app --port 8001`.
  4. Notice all historical reports and recurring drift stats are preserved.
- **Inspect DB**: You can open `sentinel.db` in any SQLite viewer (DB Browser for SQLite, DBeaver, or VS Code SQLite extension) to inspect `validation_reports`, `differences`, and `aggregated_drifts`.

---

## 🧪 Running the Full Automated Test Suite
To verify code correctness across all components:
```powershell
pytest -v
```
All **165 tests** across middleware, schema inferencer, diff engine, spec validator, and CLI should pass.
