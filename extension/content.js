// Runs in each page: reads the page context (extract.js) and tells the extension when it changes.
// The background script decides whether this site may be read (skip lists, allowlist, incognito).

(() => {
  let last = "";
  let lastUrl = location.href;
  let timer = null;

  function send() {
    let ctx;
    try {
      ctx = extractContext(document); // eslint-disable-line no-undef
    } catch {
      return;
    }
    const key = location.href + JSON.stringify(ctx);
    if (key === last) return;
    last = key;
    chrome.runtime.sendMessage({ type: "context", url: location.href, ctx }).catch(() => undefined);
  }

  function schedule(delay = 1500) {
    clearTimeout(timer);
    timer = setTimeout(send, delay);
  }

  schedule(800);
  // Single-page apps change the URL without a reload; check every 2 s.
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      schedule(800);
    }
  }, 2000);
  // Content changes (a new form or section) are picked up at most every 30 s.
  let lastObserved = 0;
  new MutationObserver(() => {
    const now = Date.now();
    if (now - lastObserved > 30000) {
      lastObserved = now;
      schedule(1500);
    }
  }).observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && schedule(300));
})();
