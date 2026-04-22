import { expect, test } from "@playwright/test";

test("home page renders Argus heading", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /argus/i })).toBeVisible();
});
