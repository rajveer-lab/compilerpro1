/**
 * Learning tab: the beginner misconceptions behind the current diagnostics
 * (sca/misconceptions.py), and a per-browser profile of how often each one shows up.
 *
 * The profile counts distinct mistakes, keyed by misconception and the text of the
 * offending line, so re-running the same code (or live analysis while typing) does
 * not inflate it. It lives only in this browser's localStorage.
 */

import { jumpToLine } from "./editor.js";

const STORAGE_KEY = "sca_misconception_profile";
const MAX_KEYS_PER_ITEM = 200;

function loadProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const data = raw ? JSON.parse(raw) : null;
    if (data && typeof data.items === "object") return data;
  } catch (e) {}
  return { items: {} };
}

function saveProfile(profile) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(profile));
  } catch (e) {}
}

/** Record this run's misconceptions; returns the updated profile. */
function recordRun(misconceptions, source) {
  const profile = loadProfile();
  const lines = source.split("\n");
  const now = new Date().toISOString();
  for (const m of misconceptions) {
    const item = profile.items[m.id] || { title: m.title, keys: [], last_seen: now };
    item.title = m.title;
    for (const line of m.lines) {
      const key = (lines[line - 1] || "").trim();
      if (key && !item.keys.includes(key)) {
        item.keys.push(key);
        item.last_seen = now;
        if (item.keys.length > MAX_KEYS_PER_ITEM) item.keys.shift();
      }
    }
    profile.items[m.id] = item;
  }
  saveProfile(profile);
  return profile;
}

export function renderLearning(misconceptions, source) {
  const container = document.getElementById("learning-container");
  const badge = document.getElementById("badge-learning");
  if (!container) return;
  if (misconceptions === null) {
    if (badge) badge.textContent = 0;
    container.innerHTML = `
      <div class="empty-state">
        <p style="font-size: 13px;">Misconception diagnosis unavailable due to syntax errors.</p>
      </div>`;
    return;
  }
  if (badge) badge.textContent = misconceptions.length;

  const profile = recordRun(misconceptions, source || "");

  let html = `<h3 class="learning-heading">In this code</h3>`;
  if (misconceptions.length === 0) {
    html += `<p class="learning-empty">No beginner misconceptions detected in this code.</p>`;
  } else {
    html += `<div class="misconception-list">`;
    for (const m of misconceptions) {
      html += `
        <div class="misconception-card">
          <div class="misconception-title">Misconception: "${escapeHtml(m.title)}"</div>
          <p class="misconception-text">${escapeHtml(m.explanation)}</p>
          <p class="misconception-fix"><strong>Fix your mental model:</strong> ${escapeHtml(m.fix)}</p>
          <div class="misconception-lines">Seen on ${m.lines
            .map(l => `<button class="misconception-line" data-line="${l}">line ${l}</button>`).join(" ")}
            <span class="misconception-rules">(${m.rule_ids.map(escapeHtml).join(", ")})</span>
          </div>
        </div>`;
    }
    html += `</div>`;
  }

  const entries = Object.entries(profile.items)
    .map(([id, item]) => ({ id, title: item.title, count: item.keys.length, last: item.last_seen }))
    .filter(e => e.count > 0)
    .sort((a, b) => b.count - a.count);
  const max = Math.max(1, ...entries.map(e => e.count));

  html += `
    <div class="learning-profile-header">
      <h3 class="learning-heading">Your profile</h3>
      <button class="btn-ast-tool" id="btn-reset-profile" ${entries.length ? "" : "disabled"}>Reset</button>
    </div>
    <p class="learning-note">Distinct mistakes seen across your runs. Stored only in this browser.</p>`;
  if (entries.length === 0) {
    html += `<p class="learning-empty">Nothing recorded yet.</p>`;
  } else {
    html += `<div class="profile-list">`;
    for (const e of entries) {
      html += `
        <div class="profile-row" title="Last seen ${escapeHtml(new Date(e.last).toLocaleString())}">
          <span class="profile-title">${escapeHtml(e.title)}</span>
          <span class="profile-bar"><span style="width: ${(100 * e.count / max).toFixed(0)}%"></span></span>
          <span class="profile-count">${e.count}×</span>
        </div>`;
    }
    html += `</div>`;
  }
  container.innerHTML = html;

  container.querySelectorAll(".misconception-line").forEach(btn => {
    btn.addEventListener("click", () => jumpToLine(parseInt(btn.getAttribute("data-line"), 10), 1));
  });
  const reset = document.getElementById("btn-reset-profile");
  if (reset) {
    reset.addEventListener("click", () => {
      if (!confirm("Clear your misconception profile in this browser?")) return;
      try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
      renderLearning(misconceptions, "");
    });
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
