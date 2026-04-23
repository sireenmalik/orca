# ORCA Frontend Skill
**Read this before touching dashboard/src/App.jsx.**

> **Baseline tagged `v1.0.0`.** Invariants below are pinned by the
> E2E suite; frontend-only items are verified by loading the dashboard
> and checking that the ChurnTab renders + the Security tab updates on
> remediation.

## Frontend invariants (must not break)

**α. Define `churnHistory` and `churnForecast` at module scope.** These
drive the sparkline in ChurnTab. Removing them throws ReferenceError
and the entire Churn tab goes blank (no error boundary).

**β. AgentLogPanel auto-scroll respects a 100px bottom-proximity check.**
Use `containerRef` on the scrollable div, and only set
`el.scrollTop = el.scrollHeight` when the user is already within 100px
of the bottom. Don't use `scrollIntoView` unconditionally — the log
will snap-back on every new event and the operator can't read.

**γ. Security alert status colors:** `active` → red, `remediated` /
`resolved` / `blocked` → green, anything containing `revert` → yellow.
Render `remediated` as `✓ remediated`. Expose the remediation PR link
alongside the evidence PR link when `ev.remediation_pr_url` is set.

**δ. Churn KPIs + sparkline derive from live risk data.** `liveChurn` is
the average of `churn_probability_pct` across LSPs; `liveForecast[0].v
= liveChurn × 0.95`; the sparkline's last history point is `liveChurn`
(not the static April value), and the forecast band retracks as risk
bands shift.

**ε. D3 topology utilization labels are 17px bold monospace.**

---

## Theme

```javascript
const C = {
  bg: "#0a0f1e",      panel: "#111827",   border: "#1e293b",
  text: "#e2e8f0",    muted: "#64748b",   green: "#10b981",
  yellow: "#eab308",  orange: "#f97316",  red: "#ef4444",
  blue: "#06b6d4",    purple: "#8b5cf6",  accent: "#06b6d4",
};
const utilColor = u => u >= 90 ? C.red : u >= 80 ? C.orange : u >= 60 ? C.yellow : C.green;
const sevColor = { critical: "#ef4444", high: "#f97316", medium: "#eab308",
                   warning: "#eab308", low: "#06b6d4", info: "#8b5cf6" };
```

Always use `C.*` constants. Never hardcode hex colours in components.

---

## Tab Structure

Four tabs: `ops` | `contracts` | `security` | `churn`

All tabs receive `events` prop (WebSocket event array, last 500).

```javascript
{activeTab === "ops" && <OperationsTab state={state} events={events} ... />}
{activeTab === "security" && <SecurityTab events={events} />}
{activeTab === "churn" && <ChurnTab events={events} />}
```

---

## Operations Tab Layout

```
┌─ 60% LEFT ─────────────────────────────┐ ┌─ 40% RIGHT ──────┐
│ Topology (D3)    │ Agent status + LSPs  │ │ Agent Log        │
│                  │ (210px sidebar)      │ │ (full height)    │
├──────────────────┴──────────────────────┤ │                  │
│ Controls slim bar (full width)          │ │                  │
├────────────────────────────┬────────────┤ │                  │
│ Config Proposals           │ Alarms     │ │                  │
│ (flex:1)                   │ (160px)    │ │                  │
│                            ├────────────┤ │                  │
│                            │ Email Outbox│ │                  │
│                            │ (flex:1)   │ │                  │
└────────────────────────────┴────────────┘ └──────────────────┘
```

---

## Key Components

### Panel
```javascript
<Panel title="..." badge={n} style={{...}}>
  {children}
</Panel>
```
`badge` shows red pill if > 0.

### Modal (draggable)
```javascript
<Modal title="..." onClose={fn} width="1040px">
  {children}
</Modal>
```
Esc key closes. Draggable by header.

### LogEntry
Reads from `entry.data.*` — not `entry.message` directly.
```javascript
const msg = entry.message || entry.msg
  || data.message || data.command || data.text
  || (data.tool && data.inputs ? `${data.tool}(...)` : null)
  || JSON.stringify(data);
```

### EmailCard
Expandable card showing full email body with clickable links.
GitHub links auto-extracted as quick-access buttons (PR #N, 📚 Episode, 🔐 Evidence).

### ConfigModal
Three-panel layout:
- **Left sidebar (210px):** Status → Reason + projected improvement → 6 validation checks with ✅/❌ + detail text
- **Center:** Diff panel — red `−` lines, green `+` lines, left border colored
- **Right (220px):** Proposed config (add lines only, green text)
- **Bottom:** Device tabs + comment + 4 action buttons (Reject / Save / Save & Commit / Approve & Push)

---

## Log Type → Style Mapping

```javascript
const logTypeStyle = {
  alert:         { bg: "#ef444418", color: C.red,    label: "ALERT" },
  reasoning:     { bg: "#8b5cf618", color: C.purple, label: "THINK" },
  agent_thinking:{ bg: "#8b5cf618", color: C.purple, label: "THINK" },
  tool_call:     { bg: "#06b6d418", color: C.blue,   label: "TOOL"  },
  tool_result:   { bg: "#10b98118", color: C.green,  label: "RESULT"},
  tool_error:    { bg: "#ef444418", color: C.red,    label: "ERROR" },
  notification:  { bg: "#eab30818", color: C.yellow, label: "NOTIFY"},
  status:        { bg: "#10b98118", color: C.green,  label: "STATUS"},
  agent_status:  { bg: "#10b98118", color: C.green,  label: "STATUS"},
  git_command:   { bg: "#06b6d418", color: C.blue,   label: "GIT"   },
  pr_opened:     { bg: "#8b5cf618", color: C.purple, label: "PR"    },
  netconf_push:  { bg: "rgba(16,185,129,0.10)", color: C.green, label: "NETCONF"},
  state_update:  { bg: "rgba(255,255,255,0.02)", color: C.muted, label: "STATE"},
};
```

---

## WebSocket Event Handling Pattern

```javascript
// In useEffect — filter meaningful events
const meaningful = events.filter(e => e.type !== "state_update");

// state_update is handled separately
useEffect(() => {
  const latest = [...events].reverse().find(e => e.type === "state_update");
  if (latest?.data) setState(latest.data);
}, [events]);

// Security: listen for BOTH types
events.filter(e => e.type === "security_alert" || e.type === "security_alarm")

// Provisional alert replacement
setAlerts(prev => {
  const merged = [...prev];
  sec.forEach(a => {
    const idx = merged.findIndex(e => e.node === a.node && e.provisional);
    if (idx >= 0) merged[idx] = { ...merged[idx], ...a };
    else merged.push(a);
  });
  return merged;
});
```

---

## Config Proposal Card

Security proposals get red border + SECURITY badge:
```javascript
borderLeft: `3px solid ${cfg.security ? C.red : C.blue}`
{cfg.security && <span style={{...red badge...}}>SECURITY</span>}
```

---

## Config Proposal → Modal Data Flow

The modal reads changes with `device` key (agent sends this):
```javascript
changes.forEach(ch => {
  const node = ch.device || ch.node || ch.router || "Router";
  // current_config → remove lines
  // new_config → add lines
  // diff_summary → tab title
});
```

Validation normalisation — agent may send booleans or strings:
```javascript
const norm = v => typeof v === "boolean" ? v : !String(v).trim().startsWith("❌");
const rawChecks = proposal.validation_checks || proposal.validation || {};
```

Always render all 6 checks even if not present (default `true`):
```javascript
const checks = {
  syntax:       { pass: norm(rawChecks.syntax       ?? true), ... },
  semantic:     { pass: norm(rawChecks.semantic     ?? true), ... },
  mission_1:    { pass: norm(rawChecks.mission_1    ?? true), ... },
  mission_2:    { pass: norm(rawChecks.mission_2    ?? true), ... },
  digital_twin: { pass: norm(rawChecks.digital_twin ?? true), ... },
  policy:       { pass: norm(rawChecks.policy       ?? true), ... },
};
```

---

## Timestamp Parsing

Agent sends timestamps as ISO strings (not epoch):
```javascript
const ts = (() => {
  if (!entry.timestamp) return "";
  const t = entry.timestamp;
  if (typeof t === "string" && isNaN(Number(t))) return t; // already formatted
  const ms = Number(t) < 1e10 ? Number(t) * 1000 : Number(t); // epoch seconds
  const d = new Date(ms);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
})();
```

---

## Performance Rules

- Use `memo()` on `LogEntry` — high frequency renders
- Use `useMemo` for filtered event lists
- Use `useLayoutEffect` for auto-scroll (not `useEffect`)
- Stable keys on log entries — use index (entries never reorder)
- `useCallback` with stable dep arrays for D3 draw functions

---

## Python 3.11 Compat (critical)

The server runs Python 3.11. **Backslashes inside f-string expressions are a SyntaxError.**

```python
# WRONG — crashes on Python 3.11
f'git commit -m "cfg({",".join(routers)}): {proposal.get(\"title\", \"update\")}"'

# CORRECT — extract variables first
routers_str = ",".join(routers)
commit_title = proposal.get("title", "update")
f'git commit -m "cfg({routers_str}): {commit_title}"'
```
