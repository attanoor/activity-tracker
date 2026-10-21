import fs from "node:fs";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

type Account = { email: string; password: string };
export type E2E = { "e2e.resource": Account; "e2e.manager": Account; "e2e.admin": Account; day: string; team_id: number; resource_id: number };

export function e2e(): E2E {
  const file = path.resolve(__dirname, "..", "..", "..", ".local", "secrets", "e2e.json");
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export async function signIn(page: Page, who: Account) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(who.email);
  await page.locator("#current-password").fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}
