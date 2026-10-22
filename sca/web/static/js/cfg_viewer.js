/**
 * Control flow graph viewer: draws the CFG of every function as a layered SVG graph.
 * Blocks are clickable and jump to their first line in the editor.
 */

import { jumpToLine, getActiveTab } from "./editor.js";

const CHAR_W = 7.2;      // approx. width of one monospace character at 12px
const LINE_H = 17;
const HEADER_H = 22;
const PAD_X = 12;
const GAP_X = 36;
const GAP_Y = 48;
const SVG_NS = "http://www.w3.org/2000/svg";

// The function shown is remembered per editor tab.
function selectedFunction() {
  const tab = getActiveTab();
  return tab ? tab.state.cfgFunction || null : null;
}

function selectFunction(name) {
  const tab = getActiveTab();
  if (tab) tab.state.cfgFunction = name;
}

export function renderCfg(cfgResult) {
  const container = document.getElementById("cfg-container");
  if (!container) return;

  if (!cfgResult || !cfgResult.ok || !Array.isArray(cfgResult.functions)) {
    const msg = cfgResult && cfgResult.error ? cfgResult.error.message : "No control flow graph available.";
    container.innerHTML = `
      <div class="empty-state">
        <h3 style="font-weight: 600;">Control Flow Graph</h3>
        <p style="font-size: 13px; max-width: 380px;">${escapeHtml(msg.replace(/\.?$/, "."))} Fix syntax errors and run analysis again.</p>
      </div>`;
    return;
  }

  const funcs = cfgResult.functions;
  if (funcs.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <h3 style="font-weight: 600;">Control Flow Graph</h3>
        <p style="font-size: 13px;">No function definitions found in this source.</p>
      </div>`;
    return;
  }

  if (!funcs.some(f => f.function === selectedFunction())) {
    const main = funcs.find(f => f.function === "main");
    selectFunction((main || funcs[0]).function);
  }

  container.innerHTML = `
    <div class="ast-toolbar cfg-toolbar">
      <div class="cfg-func-list" role="tablist" aria-label="Function to show"></div>
      <span class="ast-schema-label" id="cfg-summary"></span>
    </div>
    <div class="cfg-legend">
      <span><i class="cfg-swatch cfg-swatch-true"></i>true</span>
      <span><i class="cfg-swatch cfg-swatch-false"></i>false</span>
      <span><i class="cfg-swatch cfg-swatch-back"></i>loop back</span>
      <span><i class="cfg-swatch cfg-swatch-unreachable"></i>unreachable</span>
    </div>
    <div class="cfg-canvas" id="cfg-canvas"></div>
  `;

  const list = container.querySelector(".cfg-func-list");
  for (const f of funcs) {
    const btn = document.createElement("button");
    btn.className = "btn-ast-tool cfg-func-btn" + (f.function === selectedFunction() ? " active" : "");
    btn.textContent = `${f.function}()`;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", f.function === selectedFunction() ? "true" : "false");
    btn.addEventListener("click", () => {
      selectFunction(f.function);
      renderCfg(cfgResult);
    });
    list.appendChild(btn);
  }

  const fn = funcs.find(f => f.function === selectedFunction());
  // Cyclomatic complexity E - N + 2 over the part of the graph reachable from ENTRY.
  const reachIds = new Set(fn.blocks.filter(b => b.reachable).map(b => b.id));
  const reachEdges = fn.edges.filter(e => reachIds.has(e.from) && reachIds.has(e.to)).length;
  const complexity = Math.max(1, reachEdges - reachIds.size + 2);
  document.getElementById("cfg-summary").textContent =
    `${fn.blocks.length} blocks · ${fn.edges.length} edges · cyclomatic ${complexity}`;

  document.getElementById("cfg-canvas").appendChild(drawGraph(fn));
}

/** Compute a layered (top-to-bottom) layout and return the SVG element. */
function drawGraph(fn) {
  const nodes = new Map();
  for (const b of fn.blocks) {
    const lines = b.statements.length ? b.statements : [];
    const longest = Math.max(b.label.length + 8, ...lines.map(s => s.length));
    const isTerminal = (b.is_entry || b.is_exit) && lines.length === 0;
    nodes.set(b.id, {
      block: b,
      succ: [],
      pred: [],
      w: Math.min(460, Math.max(isTerminal ? 72 : 96, longest * CHAR_W + PAD_X * 2)),
      h: isTerminal ? 28 : HEADER_H + lines.length * LINE_H + 8,
      isTerminal,
    });
  }
  for (const e of fn.edges) {
    nodes.get(e.from).succ.push(e);
    nodes.get(e.to).pred.push(e);
  }

  // 1. DFS from ENTRY (then from any unreachable roots) to find loop back edges.
  const order = [];
  const state = new Map();   // 1 = on stack, 2 = done
  const visit = (id) => {
    state.set(id, 1);
    for (const e of nodes.get(id).succ) {
      const s = state.get(e.to);
      if (s === 1) e.back = true;
      else if (!s) visit(e.to);
    }
    state.set(id, 2);
    order.push(id);
  };
  const entry = fn.blocks.find(b => b.is_entry);
  if (entry) visit(entry.id);
  for (const b of fn.blocks) if (!state.has(b.id)) visit(b.id);
  order.reverse();   // reverse postorder = topological order of the forward edges

  // 2. Longest-path layering over forward edges; EXIT always on the bottom row.
  // Unreachable blocks go one row below the reachable block whose code precedes them,
  // so dead code after a `return` shows up next to that return.
  const layer = new Map();
  const minLayer = new Map();
  const layerOrder = [
    ...order.filter(id => nodes.get(id).block.reachable),
    ...order.filter(id => !nodes.get(id).block.reachable),
  ];
  const assignLayers = () => {
    layer.clear();
    for (const id of layerOrder) {
      const b = nodes.get(id).block;
      let l = minLayer.get(id) || 0;
      for (const e of nodes.get(id).pred) if (!e.back && layer.has(e.from)) l = Math.max(l, layer.get(e.from) + 1);
      if (!b.reachable && b.line) {
        for (const other of fn.blocks) {
          if (other.reachable && other.line && other.line <= b.line && layer.has(other.id)) {
            l = Math.max(l, layer.get(other.id) + 1);
          }
        }
      }
      layer.set(id, l);
    }
  };
  assignLayers();

  // Code after a loop goes below the whole loop body, so its edges don't cut through it.
  // A loop's body is every node that reaches one of its back edges u -> h without
  // passing the header h; all back edges to the same header (continue, loop end) form one loop.
  const loopTails = new Map();   // header id -> back-edge sources
  for (const e of fn.edges) {
    if (e.back) loopTails.set(e.to, [...(loopTails.get(e.to) || []), e.from]);
  }
  for (let pass = 0; pass < 3 && loopTails.size; pass++) {
    let changed = false;
    for (const [header, tails] of loopTails) {
      const body = new Set([header]);
      const stack = [...tails];
      while (stack.length) {
        const id = stack.pop();
        if (body.has(id)) continue;
        body.add(id);
        for (const e of nodes.get(id).pred) stack.push(e.from);
      }
      const bottom = Math.max(...[...body].map(id => layer.get(id)));
      for (const id of body) {
        for (const e of nodes.get(id).succ) {
          if (!body.has(e.to) && (minLayer.get(e.to) || 0) < bottom + 1) {
            minLayer.set(e.to, bottom + 1);
            changed = true;
          }
        }
      }
    }
    if (!changed) break;
    assignLayers();
  }
  const exit = fn.blocks.find(b => b.is_exit);
  if (exit) {
    let maxOther = 0;
    for (const [id, l] of layer) if (id !== exit.id) maxOther = Math.max(maxOther, l);
    layer.set(exit.id, maxOther + 1);
  }

  const rows = [];
  for (const id of order) {
    const l = layer.get(id);
    (rows[l] = rows[l] || []).push(id);
  }

  // 3. Order each row by the average position of its predecessors (reduces crossings).
  const pos = new Map();
  rows.forEach(row => row.forEach((id, i) => pos.set(id, i)));
  for (let pass = 0; pass < 2; pass++) {
    for (const row of rows) {
      if (!row) continue;
      const key = (id) => {
        const ps = nodes.get(id).pred.filter(e => !e.back).map(e => pos.get(e.from));
        return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : pos.get(id);
      };
      const line = (id) => nodes.get(id).block.line || Infinity;
      // Among siblings, the true branch goes left of the false branch.
      const side = (id) => {
        const kinds = nodes.get(id).pred.map(e => e.kind);
        return kinds.includes("true") ? 0 : kinds.includes("false") ? 2 : 1;
      };
      row.sort((a, b) => (key(a) - key(b)) || (side(a) - side(b)) || (line(a) - line(b)));
      row.forEach((id, i) => pos.set(id, i));
    }
  }

  // Forward edges that skip rows would cut through blocks in between; they get a lane
  // on the left, as back edges get one on the right.
  const longEdges = fn.edges.filter(e => !e.back && layer.get(e.to) - layer.get(e.from) > 1);
  const leftMargin = 24 + longEdges.length * 16;

  // 4. Coordinates: rows stacked vertically, each row centred on a shared axis.
  // Array.from, not map: rows may have holes (empty layers) and map would keep them.
  const rowWidths = Array.from(rows, row => (row || []).reduce((s, id) => s + nodes.get(id).w, 0) + GAP_X * ((row || []).length - 1));
  const contentW = Math.max(...rowWidths, 120);
  let y = 16;
  rows.forEach((row, r) => {
    if (!row) return;
    let x = leftMargin + (contentW - rowWidths[r]) / 2;
    const rowH = Math.max(...row.map(id => nodes.get(id).h));
    for (const id of row) {
      const n = nodes.get(id);
      n.x = x;
      n.y = y + (rowH - n.h) / 2;
      x += n.w + GAP_X;
    }
    y += rowH + GAP_Y;
  });

  // Back edges are routed around the right side, one lane each.
  const backEdges = fn.edges.filter(e => e.back);
  const laneBase = leftMargin + contentW + 20;
  const width = laneBase + backEdges.length * 16 + 16;
  const height = y - GAP_Y + 16;

  const svg = el("svg", {
    class: "cfg-svg",
    viewBox: `0 0 ${width} ${height}`,
    width,
    height,
    role: "img",
    "aria-label": `Control flow graph of ${fn.function}`,
  });
  const defs = el("defs");
  for (const kind of ["normal", "true", "false", "back"]) {
    const marker = el("marker", {
      id: `cfg-arrow-${kind}`, viewBox: "0 0 10 10", refX: 9, refY: 5,
      markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse",
    });
    marker.appendChild(el("path", { d: "M0,0 L10,5 L0,10 z", class: `cfg-arrowhead cfg-edge-${kind}` }));
    defs.appendChild(marker);
  }
  svg.appendChild(defs);

  const edgeLayer = el("g");
  const nodeLayer = el("g");
  svg.appendChild(edgeLayer);
  svg.appendChild(nodeLayer);

  // Forward edges: leave from the bottom (spread across the width), enter at the top.
  for (const n of nodes.values()) {
    const fwd = n.succ.filter(e => !e.back && !longEdges.includes(e));
    fwd.sort((a, b) => nodes.get(a.to).x - nodes.get(b.to).x);
    fwd.forEach((e, i) => {
      const t = nodes.get(e.to);
      const x1 = n.x + n.w * (i + 1) / (fwd.length + 1);
      const y1 = n.y + n.h;
      const x2 = t.x + t.w / 2;
      const y2 = t.y;
      const dy = Math.max(24, (y2 - y1) / 2);
      const kind = e.kind;
      edgeLayer.appendChild(el("path", {
        d: `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2 - 2}`,
        class: `cfg-edge cfg-edge-${kind}`,
        "marker-end": `url(#cfg-arrow-${kind})`,
      }));
      if (kind === "true" || kind === "false") {
        const lbl = el("text", { x: x1 + (x2 >= x1 ? 6 : -6), y: y1 + 14, class: `cfg-edge-label cfg-edge-${kind}`,
          "text-anchor": x2 >= x1 ? "start" : "end" });
        lbl.textContent = kind === "true" ? "T" : "F";
        edgeLayer.appendChild(lbl);
      }
    });
  }

  longEdges.forEach((e, i) => {
    const s = nodes.get(e.from);
    const t = nodes.get(e.to);
    const lane = leftMargin - 16 - i * 16;
    const y1 = s.y + s.h / 2;
    const yTurn = t.y - 18;
    const x2 = t.x + t.w / 2;
    const r = 8;
    edgeLayer.appendChild(el("path", {
      d: `M${s.x},${y1} H${lane + r} Q${lane},${y1} ${lane},${y1 + r} V${yTurn - r} Q${lane},${yTurn} ${lane + r},${yTurn} H${x2 - r} Q${x2},${yTurn} ${x2},${yTurn + r} V${t.y - 2}`,
      class: `cfg-edge cfg-edge-${e.kind}`,
      "marker-end": `url(#cfg-arrow-${e.kind})`,
    }));
    if (e.kind === "true" || e.kind === "false") {
      const lbl = el("text", { x: s.x - 6, y: y1 - 5, class: `cfg-edge-label cfg-edge-${e.kind}`, "text-anchor": "end" });
      lbl.textContent = e.kind === "true" ? "T" : "F";
      edgeLayer.appendChild(lbl);
    }
  });

  backEdges.forEach((e, i) => {
    const s = nodes.get(e.from);
    const t = nodes.get(e.to);
    const lane = laneBase + i * 16;
    // Leave from the bottom-right corner and drop into the gap below the block, so the
    // edge never runs behind other blocks in the same row.
    const x1 = s.x + s.w - 14;
    const yb = s.y + s.h + 12 + (i % 3) * 4;
    const y2 = t.y + t.h / 2;
    const r = 8;
    edgeLayer.appendChild(el("path", {
      d: `M${x1},${s.y + s.h} V${yb - r} Q${x1},${yb} ${x1 + r},${yb} H${lane - r} Q${lane},${yb} ${lane},${yb - r} V${y2 + r} Q${lane},${y2} ${lane - r},${y2} H${t.x + t.w + 2}`,
      class: "cfg-edge cfg-edge-back",
      "marker-end": "url(#cfg-arrow-back)",
    }));
  });

  for (const n of nodes.values()) {
    const b = n.block;
    const cls = ["cfg-node"];
    if (b.is_entry || b.is_exit) cls.push("cfg-node-terminal");
    if (!b.reachable) cls.push("cfg-node-unreachable");
    if (b.line) cls.push("cfg-node-clickable");
    const g = el("g", { class: cls.join(" "), transform: `translate(${n.x},${n.y})` });

    const title = el("title");
    title.textContent = b.line
      ? `${b.label}: lines ${b.line}${b.end_line !== b.line ? "–" + b.end_line : ""}${b.reachable ? "" : " (unreachable)"} — click to jump`
      : b.label;
    g.appendChild(title);
    g.appendChild(el("rect", { width: n.w, height: n.h, rx: n.isTerminal ? n.h / 2 : 6, class: "cfg-node-box" }));

    if (n.isTerminal) {
      const t = el("text", { x: n.w / 2, y: n.h / 2 + 4, "text-anchor": "middle", class: "cfg-node-title" });
      t.textContent = b.label;
      g.appendChild(t);
    } else {
      const head = el("text", { x: PAD_X, y: 15, class: "cfg-node-title" });
      head.textContent = b.label + (b.line ? `  L${b.line}` : "") + (b.reachable ? "" : "  unreachable");
      g.appendChild(head);
      g.appendChild(el("line", { x1: 0, x2: n.w, y1: HEADER_H, y2: HEADER_H, class: "cfg-node-sep" }));
      b.statements.forEach((s, i) => {
        const t = el("text", { x: PAD_X, y: HEADER_H + 13 + i * LINE_H, class: "cfg-node-code" });
        t.textContent = s;
        g.appendChild(t);
      });
    }

    if (b.line) g.addEventListener("click", () => jumpToLine(b.line, 1));
    nodeLayer.appendChild(g);
  }

  return svg;
}

function el(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
