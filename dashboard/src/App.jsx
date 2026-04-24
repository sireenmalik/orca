import { useEffect, useLayoutEffect, useRef, useState, useCallback, useMemo, memo, Fragment } from "react";
import * as d3 from "d3";

const API = "";
const WS_URL = `ws://${window.location.host}/ws`;

// ─── THEME ────────────────────────────────────────────────────────────────────
const C = {
  bg: "#0a0f1e", panel: "#111827", border: "#1e293b", text: "#e2e8f0",
  muted: "#64748b", green: "#10b981", yellow: "#eab308", orange: "#f97316",
  red: "#ef4444", blue: "#06b6d4", purple: "#8b5cf6", accent: "#06b6d4",
};
const utilColor = u => u >= 90 ? C.red : u >= 80 ? C.orange : u >= 60 ? C.yellow : C.green;
const sevColor = { critical: "#ef4444", high: "#f97316", medium: "#eab308", warning: "#eab308", low: "#06b6d4", info: "#8b5cf6" };

// ─── FLUID TYPOGRAPHY ─────────────────────────────────────────────────────────
// Every text size is clamp(teams-safe-min, viewport-responsive-preferred,
// 27"-monitor-cap). Viewport-based so the dashboard stays readable over a
// Teams screen share (typically compressed to ~1280px wide for the viewer)
// without ballooning on a 2560px display. Read DEMO_README "pre-flight
// checklist" before tuning any of these — there's a Teams-share test that
// must pass on: logEntry, proposalReason, sliceName, topoLspLabel.
const FS = {
  // Generic
  body:            "clamp(13px, 1.0vw, 15px)",
  header:          "clamp(14px, 1.15vw, 17px)",
  tabNav:          "clamp(13px, 1.05vw, 15px)",
  // Agent reasoning log
  logEntry:        "clamp(14px, 1.15vw, 17px)",
  logTimestamp:    "clamp(11px, 0.85vw, 13px)",
  logBadge:        "clamp(10px, 0.8vw, 12px)",
  // Config proposals
  proposalTitle:   "clamp(15px, 1.2vw, 18px)",
  proposalReason:  "clamp(13px, 1.1vw, 16px)",
  diff:            "clamp(13px, 1.1vw, 16px)",
  validationLabel: "clamp(12px, 1.0vw, 14px)",
  // LSP sidebar
  lspName:         "clamp(13px, 1.0vw, 15px)",
  lspPath:         "clamp(12px, 0.95vw, 14px)",
  lspBandwidth:    "clamp(12px, 0.95vw, 14px)",
  // Slice legend (HTML portion of topology)
  sliceName:       "clamp(13px, 1.0vw, 15px)",
  sliceMeta:       "clamp(12px, 0.95vw, 14px)",
  // SVG labels on the topology canvas (set via .style not .attr so clamp parses)
  topoUtil:        "clamp(12px, 0.95vw, 14px)",
  topoLspLabel:    "clamp(12px, 0.95vw, 14px)",
  topoNodeLabel:   "clamp(11px, 0.9vw, 13px)",
  // Alarms
  alarm:           "clamp(13px, 1.05vw, 15px)",
  alarmSev:        "clamp(11px, 0.9vw, 13px)",
  // Email outbox
  emailSubject:    "clamp(13px, 1.05vw, 15px)",
  emailBody:       "clamp(12px, 1.0vw, 14px)",
};

// Minimum sizes (px) for each resizable pane — enforced in Split via minPx.
// Below these the content becomes unreadable on a Teams share.
const MIN = {
  topology:     { w: 600, h: 400 },
  agentLog:     { w: 340, h: 320 },
  configProps:  { w: 400, h: 220 },
  lspsSidebar:  { w: 240, h: 300 },
  alarms:       { w: 260, h: 160 },
  emails:       { w: 260, h: 180 },
  controlsBar:  { w: 0,   h: 50  },
};

// ─── CHURN CHART DATA (static — drives the forecast sparkline in ChurnTab) ───
const churnHistory = [
  { m: "Nov", v: 3.1 },
  { m: "Dec", v: 3.3 },
  { m: "Jan", v: 3.6 },
  { m: "Feb", v: 3.8 },
  { m: "Mar", v: 3.5 },
  { m: "Apr", v: 3.4 },
];
const churnForecast = [
  { m: "May", v: 3.2, lo: 2.8, hi: 3.6 },
  { m: "Jun", v: 3.0, lo: 2.5, hi: 3.5 },
  { m: "Jul", v: 2.8, lo: 2.2, hi: 3.4 },
  { m: "Aug", v: 2.7, lo: 2.0, hi: 3.4 },
  { m: "Sep", v: 2.6, lo: 1.8, hi: 3.4 },
  { m: "Oct", v: 2.5, lo: 1.6, hi: 3.4 },
];

// ─── SPLIT PANE ───────────────────────────────────────────────────────────────
// Lightweight resizable split container. Drag the 6px divider between
// panes to resize; sizes are stored in state as percentages so the layout
// reflows on window resize without losing user-chosen proportions.
//
//   <Split direction="horizontal" defaultSizes={[60, 40]}>
//     <LeftPane />
//     <RightPane />
//   </Split>
//
// Children must be valid elements (one per pane). Size count must match
// children count, summing to ~100. minPct keeps a pane from being dragged
// to zero width/height.
function Split({ direction = "horizontal", defaultSizes, minPx, storageKey, children, minPct = 4, dividerColor }) {
  const arr = Array.isArray(children) ? children.filter(Boolean) : [children];
  const containerRef = useRef(null);
  // Hydrate from localStorage if a key is provided; tolerate malformed values.
  const initial = (() => {
    if (storageKey) {
      try {
        const raw = localStorage.getItem(storageKey);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.length === arr.length
              && parsed.every(n => typeof n === "number" && n > 0)) {
            return parsed;
          }
        }
      } catch { /* ignore */ }
    }
    return defaultSizes && defaultSizes.length === arr.length
      ? defaultSizes
      : Array(arr.length).fill(100 / arr.length);
  })();
  const [sizes, setSizes] = useState(initial);
  const dragState = useRef(null);
  const isHoriz = direction === "horizontal";

  // Persist on every settled change. Cheap write, debounced via state update.
  useEffect(() => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, JSON.stringify(sizes)); } catch { /* ignore quota */ }
  }, [sizes, storageKey]);

  const onDividerDown = (i) => (e) => {
    e.preventDefault();
    const rect = containerRef.current.getBoundingClientRect();
    const totalPx = isHoriz ? rect.width : rect.height;
    // Convert per-pane pixel minimums to per-pane percent mins for this
    // frame. If minPx isn't supplied, fall back to the global minPct floor.
    const pctMin = (i_) => {
      if (minPx && minPx[i_] != null && totalPx > 0) {
        return Math.max(minPct, (minPx[i_] / totalPx) * 100);
      }
      return minPct;
    };
    dragState.current = {
      idx: i,
      startCoord: isHoriz ? e.clientX : e.clientY,
      startSizes: [...sizes],
      total: totalPx,
      minA: pctMin(i),
      minB: pctMin(i + 1),
    };
    const onMove = (me) => {
      const ds = dragState.current;
      if (!ds || !ds.total) return;
      const deltaPx = (isHoriz ? me.clientX : me.clientY) - ds.startCoord;
      const deltaPct = (deltaPx / ds.total) * 100;
      const next = [...ds.startSizes];
      let a = ds.startSizes[ds.idx] + deltaPct;
      let b = ds.startSizes[ds.idx + 1] - deltaPct;
      // Clamp at either minimum — if we hit one, snap to it instead of
      // discarding the drag (so the handle physically stops at the min
      // rather than refusing to move).
      if (a < ds.minA) { a = ds.minA; b = ds.startSizes[ds.idx] + ds.startSizes[ds.idx + 1] - a; }
      if (b < ds.minB) { b = ds.minB; a = ds.startSizes[ds.idx] + ds.startSizes[ds.idx + 1] - b; }
      next[ds.idx] = a;
      next[ds.idx + 1] = b;
      setSizes(next);
    };
    const onUp = () => {
      dragState.current = null;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = isHoriz ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const dividerBg = dividerColor || "rgba(255,255,255,0.04)";
  const dividerHoverBg = "rgba(6,182,212,0.35)";

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        flexDirection: isHoriz ? "row" : "column",
        width: "100%",
        height: "100%",
        minWidth: 0,
        minHeight: 0,
      }}
    >
      {arr.map((child, i) => (
        <Fragment key={i}>
          <div
            style={{
              flex: `0 0 ${sizes[i]}%`,
              minWidth: 0,
              minHeight: 0,
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            {child}
          </div>
          {i < arr.length - 1 && (
            <div
              onMouseDown={onDividerDown(i)}
              onMouseEnter={(e) => (e.currentTarget.style.background = dividerHoverBg)}
              onMouseLeave={(e) => (e.currentTarget.style.background = dividerBg)}
              style={{
                flex: "0 0 6px",
                background: dividerBg,
                cursor: isHoriz ? "col-resize" : "row-resize",
                transition: "background 0.15s",
                zIndex: 2,
              }}
            />
          )}
        </Fragment>
      ))}
    </div>
  );
}

// ─── SHARED PANEL ─────────────────────────────────────────────────────────────
function Panel({ title, badge, children, style }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, display: "flex", flexDirection: "column", overflow: "hidden", ...style }}>
      {title && (
        <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
          <span style={{ fontSize: FS.header, fontWeight: 700, color: C.text, letterSpacing: 0.3 }}>{title}</span>
          {badge != null && badge > 0 && <span style={{ fontSize: FS.logBadge, fontWeight: 700, padding: "2px 7px", borderRadius: 10, background: C.red + "22", color: C.red, fontFamily: "monospace" }}>{badge}</span>}
        </div>
      )}
      <div style={{ flex: 1, overflow: "auto", padding: 12 }}>{children}</div>
    </div>
  );
}

// ─── DRAGGABLE MODAL ──────────────────────────────────────────────────────────
function Modal({ title, onClose, children, width = "780px" }) {
  const [pos, setPos] = useState(null);
  const dragging = useRef(false);
  const dragStart = useRef({ mx: 0, my: 0, px: 0, py: 0 });
  const modalRef = useRef(null);
  useEffect(() => {
    const onKey = e => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const onMouseDown = (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    dragging.current = true;
    const rect = modalRef.current?.getBoundingClientRect();
    const startX = pos ? pos.x : (window.innerWidth / 2 - rect.width / 2);
    const startY = pos ? pos.y : (window.innerHeight / 2 - rect.height / 2);
    dragStart.current = { mx: e.clientX, my: e.clientY, px: startX, py: startY };
    const onMove = (ev) => {
      if (!dragging.current) return;
      setPos({ x: dragStart.current.px + ev.clientX - dragStart.current.mx, y: dragStart.current.py + ev.clientY - dragStart.current.my });
    };
    const onUp = () => { dragging.current = false; window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };
  const posStyle = pos ? { position: "fixed", left: pos.x, top: pos.y, transform: "none", margin: 0 } : { position: "relative" };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: "20px" }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={modalRef} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10, width, maxWidth: "96vw", maxHeight: "92vh", display: "flex", flexDirection: "column", boxShadow: "0 24px 60px rgba(0,0,0,0.8)", ...posStyle }}>
        <div onMouseDown={onMouseDown} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "13px 18px", borderBottom: `1px solid ${C.border}`, flexShrink: 0, cursor: "grab", userSelect: "none", background: "#151d2e", borderRadius: "10px 10px 0 0" }}>
          <span style={{ color: C.text, fontWeight: 700, fontSize: 14 }}>{title}</span>
          <button onClick={onClose} style={{ background: "transparent", border: "none", color: C.muted, fontSize: 20, cursor: "pointer" }}>×</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>{children}</div>
      </div>
    </div>
  );
}

// ─── TOPOLOGY ─────────────────────────────────────────────────────────────────
// v2 demo: 5-column layout — gNBs (RAN) → PEs → P core → PEs → UPFs.
// Role → column index map drives x; top/bottom within a column is hard-coded
// by node id so PE-01/P-02/PE-03/UPF-01 sit on the slice-A rail and
// PE-02/P-01/PE-04/UPF-02 sit on the slice-B rail.
const NODE_COLUMN = {
  "gNB-1": 0, "gNB-2": 0,
  "PE-01": 1, "PE-02": 1,
  "P-02":  2, "P-01":  2,
  "PE-03": 3, "PE-04": 3,
  "UPF-01": 4, "UPF-02": 4,
};
const NODE_ROW = {
  "gNB-1": 0, "PE-01": 0, "P-02": 0, "PE-03": 0, "UPF-01": 0,  // top rail = slice A
  "gNB-2": 1, "PE-02": 1, "P-01": 1, "PE-04": 1, "UPF-02": 1,  // bottom rail = slice B
};
const ROLE_STYLE = {
  ran:  { fill: "#d97706", stroke: "#f59e0b", shape: "rect",   label: C.text },  // amber
  edge: { fill: "#1f6feb", stroke: C.accent,  shape: "circle", label: C.text },  // blue
  core: { fill: "#0e4a9e", stroke: C.accent,  shape: "circle", label: C.text },  // dark blue
  upf:  { fill: "#0891b2", stroke: C.blue,    shape: "rect",   label: C.text },  // cyan
};
const SLICE_COLOR = { "slice-A": "#a855f7", "slice-B": "#22c55e" };  // purple / green

function TopologyMap({ nodes, links, lsps, slices }) {
  const wrapRef = useRef(null);
  const svgRef = useRef(null);
  const stateKey = JSON.stringify({ nodes, links, lsps, slices });

  const draw = useCallback(() => {
    if (!nodes || !links || !svgRef.current || !wrapRef.current) return;
    const W = wrapRef.current.clientWidth || 600;
    const H = wrapRef.current.clientHeight || 380;
    d3.select(svgRef.current).selectAll("*").remove();
    const svg = d3.select(svgRef.current).attr("width", W).attr("height", H);

    // Scale everything proportionally to container. Target design size is
    // ~900×500; if the panel is smaller we shrink, larger we stretch
    // (capped so nodes don't get absurdly huge on fullscreen).
    const designW = 900, designH = 500;
    const scale = Math.min(Math.max(Math.min(W / designW, H / designH), 0.45), 1.3);
    const NODE_R  = 22 * scale;
    const RECT_W  = 64 * scale;
    const RECT_H  = 36 * scale;
    // Topology label font sizes now come from FS.topoUtil / FS.topoLspLabel /
    // FS.topoNodeLabel (viewport-driven clamp) — the panel-local `scale`
    // only shapes node geometry, not text.

    const padX = Math.max(28, 55 * scale);
    const padY = Math.max(30, 50 * scale);
    const colW = (W - padX * 2) / 4;
    const rowH = H - padY * 2 - 20;
    const colX = i => padX + i * colW;
    const rowY = i => padY + i * rowH + 10;

    const pos = {};
    Object.keys(nodes).forEach(id => {
      const c = NODE_COLUMN[id]; const r = NODE_ROW[id];
      if (c === undefined || r === undefined) return;
      pos[id] = { x: colX(c), y: rowY(r) };
    });

    const nodeData = Object.entries(nodes)
      .filter(([id]) => pos[id])
      .map(([id, n]) => ({ id, ...n, ...pos[id] }));

    const linkData = Object.entries(links).map(([id, l]) => {
      const srcId = l.src_node || l.src;
      const dstId = l.dst_node || l.dst;
      return {
        id, ...l,
        s: pos[srcId], t: pos[dstId],
        util: l.utilization_pct || 0,
        is_stub: !!l.is_stub,
      };
    }).filter(d => d.s && d.t);

    // 1. Stub + transport links — stubs dashed/thinner/grey, transport coloured by util
    svg.append("g").selectAll("line.core-link").data(linkData.filter(d => !d.is_stub)).enter()
      .append("line")
        .attr("x1", d => d.s.x).attr("y1", d => d.s.y)
        .attr("x2", d => d.t.x).attr("y2", d => d.t.y)
        .attr("stroke", d => d.state === "down" ? "#555" : utilColor(d.util))
        .attr("stroke-width", 4)
        .attr("stroke-dasharray", d => d.state === "down" ? "8,6" : null)
        .attr("opacity", d => d.state === "down" ? 0.45 : 0.95);

    svg.append("g").selectAll("line.stub-link").data(linkData.filter(d => d.is_stub)).enter()
      .append("line")
        .attr("x1", d => d.s.x).attr("y1", d => d.s.y)
        .attr("x2", d => d.t.x).attr("y2", d => d.t.y)
        .attr("stroke", C.muted)
        .attr("stroke-width", 2)
        .attr("stroke-dasharray", "5,4")
        .attr("opacity", 0.7);

    // 2. Utilization labels on transport links only
    svg.append("g").selectAll("text.util").data(linkData.filter(d => !d.is_stub)).enter()
      .append("text")
        .attr("x", d => (d.s.x + d.t.x) / 2)
        .attr("y", d => (d.s.y + d.t.y) / 2 - 7)
        .attr("text-anchor", "middle")
        .attr("fill", d => d.state === "down" ? C.red : utilColor(d.util))
        .style("font-size", FS.topoUtil).style("font-family", "monospace").style("font-weight", "bold")
        .text(d => d.state === "down" ? "DOWN" : `${d.util.toFixed(0)}%`);

    // 3. LSP overlay paths — one routed polyline per LSP (slice A + B)
    const lspList = lsps ? Object.values(lsps) : [];
    const lspHop = (lsp) => {
      const hops = [];
      const slice = Object.values(slices || {}).find(s => s.lsp === lsp.id);
      if (slice) hops.push(slice.gnb);
      hops.push(...(lsp.path || []));
      if (slice) hops.push(slice.upf);
      return hops;
    };

    svg.append("g").selectAll("path.lsp").data(lspList).enter()
      .append("path")
        .attr("fill", "none")
        .attr("stroke", d => SLICE_COLOR[Object.values(slices || {}).find(s => s.lsp === d.id)?.id] || C.purple)
        .attr("stroke-width", 3)
        .attr("stroke-linecap", "round")
        .attr("stroke-linejoin", "round")
        .attr("opacity", 0.55)
        .attr("d", d => {
          const hops = lspHop(d);
          const points = hops.map(h => pos[h]).filter(Boolean);
          if (points.length < 2) return "";
          return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
        });

    // LSP label near midpoint of its transport portion
    svg.append("g").selectAll("text.lsp-lbl").data(lspList).enter()
      .append("text")
        .attr("x", d => {
          const pts = (d.path || []).map(h => pos[h]).filter(Boolean);
          if (!pts.length) return 0;
          const mid = pts[Math.floor(pts.length / 2)];
          return mid.x;
        })
        .attr("y", d => {
          const pts = (d.path || []).map(h => pos[h]).filter(Boolean);
          if (!pts.length) return 0;
          const mid = pts[Math.floor(pts.length / 2)];
          const row = NODE_ROW[d.path[Math.floor(d.path.length / 2)]];
          return mid.y + (row === 0 ? -28 : 34);
        })
        .attr("text-anchor", "middle")
        .attr("fill", d => SLICE_COLOR[Object.values(slices || {}).find(s => s.lsp === d.id)?.id] || C.purple)
        .style("font-size", FS.topoLspLabel)
        .style("font-family", "monospace")
        .style("font-weight", "700")
        .text(d => {
          const slice = Object.values(slices || {}).find(s => s.lsp === d.id);
          return slice ? `${d.id} · ${slice.id}` : d.id;
        });

    // 4. Nodes
    const nodeGroups = svg.append("g").selectAll("g.node").data(nodeData).enter()
      .append("g").attr("class", "node")
      .attr("transform", d => `translate(${d.x},${d.y})`);

    // NODE_R, RECT_W, RECT_H are computed earlier with `scale`

    nodeGroups.each(function (d) {
      const style = ROLE_STYLE[d.role] || ROLE_STYLE.edge;
      const g = d3.select(this);
      if (style.shape === "rect") {
        g.append("rect")
          .attr("x", -RECT_W/2).attr("y", -RECT_H/2)
          .attr("width", RECT_W).attr("height", RECT_H)
          .attr("rx", 6).attr("ry", 6)
          .attr("fill", d.state === "down" ? "#1a1a2e" : style.fill)
          .attr("stroke", d.state === "down" ? C.red : style.stroke)
          .attr("stroke-width", 2);
      } else {
        g.append("circle")
          .attr("r", NODE_R)
          .attr("fill", d.state === "down" ? "#1a1a2e" : style.fill)
          .attr("stroke", d.state === "down" ? C.red : style.stroke)
          .attr("stroke-width", 2);
      }

      // Antenna icon for RAN nodes — two arcs + vertical stroke, above/right of node
      if (d.role === "ran") {
        const ax = RECT_W/2 + 6, ay = -RECT_H/2 - 4;
        g.append("line")
          .attr("x1", ax).attr("y1", ay - 2).attr("x2", ax).attr("y2", ay + 10)
          .attr("stroke", "#fbbf24").attr("stroke-width", 2);
        g.append("path")
          .attr("d", `M ${ax-5},${ay+2} Q ${ax},${ay-4} ${ax+5},${ay+2}`)
          .attr("fill", "none").attr("stroke", "#fbbf24").attr("stroke-width", 1.6);
        g.append("path")
          .attr("d", `M ${ax-8},${ay+4} Q ${ax},${ay-8} ${ax+8},${ay+4}`)
          .attr("fill", "none").attr("stroke", "#fbbf24").attr("stroke-width", 1.4).attr("opacity", 0.7);
      }

      // UPF gets 3 small horizontal bars (server stack)
      if (d.role === "upf") {
        for (let i = 0; i < 3; i++) {
          g.append("rect")
            .attr("x", -9).attr("y", -10 + i * 7)
            .attr("width", 18).attr("height", 4)
            .attr("rx", 1)
            .attr("fill", "rgba(255,255,255,0.18)");
        }
      }

      // Label
      g.append("text")
        .attr("text-anchor", "middle")
        .attr("dominant-baseline", "middle")
        .attr("fill", style.label)
        .style("font-size", FS.topoNodeLabel)
        .style("font-weight", "700")
        .style("font-family", "monospace")
        .attr("y", d.role === "upf" ? RECT_H / 2 - 8 : 0)
        .text(d.id);
    });

    // 5. Legend — default anchored to the right edge, vertically centered.
    // The 5-column topology leaves empty space between UPF-01 (top-right)
    // and UPF-02 (bottom-right), which is where the legend sits. If the
    // panel is narrow (<560px) each slice reflows to 2 lines (path on
    // line 1, meta on line 2). If the right side can't fit a 200px
    // legend, we slide to the left edge (still vertically centered) so
    // it never clips over the UPF nodes. Below 280px wide, hide.
    const sliceRows = Object.values(slices || {});
    if (sliceRows.length && W >= 280) {
      const twoLine = W < 560;
      const lgWideRaw = twoLine ? Math.min(260, W - 28) : 300;
      const lgW = Math.max(200, Math.min(lgWideRaw, W - 28));
      const rowH = twoLine ? 32 : 22;
      const lgH = rowH * sliceRows.length + 18;
      const preferRight = (W - lgW - 14) > 10;
      const lgX = preferRight ? W - lgW - 14 : 14;
      // Vertically center (clamped so it never pokes above the top padding
      // or below the bottom padding).
      const lgY = Math.max(10, Math.min(H - lgH - 10, (H - lgH) / 2));
      const lg = svg.append("g");
      lg.append("rect")
        .attr("x", lgX).attr("y", lgY)
        .attr("width", lgW).attr("height", lgH)
        .attr("rx", 6)
        .attr("fill", "rgba(17,24,39,0.95)")
        .attr("stroke", C.border);
      sliceRows.forEach((s, i) => {
        const y = lgY + 18 + i * rowH;
        lg.append("circle").attr("cx", lgX + 14).attr("cy", y - 4).attr("r", 5)
          .attr("fill", SLICE_COLOR[s.id] || C.muted);
        lg.append("text").attr("x", lgX + 26).attr("y", y)
          .attr("fill", C.text).style("font-size", FS.sliceName).style("font-family", "monospace").style("font-weight", "700")
          .text(`${s.id.toUpperCase()} · ${s.gnb} → ${s.lsp} → ${s.upf}`);
        if (twoLine) {
          lg.append("text").attr("x", lgX + 26).attr("y", y + 14)
            .attr("fill", C.muted).style("font-size", FS.sliceMeta).style("font-family", "monospace")
            .text(`${s.subscribers.toLocaleString()} subs · SLA ${s.sla_latency_ms}ms`);
        } else {
          lg.append("text").attr("x", lgX + lgW - 12).attr("y", y)
            .attr("fill", C.muted).style("font-size", FS.sliceMeta).style("font-family", "monospace")
            .attr("text-anchor", "end")
            .text(`${s.subscribers.toLocaleString()} subs · SLA ${s.sla_latency_ms}ms`);
        }
      });
    }
  }, [stateKey]);

  useEffect(() => {
    draw();
    const ro = new ResizeObserver(draw);
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [draw]);
  return <div ref={wrapRef} style={{ width: "100%", height: "100%" }}><svg ref={svgRef} style={{ display: "block" }} /></div>;
}

// ─── LOG TYPE STYLES ──────────────────────────────────────────────────────────
const logTypeStyle = {
  alert:              { bg: "#ef444418", color: C.red,    label: "ALERT" },
  reasoning:          { bg: "#8b5cf618", color: C.purple, label: "THINK" },
  tool_call:          { bg: "#06b6d418", color: C.blue,   label: "TOOL" },
  tool_result:        { bg: "#10b98118", color: C.green,  label: "RESULT" },
  notification:       { bg: "#eab30818", color: C.yellow, label: "NOTIFY" },
  status:             { bg: "#10b98118", color: C.green,  label: "STATUS" },
  agent_status:       { bg: "#10b98118", color: C.green,  label: "STATUS" },
  git_command:        { bg: "#06b6d418", color: C.blue,   label: "GIT" },
  pr_opened:          { bg: "#8b5cf618", color: C.purple, label: "PR" },
  netconf_push:       { bg: "rgba(16,185,129,0.10)", color: C.green, label: "NETCONF" },
  state_update:       { bg: "rgba(255,255,255,0.02)", color: C.muted, label: "STATE" },
  scenario_started:   { bg: "#06b6d418", color: C.blue,   label: "▶ SCENARIO" },
  scenario_complete:  { bg: "#10b98118", color: C.green,  label: "✓ SCENARIO" },
  scenario_stopped:   { bg: "#64748b18", color: C.muted,  label: "■ STOPPED" },
};

// v2 scenario playback — reasoning-log subtypes, each with its own
// colored indicator dot + label. `conclude` renders bolder/larger with
// a one-time pulse on mount. `system` is a muted operational marker
// (proposal created, etc). `recovered` is the green post-deploy stream
// (QER committed, p99 recovered, etc).
const scenarioSubtypeStyle = {
  detect:    { bg: "rgba(6,182,212,0.08)",  color: C.blue,   label: "DETECT" },
  analyze:   { bg: "rgba(139,92,246,0.08)", color: C.purple, label: "ANALYZE" },
  correlate: { bg: "rgba(249,115,22,0.10)", color: C.orange, label: "CORRELATE" },
  decide:    { bg: "rgba(16,185,129,0.08)", color: C.green,  label: "DECIDE" },
  conclude:  { bg: "rgba(234,179,8,0.12)",  color: C.yellow, label: "CONCLUDE" },
  system:    { bg: "rgba(148,163,184,0.10)", color: C.muted, label: "SYSTEM" },
  recovered: { bg: "rgba(16,185,129,0.12)", color: C.green,  label: "✓ RECOVERED" },
  // Act 3 security teaser — louder than reasoning subtypes by design.
  alert:     { bg: "rgba(239,68,68,0.09)",  color: C.red,    label: "🔴 ALERT" },
};

// Pre-seeded Act 3 event — always present in the reasoning log, ~3h in
// the past. Survives Reset. Detail block expands on click.
const PRE_SEEDED_ALERT = {
  type:      "scenario_log",
  timestamp: new Date(Date.now() - 3 * 60 * 60 * 1000 - 17 * 60 * 1000).toISOString(),
  data: {
    seq:           -999,
    subtype:       "alert",
    content:       "Unauthorized gNMI config change attempt detected · target: PE-02 · source IP: 10.0.3.44 · invalid certificate · change blocked · connection terminated",
    is_conclusion: false,
    scenario_id:   "act3-security-teaser",
    is_preseed:    true,
    detail: {
      source_ip:          "10.0.3.44",
      target_device:      "PE-02",
      attempted_change:   "gNMI SET on interface configuration",
      certificate_status: "invalid (self-signed, not in trust store)",
      action_taken:       "connection terminated, change blocked",
      logged_to:          "SIEM (placeholder tag)",
    },
  },
};

const LogEntry = memo(function LogEntry({ entry }) {
  const data = entry.data || {};
  // Scripted scenario entries ride the same bus but pick their style from
  // data.subtype instead of entry.type so detect/analyze/correlate/decide/
  // conclude each get their own color dot + label.
  const isScenario  = entry.type === "scenario_log";
  const isConclude  = isScenario && !!data.is_conclusion;
  const isAlert     = isScenario && data.subtype === "alert";
  const [expanded, setExpanded] = useState(false);
  const s = isScenario
    ? (scenarioSubtypeStyle[data.subtype] || scenarioSubtypeStyle.analyze)
    : (logTypeStyle[entry.type] || logTypeStyle.status);

  // Scenario lifecycle events carry a small payload — format them as
  // human lines rather than JSON-stringifying the blob into the UI.
  const scenarioLifecycleMsg = (() => {
    if (entry.type === "scenario_started") {
      const label = data.short_label || data.name || data.id;
      const dur = data.duration_seconds ? ` (${data.duration_seconds}s)` : "";
      return label ? `Playing: ${label}${dur}` : "Scenario started";
    }
    if (entry.type === "scenario_complete") {
      return data.id ? `Completed: ${data.id}` : "Scenario complete";
    }
    if (entry.type === "scenario_stopped") {
      const r = data.reason ? ` — ${data.reason}` : "";
      return `Stopped${r}`;
    }
    return null;
  })();

  // For scenario_log entries we use data.content directly; for lifecycle
  // events we use the formatter above; for everything else keep the
  // existing extraction logic.
  const msg = isScenario
    ? (data.content || "")
    : (scenarioLifecycleMsg
       || entry.message || entry.msg
       || data.message || data.command || data.text
       || (data.tool && data.inputs ? `${data.tool}(\n${JSON.stringify(data.inputs, null, 2)})` : null)
       || (data.tool && data.result ? `${data.tool} → ${typeof data.result === "object" ? JSON.stringify(data.result) : data.result}` : null)
       || (typeof data === "string" ? data : JSON.stringify(data)));

  const ts = (() => {
    if (!entry.timestamp) return "";
    const t = entry.timestamp;
    if (typeof t === "string" && isNaN(Number(t))) {
      try { const d = new Date(t); if (!isNaN(d.getTime())) return d.toLocaleTimeString(); } catch {}
      return t;
    }
    const ms = Number(t) < 1e10 ? Number(t) * 1000 : Number(t);
    const d = new Date(ms);
    return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
  })();
  const msgStr = typeof msg === "string" ? msg : "";
  // Alerts: louder than reasoning — red border, tinted background, bigger
  // pill, bold text; click to expand inline detail block.
  // Conclusions: larger font, heavier weight, subtle pulse on mount.
  // Everything else: standard 3-line clamp with hover tooltip.
  const handleClick = isAlert && data.detail ? () => setExpanded(v => !v) : undefined;
  return (
    <div
      onClick={handleClick}
      style={{
        padding: isAlert ? "11px 12px" : (isConclude ? "11px 12px" : "8px 10px"),
        marginBottom: isAlert || isConclude ? 6 : 4,
        borderRadius: 6,
        background: s.bg,
        borderLeft: `${isAlert ? 4 : (isConclude ? 3 : 2)}px solid ${s.color}`,
        cursor: handleClick ? "pointer" : "default",
        animation: isConclude ? "orcaPulse 900ms ease-out" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
        <span style={{
          fontSize: isAlert ? "clamp(11px, 0.95vw, 13px)" : FS.logBadge,
          fontWeight: 700,
          padding: isAlert ? "2px 9px" : "1px 6px",
          borderRadius: 3,
          background: s.color + (isAlert ? "28" : "22"),
          color: s.color, fontFamily: "monospace",
          letterSpacing: 0.5,
        }}>{s.label}</span>
        {ts && <span style={{ fontSize: FS.logTimestamp, color: C.muted, fontFamily: "monospace" }}>{ts}</span>}
        {isAlert && data.detail && (
          <span style={{ marginLeft: "auto", fontSize: FS.logTimestamp, color: C.muted, fontFamily: "monospace" }}>
            {expanded ? "▾ hide details" : "▸ details"}
          </span>
        )}
      </div>
      <div
        title={isConclude || isAlert ? undefined : msgStr}
        style={{
          fontSize: isConclude ? "clamp(15px, 1.25vw, 18px)" : (isAlert ? "clamp(14px, 1.15vw, 16px)" : FS.logEntry),
          fontWeight: isConclude || isAlert ? 700 : 600,
          color: C.text,
          lineHeight: 1.45,
          fontFamily: entry.type === "tool_call" || entry.type === "tool_result" || entry.type === "git_command" ? "monospace" : "inherit",
          display: isConclude || isAlert ? undefined : "-webkit-box",
          WebkitLineClamp: isConclude || isAlert ? undefined : 3,
          WebkitBoxOrient: isConclude || isAlert ? undefined : "vertical",
          overflow: "hidden",
          wordBreak: "break-word",
          whiteSpace: "pre-wrap",
        }}
      >
        {msg}
      </div>
      {isAlert && expanded && data.detail && (
        <div style={{
          marginTop: 8, padding: "8px 10px", borderRadius: 4,
          background: "rgba(0,0,0,0.25)", border: `1px solid ${C.red}33`,
          fontFamily: "monospace", fontSize: "clamp(11px, 0.95vw, 13px)",
          lineHeight: 1.7, color: C.text,
        }}>
          {Object.entries(data.detail).map(([k, v]) => (
            <div key={k}>
              <span style={{ color: C.muted, letterSpacing: 0.5 }}>{k.replace(/_/g, " ")}:</span>
              {" "}
              <span style={{ color: k === "action_taken" ? C.red : C.text }}>{String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

// ─── AGENT LOG PANEL ──────────────────────────────────────────────────────────
function AgentLogPanel({ events, onOpenModal }) {
  const [filter, setFilter] = useState("all");
  const containerRef = useRef(null);
  const prevLenRef = useRef(0);

  const filtered = useMemo(() => {
    const meaningful = events.filter(e => e.type !== "state_update");
    if (filter === "all") return meaningful;
    const map = { THINK: ["reasoning", "agent_thinking", "scenario_log"], TOOL: ["tool_call", "tool_result", "git_command", "pr_opened"], ALERT: ["alert"] };
    return meaningful.filter(e => (map[filter] || []).includes(e.type));
  }, [events, filter]);

  useLayoutEffect(() => {
    const meaningful = events.filter(e => e.type !== "state_update");
    if (containerRef.current && meaningful.length > prevLenRef.current) {
      const el = containerRef.current;
      // only auto-scroll if user is already within 100px of the bottom;
      // otherwise leave scroll position alone so they can read
      if (el.scrollTop + el.clientHeight > el.scrollHeight - 100) {
        el.scrollTop = el.scrollHeight;
      }
    }
    prevLenRef.current = meaningful.length;
  }, [events]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap", flexShrink: 0, padding: "8px 12px 0" }}>
        {["all", "THINK", "TOOL", "ALERT"].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{ padding: "3px 8px", borderRadius: 4, fontSize: 9, fontWeight: 700, cursor: "pointer", background: filter === f ? C.blue + "18" : "rgba(255,255,255,0.03)", border: `1px solid ${filter === f ? C.blue + "44" : C.border}`, color: filter === f ? C.blue : C.muted, fontFamily: "monospace" }}>{f.toUpperCase()}</button>
        ))}
        <button onClick={onOpenModal} style={{ marginLeft: "auto", padding: "3px 8px", borderRadius: 4, fontSize: 9, fontWeight: 700, cursor: "pointer", background: "rgba(255,255,255,0.03)", border: `1px solid ${C.border}`, color: C.muted }}>⤢ Expand</button>
      </div>
      <div ref={containerRef} style={{ flex: 1, overflow: "auto", padding: "0 12px 12px" }}>
        {filtered.map((e, i) => <LogEntry key={i} entry={e} />)}
      </div>
    </div>
  );
}

// ─── AGENT LOG MODAL ─────────────────────────────────────────────────────────
function AgentLogModal({ events, onClose }) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState(false);
  const containerRef = useRef(null);
  const prevLenRef = useRef(0);

  const filtered = useMemo(() => {
    const meaningful = events.filter(e => e.type !== "state_update");
    let r = meaningful;
    if (filter !== "all") {
      const map = { THINK: ["reasoning", "agent_thinking", "scenario_log"], TOOL: ["tool_call", "tool_result", "git_command", "pr_opened"], ALERT: ["alert"] };
      r = r.filter(e => (map[filter] || []).includes(e.type));
    }
    if (search) r = r.filter(e => (e.message || e.msg || "").toLowerCase().includes(search.toLowerCase()));
    return r;
  }, [events, filter, search]);

  useLayoutEffect(() => {
    const meaningful = events.filter(e => e.type !== "state_update");
    if (containerRef.current && meaningful.length > prevLenRef.current) {
      const el = containerRef.current;
      if (el.scrollTop + el.clientHeight > el.scrollHeight - 100) {
        el.scrollTop = el.scrollHeight;
      }
    }
    prevLenRef.current = meaningful.length;
  }, [events]);

  const copyAll = () => {
    const text = filtered.map(e => `[${e.type}] ${e.message || e.msg || ""}`).join("\n");
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  };

  return (
    <Modal title="Agent Reasoning Log" onClose={onClose} width="900px">
      <div style={{ padding: "10px 16px", borderBottom: `1px solid ${C.border}`, display: "flex", gap: 6, flexWrap: "wrap", flexShrink: 0 }}>
        {["all", "THINK", "TOOL", "ALERT"].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{ padding: "3px 8px", borderRadius: 4, fontSize: 9, fontWeight: 700, cursor: "pointer", background: filter === f ? C.blue + "18" : "rgba(255,255,255,0.03)", border: `1px solid ${filter === f ? C.blue + "44" : C.border}`, color: filter === f ? C.blue : C.muted, fontFamily: "monospace" }}>{f.toUpperCase()}</button>
        ))}
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..." style={{ marginLeft: 8, padding: "3px 8px", borderRadius: 4, fontSize: 11, background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.text, outline: "none", width: 160 }} />
        <button onClick={copyAll} style={{ marginLeft: "auto", padding: "3px 10px", borderRadius: 4, fontSize: 10, cursor: "pointer", background: copied ? C.green + "18" : "rgba(255,255,255,0.04)", border: `1px solid ${copied ? C.green + "44" : C.border}`, color: copied ? C.green : C.muted }}>
          {copied ? "✓ Copied" : "Copy All"}
        </button>
      </div>
      <div ref={containerRef} style={{ flex: 1, overflow: "auto", padding: "12px 16px" }}>
        {filtered.map((e, i) => <LogEntry key={i} entry={e} />)}
      </div>
    </Modal>
  );
}

// ─── CONFIG PROPOSAL MODAL ────────────────────────────────────────────────────
function ConfigModal({ proposal, onClose, onAction, events }) {
  const [comment, setComment] = useState("");
  const [action, setAction] = useState(null);
  const [activeRouter, setActiveRouter] = useState(null);
  const [streamLog, setStreamLog] = useState([]);

  const handleAction = async (act) => {
    setAction(act);
    if (act !== "approved") {
      // Non-approval actions: call API and close immediately
      await onAction(proposal.id, act, comment, proposal.changes);
      onClose();
      return;
    }
    // Approval: call API, stay open, show streaming progress, close on complete
    try {
      await onAction(proposal.id, act, comment, proposal.changes);
    } catch (e) {
      setStreamLog(prev => [...prev, `❌ Error: ${e.message}`]);
    }
    // Fallback: close after 45 seconds if complete event never arrives
    setTimeout(onClose, 45000);
  };

  // Watch events for stream progress while pushing
  useEffect(() => {
    if (action !== "approved") return;
    const relevant = (events || []).filter(e =>
      ["git_command", "agent_status", "tool_result", "pr_opened", "netconf_push"].includes(e.type)
    ).slice(-20);
    const msgs = relevant.map(e => {
      const d = e.data || {};
      return d.command || d.message || (d.result?.message) || (d.pr_url ? `PR #${d.pr_number} → ${d.pr_url}` : null);
    }).filter(Boolean);
    setStreamLog(msgs);
    // Close when stream completes
    const complete = (events || []).slice(-10).find(e =>
      e.type === "agent_status" && e.data?.status === "complete"
    );
    if (complete) setTimeout(onClose, 1500);
  }, [events, action]);

  // Parse changes — agent sends {device, current_config, new_config, diff_summary}
  // Group by device name
  const routerData = useMemo(() => {
    const changes = proposal.changes || [];
    const grouped = {};
    changes.forEach(ch => {
      const router = ch.device || ch.node || ch.router || "Router";
      if (!grouped[router]) grouped[router] = [];
      grouped[router].push(ch);
    });
    // If no structured changes, fall back to raw diff
    if (Object.keys(grouped).length === 0 && (proposal.diff || []).length > 0) {
      grouped["Router"] = [];
    }
    return grouped;
  }, [proposal.changes, proposal.diff]);

  const routers = Object.keys(routerData);
  const sel = activeRouter || routers[0] || "";
  const selChanges = routerData[sel] || [];

  // Build diff lines from current_config / new_config strings
  const diffLines = useMemo(() => {
    if (selChanges.length > 0) {
      const lines = [];
      selChanges.forEach(ch => {
        // Parse current_config lines as removes, new_config as adds
        const cur = (ch.current_config || "").split("\n").filter(l => l.trim());
        const nxt = (ch.new_config || "").split("\n").filter(l => l.trim());
        // Find shared context lines
        const allLines = new Set([...cur, ...nxt]);
        allLines.forEach(line => {
          const inCur = cur.includes(line);
          const inNxt = nxt.includes(line);
          if (inCur && inNxt) lines.push({ type: "context", line });
          else if (inCur)     lines.push({ type: "remove",  line });
          else if (inNxt)     lines.push({ type: "add",     line });
        });
        // If no parsed lines, use diff_summary
        if (lines.length === 0 && ch.diff_summary) {
          ch.diff_summary.split("\n").forEach(l => {
            if (l.startsWith("+"))      lines.push({ type: "add",     line: l.slice(1).trim() });
            else if (l.startsWith("-")) lines.push({ type: "remove",  line: l.slice(1).trim() });
            else if (l.trim())          lines.push({ type: "context", line: l.trim() });
          });
        }
      });
      return lines;
    }
    // Fall back to proposal.diff
    return (proposal.diff || []).map(d => ({
      type: d.type || "context",
      line: d.line || d.content || ""
    }));
  }, [selChanges, proposal.diff]);

  // Proposed config = new_config of selected changes
  const proposedConfig = useMemo(() => {
    if (selChanges.length > 0) {
      return selChanges.map(ch => ch.new_config || "").join("\n");
    }
    return diffLines.filter(d => d.type !== "remove").map(d => d.line).join("\n");
  }, [selChanges, diffLines]);

  // Title for active tab
  const tabTitle = useMemo(() => {
    if (selChanges.length > 0 && selChanges[0].diff_summary) return selChanges[0].diff_summary.slice(0, 60);
    if (selChanges.length > 0 && selChanges[0].type) return selChanges[0].type.replace(/_/g, " ");
    return "metric_change";
  }, [selChanges]);

  // Validation
  const rawChecks = proposal.validation_checks || proposal.validation || {};
  const rawDetail = proposal.validation_detail || {};
  const norm = v => typeof v === "boolean" ? v : !String(v).trim().startsWith("❌");
  const checks = {
    syntax:       { pass: norm(rawChecks.syntax       ?? true), label: "Syntax",       detail: rawDetail.syntax       || "Valid Nokia SR-OS 22.x syntax" },
    semantic:     { pass: norm(rawChecks.semantic     ?? true), label: "Semantic",     detail: rawDetail.semantic     || "All hops reachable, BW available" },
    mission_1:    { pass: norm(rawChecks.mission_1    ?? true), label: "Mission 1",    detail: rawDetail.mission_1    || "All links remain < 90%" },
    mission_2:    { pass: norm(rawChecks.mission_2    ?? true), label: "Mission 2",    detail: rawDetail.mission_2    || "Overall max utilization improves" },
    digital_twin: { pass: norm(rawChecks.digital_twin ?? true), label: "Digital Twin", detail: rawDetail.digital_twin || "Simulated — stable under peak load" },
    policy:       { pass: norm(rawChecks.policy       ?? true), label: "Policy",       detail: rawDetail.policy       || "Metric change within allowed range" },
  };

  const sc = s => s === "approved" ? C.green : s === "rejected" ? C.red : s === "committed" ? C.blue : C.yellow;

  return (
    <Modal title={`Config Proposal — ${proposal.title}`} onClose={onClose} width="1040px">
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* ── LEFT SIDEBAR ── */}
        <div style={{ width: 210, flexShrink: 0, borderRight: `1px solid ${C.border}`, display: "flex", flexDirection: "column", overflow: "auto", background: "#0d1117" }}>
          {/* Status */}
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 9, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 5 }}>Status</div>
            <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 4, background: sc(proposal.status) + "22", color: sc(proposal.status), fontFamily: "monospace", fontWeight: 700, textTransform: "uppercase" }}>{proposal.status}</span>
          </div>
          {/* Reason */}
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 9, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 5 }}>Reason</div>
            <div style={{ fontSize: 11, color: C.text, lineHeight: 1.5 }}>{proposal.reason}</div>
            {proposal.projected_improvement && (
              <div style={{ marginTop: 8, fontSize: 10, color: C.green, fontFamily: "monospace", lineHeight: 1.5 }}>↑ {proposal.projected_improvement}</div>
            )}
          </div>
          {/* All 6 validation checks */}
          <div style={{ padding: "10px 14px", flex: 1, overflow: "auto" }}>
            <div style={{ fontSize: 9, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 10 }}>Validation</div>
            {Object.entries(checks).map(([k, c]) => (
              <div key={k} style={{ marginBottom: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                  <span style={{ fontSize: 12 }}>{c.pass ? "✅" : "❌"}</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: c.pass ? C.green : C.red }}>{c.label}</span>
                </div>
                <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.4, paddingLeft: 20 }}>{c.detail}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── CENTER: DIFF ── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", borderRight: `1px solid ${C.border}` }}>
          {/* Tab title bar */}
          {sel && tabTitle && (
            <div style={{ padding: "6px 14px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 8, flexShrink: 0, background: "#111" }}>
              <span style={{ fontSize: 10, color: C.blue, fontFamily: "monospace" }}>📋 {sel}</span>
              <span style={{ fontSize: 10, color: C.muted }}>{tabTitle}</span>
            </div>
          )}
          <div style={{ padding: "6px 14px 4px", borderBottom: `1px solid ${C.border}`, fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>Diff — Current vs Proposed</div>
          <div style={{ flex: 1, overflow: "auto", background: "#0d1117", padding: "10px 14px", fontFamily: "monospace", fontSize: 12, lineHeight: 1.9 }}>
            {diffLines.length === 0
              ? <div style={{ color: C.muted, fontSize: 11 }}>No diff available.</div>
              : diffLines.map((d, i) => (
              <div key={i} style={{
                padding: "0 8px", borderRadius: 2,
                background: d.type === "add" ? "rgba(16,185,129,0.10)" : d.type === "remove" ? "rgba(239,68,68,0.10)" : "transparent",
                color: d.type === "add" ? "#4ade80" : d.type === "remove" ? "#f87171" : "#6b7280",
                borderLeft: d.type === "add" ? `3px solid ${C.green}` : d.type === "remove" ? `3px solid ${C.red}` : "3px solid transparent",
              }}>
                <span style={{ userSelect: "none", marginRight: 10, opacity: 0.5 }}>{d.type === "add" ? "+" : d.type === "remove" ? "−" : " "}</span>
                {d.line}
              </div>
            ))}
          </div>
        </div>

        {/* ── RIGHT: PROPOSED CONFIG ── */}
        <div style={{ width: 220, flexShrink: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ padding: "6px 14px", borderBottom: `1px solid ${C.border}`, fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>Proposed Config — Editable</div>
          <div style={{ flex: 1, overflow: "auto", padding: "10px 14px", fontFamily: "monospace", fontSize: 12, lineHeight: 1.9, color: C.text }}>
            {proposedConfig.split("\n").filter(l => l.trim()).map((line, i) => (
              <div key={i} style={{ color: line.trim().match(/^\d+$|^isis|^metric|^ospf/) ? C.green : C.text }}>{line}</div>
            ))}
          </div>
        </div>
      </div>

      {/* ── BOTTOM: device tabs + stream progress + comment + actions ── */}
      <div style={{ borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
        <div style={{ display: "flex", gap: 4, padding: "6px 14px 0", borderBottom: `1px solid ${C.border}`, background: "#0d1117", alignItems: "center" }}>
          <span style={{ fontSize: 9, color: C.muted, textTransform: "uppercase", letterSpacing: 1, marginRight: 6 }}>Devices</span>
          {routers.map(r => (
            <button key={r} onClick={() => setActiveRouter(r)} style={{
              padding: "5px 14px", borderRadius: "4px 4px 0 0", fontSize: 11, fontWeight: 600,
              cursor: "pointer", border: `1px solid ${C.border}`, borderBottom: "none",
              background: (activeRouter || routers[0]) === r ? C.panel : "transparent",
              color: (activeRouter || routers[0]) === r ? C.blue : C.muted, marginBottom: -1,
            }}>📋 {r}</button>
          ))}
        </div>
        {/* Stream progress panel — visible while pushing */}
        {action === "approved" && (
          <div style={{ padding: "8px 14px", background: "#0a0f1e", borderBottom: `1px solid ${C.border}`, maxHeight: 110, overflow: "auto" }}>
            {streamLog.length === 0
              ? <div style={{ fontSize: 11, color: C.muted, fontFamily: "monospace" }}>⏳ Starting deployment...</div>
              : streamLog.map((msg, i) => (
                <div key={i} style={{ fontSize: 11, fontFamily: "monospace", lineHeight: 1.7,
                  color: i === streamLog.length - 1 ? C.green : C.muted }}>
                  {msg.startsWith("git ") || msg.startsWith("cfg(") ? "$ " : "→ "}{msg}
                </div>
              ))
            }
          </div>
        )}
        <div style={{ padding: "10px 14px", display: "flex", gap: 8, alignItems: "center" }}>
          <textarea value={comment} onChange={e => setComment(e.target.value)} rows={1}
            placeholder="Add a comment (optional)..." disabled={!!action}
            style={{ flex: 1, padding: "7px 10px", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, fontSize: 12, resize: "none", outline: "none", fontFamily: "inherit", opacity: action ? 0.5 : 1 }} />
          <button onClick={() => handleAction("rejected")} disabled={!!action} style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: action ? "default" : "pointer", background: C.red + "18", border: `1px solid ${C.red}44`, color: C.red, flexShrink: 0, opacity: action ? 0.4 : 1 }}>✗ Reject</button>
          <button onClick={() => handleAction("saved")} disabled={!!action} style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: action ? "default" : "pointer", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, flexShrink: 0, opacity: action ? 0.4 : 1 }}>💾 Save</button>
          <button onClick={() => handleAction("committed")} disabled={!!action} style={{ padding: "8px 14px", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: action ? "default" : "pointer", background: C.blue + "18", border: `1px solid ${C.blue}44`, color: C.blue, flexShrink: 0, opacity: action ? 0.4 : 1 }}>🔀 Save & Commit</button>
          <button onClick={() => handleAction("approved")} disabled={!!action} style={{ padding: "8px 18px", borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: action ? "default" : "pointer", background: C.green + "18", border: `1px solid ${C.green}44`, color: C.green, flexShrink: 0 }}>
            {action === "approved" ? "⚙️ Pushing..." : "✅ Approve & Push"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function EmailModal({ email, onClose, onSend }) {
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);
  const [to, setTo] = useState(email.to);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSend = async () => {
    setSending(true);
    await onSend({ ...email, subject, body, to });
    setSent(true);
    setSending(false);
    setTimeout(onClose, 1000);
  };

  const mailtoLink = `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  return (
    <Modal title="Email Draft" onClose={onClose} width="640px">
      <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 12, flex: 1, overflow: "auto" }}>
        <div><label style={{ fontSize: 11, color: C.muted }}>To</label><input value={to} onChange={e => setTo(e.target.value)} style={{ width: "100%", marginTop: 4, padding: 8, background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, fontSize: 13, outline: "none" }} /></div>
        <div><label style={{ fontSize: 11, color: C.muted }}>Subject</label><input value={subject} onChange={e => setSubject(e.target.value)} style={{ width: "100%", marginTop: 4, padding: 8, background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, fontSize: 13, outline: "none" }} /></div>
        <div style={{ flex: 1 }}><label style={{ fontSize: 11, color: C.muted }}>Body</label><textarea value={body} onChange={e => setBody(e.target.value)} rows={10} style={{ width: "100%", marginTop: 4, padding: 8, background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 6, color: C.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit" }} /></div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleSend} disabled={sending || sent} style={{ flex: 1, padding: 10, borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: "pointer", background: sent ? C.green + "18" : C.blue + "18", border: `1px solid ${sent ? C.green + "44" : C.blue + "44"}`, color: sent ? C.green : C.blue }}>
            {sent ? "✓ Sent" : sending ? "Sending..." : "Send via API"}
          </button>
          <a href={mailtoLink} style={{ flex: 1, padding: 10, borderRadius: 6, fontSize: 12, fontWeight: 700, cursor: "pointer", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, textDecoration: "none", textAlign: "center" }}>Open in Mail Client</a>
        </div>
      </div>
    </Modal>
  );
}

// ─── CONTROLS SLIM BAR ────────────────────────────────────────────────────────
function ControlsBar({ onAnalyze, onAction, playingScenario }) {
  const [link, setLink] = useState("PE-01-PE-04");
  const [level, setLevel] = useState(92);
  const [scenarios, setScenarios] = useState([]);
  const links = ["PE-01-P-02","P-02-PE-03","PE-03-PE-04","PE-04-P-01","P-01-PE-02","PE-02-PE-01","PE-01-PE-04","P-02-P-01"];

  useEffect(() => {
    let cancel = false;
    fetch(`${API}/api/scenarios`).then(r => r.json()).then(d => {
      if (!cancel) setScenarios(d.scenarios || []);
    }).catch(() => {});
    return () => { cancel = true; };
  }, []);

  // Act 3 security teaser — emits a red ALERT log entry. No state machine,
  // no revert proposal (unlike the v1 rogue config flow). Just a log line.
  const injectSecurityEvent = async () => {
    await fetch(`${API}/api/v2/security/inject-event`, { method: "POST" });
  };
  const injectScenario = async (id) => {
    if (!id) return;
    await fetch(`${API}/api/scenarios/${id}/inject`, { method: "POST" });
  };
  const resetScenarios = async () => {
    await fetch(`${API}/api/scenarios/reset`, { method: "POST" });
  };

  const activeScenario = scenarios.find(s => s.id === playingScenario);

  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 7, padding: "7px 12px", display: "flex", alignItems: "center", gap: 10, flexShrink: 0, flexWrap: "wrap" }}>
      {/* ── v2 demo scenarios (primary controls) ── */}
      <span style={{ fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>Scenario</span>
      <select
        value=""
        onChange={e => { injectScenario(e.target.value); e.target.value = ""; }}
        disabled={!!playingScenario}
        style={{ padding: "3px 6px", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 11, maxWidth: 260 }}
      >
        <option value="">{playingScenario ? "(scenario running)" : "— Inject Fault —"}</option>
        {scenarios.map(s => <option key={s.id} value={s.id}>{s.short_label}</option>)}
      </select>
      <button
        onClick={resetScenarios}
        style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, flexShrink: 0 }}
      >Reset</button>
      {activeScenario && (
        <span style={{
          fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 12,
          background: C.blue + "22", color: C.blue, fontFamily: "monospace",
          display: "inline-flex", alignItems: "center", gap: 6,
        }}>
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: C.blue, animation: "orcaPulse 1400ms ease-out infinite" }} />
          Playing: {activeScenario.short_label}
        </span>
      )}

      <div style={{ width: 1, height: 16, background: C.border, flexShrink: 0 }} />

      {/* ── v1 link fault controls (preserved for Act 3 security teaser) ── */}
      <span style={{ fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>Link</span>
      <select value={link} onChange={e => setLink(e.target.value)} style={{ padding: "3px 6px", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 11 }}>
        {links.map(l => <option key={l} value={l}>{l}</option>)}
      </select>
      <input type="range" min={50} max={99} value={level} onChange={e => setLevel(Number(e.target.value))} style={{ width: 80 }} />
      <span style={{ fontSize: 10, color: C.muted, fontFamily: "monospace", width: 28, flexShrink: 0 }}>{level}%</span>
      <button onClick={() => onAction("failure", link)} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.red + "18", border: `1px solid ${C.red}44`, color: C.red, flexShrink: 0 }}>Fault</button>
      <button onClick={() => onAction("congestion", link, level)} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.orange + "18", border: `1px solid ${C.orange}44`, color: C.orange, flexShrink: 0 }}>Congest</button>
      <button onClick={() => onAction("restore", link)} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.green + "18", border: `1px solid ${C.green}44`, color: C.green, flexShrink: 0 }}>Restore</button>
      <div style={{ width: 1, height: 16, background: C.border, flexShrink: 0 }} />
      <button
        onClick={injectSecurityEvent}
        title="Act 3 teaser — emits a red ALERT entry in the reasoning log"
        style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.red + "18", border: `1px solid ${C.red}44`, color: C.red, flexShrink: 0 }}
      >
        🔓 Inject Security Event (Act 3)
      </button>
      <button onClick={onAnalyze} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.blue + "18", border: `1px solid ${C.blue}44`, color: C.blue, flexShrink: 0, marginLeft: "auto" }}>🔍 Analyze</button>
    </div>
  );
}

// ─── LINK UTILIZATION TABLE ───────────────────────────────────────────────────
function LinkUtilPanel({ links }) {
  const rows = Object.entries(links || {}).map(([id, l]) => ({
    id, src: l.src_node || l.src || "—", dst: l.dst_node || l.dst || "—",
    util: l.utilization_pct || 0, state: l.state || "up",
    cap: l.capacity_gbps || "—",
  })).sort((a, b) => b.util - a.util);

  return (
    <div style={{ height: "100%", overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.border}` }}>
            {["Link", "Src", "Dst", "Util", "Cap", "State"].map(h => (
              <th key={h} style={{ padding: "5px 8px", textAlign: "left", fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: 0.5, textTransform: "uppercase", fontFamily: "monospace" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={6} style={{ padding: "12px 8px", textAlign: "center", color: C.muted, fontSize: 11 }}>No link data</td></tr>
          ) : rows.map((r, i) => (
            <tr key={r.id} style={{ borderBottom: `1px solid ${C.border}22` }}>
              <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: 10, color: C.muted }}>{r.id}</td>
              <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: 10, color: C.text }}>{r.src}</td>
              <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: 10, color: C.text }}>{r.dst}</td>
              <td style={{ padding: "6px 8px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 48, height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ width: `${Math.min(r.util, 100)}%`, height: "100%", background: utilColor(r.util), borderRadius: 2 }} />
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: utilColor(r.util), minWidth: 34 }}>{r.state === "down" ? "—" : `${r.util.toFixed(0)}%`}</span>
                </div>
              </td>
              <td style={{ padding: "6px 8px", fontFamily: "monospace", fontSize: 10, color: C.muted }}>{r.cap !== "—" ? `${r.cap}G` : "—"}</td>
              <td style={{ padding: "6px 8px" }}>
                <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, fontFamily: "monospace", fontWeight: 700, background: r.state === "down" ? C.red + "18" : C.green + "12", color: r.state === "down" ? C.red : C.green }}>{r.state}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── EMAIL CARD ───────────────────────────────────────────────────────────────
function EmailCard({ email: e, onEdit }) {
  const [expanded, setExpanded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const githubLinks = useMemo(() => {
    const matches = (e.body || "").match(/https:\/\/github\.com\/[^\s\n"')]+/g) || [];
    return [...new Set(matches)];
  }, [e.body]);

  const renderBody = (text) => {
    const parts = text.split(/(https?:\/\/[^\s\n"')]+)/g);
    return parts.map((part, i) =>
      part.match(/^https?:\/\//) ? (
        <a key={i} href={part} target="_blank" rel="noreferrer"
          style={{ color: C.blue, textDecoration: "underline", wordBreak: "break-all" }}>
          {part}
        </a>
      ) : <span key={i}>{part}</span>
    );
  };

  const LinkButtons = () => githubLinks.length > 0 ? (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
      {githubLinks.map((url, i) => {
        const label = url.includes("/pull/") ? `🔀 PR #${url.split("/pull/")[1]?.split("/")[0]}`
                    : url.includes("/episodes") ? "📚 Episode"
                    : url.includes("/security") ? "🔐 Evidence"
                    : "🔗 GitHub";
        return (
          <a key={i} href={url} target="_blank" rel="noreferrer" style={{
            padding: "4px 12px", borderRadius: 4, fontSize: 11, fontWeight: 600,
            background: C.blue + "18", border: `1px solid ${C.blue}44`,
            color: C.blue, textDecoration: "none",
          }}>{label}</a>
        );
      })}
    </div>
  ) : null;

  const isDeployed = e.subject?.includes("Deployed") || e.subject?.includes("Config");
  const isSecurity = e.subject?.includes("SECURITY") || e.subject?.includes("security");
  const borderColor = isSecurity ? C.red : isDeployed ? C.green : C.yellow;

  return (
    <>
      {/* Full-screen modal */}
      {fullscreen && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", zIndex: 2000,
          display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
        }} onClick={() => setFullscreen(false)}>
          <div onClick={ev => ev.stopPropagation()} style={{
            background: C.panel, border: `1px solid ${C.border}`, borderRadius: 12,
            width: "min(860px, 96vw)", maxHeight: "90vh", display: "flex", flexDirection: "column",
            boxShadow: "0 32px 80px rgba(0,0,0,0.9)",
          }}>
            {/* Modal header */}
            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${C.border}`, display: "flex", justifyContent: "space-between", alignItems: "start", flexShrink: 0 }}>
              <div>
                <div style={{ fontSize: 10, color: C.muted, fontFamily: "monospace", marginBottom: 4 }}>To: {e.to}</div>
                <div style={{ fontSize: 15, fontWeight: 700, color: C.text, lineHeight: 1.3 }}>{e.subject}</div>
              </div>
              <button onClick={() => setFullscreen(false)} style={{ background: "transparent", border: "none", color: C.muted, fontSize: 22, cursor: "pointer", marginLeft: 16, flexShrink: 0 }}>×</button>
            </div>
            {/* Full scrollable body */}
            <div style={{ flex: 1, overflow: "auto", padding: "20px 24px", background: "#0a0f1e" }}>
              <pre style={{ margin: 0, fontSize: 13, color: C.text, lineHeight: 1.8, fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {renderBody(e.body || "")}
              </pre>
            </div>
            {/* Modal footer */}
            <div style={{ padding: "14px 20px", borderTop: `1px solid ${C.border}`, display: "flex", gap: 10, alignItems: "center", flexShrink: 0, flexWrap: "wrap" }}>
              <LinkButtons />
              <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
                <a href={e.mailto || `mailto:${e.to}?subject=${encodeURIComponent(e.subject)}&body=${encodeURIComponent((e.body||"").slice(0,1800))}`}
                  style={{ padding: "7px 16px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: C.green + "18", border: `1px solid ${C.green}44`, color: C.green, textDecoration: "none" }}>
                  ✉ Open in Mail
                </a>
                <button onClick={() => { setFullscreen(false); onEdit(); }} style={{ padding: "7px 16px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, cursor: "pointer" }}>
                  ✏ Edit
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Card */}
      <div style={{ background: "rgba(255,255,255,0.02)", border: `1px solid ${C.border}`, borderRadius: 8, marginBottom: 8, borderLeft: `3px solid ${borderColor}`, overflow: "hidden" }}>
        {/* Header — click to expand inline, double-click or button to fullscreen */}
        <div onClick={() => setExpanded(!expanded)} style={{ padding: "10px 12px", cursor: "pointer" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
            <div style={{ flex: 1, marginRight: 8 }}>
              <div style={{ fontSize: FS.logBadge, color: C.muted, fontFamily: "monospace", marginBottom: 3 }}>To: {e.to}</div>
              <div style={{ fontSize: FS.emailSubject, fontWeight: 600, color: C.text, wordBreak: "break-word" }}>{e.subject}</div>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
              <button onClick={ev => { ev.stopPropagation(); setFullscreen(true); }} style={{
                padding: "2px 8px", borderRadius: 4, fontSize: FS.logBadge, fontWeight: 700, cursor: "pointer",
                background: C.blue + "18", border: `1px solid ${C.blue}44`, color: C.blue,
              }}>⤢ View</button>
              <span style={{ fontSize: FS.logBadge, color: C.muted }}>{expanded ? "▲" : "▼"}</span>
            </div>
          </div>
          {!expanded && (
            /* Preview — word-break keeps long URLs from horizontal-overflowing;
               line-clamp at 2 lines truncates with ellipsis at word boundary */
            <div style={{
              fontSize: FS.emailBody, color: C.muted, marginTop: 4, lineHeight: 1.45,
              display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
              overflow: "hidden", wordBreak: "break-word",
            }}>
              {(e.body || "").replace(/\n/g, " ")}
            </div>
          )}
        </div>

        {/* Inline expanded */}
        {expanded && (
          <div style={{ borderTop: `1px solid ${C.border}` }}>
            <div style={{ padding: "10px 12px", maxHeight: 220, overflow: "auto", background: "#0a0f1e" }}>
              <pre style={{ margin: 0, fontSize: 11, color: C.text, lineHeight: 1.7, fontFamily: "monospace", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {renderBody(e.body || "")}
              </pre>
            </div>
            {githubLinks.length > 0 && (
              <div style={{ padding: "8px 12px", borderTop: `1px solid ${C.border}`, display: "flex", gap: 6, flexWrap: "wrap" }}>
                {githubLinks.map((url, i) => {
                  const label = url.includes("/pull/") ? `🔀 PR #${url.split("/pull/")[1]?.split("/")[0]}`
                              : url.includes("/episodes") ? "📚 Episode"
                              : url.includes("/security") ? "🔐 Evidence"
                              : "🔗 GitHub";
                  return (
                    <a key={i} href={url} target="_blank" rel="noreferrer" style={{
                      padding: "3px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600,
                      background: C.blue + "18", border: `1px solid ${C.blue}44`,
                      color: C.blue, textDecoration: "none",
                    }}>{label}</a>
                  );
                })}
              </div>
            )}
            <div style={{ padding: "8px 12px", borderTop: `1px solid ${C.border}`, display: "flex", gap: 6 }}>
              <a href={e.mailto || `mailto:${e.to}?subject=${encodeURIComponent(e.subject)}&body=${encodeURIComponent((e.body||"").slice(0,1800))}`}
                style={{ padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: C.green + "18", border: `1px solid ${C.green}44`, color: C.green, textDecoration: "none" }}>
                ✉ Open in Mail
              </a>
              <button onClick={ev => { ev.stopPropagation(); setFullscreen(true); }} style={{ padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: C.blue + "18", border: `1px solid ${C.blue}44`, color: C.blue, cursor: "pointer" }}>
                ⤢ Full Screen
              </button>
              <button onClick={ev => { ev.stopPropagation(); onEdit(); }} style={{ padding: "4px 10px", borderRadius: 4, fontSize: 10, fontWeight: 600, background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, cursor: "pointer" }}>
                ✏ Edit
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ─── V2 CONFIG PROPOSAL CARD ──────────────────────────────────────────────────
// Full-fidelity proposal card for the 5G demo. Backed by /api/proposals
// (see agent/v2_proposals.py). Renders: header + status badge + timestamp,
// reason block, projected impact, six validation gate chips with hover
// tooltips, unified diff preview, and action buttons. Pulses briefly on
// status transition so the presenter's eye is drawn to the change.
const STATUS_STYLE = {
  pending:   { label: "PENDING",   fg: C.yellow, border: C.yellow },
  approved:  { label: "APPROVED",  fg: C.green,  border: C.green  },
  deploying: { label: "DEPLOYING", fg: C.blue,   border: C.blue   },
  deployed:  { label: "DEPLOYED",  fg: C.blue,   border: C.blue   },
  rejected:  { label: "REJECTED",  fg: C.red,    border: C.red    },
};
const GATE_COLOR = {
  pass:    { bg: C.green + "18", fg: C.green,  icon: "✓" },
  fail:    { bg: C.red + "18",   fg: C.red,    icon: "✗" },
  pending: { bg: "#eab30818",    fg: C.yellow, icon: "•" },
};

// ─── V2 EMAIL ROW ────────────────────────────────────────────────────────────
// Compact outbox row. Click-to-expand detail is deferred to Prompt 7 — for
// now the row shows enough preview content (recipient, subject, first
// ~120 chars of body, attachment count, status badge) to read in the
// panel without opening anything.
const V2_EMAIL_STATUS = {
  draft:  { bg: "rgba(234,179,8,0.14)", fg: C.yellow, label: "DRAFT"  },
  sent:   { bg: "rgba(16,185,129,0.14)", fg: C.green,  label: "SENT"   },
  failed: { bg: "rgba(239,68,68,0.14)",  fg: C.red,    label: "FAILED" },
};
const V2_EMAIL_STRIPE = {
  internal_ops: C.blue,      // cyan stripe for NOC notifications
  external_tac: C.yellow,    // amber stripe for TAC handoffs
};

// ─── V2 PROPOSAL MODAL ───────────────────────────────────────────────────────
// Three-column full-fidelity review modal. Clicking anywhere on a V2
// proposal card opens this. Left = REASON / PROJECTED / VALIDATION /
// DEVICES / AUDIT. Middle = DIFF with device tabs. Right = editable
// proposed config for the selected device tab. Bottom = comment box +
// Reject / Save (local) / Save & Commit (persists) / Approve & Push.
// Read-only mode when proposal is already approved/deploying/deployed/
// rejected — action bar collapses to just Close.
function V2ProposalModal({ proposal, onClose, onApprove, onReject, onSaveCommit }) {
  const devices = (proposal.devices && proposal.devices.length > 0)
    ? proposal.devices
    : [{ id: "default", label: proposal.title || "proposal", note: null }];

  const [activeIdx,    setActiveIdx]    = useState(0);
  const [comment,      setComment]      = useState(proposal.comment || "");
  const [draftSaved,   setDraftSaved]   = useState(false);
  const [committed,    setCommitted]    = useState(false);
  const [configDrafts, setConfigDrafts] = useState(() => {
    const init = {};
    devices.forEach(d => {
      init[d.id] = (proposal.device_configs || {})[d.id] || "";
    });
    return init;
  });
  const [editedDeviceIds, setEditedDeviceIds] = useState(new Set());

  const isReadOnly = ["approved", "deploying", "deployed", "rejected"].includes(proposal.status);
  const status = STATUS_STYLE[proposal.status] || STATUS_STYLE.pending;
  const activeDevice = devices[activeIdx] || devices[0];
  const activeDiff = (proposal.device_diffs && proposal.device_diffs[activeDevice.id])
    || proposal.diff
    || [];

  // Escape closes the modal
  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  const onConfigEdit = (deviceId, next) => {
    setConfigDrafts(prev => ({ ...prev, [deviceId]: next }));
    setEditedDeviceIds(prev => new Set([...prev, deviceId]));
    setDraftSaved(false);
    setCommitted(false);
  };

  const handleSave = () => {
    // local-only — no server call. Persists within the modal until closed.
    setDraftSaved(true);
    setCommitted(false);
  };

  const handleSaveCommit = async () => {
    try {
      await fetch(`${API}/api/proposals/${proposal.id}/save`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment, device_configs: configDrafts }),
      });
    } catch {}
    setCommitted(true);
    setDraftSaved(true);
    if (onSaveCommit) onSaveCommit();
  };

  const ts = (() => {
    try { return new Date(proposal.created_at).toLocaleString(); } catch { return ""; }
  })();

  const backdrop = {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.62)",
    zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center",
    padding: 20,
  };
  const panel = {
    background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10,
    width: "90vw", height: "85vh", maxWidth: 1400, maxHeight: 900,
    display: "flex", flexDirection: "column", overflow: "hidden",
    boxShadow: "0 32px 80px rgba(0,0,0,0.7)",
  };

  return (
    <div onClick={onClose} style={backdrop}>
      <div onClick={e => e.stopPropagation()} style={panel}>

        {/* HEADER STRIP */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 18px", borderBottom: `1px solid ${C.border}`, flexShrink: 0, flexWrap: "wrap" }}>
          <span style={{
            fontSize: FS.logBadge, fontWeight: 700, padding: "4px 12px", borderRadius: 4,
            background: status.fg + "20", color: status.fg, fontFamily: "monospace", letterSpacing: 0.5, flexShrink: 0,
          }}>{status.label}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: "clamp(16px, 1.4vw, 20px)", fontWeight: 700, color: C.text, lineHeight: 1.25, wordBreak: "break-word" }}>
              {proposal.title}
            </div>
            {proposal.summary && (
              <div style={{ fontSize: FS.proposalReason, color: C.muted, marginTop: 3 }}>
                {proposal.summary}
              </div>
            )}
          </div>
          <div style={{ fontSize: FS.logTimestamp, color: C.muted, fontFamily: "monospace", textAlign: "right", flexShrink: 0 }}>
            <div>{ts}</div>
            <div>{proposal.id}</div>
          </div>
          <button onClick={onClose} aria-label="Close" style={{
            background: "transparent", border: "none", color: C.muted, fontSize: 22, cursor: "pointer",
            padding: "0 4px", lineHeight: 1, flexShrink: 0,
          }}>×</button>
        </div>

        {/* DEVICE TAB BAR (only when >1 device) */}
        {devices.length > 1 && (
          <div style={{ display: "flex", gap: 2, padding: "8px 18px", background: "rgba(255,255,255,0.02)", borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
            {devices.map((d, i) => {
              const active = i === activeIdx;
              const edited = editedDeviceIds.has(d.id);
              return (
                <button key={d.id} onClick={() => setActiveIdx(i)} style={{
                  padding: "6px 14px", borderRadius: 5, border: "none",
                  fontSize: FS.validationLabel, fontWeight: 700, fontFamily: "monospace",
                  background: active ? "rgba(6,182,212,0.14)" : "transparent",
                  color: active ? C.blue : C.muted, cursor: "pointer",
                }}>
                  📋 {d.label || d.id}
                  {edited && <span title="unsaved edits" style={{ marginLeft: 6, color: C.yellow }}>●</span>}
                </button>
              );
            })}
          </div>
        )}

        {/* THREE-COLUMN BODY */}
        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "minmax(0, 25fr) minmax(0, 37fr) minmax(0, 38fr)", minHeight: 0, overflow: "hidden" }}>

          {/* LEFT — Review panel */}
          <div style={{ padding: "14px 16px", overflow: "auto", borderRight: `1px solid ${C.border}` }}>
            <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5, marginBottom: 6 }}>REASON</div>
            <div style={{ fontSize: "clamp(12px, 1.05vw, 14px)", color: C.text, lineHeight: 1.55, marginBottom: 18, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {proposal.reason || "—"}
            </div>

            <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5, marginBottom: 6 }}>PROJECTED</div>
            <div style={{ fontSize: "clamp(12px, 1.05vw, 14px)", color: C.green, fontFamily: "monospace", lineHeight: 1.5, marginBottom: 18, wordBreak: "break-word" }}>
              {proposal.projected_impact || "—"}
            </div>

            <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5, marginBottom: 8 }}>VALIDATION</div>
            <div style={{ marginBottom: 18 }}>
              {(proposal.validation_gates || []).map(g => {
                const col = GATE_COLOR[g.status] || GATE_COLOR.pending;
                return (
                  <div key={g.name} style={{ marginBottom: 10 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: "clamp(12px, 1.0vw, 14px)", fontWeight: 700, color: C.text, fontFamily: "monospace" }}>{g.name}</span>
                      <span style={{ fontSize: FS.logBadge, fontWeight: 700, padding: "1px 6px", borderRadius: 3, background: col.bg, color: col.fg, fontFamily: "monospace" }}>
                        {col.icon} {g.status.toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: "clamp(11px, 0.95vw, 13px)", color: C.muted, marginTop: 2, paddingLeft: 2, lineHeight: 1.4, wordBreak: "break-word" }}>
                      {g.detail || ""}
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5, marginBottom: 6 }}>DEVICES</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 18 }}>
              {devices.map((d, i) => (
                <button key={d.id} onClick={() => setActiveIdx(i)} style={{
                  padding: "4px 10px", borderRadius: 4, border: `1px solid ${i === activeIdx ? C.blue : C.border}`,
                  background: i === activeIdx ? "rgba(6,182,212,0.14)" : "transparent",
                  color: i === activeIdx ? C.blue : C.muted,
                  fontSize: FS.validationLabel, fontWeight: 700, fontFamily: "monospace", cursor: "pointer",
                  display: "flex", alignItems: "center", gap: 4,
                }}>
                  {d.id}
                  {d.note && <span style={{ fontSize: FS.logBadge, color: C.muted, fontWeight: 400 }}>· {d.note}</span>}
                </button>
              ))}
            </div>

            <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5, marginBottom: 6 }}>AUDIT</div>
            <div style={{ fontSize: "clamp(11px, 0.95vw, 13px)", color: C.muted, fontFamily: "monospace", lineHeight: 1.7 }}>
              <div>Created: {ts || "—"}</div>
              <div>Incident: {proposal.triggering_incident_id || proposal.triggering_scenario_id || "—"}</div>
              <div>Approver: {proposal.approved_at ? "operator@session" : "[Pending]"}</div>
              <div>Status: {proposal.status}</div>
              {proposal.pr_url && (
                <div style={{ marginTop: 6 }}>
                  <a href={proposal.pr_url} target="_blank" rel="noreferrer" style={{ color: C.blue, textDecoration: "none" }}>
                    🔀 PR #{proposal.pr_number}
                  </a>
                </div>
              )}
            </div>
          </div>

          {/* MIDDLE — Diff */}
          <div style={{ display: "flex", flexDirection: "column", borderRight: `1px solid ${C.border}`, minHeight: 0 }}>
            <div style={{ padding: "12px 16px 8px", flexShrink: 0 }}>
              <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5 }}>
                DIFF — CURRENT vs PROPOSED
              </div>
              <div style={{ fontSize: FS.logTimestamp, color: C.muted, marginTop: 2, fontFamily: "monospace" }}>
                {activeDevice.label || activeDevice.id}
              </div>
            </div>
            <div style={{
              flex: 1, overflow: "auto", padding: "4px 12px 12px",
              fontFamily: "monospace", fontSize: "clamp(12px, 1.0vw, 14px)",
              lineHeight: 1.7, minHeight: 0,
            }}>
              {activeDiff.length === 0 ? (
                <div style={{ color: C.muted, padding: 12, textAlign: "center" }}>No diff entries</div>
              ) : activeDiff.map((d, i) => (
                <div key={i} style={{
                  padding: "1px 8px", whiteSpace: "pre",
                  background: d.type === "add" ? "rgba(16,185,129,0.10)"
                            : d.type === "remove" ? "rgba(239,68,68,0.10)"
                            : "transparent",
                  color: d.type === "add" ? C.green
                       : d.type === "remove" ? C.red
                       : "#94a3b8",
                }}>
                  {d.type === "add" ? "+ " : d.type === "remove" ? "- " : "  "}{d.line}
                </div>
              ))}
            </div>
          </div>

          {/* RIGHT — Editable proposed config */}
          <div style={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
            <div style={{ padding: "12px 16px 8px", flexShrink: 0 }}>
              <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: isReadOnly ? C.muted : C.blue, letterSpacing: 1.5 }}>
                {isReadOnly ? "DEPLOYED CONFIG — READ ONLY" : "PROPOSED CONFIG — EDITABLE"}
              </div>
              <div style={{ fontSize: FS.logTimestamp, color: C.muted, marginTop: 2, fontFamily: "monospace" }}>
                {activeDevice.label || activeDevice.id}
              </div>
            </div>
            <textarea
              value={configDrafts[activeDevice.id] || ""}
              onChange={(e) => onConfigEdit(activeDevice.id, e.target.value)}
              readOnly={isReadOnly}
              spellCheck={false}
              style={{
                flex: 1, margin: "4px 12px 12px", padding: 10,
                background: "#0d1117", color: C.text,
                fontFamily: "monospace", fontSize: "clamp(12px, 1.0vw, 14px)",
                lineHeight: 1.6, whiteSpace: "pre",
                border: `1px solid ${C.border}`, borderRadius: 4,
                outline: "none", resize: "none", minHeight: 0,
              }}
              onFocus={e => !isReadOnly && (e.currentTarget.style.borderColor = C.blue)}
              onBlur={e => e.currentTarget.style.borderColor = C.border}
            />
          </div>
        </div>

        {/* ACTION BAR */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 18px", borderTop: `1px solid ${C.border}`, flexShrink: 0, flexWrap: "wrap", background: "rgba(255,255,255,0.02)" }}>
          {isReadOnly ? (
            <button onClick={onClose} style={{
              marginLeft: "auto",
              padding: "8px 22px", borderRadius: 6,
              fontSize: FS.proposalReason, fontWeight: 700, cursor: "pointer",
              background: "rgba(255,255,255,0.04)", color: C.text,
              border: `1px solid ${C.border}`,
            }}>Close</button>
          ) : (
            <>
              <input
                type="text"
                value={comment}
                onChange={e => { setComment(e.target.value); setDraftSaved(false); }}
                placeholder="Add a comment (optional)..."
                style={{
                  flex: 1, minWidth: 200,
                  padding: "8px 10px", borderRadius: 5,
                  background: "rgba(255,255,255,0.03)", color: C.text,
                  fontSize: FS.body, fontFamily: "inherit",
                  border: `1px solid ${C.border}`, outline: "none",
                }}
              />
              {draftSaved && (
                <span style={{
                  fontSize: FS.logBadge, fontWeight: 700, padding: "3px 8px", borderRadius: 3,
                  background: C.yellow + "22", color: C.yellow, fontFamily: "monospace",
                }}>{committed ? "COMMITTED" : "DRAFT SAVED"}</span>
              )}
              <button onClick={() => onReject(comment)} style={{
                padding: "8px 14px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 600, cursor: "pointer",
                background: "transparent", color: C.red,
                border: `1px solid ${C.red}66`,
              }}>✗ Reject</button>
              <button onClick={handleSave} style={{
                padding: "8px 14px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 600, cursor: "pointer",
                background: "rgba(255,255,255,0.04)", color: C.muted,
                border: `1px solid ${C.border}`,
              }}>💾 Save</button>
              <button onClick={handleSaveCommit} style={{
                padding: "8px 14px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 700, cursor: "pointer",
                background: C.blue + "22", color: C.blue,
                border: `1px solid ${C.blue}66`,
              }}>🔀 Save & Commit</button>
              <button onClick={() => onApprove(comment)} style={{
                padding: "8px 18px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 700, cursor: "pointer",
                background: C.green + "22", color: C.green,
                border: `1px solid ${C.green}`,
              }}>✓ Approve & Push</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── V2 EMAIL MODAL ──────────────────────────────────────────────────────────
// Single-column full-view modal for a queued email. Body is read-only by
// default; Edit toggles it into a textarea. Attachment clicks show a
// demo-honest toast ("preview not wired"). Send/Discard/Save Draft/Edit
// buttons only when status=draft; read-only shows just Close.
function V2EmailModal({ email, onClose, onSend, onDiscard, onEdit, onSaveDraft }) {
  const [editing, setEditing] = useState(false);
  const [bodyDraft, setBodyDraft] = useState(email.body || "");
  const [toast, setToast] = useState(null);
  const s = V2_EMAIL_STATUS[email.status] || V2_EMAIL_STATUS.draft;
  const isDraft = email.status === "draft";

  useEffect(() => {
    const h = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  useEffect(() => { setBodyDraft(email.body || ""); }, [email.body]);

  const ts = (() => {
    try { return new Date(email.created_at).toLocaleString(); } catch { return ""; }
  })();

  const showAttachmentToast = () => {
    setToast("Attachment preview not wired — demo harness");
    setTimeout(() => setToast(null), 2200);
  };

  const fmtSize = (b) => {
    const n = Number(b) || 0;
    if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
    if (n >= 1024)        return `${(n / 1024).toFixed(1)} KB`;
    return `${n} B`;
  };

  const backdrop = {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.62)",
    zIndex: 2000, display: "flex", alignItems: "center", justifyContent: "center",
    padding: 20,
  };
  const panel = {
    background: C.panel, border: `1px solid ${C.border}`, borderRadius: 10,
    width: "70vw", height: "85vh", maxWidth: 900, maxHeight: 900,
    display: "flex", flexDirection: "column", overflow: "hidden",
    boxShadow: "0 32px 80px rgba(0,0,0,0.7)",
  };

  return (
    <div onClick={onClose} style={backdrop}>
      <div onClick={e => e.stopPropagation()} style={panel}>

        {/* HEADER */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 18px", borderBottom: `1px solid ${C.border}`, flexShrink: 0, flexWrap: "wrap" }}>
          <span style={{
            fontSize: FS.logBadge, fontWeight: 700, padding: "4px 12px", borderRadius: 4,
            background: s.bg, color: s.fg, fontFamily: "monospace", letterSpacing: 0.5,
          }}>{s.label}</span>
          <span style={{ fontSize: FS.body, color: C.muted, fontFamily: "monospace" }}>from {email.from}</span>
          <span style={{ fontSize: FS.logTimestamp, color: C.muted, fontFamily: "monospace", marginLeft: "auto" }}>{ts}</span>
          <button onClick={onClose} aria-label="Close" style={{
            background: "transparent", border: "none", color: C.muted, fontSize: 22, cursor: "pointer",
            padding: "0 4px", lineHeight: 1,
          }}>×</button>
        </div>

        {/* RECIPIENTS + SUBJECT */}
        <div style={{ padding: "14px 18px", borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
          <div style={{ fontSize: FS.body, color: C.muted, marginBottom: 4, display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <span style={{ letterSpacing: 1, textTransform: "uppercase", fontSize: FS.logBadge }}>To</span>
            {(email.to || []).map((r, i) => (
              <span key={i} style={{ padding: "2px 8px", borderRadius: 3, background: "rgba(255,255,255,0.04)", color: C.text, fontFamily: "monospace", fontSize: FS.body }}>{r}</span>
            ))}
          </div>
          {(email.cc || []).length > 0 && (
            <div style={{ fontSize: FS.body, color: C.muted, marginBottom: 4, display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
              <span style={{ letterSpacing: 1, textTransform: "uppercase", fontSize: FS.logBadge }}>Cc</span>
              {email.cc.map((r, i) => (
                <span key={i} style={{ padding: "2px 8px", borderRadius: 3, background: "rgba(255,255,255,0.04)", color: C.muted, fontFamily: "monospace", fontSize: FS.body }}>{r}</span>
              ))}
            </div>
          )}
          <div style={{ fontSize: "clamp(15px, 1.3vw, 18px)", fontWeight: 700, color: C.text, marginTop: 8, wordBreak: "break-word" }}>
            {email.subject}
          </div>
        </div>

        {/* BODY */}
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: "14px 18px" }}>
          {editing ? (
            <textarea
              value={bodyDraft}
              onChange={e => setBodyDraft(e.target.value)}
              spellCheck={false}
              style={{
                width: "100%", minHeight: "100%", boxSizing: "border-box",
                background: "#0d1117", color: C.text,
                padding: 10, border: `1px solid ${C.blue}`, borderRadius: 4,
                fontSize: "clamp(12px, 1.05vw, 14px)", fontFamily: "monospace",
                lineHeight: 1.65, outline: "none", resize: "none",
              }}
            />
          ) : (
            <div style={{
              fontSize: "clamp(12px, 1.05vw, 14px)", color: C.text,
              lineHeight: 1.65, whiteSpace: "pre-wrap", wordBreak: "break-word",
              fontFamily: "'DM Sans', 'Segoe UI', system-ui, sans-serif",
            }}>
              {email.body || ""}
            </div>
          )}
        </div>

        {/* ATTACHMENTS */}
        {(email.attachments || []).length > 0 && (
          <div style={{ borderTop: `1px solid ${C.border}`, padding: "10px 18px 14px", flexShrink: 0, maxHeight: "30%", overflow: "auto" }}>
            <div style={{ fontSize: "clamp(10px, 0.9vw, 12px)", fontWeight: 700, color: C.muted, letterSpacing: 1.5, marginBottom: 8 }}>
              ATTACHMENTS — {email.attachments.length} file{email.attachments.length === 1 ? "" : "s"}
            </div>
            {email.attachments.map((a, i) => (
              <div key={i}
                onClick={showAttachmentToast}
                style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "6px 8px",
                  borderRadius: 4, cursor: "pointer",
                  transition: "background 0.15s",
                }}
                onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.04)"}
                onMouseLeave={e => e.currentTarget.style.background = "transparent"}
              >
                <span style={{ fontSize: 16, flexShrink: 0 }}>📄</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "clamp(12px, 1.05vw, 14px)", fontWeight: 700, color: C.text, fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.filename}
                  </div>
                  <div style={{ fontSize: "clamp(10px, 0.85vw, 12px)", color: C.muted, fontFamily: "monospace" }}>
                    {a.mime_type}
                  </div>
                </div>
                <div style={{ fontSize: FS.body, color: C.muted, fontFamily: "monospace", flexShrink: 0 }}>
                  {fmtSize(a.size_bytes)}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ACTION BAR */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 18px", borderTop: `1px solid ${C.border}`, flexShrink: 0, background: "rgba(255,255,255,0.02)" }}>
          {isDraft ? (
            <>
              <div style={{ flex: 1 }} />
              <button onClick={() => onDiscard(email.id)} style={{
                padding: "8px 14px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 600, cursor: "pointer",
                background: "transparent", color: C.red, border: `1px solid ${C.red}66`,
              }}>Discard</button>
              <button onClick={() => {
                if (editing) {
                  // Edit Done — persist local draft back to parent if provided
                  if (onEdit) onEdit(email.id, bodyDraft);
                }
                setEditing(!editing);
              }} style={{
                padding: "8px 14px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 600, cursor: "pointer",
                background: "rgba(255,255,255,0.04)", color: C.text,
                border: `1px solid ${C.border}`,
              }}>{editing ? "Edit Done" : "Edit"}</button>
              {editing && (
                <button onClick={() => { onSaveDraft && onSaveDraft(email.id, bodyDraft); }} style={{
                  padding: "8px 14px", borderRadius: 6,
                  fontSize: FS.proposalReason, fontWeight: 600, cursor: "pointer",
                  background: C.blue + "22", color: C.blue, border: `1px solid ${C.blue}66`,
                }}>Save Draft</button>
              )}
              <button onClick={() => onSend(email.id)} style={{
                padding: "8px 22px", borderRadius: 6,
                fontSize: FS.proposalReason, fontWeight: 700, cursor: "pointer",
                background: C.green + "22", color: C.green, border: `1px solid ${C.green}`,
              }}>Send</button>
            </>
          ) : (
            <button onClick={onClose} style={{
              marginLeft: "auto",
              padding: "8px 22px", borderRadius: 6,
              fontSize: FS.proposalReason, fontWeight: 700, cursor: "pointer",
              background: "rgba(255,255,255,0.04)", color: C.text,
              border: `1px solid ${C.border}`,
            }}>Close</button>
          )}
        </div>

        {/* TOAST */}
        {toast && (
          <div style={{
            position: "absolute", bottom: 78, right: 20,
            padding: "8px 14px", borderRadius: 5,
            background: "rgba(17,24,39,0.96)", color: C.text,
            border: `1px solid ${C.blue}66`, fontSize: FS.body,
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          }}>{toast}</div>
        )}
      </div>
    </div>
  );
}

function V2EmailRow({ email, onSend, onDiscard, onOpen }) {
  const s = V2_EMAIL_STATUS[email.status] || V2_EMAIL_STATUS.draft;
  const stripe = V2_EMAIL_STRIPE[email.type] || C.muted;
  const isDraft = email.status === "draft";
  const ts = (() => {
    try {
      const d = new Date(email.created_at);
      return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
    } catch { return ""; }
  })();
  const preview = (email.body || "").replace(/\n+/g, " · ").slice(0, 120)
    + ((email.body || "").length > 120 ? "…" : "");
  const toLabel = Array.isArray(email.to) ? email.to.join(", ") : (email.to || "");
  const atts = Array.isArray(email.attachments) ? email.attachments : [];

  return (
    <div
      onClick={() => onOpen && onOpen(email.id)}
      style={{
        background: "rgba(255,255,255,0.02)",
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${stripe}`,
        borderRadius: 6,
        padding: "8px 10px",
        marginBottom: 8,
        cursor: "pointer",
        transition: "background 0.15s",
      }}
      onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.035)"}
      onMouseLeave={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
    >
      {/* Top line: recipient + timestamp */}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, marginBottom: 3 }}>
        <span style={{
          fontSize: FS.body, fontWeight: 700, color: C.text,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{toLabel}</span>
        <span style={{
          fontSize: FS.logTimestamp, color: C.muted, fontFamily: "monospace",
          flexShrink: 0,
        }}>{ts}</span>
      </div>
      {/* Subject */}
      <div style={{
        fontSize: FS.emailSubject, fontWeight: 700, color: C.text,
        lineHeight: 1.35, wordBreak: "break-word", marginBottom: 4,
      }}>
        {email.subject}
      </div>
      {/* Preview snippet */}
      <div style={{
        fontSize: FS.emailBody, color: C.muted, lineHeight: 1.4,
        wordBreak: "break-word",
        display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
        overflow: "hidden",
      }}>
        {preview}
      </div>
      {/* Footer: attachments + status + actions */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 7, flexWrap: "wrap" }}>
        {atts.length > 0 && (
          <span style={{ fontSize: FS.logBadge, color: C.muted, fontFamily: "monospace" }}>
            📎 {atts.length} attachment{atts.length === 1 ? "" : "s"}
          </span>
        )}
        {/* AUTO marker for auto-sent early notifications (Prompt 9) —
            visually distinct from human-sent drafts */}
        {email.tag === "early_notification" && (
          <span style={{
            fontSize: FS.logBadge, fontWeight: 700, padding: "2px 7px", borderRadius: 3,
            background: C.blue + "18", color: C.blue,
            fontFamily: "monospace", letterSpacing: 0.5,
            border: `1px solid ${C.blue}44`,
          }} title="Auto-sent by ORCA at diagnosis completion — no human action required">AUTO</span>
        )}
        <span style={{
          fontSize: FS.logBadge, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
          background: s.bg, color: s.fg, fontFamily: "monospace", letterSpacing: 0.5,
        }}>{s.label}</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {isDraft ? (
            <>
              <button
                onClick={e => { e.stopPropagation(); onSend && onSend(); }}
                style={{
                  fontSize: FS.logBadge, fontWeight: 700, padding: "3px 10px", borderRadius: 4,
                  background: C.green + "22", color: C.green,
                  border: `1px solid ${C.green}44`, cursor: "pointer",
                }}
              >Send</button>
              <button
                onClick={e => { e.stopPropagation(); onDiscard && onDiscard(); }}
                style={{
                  fontSize: FS.logBadge, fontWeight: 600, padding: "3px 10px", borderRadius: 4,
                  background: "transparent", color: C.muted,
                  border: `1px solid ${C.border}`, cursor: "pointer",
                }}
              >Discard</button>
            </>
          ) : email.sent_at ? (
            <span style={{ fontSize: FS.logBadge, color: C.muted, fontFamily: "monospace" }}>
              sent {new Date(email.sent_at).toLocaleTimeString()}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function V2ProposalCard({ p, isPulsing, isNew, isDeploying, onApprove, onReject, onOpen }) {
  const status = STATUS_STYLE[p.status] || STATUS_STYLE.pending;
  const gates  = p.validation_gates || [];
  const allPass = gates.length > 0 && gates.every(g => g.status === "pass");
  const canApprove = p.status === "pending" && allPass && !isDeploying;
  const approveTooltip = !allPass ? "Cannot deploy — one or more validation gates failed" : "";
  const ts = (() => {
    try { return new Date(p.created_at).toLocaleTimeString(); } catch { return ""; }
  })();

  // Subtle shadow on pending to draw attention; removed once decided.
  const shadow = p.status === "pending" ? "0 4px 16px rgba(234,179,8,0.12)" : "none";

  // Compose animations. `isNew` = first appearance (scenario-generated).
  // `isPulsing` = status transition. They can coexist for the first click
  // on a freshly-appeared card, but the entrance animation dominates the
  // first 1.2s. Order matters — last animation in the string wins visually.
  let animation;
  if (isNew && isPulsing) {
    animation = "orcaCardEnter 420ms ease-out, orcaStripePulse 800ms ease-out 420ms, orcaPulse 800ms ease-out 1200ms";
  } else if (isNew) {
    animation = "orcaCardEnter 420ms ease-out, orcaStripePulse 800ms ease-out 420ms";
  } else if (isPulsing) {
    animation = "orcaPulse 800ms ease-out";
  }

  return (
    <div
      onClick={() => onOpen && onOpen(p.id)}
      style={{
      background: "rgba(255,255,255,0.02)",
      border: `1px solid ${C.border}`,
      borderLeft: `3px solid ${status.border}`,
      borderRadius: 8,
      padding: 14,
      marginBottom: 12,
      boxShadow: shadow,
      animation,
      cursor: "pointer",
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 10, marginBottom: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: FS.proposalTitle, fontWeight: 700, color: C.text, wordBreak: "break-word", lineHeight: 1.3 }}>
            {p.title}
          </div>
          <div style={{ fontSize: FS.logTimestamp, color: C.muted, fontFamily: "monospace", marginTop: 3 }}>
            {p.id} · generated {ts}
            {p.pr_url && (
              <> · <a href={p.pr_url} target="_blank" rel="noreferrer" style={{ color: C.blue, textDecoration: "none" }}>PR #{p.pr_number}</a></>
            )}
          </div>
        </div>
        <span style={{
          fontSize: FS.logBadge,
          fontWeight: 700,
          padding: "3px 10px",
          borderRadius: 4,
          background: status.fg + "18",
          color: status.fg,
          fontFamily: "monospace",
          flexShrink: 0,
          letterSpacing: 0.5,
        }}>{status.label}</span>
      </div>

      {/* Reason */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: FS.logBadge, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 3 }}>
          Reason
        </div>
        <div style={{ fontSize: FS.proposalReason, color: C.text, lineHeight: 1.5, wordBreak: "break-word" }}>
          {p.reason || "—"}
        </div>
      </div>

      {/* Projected impact */}
      {p.projected_impact && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: FS.logBadge, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 3 }}>
            Projected impact
          </div>
          <div style={{ fontSize: FS.proposalReason, color: C.green, lineHeight: 1.5, wordBreak: "break-word", fontFamily: "monospace" }}>
            {p.projected_impact}
          </div>
        </div>
      )}

      {/* Validation gates */}
      {gates.length > 0 && (
        <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 10 }}>
          {gates.map(g => {
            const col = GATE_COLOR[g.status] || GATE_COLOR.pending;
            return (
              <span
                key={g.name}
                title={g.detail || ""}
                style={{
                  fontSize: FS.validationLabel,
                  fontWeight: 700,
                  padding: "3px 8px",
                  borderRadius: 3,
                  background: col.bg,
                  color: col.fg,
                  fontFamily: "monospace",
                  cursor: "help",
                }}
              >
                {col.icon} {g.name}
              </span>
            );
          })}
        </div>
      )}

      {/* Diff */}
      {(p.diff || []).length > 0 && (
        <div style={{
          background: "#0d1117",
          border: `1px solid ${C.border}`,
          borderRadius: 6,
          padding: 8,
          fontFamily: "monospace",
          fontSize: FS.diff,
          lineHeight: 1.65,
          maxHeight: 250,
          overflow: "auto",
          marginBottom: 10,
        }}>
          {p.diff.map((d, i) => (
            <div key={i} style={{
              padding: "1px 8px",
              background: d.type === "add"   ? "rgba(16,185,129,0.08)"
                        : d.type === "remove" ? "rgba(239,68,68,0.08)"
                        : "transparent",
              color: d.type === "add"    ? C.green
                   : d.type === "remove" ? C.red
                   : C.muted,
              whiteSpace: "pre",
            }}>
              {d.type === "add" ? "+ " : d.type === "remove" ? "- " : "  "}{d.line}
            </div>
          ))}
        </div>
      )}

      {/* Action buttons */}
      {p.status === "pending" && (
        <div onClick={e => e.stopPropagation()} style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={e => { e.stopPropagation(); onApprove && onApprove(); }}
            disabled={!canApprove}
            title={approveTooltip}
            style={{
              flex: 1,
              padding: "10px 14px",
              borderRadius: 6,
              fontSize: FS.proposalReason,
              fontWeight: 700,
              cursor: canApprove ? "pointer" : "not-allowed",
              background: canApprove ? C.green + "22" : "rgba(255,255,255,0.03)",
              border: `1px solid ${canApprove ? C.green : C.border}`,
              color: canApprove ? C.green : C.muted,
              opacity: canApprove ? 1 : 0.6,
            }}
          >
            {isDeploying ? "⚙️ Deploying..." : "✓ Approve & Deploy"}
          </button>
          <button
            onClick={e => { e.stopPropagation(); onReject && onReject(); }}
            disabled={isDeploying}
            style={{
              padding: "10px 14px",
              borderRadius: 6,
              fontSize: FS.proposalReason,
              fontWeight: 600,
              cursor: isDeploying ? "not-allowed" : "pointer",
              background: "transparent",
              border: `1px solid ${C.red}66`,
              color: C.red,
            }}
          >Reject</button>
        </div>
      )}
    </div>
  );
}

// Single <style> tag with keyframes. Mounted once — cheap, no Vite CSS step.
function GlobalStyles() {
  return (
    <style>{`
      /* Fired on proposal status transition (pending→approved→deployed). */
      @keyframes orcaPulse {
        0%   { box-shadow: 0 0 0 0    rgba(6, 182, 212, 0.55); }
        50%  { box-shadow: 0 0 0 10px rgba(6, 182, 212, 0.18); }
        100% { box-shadow: 0 0 0 0    rgba(6, 182, 212, 0);    }
      }
      /* Fired on first appearance of a scenario-generated proposal card.
         Fade + slide up + amber stripe glow — the demo's money-shot beat. */
      @keyframes orcaCardEnter {
        0%   { opacity: 0; transform: translateY(20px); }
        70%  { opacity: 1; transform: translateY(0);    }
        100% { opacity: 1; transform: translateY(0);    }
      }
      @keyframes orcaStripePulse {
        0%   { box-shadow: -4px 0 14px 0 rgba(234, 179, 8, 0.55),
                             0 4px 16px    rgba(234, 179, 8, 0.22); }
        100% { box-shadow: -4px 0 0 0   rgba(234, 179, 8, 0),
                             0 4px 16px    rgba(234, 179, 8, 0.12); }
      }
    `}</style>
  );
}

// ─── OPERATIONS TAB ──────────────────────────────────────────────────────────
function OperationsTab({ state, events, agentRunning, wsStatus, onToggleAgent, onAnalyze, onAction, onConfigAction, onEmailSend, logModalOpen, setLogModalOpen, emailModal, setEmailModal, configModal, setConfigModal }) {
  const [proposals, setProposals] = useState([]);       // v1 store, kept for baseline
  const [v2Proposals, setV2Proposals] = useState([]);   // v2 demo chassis — the panel renders these
  const [emails, setEmails] = useState([]);
  const [notifications, setNotifications] = useState([]);
  // Track which v2 proposal card just transitioned so we can pulse it.
  const [pulseId, setPulseId] = useState(null);
  const prevStatusRef = useRef({});
  const [deployingIds, setDeployingIds] = useState(new Set());
  // Track which proposal id just appeared — triggers the entrance
  // animation (fade-in + slide-up + stripe pulse), distinct from the
  // status-transition pulse above.
  const [entranceId, setEntranceId] = useState(null);
  const prevIdsRef = useRef(new Set());

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/config-proposals`);
        const d = await r.json();
        setProposals(d.proposals || []);
      } catch {}
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, []);

  // v2 proposals — poll + refresh on PR/status WebSocket events
  const fetchV2 = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/proposals`);
      const d = await r.json();
      setV2Proposals(d.proposals || []);
    } catch {}
  }, []);
  useEffect(() => {
    fetchV2();
    const t = setInterval(fetchV2, 3000);
    return () => clearInterval(t);
  }, [fetchV2]);
  // Proposal-related WebSocket events also trigger an immediate refetch so
  // the UI doesn't lag behind a 3s poll.
  useEffect(() => {
    const last = events[events.length - 1];
    if (!last) return;
    const status = last?.data?.status;
    if (last.type === "pr_opened"
        || ["proposal_created", "proposal_approved", "proposal_rejected", "deploying", "deployed"].includes(status)) {
      fetchV2();
    }
  }, [events, fetchV2]);

  // ── v2 Email Outbox ──
  const [v2Emails, setV2Emails] = useState([]);
  const fetchV2Emails = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/v2/emails`);
      const d = await r.json();
      setV2Emails(d.emails || []);
    } catch {}
  }, []);
  useEffect(() => {
    fetchV2Emails();
    const t = setInterval(fetchV2Emails, 4000);
    return () => clearInterval(t);
  }, [fetchV2Emails]);
  // Refetch immediately on outbox WebSocket events so Send / Discard /
  // email_created land in the UI within a frame.
  useEffect(() => {
    const last = events[events.length - 1];
    if (!last) return;
    if (last.type === "email_created" || last.type === "email_updated" || last.type === "emails_cleared") {
      fetchV2Emails();
    }
  }, [events, fetchV2Emails]);

  // Pulse card when its status changes (pending→approved→deployed etc).
  useEffect(() => {
    const prev = prevStatusRef.current;
    const next = {};
    const transitioned = [];
    for (const p of v2Proposals) {
      next[p.id] = p.status;
      if (prev[p.id] && prev[p.id] !== p.status) transitioned.push(p.id);
    }
    prevStatusRef.current = next;
    if (transitioned.length) {
      setPulseId(transitioned[0]);
      const t = setTimeout(() => setPulseId(null), 900);
      return () => clearTimeout(t);
    }
  }, [v2Proposals]);

  // Entrance animation: fire once per newly-arrived proposal id. Compare
  // current ids against the previous set. Skip the very first render
  // (where every id is "new") so refreshes don't re-fire the animation
  // on already-seen proposals.
  const entranceInitializedRef = useRef(false);
  useEffect(() => {
    const curr = new Set(v2Proposals.map(p => p.id));
    if (!entranceInitializedRef.current) {
      prevIdsRef.current = curr;
      entranceInitializedRef.current = true;
      return;
    }
    const fresh = [...curr].filter(id => !prevIdsRef.current.has(id));
    prevIdsRef.current = curr;
    if (fresh.length) {
      // Animate the newest-first proposal (store renders in newest-first)
      setEntranceId(fresh[fresh.length - 1]);
      const t = setTimeout(() => setEntranceId(null), 1300);
      return () => clearTimeout(t);
    }
  }, [v2Proposals]);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/emails`);
        const d = await r.json();
        setEmails(d.emails || []);
      } catch {}
    };
    poll();
    const t = setInterval(poll, 8000);
    return () => clearInterval(t);
  }, []);

  // Extract notifications from events
  useEffect(() => {
    const notifs = events.filter(e => e.type === "notification" || e.type === "pr_opened")
      .slice(-5)
      .map((e, i) => ({ id: i, msg: e.message || e.msg, type: e.type, ts: e.timestamp }));
    setNotifications(notifs);
  }, [events]);

  const alarms = state.alarms || [];
  const pendingProposals = proposals.filter(p => p.status === "pending").length;

  // v2 demo: hide legacy v1 customer LSPs from the Active LSPs sidebar so
  // the slice narrative stays crisp. The data is still present in /api/state
  // and still exercised by test_e2e_baseline — this is a display filter only.
  const visibleLsps = Object.entries(state.lsps || {}).filter(
    ([id]) => id.startsWith("LSP-") || id === "lsp-mgmt"
  );

  // ─── Inner pane components (kept inline so they close over handlers) ───
  const TopologyPane = (
    <Panel title="Network Topology" style={{ flex: 1, height: "100%" }}>
      <TopologyMap nodes={state.nodes || {}} links={state.links || {}} lsps={state.lsps || {}} slices={state.slices || {}} />
    </Panel>
  );

  const RightSidebarPane = (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, height: "100%", minHeight: 0 }}>
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "9px 12px", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: wsStatus === "connected" ? C.green : C.red, boxShadow: `0 0 8px ${wsStatus === "connected" ? C.green : C.red}55` }} />
        <span style={{ fontSize: FS.body, color: C.text, fontWeight: 600 }}>{agentRunning ? "Agent Running" : "Agent Stopped"}</span>
        <button onClick={onToggleAgent} style={{ marginLeft: "auto", padding: "3px 9px", borderRadius: 5, fontSize: FS.validationLabel, fontWeight: 700, background: agentRunning ? C.red + "18" : C.green + "18", border: `1px solid ${agentRunning ? C.red + "44" : C.green + "44"}`, color: agentRunning ? C.red : C.green, cursor: "pointer" }}>
          {agentRunning ? "⏹ Stop" : "▶ Start"}
        </button>
      </div>
      <Panel title="Active LSPs" style={{ flex: 1, minHeight: 0 }}>
        {visibleLsps.length === 0 ? (
          <div style={{ fontSize: FS.body, color: C.muted, textAlign: "center", paddingTop: 8 }}>No LSP data</div>
        ) : visibleLsps.map(([id, l]) => (
          <div key={id} style={{ padding: "6px 0", borderBottom: `1px solid ${C.border}22`, display: "flex", flexDirection: "column", gap: 3 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: FS.lspName, fontWeight: 700, fontFamily: "monospace", color: C.blue }}>{id}</span>
              <span style={{ fontSize: FS.logBadge, padding: "1px 5px", borderRadius: 3, background: l.state === "up" ? C.green + "12" : C.red + "18", color: l.state === "up" ? C.green : C.red, fontFamily: "monospace", flexShrink: 0 }}>{l.state || "up"}</span>
            </div>
            {/* Path: wrap (don't clip) when sidebar is narrow */}
            <div style={{ fontSize: FS.lspPath, color: C.muted, fontFamily: "monospace", whiteSpace: "normal", wordBreak: "break-word", lineHeight: 1.4 }}>
              {(l.path || []).join(" → ")}
            </div>
            {l.bandwidth_gbps && <div style={{ fontSize: FS.lspBandwidth, color: C.muted }}>{l.bandwidth_gbps} Gbps</div>}
          </div>
        ))}
      </Panel>
    </div>
  );

  const AlarmsPane = (
    <Panel title="Alarms" badge={alarms.filter(a => a.severity === "critical").length} style={{ height: "100%", minHeight: 0 }}>
      {alarms.length === 0 ? (
        <div style={{ fontSize: FS.body, color: C.muted, textAlign: "center", paddingTop: 8 }}>No active alarms</div>
      ) : alarms.slice(-5).map((a, i) => (
        <div key={i} style={{ padding: "5px 0", borderBottom: i < Math.min(alarms.length, 5) - 1 ? `1px solid ${C.border}` : "none", display: "flex", gap: 6, alignItems: "start" }}>
          <span style={{ fontSize: FS.alarmSev, fontWeight: 700, padding: "2px 6px", borderRadius: 3, background: (sevColor[a.severity] || C.yellow) + "18", color: sevColor[a.severity] || C.yellow, fontFamily: "monospace", flexShrink: 0, marginTop: 1 }}>{(a.severity || "warn").slice(0,4).toUpperCase()}</span>
          <span style={{ fontSize: FS.alarm, color: C.text, lineHeight: 1.4, wordBreak: "break-word" }}>{a.description || a.message}</span>
        </div>
      ))}
    </Panel>
  );

  // v2 Email Outbox action handlers — call the backend, rely on the
  // broadcast event to refresh v2Emails state (fetchV2Emails hook above).
  const v2EmailSend = async (id) => {
    try { await fetch(`${API}/api/v2/emails/${id}/send`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }); } catch {}
    fetchV2Emails();
  };
  const v2EmailDiscard = async (id) => {
    try { await fetch(`${API}/api/v2/emails/${id}/discard`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    }); } catch {}
    fetchV2Emails();
  };

  const v2DraftCount = v2Emails.filter(e => e.status === "draft").length;
  const EmailsPane = (
    <Panel title="📧 Email Outbox" badge={v2DraftCount} style={{ height: "100%", minHeight: 0 }}>
      {v2Emails.length === 0 ? (
        <div style={{ fontSize: FS.body, color: C.muted, textAlign: "center", paddingTop: 8 }}>No queued emails</div>
      ) : v2Emails.map(e => (
        <V2EmailRow
          key={e.id}
          email={e}
          onSend={() => v2EmailSend(e.id)}
          onDiscard={() => v2EmailDiscard(e.id)}
          onOpen={(id) => setEmailModal(id)}
        />
      ))}
    </Panel>
  );

  // v2 demo: approve / reject handlers for the new workflow chassis.
  // They hit /api/proposals/{id}/{approve|reject} and optimistically mark
  // the card as deploying so the button spinner state is visible even
  // before the server round-trips.
  const v2Approve = async (id) => {
    setDeployingIds(s => new Set([...s, id]));
    try {
      await fetch(`${API}/api/proposals/${id}/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
    } catch {}
    // Refetch after a bit — the deploy sim is ~1.5s server-side.
    setTimeout(fetchV2, 2200);
    setTimeout(() => setDeployingIds(s => { const n = new Set(s); n.delete(id); return n; }), 2500);
  };
  const v2Reject = async (id) => {
    try {
      await fetch(`${API}/api/proposals/${id}/reject`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
    } catch {}
    fetchV2();
  };

  const v2PendingCount = v2Proposals.filter(p => p.status === "pending").length;
  const ConfigProposalsPane = (
    <Panel title="Config Proposals" badge={v2PendingCount} style={{ height: "100%", minHeight: 0 }}>
      {v2Proposals.length === 0 ? (
        <div style={{ fontSize: FS.body, color: C.muted, textAlign: "center", paddingTop: 14 }}>
          No proposals
        </div>
      ) : v2Proposals.map(p => (
        <V2ProposalCard
          key={p.id}
          p={p}
          isPulsing={pulseId === p.id}
          isNew={entranceId === p.id}
          isDeploying={deployingIds.has(p.id) || p.status === "deploying"}
          onApprove={() => v2Approve(p.id)}
          onReject={() => v2Reject(p.id)}
          onOpen={(id) => setConfigModal(id)}
        />
      ))}
    </Panel>
  );

  const AgentLogPane = (
    <Panel title="Agent Reasoning Log" style={{ height: "100%", minHeight: 0, padding: 0 }}>
      <AgentLogPanel events={events} onOpenModal={() => setLogModalOpen(true)} />
    </Panel>
  );

  // Pane minimums for drag. Left-column width minimum = MIN.topology.w
  // because the topology is the widest thing the left column contains
  // (the bottom-row sub-panes are narrower and can compress into the
  // same width). Bottom row's min height = max(configProps, alarms+emails)
  // so dragging the vertical divider can't crush either pane.
  const leftColMinW   = MIN.topology.w;
  const topRowMinH    = MIN.topology.h;
  const bottomRowMinH = Math.max(MIN.configProps.h, MIN.alarms.h + MIN.emails.h);
  const alarmsColMinW = Math.max(MIN.alarms.w, MIN.emails.w);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Split
        direction="horizontal"
        defaultSizes={[62, 38]}
        minPx={[leftColMinW, MIN.agentLog.w]}
        storageKey="orca.v2.split.root"
      >
        {/* LEFT — topology / controls / config+alarms+emails */}
        <Split
          direction="vertical"
          defaultSizes={[44, 10, 46]}
          minPx={[topRowMinH, MIN.controlsBar.h, bottomRowMinH]}
          storageKey="orca.v2.split.left"
        >
          {/* Top row: topology + right sidebar (status + LSPs) */}
          <Split
            direction="horizontal"
            defaultSizes={[74, 26]}
            minPx={[MIN.topology.w, MIN.lspsSidebar.w]}
            storageKey="orca.v2.split.top"
          >
            {TopologyPane}
            {RightSidebarPane}
          </Split>
          {/* Controls bar — slim, still inside a Split so operator can
              collapse it for more topology height if they want */}
          <div style={{ height: "100%", display: "flex", alignItems: "center" }}>
            <ControlsBar onAnalyze={onAnalyze} onAction={onAction} playingScenario={state.playing_scenario || null} />
          </div>
          {/* Bottom row: proposals on left, alarms+emails on right */}
          <Split
            direction="horizontal"
            defaultSizes={[58, 42]}
            minPx={[MIN.configProps.w, alarmsColMinW]}
            storageKey="orca.v2.split.bottom"
          >
            {ConfigProposalsPane}
            <Split
              direction="vertical"
              defaultSizes={[30, 70]}
              minPx={[MIN.alarms.h, MIN.emails.h]}
              storageKey="orca.v2.split.right-stack"
            >
              {AlarmsPane}
              {EmailsPane}
            </Split>
          </Split>
        </Split>
        {/* RIGHT — full-height agent reasoning log */}
        {AgentLogPane}
      </Split>

      {/* Modals */}
      {logModalOpen && <AgentLogModal events={events} onClose={() => setLogModalOpen(false)} />}

      {/* v2 Proposal modal — look up current state from v2Proposals so the
          modal reflects approve/deploy progress live. Auto-closes if the
          proposal is cleared (e.g. by Reset). */}
      {configModal && (() => {
        const p = v2Proposals.find(x => x.id === configModal);
        if (!p) return null;
        return (
          <V2ProposalModal
            proposal={p}
            onClose={() => setConfigModal(null)}
            onApprove={() => { v2Approve(p.id); setConfigModal(null); }}
            onReject={() => { v2Reject(p.id); setConfigModal(null); }}
            onSaveCommit={() => { fetchV2(); }}
          />
        );
      })()}

      {/* v2 Email modal — same pattern: resolve id against v2Emails list. */}
      {emailModal && (() => {
        const e = v2Emails.find(x => x.id === emailModal);
        if (!e) return null;
        return (
          <V2EmailModal
            email={e}
            onClose={() => setEmailModal(null)}
            onSend={(id) => { v2EmailSend(id); setEmailModal(null); }}
            onDiscard={(id) => { v2EmailDiscard(id); setEmailModal(null); }}
            onEdit={(id, body) => { /* local edit — no backend roundtrip in v2 */ }}
            onSaveDraft={(id, body) => { /* demo-only — edits persist in modal local state */ }}
          />
        );
      })()}
    </div>
  );
}

// ─── CONTRACT STACK TAB (mock — wire later) ───────────────────────────────────
const layers = [
  { id: 1, name: "Product Feature", color: "#f59e0b", health: 0.87, items: [{ name: "Same-day Activation", state: "active", risk: "low" }, { name: "Carrier Agg 3-Band", state: "active", risk: "medium" }, { name: "eSIM Provisioning", state: "piloting", risk: "low" }] },
  { id: 2, name: "Capability", color: "#06b6d4", health: 0.92, items: [{ name: "Real-time Inventory Sync", state: "operational", risk: "low" }, { name: "Multi-carrier Radio Mgmt", state: "degraded", risk: "high" }, { name: "OTA Config Push", state: "operational", risk: "low" }] },
  { id: 3, name: "Policy", color: "#8b5cf6", health: 0.78, items: [{ name: "SCell Activation v3", state: "active", risk: "medium" }, { name: "Reorder Policy", state: "active", risk: "low" }] },
  { id: 4, name: "Managed Object", color: "#10b981", health: 0.95, items: [{ name: "CellDU.sCellConfig", state: "valid", risk: "low" }, { name: "dispatches row", state: "invalid", risk: "high" }] },
  { id: 5, name: "Parameter", color: "#ef4444", health: 0.96, items: [{ name: "maxSCellCount = 2", state: "committed", risk: "low" }, { name: "ui_status = AT_PORT", state: "pending", risk: "medium" }] },
];

function HealthRing({ value, color, size = 36 }) {
  const r = (size - 5) / 2, circ = 2 * Math.PI * r;
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={2.5} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={2.5} strokeDasharray={circ} strokeDashoffset={circ * (1 - value)} strokeLinecap="round" />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, fontFamily: "monospace", color }}>{Math.round(value * 100)}</div>
    </div>
  );
}

function ContractStackTab() {
  const [showLineage, setShowLineage] = useState(false);
  const riskBadge = { low: { bg: "rgba(16,185,129,0.12)", fg: "#10b981" }, medium: { bg: "rgba(245,158,11,0.12)", fg: "#f59e0b" }, high: { bg: "rgba(239,68,68,0.12)", fg: "#ef4444" } };
  const stateColor = { active: "#10b981", operational: "#10b981", valid: "#10b981", committed: "#10b981", piloting: "#06b6d4", pending: "#f59e0b", degraded: "#ef4444", invalid: "#ef4444" };
  const lineageTrace = [{ layer: 5, msg: "maxSCellCount changed 2→0" }, { layer: 4, msg: "CellDU.sCellConfig flagged invalid" }, { layer: 3, msg: "SCell Activation v3 cannot be enforced" }, { layer: 2, msg: "Multi-carrier Radio Mgmt degraded" }, { layer: 1, msg: "Carrier Agg 3-Band at risk" }];
  const conflicts = [
    { sev: "critical", layers: "L1↔L3", title: "Cross-feature param collision", desc: "eSIM needs max_concurrent_syncs≥10. Carrier Agg needs ≤5.", time: "12m", mode: "quarantine" },
    { sev: "warning", layers: "L3→L5", title: "Policy range violation", desc: "SCell Activation v3 requires maxSCellCount [1..4] but pending→0.", time: "34m", mode: "soft flag" },
  ];
  return (
    <div style={{ display: "flex", height: "100%", gap: 12 }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 3, overflow: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted }}>Dependency Stack</span>
          <button onClick={() => setShowLineage(!showLineage)} style={{ background: showLineage ? C.purple + "15" : "rgba(255,255,255,0.03)", border: `1px solid ${showLineage ? C.purple + "44" : C.border}`, color: showLineage ? "#a78bfa" : C.muted, borderRadius: 5, padding: "5px 12px", fontSize: 10, cursor: "pointer", fontFamily: "monospace" }}>{showLineage ? "Lineage Active" : "Show Lineage"}</button>
        </div>
        {layers.map(layer => (
          <div key={layer.id} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", borderLeft: `3px solid ${layer.color}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <HealthRing value={layer.health} color={layer.color} />
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 9, fontWeight: 700, color: layer.color, fontFamily: "monospace", background: layer.color + "18", padding: "1px 5px", borderRadius: 3 }}>L{layer.id}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{layer.name}</span>
                </div>
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                  {layer.items.map((item, j) => (
                    <span key={j} style={{ fontSize: 10, padding: "2px 6px", borderRadius: 3, background: riskBadge[item.risk].bg, color: riskBadge[item.risk].fg, fontFamily: "monospace" }}>
                      <span style={{ display: "inline-block", width: 4, height: 4, borderRadius: "50%", background: stateColor[item.state], marginRight: 4, verticalAlign: "middle" }} />
                      {item.name}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            {showLineage && lineageTrace.find(l => l.layer === layer.id) && (
              <div style={{ marginTop: 8, padding: "6px 10px", borderRadius: 5, background: "rgba(139,92,246,0.06)", borderLeft: "2px solid #a78bfa", fontSize: 11, color: "#c4b5fd", fontFamily: "monospace" }}>
                ↑ {lineageTrace.find(l => l.layer === layer.id).msg}
              </div>
            )}
          </div>
        ))}
      </div>
      <div style={{ width: 320, display: "flex", flexDirection: "column", gap: 10, flexShrink: 0, overflow: "auto" }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted }}>Conflicts · {conflicts.length}</span>
        {conflicts.map((c, i) => (
          <div key={i} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, borderLeft: `3px solid ${sevColor[c.sev]}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 3, background: sevColor[c.sev] + "18", color: sevColor[c.sev], textTransform: "uppercase", fontFamily: "monospace" }}>{c.sev}</span>
              <span style={{ fontSize: 9, color: C.muted, fontFamily: "monospace" }}>{c.time}</span>
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, color: C.text, marginBottom: 3 }}>{c.title}</div>
            <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.4, marginBottom: 6 }}>{c.desc}</div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, fontFamily: "monospace", color: C.purple }}>{c.layers}</span>
              <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: "rgba(255,255,255,0.04)", color: C.muted, fontFamily: "monospace" }}>{c.mode}</span>
            </div>
          </div>
        ))}
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: 1, textTransform: "uppercase", color: C.muted, marginBottom: 8 }}>Operational Chain</div>
          {[{ n: "Checker", c: C.green, t: "rule-based" }, { n: "Reconciler", c: C.blue, t: "deterministic" }, { n: "Explainer", c: C.purple, t: "agent" }, { n: "Human Review", c: C.yellow, t: "approval" }].map((s, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
              <div style={{ width: 22, height: 22, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, fontFamily: "monospace", background: s.c + "15", color: s.c, border: `1px solid ${s.c}33` }}>{i+1}</div>
              <span style={{ fontSize: 11, color: C.text, flex: 1 }}>{s.n}</span>
              <span style={{ fontSize: 9, fontFamily: "monospace", color: s.c }}>{s.t}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── SECURITY TAB (live) ─────────────────────────────────────────────────────
function SecurityTab({ events }) {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/security-alerts`);
        const d = await r.json();
        if (d.alerts && d.alerts.length > 0) setAlerts(d.alerts);
      } catch {}
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, []);

  // Listen for both security_alert and security_alarm
  useEffect(() => {
    const sec = events
      .filter(e => e.type === "security_alert" || e.type === "security_alarm")
      .map(e => e.data?.alert || (e.data ? {
        id: `ws-${e.timestamp || Date.now()}`,
        timestamp: e.timestamp,
        node: e.data.node || "?",
        severity: "critical",
        type: "unauthorized_config_change",
        detail: e.data.message || "",
        status: "detected",
        source: "gNMI",
        provisional: true,
      } : null))
      .filter(Boolean);
    if (sec.length > 0) {
      setAlerts(prev => {
        const merged = [...prev];
        sec.forEach(a => {
          const idx = merged.findIndex(e => e.node === a.node && (e.provisional || e.id === a.id));
          if (idx >= 0) merged[idx] = { ...merged[idx], ...a };
          else merged.push(a);
        });
        return merged;
      });
    }
  }, [events]);

  // When revert proposed — update status
  useEffect(() => {
    const reverts = events.filter(e => e.type === "security_revert_proposed");
    if (reverts.length > 0) {
      setAlerts(prev => prev.map(a =>
        a.provisional ? { ...a, status: "revert proposed — awaiting approval", provisional: false } : a
      ));
    }
  }, [events]);

  const handleReset = async () => {
    await fetch(`${API}/api/demo/security-reset`, { method: "POST" });
    setAlerts([]);
  };

  const mockBase = [
    { ts: "14:18", sev: "high", src: "RADIUS", title: "Brute force auth pattern", detail: "847 failed auths from BRAS-02 in 5min", status: "investigating" },
    { ts: "13:55", sev: "medium", src: "BGP", title: "Anomalous prefix announcement", detail: "AS 64512 advertising 10.0.0.0/8", status: "quarantined" },
    { ts: "13:41", sev: "low", src: "TLS", title: "Certificate expiry in 14d", detail: "gNMI server cert on PE-01", status: "scheduled" },
  ];

  const liveEvents = alerts.map(a => ({
    ts: a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : "live",
    sev: a.severity || "critical",
    src: a.source || "gNMI",
    title: (a.type || "").replace(/_/g, " ") || a.node,
    detail: a.detail || "",
    status: a.status || "active",
    threat_intel: a.threat_intel,
    evidence_url: a.evidence_url,
    remediation_pr_url: a.remediation_pr_url,
    remediation_pr_number: a.remediation_pr_number,
    live: true,
  }));

  const allEvents = [...liveEvents, ...mockBase];
  const counts = {
    critical: allEvents.filter(e => e.sev === "critical").length,
    high:     allEvents.filter(e => e.sev === "high").length,
    medium:   allEvents.filter(e => e.sev === "medium").length,
    low:      allEvents.filter(e => e.sev === "low").length,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, height: "100%", overflow: "auto" }}>
      <div style={{ display: "flex", gap: 10, alignItems: "stretch" }}>
        {[["CRITICAL", counts.critical, "#ef4444"], ["HIGH", counts.high, "#f97316"], ["MEDIUM", counts.medium, "#eab308"], ["LOW", counts.low, "#06b6d4"]].map(([l, n, c]) => (
          <div key={l} style={{ flex: 1, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 14px", borderTop: `2px solid ${c}` }}>
            <div style={{ fontSize: 9, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>{l}</div>
            <div style={{ fontSize: 24, fontWeight: 700, fontFamily: "monospace", color: c }}>{n}</div>
          </div>
        ))}
        <button onClick={handleReset} style={{ padding: "0 16px", borderRadius: 8, fontSize: 11, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, flexShrink: 0, whiteSpace: "nowrap" }}>
          🔄 Reset Demo
        </button>
      </div>
      <Panel title="Security Events" style={{ flex: 1 }}>
        {allEvents.map((ev, i) => (
          <div key={i} style={{ padding: "10px 0", borderBottom: `1px solid ${C.border}` }}>
            <div style={{ display: "grid", gridTemplateColumns: "52px 64px 1fr 120px", gap: 10, alignItems: "start" }}>
              <span style={{ fontSize: 10, fontFamily: "monospace", color: ev.live ? C.red : C.muted }}>{ev.ts}</span>
              <span style={{ fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 3, textAlign: "center", background: sevColor[ev.sev] + "18", color: sevColor[ev.sev], textTransform: "uppercase", fontFamily: "monospace" }}>{ev.sev}</span>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                  <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "rgba(255,255,255,0.04)", color: C.muted, fontFamily: "monospace" }}>{ev.src}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{ev.title}</span>
                  {ev.live && <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: C.red + "18", color: C.red, fontFamily: "monospace" }}>LIVE</span>}
                </div>
                <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.4 }}>{ev.detail}</div>
                {ev.threat_intel && (
                  <div style={{ marginTop: 6, padding: "5px 8px", borderRadius: 4, background: "rgba(239,68,68,0.06)", border: `1px solid ${C.red}22`, fontSize: 10, color: "#fca5a5", lineHeight: 1.5 }}>
                    🔴 {ev.threat_intel}
                  </div>
                )}
                {ev.evidence_url && (
                  <a href={ev.evidence_url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 5, marginRight: 12, fontSize: 10, color: C.blue, textDecoration: "none" }}>
                    📁 Evidence PR → view on GitHub
                  </a>
                )}
                {ev.remediation_pr_url && (
                  <a href={ev.remediation_pr_url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 5, fontSize: 10, color: C.green, textDecoration: "none" }}>
                    🔀 Remediation PR #{ev.remediation_pr_number} → view on GitHub
                  </a>
                )}
              </div>
              <span style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, textAlign: "center", fontFamily: "monospace",
                background: ev.status === "remediated" || ev.status === "resolved" || ev.status === "blocked"
                              ? C.green + "16"
                          : ev.status === "active" ? C.red + "12"
                          : ev.status?.includes("revert") ? C.yellow + "12"
                          : "rgba(255,255,255,0.04)",
                color:      ev.status === "remediated" || ev.status === "resolved" || ev.status === "blocked"
                              ? C.green
                          : ev.status === "active" ? C.red
                          : ev.status?.includes("revert") ? C.yellow
                          : C.muted,
              }}>{ev.status === "remediated" ? "✓ remediated" : ev.status}</span>
            </div>
          </div>
        ))}
      </Panel>
    </div>
  );
}

// ─── CHURN FORECAST ──────────────────────────────────────────────────────────
// v2 demo: 4 regions — top summary / cohort table / time-series / revenue
// callout. Slice-A Enterprise is the star; when /api/churn phase flips
// from "baseline" to "recovered" (after Act 1 deploy), numbers animate
// down over 3s. Baseline snapshot for animation start is hard-coded so
// it works even on a first-mount post-transition.
const CHURN_BASELINE_SNAPSHOT = {
  cohorts: [
    { id: "slice-a", name: "slice-A Enterprise",      is_star: true,  subscribers_total: 842,   at_risk: 423, at_risk_pct: 50.2, arr_exposed_usd: 1_200_000, status: "amber", sparkline: [18,28,42,65,110,180,260,340,423], note: "Session skew + QER drift → p99 climbing" },
    { id: "slice-b", name: "slice-B Consumer",        is_star: false, subscribers_total: 15_000,at_risk: 280, at_risk_pct: 1.9,  arr_exposed_usd: 420_000,   status: "green", sparkline: [265,270,278,282,280,276,279,281,280], note: "Stable — baseline fluctuation" },
    { id: "slice-c", name: "slice-C IoT",             is_star: false, subscribers_total: 50_000,at_risk: 120, at_risk_pct: 0.24, arr_exposed_usd: 180_000,   status: "green", sparkline: [112,116,118,120,122,119,121,120,120], note: "Stable — healthy" },
    { id: "slice-d", name: "slice-D MVNO wholesale",  is_star: false, subscribers_total: 25_000,at_risk: 24,  at_risk_pct: 0.10, arr_exposed_usd: 2_300_000, status: "amber", sparkline: [20,21,22,23,24,24,23,24,24], note: "High $/subscriber — watchlist" },
  ],
  time_series: [
    { t_hours_ago: 24, at_risk: 80 },  { t_hours_ago: 21, at_risk: 88 },
    { t_hours_ago: 18, at_risk: 102 }, { t_hours_ago: 15, at_risk: 135 },
    { t_hours_ago: 12, at_risk: 188 }, { t_hours_ago: 9,  at_risk: 255 },
    { t_hours_ago: 6,  at_risk: 340 }, { t_hours_ago: 3,  at_risk: 395 },
    { t_hours_ago: 0,  at_risk: 423 },
  ],
  at_risk_total: 847,
  revenue_at_risk_usd: 4_100_000,
  forecast_confidence: 87,
  phase: "baseline",
  callout: { cohort: "slice-A Enterprise", subscribers: 842, arr_usd: 2_400_000, sla_commitment: "15ms N3 one-way" },
};

const CHURN_STATUS_STYLE = {
  green: { bg: C.green + "18",  fg: C.green,  label: "GREEN"  },
  amber: { bg: C.yellow + "18", fg: C.yellow, label: "AMBER"  },
  red:   { bg: C.red + "18",    fg: C.red,    label: "RED"    },
};

function fmtMoney(n) {
  const v = Number(n) || 0;
  if (v >= 1_000_000) return `$${(v/1_000_000).toFixed(v >= 10_000_000 ? 0 : 1)}M`;
  if (v >= 1_000)     return `$${(v/1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

function fmtCount(n) {
  const v = Number(n) || 0;
  if (v >= 1_000) return v.toLocaleString();
  return `${v}`;
}

// Tiny SVG sparkline for the cohort table trend column.
function Sparkline({ points, color, width = 70, height = 22 }) {
  if (!points || points.length < 2) return <svg width={width} height={height} />;
  const min = Math.min(...points), max = Math.max(...points);
  const range = Math.max(max - min, 1);
  const sx = (i) => (i / (points.length - 1)) * width;
  const sy = (v) => height - 2 - ((v - min) / range) * (height - 4);
  const d = points.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// Time-series line + area chart. `data` is array of {t_hours_ago, at_risk}.
function AtRiskTimeSeries({ data, sliceAColor }) {
  if (!data || data.length < 2) return null;
  const W = 520, H = 220;
  const padL = 44, padR = 16, padT = 14, padB = 28;
  const pw = W - padL - padR, ph = H - padT - padB;
  const vMin = 0;
  const vMax = Math.max(500, ...data.map(d => d.at_risk));
  // x axis: -24h (left) → 0h "now" (right); recovery point with t_hours_ago<0 extends slightly past
  const tMin = -24, tMax = Math.max(0, ...data.map(d => -d.t_hours_ago));
  const sx = (hoursFromPast) => padL + ((hoursFromPast - tMin) / (tMax - tMin)) * pw;
  const sy = (v) => padT + ph - ((v - vMin) / (vMax - vMin)) * ph;
  const pts = data.map(d => ({ x: sx(-d.t_hours_ago), y: sy(d.at_risk) }));
  const linePath = pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${pts[pts.length-1].x.toFixed(1)},${(padT + ph).toFixed(1)} L${pts[0].x.toFixed(1)},${(padT + ph).toFixed(1)} Z`;
  const ticks = [-24, -20, -16, -12, -8, -4, 0];
  const yTicks = [0, 100, 200, 300, 400, 500];
  const nowX = sx(0);
  return (
    <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: "block" }}>
      {yTicks.map(v => (
        <g key={v}>
          <line x1={padL} x2={W-padR} y1={sy(v)} y2={sy(v)} stroke="rgba(255,255,255,0.05)" />
          <text x={padL-6} y={sy(v)+3} fill="#475569" fontSize={9} textAnchor="end" fontFamily="monospace">{v}</text>
        </g>
      ))}
      {ticks.map(t => (
        <text key={t} x={sx(t)} y={H-8} fill="#475569" fontSize={9} textAnchor="middle" fontFamily="monospace">{t === 0 ? "now" : `${t}h`}</text>
      ))}
      <path d={areaPath} fill={sliceAColor + "22"} />
      <path d={linePath} fill="none" stroke={sliceAColor} strokeWidth={2.2} strokeLinejoin="round" />
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={2.2} fill={sliceAColor} />)}
      <line x1={nowX} x2={nowX} y1={padT} y2={padT + ph} stroke="rgba(255,255,255,0.15)" strokeDasharray="3,3" />
      <text x={nowX + 4} y={padT + 10} fill="#64748b" fontSize={9} fontFamily="monospace">now</text>
    </svg>
  );
}

function ChurnTab({ events }) {
  // Live state from backend (/api/churn). `displayed` is what's actually
  // on screen — animates between baseline and recovered during the grace
  // window, snaps otherwise.
  const [churn, setChurn] = useState(CHURN_BASELINE_SNAPSHOT);
  const [displayed, setDisplayed] = useState(CHURN_BASELINE_SNAPSHOT);
  const animatedForTransitionRef = useRef(null);  // transitioned_at value we already animated for
  const rafRef = useRef(0);

  const fetchChurn = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/churn`);
      const d = await r.json();
      setChurn(d);
    } catch {}
  }, []);

  // Fetch on mount + every 10s + on churn_updated event
  useEffect(() => {
    fetchChurn();
    const t = setInterval(fetchChurn, 10000);
    return () => clearInterval(t);
  }, [fetchChurn]);
  useEffect(() => {
    const last = events[events.length - 1];
    if (last?.type === "churn_updated") fetchChurn();
  }, [events, fetchChurn]);

  // Animation / snap decision whenever churn state changes.
  useEffect(() => {
    if (!churn) return;
    // Cancel any in-flight animation first (defensive — rapid reset+inject
    // cycles shouldn't leave a zombie RAF loop writing stale values).
    if (rafRef.current) cancelAnimationFrame(rafRef.current);

    if (churn.phase === "baseline") {
      animatedForTransitionRef.current = null;
      setDisplayed(churn);
      return;
    }
    // phase === "recovered"
    const tsKey = churn.transitioned_at || "recovered";
    if (animatedForTransitionRef.current === tsKey) {
      // Already played animation for this transition. Keep current displayed.
      setDisplayed(churn);
      return;
    }
    const transitionedAt = churn.transitioned_at ? new Date(churn.transitioned_at).getTime() : 0;
    const dt = Date.now() - transitionedAt;
    if (dt > 8000) {
      // Past grace window — snap. Mark as animated so we don't re-fire.
      animatedForTransitionRef.current = tsKey;
      setDisplayed(churn);
      return;
    }
    // Within grace window → play animation from baseline to recovered.
    animatedForTransitionRef.current = tsKey;
    const from = CHURN_BASELINE_SNAPSHOT;
    const to = churn;
    const durationMs = 3000;
    const startTs = performance.now();
    const interp = (a, b, e) => a + (b - a) * e;

    const step = (now) => {
      const t = Math.min(1, (now - startTs) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);  // ease-out cubic

      // Interpolate cohorts (only slice-A actually changes in the recovery)
      const nextCohorts = to.cohorts.map(toCohort => {
        const fromCohort = from.cohorts.find(c => c.id === toCohort.id) || toCohort;
        if (toCohort.id !== "slice-a") return toCohort;
        return {
          ...toCohort,
          at_risk:         Math.round(interp(fromCohort.at_risk, toCohort.at_risk, eased)),
          at_risk_pct:    +interp(fromCohort.at_risk_pct, toCohort.at_risk_pct, eased).toFixed(1),
          arr_exposed_usd: Math.round(interp(fromCohort.arr_exposed_usd, toCohort.arr_exposed_usd, eased)),
          // Status flips partway through (amber → green at ~70% progress)
          status: eased > 0.7 ? toCohort.status : fromCohort.status,
          // Sparkline cliff revealed at ~70%
          sparkline: eased > 0.7 ? toCohort.sparkline : fromCohort.sparkline,
        };
      });
      const nextAtRiskTotal = nextCohorts.reduce((s, c) => s + c.at_risk, 0);
      const nextRevenue     = nextCohorts.reduce((s, c) => s + c.arr_exposed_usd, 0);
      // Time-series: reveal the recovery drop point at ~50% progress
      const nextSeries = eased > 0.5 ? to.time_series : from.time_series;

      setDisplayed({
        ...to,
        cohorts: nextCohorts,
        at_risk_total:        Math.round(interp(from.at_risk_total,        nextAtRiskTotal, 1)),
        revenue_at_risk_usd:  Math.round(interp(from.revenue_at_risk_usd,  nextRevenue,     1)),
        forecast_confidence:  Math.round(interp(from.forecast_confidence, to.forecast_confidence, eased)),
        time_series:          nextSeries,
      });

      if (t < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [churn]);

  const handleDemoResetChurn = async () => {
    try { await fetch(`${API}/api/churn/reset`, { method: "POST" }); } catch {}
    await fetchChurn();
  };

  if (!displayed) return null;

  const sliceAColor = "#a855f7";  // matches topology slice-A purple
  const sliceA = displayed.cohorts.find(c => c.id === "slice-a");
  // Only the two causally-tied metrics get delta chips. Forecast
  // Confidence is a static baseline — no chip, no implied movement.
  const deltaChips = {
    at_risk: displayed.phase === "recovered" ? "▼ 409 last minute" : "▲ 47 last hour",
    revenue: displayed.phase === "recovered" ? "▼ $1.16M last minute" : "▲ $230K last hour",
    forecast: null,
  };
  const deltaColor = displayed.phase === "recovered" ? C.green : C.muted;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: 12, padding: 12, overflow: "auto", position: "relative" }}>

      {/* Subdued demo-only reset — icon only, muted, tooltip on hover */}
      <button
        onClick={handleDemoResetChurn}
        title="Reset churn state (demo only)"
        aria-label="Reset churn state (demo only)"
        style={{
          position: "absolute", top: 6, right: 10,
          width: 22, height: 22, padding: 0,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, lineHeight: 1,
          background: "transparent", color: "#475569",
          border: `1px solid ${C.border}`, borderRadius: "50%",
          cursor: "pointer",
          opacity: 0.35,
          transition: "opacity 0.15s",
        }}
        onMouseEnter={e => e.currentTarget.style.opacity = "0.75"}
        onMouseLeave={e => e.currentTarget.style.opacity = "0.35"}
      >↻</button>

      {/* REGION A — top summary band */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, flexShrink: 0 }}>
        {[
          { label: "At-risk subscribers",         value: fmtCount(displayed.at_risk_total), chip: deltaChips.at_risk, emphasisColor: displayed.at_risk_total > 500 ? C.yellow : C.green },
          { label: "Revenue at risk · 30-day",    value: fmtMoney(displayed.revenue_at_risk_usd), chip: deltaChips.revenue, emphasisColor: displayed.revenue_at_risk_usd > 3_000_000 ? C.yellow : C.green },
          { label: "Forecast confidence",         value: `${displayed.forecast_confidence}%`, chip: deltaChips.forecast, emphasisColor: C.blue },
        ].map((c, i) => (
          <div key={i} style={{
            background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8,
            borderLeft: `3px solid ${c.emphasisColor}`,
            padding: "14px 18px",
          }}>
            <div style={{ fontSize: FS.logBadge, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 6 }}>{c.label}</div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: "clamp(24px, 2.2vw, 36px)", fontWeight: 700, fontFamily: "monospace", color: C.text, transition: "color 0.4s" }}>
                {c.value}
              </span>
              {c.chip && (
                <span style={{ fontSize: FS.logBadge, fontWeight: 600, fontFamily: "monospace", color: deltaColor }}>
                  {c.chip}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Main two-column area: cohort table + time-series */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 55fr) minmax(0, 45fr)", gap: 12, flex: 1, minHeight: 0 }}>

        {/* REGION B — cohort breakdown */}
        <Panel title="Cohort breakdown">
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) 0.7fr 0.8fr 0.7fr 1fr 80px 0.7fr", columnGap: 10, rowGap: 6, alignItems: "center" }}>
            {/* Header */}
            {["Cohort", "Subscribers", "At risk", "%", "ARR exposed", "Trend", "Status"].map((h, i) => (
              <div key={`h-${i}`} style={{ fontSize: FS.logBadge, color: C.muted, letterSpacing: 1, textTransform: "uppercase", paddingBottom: 6, borderBottom: `1px solid ${C.border}` }}>{h}</div>
            ))}
            {/* Rows */}
            {displayed.cohorts.map(c => {
              const st = CHURN_STATUS_STYLE[c.status] || CHURN_STATUS_STYLE.green;
              const sparkColor = c.is_star ? sliceAColor : (st.fg);
              return (
                <Fragment key={c.id}>
                  <div style={{
                    fontSize: c.is_star ? FS.proposalTitle : FS.body,
                    fontWeight: c.is_star ? 700 : 600,
                    color: C.text,
                    paddingLeft: c.is_star ? 8 : 0,
                    borderLeft: c.is_star ? `3px solid ${sliceAColor}` : "3px solid transparent",
                    padding: c.is_star ? "8px 0 8px 10px" : "7px 0",
                    wordBreak: "break-word",
                  }}>
                    <div>{c.name}</div>
                    <div style={{ fontSize: FS.logTimestamp, color: C.muted, fontWeight: 400, marginTop: 2 }}>{c.note}</div>
                  </div>
                  <div style={{ fontSize: FS.body, fontFamily: "monospace", color: C.muted }}>{fmtCount(c.subscribers_total)}</div>
                  <div style={{ fontSize: FS.body, fontFamily: "monospace", fontWeight: 700, color: C.text, transition: "color 0.4s" }}>{fmtCount(c.at_risk)}</div>
                  <div style={{ fontSize: FS.body, fontFamily: "monospace", color: st.fg }}>{c.at_risk_pct.toFixed(1)}%</div>
                  <div style={{ fontSize: FS.body, fontFamily: "monospace", fontWeight: 600, color: C.text }}>{fmtMoney(c.arr_exposed_usd)}</div>
                  <Sparkline points={c.sparkline} color={sparkColor} />
                  <span style={{
                    justifySelf: "start",
                    fontSize: FS.logBadge, fontWeight: 700, padding: "3px 9px", borderRadius: 4,
                    background: st.bg, color: st.fg, fontFamily: "monospace",
                    transition: "background 0.4s, color 0.4s",
                  }}>
                    {st.label}
                  </span>
                </Fragment>
              );
            })}
          </div>
        </Panel>

        {/* REGION C — time series */}
        <Panel title="Slice-A Enterprise · at-risk subscribers over time">
          <div style={{ display: "flex", flexDirection: "column", height: "100%", gap: 10 }}>
            <div style={{ fontSize: FS.logBadge, color: C.muted }}>last 24 hours · live</div>
            <div style={{ flex: 1, minHeight: 180 }}>
              <AtRiskTimeSeries data={displayed.time_series} sliceAColor={sliceAColor} />
            </div>
          </div>
        </Panel>
      </div>

      {/* REGION D — revenue callout band */}
      <div style={{
        background: "rgba(168,85,247,0.06)",
        border: `1px solid ${sliceAColor}44`,
        borderLeft: `4px solid ${sliceAColor}`,
        borderRadius: 8,
        padding: "12px 18px",
        display: "flex", alignItems: "center", gap: 18,
        flexShrink: 0, flexWrap: "wrap",
      }}>
        <div style={{ fontSize: FS.logBadge, color: C.muted, letterSpacing: 1, textTransform: "uppercase" }}>
          Star cohort
        </div>
        <div style={{ fontSize: FS.proposalTitle, fontWeight: 700, color: C.text }}>
          {displayed.callout?.cohort || "slice-A Enterprise"}
        </div>
        <div style={{ fontSize: FS.body, color: C.muted }}>·</div>
        <div style={{ fontSize: FS.body, fontFamily: "monospace", color: C.text }}>
          {fmtCount(displayed.callout?.subscribers || 842)} subscribers
        </div>
        <div style={{ fontSize: FS.body, color: C.muted }}>·</div>
        <div style={{ fontSize: FS.body, fontFamily: "monospace", fontWeight: 700, color: C.text }}>
          {fmtMoney(displayed.callout?.arr_usd || 2_400_000)} ARR
        </div>
        <div style={{ fontSize: FS.body, color: C.muted }}>·</div>
        <div style={{ fontSize: FS.body, fontFamily: "monospace", color: C.text }}>
          SLA: {displayed.callout?.sla_commitment || "15ms N3 one-way"}
        </div>
      </div>
    </div>
  );
}

// Unused — v1 ChurnTab internals retained for reference but not rendered.
function _v1ChurnTabLegacy({ events }) {
  const [risks, setRisks] = useState({});
  const [lastIncident, setLastIncident] = useState(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/churn-risk`);
        const d = await r.json();
        if (d.risks) setRisks(d.risks);
      } catch {}
    };
    poll();
    const t = setInterval(poll, 10000);
    return () => clearInterval(t);
  }, []);

  // Pick up live churn_risk_update events from WebSocket
  useEffect(() => {
    const latest = [...events].reverse().find(e => e.type === "churn_risk_update");
    if (latest?.data?.risks) setRisks(latest.data.risks);
  }, [events]);

  // Detect incident resolution to show counterfactual
  useEffect(() => {
    const resolved = [...events].reverse().find(e =>
      e.type === "agent_status" && e.data?.status === "complete"
    );
    if (resolved && !lastIncident) {
      setLastIncident({ ts: resolved.timestamp, message: resolved.data?.message });
    }
  }, [events]);

  const bandColor = { healthy: C.green, watch: C.yellow, at_risk: C.orange, critical: C.red };
  const riskList = Object.values(risks);

  // Live current churn rate — avg across LSPs, falls back to trailing history
  const liveProbs = riskList.map(r => r.churn_probability_pct || 0);
  const liveChurn = liveProbs.length
    ? liveProbs.reduce((a,b)=>a+b,0)/liveProbs.length
    : churnHistory[churnHistory.length-1].v;

  // Replace last history point with the live value so the sparkline "now"
  // tracks reality; rebuild forecast as a monotonic decay from live churn.
  const liveHistory = [...churnHistory.slice(0, -1), { m: churnHistory[churnHistory.length-1].m, v: liveChurn }];
  const liveForecast = churnForecast.map((f, i) => {
    const base = liveChurn * (1 - (i + 1) * 0.05);
    const v = Math.max(base, 0.5);
    return { m: f.m, v, lo: Math.max(v - 0.55, 0.2), hi: v + 0.55 };
  });

  // Churn history chart data
  const all = [...liveHistory.map(d => ({ m: d.m })), ...liveForecast.map(d => ({ m: d.m }))];
  const W = 600, H = 160, pL = 35, pR = 15, pT = 15, pB = 25, pW = W-pL-pR, pH = H-pT-pB, mx = 5;
  const x = i => pL + (i/(all.length-1))*pW;
  const y = v => pT + pH - (v/mx)*pH;
  const hPath = liveHistory.map((d,i) => `${i?'L':'M'}${x(i)},${y(d.v)}`).join('');
  const fPath = liveForecast.map((d,i) => `${i?'L':'M'}${x(liveHistory.length+i)},${y(d.v)}`).join('');
  const conn = `M${x(liveHistory.length-1)},${y(liveHistory[liveHistory.length-1].v)} L${x(liveHistory.length)},${y(liveForecast[0].v)}`;
  const bandU = liveForecast.map((d,i) => `${x(liveHistory.length+i)},${y(d.hi)}`).join(' L');
  const bandD = [...liveForecast].reverse().map((d,i) => `${x(liveHistory.length+liveForecast.length-1-i)},${y(d.lo)}`).join(' L');

  const drivers = [
    { d: "Network Quality < 70", pct: 34, seg: "Enterprise" },
    { d: "Ticket Resolution > 48hrs", pct: 22, seg: "SMB" },
    { d: "Price Sensitivity", pct: 18, seg: "Consumer" },
    { d: "Feature Adoption Rate", pct: 14, seg: "All" },
  ];

  return (
    <div style={{ display: "flex", height: "100%", gap: 12 }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10, overflow: "auto" }}>
        {/* KPIs — live from /api/churn-risk */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, flexShrink: 0 }}>
          {(() => {
            const forecastChurn = liveForecast[0].v;
            const atRiskLSPs = riskList.filter(r => r.risk_band === "at_risk" || r.risk_band === "critical");
            const atRiskArr = atRiskLSPs.reduce((s,r)=>s+(r.arr_usd || 0), 0);
            const atRiskArrLabel = atRiskArr >= 1e6 ? `$${(atRiskArr/1e6).toFixed(1)}M`
                                  : atRiskArr >= 1e3 ? `$${(atRiskArr/1e3).toFixed(0)}K`
                                  : `$${atRiskArr.toFixed(0)}`;
            const prevChurn = churnHistory[churnHistory.length-2].v;
            const delta = (liveChurn - prevChurn).toFixed(1);
            const forecastDelta = (forecastChurn - liveChurn).toFixed(1);
            return [
              { l: "Current Churn", v: `${liveChurn.toFixed(1)}%`,
                ch: (delta > 0 ? "+" : "") + delta + "%", bad: liveChurn > prevChurn },
              { l: "Forecast Q3",   v: `${forecastChurn.toFixed(1)}%`,
                ch: (forecastDelta > 0 ? "+" : "") + forecastDelta + "%", bad: false },
              { l: "At-Risk ARR",   v: atRiskArr > 0 ? atRiskArrLabel : "$0",
                ch: atRiskLSPs.length > 0 ? `${atRiskLSPs.length} LSP${atRiskLSPs.length===1?"":"s"}` : "all healthy",
                bad: atRiskLSPs.length > 0 },
            ];
          })().map((c, i) => (
            <div key={i} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: "12px 14px" }}>
              <div style={{ fontSize: 9, letterSpacing: 1, color: C.muted, marginBottom: 4 }}>{c.l}</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                <span style={{ fontSize: 22, fontWeight: 700, fontFamily: "monospace", color: C.text }}>{c.v}</span>
                <span style={{ fontSize: 10, fontWeight: 600, fontFamily: "monospace", color: c.bad ? C.red : C.green }}>{c.ch}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Live SLA Risk per customer */}
        {riskList.length > 0 && (
          <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, flexShrink: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: C.text, marginBottom: 10 }}>Live SLA Risk — Customer LSPs</div>
            {riskList.map(r => (
              <div key={r.lsp_id} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, padding: "8px 10px", borderRadius: 6, background: "rgba(255,255,255,0.02)", border: `1px solid ${C.border}` }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{r.customer}</span>
                    <span style={{ fontSize: 9, padding: "1px 6px", borderRadius: 3, background: bandColor[r.risk_band] + "18", color: bandColor[r.risk_band], fontFamily: "monospace", fontWeight: 700 }}>{r.risk_band}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ width: `${r.risk_score}%`, height: "100%", background: bandColor[r.risk_band], borderRadius: 3, transition: "width 0.8s" }} />
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: bandColor[r.risk_band], minWidth: 36 }}>Risk: {r.risk_score}</span>
                    <span style={{ fontSize: 11, fontFamily: "monospace", color: C.muted, minWidth: 60 }}>Churn: {r.churn_probability_pct}%</span>
                  </div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>
                    {r.segment} · ARR ${(r.arr_usd / 1e6).toFixed(1)}M · {r.reroute_count} reroutes · {r.breach_90_count} SLA breaches
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Counterfactual panel — shown after incident resolution */}
        {lastIncident && (
          <div style={{ background: "rgba(16,185,129,0.05)", border: `1px solid ${C.green}33`, borderRadius: 8, padding: 12, flexShrink: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: C.green, marginBottom: 8 }}>✅ ORCA Impact — Revenue Protected</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div>
                <div style={{ fontSize: 10, color: C.muted, marginBottom: 4 }}>Without ORCA response</div>
                <div style={{ fontSize: 11, color: C.red, fontFamily: "monospace", lineHeight: 1.8 }}>
                  lsp-customer-a degraded ~8 min<br/>
                  Risk score: 12 → 71 (Healthy → At Risk)<br/>
                  Churn probability: 1% → 78%<br/>
                  ARR at risk: $2.4M
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: C.muted, marginBottom: 4 }}>With ORCA (47s response)</div>
                <div style={{ fontSize: 11, color: C.green, fontFamily: "monospace", lineHeight: 1.8 }}>
                  lsp-customer-a degraded &lt;1 min<br/>
                  Risk score: 12 → 34 (Healthy → Watch)<br/>
                  Churn probability: 1% → 5%<br/>
                  Revenue protected: $2.4M ARR
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Churn trend chart */}
        <Panel title="Churn Rate — Actual vs Forecast" style={{ flex: 1, minHeight: 200 }}>
          {/* Legend */}
          <div style={{ display: "flex", gap: 16, marginBottom: 8, flexWrap: "wrap" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <svg width={24} height={8}><line x1={0} y1={4} x2={24} y2={4} stroke={C.text} strokeWidth={2}/></svg>
              <span style={{ fontSize: 10, color: C.muted }}>Actual churn rate</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <svg width={24} height={8}><line x1={0} y1={4} x2={24} y2={4} stroke={C.blue} strokeWidth={2} strokeDasharray="5,3"/></svg>
              <span style={{ fontSize: 10, color: C.muted }}>Forecast (with ORCA)</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <svg width={24} height={8}><line x1={0} y1={4} x2={24} y2={4} stroke={C.red} strokeWidth={1.5} strokeDasharray="3,2"/></svg>
              <span style={{ fontSize: 10, color: C.muted }}>Forecast (without ORCA)</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <svg width={10} height={10}><polygon points="5,0 10,10 0,10" fill={C.yellow}/></svg>
              <span style={{ fontSize: 10, color: C.muted }}>Network incident — ORCA resolved</span>
            </div>
          </div>
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
            {/* Grid */}
            {[0,1,2,3,4,5].map(v => <g key={v}>
              <line x1={pL} x2={W-pR} y1={y(v)} y2={y(v)} stroke="rgba(255,255,255,0.04)" />
              <text x={pL-6} y={y(v)+3} fill="#475569" fontSize={9} textAnchor="end" fontFamily="monospace">{v}%</text>
            </g>)}
            {all.map((d,i) => <text key={i} x={x(i)} y={H-4} fill="#475569" fontSize={8} textAnchor="middle" fontFamily="monospace">{d.m}</text>)}

            {/* Today divider */}
            <line x1={x(5.5)} x2={x(5.5)} y1={pT} y2={H-pB} stroke="rgba(255,255,255,0.1)" strokeDasharray="3,3" />
            <text x={x(5.5)+3} y={pT+8} fill="#475569" fontSize={8} fontFamily="monospace">today</text>

            {/* Confidence band — with ORCA */}
            <path d={`M${bandU} L${bandD} Z`} fill="rgba(6,182,212,0.07)" />

            {/* Counterfactual band — without ORCA (wider, higher, red tint) */}
            <path d={`M${x(5.5)},${y(3.4)} L${x(6)},${y(3.9)} L${x(7)},${y(4.3)} L${x(8)},${y(4.6)} L${x(9)},${y(4.8)} L${x(9)},${y(3.8)} L${x(8)},${y(3.5)} L${x(7)},${y(3.2)} L${x(6)},${y(3.0)} Z`} fill="rgba(239,68,68,0.07)" />

            {/* Actual line */}
            <path d={hPath} fill="none" stroke={C.text} strokeWidth={2} />
            <path d={conn} fill="none" stroke={C.blue} strokeWidth={1.5} strokeDasharray="4,3" />

            {/* Forecast with ORCA */}
            <path d={fPath} fill="none" stroke={C.blue} strokeWidth={2} strokeDasharray="6,3" />

            {/* Forecast WITHOUT ORCA — diverges upward */}
            <path d={`M${x(5.5)},${y(3.4)} L${x(6)},${y(3.85)} L${x(7)},${y(4.2)} L${x(8)},${y(4.45)} L${x(9)},${y(4.6)}`} fill="none" stroke={C.red} strokeWidth={1.5} strokeDasharray="3,2" opacity={0.7} />

            {/* Data points */}
            {churnHistory.map((d,i) => <circle key={i} cx={x(i)} cy={y(d.v)} r={2.5} fill={C.text} />)}
            {churnForecast.map((d,i) => <circle key={i} cx={x(churnHistory.length+i)} cy={y(d.v)} r={2.5} fill={C.blue} />)}

            {/* ── INCIDENT ANNOTATIONS ── */}

            {/* Incident 1: Feb congestion — ORCA resolved */}
            <line x1={x(3)} x2={x(3)} y1={y(3.9)+2} y2={y(3.9)+18} stroke={C.yellow} strokeWidth={1} strokeDasharray="2,2" />
            <polygon points={`${x(3)},${y(3.9)-6} ${x(3)+5},${y(3.9)+4} ${x(3)-5},${y(3.9)+4}`} fill={C.yellow} opacity={0.9} />
            <rect x={x(3)-28} y={y(3.9)-28} width={56} height={18} rx={3} fill="rgba(234,179,8,0.12)" stroke={C.yellow + "44"} />
            <text x={x(3)} y={y(3.9)-16} fill={C.yellow} fontSize={8} textAnchor="middle" fontFamily="monospace">P-02-P-01 congestion</text>
            <text x={x(3)} y={y(3.9)-7} fill={C.yellow} fontSize={7} textAnchor="middle" fontFamily="monospace">ORCA: 23s</text>

            {/* Incident 2: Apr PE-01-PE-04 failure — today, ORCA resolved */}
            <line x1={x(5)} x2={x(5)} y1={y(3.4)+2} y2={y(3.4)+18} stroke={C.red} strokeWidth={1} strokeDasharray="2,2" />
            <polygon points={`${x(5)},${y(3.4)-6} ${x(5)+5},${y(3.4)+4} ${x(5)-5},${y(3.4)+4}`} fill={C.red} opacity={0.9} />
            <rect x={x(5)-32} y={y(3.4)-28} width={64} height={18} rx={3} fill="rgba(239,68,68,0.12)" stroke={C.red + "44"} />
            <text x={x(5)} y={y(3.4)-16} fill={C.red} fontSize={8} textAnchor="middle" fontFamily="monospace">PE-01-PE-04 DOWN</text>
            <text x={x(5)} y={y(3.4)-7} fill={C.green} fontSize={7} textAnchor="middle" fontFamily="monospace">ORCA: 47s ✓</text>

            {/* Gap annotation between with/without ORCA */}
            <line x1={x(8)} x2={x(8)} y1={y(4.45)} y2={y(3.1)} stroke="rgba(255,255,255,0.15)" strokeWidth={1} strokeDasharray="2,2" />
            <text x={x(8)+4} y={y(3.8)} fill={C.red} fontSize={8} fontFamily="monospace" opacity={0.8}>+1.35%</text>
            <text x={x(8)+4} y={y(3.8)+10} fill={C.red} fontSize={7} fontFamily="monospace" opacity={0.7}>without ORCA</text>
          </svg>
        </Panel>
      </div>

      {/* Right: Top Drivers */}
      <div style={{ width: 280, display: "flex", flexDirection: "column", gap: 10, flexShrink: 0, overflow: "auto" }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted }}>Top Drivers</span>
        {drivers.map((d, i) => (
          <div key={i} style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: C.text }}>{d.d}</span>
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: "rgba(255,255,255,0.04)", color: C.muted, fontFamily: "monospace" }}>{d.seg}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ flex: 1, height: 5, background: "rgba(255,255,255,0.04)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ width: `${d.pct*2.5}%`, height: "100%", background: d.pct > 25 ? C.red : d.pct > 15 ? C.yellow : C.blue, borderRadius: 3 }} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, fontFamily: "monospace", color: C.text }}>{d.pct}%</span>
            </div>
          </div>
        ))}
        <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 8, padding: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 8 }}>Model</div>
          <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.7 }}>
            Risk score → churn via logistic curve<br/>
            k=0.08 · midpoint=60<br/>
            Enterprise 0.7× · SMB 1.0× · Consumer 1.4×<br/>
            Window: 24h · 15min intervals
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── TABS ─────────────────────────────────────────────────────────────────────
// Security tab hidden from the nav for v2 PM demo — the pitch drops
// Act 3, and a visible unused tab raises "what's that?" mid-flow. The
// <SecurityTab/> component, its route handler, and the pre-seeded
// ALERT in the reasoning log all remain live. Direct access via
// ?tab=security is preserved for Q&A fallback.
const TABS = [
  { key: "ops",       label: "Operations",      icon: "◉" },
  { key: "contracts", label: "Contract Stack",  icon: "◧" },
  { key: "churn",     label: "Churn Forecast",  icon: "◎" },
];
const HIDDEN_TABS = {
  security: { label: "Security", icon: "◈" },
};

// ─── MAIN APP ─────────────────────────────────────────────────────────────────
export default function App() {
  const [state, setState] = useState({ nodes: {}, links: {}, lsps: {}, alarms: [] });
  // Events start with a single pre-seeded Act 3 ALERT (~3h ago). Reset
  // filters back to just the pre-seed; WebSocket events accumulate on top.
  const [events, setEvents] = useState([PRE_SEEDED_ALERT]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [wsStatus, setWsStatus] = useState("connecting");
  // Initial tab: ?tab=<key> in the URL wins so hidden tabs (e.g. ?tab=security)
  // can still be opened directly for Q&A. Falls back to Operations.
  const [activeTab, setActiveTab] = useState(() => {
    try {
      const q = new URLSearchParams(window.location.search).get("tab");
      if (q) return q;
    } catch {}
    return "ops";
  });
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [emailModal, setEmailModal] = useState(null);
  const [configModal, setConfigModal] = useState(null);
  const wsRef = useRef(null);

  const addEvent = useCallback((event) => {
    setEvents(prev => [...prev.slice(-500), event]);
    if (event.type === "state_update") setState(event.data);
  }, []);

  // WebSocket
  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => setWsStatus("connected");
      ws.onclose = () => { setWsStatus("disconnected"); setTimeout(connect, 3000); };
      ws.onerror = () => setWsStatus("error");
      ws.onmessage = m => { try { addEvent(JSON.parse(m.data)); } catch {} };
    };
    connect();
    return () => wsRef.current?.close();
  }, [addEvent]);

  // Poll state
  useEffect(() => {
    const poll = async () => {
      try { const r = await fetch(`${API}/api/state`); setState(await r.json()); } catch {}
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, []);

  const toggleAgent = async () => {
    if (agentRunning) { await fetch(`${API}/api/agent/stop`, { method: "POST" }); setAgentRunning(false); }
    else { await fetch(`${API}/api/agent/start`, { method: "POST" }); setAgentRunning(true); }
  };

  const analyzeBtn = () => fetch(`${API}/api/agent/analyze`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context: "Full network health check." })
  });

  const handleAction = async (type, linkId, level) => {
    const map = { failure: "/api/demo/inject-failure", congestion: "/api/demo/inject-congestion", restore: "/api/demo/restore-link", reset: "/api/demo/reset" };
    const body = type === "congestion" ? { link_id: linkId, utilization: level } : type === "reset" ? {} : { link_id: linkId };
    try {
      const r = await fetch(`${API}${map[type]}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await r.json();
      // Reset additionally clears the v2 proposal list (belt + suspenders —
      // /api/demo/reset already does this server-side, but hitting the
      // dedicated endpoint also refetches quickly).
      if (type === "reset") {
        try { await fetch(`${API}/api/proposals`, { method: "DELETE" }); } catch {}
        // Clear the reasoning log too, but keep the pre-seeded Act 3 ALERT
        // so the "earlier today" security event survives the reset for
        // the demo narrative ("ORCA was watching the whole time").
        setEvents([PRE_SEEDED_ALERT]);
      }
      setTimeout(async () => { try { const sr = await fetch(`${API}/api/state`); setState(await sr.json()); } catch {} }, 400);
    } catch {}
  };

  const handleConfigAction = async (id, action, comment, changes) => {
    await fetch(`${API}/api/config-proposals/${id}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment, changes })
    });
  };

  const handleEmailSend = async (email) => {
    await fetch(`${API}/api/emails/${email.id}/send`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(email)
    });
  };

  return (
    <div style={{ height: "100vh", background: C.bg, color: C.text, fontFamily: "'DM Sans','Segoe UI',system-ui,sans-serif", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <GlobalStyles />
      {/* HEADER */}
      <div style={{ padding: "10px 20px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", gap: 16, flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginRight: 8 }}>
          <div style={{ width: 32, height: 32, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", background: "linear-gradient(135deg,#06b6d4,#8b5cf6)", fontSize: 16, fontWeight: 800, fontFamily: "monospace", color: "#fff" }}>O</div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, letterSpacing: -0.5, color: "#f0f4f8" }}>ORCA</div>
            <div style={{ fontSize: 9, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted }}>Autonomous Ops & Response</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 2, background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: 3 }}>
          {TABS.map(tab => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{ padding: "7px 16px", borderRadius: 6, border: "none", background: activeTab === tab.key ? "rgba(6,182,212,0.12)" : "transparent", color: activeTab === tab.key ? C.blue : C.muted, fontSize: FS.tabNav, fontWeight: 700, cursor: "pointer", transition: "all 0.15s", display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: FS.body }}>{tab.icon}</span>{tab.label}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span
            title="ORCA demonstration environment · not production data"
            style={{
              fontSize: "clamp(10px, 0.85vw, 12px)", fontWeight: 700, letterSpacing: 1.5,
              padding: "2px 8px", borderRadius: 3,
              border: `1px solid ${C.muted}66`, color: C.muted,
              fontFamily: "monospace", background: "transparent",
              cursor: "help",
            }}
          >DEMO</span>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: wsStatus === "connected" ? C.green : C.red, boxShadow: `0 0 6px ${wsStatus === "connected" ? C.green : C.red}55` }} />
          <span style={{ fontSize: 10, color: C.muted, fontFamily: "monospace" }}>v26 · {window.location.hostname}</span>
        </div>
      </div>

      {/* CONTENT */}
      <div style={{ flex: 1, padding: 12, minHeight: 0, overflow: "hidden" }}>
        {activeTab === "ops" && (
          <OperationsTab
            state={state} events={events} agentRunning={agentRunning} wsStatus={wsStatus}
            onToggleAgent={toggleAgent} onAnalyze={analyzeBtn} onAction={handleAction}
            onConfigAction={handleConfigAction} onEmailSend={handleEmailSend}
            logModalOpen={logModalOpen} setLogModalOpen={setLogModalOpen}
            emailModal={emailModal} setEmailModal={setEmailModal}
            configModal={configModal} setConfigModal={setConfigModal}
          />
        )}
        {activeTab === "contracts" && <ContractStackTab />}
        {activeTab === "security" && <SecurityTab events={events} />}
        {activeTab === "churn" && <ChurnTab events={events} />}
      </div>
    </div>
  );
}


