// Sterling Industrial Works -- Fraud Audit chat UI
// Parses agents/summary.py's fixed-format audit report (Section 10) into
// a "ticket" card; anything else (Q&A answers, blocked/needs_upload
// messages, errors) renders as a plain assistant bubble.
//
// Sessions: each browser session_id maps to one in-memory case on the
// backend (app/main.py's SESSIONS/COMPLETED_CASES dicts). This file keeps
// a client-side list of those session_ids in localStorage, with the raw
// transcript, so the sidebar can switch between cases without losing
// history -- purely a front-end convenience; the backend itself has no
// concept of "sessions" beyond the single dict it already keeps.

const API_BASE = "";
const SESSIONS_STORE_KEY = "sifa_sessions_v1";
const ACTIVE_SESSION_KEY = "sifa_active_session_v1";

const chatEl = document.getElementById("chat");
const composerEl = document.getElementById("composer");
const messageInput = document.getElementById("message-input");
const fileInput = document.getElementById("file-input");
const attachChip = document.getElementById("attach-chip");
const sendButton = document.getElementById("send-button");
const sessionCaseEl = document.getElementById("session-case");

const sidebarEl = document.getElementById("sidebar");
const sidebarBackdropEl = document.getElementById("sidebar-backdrop");
const sidebarToggleEl = document.getElementById("sidebar-toggle");
const sessionListEl = document.getElementById("session-list");
const newSessionBtn = document.getElementById("new-session-btn");

const modalOverlayEl = document.getElementById("modal-overlay");
const modalBodyEl = document.getElementById("modal-body");
const modalCloseEl = document.getElementById("modal-close");

const INTRO_HTML = `<p>Attach an invoice PDF to start an audit, or ask a question about a case you've already reviewed.</p>`;

// ---- Session store (localStorage) ----------------------------------------

function loadSessions() {
  try {
    const raw = JSON.parse(localStorage.getItem(SESSIONS_STORE_KEY));
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function saveSessions() {
  localStorage.setItem(SESSIONS_STORE_KEY, JSON.stringify(sessions));
}

function newSessionId() {
  return "web-" + Math.random().toString(36).slice(2, 10);
}

function createSession() {
  const session = {
    id: newSessionId(),
    title: "New audit",
    sub: "",
    updatedAt: Date.now(),
    messages: [],
  };
  sessions.unshift(session);
  saveSessions();
  return session;
}

function getSession(id) {
  return sessions.find((s) => s.id === id) || null;
}

function touchSession(id, patch) {
  const session = getSession(id);
  if (!session) return;
  Object.assign(session, patch, { updatedAt: Date.now() });
  saveSessions();
  renderSidebar();
}

let sessions = loadSessions();
let activeSessionId = localStorage.getItem(ACTIVE_SESSION_KEY);
if (!activeSessionId || !getSession(activeSessionId)) {
  const fallback = sessions[0] || createSession();
  activeSessionId = fallback.id;
}
localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);

// ---- Sidebar ---------------------------------------------------------------

function renderSidebar() {
  sessionListEl.innerHTML = "";
  const ordered = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt);
  if (ordered.length === 0) {
    const empty = document.createElement("li");
    empty.className = "sidebar-empty";
    empty.textContent = "No sessions yet.";
    sessionListEl.appendChild(empty);
    return;
  }
  for (const session of ordered) {
    const li = document.createElement("li");
    li.className = "session-item" + (session.id === activeSessionId ? " active" : "");
    li.innerHTML = `
      <span class="session-item-title">${escapeHtml(session.title)}</span>
      <span class="session-item-sub">${escapeHtml(session.sub || relativeTime(session.updatedAt))}</span>
    `;
    li.addEventListener("click", () => {
      switchSession(session.id);
      closeSidebarOnMobile();
    });
    sessionListEl.appendChild(li);
  }
}

function relativeTime(ts) {
  const mins = Math.round((Date.now() - ts) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function switchSession(id) {
  const session = getSession(id);
  if (!session) return;
  activeSessionId = id;
  localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
  sessionCaseEl.textContent = session.title === "New audit" ? "—" : session.title;
  renderChatFromMessages(session.messages);
  renderSidebar();
}

function renderChatFromMessages(messages) {
  chatEl.innerHTML = "";
  if (!messages || messages.length === 0) {
    const intro = document.createElement("div");
    intro.className = "intro";
    intro.innerHTML = INTRO_HTML;
    chatEl.appendChild(intro);
    return;
  }
  for (const m of messages) {
    if (m.role === "user") appendUserMessage(m.text);
    else if (m.role === "error") appendError(m.text);
    else renderAssistantMessage(m.text);
  }
}

newSessionBtn.addEventListener("click", () => {
  const session = createSession();
  switchSession(session.id);
  closeSidebarOnMobile();
});

sidebarToggleEl.addEventListener("click", () => {
  sidebarEl.classList.toggle("open");
  sidebarBackdropEl.classList.toggle("open");
});

sidebarBackdropEl.addEventListener("click", closeSidebarOnMobile);

function closeSidebarOnMobile() {
  sidebarEl.classList.remove("open");
  sidebarBackdropEl.classList.remove("open");
}

renderSidebar();
renderChatFromMessages(getSession(activeSessionId).messages);

// ---- Composer / chat -------------------------------------------------------

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (file) {
    attachChip.textContent = file.name;
    attachChip.hidden = false;
    if (!messageInput.value.trim()) messageInput.value = "Can you audit this invoice?";
  } else {
    attachChip.hidden = true;
  }
});

composerEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  const file = fileInput.files[0] || null;
  if (!message && !file) return;

  const session = getSession(activeSessionId);
  const userText = message || "(sent an invoice)";
  appendUserMessage(userText);
  session.messages.push({ role: "user", text: userText });

  const pendingEl = appendPending();
  messageInput.value = "";
  fileInput.value = "";
  attachChip.hidden = true;
  sendButton.disabled = true;

  try {
    const form = new FormData();
    form.append("message", message);
    form.append("session_id", activeSessionId);
    if (file) form.append("file", file);

    const res = await fetch(`${API_BASE}/api/v1/chat`, { method: "POST", body: form });
    const data = await res.json();
    pendingEl.remove();

    if (!res.ok) {
      const errText = data.detail || `Request failed (${res.status})`;
      appendError(errText);
      session.messages.push({ role: "error", text: errText });
      touchSession(activeSessionId, {});
      return;
    }

    const replyText = data.message || "";
    renderAssistantMessage(replyText);
    session.messages.push({ role: "assistant", text: replyText });

    const invoiceId = extractInvoiceId(replyText);
    const patch = {};
    if (data.mode && data.mode !== "blocked" && invoiceId) {
      patch.title = invoiceId;
      sessionCaseEl.textContent = invoiceId;
    }
    const ticket = parseAuditReport(replyText);
    if (ticket) patch.sub = `${ticket.vendor} — ${ticket.fraudType}`;
    touchSession(activeSessionId, patch);
  } catch (err) {
    pendingEl.remove();
    const errText = "Could not reach the server: " + err.message;
    appendError(errText);
    session.messages.push({ role: "error", text: errText });
    touchSession(activeSessionId, {});
  } finally {
    sendButton.disabled = false;
  }
});

function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "msg msg-user";
  div.textContent = text;
  chatEl.appendChild(div);
  scrollToBottom();
}

function appendPending() {
  const div = document.createElement("div");
  div.className = "msg msg-assistant pending";
  div.textContent = "Working on it…";
  chatEl.appendChild(div);
  scrollToBottom();
  return div;
}

function appendError(text) {
  const div = document.createElement("div");
  div.className = "msg msg-error";
  div.textContent = text;
  chatEl.appendChild(div);
  scrollToBottom();
}

function renderAssistantMessage(text) {
  const ticket = parseAuditReport(text);
  const div = document.createElement("div");
  if (ticket) {
    div.className = "msg ticket";
    div.tabIndex = 0;
    div.setAttribute("role", "button");
    div.setAttribute("aria-label", "Expand full audit ticket");
    div.title = "Click to view full ticket";
    div.appendChild(buildTicket(ticket));
    div.addEventListener("click", () => openModal(ticket));
    div.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openModal(ticket);
      }
    });
  } else {
    div.className = "msg msg-assistant";
    div.textContent = text;
  }
  chatEl.appendChild(div);
  scrollToBottom();
}

function extractInvoiceId(text) {
  const m = /^INVOICE\s+(\S+)/m.exec(text || "");
  return m ? m[1] : null;
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

// ---- Ticket popout modal ----------------------------------------------------

function openModal(ticket) {
  modalBodyEl.innerHTML = "";
  modalBodyEl.appendChild(buildTicket(ticket));
  modalOverlayEl.classList.add("open");
}

function closeModal() {
  modalOverlayEl.classList.remove("open");
  modalBodyEl.innerHTML = "";
}

modalCloseEl.addEventListener("click", closeModal);
modalOverlayEl.addEventListener("click", (e) => {
  if (e.target === modalOverlayEl) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && modalOverlayEl.classList.contains("open")) closeModal();
});

// ---- Fixed-format audit report parser (mirrors agents/summary.py) --------

function parseAuditReport(text) {
  const header = /^INVOICE\s+(\S+)\s+—\s+(.+?)\s+—\s+\$([\d,]+\.\d+)/m.exec(text);
  const verdictLine = /^VERDICT:\s*(\S+)\s*\|\s*Severity:\s*(\w+)\s*\|\s*Confidence:\s*(.+)$/m.exec(text);
  if (!header || !verdictLine) return null;

  const checksBlock = /Checks completed:\n([\s\S]*?)\n\nEvidence:/.exec(text);
  const evidenceBlock = /Evidence:\n([\s\S]*?)\n\nNarrative:/.exec(text);
  const narrativeBlock = /Narrative:\s*([\s\S]*?)\n\nRecommended action:/.exec(text);
  const actionBlock = /Recommended action:\s*([\s\S]*)$/.exec(text);

  const checks = [];
  if (checksBlock) {
    const lineRe = /^\s*\d+\.\s+(\S+)\s+\.\.\.\s+(\S+)$/gm;
    let m;
    while ((m = lineRe.exec(checksBlock[1])) !== null) {
      checks.push({ name: m[1], result: m[2] });
    }
  }

  // Each bullet starts with "  - "; a citation excerpt can itself span
  // several physical lines (e.g. a multi-line contract clause), so
  // continuation lines must be folded back into the bullet they belong to
  // rather than each becoming a bogus separate entry.
  const evidence = [];
  if (evidenceBlock) {
    let current = null;
    for (const line of evidenceBlock[1].split("\n")) {
      if (/^\s*-\s+/.test(line)) {
        if (current !== null) evidence.push(current);
        current = line.replace(/^\s*-\s*/, "");
      } else if (current !== null && line.trim()) {
        current += " " + line.trim();
      }
    }
    if (current !== null) evidence.push(current);
  }
  const evidenceItems = evidence
    .map(e => e.replace(/\s+/g, " ").trim())
    .filter(e => e && e !== "(none)")
    .map(e => (e.length > 220 ? e.slice(0, 217) + "…" : e));

  return {
    invoiceId: header[1],
    vendor: header[2],
    amount: header[3],
    fraudType: verdictLine[1],
    severity: verdictLine[2],
    confidence: verdictLine[3].trim(),
    checks,
    evidence: evidenceItems,
    narrative: narrativeBlock ? narrativeBlock[1].trim() : "",
    recommendedAction: actionBlock ? actionBlock[1].trim() : "",
  };
}

function buildTicket(t) {
  const wrap = document.createElement("div");
  wrap.className = "ticket-inner";

  const stampInfo = stampFor(t);

  wrap.innerHTML = `
    <div class="ticket-head">
      <div>
        <div class="ticket-invoice">${escapeHtml(t.invoiceId)}</div>
        <div class="ticket-vendor">${escapeHtml(t.vendor)}</div>
      </div>
      <div class="ticket-amount">$${escapeHtml(t.amount)}</div>
    </div>
    <span class="stamp ${stampInfo.cls}">${stampInfo.label}</span>
    <hr class="ticket-divider">
    <div class="ticket-body">
      ${t.checks.length ? `
        <div>
          <div class="ticket-section-label">Checks completed</div>
          <ul class="checklist">${t.checks.map(checkRow).join("")}</ul>
        </div>` : ""}
      ${t.evidence.length ? `
        <div>
          <div class="ticket-section-label">Evidence</div>
          <ul class="evidence-list">${t.evidence.map(e => `<li>${escapeHtml(e)}</li>`).join("")}</ul>
        </div>` : ""}
      ${t.narrative ? `
        <div>
          <div class="ticket-section-label">Narrative</div>
          <p class="narrative">${escapeHtml(t.narrative)}</p>
        </div>` : ""}
    </div>
    <div class="ticket-footer">
      <span class="ticket-footer-label">Recommended action</span>
      <span class="ticket-footer-value ${actionClass(t.recommendedAction)}">${escapeHtml(t.recommendedAction)}</span>
    </div>
  `;
  return wrap;
}

function checkRow(c) {
  const icon = c.result === "CLEAN" ? { glyph: "✓", cls: "clean" }
    : c.result === "ANOMALY" ? { glyph: "✕", cls: "anomaly" }
    : { glyph: "–", cls: "na" };
  return `<li><span class="check-icon ${icon.cls}">${icon.glyph}</span><span class="check-name">${escapeHtml(c.name)}</span><span class="check-result">${escapeHtml(c.result)}</span></li>`;
}

function stampFor(t) {
  if (t.fraudType === "CLEAN") return { cls: "stamp-clean", label: "Clear" };
  const action = t.recommendedAction.toLowerCase();
  if (action.includes("auto-flagged")) return { cls: "stamp-flag", label: "Flagged" };
  if (action.includes("human review")) return { cls: "stamp-review", label: "Review" };
  return { cls: "stamp-flag", label: "Flagged" };
}

function actionClass(action) {
  const a = (action || "").toLowerCase();
  if (a.includes("auto-flagged")) return "action-flagged";
  if (a.includes("human review")) return "action-review";
  return "action-none";
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
