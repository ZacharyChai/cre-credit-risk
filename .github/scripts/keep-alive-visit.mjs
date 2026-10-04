// Opens the deployed Streamlit app and waits for it to render, waking it first if it
// went to sleep. Run by .github/workflows/keep-alive.yml.
//
// The sleep screen is rendered by JavaScript after the page loads, so at
// "domcontentloaded" the page is still blank. Playwright's locator.isVisible() answers
// for that instant and returns immediately (its timeout option does not make it wait),
// so a one-shot check right after page.goto never sees the wake button. This script
// polls instead: each pass looks for the app title (awake, done) or the wake button
// (asleep, press it), in the page and in every frame, until the app renders or the
// deadline passes.
//
// The settings below can be overridden through the environment so the same script can
// be exercised against local fixtures; the defaults are what CI uses.
import { chromium } from "playwright";

const url = process.env.KEEPALIVE_URL ?? "https://cre-credit-risk.streamlit.app/";
const deadlineMs = Number(process.env.KEEPALIVE_DEADLINE_MS ?? 300_000);
const holdMs = Number(process.env.KEEPALIVE_HOLD_MS ?? 20_000);
const retryClickMs = Number(process.env.KEEPALIVE_RETRY_MS ?? 60_000);
const pollMs = Number(process.env.KEEPALIVE_POLL_MS ?? 3_000);
const channel = process.env.KEEPALIVE_BROWSER_CHANNEL; // e.g. "chrome" for a local run

const WAKE = /get this app back up/i;
const TITLE = "text=CRE Credit Risk"; // from st.title("CRE Credit Risk")

const browser = await chromium.launch(channel ? { channel } : {});
const page = await browser.newPage();
const started = Date.now();
const elapsed = () => `${Math.round((Date.now() - started) / 1000)}s`;

try {
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90_000 });

  const deadline = started + deadlineMs;
  let rendered = false;
  let clicks = 0;
  let lastClick = 0;
  let wakeSeen = false;
  let pass = 0;

  while (!rendered && Date.now() < deadline) {
    for (const frame of page.frames()) {
      if ((await frame.locator(TITLE).count().catch(() => 0)) > 0) {
        rendered = true;
        break;
      }
      const wake = frame.getByRole("button", { name: WAKE });
      if ((await wake.count().catch(() => 0)) > 0) {
        wakeSeen = true;
        // Press it once, and again if it is still showing a while later (a click that
        // did not take, or a boot that failed and fell back to the sleep screen).
        if (clicks === 0 || Date.now() - lastClick > retryClickMs) {
          clicks += 1;
          lastClick = Date.now();
          console.log(`[${elapsed()}] app is asleep (wake button in ${frame.url() || "main page"}); pressing it (click ${clicks})`);
          await wake.first().click().catch((e) => console.log(`[${elapsed()}] click failed: ${e.message.split("\n")[0]}`));
        }
      }
    }
    if (!rendered) {
      pass += 1;
      if (pass % 10 === 0) console.log(`[${elapsed()}] still waiting for the app to render (${Math.round((deadline - Date.now()) / 1000)}s left)`);
      await page.waitForTimeout(pollMs);
    }
  }

  if (!rendered) {
    const body = await page.locator("body").innerText({ timeout: 5_000 }).catch(() => "(could not read page text)");
    console.log(`page text at timeout: ${body.replace(/\s+/g, " ").slice(0, 300)}`);
    throw new Error(
      `app did not render within ${Math.round(deadlineMs / 1000)}s ` +
      `(wake button seen: ${wakeSeen ? "yes" : "no"}, clicks: ${clicks})`,
    );
  }

  console.log(`[${elapsed()}] app rendered${clicks ? ` after ${clicks} wake click(s)` : " (it was already awake)"}`);

  // Hold the session open briefly so the visit registers as viewer traffic.
  await page.waitForTimeout(holdMs);
  console.log(`[${elapsed()}] visit complete`);
} finally {
  await browser.close();
}
