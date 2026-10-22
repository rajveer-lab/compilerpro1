/**
 * File tab strip above the editor: switch, close (x), rename (double-click) and new (+).
 * The tab model itself lives in editor.js.
 */

import {
  getTabs, getActiveTab, switchToTab, newUntitledTab, closeTab, renameTab, onTabsChanged,
} from "./editor.js";

export function initTabStrip() {
  const strip = document.getElementById("file-tabs");
  const addBtn = document.getElementById("btn-new-tab");
  if (!strip) return;

  if (addBtn) addBtn.addEventListener("click", () => newUntitledTab());
  onTabsChanged(() => renderTabStrip(strip));
  renderTabStrip(strip);
}

function renderTabStrip(strip) {
  const active = getActiveTab();
  strip.innerHTML = "";
  for (const tab of getTabs()) {
    const isActive = active && tab.id === active.id;
    const el = document.createElement("div");
    el.className = "file-tab" + (isActive ? " active" : "");
    el.setAttribute("role", "tab");
    el.setAttribute("aria-selected", isActive ? "true" : "false");
    el.tabIndex = 0;
    el.title = `${tab.name} (double-click to rename)`;

    const label = document.createElement("span");
    label.className = "file-tab-name";
    label.textContent = tab.name;
    el.appendChild(label);

    if (getTabs().length > 1) {
      const close = document.createElement("button");
      close.className = "file-tab-close";
      close.setAttribute("aria-label", `Close ${tab.name}`);
      close.textContent = "×";
      close.addEventListener("click", (e) => {
        e.stopPropagation();
        const code = tab.doc.getValue();
        if (code.trim() && !confirm(`Close "${tab.name}"? Its code will be removed from this browser (use Download to keep a copy).`)) {
          return;
        }
        closeTab(tab.id);
      });
      el.appendChild(close);
    }

    el.addEventListener("click", () => switchToTab(tab.id));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        switchToTab(tab.id);
      } else if (e.key === "F2") {
        startRename(el, label, tab);
      }
    });
    el.addEventListener("dblclick", () => startRename(el, label, tab));
    strip.appendChild(el);
  }

  const activeEl = strip.querySelector(".file-tab.active");
  if (activeEl) activeEl.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function startRename(el, label, tab) {
  const input = document.createElement("input");
  input.className = "file-tab-rename";
  input.value = tab.name;
  input.setAttribute("aria-label", "File name");
  label.replaceWith(input);
  input.focus();
  input.select();

  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    if (commit) {
      renameTab(tab.id, input.value);   // re-renders the strip
    } else {
      input.replaceWith(label);
    }
  };
  input.addEventListener("click", (e) => e.stopPropagation());
  input.addEventListener("dblclick", (e) => e.stopPropagation());
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}
