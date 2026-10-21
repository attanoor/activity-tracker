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

function scheduleReport() {
  // Tab events arrive in bursts (activate + several updates); report once they settle.
  clearTimeout(timer);
  timer = setTimeout(report, 300);
}

async function report() {
  let body = { browser: BROWSER, url: null, title: "" };
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tab) body = { browser: BROWSER, url: tab.url ?? null, title: tab.title ?? "", incognito: tab.incognito };
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

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === "refresh") report().then(() => chrome.storage.session.get("status").then(reply));
  return true;
});
