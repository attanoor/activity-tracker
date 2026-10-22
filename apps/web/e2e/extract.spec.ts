import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

// The extension's page reader, run in a real browser against fixture pages (no server needed).
const extractJs = fs.readFileSync(path.resolve(__dirname, "..", "..", "..", "extension", "extract.js"), "utf8");

async function extract(page: import("@playwright/test").Page, html: string, typeInto?: string) {
  await page.setContent(html);
  if (typeInto) await page.fill(typeInto, "SECRET-TYPED-VALUE");
  await page.addScriptTag({ content: extractJs });
  return page.evaluate(() => (window as unknown as { extractContext(d: Document): Record<string, unknown> }).extractContext(document));
}

test("backoffice page: club from the header, breadcrumb and menu", async ({ page }) => {
  const ctx = await extract(page, `
    <header><a class="navbar-brand">NorthStar</a><span class="current-club">River Oaks Country Club</span></header>
    <nav><ul><li><a href="#">Members</a></li><li class="active"><a href="#">Billing</a></li></ul></nav>
    <ol class="breadcrumb"><li>Home</li><li>Membership</li><li>Dues setup</li></ol>
    <main><h1>Dues setup</h1><form><legend>Annual dues</legend>
      <label>Card number <input name="card" value="4111111111111111"></label>
      <label>Password <input type="password" name="pw" value="hunter2"></label>
      <textarea name="note">private note</textarea></form>
      <p>Member John Smith owes 1,200 dollars.</p></main>`, "input[name=card]");
  expect(ctx).toEqual({
    h1: "Dues setup", heading: "Annual dues", crumbs: ["Home", "Membership", "Dues setup"], menu: "Billing",
    clubs: ["River Oaks Country Club", "NorthStar"],
  });
  const text = JSON.stringify(ctx);
  for (const secret of ["SECRET-TYPED-VALUE", "4111", "hunter2", "private note", "John Smith", "1,200"]) {
    expect(text).not.toContain(secret);
  }
});

test("club picked in a selector, site name and logo", async ({ page }) => {
  const ctx = await extract(page, `
    <head><meta property="og:site_name" content="Lakeside Golf Club"></head>
    <header><img class="logo" alt="Lakeside Golf Club logo" src="x.png"></header>
    <select name="clubId"><option>Choose a club</option><option selected>Oak Hills CC</option></select>
    <main><h2>Tee time rules</h2></main>`);
  expect(ctx.clubs).toEqual(["Oak Hills CC", "Lakeside Golf Club"]);
  expect(ctx.heading).toBe("Tee time rules");
});

test("large containers named 'club' are not read as a club name", async ({ page }) => {
  const long = "word ".repeat(60);
  const ctx = await extract(page, `<div class="club-panel"><p>${long}</p><p>more</p><p>more</p><p>more</p></div><h1>Dashboard</h1>`);
  expect(ctx.clubs).toBeUndefined();
  expect(JSON.stringify(ctx).length).toBeLessThan(1000);
});
