import { chromium } from "playwright";

const modelPath = "D:\\sih_drone_pipeline\\.codex-build\\optimized_v1_archive\\optimized_v1\\point_cloud.ply";
const reportPath = "D:\\sih_drone_pipeline\\.codex-build\\optimized_v1_archive\\optimized_v1\\viewer_metadata.json";
const outputPath = "D:\\sih_drone_pipeline\\.codex-build\\presentation\\viewer_point_cloud.png";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
await page.goto("http://127.0.0.1:4173/", { waitUntil: "networkidle" });
await page.locator("#model-file").setInputFiles(modelPath);
await page.waitForFunction(() => document.querySelector("#model-name")?.textContent === "point_cloud.ply", null, { timeout: 120000 });
await page.locator("#report-file").setInputFiles(reportPath);
await page.waitForFunction(() => document.querySelector("#processing")?.textContent?.includes("min"), null, { timeout: 30000 });
await page.mouse.move(820, 440);
for (let i = 0; i < 2; i++) {
  await page.mouse.wheel(0, -1100);
  await page.waitForTimeout(250);
}
const hits = [];
for (let y = 140; y <= 780 && hits.length < 20; y += 35) {
  for (let x = 90; x <= 1170 && hits.length < 20; x += 35) {
    await page.mouse.move(x, y);
    await page.waitForTimeout(12);
    const cursor = await page.locator("#cursor").textContent();
    if (cursor && cursor.trim() !== "-") hits.push({ x, y, cursor });
  }
}
if (hits.length >= 2) {
  const first = hits[0];
  const second = hits.find((hit) => Math.hypot(hit.x - first.x, hit.y - first.y) > 160) ?? hits[hits.length - 1];
  await page.mouse.click(first.x, first.y, { modifiers: ["Shift"] });
  await page.mouse.click(second.x, second.y, { modifiers: ["Shift"] });
}
await page.waitForTimeout(6000);
await page.screenshot({ path: outputPath, fullPage: true });
await browser.close();
console.log(outputPath);
