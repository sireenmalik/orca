import { useEffect, useLayoutEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";

const API = "";
const WS_URL = `ws://${window.location.host}/ws`;

const C = {
  bg: "#0d1117", panel: "#161b22", border: "#30363d", text: "#e6edf3",
  muted: "#8b949e", green: "#3fb950", yellow: "#d29922", orange: "#f0883e",
  red: "#f85149", blue: "#58a6ff", accent: "#00b0f0", node: "#1f6feb",
  panel2: "#1c2128",
};

const utilColor = u => u >= 90 ? C.red : u >= 85 ? C.orange : u >= 75 ? C.yellow : C.green;

// ── Draggable Modal ────────────────────────────────────────────────────────────
function Modal({ title, onClose, children, width = "780px" }) {
  const [pos, setPos] = useState(null); // null = centered
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
      const dx = ev.clientX - dragStart.current.mx;
      const dy = ev.clientY - dragStart.current.my;
      setPos({ x: dragStart.current.px + dx, y: dragStart.current.py + dy });
    };
    const onUp = () => { dragging.current = false; window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const posStyle = pos
    ? { position: "fixed", left: pos.x, top: pos.y, transform: "none", margin: 0 }
    : { position: "relative" };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: "20px", pointerEvents: "all"
    }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={modalRef} style={{
        background: C.panel, border: `1px solid ${C.border}`, borderRadius: "10px",
        width: width, maxWidth: "96vw", maxHeight: "92vh",
        display: "flex", flexDirection: "column",
        boxShadow: "0 24px 60px rgba(0,0,0,0.8)",
        ...posStyle
      }}>
        {/* Draggable header */}
        <div onMouseDown={onMouseDown} style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "13px 18px", borderBottom: `1px solid ${C.border}`, flexShrink: 0,
          cursor: "grab", userSelect: "none",
          borderRadius: "10px 10px 0 0",
          background: "#1c2128"
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span style={{ color: "#444", fontSize: "13px" }}>⠿</span>
            <span style={{ color: C.text, fontWeight: "bold", fontSize: "14px" }}>{title}</span>
          </div>
          <button onClick={onClose} style={{
            background: "transparent", border: "none", color: C.muted,
            fontSize: "20px", cursor: "pointer", lineHeight: 1, padding: "0 4px"
          }}>×</button>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {children}
        </div>
      </div>
    </div>
  );
}

// ── Topology ──────────────────────────────────────────────────────────────────
function TopologyMap({ nodes, links }) {
  const wrapRef = useRef(null);
  const svgRef = useRef(null);
  const linksKey = JSON.stringify(links);
  const nodesKey = JSON.stringify(nodes);

  const draw = useCallback(() => {
    if (!nodes || !links || !svgRef.current || !wrapRef.current) return;
    const W = wrapRef.current.clientWidth || 400;
    const H = wrapRef.current.clientHeight || 300;
    d3.select(svgRef.current).selectAll("*").remove();
    const svg = d3.select(svgRef.current).attr("width", W).attr("height", H);
    const pad = Math.min(W, H) * 0.17;
    const cx = W / 2, cy = H / 2;
    const rx = W / 2 - pad, ry = H / 2 - pad;
    const ring = ["R1","R2","R3","R4","R5","R6"];
    const pos = {};
    ring.forEach((id, i) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / 6;
      pos[id] = { x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) };
    });
    const linkData = Object.entries(links).map(([id, l]) => ({
      id, ...l, s: pos[l.src_node || l.src] || { x: cx, y: cy },
      t: pos[l.dst_node || l.dst] || { x: cx, y: cy }, util: l.utilization_pct || 0,
    }));
    const nodeData = Object.entries(nodes).map(([id, n]) => ({ id, ...n, ...(pos[id] || { x: cx, y: cy }) }));
    const nodeR = Math.max(18, Math.min(30, Math.min(rx, ry) * 0.28));
    const fs = Math.max(10, nodeR * 0.55);
    svg.append("g").selectAll("line").data(linkData).enter().append("line")
      .attr("x1", d => d.s.x).attr("y1", d => d.s.y).attr("x2", d => d.t.x).attr("y2", d => d.t.y)
      .attr("stroke", "#000").attr("stroke-width", 10).attr("opacity", 0.4);
    svg.append("g").selectAll("line").data(linkData).enter().append("line")
      .attr("x1", d => d.s.x).attr("y1", d => d.s.y).attr("x2", d => d.t.x).attr("y2", d => d.t.y)
      .attr("stroke", d => d.state === "down" ? "#333" : utilColor(d.util))
      .attr("stroke-width", 4).attr("stroke-dasharray", d => d.state === "down" ? "8,6" : null)
      .attr("opacity", d => d.state === "down" ? 0.3 : 1);
    svg.append("g").selectAll("text").data(linkData).enter().append("text")
      .attr("x", d => (d.s.x + d.t.x) / 2).attr("y", d => (d.s.y + d.t.y) / 2 - 7)
      .attr("text-anchor", "middle").attr("fill", d => d.state === "down" ? C.red : utilColor(d.util))
      .attr("font-size", Math.max(9, fs * 0.75) + "px").attr("font-family", "monospace").attr("font-weight", "bold")
      .text(d => d.state === "down" ? "DOWN" : `${d.util.toFixed(0)}%`);
    svg.append("g").selectAll("circle").data(nodeData).enter().append("circle")
      .attr("cx", d => d.x).attr("cy", d => d.y).attr("r", nodeR + 8).attr("fill", "none")
      .attr("stroke", d => d.state === "down" ? C.red : C.accent).attr("stroke-width", 1.5).attr("opacity", 0.25);
    svg.append("g").selectAll("circle").data(nodeData).enter().append("circle")
      .attr("cx", d => d.x).attr("cy", d => d.y).attr("r", nodeR)
      .attr("fill", d => d.state === "down" ? "#1a1a2e" : C.node)
      .attr("stroke", d => d.state === "down" ? C.red : C.accent).attr("stroke-width", 2);
    svg.append("g").selectAll("text").data(nodeData).enter().append("text")
      .attr("x", d => d.x).attr("y", d => d.y).attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle").attr("fill", C.text)
      .attr("font-size", fs + "px").attr("font-weight", "bold").attr("font-family", "Arial")
      .text(d => d.id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linksKey, nodesKey]);

  useEffect(() => {
    draw();
    const ro = new ResizeObserver(draw);
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, [draw]);

  return (
    <div ref={wrapRef} style={{ width: "100%", height: "100%" }}>
      <svg ref={svgRef} style={{ display: "block", width: "100%", height: "100%" }} />
    </div>
  );
}

function UtilBars({ links }) {
  return (
    <div style={{ overflowY: "auto", height: "100%" }}>
      {Object.entries(links || {}).map(([id, l]) => {
        const u = l.utilization_pct || 0; const down = l.state === "down";
        return (
          <div key={id} style={{ marginBottom: "10px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
              <span style={{ color: C.text, fontSize: "12px", fontFamily: "monospace" }}>{id}</span>
              <span style={{ color: down ? C.red : utilColor(u), fontSize: "12px", fontWeight: "bold" }}>
                {down ? "DOWN" : `${u.toFixed(1)}%`}
              </span>
            </div>
            <div style={{ background: "#21262d", borderRadius: "3px", height: "5px" }}>
              <div style={{ width: `${Math.min(100, u)}%`, background: down ? "#444" : utilColor(u),
                height: "100%", borderRadius: "3px", transition: "width 0.6s ease" }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Alarms({ alarms }) {
  const sc = s => s === "critical" ? C.red : s === "major" ? C.orange : C.yellow;
  if (!alarms.length) return <div style={{ color: C.green, fontSize: "13px" }}>✅ No active alarms</div>;
  return (
    <div style={{ overflowY: "auto", height: "100%" }}>
      {alarms.map((a, i) => (
        <div key={i} style={{ padding: "7px 10px", marginBottom: "6px", borderRadius: "4px",
          borderLeft: `3px solid ${sc(a.severity)}`, background: "#21262d" }}>
          <span style={{ color: sc(a.severity), fontWeight: "bold", fontSize: "10px", textTransform: "uppercase" }}>{a.severity}</span>
          <span style={{ color: C.muted, marginLeft: "6px", fontSize: "11px" }}>{a.node}</span>
          <div style={{ color: C.text, fontSize: "12px", marginTop: "2px" }}>{a.description}</div>
        </div>
      ))}
    </div>
  );
}

function FaultPanel({ links, onAction, lastResult }) {
  const [link, setLink] = useState("R1-R4");
  const [level, setLevel] = useState(92);
  const btn = (label, color, onClick) => (
    <button onClick={onClick} style={{ background: color + "22", border: `2px solid ${color}`, color,
      padding: "11px 0", borderRadius: "6px", cursor: "pointer", fontSize: "13px", fontWeight: "bold", width: "100%" }}>
      {label}
    </button>
  );
  return (
    <div>
      <div style={{ display: "flex", gap: "16px", flexWrap: "wrap", marginBottom: "14px" }}>
        <div style={{ flex: "1", minWidth: "140px" }}>
          <div style={{ color: C.muted, fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.8px", marginBottom: "5px" }}>Target Link</div>
          <select value={link} onChange={e => setLink(e.target.value)} style={{ background: "#21262d", color: C.text,
            border: `1px solid ${C.border}`, padding: "8px 10px", borderRadius: "5px", fontSize: "13px", width: "100%" }}>
            {Object.keys(links || {}).map(id => <option key={id}>{id}</option>)}
          </select>
        </div>
        <div style={{ flex: "3", minWidth: "200px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "5px" }}>
            <span style={{ color: C.muted, fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.8px" }}>Congestion Level</span>
            <span style={{ color: utilColor(level), fontWeight: "bold", fontSize: "13px", fontFamily: "monospace" }}>{level}%</span>
          </div>
          <input type="range" min="75" max="99" value={level} onChange={e => setLevel(+e.target.value)}
            style={{ width: "100%", accentColor: utilColor(level), cursor: "pointer" }} />
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
        {btn("💥 Inject Failure", C.red, () => onAction("failure", link))}
        {btn("📈 Inject Congestion", C.orange, () => onAction("congestion", link, level))}
        {btn("✅ Restore Link", C.green, () => onAction("restore", link))}
        {btn("🔄 Reset All", C.blue, () => onAction("reset"))}
      </div>
      {lastResult && (
        <div style={{ marginTop: "10px", padding: "7px 12px", borderRadius: "5px",
          background: lastResult.success ? C.green + "18" : C.red + "18",
          border: `1px solid ${lastResult.success ? C.green : C.red}`,
          color: lastResult.success ? C.green : C.red, fontSize: "12px", fontFamily: "monospace" }}>
          {lastResult.success ? "✅" : "❌"} {lastResult.message || JSON.stringify(lastResult).slice(0, 100)}
        </div>
      )}
    </div>
  );
}

// ── Agent Log Modal ────────────────────────────────────────────────────────────
function AgentLogModal({ events, onClose }) {
  const ref = useRef(null);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const scrollLocked = useRef(false);
  const prevMeaningfulLen = useRef(0);

  useEffect(() => {
    scrollLocked.current = false;
    prevMeaningfulLen.current = 0;
    const el = ref.current;
    if (!el) return;
    setTimeout(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, 100);
    const onScroll = () => {
        if (!ref.current) return;
        const dist = ref.current.scrollHeight - ref.current.scrollTop - ref.current.clientHeight;
        scrollLocked.current = dist > 100;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  useLayoutEffect(() => {
    const meaningful = events.filter(e => e.type !== 'state_update').length;
    if (meaningful <= prevMeaningfulLen.current) return;
    prevMeaningfulLen.current = meaningful;
    if (scrollLocked.current) return;
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  });

  const meta = {
    agent_reasoning: { icon: "🧠", color: C.blue, label: "Reasoning" },
    tool_call:       { icon: "🔧", color: C.yellow, label: "Tool Call" },
    tool_result:     { icon: "✅", color: C.green, label: "Tool Result" },
    tool_error:      { icon: "❌", color: C.red, label: "Error" },
    agent_status:    { icon: "📡", color: C.accent, label: "Status" },
    agent_thinking:  { icon: "💭", color: C.muted, label: "Thinking" },
    state_update:    { icon: "📊", color: C.muted, label: "State" },
    git_command:     { icon: "⌥", color: "#7ee787", label: "Git" },
  };

  const fmt = (t, d) => {
    if (t === "agent_reasoning") return d.text;
    if (t === "tool_call") return `${d.tool}(\n  ${JSON.stringify(d.inputs, null, 2).slice(1, -1).trim()}\n)`;
    if (t === "tool_result") return `${d.tool} →\n${JSON.stringify(d.result || {}, null, 2)}`;
    if (t === "agent_status" || t === "agent_thinking") return d.message;
    if (t === "state_update") return `Network updated — ${Object.keys(d.links || {}).length} links, ${(d.alarms || []).length} alarms`;
    if (t === "git_command") return d.command;
    if (t === "pr_opened") return `PR #${d.pr_number} opened\n${d.pr_url}`;
    return JSON.stringify(d, null, 2);
  };

  const types = ["all", ...Object.keys(meta)];
  const filtered = events.filter(e => {
    if (filter !== "all" && e.type !== filter) return false;
    if (search) {
      const text = fmt(e.type, e.data || {}).toLowerCase();
      if (!text.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const copyAll = () => {
    const text = events.map(e => {
        const time = new Date(e.timestamp).toLocaleTimeString();
        const d = e.data || {};
        const content = d.text || d.message || d.command || JSON.stringify(d);
        return `[${time}] ${e.type.toUpperCase()}\n${content}`;
    }).join('\n\n');
    navigator.clipboard.writeText(text).then(() => alert('Copied!'));
  };

  return (
    <Modal title={`Agent Reasoning Log — ${events.length} events`} onClose={onClose} width="900px">
      {/* Toolbar */}
      <div style={{ padding: "10px 16px", borderBottom: `1px solid ${C.border}`, flexShrink: 0,
        display: "flex", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
        <input value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search events..." style={{ background: "#21262d", border: `1px solid ${C.border}`,
          color: C.text, padding: "5px 10px", borderRadius: "5px", fontSize: "12px", width: "200px" }} />
        <select value={filter} onChange={e => setFilter(e.target.value)}
          style={{ background: "#21262d", border: `1px solid ${C.border}`, color: C.text,
          padding: "5px 10px", borderRadius: "5px", fontSize: "12px" }}>
          {types.map(t => <option key={t} value={t}>{t === "all" ? "All types" : meta[t]?.label || t}</option>)}
        </select>
        <span style={{ color: C.muted, fontSize: "11px" }}>{filtered.length} events</span>
        <button onClick={copyAll} style={{ marginLeft: "auto", background: "#21262d",
          border: `1px solid ${C.border}`, color: C.muted, padding: "5px 12px",
          borderRadius: "5px", cursor: "pointer", fontSize: "12px" }}>📋 Copy All</button>
      </div>
      {/* Log entries */}
      <div ref={ref}
        style={{ flex: 1, minHeight: 0, overflowY: "scroll", padding: "12px 16px",
        fontFamily: "monospace", fontSize: "12px", lineHeight: "1.6" }}>
        {filtered.length === 0 && (
          <div style={{ color: C.muted, textAlign: "center", padding: "40px" }}>No events match filter</div>
        )}
        {filtered.map((e, i) => {
          const m = meta[e.type] || { icon: "ℹ️", color: C.muted };
          const text = fmt(e.type, e.data || {});
          return (
            <div key={i} style={{
              marginBottom: e.type === "git_command" ? "1px" : "8px",
              padding: e.type === "git_command" ? "3px 10px 3px 12px" : "8px 10px",
              borderRadius: e.type === "git_command" ? "3px" : "5px",
              background: e.type === "git_command" ? "#0d1f0d" : C.panel2,
              border: e.type === "git_command" ? "none" : `1px solid ${C.border}`,
              borderLeft: e.type === "git_command" ? "3px solid #3fb950" : undefined,
            }}>
              {e.type !== "git_command" && (
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                  <span>{m.icon}</span>
                  <span style={{ color: C.muted, fontSize: "10px" }}>{new Date(e.timestamp).toLocaleTimeString()}</span>
                  <span style={{ color: m.color, fontSize: "10px", textTransform: "uppercase",
                    fontWeight: "bold", letterSpacing: "0.5px" }}>{e.type.replace(/_/g, " ")}</span>
                </div>
              )}
              <div style={{ color: m.color, whiteSpace: "pre-wrap", wordBreak: "break-word",
                fontFamily: "monospace", fontSize: e.type === "git_command" ? "12px" : "inherit",
                fontWeight: e.type === "git_command" ? "bold" : "normal" }}>{text}</div>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}

// ── Email Modal ────────────────────────────────────────────────────────────────
function EmailModal({ email, onClose, onSend }) {
  const [subject, setSubject] = useState(email.subject);
  const [body, setBody] = useState(email.body);
  const [to, setTo] = useState(email.to);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSend = async () => {
    setSending(true);
    // Update mailto link with edited content
    await onSend({ ...email, subject, body, to });
    setSending(false);
    setSent(true);
    setTimeout(onClose, 1200);
  };

  const mailto = `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body.slice(0, 1800))}`;
  const sc = subject.includes("CRITICAL") || subject.includes("P1") ? C.red
           : subject.includes("TAC") || subject.includes("P2") ? C.orange : C.green;

  return (
    <Modal title="Email Composer" onClose={onClose} width="820px">
      {/* Fields */}
      <div style={{ padding: "14px 16px", borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        <div style={{ display: "grid", gridTemplateColumns: "60px 1fr", gap: "8px", alignItems: "center", marginBottom: "8px" }}>
          <span style={{ color: C.muted, fontSize: "12px" }}>To</span>
          <input value={to} onChange={e => setTo(e.target.value)}
            style={{ background: "#21262d", border: `1px solid ${C.border}`, color: C.text,
            padding: "6px 10px", borderRadius: "5px", fontSize: "13px" }} />
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "60px 1fr", gap: "8px", alignItems: "center" }}>
          <span style={{ color: C.muted, fontSize: "12px" }}>Subject</span>
          <input value={subject} onChange={e => setSubject(e.target.value)}
            style={{ background: "#21262d", border: `1px solid ${sc}44`, color: sc,
            padding: "6px 10px", borderRadius: "5px", fontSize: "13px", fontWeight: "bold" }} />
        </div>
      </div>
      {/* Body — editable */}
      <div style={{ flex: 1, minHeight: 0, padding: "12px 16px", display: "flex", flexDirection: "column" }}>
        <div style={{ color: C.muted, fontSize: "10px", textTransform: "uppercase",
          letterSpacing: "0.8px", marginBottom: "8px", flexShrink: 0 }}>Message Body — editable</div>
        <textarea value={body} onChange={e => setBody(e.target.value)}
          style={{ flex: 1, minHeight: "260px", background: "#21262d", border: `1px solid ${C.border}`,
          color: C.text, padding: "12px", borderRadius: "6px", fontFamily: "monospace",
          fontSize: "12px", lineHeight: "1.7", resize: "vertical" }} />
      </div>
      {/* Actions */}
      <div style={{ padding: "12px 16px", borderTop: `1px solid ${C.border}`, flexShrink: 0,
        display: "flex", gap: "10px", justifyContent: "flex-end" }}>
        <button onClick={onClose} style={{ background: "transparent", border: `1px solid ${C.border}`,
          color: C.muted, padding: "8px 16px", borderRadius: "6px", cursor: "pointer", fontSize: "13px" }}>
          Cancel
        </button>
        <a href={mailto} style={{ background: C.blue + "22", border: `1px solid ${C.blue}`,
          color: C.blue, padding: "8px 16px", borderRadius: "6px", cursor: "pointer",
          fontSize: "13px", textDecoration: "none", fontWeight: "bold" }}>
          📬 Open in Mail Client
        </a>
        <button onClick={handleSend} disabled={sending || sent}
          style={{ background: sent ? C.green + "22" : C.green + "22",
          border: `2px solid ${sent ? C.green : C.green}`,
          color: sent ? C.green : C.green, padding: "8px 20px",
          borderRadius: "6px", cursor: "pointer", fontSize: "13px", fontWeight: "bold",
          opacity: sending ? 0.6 : 1 }}>
          {sent ? "✅ Sent!" : sending ? "Sending..." : "✉️ Send via SendGrid"}
        </button>
      </div>
    </Modal>
  );
}

// ── Config Modal ───────────────────────────────────────────────────────────────
function ConfigModal({ proposal, onClose, onAction }) {
  const [editedChanges, setEditedChanges] = useState(
    (proposal.changes || []).map(c => ({ ...c, new_config_edited: c.new_config }))
  );
  const [comment, setComment] = useState("");
  const [action, setAction] = useState(null);
  const [activeChange, setActiveChange] = useState(0);

  const currentChange = editedChanges[activeChange] || {};

  const updateConfig = (val) => {
    setEditedChanges(prev => prev.map((c, i) => i === activeChange ? { ...c, new_config_edited: val } : c));
  };

  const renderDiff = (change) => {
    const current = (change.current_config || "").split("\n").filter(l => l.trim());
    const newConf = (change.new_config_edited || change.new_config || "").split("\n").filter(l => l.trim());
    const lines = [];
    current.forEach(l => { if (!newConf.includes(l)) lines.push({ type: "removed", text: l }); });
    newConf.forEach(l => { if (!current.includes(l)) lines.push({ type: "added", text: l }); });
    current.forEach(l => { if (newConf.includes(l)) lines.push({ type: "unchanged", text: l }); });
    lines.sort((a, b) => ({ unchanged: 0, removed: 1, added: 2 }[a.type] - ({ unchanged: 0, removed: 1, added: 2 }[b.type])));
    return lines;
  };

  const handleAction = async (type) => {
    setAction(type);
    await onAction(proposal.id, type, comment, editedChanges);
    setTimeout(onClose, 1000);
  };

  const statusColor = s => s === "approved" ? C.green : s === "rejected" ? C.red : C.yellow;

  return (
    <Modal title={`Config Proposal — ${proposal.title}`} onClose={onClose} width="960px">
      <div style={{ flex: 1, minHeight: 0, display: "flex", overflow: "hidden" }}>

        {/* Left sidebar — summary + validation */}
        <div style={{ width: "260px", flexShrink: 0, borderRight: `1px solid ${C.border}`,
          overflowY: "auto", padding: "14px" }}>

          {/* Status */}
          <div style={{ marginBottom: "14px", padding: "8px 10px", borderRadius: "6px",
            background: statusColor(proposal.status) + "18", border: `1px solid ${statusColor(proposal.status)}44`,
            color: statusColor(proposal.status), fontSize: "12px", fontWeight: "bold", textAlign: "center" }}>
            {proposal.status.toUpperCase()}
          </div>

          {/* Reason */}
          <div style={{ marginBottom: "14px" }}>
            <div style={{ color: C.muted, fontSize: "10px", textTransform: "uppercase",
              letterSpacing: "0.8px", marginBottom: "5px" }}>Reason</div>
            <div style={{ color: C.text, fontSize: "12px", lineHeight: "1.6" }}>{proposal.reason}</div>
          </div>

          {/* Improvement */}
          {proposal.projected_improvement && (
            <div style={{ marginBottom: "14px", padding: "8px 10px", background: C.green + "14",
              borderRadius: "5px", border: `1px solid ${C.green}33` }}>
              <div style={{ color: C.muted, fontSize: "10px", marginBottom: "3px" }}>Projected</div>
              <div style={{ color: C.green, fontSize: "12px", fontWeight: "bold" }}>{proposal.projected_improvement}</div>
            </div>
          )}

          {/* Validation */}
          <div style={{ marginBottom: "14px" }}>
            <div style={{ color: C.muted, fontSize: "10px", textTransform: "uppercase",
              letterSpacing: "0.8px", marginBottom: "8px" }}>Validation</div>
            {Object.entries({
              "Syntax":       proposal.validation?.syntax || "✅ Nokia SR-OS 22.x",
              "Semantic":     proposal.validation?.semantic || "✅ All hops reachable",
              "Mission 1":    proposal.validation?.mission_1 || "✅ All links < 90%",
              "Mission 2":    proposal.validation?.mission_2 || "✅ Max util improves",
              "Digital Twin": proposal.validation?.digital_twin || "✅ Simulated — stable",
              "Policy":       proposal.validation?.policy || "✅ Within policy",
            }).map(([k, v]) => (
              <div key={k} style={{ marginBottom: "5px", padding: "5px 8px",
                background: "#21262d", borderRadius: "4px" }}>
                <div style={{ color: C.muted, fontSize: "10px" }}>{k}</div>
                <div style={{ color: C.green, fontSize: "11px" }}>{v}</div>
              </div>
            ))}
          </div>

          {/* Device tabs */}
          {editedChanges.length > 1 && (
            <div style={{ marginBottom: "14px" }}>
              <div style={{ color: C.muted, fontSize: "10px", textTransform: "uppercase",
                letterSpacing: "0.8px", marginBottom: "6px" }}>Devices</div>
              {editedChanges.map((c, i) => (
                <button key={i} onClick={() => setActiveChange(i)} style={{
                  display: "block", width: "100%", textAlign: "left",
                  background: activeChange === i ? C.blue + "22" : "transparent",
                  border: `1px solid ${activeChange === i ? C.blue : C.border}`,
                  color: activeChange === i ? C.blue : C.muted,
                  padding: "6px 10px", borderRadius: "5px", cursor: "pointer",
                  fontSize: "12px", marginBottom: "4px" }}>
                  📄 {c.device}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right — diff + edit */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Device header */}
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}`,
            flexShrink: 0, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={{ color: C.accent, fontWeight: "bold", fontSize: "13px" }}>
                📄 {currentChange.device}
              </span>
              <span style={{ color: C.muted, marginLeft: "8px", fontSize: "11px" }}>{currentChange.type}</span>
            </div>
            {currentChange.diff_summary && (
              <span style={{ color: C.yellow, fontSize: "11px" }}>{currentChange.diff_summary}</span>
            )}
          </div>

          {/* Split view — diff left, edit right */}
          <div style={{ flex: 1, minHeight: 0, display: "flex", overflow: "hidden" }}>

            {/* Diff view — scrollable */}
            <div style={{ flex: 1, minWidth: 0, borderRight: `1px solid ${C.border}`, overflow: "hidden",
              display: "flex", flexDirection: "column" }}>
              <div style={{ padding: "6px 12px", background: "#0d1117", flexShrink: 0,
                color: C.muted, fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.8px" }}>
                Diff — current vs proposed
              </div>
              <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: "monospace", fontSize: "12px" }}>
                  <tbody>
                    {renderDiff(currentChange).map((line, li) => (
                      <tr key={li} style={{
                        background: line.type === "added" ? "#1a3626" :
                                    line.type === "removed" ? "#3c1c1c" : "transparent" }}>
                        <td style={{ width: "28px", textAlign: "center", padding: "2px 4px",
                          color: line.type === "added" ? C.green : line.type === "removed" ? C.red : "#444",
                          borderRight: `1px solid ${C.border}`, userSelect: "none", fontSize: "13px",
                          fontWeight: "bold" }}>
                          {line.type === "added" ? "+" : line.type === "removed" ? "−" : " "}
                        </td>
                        <td style={{ padding: "2px 10px",
                          color: line.type === "added" ? "#7ee787" :
                                 line.type === "removed" ? "#ff7b72" : "#555",
                          whiteSpace: "pre", lineHeight: "1.6",
                          fontWeight: line.type !== "unchanged" ? "600" : "normal" }}>
                          {line.text}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Edit view — scrollable textarea */}
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
              <div style={{ padding: "6px 12px", background: "#0d1117", flexShrink: 0,
                color: C.muted, fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.8px" }}>
                Proposed config — editable
              </div>
              <textarea value={currentChange.new_config_edited || currentChange.new_config || ""}
                onChange={e => updateConfig(e.target.value)}
                style={{ flex: 1, minHeight: 0, background: "#0d1117", border: "none",
                color: C.text, padding: "8px 12px", fontFamily: "monospace",
                fontSize: "12px", lineHeight: "1.7", resize: "none", outline: "none" }} />
            </div>
          </div>

          {/* Comment box */}
          <div style={{ padding: "10px 14px", borderTop: `1px solid ${C.border}`, flexShrink: 0 }}>
            <input value={comment} onChange={e => setComment(e.target.value)}
              placeholder="Add a comment (optional)..."
              style={{ width: "100%", background: "#21262d", border: `1px solid ${C.border}`,
              color: C.text, padding: "7px 12px", borderRadius: "5px", fontSize: "12px" }} />
          </div>

          {/* Action buttons */}
          {(proposal.status === "pending" || proposal.status === "saved") && (
            <div style={{ padding: "10px 14px", borderTop: `1px solid ${C.border}`, flexShrink: 0,
              display: "flex", gap: "10px" }}>
              <button onClick={() => handleAction("rejected")} disabled={!!action}
                style={{ background: C.red + "22", border: `2px solid ${C.red}`, color: C.red,
                padding: "9px 20px", borderRadius: "6px", cursor: "pointer",
                fontSize: "13px", fontWeight: "bold", opacity: action ? 0.6 : 1 }}>
                ❌ Reject
              </button>
              <button onClick={() => handleAction("saved")} disabled={!!action}
                style={{ background: C.yellow + "22", border: `2px solid ${C.yellow}`, color: C.yellow,
                padding: "9px 20px", borderRadius: "6px", cursor: "pointer",
                fontSize: "13px", fontWeight: "bold", opacity: action ? 0.6 : 1 }}>
                💾 Save
              </button>
              <button onClick={() => handleAction("committed")} disabled={!!action}
                style={{ background: C.blue + "22", border: `2px solid ${C.blue}`, color: C.blue,
                padding: "9px 20px", borderRadius: "6px", cursor: "pointer",
                fontSize: "13px", fontWeight: "bold", opacity: action ? 0.6 : 1 }}>
                🔀 Save & Commit
              </button>
              <button onClick={() => handleAction("approved")} disabled={!!action}
                style={{ marginLeft: "auto", background: C.green + "22", border: `2px solid ${C.green}`,
                color: C.green, padding: "9px 24px", borderRadius: "6px", cursor: "pointer",
                fontSize: "13px", fontWeight: "bold", opacity: action ? 0.6 : 1 }}>
                {action === "approved" ? "Pushing..." : "✅ Approve & Push"}
              </button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

// ── Agent Log Panel (compact, opens modal) ────────────────────────────────────
function AgentLog({ events, onOpenModal }) {
  const ref = useRef(null);
  const lockedByUser = useRef(false);
  const prevEventCount = useRef(0);

  // Attach scroll listener once on mount — track if user scrolled up
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onScroll = () => {
      const dist = el.scrollHeight - el.scrollTop - el.clientHeight;
      lockedByUser.current = dist > 80;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Only scroll to bottom when NEW events arrive AND user hasn't scrolled up
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (events.length > prevEventCount.current && !lockedByUser.current) {
      el.scrollTop = el.scrollHeight;
    }
    prevEventCount.current = events.length;
  }, [events]);
  const meta = {
    agent_reasoning: { icon: "🧠", color: C.blue },
    tool_call:       { icon: "🔧", color: C.yellow },
    tool_result:     { icon: "✅", color: C.green },
    tool_error:      { icon: "❌", color: C.red },
    agent_status:    { icon: "📡", color: C.accent },
    agent_thinking:  { icon: "💭", color: C.muted },
    state_update:    { icon: "📊", color: C.muted },
    git_command:     { icon: "⌥", color: "#7ee787" },
    pr_opened:       { icon: "🔀", color: C.blue },
  };
  const fmt = (t, d) => {
    if (t === "agent_reasoning") return d.text;
    if (t === "tool_call") return `${d.tool}(${JSON.stringify(d.inputs)})`;
    if (t === "tool_result") return `${d.tool} → ${JSON.stringify(d.result || {}).slice(0, 120)}`;
    if (t === "agent_status" || t === "agent_thinking") return d.message;
    if (t === "state_update") return `Network updated — ${Object.keys(d.links || {}).length} links, ${(d.alarms || []).length} alarms`;
    if (t === "git_command") return d.command;
    if (t === "pr_opened") return `PR #${d.pr_number} opened — ${d.pr_url}`;
    return JSON.stringify(d).slice(0, 100);
  };
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {events.length > 0 && (
        <button onClick={onOpenModal} style={{ flexShrink: 0, marginBottom: "8px",
          background: "transparent", border: `1px solid ${C.border}`, color: C.muted,
          padding: "4px 10px", borderRadius: "4px", cursor: "pointer", fontSize: "11px",
          alignSelf: "flex-end" }}>
          ⤢ Expand
        </button>
      )}
      <div ref={ref}
        style={{ flex: 1, minHeight: 0, overflowY: "scroll", fontFamily: "monospace",
        fontSize: "12px", lineHeight: "1.6", paddingRight: "4px" }}>
        {events.length === 0 && (
          <div style={{ color: C.muted, padding: "20px", textAlign: "center" }}>
            Click <strong style={{ color: C.blue }}>Analyze</strong> or <strong style={{ color: C.green }}>Start Agent</strong> to begin.
          </div>
        )}
        {events.map((e, i) => {
          const m = meta[e.type] || { icon: "ℹ️", color: C.muted };
          const isGit = e.type === "git_command";
          const isPR = e.type === "pr_opened";
          return (
            <div key={i} style={{
              marginBottom: "4px", paddingBottom: "4px",
              borderBottom: `1px solid ${C.border}`,
              ...(isGit ? {
                background: "#0d1f0d",
                borderLeft: "3px solid #3fb950",
                paddingLeft: "8px",
                borderBottom: "none",
                marginBottom: "1px",
              } : {}),
              ...(isPR ? {
                background: C.blue + "11",
                borderLeft: `3px solid ${C.blue}`,
                paddingLeft: "8px",
                borderRadius: "4px",
                padding: "6px 8px",
              } : {})
            }}>
              <span style={{ color: C.muted, fontSize: "10px" }}>{new Date(e.timestamp).toLocaleTimeString()}</span>
              <span style={{ margin: "0 5px" }}>{m.icon}</span>
              {isPR && e.data?.pr_url ? (
                <span style={{ color: m.color }}>
                  PR #{e.data.pr_number} opened — {" "}
                  <a href={e.data.pr_url} target="_blank" rel="noreferrer"
                    style={{ color: C.blue, fontWeight: "bold" }}>
                    View on GitHub ↗
                  </a>
                </span>
              ) : (
                <span style={{ color: m.color, whiteSpace: "pre-wrap", wordBreak: "break-word",
                  fontWeight: isGit ? "bold" : "normal" }}>{fmt(e.type, e.data)}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Email Outbox Panel (compact, opens modal) ─────────────────────────────────
function EmailInbox({ onOpenEmail }) {
  const [emails, setEmails] = useState([]);
  useEffect(() => {
    const poll = async () => {
      try { const r = await fetch(`${API}/api/emails`); const d = await r.json(); setEmails(d.emails || []); } catch {}
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, []);
  const clear = async () => { await fetch(`${API}/api/emails`, { method: "DELETE" }); setEmails([]); };
  const sc = s => s.includes("CRITICAL") || s.includes("P1") ? C.red : s.includes("TAC") || s.includes("P2") ? C.orange : C.green;
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px", flexShrink: 0 }}>
        <span style={{ color: C.muted, fontSize: "11px" }}>{emails.length} email{emails.length !== 1 ? "s" : ""}</span>
        {emails.length > 0 && (
          <button onClick={clear} style={{ background: "transparent", border: `1px solid ${C.border}`,
            color: C.muted, padding: "2px 8px", borderRadius: "4px", cursor: "pointer", fontSize: "11px" }}>Clear</button>
        )}
      </div>
      {emails.length === 0 && (
        <div style={{ color: C.muted, textAlign: "center", padding: "20px", fontSize: "12px" }}>
          No emails yet — run ORCA to generate alerts.
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {emails.map(e => (
          <div key={e.id} onClick={() => onOpenEmail(e)}
            style={{ padding: "9px 11px", marginBottom: "6px", borderRadius: "6px",
            background: C.panel2, border: `1px solid ${C.border}`, cursor: "pointer",
            transition: "border-color 0.15s" }}
            onMouseEnter={el => el.currentTarget.style.borderColor = C.blue}
            onMouseLeave={el => el.currentTarget.style.borderColor = C.border}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "3px" }}>
              <div style={{ width: "7px", height: "7px", borderRadius: "50%", background: sc(e.subject), flexShrink: 0 }} />
              <span style={{ color: C.text, fontSize: "12px", fontWeight: "bold",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                {e.subject.replace(/[🔴🟠🟡🟢⚡]/g, "").trim().slice(0, 45)}
              </span>
            </div>
            <div style={{ color: C.muted, fontSize: "10px" }}>
              To: {e.to} · {new Date(e.timestamp).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Config Proposals Panel (compact, opens modal) ─────────────────────────────
function ConfigPanel({ onOpenProposal }) {
  const [proposals, setProposals] = useState([]);
  useEffect(() => {
    const poll = async () => {
      try { const r = await fetch(`${API}/api/config-proposals`); const d = await r.json(); setProposals(d.proposals || []); } catch {}
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, []);
  const clear = async () => { await fetch(`${API}/api/config-proposals`, { method: "DELETE" }); setProposals([]); };
  const sc = s => s === "approved" ? C.green : s === "rejected" ? C.red : s === "committed" ? C.blue : C.yellow;
  const si = s => s === "approved" ? "✅" : s === "rejected" ? "❌" : s === "committed" ? "🔀" : s === "saved" ? "💾" : "⏳";
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "8px", flexShrink: 0 }}>
        <span style={{ color: C.muted, fontSize: "11px" }}>{proposals.length} proposal{proposals.length !== 1 ? "s" : ""}</span>
        {proposals.length > 0 && (
          <button onClick={clear} style={{ background: "transparent", border: `1px solid ${C.border}`,
            color: C.muted, padding: "2px 8px", borderRadius: "4px", cursor: "pointer", fontSize: "11px" }}>Clear</button>
        )}
      </div>
      {proposals.length === 0 && (
        <div style={{ color: C.muted, textAlign: "center", padding: "20px", fontSize: "12px" }}>
          No proposals yet — run ORCA after a fault.
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {proposals.map(p => (
          <div key={p.id} onClick={() => onOpenProposal(p)}
            style={{ padding: "9px 11px", marginBottom: "6px", borderRadius: "6px",
            background: C.panel2, border: `1px solid ${sc(p.status)}44`, cursor: "pointer" }}
            onMouseEnter={el => el.currentTarget.style.borderColor = C.blue}
            onMouseLeave={el => el.currentTarget.style.borderColor = sc(p.status) + "44"}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
              <span style={{ color: C.text, fontSize: "12px", fontWeight: "bold",
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                {p.title?.slice(0, 40)}
              </span>
              <span style={{ color: sc(p.status), fontSize: "12px", marginLeft: "6px" }}>{si(p.status)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: sc(p.status), fontSize: "10px", textTransform: "uppercase" }}>{p.status}</span>
              <span style={{ color: C.muted, fontSize: "10px" }}>{new Date(p.timestamp).toLocaleTimeString()}</span>
            </div>
            {p.projected_improvement && (
              <div style={{ color: C.green, fontSize: "10px", marginTop: "2px" }}>📈 {p.projected_improvement}</div>
            )}
            {p.pr_url && (
              <a href={p.pr_url} target="_blank" rel="noreferrer"
                style={{ color: C.blue, fontSize: "10px", marginTop: "2px", display: "block",
                textDecoration: "none", fontWeight: "bold" }}
                onClick={e => e.stopPropagation()}>
                🔀 PR #{p.pr_number} — View on GitHub ↗
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Panel({ title, children, style = {}, action }) {
  return (
    <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: "8px",
      padding: "14px", display: "flex", flexDirection: "column", overflow: "hidden", ...style }}>
      {title && (
        <div style={{ color: C.muted, fontSize: "10px", fontWeight: "bold", textTransform: "uppercase",
          letterSpacing: "1.2px", borderBottom: `1px solid ${C.border}`,
          paddingBottom: "8px", marginBottom: "12px", flexShrink: 0,
          display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span>{title}</span>
          {action}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>{children}</div>
    </div>
  );
}

const TABS = ["Topology", "Utilization", "Controls", "Agent Log", "Emails", "Config"];

function TabBar({ active, onChange, configBadge }) {
  return (
    <div style={{ display: "flex", background: C.panel, borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
      {TABS.map(t => (
        <button key={t} onClick={() => onChange(t)} style={{ flex: 1, padding: "10px 2px",
          background: "transparent", border: "none",
          borderBottom: active === t ? `2px solid ${C.accent}` : "2px solid transparent",
          color: active === t ? C.accent : C.muted,
          fontSize: "11px", fontWeight: active === t ? "bold" : "normal",
          cursor: "pointer", whiteSpace: "nowrap", position: "relative" }}>
          {t}
          {t === "Config" && configBadge > 0 && (
            <span style={{ position: "absolute", top: "4px", right: "1px", background: C.yellow,
              color: "#000", borderRadius: "8px", padding: "0 4px", fontSize: "9px", fontWeight: "bold" }}>
              {configBadge}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export default function App() {
  const [state, setState] = useState({ nodes: {}, links: {}, lsps: {}, alarms: [] });
  const [events, setEvents] = useState([]);
  const [agentRunning, setAgentRunning] = useState(false);
  const [wsStatus, setWsStatus] = useState("connecting");
  const [tab, setTab] = useState("Topology");
  const [lastResult, setLastResult] = useState(null);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 900);
  const [configBadge, setConfigBadge] = useState(0);
  const wsRef = useRef(null);

  // Modal state
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [emailModal, setEmailModal] = useState(null);
  const [configModal, setConfigModal] = useState(null);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 900);
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch(`${API}/api/config-proposals`);
        const d = await r.json();
        setConfigBadge((d.proposals || []).filter(p => p.status === "pending").length);
      } catch {}
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => clearInterval(t);
  }, []);

  const addEvent = useCallback((event) => {
    setEvents(prev => [...prev.slice(-500), event]);
    if (event.type === "state_update") setState(event.data);
  }, []);

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
    const map = { failure: "/api/demo/inject-failure", congestion: "/api/demo/inject-congestion",
                  restore: "/api/demo/restore-link", reset: "/api/demo/reset" };
    const body = type === "congestion" ? { link_id: linkId, utilization: level }
               : type === "reset" ? {} : { link_id: linkId };
    try {
      const r = await fetch(`${API}${map[type]}`, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await r.json();
      setLastResult(result);
      const repoll = async () => {
        try { const sr = await fetch(`${API}/api/state`); setState(await sr.json()); } catch {}
      };
      setTimeout(repoll, 400);
      setTimeout(repoll, 2000);
    } catch (e) { setLastResult({ success: false, message: e.message }); }
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

  const alarmCount = (state.alarms || []).length;

  const Header = ({ mobile }) => (
    <div style={{ height: mobile ? "44px" : "48px", flexShrink: 0, background: C.panel,
      borderBottom: `1px solid ${C.border}`, padding: "0 14px",
      display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ fontSize: "18px" }}>⚡</span>
        <span style={{ color: C.accent, fontWeight: "bold", fontSize: mobile ? "15px" : "16px" }}>ORCA</span>
        {!mobile && <span style={{ color: C.muted, fontSize: "12px" }}>Autonomous Network Operations & Response Agent</span>}
        {alarmCount > 0 && (
          <span style={{ background: C.red + "33", border: `1px solid ${C.red}`, color: C.red,
            borderRadius: "10px", padding: "1px 8px", fontSize: "11px", fontWeight: "bold" }}>
            {alarmCount} alarm{alarmCount > 1 ? "s" : ""}
          </span>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ fontSize: "11px", color: wsStatus === "connected" ? C.green : C.red }}>●</span>
        {!mobile && (
          <button onClick={analyzeBtn} style={{ background: C.blue + "22", border: `1px solid ${C.blue}`,
            color: C.blue, padding: "5px 14px", borderRadius: "5px", cursor: "pointer",
            fontSize: "12px", fontWeight: "bold" }}>🔍 Analyze</button>
        )}
        <button onClick={toggleAgent} style={{
          background: agentRunning ? C.red + "22" : C.green + "22",
          border: `1px solid ${agentRunning ? C.red : C.green}`,
          color: agentRunning ? C.red : C.green, padding: "5px 12px",
          borderRadius: "5px", cursor: "pointer", fontSize: "12px", fontWeight: "bold" }}>
          {agentRunning ? (mobile ? "⏹ Stop" : "⏹ Stop Agent") : (mobile ? "▶ Start" : "▶ Start Agent")}
        </button>
      </div>
    </div>
  );

  // Modals rendered at root level
  const Modals = () => (
    <>
      {emailModal && <EmailModal email={emailModal} onClose={() => setEmailModal(null)} onSend={handleEmailSend} />}
      {configModal && <ConfigModal proposal={configModal} onClose={() => setConfigModal(null)} onAction={handleConfigAction} />}
    </>
  );

  if (!isMobile) {
    return (
      <div style={{ background: C.bg, height: "100vh", color: C.text,
        fontFamily: "Arial, sans-serif", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <Modals />
        {logModalOpen && <AgentLogModal events={events} onClose={() => setLogModalOpen(false)} />}
        <Header />
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", padding: "12px", gap: "12px" }}>
          {/* Top row */}
          <div style={{ flex: "0 0 calc(50vh - 60px)", minHeight: 0, display: "flex", gap: "12px" }}>
            <Panel title="Network Topology" style={{ flex: "1 1 0", minWidth: 0 }}>
              <TopologyMap nodes={state.nodes} links={state.links} />
            </Panel>
            <div style={{ width: "270px", flexShrink: 0, display: "flex", flexDirection: "column", gap: "12px" }}>
              <Panel title="Link Utilization" style={{ flex: "1 1 0", minHeight: 0 }}>
                <UtilBars links={state.links} />
              </Panel>
              <Panel title={`Active Alarms${alarmCount > 0 ? ` (${alarmCount})` : ""}`}
                style={{ flex: "0 0 auto", maxHeight: "145px" }}>
                <Alarms alarms={state.alarms || []} />
              </Panel>
            </div>
          </div>
          {/* Fault controls */}
          <Panel title="Demo Controls — Fault Injection" style={{ flex: "0 0 auto" }}>
            <FaultPanel links={state.links} onAction={handleAction} lastResult={lastResult} />
          </Panel>
          {/* Bottom row */}
          <div style={{ flex: "1 1 0", minHeight: 0, display: "flex", gap: "12px" }}>
            <Panel title="Agent Reasoning Log" style={{ flex: "1 1 0", minHeight: 0 }}>
              <AgentLog events={events} onOpenModal={() => setLogModalOpen(true)} />
            </Panel>
            <Panel title={`📋 Config Proposals${configBadge > 0 ? ` (${configBadge})` : ""}`}
              style={{ flex: "0 0 320px", minHeight: 0 }}>
              <ConfigPanel onOpenProposal={p => setConfigModal(p)} />
            </Panel>
            <Panel title="📧 Email Outbox" style={{ flex: "0 0 300px", minHeight: 0 }}>
              <EmailInbox onOpenEmail={e => setEmailModal(e)} />
            </Panel>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ background: C.bg, height: "100vh", color: C.text,
      fontFamily: "Arial, sans-serif", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <Modals />
      {logModalOpen && <AgentLogModal events={events} onClose={() => setLogModalOpen(false)} />}
      <Header mobile />
      <TabBar active={tab} onChange={setTab} configBadge={configBadge} />
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden", padding: "10px" }}>
        {tab === "Topology" && (
          <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "10px" }}>
            <Panel title="Network Topology" style={{ flex: "1 1 0", minHeight: 0 }}>
              <TopologyMap nodes={state.nodes} links={state.links} />
            </Panel>
            <Panel title={`Active Alarms${alarmCount > 0 ? ` (${alarmCount})` : ""}`}
              style={{ flex: "0 0 auto", maxHeight: "140px" }}>
              <Alarms alarms={state.alarms || []} />
            </Panel>
          </div>
        )}
        {tab === "Utilization" && <Panel title="Link Utilization" style={{ height: "100%" }}><UtilBars links={state.links} /></Panel>}
        {tab === "Controls" && (
          <div style={{ height: "100%", display: "flex", flexDirection: "column", gap: "10px", overflowY: "auto" }}>
            <Panel title="Demo Controls — Fault Injection">
              <FaultPanel links={state.links} onAction={handleAction} lastResult={lastResult} />
            </Panel>
            <button onClick={() => { analyzeBtn(); setTab("Agent Log"); }} style={{
              background: C.blue + "22", border: `2px solid ${C.blue}`, color: C.blue,
              padding: "12px", borderRadius: "8px", cursor: "pointer", fontSize: "13px", fontWeight: "bold" }}>
              🔍 Run Analysis Now
            </button>
          </div>
        )}
        {tab === "Agent Log" && (
          <Panel title="Agent Reasoning Log" style={{ height: "100%" }}>
            <AgentLog events={events} onOpenModal={() => setLogModalOpen(true)} />
          </Panel>
        )}
        {tab === "Emails" && (
          <Panel title="📧 Email Outbox" style={{ height: "100%" }}>
            <EmailInbox onOpenEmail={e => setEmailModal(e)} />
          </Panel>
        )}
        {tab === "Config" && (
          <Panel title="📋 Config Proposals" style={{ height: "100%" }}>
            <ConfigPanel onOpenProposal={p => setConfigModal(p)} />
          </Panel>
        )}
      </div>
    </div>
  );
}
