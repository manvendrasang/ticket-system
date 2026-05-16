"""
Optional dashboard — FastAPI + HTML UI for viewing audit logs in real time.

Run with: python -m uvicorn dashboard.app:app --reload --port 8000
Or via Docker: dashboard is served on port 8000
"""

import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

LOGS_DIR = Path(__file__).parent.parent / "logs"
AUDIT_LOG_PATH = LOGS_DIR / "audit_log.json"

app = FastAPI(title="ShopWave Agent Dashboard", version="1.0.0")


def load_audit_log() -> list[dict]:
    if not AUDIT_LOG_PATH.exists():
        return []
    events = []
    with open(AUDIT_LOG_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


@app.get("/api/events")
async def get_events(
    outcome: Optional[str] = Query(None),
    escalated: Optional[bool] = Query(None),
    tier: Optional[str] = Query(None),
) -> JSONResponse:
    events = load_audit_log()
    
    if outcome:
        events = [e for e in events if e.get("outcome") == outcome]
    if escalated is not None:
        events = [e for e in events if e.get("escalated") == escalated]
    if tier:
        events = [e for e in events if e.get("customer_tier") == tier]
    
    return JSONResponse({"events": events, "total": len(events)})


@app.get("/api/stats")
async def get_stats() -> JSONResponse:
    events = load_audit_log()
    if not events:
        return JSONResponse({"total": 0})
    
    outcomes = {}
    for e in events:
        o = e.get("outcome", "unknown")
        outcomes[o] = outcomes.get(o, 0) + 1
    
    avg_tools = sum(len(e.get("tool_calls", [])) for e in events) / len(events)
    avg_duration = sum(e.get("processing_duration_ms", 0) for e in events) / len(events)
    escalated = sum(1 for e in events if e.get("escalated"))
    
    return JSONResponse({
        "total": len(events),
        "escalated": escalated,
        "auto_resolved": len(events) - escalated,
        "outcomes": outcomes,
        "avg_tool_calls": round(avg_tools, 1),
        "avg_duration_ms": round(avg_duration),
        "fraud_signals": sum(1 for e in events if e.get("fraud_signals")),
    })


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShopWave Agent Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; }
  header { background: #1a1d2e; border-bottom: 1px solid #2d3748; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.2rem; font-weight: 700; color: #63b3ed; }
  header .sub { color: #718096; font-size: 0.8rem; }
  .badge { background: #2d3748; border-radius: 12px; padding: 2px 10px; font-size: 0.75rem; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; padding: 24px; }
  .stat-card { background: #1a1d2e; border: 1px solid #2d3748; border-radius: 8px; padding: 16px; text-align: center; }
  .stat-card .value { font-size: 2rem; font-weight: 700; color: #63b3ed; }
  .stat-card .label { font-size: 0.75rem; color: #718096; margin-top: 4px; }
  .filters { padding: 0 24px 16px; display: flex; gap: 12px; flex-wrap: wrap; }
  .filters select, .filters button { background: #2d3748; color: #e2e8f0; border: 1px solid #4a5568; border-radius: 6px; padding: 6px 12px; font-size: 0.85rem; cursor: pointer; }
  .filters button:hover { background: #4a5568; }
  .filters button.active { background: #2b6cb0; border-color: #3182ce; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .table-wrapper { padding: 0 24px 24px; overflow-x: auto; }
  th { background: #1a1d2e; color: #718096; text-align: left; padding: 8px 12px; border-bottom: 1px solid #2d3748; font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
  td { padding: 10px 12px; border-bottom: 1px solid #1a1d2e; vertical-align: top; }
  tr:hover td { background: #1a1d2e; }
  .badge-outcome { padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .outcome-refund_issued { background: #1c4532; color: #68d391; }
  .outcome-escalated { background: #744210; color: #f6ad55; }
  .outcome-informed { background: #1a365d; color: #63b3ed; }
  .outcome-error { background: #742a2a; color: #fc8181; }
  .outcome-unknown { background: #2d3748; color: #a0aec0; }
  .tier-vip { color: #f6ad55; font-weight: 700; }
  .tier-premium { color: #63b3ed; font-weight: 600; }
  .tier-standard { color: #a0aec0; }
  .fraud-flag { color: #fc8181; font-size: 0.7rem; }
  .tool-list { display: flex; flex-wrap: wrap; gap: 3px; max-width: 300px; }
  .tool-chip { background: #2d3748; border-radius: 3px; padding: 1px 5px; font-size: 0.65rem; color: #a0aec0; }
  .tool-chip.write { background: #2c3a4a; color: #63b3ed; }
  .tool-chip.error { background: #3d2020; color: #fc8181; }
  .conf { font-size: 0.75rem; }
  .conf.high { color: #68d391; }
  .conf.mid { color: #f6ad55; }
  .conf.low { color: #fc8181; }
  .duration { color: #718096; font-size: 0.8rem; }
  .empty { text-align: center; padding: 48px; color: #4a5568; }
  .refresh-btn { margin-left: auto; background: #2b6cb0 !important; color: white !important; }
  #last-updated { color: #4a5568; font-size: 0.75rem; margin-left: auto; }
</style>
</head>
<body>
<header>
  <div>
    <h1>🛍️ ShopWave Agent Dashboard</h1>
    <div class="sub">Autonomous Support Resolution — Real-time Audit Log</div>
  </div>
  <span id="last-updated"></span>
  <button class="filters" onclick="loadData()" style="margin-left:auto; background:#2b6cb0; border:none; color:white; padding:8px 16px; border-radius:6px; cursor:pointer;">↻ Refresh</button>
</header>

<div class="stats-grid" id="stats-grid">
  <div class="stat-card"><div class="value" id="s-total">—</div><div class="label">Total Tickets</div></div>
  <div class="stat-card"><div class="value" id="s-resolved" style="color:#68d391">—</div><div class="label">Auto-Resolved</div></div>
  <div class="stat-card"><div class="value" id="s-escalated" style="color:#f6ad55">—</div><div class="label">Escalated</div></div>
  <div class="stat-card"><div class="value" id="s-tools" style="color:#b794f4">—</div><div class="label">Avg Tool Calls</div></div>
  <div class="stat-card"><div class="value" id="s-duration" style="color:#76e4f7">—</div><div class="label">Avg Duration (ms)</div></div>
  <div class="stat-card"><div class="value" id="s-fraud" style="color:#fc8181">—</div><div class="label">Fraud Signals</div></div>
</div>

<div class="filters">
  <label style="color:#718096;font-size:0.8rem;align-self:center">Filter:</label>
  <select id="filter-outcome" onchange="renderTable()">
    <option value="">All Outcomes</option>
    <option value="refund_issued">Refund Issued</option>
    <option value="escalated">Escalated</option>
    <option value="informed">Informed</option>
    <option value="error">Error</option>
  </select>
  <select id="filter-tier" onchange="renderTable()">
    <option value="">All Tiers</option>
    <option value="vip">VIP</option>
    <option value="premium">Premium</option>
    <option value="standard">Standard</option>
  </select>
  <select id="filter-escalated" onchange="renderTable()">
    <option value="">Escalated: All</option>
    <option value="true">Escalated Only</option>
    <option value="false">Auto-Resolved Only</option>
  </select>
</div>

<div class="table-wrapper">
<table>
  <thead>
    <tr>
      <th>Ticket</th>
      <th>Customer</th>
      <th>Tier</th>
      <th>Classification</th>
      <th>Outcome</th>
      <th>Tools Called</th>
      <th>Conf</th>
      <th>Duration</th>
      <th>Fraud</th>
    </tr>
  </thead>
  <tbody id="events-tbody">
    <tr><td colspan="9" class="empty">Loading…</td></tr>
  </tbody>
</table>
</div>

<script>
let allEvents = [];

const WRITE_TOOLS = new Set(['issue_refund', 'send_reply', 'escalate', 'check_refund_eligibility']);

async function loadData() {
  try {
    const [evtsRes, statsRes] = await Promise.all([
      fetch('/api/events'),
      fetch('/api/stats')
    ]);
    const evts = await evtsRes.json();
    const stats = await statsRes.json();
    allEvents = evts.events || [];
    updateStats(stats);
    renderTable();
    document.getElementById('last-updated').textContent = 'Updated: ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error(e);
  }
}

function updateStats(s) {
  document.getElementById('s-total').textContent = s.total || 0;
  document.getElementById('s-resolved').textContent = s.auto_resolved || 0;
  document.getElementById('s-escalated').textContent = s.escalated || 0;
  document.getElementById('s-tools').textContent = s.avg_tool_calls || '—';
  document.getElementById('s-duration').textContent = s.avg_duration_ms || '—';
  document.getElementById('s-fraud').textContent = s.fraud_signals || 0;
}

function renderTable() {
  const outFilter = document.getElementById('filter-outcome').value;
  const tierFilter = document.getElementById('filter-tier').value;
  const escFilter = document.getElementById('filter-escalated').value;

  let events = allEvents.filter(e => {
    if (outFilter && e.outcome !== outFilter) return false;
    if (tierFilter && e.customer_tier !== tierFilter) return false;
    if (escFilter === 'true' && !e.escalated) return false;
    if (escFilter === 'false' && e.escalated) return false;
    return true;
  });

  const tbody = document.getElementById('events-tbody');
  if (!events.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">No events found. Run the agent to generate audit logs.</td></tr>';
    return;
  }

  tbody.innerHTML = events.map(e => {
    const cls = e.classification || {};
    const conf = e.confidence || 0;
    const confClass = conf >= 0.8 ? 'high' : conf >= 0.6 ? 'mid' : 'low';
    const tierClass = e.customer_tier ? `tier-${e.customer_tier}` : 'tier-standard';
    const outcome = e.outcome || 'unknown';
    const tools = (e.tool_calls || []);
    const frauds = (e.fraud_signals || []).filter(Boolean);
    const retries = (e.retry_events || []).length;

    const toolChips = tools.map(t => {
      const cls2 = t.status !== 'success' ? 'error' : WRITE_TOOLS.has(t.tool) ? 'write' : '';
      return `<span class="tool-chip ${cls2}" title="${t.tool}: ${t.status} (${t.duration_ms}ms)">${t.tool.replace('_', ' ')}</span>`;
    }).join('');

    return `<tr>
      <td><strong>${e.ticket_id}</strong>${retries > 0 ? `<br><span style="color:#f6ad55;font-size:0.7rem">⚠ ${retries} retry</span>` : ''}</td>
      <td style="font-size:0.8rem">${e.customer_email}<br><span style="color:#4a5568">${e.customer_tier || '—'}</span></td>
      <td><span class="${tierClass}">${(e.customer_tier || '—').toUpperCase()}</span></td>
      <td style="font-size:0.75rem">
        <div>${cls.category || '—'}</div>
        <div style="color:#718096">${cls.urgency || ''} · ${cls.resolvability || ''}</div>
      </td>
      <td><span class="badge-outcome outcome-${outcome}">${outcome.replace('_', ' ')}</span>${e.escalated ? '<br><span style="color:#f6ad55;font-size:0.7rem">↑ escalated</span>' : ''}</td>
      <td><div class="tool-list">${toolChips || '<span style="color:#4a5568">none</span>'}</div></td>
      <td><span class="conf ${confClass}">${(conf * 100).toFixed(0)}%</span></td>
      <td><span class="duration">${e.processing_duration_ms || '—'}ms</span></td>
      <td>${frauds.length ? frauds.map(f => `<span class="fraud-flag">⚠ ${f}</span>`).join('<br>') : '<span style="color:#2d3748">—</span>'}</td>
    </tr>`;
  }).join('');
}

// Load on startup and auto-refresh every 10s
loadData();
setInterval(loadData, 10000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
