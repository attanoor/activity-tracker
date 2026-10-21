import { expect, test } from "@playwright/test";

import { e2e, signIn } from "./helpers";

const data = e2e();

test.describe.configure({ mode: "serial" });

test("a person reviews their day, edits the AI report and submits it", async ({ page }) => {
  await signIn(page, data["e2e.resource"]);
  await page.goto(`/day?d=${data.day}`);
  await expect(page.getByRole("heading", { name: "My day" })).toBeVisible();
  // The breakdown always adds up to the 9-hour shift.
  await expect(page.getByRole("heading", { name: "Where the 9h00m went" })).toBeVisible();
  await expect(page.getByRole("img", { name: /Timeline from/ })).toBeVisible();
  await expect(page.getByText("Longest focus block")).toBeVisible();

  await page.getByRole("button", { name: "Generate report" }).click();
  const firstTitle = page.locator("input[id^='t-t']").first();
  await expect(firstTitle).toBeVisible({ timeout: 280_000 });
  await expect(page.getByText(/Written by (AI|the tracker)/)).toBeVisible();

  await firstTitle.fill("Payments: timeout fix and tests");
  await page.getByLabel("Highlights").fill("Payment timeout fixed on staging");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByText("edited by you")).toBeVisible();

  // Preview of what the manager will see hides the personal suggestions.
  await page.getByLabel("Show what my manager will see").check();
  await expect(page.getByText("Suggestions for you")).toHaveCount(0);
  await page.getByLabel("Show what my manager will see").uncheck();

  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Submit report" }).click();
  await expect(page.getByText("submitted", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Submit report" })).toHaveCount(0);
  await expect(page.getByText("Payments: timeout fix and tests")).toBeVisible();

  const xlsx = await page.request.get(`/api/me/dsr/${data.day}/export/xlsx`);
  expect(xlsx.status()).toBe(200);
  expect((await xlsx.body()).subarray(0, 2).toString()).toBe("PK");
  const pdf = await page.request.get(`/api/me/dsr/${data.day}/export/pdf`);
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
});

test("the manager sees the submitted report in the team view", async ({ page }) => {
  await signIn(page, data["e2e.manager"]);
  await page.goto(`/team?team=${data.team_id}&d=${data.day}`);
  const row = page.getByRole("row", { name: /Erin Resource/ });
  await expect(row).toContainText("Submitted");
  await row.getByRole("link", { name: "Erin Resource" }).click();
  await expect(page.getByRole("heading", { name: "Erin Resource" })).toBeVisible();
  await expect(page.getByText("Payments: timeout fix and tests")).toBeVisible();
  await expect(page.getByText("Suggestions for you")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Submit report" })).toHaveCount(0);

  const team = await page.request.get(`/api/team/${data.team_id}/day/${data.day}/export/xlsx`);
  expect(team.status()).toBe(200);

  await page.goto(`/analysis`);
  await expect(page.getByRole("heading", { name: "Analysis" })).toBeVisible();
  await page.getByLabel("Person").selectOption({ label: "Erin Resource" });
  await expect(page.getByRole("heading", { name: "Productive time by hour" })).toBeVisible();
});

test("people cannot open someone else's day", async ({ page }) => {
  await signIn(page, data["e2e.resource"]);
  const r = await page.request.get(`/api/people/${data.resource_id + 1000}/overview/${data.day}`);
  expect(r.status()).toBe(404);
  await page.goto("/team");
  await expect(page.getByText("The team view is for managers and admins.")).toBeVisible();
});

test("an admin manages category rules and sees the integrations", async ({ page }) => {
  await signIn(page, data["e2e.admin"]);
  await page.goto("/admin?tab=rules");
  const pattern = `e2e-${Date.now()}.example`;
  await page.getByLabel("Pattern").fill(pattern);
  await page.getByRole("button", { name: "Add rule" }).click();
  await page.getByLabel("Filter rules").fill(pattern);
  const row = page.getByRole("row", { name: new RegExp(pattern) });
  await expect(row).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(row).toHaveCount(0);

  await page.getByRole("button", { name: "Integrations" }).click();
  await expect(page.getByRole("heading", { name: "MantisBT" })).toBeVisible();
  await expect(page.getByText("TRACKER_MANTIS_TOKEN")).toBeVisible();
  await page.getByRole("button", { name: "Excel template" }).click();
  await expect(page.getByRole("heading", { name: "Your company DSR template" })).toBeVisible();
});
