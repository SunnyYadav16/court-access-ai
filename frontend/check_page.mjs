import { chromium } from "playwright";

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  page.on("console", (msg) => console.log(`[Browser Console] ${msg.type()}: ${msg.text()}`));
  page.on("pageerror", (err) => console.error(`[Browser Error] ${err.message}`));

  page.on("response", (res) => {
    if (res.status() >= 400) {
      console.log(`[Network Error] ${res.status()} ${res.url()}`);
    }
  });

  try {
    await page.goto("http://localhost:3000/", { waitUntil: "networkidle", timeout: 10000 });
    const html = await page.content();
    console.log(`[HTML snippet]`, html.substring(0, 300));
  } catch (err) {
    console.log("[Navigation Error]", err.message);
  } finally {
    await browser.close();
  }
})();
