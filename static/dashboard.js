/**
 * API Sentinel Developer Dashboard Client Controller
 * Real-Time Telemetry, Schema Drift Monitoring & Dynamic Polling
 */

(function () {
    let lastReportDataJson = "";
    let isPolling = false;
    let pollIntervalId = null;

    // Helper: Escape HTML
    function escapeHtml(str) {
        if (str === null || str === undefined) return "";
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    // Method badge styling
    function getMethodBadgeClass(method) {
        const m = (method || "").toUpperCase();
        switch (m) {
            case "GET":
                return "bg-primary-container text-on-primary-container";
            case "POST":
                return "bg-emerald-600 text-white";
            case "PUT":
                return "bg-amber-600 text-white";
            case "DELETE":
                return "bg-error text-white";
            case "PATCH":
                return "bg-purple-600 text-white";
            default:
                return "bg-secondary text-white";
        }
    }

    // Status badge styling
    function getStatusBadge(status) {
        const s = (status || "").toUpperCase();
        if (s === "PASSED") {
            return `<span class="bg-secondary-container text-on-secondary-container px-2 py-0.5 rounded text-xs font-bold border border-secondary/20 flex items-center gap-1 w-fit"><span class="material-symbols-outlined text-[12px]">check_circle</span>PASSED</span>`;
        } else if (s === "WARNING") {
            return `<span class="bg-tertiary-container text-on-tertiary-container px-2 py-0.5 rounded text-xs font-bold border border-tertiary/20 flex items-center gap-1 w-fit"><span class="material-symbols-outlined text-[12px]">warning</span>WARNING</span>`;
        } else {
            return `<span class="bg-error-container text-on-error-container px-2 py-0.5 rounded text-xs font-bold border border-error/20 flex items-center gap-1 w-fit"><span class="material-symbols-outlined text-[12px]">error</span>FAILED</span>`;
        }
    }

    // Severity text styling
    function getSeverityFormatted(severity) {
        const sev = (severity || "NONE").toUpperCase();
        if (sev === "ERROR" || sev === "CRITICAL") {
            return `<span class="text-error font-semibold font-code-md">${escapeHtml(sev)}</span>`;
        } else if (sev === "WARNING") {
            return `<span class="text-tertiary font-semibold font-code-md">${escapeHtml(sev)}</span>`;
        } else if (sev === "INFO") {
            return `<span class="text-primary font-code-md">${escapeHtml(sev)}</span>`;
        }
        return `<span class="text-on-surface-variant font-code-md">NONE</span>`;
    }

    // Filter application
    function applyFilters() {
        const searchInput = document.getElementById("global-search-input");
        const methodSelect = document.getElementById("filter-method");
        const statusSelect = document.getElementById("filter-status");
        const tableBody = document.getElementById("endpoint-table-rows");

        if (!tableBody) return;

        const query = (searchInput ? searchInput.value : "").toLowerCase().trim();
        const selectedMethod = methodSelect ? methodSelect.value.toUpperCase() : "ALL";
        const selectedStatus = statusSelect ? statusSelect.value.toUpperCase() : "ALL";

        const rows = tableBody.querySelectorAll("tr.endpoint-row");
        let visibleCount = 0;

        rows.forEach(row => {
            const endpoint = (row.dataset.endpoint || "").toLowerCase();
            const method = (row.dataset.method || "").toUpperCase();
            const status = (row.dataset.status || "").toUpperCase();

            const matchesSearch = !query || endpoint.includes(query) || method.includes(query);
            const matchesMethod = selectedMethod === "ALL" || method === selectedMethod;
            const matchesStatus = selectedStatus === "ALL" || status === selectedStatus;

            if (matchesSearch && matchesMethod && matchesStatus) {
                row.style.display = "";
                visibleCount++;
            } else {
                row.style.display = "none";
            }
        });

        const noResultsRow = document.getElementById("no-results-row");
        if (noResultsRow) {
            noResultsRow.style.display = visibleCount === 0 ? "" : "none";
        }
    }

    // Render / Update DOM from active report JSON
    function updateDashboardUI(report) {
        if (!report) return;

        const results = report.results || [];
        const total = report.summary ? report.summary.total_endpoints : results.length;
        const passed = report.summary ? report.summary.passed_endpoints : results.filter(r => (r.validation_status || "").toUpperCase() === "PASSED").length;
        const warning = report.summary ? report.summary.warning_count : results.filter(r => (r.validation_status || "").toUpperCase() === "WARNING").length;
        const failed = report.summary ? report.summary.failed_endpoints : results.filter(r => (r.validation_status || "").toUpperCase() === "FAILED").length;
        const passRate = total > 0 ? Math.round((passed / total) * 100) + "%" : "—";
        const driftIssues = failed + warning;

        // Update KPI counters
        const elTotal = document.getElementById("metric-total");
        const elPassed = document.getElementById("metric-passed");
        const elWarning = document.getElementById("metric-warning");
        const elFailed = document.getElementById("metric-failed");
        const elPassRate = document.getElementById("metric-pass-rate");
        const elDrift = document.getElementById("metric-drift");

        if (elTotal) elTotal.textContent = total;
        if (elPassed) elPassed.textContent = passed;
        if (elWarning) elWarning.textContent = warning;
        if (elFailed) elFailed.textContent = failed;
        if (elPassRate) elPassRate.textContent = passRate;
        if (elDrift) elDrift.textContent = driftIssues;

        // Update Donut Chart
        const elDonutWheel = document.getElementById("donut-chart-wheel");
        const elDonutTotal = document.getElementById("donut-total-count");
        const elDonutCrit = document.getElementById("donut-crit-count");
        const elDonutWarn = document.getElementById("donut-warn-count");
        const elDonutPass = document.getElementById("donut-pass-count");

        if (elDonutTotal) elDonutTotal.textContent = driftIssues;
        if (elDonutCrit) elDonutCrit.textContent = failed;
        if (elDonutWarn) elDonutWarn.textContent = warning;
        if (elDonutPass) elDonutPass.textContent = passed;

        if (elDonutWheel) {
            if (driftIssues > 0) {
                const failPct = Math.round((failed / driftIssues) * 100);
                const warnPct = Math.round((warning / driftIssues) * 100);
                elDonutWheel.style.background = `conic-gradient(from 0deg, #ba1a1a 0% ${failPct}%, #943700 ${failPct}% ${failPct + warnPct}%, #c3c6d7 ${failPct + warnPct}% 100%)`;
            } else {
                elDonutWheel.style.background = "#c3c6d7";
            }
        }

        // Update Table Rows
        const tableBody = document.getElementById("endpoint-table-rows");
        if (tableBody) {
            let html = "";
            results.forEach((res, idx) => {
                const method = (res.method || "GET").toUpperCase();
                const endpoint = res.endpoint || "/";
                const statusCode = res.status_code || 200;
                const status = (res.validation_status || "PASSED").toUpperCase();
                const severity = res.severity || "NONE";
                const timestamp = res.timestamp ? res.timestamp.replace("T", " ").substring(0, 19) : new Date().toISOString().substring(0, 19);

                html += `
                <tr class="data-table-row hover:bg-surface-container transition-colors endpoint-row"
                    data-endpoint="${escapeHtml(endpoint)}"
                    data-method="${escapeHtml(method)}"
                    data-status="${escapeHtml(status)}"
                    data-severity="${escapeHtml(severity)}">
                  <td class="py-3 pr-4">
                    <span class="${getMethodBadgeClass(method)} px-2 py-0.5 rounded text-xs font-bold">${escapeHtml(method)}</span>
                  </td>
                  <td class="py-3 pr-4 text-on-surface font-semibold font-code-md">${escapeHtml(endpoint)}</td>
                  <td class="py-3 pr-4 text-on-surface-variant font-code-md">${statusCode}</td>
                  <td class="py-3 pr-4">
                    ${getStatusBadge(status)}
                  </td>
                  <td class="py-3 pr-4 text-on-surface-variant">${getSeverityFormatted(severity)}</td>
                  <td class="py-3 pr-4 text-on-surface-variant text-xs font-code-md">${escapeHtml(timestamp)}</td>
                  <td class="py-3">
                    <a href="/endpoint/detail?index=${idx}" class="text-primary hover:underline text-xs font-semibold flex items-center gap-1">
                      Inspect <span class="material-symbols-outlined text-sm">arrow_forward</span>
                    </a>
                  </td>
                </tr>`;
            });

            html += `
            <tr id="no-results-row" style="display: ${results.length === 0 ? "" : "none"};">
              <td colspan="7" class="text-center py-8 text-on-surface-variant">
                ${results.length === 0 ? "No endpoint validation telemetry captured yet. Send requests to see live updates!" : "No endpoint validation results match the selected filters."}
              </td>
            </tr>`;

            tableBody.innerHTML = html;
            applyFilters();
        }

        // Update Validation Pass/Fail Rate Timeline Chart
        updateTimelineUI(report);

        // Update last updated clock
        const elLastUpdated = document.getElementById("last-updated-text");
        if (elLastUpdated) {
            const now = new Date();
            elLastUpdated.textContent = now.toTimeString().split(" ")[0];
        }
    }

    // Render / Update Timeline Bars
    function updateTimelineUI(report) {
        const container = document.getElementById("timeline-bars");
        if (!container) return;

        let timeline = report ? report.timeline : null;
        if (!timeline) {
            const results = (report && report.results) ? report.results : [];
            const resultsAsc = results.slice().reverse();
            const totalItems = resultsAsc.length;
            const numBars = 12;

            function fmtTs(ts) {
                if (!ts) return "";
                try {
                    const d = new Date(ts);
                    if (isNaN(d.getTime())) return String(ts).substring(11, 19);
                    return d.toTimeString().split(" ")[0];
                } catch (e) {
                    return "";
                }
            }

            const startLabel = totalItems > 0 ? (fmtTs(resultsAsc[0].timestamp) || "-24h") : "-24h";
            const midLabel = totalItems > 0 ? (fmtTs(resultsAsc[Math.floor(totalItems / 2)].timestamp) || "-12h") : "-12h";
            const endLabel = "Now";

            const bars = [];
            if (totalItems <= numBars) {
                resultsAsc.forEach(r => {
                    const status = (r.validation_status || "PASSED").toUpperCase();
                    const method = (r.method || "GET").toUpperCase();
                    const ep = r.endpoint || "/";
                    const sc = r.status_code || 200;

                    if (status === "PASSED") {
                        bars.push({
                            height_pct: 100,
                            status: "PASSED",
                            label: "100%",
                            tooltip: `${method} ${ep} • PASSED (${sc})`,
                        });
                    } else if (status === "WARNING") {
                        bars.push({
                            height_pct: 70,
                            status: "WARNING",
                            label: "Warn",
                            tooltip: `${method} ${ep} • WARNING (${sc})`,
                        });
                    } else {
                        bars.push({
                            height_pct: 40,
                            status: "FAILED",
                            label: "Fail",
                            tooltip: `${method} ${ep} • FAILED (${sc})`,
                        });
                    }
                });
                for (let i = totalItems; i < numBars; i++) {
                    bars.push({
                        height_pct: 6,
                        status: "EMPTY",
                        label: "—",
                        tooltip: "Awaiting validation telemetry...",
                    });
                }
            } else {
                for (let i = 0; i < numBars; i++) {
                    const startIdx = Math.floor((i * totalItems) / numBars);
                    const endIdx = Math.floor(((i + 1) * totalItems) / numBars);
                    const bucket = resultsAsc.slice(startIdx, endIdx);

                    if (bucket.length === 0) {
                        bars.push({
                            height_pct: 6,
                            status: "EMPTY",
                            label: "—",
                            tooltip: "No validation data in this interval",
                        });
                        continue;
                    }

                    const bTotal = bucket.length;
                    const bPassed = bucket.filter(x => (x.validation_status || "").toUpperCase() === "PASSED").length;
                    const bWarn = bucket.filter(x => (x.validation_status || "").toUpperCase() === "WARNING").length;
                    const bFailed = bucket.filter(x => (x.validation_status || "").toUpperCase() === "FAILED").length;
                    const passRate = Math.round((bPassed / bTotal) * 100);

                    const bStartTs = fmtTs(bucket[0].timestamp);
                    const bEndTs = fmtTs(bucket[bucket.length - 1].timestamp);
                    const rangeStr = bStartTs !== bEndTs ? `${bStartTs} - ${bEndTs}` : bStartTs;

                    if (bFailed > 0) {
                        bars.push({
                            height_pct: Math.max(passRate, 25),
                            status: "FAILED",
                            label: `${passRate}%`,
                            tooltip: `Pass Rate: ${passRate}% (${bPassed}/${bTotal} passed, ${bFailed} failed) • ${rangeStr}`,
                        });
                    } else if (bWarn > 0) {
                        bars.push({
                            height_pct: Math.max(passRate, 50),
                            status: "WARNING",
                            label: `${passRate}%`,
                            tooltip: `Pass Rate: ${passRate}% (${bPassed}/${bTotal} passed, ${bWarn} warnings) • ${rangeStr}`,
                        });
                    } else {
                        bars.push({
                            height_pct: 100,
                            status: "PASSED",
                            label: "100%",
                            tooltip: `100% Passed (${bPassed}/${bTotal} passed) • ${rangeStr}`,
                        });
                    }
                }
            }

            timeline = {
                bars: bars,
                start_label: startLabel,
                mid_label: midLabel,
                end_label: endLabel,
            };
        }

        // Render bars into container
        const bars = timeline.bars || [];
        let html = "";
        bars.forEach((bar, idx) => {
            let colorCls = "bg-outline-variant/20 hover:bg-outline-variant/40";
            let textCls = "text-on-surface-variant";
            if (bar.status === "PASSED") {
                colorCls = "bg-secondary/80 hover:bg-secondary";
                textCls = "text-secondary";
            } else if (bar.status === "WARNING") {
                colorCls = "bg-tertiary/80 hover:bg-tertiary";
                textCls = "text-tertiary";
            } else if (bar.status === "FAILED") {
                colorCls = "bg-error/80 hover:bg-error";
                textCls = "text-error";
            }

            html += `
            <div class="w-full h-full flex flex-col justify-end items-center relative group cursor-pointer" data-bar-index="${idx}">
              <div class="hidden group-hover:flex absolute -top-10 left-1/2 -translate-x-1/2 bg-surface text-on-surface border border-outline-variant shadow-lg text-xs py-1 px-2.5 rounded z-30 whitespace-nowrap pointer-events-none flex-col items-center">
                <span class="font-bold ${textCls}">${escapeHtml(bar.label)}</span>
                <span class="text-[10px] text-on-surface-variant font-code-md">${escapeHtml(bar.tooltip)}</span>
              </div>
              <div class="w-full ${colorCls} rounded-t-sm transition-all duration-300" style="height: ${bar.height_pct}%;"></div>
            </div>`;
        });
        container.innerHTML = html;

        // Update labels
        const elStart = document.getElementById("timeline-label-start");
        const elMid = document.getElementById("timeline-label-mid");
        const elEnd = document.getElementById("timeline-label-end");
        if (elStart && timeline.start_label) elStart.textContent = timeline.start_label;
        if (elMid && timeline.mid_label) elMid.textContent = timeline.mid_label;
        if (elEnd && timeline.end_label) elEnd.textContent = timeline.end_label;
    }

    // Fetch and dynamically update recurring drift history
    async function fetchDriftStats() {
        try {
            const res = await fetch("/api/drift/stats", { cache: "no-store" });
            if (!res.ok) return;
            const data = await res.json();
            const tbody = document.getElementById("recurring-drift-rows");
            if (!tbody) return;

            const items = data.top_recurring_drifts || [];
            if (items.length === 0) {
                tbody.innerHTML = `<tr id="no-drifts-row"><td colspan="7" class="py-4 text-center text-on-surface-variant font-body-sm">No recurring schema drifts recorded yet. Run <code>python push_to_dashboard.py</code> to generate drift scenarios.</td></tr>`;
                return;
            }

            let html = "";
            items.forEach(d => {
                let sevBadge = `<span class="bg-surface-container-high text-on-surface-variant px-2 py-0.5 rounded text-[11px] font-bold">INFO</span>`;
                if (d.severity === "ERROR") {
                    sevBadge = `<span class="bg-error-container text-on-error-container px-2 py-0.5 rounded text-[11px] font-bold">ERROR</span>`;
                } else if (d.severity === "WARNING") {
                    sevBadge = `<span class="bg-tertiary-container text-on-tertiary-container px-2 py-0.5 rounded text-[11px] font-bold">WARNING</span>`;
                }

                const firstSeen = d.first_seen ? d.first_seen.replace("T", " ").substring(0, 19) : "—";
                const lastSeen = d.last_seen ? d.last_seen.replace("T", " ").substring(0, 19) : "—";

                html += `
                <tr class="hover:bg-surface-container transition-colors border-b border-outline-variant/30">
                  <td class="py-2.5 pr-4 font-bold text-primary">${escapeHtml(d.occurrence_count)}x</td>
                  <td class="py-2.5 pr-4">${sevBadge}</td>
                  <td class="py-2.5 pr-4 font-bold text-on-surface">${escapeHtml(d.issue_type)}</td>
                  <td class="py-2.5 pr-4"><span class="bg-primary-container text-on-primary-container px-1.5 py-0.5 rounded mr-1 text-[10px]">${escapeHtml(d.method)}</span>${escapeHtml(d.endpoint)}</td>
                  <td class="py-2.5 pr-4 text-on-surface-variant truncate max-w-xs" title="${escapeHtml(d.message)}">${escapeHtml(d.message)}</td>
                  <td class="py-2.5 pr-4 text-on-surface-variant text-[11px]">${firstSeen}</td>
                  <td class="py-2.5 text-on-surface-variant text-[11px]">${lastSeen}</td>
                </tr>`;
            });
            tbody.innerHTML = html;
        } catch (err) {
            console.debug("Error updating drift stats:", err);
        }
    }

    // Fetch report from server
    async function fetchReport(force = false) {
        try {
            const res = await fetch("/api/report", { cache: "no-store" });
            if (!res.ok) return;
            const text = await res.text();
            if (force || text !== lastReportDataJson) {
                lastReportDataJson = text;
                const data = JSON.parse(text);
                updateDashboardUI(data);
            }
            await fetchDriftStats();
        } catch (err) {
            // Silently handle transient connection loss
            console.debug("Live sync polling error:", err);
        }
    }

    // Start live polling loop
    function startRealTimePolling() {
        if (isPolling) return;
        isPolling = true;
        fetchReport(true);
        fetchDriftStats();
        pollIntervalId = setInterval(() => {
            fetchReport(false);
        }, 1500);
    }

    document.addEventListener("DOMContentLoaded", () => {
        // Wire search and filter inputs
        const searchInput = document.getElementById("global-search-input");
        const methodSelect = document.getElementById("filter-method");
        const statusSelect = document.getElementById("filter-status");

        if (searchInput) searchInput.addEventListener("input", applyFilters);
        if (methodSelect) methodSelect.addEventListener("change", applyFilters);
        if (statusSelect) statusSelect.addEventListener("change", applyFilters);

        // Manual Refresh Button
        const refreshBtn = document.getElementById("btn-manual-refresh");
        if (refreshBtn) {
            refreshBtn.addEventListener("click", async () => {
                refreshBtn.classList.add("opacity-50");
                await fetchReport(true);
                setTimeout(() => refreshBtn.classList.remove("opacity-50"), 300);
            });
        }

        // Clear History Button
        const clearBtn = document.getElementById("btn-clear-report");
        if (clearBtn) {
            clearBtn.addEventListener("click", async () => {
                if (confirm("Clear all recorded validation history in dashboard?")) {
                    try {
                        await fetch("/api/report/clear", { method: "POST" });
                        await fetchReport(true);
                    } catch (e) {
                        console.error("Failed to clear report:", e);
                    }
                }
            });
        }

        // Start live polling
        startRealTimePolling();
    });
})();
