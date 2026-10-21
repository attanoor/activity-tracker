const COLORS = {
  tracking: "#12b76a", paused: "#f79009", private: "#667085", setup: "#f79009", disconnected: "#f04438", offline: "#f04438",
};

async function show(status) {
  if (!status) return;
  document.getElementById("dot").style.background = COLORS[status.mode] ?? COLORS.offline;
  document.getElementById("label").textContent = status.label ?? status.mode;
  const detail = [];
  if (status.pending) detail.push(`${status.pending} updates waiting to upload`);
  if (status.version) detail.push(`Agent ${status.version}`);
  document.getElementById("detail").textContent = detail.join(" · ");

  const offline = status.mode === "offline";
  document.getElementById("help-offline").hidden = !offline;
  document.getElementById("help-running").hidden = !offline;
  document.getElementById("help-setup").hidden = status.mode !== "setup";

  const { server } = await chrome.storage.local.get("server");
  for (const a of document.querySelectorAll("#downloads, .downloads")) {
    if (server) a.href = `${server.replace(/\/$/, "")}/downloads`;
    else a.removeAttribute("href"); // not known until the agent has run once; the admin has the address
  }
}

async function refresh() {
  document.getElementById("label").textContent = "Checking…";
  const r = await chrome.runtime.sendMessage("refresh");
  await show(r?.status);
}

document.getElementById("recheck").addEventListener("click", refresh);
chrome.storage.session.get("status").then(({ status }) => show(status));
refresh();
