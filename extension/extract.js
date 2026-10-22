// What the page says about where the person is: headings, breadcrumb, active menu, and the club name.
// Reads labels and headings only. It never reads what is typed into fields, form values or page body text.
// Pure function of `doc`, so it can be tested on fixture pages.

// eslint-disable-next-line no-unused-vars
function extractContext(doc) {
  const MAX = 200;
  const clip = (s, n = MAX) => (s || "").replace(/\s+/g, " ").trim().slice(0, n);
  const isField = (el) => el.closest("input, textarea, [contenteditable=''], [contenteditable='true']");
  const text = (el, n) => (el && !isField(el) ? clip(el.textContent, n) : "");
  const first = (selectors, n) => {
    for (const sel of selectors) {
      for (const el of doc.querySelectorAll(sel)) {
        const t = text(el, n);
        if (t) return t;
      }
    }
    return "";
  };

  const crumbs = [];
  for (const el of doc.querySelectorAll(
    "nav[aria-label*='readcrumb' i] li, nav[aria-label*='readcrumb' i] a, ol.breadcrumb li, ul.breadcrumb li, " +
    ".breadcrumbs li, .breadcrumb-item, [class*='breadcrumb' i] > a")) {
    const t = text(el, 60);
    if (t && !crumbs.includes(t)) crumbs.push(t);
    if (crumbs.length >= 6) break;
  }

  const menu = first(["nav [aria-current='page']", "[role='navigation'] [aria-current='page']", ".sidebar .active > a",
    ".sidebar a.active", ".menu .active > a", ".menu a.active", "nav li.active > a", "nav a.active", ".nav .active > a"], 80);
  const heading = first(["form legend", ".page-title", ".page-header h1", ".page-header h2", ".panel-title",
    ".card-header h2", ".card-title", "main h2", "h2"], 120);
  const h1 = first(["main h1", "h1"], 120);

  // Club name candidates, most reliable first.
  const clubs = [];
  const add = (v) => {
    const t = clip(v, 120);
    if (t && t.length >= 3 && !clubs.includes(t) && clubs.length < 4) clubs.push(t);
  };
  for (const sel of doc.querySelectorAll("select[name*='club' i], select[id*='club' i]")) {
    const opt = sel.selectedOptions && sel.selectedOptions[0];
    if (opt && sel.selectedIndex > 0) add(opt.textContent); // the club chosen in a club picker
  }
  for (const el of doc.querySelectorAll("[id*='club' i], [class*='club' i]")) {
    if (el.matches("input, textarea, select, option, script, style") || isField(el)) continue;
    const t = clip(el.textContent, 121);
    if (t && t.length <= 80 && el.children.length <= 3) add(t); // short labels only, never whole panels
  }
  const site = doc.querySelector("meta[property='og:site_name'], meta[name='application-name']");
  if (site) add(site.getAttribute("content"));
  for (const img of doc.querySelectorAll("header img[alt], .logo img[alt], .navbar-brand img[alt], img.logo[alt]")) {
    const alt = img.getAttribute("alt") || "";
    if (alt && !/^logo$/i.test(alt.trim())) add(alt.replace(/\s*logo\s*$/i, ""));
  }
  const brand = first([".navbar-brand", "header .brand", ".site-title", ".club-name"], 80);
  if (brand) add(brand);

  const out = {};
  if (h1) out.h1 = h1;
  if (heading && heading !== h1) out.heading = heading;
  if (crumbs.length) out.crumbs = crumbs;
  if (menu) out.menu = menu;
  if (clubs.length) out.clubs = clubs;
  // Hard cap: never more than about 1 KB.
  while (JSON.stringify(out).length > 1000 && out.crumbs && out.crumbs.length) out.crumbs.pop();
  return out;
}

if (typeof module !== "undefined") module.exports = { extractContext };
