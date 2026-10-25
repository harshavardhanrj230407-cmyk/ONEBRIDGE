const state = { user: null, reports: [], notifications: [], view: "home", filter: "all" };
const $ = (selector, root = document) => root.querySelector(selector);
const content = $("#page-content");
const roleLabels = { citizen: "Community member", resolver: "Authorized resolver", organization_admin: "Organization administrator", platform_admin: "Platform administrator" };
const statusLabels = {
  AWAITING_VERIFICATION: "Awaiting verification",
  ADDITIONAL_EVIDENCE_REQUIRED: "Evidence requested",
  UNDER_HUMAN_REVIEW: "Under human review",
  SUPPORTED_BY_EVIDENCE: "Supported by evidence",
  ASSIGNED: "Assigned",
  IN_PROGRESS: "In progress",
  RESOLUTION_SUBMITTED: "Resolution submitted",
  RESOLVED: "Resolved",
  REJECTED_AFTER_REVIEW: "Rejected after review",
  DISPUTED: "Disputed",
  REOPENED: "Reopened",
};
const categories = ["Roads & sidewalks", "Water & drainage", "Waste & sanitation", "Street lighting", "Accessibility", "Public transport", "Environment & safety", "Other"];
const categoryIcons = { "Roads & sidewalks": "⌁", "Water & drainage": "≈", "Waste & sanitation": "♲", "Street lighting": "☼", "Accessibility": "♿", "Public transport": "↗", "Environment & safety": "✳", Other: "◇" };

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...options,
    headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  const result = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status}).`);
  return result;
}

function toast(message, isError = false) {
  const element = document.createElement("div");
  element.className = `toast${isError ? " error" : ""}`;
  element.textContent = message;
  $("#toast-region").append(element);
  window.setTimeout(() => element.remove(), 3800);
}

function greeting() {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

function initials(name) {
  return String(name || "?").trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function relativeTime(value) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60000));
  if (!Number.isFinite(minutes)) return "just now";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}

function formatDate(value) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function statusTone(status) {
  if (["RESOLVED", "SUPPORTED_BY_EVIDENCE"].includes(status)) return "green";
  if (["ASSIGNED", "IN_PROGRESS", "RESOLUTION_SUBMITTED", "REOPENED"].includes(status)) return "blue";
  if (["AWAITING_VERIFICATION", "ADDITIONAL_EVIDENCE_REQUIRED", "UNDER_HUMAN_REVIEW"].includes(status)) return "amber";
  if (["REJECTED_AFTER_REVIEW", "DISPUTED"].includes(status)) return "red";
  return "";
}

function statusBadge(status) {
  return `<span class="status-badge ${statusTone(status)}">${escapeHtml(statusLabels[status] || status)}</span>`;
}

function reportRow(report) {
  const color = report.category === "Water & drainage" ? "teal" : report.category === "Waste & sanitation" ? "orange" : report.category === "Accessibility" ? "purple" : "";
  return `<article class="report-row" role="button" tabindex="0" data-report="${report.id}" aria-label="Open report ${escapeHtml(report.title)}">
    <span class="category-icon ${color}" aria-hidden="true">${escapeHtml(categoryIcons[report.category] || "◇")}</span>
    <span class="report-info"><b>${escapeHtml(report.title)}</b><span>${escapeHtml(report.category)} · ${escapeHtml(report.tracking_id)}</span></span>
    <span class="report-trailing">${statusBadge(report.status)}<span class="time-label">${relativeTime(report.created_at)}</span></span>
  </article>`;
}

function emptyState(title, description, buttonLabel = "", view = "") {
  return `<div class="empty-state"><span class="empty-symbol" aria-hidden="true">◇</span><b>${escapeHtml(title)}</b><p>${escapeHtml(description)}</p>${buttonLabel ? `<button class="button button-secondary button-small" data-go="${escapeHtml(view)}">${escapeHtml(buttonLabel)}</button>` : ""}</div>`;
}

function pageHeading(eyebrow, title, description, action = "") {
  return `<div class="page-heading"><div><div class="eyebrow"><span class="eyebrow-mark"></span>${escapeHtml(eyebrow)}</div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div>${action ? `<div class="heading-actions">${action}</div>` : ""}</div>`;
}

function trustCard() {
  return `<section class="panel trust-card"><div class="trust-top"><span class="trust-icon" aria-hidden="true">✳</span><h2>Introducing TrustShield</h2><span class="trust-mode">TRANSPARENT REVIEW</span></div><p>Every report gets clear, explainable completeness checks. Review signals support human decision-making—they never accuse someone of fraud or claim an issue is verified automatically.</p><div class="trust-footer"><span>✓</span><span>Explainable signals</span><span>·</span><span>People make the decisions</span></div></section>`;
}

function metric(title, value, symbol, subtext, trend = "") {
  return `<article class="metric-card"><div class="metric-head"><span>${escapeHtml(title)}</span><span class="metric-symbol" aria-hidden="true">${escapeHtml(symbol)}</span></div><div class="metric-value">${escapeHtml(value)}${trend ? `<span class="metric-trend">${escapeHtml(trend)}</span>` : ""}</div><div class="metric-subtext">${escapeHtml(subtext)}</div></article>`;
}

function buildActivity(reports) {
  const events = reports.flatMap((report) => (report.timeline || []).map((event) => ({ ...event, title: report.title, tracking: report.tracking_id })));
  events.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  if (!events.length) {
    return state.user.role === "citizen"
      ? emptyState("Your activity will appear here", "Report a local issue to get a timeline of every update.", "Create your first report", "new-report")
      : emptyState("No activity to show yet", "Updates appear when a report is reviewed, assigned, or changed.");
  }
  return events.slice(0, 5).map((event) => `<div class="activity-item"><span class="activity-marker" aria-hidden="true">✓</span><span class="activity-copy"><b>${escapeHtml(statusLabels[event.event_type] || event.event_type.replaceAll("_", " "))}</b> · ${escapeHtml(event.note)}<time>${relativeTime(event.created_at)} · ${escapeHtml(event.tracking)}</time></span></div>`).join("");
}

async function refreshData() {
  if (!state.user) return;
  const [reports, notifications] = await Promise.all([api("/reports"), api("/notifications")]);
  state.reports = reports.reports;
  state.notifications = notifications.notifications;
  $("#report-count").textContent = state.reports.length;
  $("#notification-dot").hidden = !state.notifications.some((item) => !item.read_at);
}

async function render() {
  if (!state.user) return state.view === "login" ? renderLogin(state.authMode || "login") : renderLanding();
  await refreshData();
  const names = { overview: "Overview", reports: "My reports", "new-report": "Report a problem", map: "Community map", notifications: "Notifications", admin: "Operations" };
  $("#breadcrumb-current").textContent = names[state.view] || "Overview";
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.view === state.view));
  if (state.view === "overview") return renderOverview();
  if (state.view === "reports") return renderReports();
  if (state.view === "new-report") return renderReportForm();
  if (state.view === "map") return renderMap();
  if (state.view === "notifications") return renderNotifications();
  if (state.view === "admin") return renderAdmin();
  return renderOverview();
}

function setUser(user) {
  state.user = user;
  const loggedIn = Boolean(user);
  $("#profile-row").hidden = !loggedIn;
  $("#navigation").hidden = !loggedIn;
  $("#profile-name").textContent = user?.name || "Guest";
  $("#profile-role").textContent = roleLabels[user?.role] || "Community member";
  $("#profile-avatar").textContent = initials(user?.name);
  $("#top-avatar").textContent = initials(user?.name);
  document.querySelectorAll(".admin-link").forEach((item) => { item.hidden = !["organization_admin", "platform_admin"].includes(user?.role); });
  if (!loggedIn) state.view = "home";
}

function renderLanding() {
  $("#breadcrumb-current").textContent = "Community platform";
  content.innerHTML = `<section class="landing-hero">
    <div class="hero-copy"><div class="eyebrow"><span class="eyebrow-mark"></span>COMMUNITY, CONNECTED</div>
      <h1>Every problem deserves <span>a solution.</span></h1>
      <p>Report local issues, see what happens next, and help your community close the loop—from a thoughtful first report to a resolution you can confirm.</p>
      <div class="hero-actions"><button class="button button-primary" data-auth-start="register">Get started <span aria-hidden="true">→</span></button><button class="button button-secondary" data-auth-start="login">Report a problem</button></div>
      <div class="hero-assurance"><span class="assurance-icon">✓</span><span>Human-led reviews</span><span>·</span><span>Updates you can follow</span></div>
    </div>
    <div class="product-preview" aria-label="Illustration of a report tracking dashboard"><div class="preview-window"><div class="preview-top"><span class="preview-dot"></span><span class="preview-dot"></span><span class="preview-dot"></span><span class="preview-top-label">COMMUNITY OVERVIEW</span></div>
      <div class="preview-content"><div class="preview-kicker">EXAMPLE REPORT · FICTIONAL DEMO</div><div class="preview-title">Progress, made visible.</div>
      <div class="preview-stat-row"><div class="preview-stat"><strong>Report journey</strong><span>From report to resolution</span></div><div class="preview-stat"><strong>Human review</strong><span>Clear, accountable decisions</span></div></div>
      <div class="preview-report"><span class="preview-category">≈</span><span><b>Water leak near library</b><small>North campus · sample issue</small></span><span class="preview-status">AWAITING REVIEW</span></div>
      <div class="preview-report"><span class="preview-category blue">☼</span><span><b>Streetlight out by the west gate</b><small>Fictional sample report</small></span><span class="preview-status resolved">IN PROGRESS</span></div>
      <div class="preview-steps"><span class="step-done">Reported</span><i></i><span class="step-done">Reviewed</span><i></i><span>Resolved</span></div></div></div>
      <div class="preview-note"><span>✳</span><b>TrustShield</b><span>Clear signals. Human decisions.</span></div>
    </div>
  </section>
  <section class="landing-section" id="how-it-works"><div class="section-heading"><div class="eyebrow">FROM REPORT TO REAL-WORLD CHANGE</div><h2>A clearer path to resolution.</h2><p>Useful context, thoughtful review, and visible progress—so no one is left wondering what happened.</p></div>
    <div class="steps-grid"><article class="step-card"><span class="step-number">01</span><h3>Tell us what’s happening</h3><p>Share a clear description and a nearby landmark. Your precise location stays private unless you choose to share it.</p></article><article class="step-card"><span class="step-number">02</span><h3>People review the details</h3><p>Transparent completeness signals support authorized reviewers. Automated checks never decide whether someone is telling the truth.</p></article><article class="step-card"><span class="step-number">03</span><h3>Follow the progress</h3><p>Track assignment and work updates, then confirm whether the proposed resolution actually helped.</p></article></div>
  </section>
  <section class="landing-bottom"><div><span class="trust-icon" aria-hidden="true">✳</span><span><b>Technology can support trust—not replace it.</b><small>TrustShield explains what’s present. A person decides what happens next.</small></span></div><button class="button button-secondary" data-auth-start="register">Join the community →</button></section>`;
}

function renderLogin(mode = "login") {
  state.authMode = mode;
  state.view = "login";
  $("#breadcrumb-current").textContent = "Welcome";
  content.innerHTML = `<section class="login-wrap"><div class="login-card">
    <div class="eyebrow"><span class="eyebrow-mark"></span>ONEBRIDGE COMMUNITY</div>
    <h1>${mode === "login" ? "Welcome back." : "Create your account."}</h1>
    <p>${mode === "login" ? "Sign in to see your reports and help your community move forward." : "Join your community. New registrations are always citizen accounts."}</p>
    <div class="login-tabs" role="tablist"><button class="login-tab ${mode === "login" ? "active" : ""}" data-auth-mode="login">Sign in</button><button class="login-tab ${mode === "register" ? "active" : ""}" data-auth-mode="register">Create account</button></div>
    <form class="login-form" id="auth-form">${mode === "register" ? `<label><span class="field-label">Your name</span><input class="field" name="name" autocomplete="name" required minlength="2" maxlength="80" placeholder="Your name"></label>` : ""}
      <label><span class="field-label">Email address</span><input class="field" name="email" type="email" autocomplete="email" required placeholder="you@example.com"></label>
      <label><span class="field-label">Password</span><input class="field" name="password" type="password" autocomplete="${mode === "login" ? "current-password" : "new-password"}" required minlength="${mode === "login" ? 1 : 10}" maxlength="128" placeholder="${mode === "login" ? "Your password" : "At least 10 characters"}"></label>
      <p class="form-error" id="auth-error" hidden></p><button class="button button-primary" type="submit">${mode === "login" ? "Sign in to ONEBRIDGE →" : "Create citizen account →"}</button>
    </form>
    <div class="demo-logins"><b>Try a fictional demo account</b><p>Demo-only credentials. Never use these outside your local demo.</p>
      <div class="demo-role-buttons"><button class="demo-role" data-demo="citizen">Citizen</button><button class="demo-role" data-demo="resolver">Resolver</button><button class="demo-role" data-demo="admin">Platform admin</button></div></div>
  </div></section>`;
}

function renderOverview() {
  const reports = state.reports;
  const stats = {
    total: reports.length,
    pending: reports.filter((r) => ["AWAITING_VERIFICATION", "UNDER_HUMAN_REVIEW", "ADDITIONAL_EVIDENCE_REQUIRED"].includes(r.status)).length,
    active: reports.filter((r) => ["ASSIGNED", "IN_PROGRESS", "REOPENED"].includes(r.status)).length,
    resolved: reports.filter((r) => r.status === "RESOLVED").length,
  };
  const latest = reports.slice(0, 4);
  const activity = buildActivity(reports);
  const action = state.user.role === "citizen"
    ? `<button class="button button-primary" data-go="new-report"><span aria-hidden="true">＋</span> Report a problem</button>`
    : `<button class="button button-secondary" data-go="${["organization_admin", "platform_admin"].includes(state.user.role) ? "admin" : "reports"}">${state.user.role === "resolver" ? "View assigned reports" : "Open operations"} →</button>`;
  content.innerHTML = `${pageHeading(`${greeting()}, ${state.user.name.split(" ")[0]}`, "A better community starts here.", "A clear view of local issues, shared progress, and real solutions.", action)}
    <section class="metrics-grid">${metric("Total reports", stats.total, "▤", state.user.role === "citizen" ? "Your community contributions" : "Reports in your workspace")}${metric("Awaiting review", stats.pending, "◷", "Needs a human review")}${metric("Being addressed", stats.active, "↗", "Assigned to an authorized resolver")}${metric("Resolved", stats.resolved, "✓", "Confirmed by the reporter", stats.resolved ? "Making progress" : "")}</section>
    ${stats.pending ? `<div class="action-strip"><div><b>${stats.pending} ${stats.pending === 1 ? "report is" : "reports are"} in the review queue</b><span>Clear review notes help residents understand what happens next.</span></div><button class="button button-secondary button-small" data-go="${["organization_admin", "platform_admin"].includes(state.user.role) ? "admin" : "reports"}">${["organization_admin", "platform_admin"].includes(state.user.role) ? "Open operations" : "View reports"} →</button></div>` : ""}
    <div class="content-grid"><section class="panel"><header class="panel-header"><div><h2>Recent reports</h2><p>Your latest community updates</p></div><button class="panel-action" data-go="reports">View all reports →</button></header><div class="report-list">${latest.length ? latest.map(reportRow).join("") : state.user.role === "citizen" ? emptyState("A good place to start", "Report a community issue and follow each step all the way through resolution.", "Create your first report", "new-report") : emptyState("No reports in this workspace", "Community reports will appear here when they are submitted.")}</div></section>
    <section class="panel"><header class="panel-header"><div><h2>Recent activity</h2><p>Updates across your reports</p></div></header><div class="activity-list">${activity}</div></section></div>${trustCard()}`;
}

function renderReports() {
  const options = ["all", ...Object.keys(statusLabels)];
  const filtered = state.reports.filter((report) => state.filter === "all" || report.status === state.filter);
  const action = `<button class="button button-primary" data-go="new-report">＋ New report</button>`;
  content.innerHTML = `${pageHeading("YOUR COMMUNITY", "Report history", "Follow a report from the first review to the final confirmation.", action)}
    <div class="filters"><label class="sr-only" for="report-status-filter">Filter reports by status</label><select id="report-status-filter" aria-label="Filter by status">${options.map((status) => `<option value="${escapeHtml(status)}" ${state.filter === status ? "selected" : ""}>${status === "all" ? "All statuses" : escapeHtml(statusLabels[status])}</option>`).join("")}</select><input class="field" id="report-search" placeholder="Search title, tracking ID, or location…" aria-label="Search reports"></div>
    <section class="panel reports-panel"><header class="panel-header"><div><h2>${filtered.length} ${filtered.length === 1 ? "report" : "reports"}</h2><p>Precise coordinates stay private unless you choose to share them.</p></div></header><div class="report-list" id="filtered-reports">${filtered.length ? filtered.map(reportRow).join("") : emptyState("No reports in this view", "Try a different status or create a new report.", "Report a problem", "new-report")}</div></section>`;
}

function renderReportForm() {
  if (state.user.role !== "citizen") {
    toast("Only citizen accounts can submit a report.");
    state.view = ["organization_admin", "platform_admin"].includes(state.user.role) ? "admin" : "reports";
    return state.view === "admin" ? renderAdmin() : renderReports();
  }
  content.innerHTML = `${pageHeading("YOUR VOICE MATTERS", "Report a community problem.", "Share what is happening. We’ll track each step and keep you informed.")}
    <section class="panel form-card"><form id="report-form"><h2 class="form-section-title">Tell us about the issue</h2>
    <div class="form-grid"><label class="form-field full"><span class="field-label">A clear, specific title</span><input class="field" name="title" required minlength="5" maxlength="120" placeholder="e.g. Streetlight out by the pedestrian crossing"><span class="field-hint">Specific locations make it easier to route an issue to the right team.</span></label>
    <label class="form-field"><span class="field-label">Category</span><select class="field" name="category" required><option value="">Choose a category</option>${categories.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("")}</select></label>
    <label class="form-field"><span class="field-label">Nearby location</span><input class="field" name="location" required minlength="3" maxlength="200" placeholder="e.g. Main entrance, near the east gate"><span class="field-hint">A landmark or neighborhood is enough. Don’t include a home address.</span></label>
    <label class="form-field full"><span class="field-label">Describe what you noticed</span><textarea name="description" required minlength="20" maxlength="3000" placeholder="What is happening? When did you notice it? Who might be affected?"></textarea><span class="field-hint">At least 20 characters. Avoid including private information about other people.</span></label>
    <label class="form-field full"><span class="field-label">Optional supporting evidence note</span><input class="field" name="evidence_note" maxlength="500" placeholder="e.g. Photo taken this morning; water is still running"><span class="field-hint">Image upload is not enabled in this local demo; no evidence is uploaded or stored.</span></label>
    <div class="form-field full"><hr class="form-divider"><label class="check-row"><input type="checkbox" name="coordinates_shared" id="coordinate-opt-in"><span>Share my precise GPS coordinates with authorized people handling this report. Off by default; coordinates are never shown on a public map.</span></label>
      <div class="location-tools"><input type="hidden" name="latitude"><input type="hidden" name="longitude"><button type="button" class="button button-secondary button-small" id="get-location" disabled>＋ Add my current location</button><span id="location-feedback" class="field-hint">Your browser will ask permission only if you choose to add your location.</span></div>
      <span class="field-hint">GPS is optional. The report form still works without it.</span></div></div>
    <div class="form-actions"><span class="field-hint">No external authority is contacted when you submit.</span><div><button type="button" class="button button-secondary" data-go="overview">Cancel</button> <button type="submit" class="button button-primary">Submit report →</button></div></div><p class="form-error" id="report-error" hidden></p></form></section>`;
}

function renderMap() {
  const reports = state.reports;
  content.innerHTML = `${pageHeading("ISSUES NEAR YOU", "Community map", "Location descriptions for reports in your workspace.")}
    <div class="action-strip"><div><b>Map integration is not implemented</b><span>Reports are not geocoded or sent to a map provider. This list shows neighborhood descriptions only.</span></div><span class="status-badge amber">LIST VIEW</span></div>
    <section class="panel"><header class="panel-header"><div><h2>Community issue list</h2><p>Location descriptions only. Exact coordinates are not displayed here.</p></div><span class="status-badge">${reports.length} reports</span></header>
    <div class="map-fallback">${reports.length ? reports.map((report) => `<article class="map-card" tabindex="0" role="button" data-report="${report.id}"><span class="map-pin" aria-hidden="true">${escapeHtml(categoryIcons[report.category] || "◇")}</span><span><b>${escapeHtml(report.title)}</b><span>${escapeHtml(report.location)} · ${escapeHtml(statusLabels[report.status])}</span></span></article>`).join("") : emptyState("No community reports yet", "Reports will appear here once they are submitted.")}</div></section>`;
}

function renderNotifications() {
  const items = state.notifications;
  content.innerHTML = `${pageHeading("STAY IN THE LOOP", "Notifications", "Updates when a report is reviewed, assigned, or resolved.")}
    <section class="panel"><header class="panel-header"><div><h2>Recent updates</h2><p>${items.filter((item) => !item.read_at).length} unread</p></div></header><div class="notification-list">${items.length ? items.map((item) => `<article class="notification-item ${item.read_at ? "" : "unread"}" data-notification="${item.id}"><span class="notification-symbol" aria-hidden="true">↗</span><div><p>${escapeHtml(item.message)}</p><time>${relativeTime(item.created_at)}</time></div>${item.read_at ? "" : `<span class="notification-unread" aria-label="Unread"></span>`}</article>`).join("") : emptyState("You’re all caught up", "Report updates and review decisions will appear here.")}</div></section>`;
}

async function renderAdmin() {
  if (!["organization_admin", "platform_admin"].includes(state.user.role)) {
    state.view = "overview";
    return renderOverview();
  }
  const summary = await api("/admin/summary");
  const resolvers = await api("/reports");
  const statuses = summary.statuses || {};
  const rows = resolvers.reports;
  const counts = ["AWAITING_VERIFICATION", "UNDER_HUMAN_REVIEW", "SUPPORTED_BY_EVIDENCE", "ASSIGNED", "IN_PROGRESS", "RESOLUTION_SUBMITTED", "RESOLVED"];
  content.innerHTML = `${pageHeading("REVIEW & COORDINATION", "Operations workspace.", "Review reports and coordinate with resolvers. External agencies are not connected.", `<button class="button button-secondary" id="refresh-admin">Refresh data ↻</button>`)}
    <div class="action-strip"><div><b>External referral is not connected</b><span>Assignments notify the resolver account in this demo. No government or external service received these reports.</span></div><span class="status-badge amber">MANUAL WORKFLOW</span></div>
    <section class="metrics-grid">${metric("Reports in workspace", summary.total, "▤", "Based on stored demo records")}${metric("Awaiting verification", statuses.AWAITING_VERIFICATION || 0, "◷", "Requires an authorized human review")}${metric("In progress", statuses.IN_PROGRESS || 0, "↗", "Assigned resolver updates")}${metric("Resolved", statuses.RESOLVED || 0, "✓", "Reporter-confirmed outcomes", `${summary.resolution_rate}% of reports`)}</section>
    <div class="content-grid"><section class="panel"><header class="panel-header"><div><h2>Review queue & report tracking</h2><p>Open a report to review evidence signals and take an authorized action.</p></div><span class="status-badge">${rows.length} records</span></header><div class="report-list">${rows.length ? rows.map(reportRow).join("") : emptyState("No reports to review", "Community reports will appear in this queue.")}</div></section>
    <section class="panel"><header class="panel-header"><div><h2>Reports by category</h2><p>Counts reflect this workspace’s stored reports.</p></div></header><div class="admin-category-list">${summary.categories.length ? summary.categories.map((entry) => { const max = Math.max(...summary.categories.map((value) => value.count), 1); const width = Math.max(10, Math.round(entry.count / max * 10) * 10); return `<div class="admin-category"><span>${escapeHtml(entry.category)}</span><div class="bar-track"><div class="bar-fill fill-${width}"></div></div><b>${entry.count}</b></div>`; }).join("") : emptyState("No category data", "Submit a report to see category totals.")}</div></section></div>
    <section class="panel admin-workflow-panel"><header class="panel-header"><div><h2>Workflow overview</h2><p>Current lifecycle counts, including review and resolution statuses.</p></div></header><div class="admin-stats workflow-stats">${counts.map((status) => `<div>${statusBadge(status)}<div class="metric-value admin-metric-value">${statuses[status] || 0}</div></div>`).join("")}</div></section>`;
  $("#refresh-admin")?.addEventListener("click", () => render().catch(showError));
}

function showError(error) {
  toast(error.message || "Something went wrong. Please try again.", true);
}

async function openReport(id) {
  try {
    const { report } = await api(`/reports/${encodeURIComponent(id)}`);
    const timeline = report.timeline || [];
    const actions = [];
    if (["organization_admin", "platform_admin"].includes(state.user.role)) {
      if (["AWAITING_VERIFICATION", "UNDER_HUMAN_REVIEW", "ADDITIONAL_EVIDENCE_REQUIRED"].includes(report.status)) {
        actions.push(`<button class="button button-primary button-small" data-action="review" data-status="SUPPORTED_BY_EVIDENCE">Mark supported by evidence</button>`);
        actions.push(`<button class="button button-secondary button-small" data-action="review" data-status="UNDER_HUMAN_REVIEW">Escalate to human review</button>`);
        actions.push(`<button class="button button-secondary button-small" data-action="review" data-status="ADDITIONAL_EVIDENCE_REQUIRED">Request more evidence</button>`);
      }
      if (["SUPPORTED_BY_EVIDENCE", "ASSIGNED", "IN_PROGRESS", "REOPENED"].includes(report.status)) {
        actions.push(`<button class="button button-primary button-small" data-action="assign">Assign to demo resolver</button>`);
      }
      if (report.status === "RESOLUTION_SUBMITTED") actions.push(`<span class="field-hint">Waiting for the reporter to confirm or dispute.</span>`);
    }
    if (state.user.role === "resolver" && report.assigned_to === state.user.id && ["ASSIGNED", "IN_PROGRESS", "REOPENED"].includes(report.status)) {
      actions.push(`<button class="button button-secondary button-small" data-action="progress">Post progress update</button><button class="button button-primary button-small" data-action="resolve">Submit resolution</button>`);
    }
    if (state.user.role === "citizen" && report.user_id === state.user.id && report.status === "RESOLUTION_SUBMITTED") {
      actions.push(`<button class="button button-primary button-small" data-action="confirm">Confirm resolution</button><button class="button button-danger button-small" data-action="dispute">Dispute resolution</button>`);
    }
    $("#detail-content").innerHTML = `<div class="detail-content"><div class="detail-top"><div><div class="eyebrow">${escapeHtml(report.tracking_id)} · ${escapeHtml(formatDate(report.created_at))}</div><h2 id="detail-title">${escapeHtml(report.title)}</h2>${statusBadge(report.status)}</div><button class="icon-button dialog-close" id="close-dialog" aria-label="Close report details">×</button></div>
      <div class="detail-body"><section class="detail-section"><h3>Report details</h3><p><b>${escapeHtml(report.category)}</b><br>${escapeHtml(report.location)}<br><br>${escapeHtml(report.description)}</p></section>
      <section class="detail-section"><h3>TrustShield signals · ${escapeHtml(report.trustshield.mode)}</h3><div class="trust-signals">${report.trustshield.signals.map((signal) => `<span class="trust-signal ${signal.supported ? "ok" : "pending"}">${escapeHtml(signal.label)} · ${signal.supported ? "provided" : "not provided"}</span>`).join("")}</div><p class="field-hint detail-inline-note">Completeness signals are not proof of authenticity. Human review is required; no confidence score is generated.</p></section>
      ${report.resolution_note ? `<section class="detail-section"><h3>Resolution note</h3><p>${escapeHtml(report.resolution_note)}</p></section>` : ""}
      <section class="detail-section"><h3>Assignment</h3><p>${escapeHtml(report.resolver_name || "Not assigned")}<br><span class="field-hint">External authority referral is not enabled.</span></p></section>
      <section class="detail-section detail-timeline"><h3>Report timeline</h3><ol class="timeline">${timeline.length ? timeline.map((event) => `<li><b>${escapeHtml(statusLabels[event.event_type] || event.event_type.replaceAll("_", " "))}</b> · ${escapeHtml(event.note)}<br>${escapeHtml(event.actor_name || "ONEBRIDGE workflow")} · ${relativeTime(event.created_at)}</li>`).join("") : "<li>Report submitted.</li>"}</ol></section></div>
      ${actions.length ? `<div class="dialog-actions">${actions.join("")}</div>` : ""}</div>`;
    const dialog = $("#detail-dialog");
    dialog.showModal();
    $("#close-dialog").addEventListener("click", () => dialog.close());
    $("#detail-content").onclick = (event) => handleReportAction(event, report);
  } catch (error) {
    showError(error);
  }
}

async function handleReportAction(event, report) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  try {
    let payload = {};
    let path;
    if (action === "review") {
      const note = window.prompt("Add a clear note explaining this human review decision:");
      if (!note?.trim()) return;
      payload = { status: button.dataset.status, note };
      path = `/reports/${report.id}/review`;
    } else if (action === "assign") {
      payload = { resolver_id: await findDemoResolverId() };
      path = `/reports/${report.id}/assign`;
    } else if (action === "progress") {
      const note = window.prompt("Share a short progress update with the reporter:");
      if (!note?.trim()) return;
      payload = { note };
      path = `/reports/${report.id}/progress`;
    } else if (action === "resolve") {
      const note = window.prompt("Describe the work completed. This will be sent to the reporter for confirmation:");
      if (!note?.trim()) return;
      payload = { note };
      path = `/reports/${report.id}/resolve`;
    } else if (action === "dispute") {
      const note = window.prompt("Tell the resolver what still needs attention:");
      if (!note?.trim()) return;
      payload = { note };
      path = `/reports/${report.id}/dispute`;
    } else {
      path = `/reports/${report.id}/confirm`;
    }
    await api(path, { method: "POST", body: JSON.stringify(payload) });
    $("#detail-dialog").close();
    toast(action === "confirm" ? "Resolution confirmed. Thank you for closing the loop." : "Report updated and relevant people notified.");
    await render();
  } catch (error) {
    showError(error);
  }
}

async function findDemoResolverId() {
  const response = await fetch("/api/demo/resolver", { credentials: "same-origin" });
  if (!response.ok) throw new Error("No demo resolver account is available.");
  const result = await response.json();
  return result.id;
}

document.addEventListener("click", async (event) => {
  const navigation = event.target.closest("[data-view]");
  if (navigation) {
    if (!state.user) return renderLogin();
    if (navigation.dataset.view === "admin" && !["organization_admin", "platform_admin"].includes(state.user.role)) return;
    state.view = navigation.dataset.view;
    $("#sidebar").classList.remove("open");
    try { await render(); } catch (error) { showError(error); }
    return;
  }
  const go = event.target.closest("[data-go]");
  if (go) {
    state.view = go.dataset.go || "overview";
    try { await render(); } catch (error) { showError(error); }
    return;
  }
  const authMode = event.target.closest("[data-auth-mode]");
  if (authMode) {
    renderLogin(authMode.dataset.authMode);
    return;
  }
  const authStart = event.target.closest("[data-auth-start]");
  if (authStart) {
    renderLogin(authStart.dataset.authStart);
    return;
  }
  const demo = event.target.closest("[data-demo]");
  if (demo) {
    const credentials = {
      citizen: ["citizen@onebridge.local", "CitizenDemo!2026"],
      resolver: ["resolver@onebridge.local", "ResolverDemo!2026"],
      admin: ["admin@onebridge.local", "AdminDemo!2026"],
    }[demo.dataset.demo];
    if ($(".login-tab.active")?.dataset.authMode !== "login") renderLogin("login");
    const form = $("#auth-form");
    form.elements.email.value = credentials[0];
    form.elements.password.value = credentials[1];
    form.requestSubmit();
    return;
  }
  const report = event.target.closest("[data-report]");
  if (report) {
    await openReport(report.dataset.report);
    return;
  }
  const notification = event.target.closest("[data-notification]");
  if (notification && notification.classList.contains("unread")) {
    try {
      await api(`/notifications/${notification.dataset.notification}`, { method: "PATCH", body: JSON.stringify({}) });
      notification.classList.remove("unread");
      notification.querySelector(".notification-unread")?.remove();
      $("#notification-dot").hidden = !state.notifications.some((item) => !item.read_at && item.id !== Number(notification.dataset.notification));
    } catch (error) { showError(error); }
    return;
  }
  if (event.target.closest("#mobile-menu")) $("#sidebar").classList.toggle("open");
  if (event.target.closest("#get-location")) {
    const feedback = $("#location-feedback");
    if (!navigator.geolocation) {
      feedback.textContent = "Location is not available in this browser. You can still submit without it.";
      return;
    }
    feedback.textContent = "Waiting for your browser’s location permission…";
    navigator.geolocation.getCurrentPosition((position) => {
      const form = $("#report-form");
      form.elements.latitude.value = position.coords.latitude.toFixed(6);
      form.elements.longitude.value = position.coords.longitude.toFixed(6);
      feedback.textContent = "Location added. It will only be visible to authorized people handling this report.";
    }, (error) => {
      const messages = {
        1: "Location permission was denied. You can submit without coordinates.",
        2: "Your location could not be determined. You can submit without coordinates.",
        3: "Location request timed out. You can submit without coordinates.",
      };
      feedback.textContent = messages[error.code] || "Location is unavailable. You can submit without coordinates.";
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 120000 });
  }
  if (event.target.closest("#top-avatar")) {
    if (state.user) toast(`${state.user.name} · ${roleLabels[state.user.role]}`);
  }
});

document.addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-report]")) {
    event.preventDefault();
    openReport(event.target.dataset.report);
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "report-status-filter") {
    state.filter = event.target.value;
    renderReports();
  }
  if (event.target.id === "coordinate-opt-in") {
    const enabled = event.target.checked;
    $("#get-location").disabled = !enabled;
    if (!enabled) {
      $("#report-form").elements.latitude.value = "";
      $("#report-form").elements.longitude.value = "";
      $("#location-feedback").textContent = "Your browser will ask permission only if you choose to add your location.";
    }
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id === "report-search") {
    const query = event.target.value.trim().toLowerCase();
    const filtered = state.reports.filter((report) => (state.filter === "all" || report.status === state.filter) &&
      [report.title, report.tracking_id, report.location].some((value) => value.toLowerCase().includes(query)));
    $("#filtered-reports").innerHTML = filtered.length ? filtered.map(reportRow).join("") : emptyState("No matching reports", "Try a different search term.");
  }
});

document.addEventListener("submit", async (event) => {
  if (event.target.id === "auth-form") {
    event.preventDefault();
    const form = event.target;
    const error = $("#auth-error");
    error.hidden = true;
    const isRegister = Boolean(form.elements.name);
    const mode = $(".login-tab.active")?.dataset.authMode || "login";
    const body = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await api(`/auth/${isRegister && mode === "register" ? "register" : "login"}`, { method: "POST", body: JSON.stringify(body) });
      setUser(result.user);
      state.view = "overview";
      await render();
      toast(`Welcome${result.user.name ? `, ${result.user.name.split(" ")[0]}` : ""}.`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
    }
  }
  if (event.target.id === "report-form") {
    event.preventDefault();
    const form = event.target;
    const error = $("#report-error");
    error.hidden = true;
    const values = new FormData(form);
    const body = Object.fromEntries(values.entries());
    body.coordinates_shared = values.has("coordinates_shared");
    try {
      const result = await api("/reports", { method: "POST", body: JSON.stringify(body) });
      state.view = "reports";
      await render();
      toast(`Report submitted. Your tracking ID is ${result.tracking_id}.`);
    } catch (exception) {
      error.textContent = exception.message;
      error.hidden = false;
    }
  }
});

$("#logout-button").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST", body: JSON.stringify({}) });
    setUser(null);
    state.reports = [];
    state.notifications = [];
    renderLanding();
    toast("You have signed out.");
  } catch (error) { showError(error); }
});

async function initialize() {
  try {
    const response = await api("/me");
    setUser(response.user);
    if (state.user) await render();
    else renderLanding();
  } catch (error) {
    content.innerHTML = `<div class="empty-state"><b>Couldn’t connect to the local service.</b><p>${escapeHtml(error.message)}</p><button class="button button-secondary" id="retry">Try again</button></div>`;
    $("#retry")?.addEventListener("click", initialize);
  }
}

initialize();
