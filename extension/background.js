// Reports the active tab of the focused browser window to the Activity Tracker agent on this PC.
// Nothing is sent anywhere else; the agent decides how long the tab was in front.

const AGENT = "http://127.0.0.1:47823";
const BROWSER = navigator.userAgent.includes("Edg/") ? "msedge.exe" : "chrome.exe";
const BADGE = {
  tracking: ["", "#12b76a"],
  paused: ["II", "#f79009"],
  private: ["P", "#667085"],
  setup: ["!", "#f79009"],
  disconnected: ["!", "#f04438"],
  offline: ["!", "#f04438"],
};

let timer = null;
// Page context per tab, from content.js; kept in session storage so it survives the worker sleeping.
const contexts = new Map();
let rules = { page_reading: true, allow: [], skip: [], at: 0 };

async function loadRules() {
  if (Date.now() - rules.at < 10 * 60 * 1000) return rules;
  try {
    const r = await fetch(`${AGENT}/config`);
    if (r.ok) rules = { ...(await r.json()), at: Date.now() };
  } catch {
    rules.at = Date.now(); // agent not running; keep the last rules
  }
  return rules;
}

function hostMatches(host, pattern) {
  pattern = (pattern || "").toLowerCase().trim();
  if (!pattern) return false;
  if (pattern.includes("*")) {
    const re = new RegExp("^" + pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$");
    return re.test(host);
  }
  return host === pattern || host.endsWith("." + pattern);
}

async function mayRead(url) {
  let host;
  try {
    const u = new URL(url);
    if (!u.protocol.startsWith("http")) return false;
    host = u.hostname.toLowerCase();
  } catch {
    return false;
  }
  const r = await loadRules();
  if (r.page_reading === false) return false;
  if ((r.skip || []).some((p) => hostMatches(host, p))) return false;
  if ((r.allow || []).length && !r.allow.some((p) => hostMatches(host, p))) return false;
  return true;
}

function scheduleReport() {
  // Tab events arrive in bursts (activate + several updates); report once they settle.
  clearTimeout(timer);
  timer = setTimeout(report, 300);
}

async function report() {
  let body = { browser: BROWSER, url: null, title: "" };
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab) {
      body = { browser: BROWSER, url: tab.url ?? null, title: tab.title ?? "", incognito: tab.incognito };
      const c = contexts.get(tab.id) ?? (await chrome.storage.session.get(`ctx${tab.id}`))[`ctx${tab.id}`];
      if (c && c.url === tab.url && !tab.incognito) body.context = c.ctx;
    }
  } catch {
    // no focused window (all minimised); the agent sees a non-browser app in front anyway
  }
  try {
    const r = await fetch(`${AGENT}/tab`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const status = r.ok ? await r.json() : { mode: "offline", label: `Agent refused (${r.status})` };
    await setStatus(status);
  } catch {
    await setStatus({ mode: "offline", label: "The Activity Tracker agent is not running on this PC." });
  }
}

async function setStatus(status) {
  const [text, color] = BADGE[status.mode] ?? BADGE.offline;
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.storage.session.set({ status, at: Date.now() });
  // Remember the server so the popup can link to the Downloads page even while the agent is not running.
  if (status.server) await chrome.storage.local.set({ server: status.server });
}

chrome.tabs.onActivated.addListener(scheduleReport);
chrome.tabs.onUpdated.addListener((_id, change, tab) => {
  if (tab.active && (change.url || change.title || change.status === "complete")) scheduleReport();
});
chrome.windows.onFocusChanged.addListener(scheduleReport);
chrome.runtime.onStartup.addListener(scheduleReport);
chrome.runtime.onInstalled.addListener(scheduleReport);

// Heartbeat: if the agent restarts it learns the current tab within half a minute.
chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((a) => a.name === "heartbeat" && report());

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg === "refresh") {
    report().then(() => chrome.storage.session.get("status").then(reply));
    return true;
  }
  if (msg && msg.type === "context" && sender.tab && !sender.tab.incognito) {
    mayRead(msg.url).then(async (ok) => {
      const entry = ok ? { url: msg.url, ctx: msg.ctx } : null;
      if (entry) contexts.set(sender.tab.id, entry);
      else contexts.delete(sender.tab.id);
      await chrome.storage.session.set({ [`ctx${sender.tab.id}`]: entry });
      if (sender.tab.active) scheduleReport();
    });
  }
  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  contexts.delete(tabId);
  chrome.storage.session.remove(`ctx${tabId}`);
});
