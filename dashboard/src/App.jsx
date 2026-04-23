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
function Split({ direction = "horizontal", defaultSizes, children, minPct = 6, dividerColor }) {
  const arr = Array.isArray(children) ? children.filter(Boolean) : [children];
  const containerRef = useRef(null);
  const [sizes, setSizes] = useState(
    defaultSizes && defaultSizes.length === arr.length
      ? defaultSizes
      : Array(arr.length).fill(100 / arr.length)
  );
  const dragState = useRef(null);
  const isHoriz = direction === "horizontal";

  const onDividerDown = (i) => (e) => {
    e.preventDefault();
    const rect = containerRef.current.getBoundingClientRect();
    dragState.current = {
      idx: i,
      startCoord: isHoriz ? e.clientX : e.clientY,
      startSizes: [...sizes],
      total: isHoriz ? rect.width : rect.height,
    };
    const onMove = (me) => {
      const ds = dragState.current;
      if (!ds || !ds.total) return;
      const deltaPx = (isHoriz ? me.clientX : me.clientY) - ds.startCoord;
      const deltaPct = (deltaPx / ds.total) * 100;
      const next = [...ds.startSizes];
      const a = ds.startSizes[ds.idx] + deltaPct;
      const b = ds.startSizes[ds.idx + 1] - deltaPct;
      if (a >= minPct && b >= minPct) {
        next[ds.idx] = a;
        next[ds.idx + 1] = b;
        setSizes(next);
      }
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
          <span style={{ fontSize: 12, fontWeight: 700, color: C.text, letterSpacing: 0.3 }}>{title}</span>
          {badge != null && badge > 0 && <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 7px", borderRadius: 10, background: C.red + "22", color: C.red, fontFamily: "monospace" }}>{badge}</span>}
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
    const NODE_FS = Math.round(11 * scale);
    const LSP_FS  = Math.max(9, Math.round(11 * scale));
    const UTIL_FS = Math.max(10, Math.round(15 * scale));

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
        .attr("font-size", UTIL_FS + "px").attr("font-family", "monospace").attr("font-weight", "bold")
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
        .attr("font-size", LSP_FS + "px")
        .attr("font-family", "monospace")
        .attr("font-weight", "700")
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
        .attr("font-size", (d.role === "ran" || d.role === "upf" ? Math.max(9, NODE_FS - 1) : NODE_FS) + "px")
        .attr("font-weight", "700")
        .attr("font-family", "monospace")
        .attr("y", d.role === "upf" ? RECT_H / 2 - 8 : 0)
        .text(d.id);
    });

    // 5. Legend (bottom-right, slice A + B)
    const sliceRows = Object.values(slices || {});
    if (sliceRows.length) {
      const lgW = 280, lgH = 22 * sliceRows.length + 18;
      const lgX = W - lgW - 14, lgY = H - lgH - 10;
      const lg = svg.append("g");
      lg.append("rect")
        .attr("x", lgX).attr("y", lgY)
        .attr("width", lgW).attr("height", lgH)
        .attr("rx", 6)
        .attr("fill", "rgba(17,24,39,0.92)")
        .attr("stroke", C.border);
      sliceRows.forEach((s, i) => {
        const y = lgY + 18 + i * 22;
        lg.append("circle").attr("cx", lgX + 14).attr("cy", y - 4).attr("r", 5)
          .attr("fill", SLICE_COLOR[s.id] || C.muted);
        lg.append("text").attr("x", lgX + 26).attr("y", y)
          .attr("fill", C.text).attr("font-size", "11px").attr("font-family", "monospace")
          .text(`${s.id.toUpperCase()} · ${s.gnb} → ${s.lsp} → ${s.upf}`);
        lg.append("text").attr("x", lgX + lgW - 12).attr("y", y)
          .attr("fill", C.muted).attr("font-size", "10px").attr("font-family", "monospace")
          .attr("text-anchor", "end")
          .text(`${s.subscribers.toLocaleString()} subs · SLA ${s.sla_latency_ms}ms`);
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
  alert: { bg: "#ef444418", color: C.red, label: "ALERT" },
  reasoning: { bg: "#8b5cf618", color: C.purple, label: "THINK" },
  tool_call: { bg: "#06b6d418", color: C.blue, label: "TOOL" },
  tool_result: { bg: "#10b98118", color: C.green, label: "RESULT" },
  notification: { bg: "#eab30818", color: C.yellow, label: "NOTIFY" },
  status: { bg: "#10b98118", color: C.green, label: "STATUS" },
  agent_status: { bg: "#10b98118", color: C.green, label: "STATUS" },
  git_command: { bg: "#06b6d418", color: C.blue, label: "GIT" },
  pr_opened: { bg: "#8b5cf618", color: C.purple, label: "PR" },
  netconf_push: { bg: "rgba(16,185,129,0.10)", color: C.green, label: "NETCONF" },
  state_update: { bg: "rgba(255,255,255,0.02)", color: C.muted, label: "STATE" },
};

const LogEntry = memo(function LogEntry({ entry }) {
  const s = logTypeStyle[entry.type] || logTypeStyle.status;
  // Agent wraps content in entry.data — extract the most useful field
  const data = entry.data || {};
  const msg = entry.message || entry.msg
    || data.message || data.command || data.text
    || (data.tool && data.inputs ? `${data.tool}(\n${JSON.stringify(data.inputs, null, 2)})` : null)
    || (data.tool && data.result ? `${data.tool} → ${typeof data.result === "object" ? JSON.stringify(data.result) : data.result}` : null)
    || (typeof data === "string" ? data : JSON.stringify(data));
  const ts = (() => {
    if (!entry.timestamp) return "";
    const t = entry.timestamp;
    // Already a formatted string
    if (typeof t === "string" && isNaN(Number(t))) return t;
    // Unix epoch in seconds
    const ms = Number(t) < 1e10 ? Number(t) * 1000 : Number(t);
    const d = new Date(ms);
    return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
  })();
  return (
    <div style={{ padding: "8px 10px", marginBottom: 4, borderRadius: 6, background: s.bg, borderLeft: `2px solid ${s.color}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
        <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3, background: s.color + "22", color: s.color, fontFamily: "monospace" }}>{s.label}</span>
        {ts && <span style={{ fontSize: 9, color: C.muted, fontFamily: "monospace" }}>{ts}</span>}
      </div>
      <div style={{ fontSize: 12, color: C.text, lineHeight: 1.6, fontFamily: entry.type === "tool_call" || entry.type === "tool_result" || entry.type === "git_command" ? "monospace" : "inherit" }}>
        {msg}
      </div>
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
    const map = { THINK: ["reasoning", "agent_thinking"], TOOL: ["tool_call", "tool_result", "git_command", "pr_opened"], ALERT: ["alert"] };
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
      const map = { THINK: ["reasoning", "agent_thinking"], TOOL: ["tool_call", "tool_result", "git_command", "pr_opened"], ALERT: ["alert"] };
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
function ControlsBar({ onAnalyze, onAction }) {
  const [link, setLink] = useState("PE-01-PE-04");
  const [level, setLevel] = useState(92);
  const [rogueActive, setRogueActive] = useState(false);
  const links = ["PE-01-P-02","P-02-PE-03","PE-03-PE-04","PE-04-P-01","P-01-PE-02","PE-02-PE-01","PE-01-PE-04","P-02-P-01"];

  const injectRogue = async () => {
    await fetch(`${API}/api/demo/inject-rogue-config`, { method: "POST" });
    setRogueActive(true);
  };
  const clearRogue = async () => {
    await fetch(`${API}/api/demo/clear-rogue-config`, { method: "POST" });
    setRogueActive(false);
  };

  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 7, padding: "7px 12px", display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
      <span style={{ fontSize: 9, fontWeight: 700, color: C.muted, letterSpacing: 1, textTransform: "uppercase", flexShrink: 0 }}>Link</span>
      <select value={link} onChange={e => setLink(e.target.value)} style={{ padding: "3px 6px", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, borderRadius: 4, color: C.text, fontSize: 11 }}>
        {links.map(l => <option key={l} value={l}>{l}</option>)}
      </select>
      <input type="range" min={50} max={99} value={level} onChange={e => setLevel(Number(e.target.value))} style={{ width: 80 }} />
      <span style={{ fontSize: 10, color: C.muted, fontFamily: "monospace", width: 28, flexShrink: 0 }}>{level}%</span>
      <div style={{ width: 1, height: 16, background: C.border, flexShrink: 0 }} />
      <button onClick={() => onAction("failure", link)} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.red + "18", border: `1px solid ${C.red}44`, color: C.red, flexShrink: 0 }}>Inject Fault</button>
      <button onClick={() => onAction("congestion", link, level)} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.orange + "18", border: `1px solid ${C.orange}44`, color: C.orange, flexShrink: 0 }}>Congest</button>
      <button onClick={() => onAction("restore", link)} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: C.green + "18", border: `1px solid ${C.green}44`, color: C.green, flexShrink: 0 }}>Restore</button>
      <button onClick={() => onAction("reset")} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: "rgba(255,255,255,0.04)", border: `1px solid ${C.border}`, color: C.muted, flexShrink: 0 }}>Reset</button>
      <div style={{ width: 1, height: 16, background: C.border, flexShrink: 0 }} />
      <button onClick={rogueActive ? clearRogue : injectRogue} style={{ padding: "4px 9px", borderRadius: 4, fontSize: 10, fontWeight: 600, cursor: "pointer", background: rogueActive ? C.green + "18" : C.purple + "18", border: `1px solid ${rogueActive ? C.green + "44" : C.purple + "44"}`, color: rogueActive ? C.green : C.purple, flexShrink: 0 }}>
        {rogueActive ? "🛡 Clear Rogue" : "🔓 Inject Rogue Config"}
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
              <div style={{ fontSize: 10, color: C.muted, fontFamily: "monospace", marginBottom: 3 }}>To: {e.to}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{e.subject}</div>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
              <button onClick={ev => { ev.stopPropagation(); setFullscreen(true); }} style={{
                padding: "2px 8px", borderRadius: 4, fontSize: 9, fontWeight: 700, cursor: "pointer",
                background: C.blue + "18", border: `1px solid ${C.blue}44`, color: C.blue,
              }}>⤢ View</button>
              <span style={{ fontSize: 9, color: C.muted }}>{expanded ? "▲" : "▼"}</span>
            </div>
          </div>
          {!expanded && (
            <div style={{ fontSize: 11, color: C.muted, marginTop: 4, lineHeight: 1.4 }}>
              {(e.body || "").slice(0, 100).replace(/\n/g, " ")}...
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

// ─── OPERATIONS TAB ──────────────────────────────────────────────────────────
function OperationsTab({ state, events, agentRunning, wsStatus, onToggleAgent, onAnalyze, onAction, onConfigAction, onEmailSend, logModalOpen, setLogModalOpen, emailModal, setEmailModal, configModal, setConfigModal }) {
  const [proposals, setProposals] = useState([]);
  const [emails, setEmails] = useState([]);
  const [notifications, setNotifications] = useState([]);

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
        <span style={{ fontSize: 11, color: C.text, fontWeight: 600 }}>{agentRunning ? "Agent Running" : "Agent Stopped"}</span>
        <button onClick={onToggleAgent} style={{ marginLeft: "auto", padding: "3px 9px", borderRadius: 5, fontSize: 10, fontWeight: 700, background: agentRunning ? C.red + "18" : C.green + "18", border: `1px solid ${agentRunning ? C.red + "44" : C.green + "44"}`, color: agentRunning ? C.red : C.green, cursor: "pointer" }}>
          {agentRunning ? "⏹ Stop" : "▶ Start"}
        </button>
      </div>
      <Panel title="Active LSPs" style={{ flex: 1, minHeight: 0 }}>
        {visibleLsps.length === 0 ? (
          <div style={{ fontSize: 11, color: C.muted, textAlign: "center", paddingTop: 8 }}>No LSP data</div>
        ) : visibleLsps.map(([id, l]) => (
          <div key={id} style={{ padding: "5px 0", borderBottom: `1px solid ${C.border}22`, display: "flex", flexDirection: "column", gap: 2 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 10, fontWeight: 700, fontFamily: "monospace", color: C.blue }}>{id}</span>
              <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: l.state === "up" ? C.green + "12" : C.red + "18", color: l.state === "up" ? C.green : C.red, fontFamily: "monospace" }}>{l.state || "up"}</span>
            </div>
            <div style={{ fontSize: 10, color: C.muted, fontFamily: "monospace" }}>{(l.path || []).join(" → ")}</div>
            {l.bandwidth_gbps && <div style={{ fontSize: 9, color: C.muted }}>{l.bandwidth_gbps}Gbps</div>}
          </div>
        ))}
      </Panel>
    </div>
  );

  const AlarmsPane = (
    <Panel title="Alarms" badge={alarms.filter(a => a.severity === "critical").length} style={{ height: "100%", minHeight: 0 }}>
      {alarms.length === 0 ? (
        <div style={{ fontSize: 11, color: C.muted, textAlign: "center", paddingTop: 8 }}>No active alarms</div>
      ) : alarms.slice(-5).map((a, i) => (
        <div key={i} style={{ padding: "4px 0", borderBottom: i < Math.min(alarms.length, 5) - 1 ? `1px solid ${C.border}` : "none", display: "flex", gap: 6, alignItems: "start" }}>
          <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 5px", borderRadius: 3, background: (sevColor[a.severity] || C.yellow) + "18", color: sevColor[a.severity] || C.yellow, fontFamily: "monospace", flexShrink: 0, marginTop: 1 }}>{(a.severity || "warn").slice(0,4).toUpperCase()}</span>
          <span style={{ fontSize: 11, color: C.text, lineHeight: 1.4 }}>{a.description || a.message}</span>
        </div>
      ))}
    </Panel>
  );

  const EmailsPane = (
    <Panel title="📧 Email Outbox" badge={emails.length} style={{ height: "100%", minHeight: 0 }}>
      {emails.length === 0 ? (
        <div style={{ fontSize: 11, color: C.muted, textAlign: "center", paddingTop: 8 }}>No queued emails</div>
      ) : emails.map(e => <EmailCard key={e.id} email={e} onEdit={() => setEmailModal(e)} />)}
    </Panel>
  );

  const ConfigProposalsPane = (
    <Panel title="Config Proposals" badge={pendingProposals} style={{ height: "100%", minHeight: 0 }}>
            {proposals.length === 0 ? (
              <div style={{ fontSize: 11, color: C.muted, textAlign: "center", paddingTop: 12 }}>No proposals</div>
            ) : proposals.map(cfg => (
              <div key={cfg.id} onClick={() => setConfigModal(cfg)} style={{ background: "rgba(255,255,255,0.02)", border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, marginBottom: 8, cursor: "pointer", borderLeft: `3px solid ${cfg.security ? C.red : C.blue}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {cfg.security && <span style={{ fontSize: 9, padding: "1px 5px", borderRadius: 3, background: C.red + "18", color: C.red, fontFamily: "monospace", fontWeight: 700 }}>SECURITY</span>}
                    <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{cfg.title}</span>
                  </div>
                  <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 4, background: C.yellow + "18", color: C.yellow, fontFamily: "monospace", fontWeight: 700 }}>{cfg.status}</span>
                </div>
                <div style={{ fontSize: 11, color: C.muted, marginBottom: 8, lineHeight: 1.5 }}>{cfg.reason}</div>
                {cfg.projected_improvement && <div style={{ fontSize: 11, fontFamily: "monospace", color: C.green, marginBottom: 8 }}>Projected: {cfg.projected_improvement}</div>}
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 10 }}>
                  {Object.entries(cfg.validation_checks || {}).map(([k, v]) => (
                    <span key={k} style={{ fontSize: 9, padding: "2px 6px", borderRadius: 3, background: v ? C.green + "12" : C.red + "12", color: v ? C.green : C.red, fontFamily: "monospace" }}>{v ? "✓" : "✗"} {k}</span>
                  ))}
                </div>
                <div style={{ background: "#0d1117", borderRadius: 6, padding: 8, fontFamily: "monospace", fontSize: 11, lineHeight: 1.7, maxHeight: 120, overflow: "auto" }}>
                  {(cfg.diff || []).slice(0, 8).map((d, i) => (
                    <div key={i} style={{ padding: "1px 6px", background: d.type === "add" ? "rgba(16,185,129,0.08)" : d.type === "remove" ? "rgba(239,68,68,0.08)" : "transparent", color: d.type === "add" ? C.green : d.type === "remove" ? C.red : C.muted }}>
                      {d.type === "add" ? "+ " : d.type === "remove" ? "- " : "  "}{d.line || d.content}
                    </div>
                  ))}
                </div>
                {cfg.status === "pending" && (
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }} onClick={e => e.stopPropagation()}>
                    <button onClick={() => onConfigAction(cfg.id, "approved", "", cfg.changes)} style={{ flex: 1, padding: 8, borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", background: C.green + "18", border: `1px solid ${C.green}44`, color: C.green }}>✓ Approve & Push</button>
                    <button onClick={() => onConfigAction(cfg.id, "rejected", "", cfg.changes)} style={{ flex: 1, padding: 8, borderRadius: 6, fontSize: 11, fontWeight: 700, cursor: "pointer", background: C.red + "18", border: `1px solid ${C.red}44`, color: C.red }}>✗ Reject</button>
                  </div>
                )}
              </div>
            ))}
    </Panel>
  );

  const AgentLogPane = (
    <Panel title="Agent Reasoning Log" style={{ height: "100%", minHeight: 0, padding: 0 }}>
      <AgentLogPanel events={events} onOpenModal={() => setLogModalOpen(true)} />
    </Panel>
  );

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <Split direction="horizontal" defaultSizes={[62, 38]}>
        {/* LEFT — topology / controls / config+alarms+emails */}
        <Split direction="vertical" defaultSizes={[44, 12, 44]}>
          {/* Top row: topology + right sidebar (status + LSPs) */}
          <Split direction="horizontal" defaultSizes={[74, 26]}>
            {TopologyPane}
            {RightSidebarPane}
          </Split>
          {/* Controls bar — fixed-ish slim row (still inside a Split pane so
              operator can squeeze it if they want more topology height) */}
          <div style={{ height: "100%", display: "flex", alignItems: "center" }}>
            <ControlsBar onAnalyze={onAnalyze} onAction={onAction} />
          </div>
          {/* Bottom row: proposals on left, alarms+emails on right */}
          <Split direction="horizontal" defaultSizes={[58, 42]}>
            {ConfigProposalsPane}
            <Split direction="vertical" defaultSizes={[30, 70]}>
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
      {emailModal && <EmailModal email={emailModal} onClose={() => setEmailModal(null)} onSend={onEmailSend} />}
      {configModal && <ConfigModal proposal={configModal} onClose={() => setConfigModal(null)} onAction={onConfigAction} events={events} />}
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

function ChurnTab({ events }) {
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
const TABS = [
  { key: "ops", label: "Operations", icon: "◉" },
  { key: "contracts", label: "Contract Stack", icon: "◧" },
  { key: "security", label: "Security", icon: "◈" },
  { key: "churn", label: "Churn Forecast", icon: "◎" },
];

// ─── MAIN APP ─────────────────────────────────────────────────────────────────
export default function App() {
  const [state, setState] = useState({ nodes: {}, links: {}, lsps: {}, alarms: [] });
  const [events, setEvents] = useState([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [wsStatus, setWsStatus] = useState("connecting");
  const [activeTab, setActiveTab] = useState("ops");
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
            <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{ padding: "7px 16px", borderRadius: 6, border: "none", background: activeTab === tab.key ? "rgba(6,182,212,0.12)" : "transparent", color: activeTab === tab.key ? C.blue : C.muted, fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all 0.15s", display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11 }}>{tab.icon}</span>{tab.label}
            </button>
          ))}
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
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


