import { chromium } from "playwright";

const baseTargetUrl = process.env.GILJOB_WEB_URL ?? "http://127.0.0.1/";
const targetUrl = interviewRoomUrl(baseTargetUrl);
const executablePath = process.env.CHROME_BIN ?? "/usr/bin/google-chrome";
const pageErrors = [];

function interviewRoomUrl(value) {
  const url = new URL(value);
  if (url.pathname === "/" || url.pathname === "") {
    url.pathname = "/interviews/local-demo/room";
  }
  return url.toString();
}

function redactSensitiveText(value) {
  return String(value)
    .replace(/access_token=[^'"\s&]+/g, "access_token=<redacted>")
    .replace(/join_request=[^'"\s&]+/g, "join_request=<redacted>")
    .replace(/eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/g, "<jwt-redacted>")
    .replace(/gj_(session|report)_[A-Za-z0-9._-]+/g, "gj_$1_<redacted>");
}

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
  ],
});

try {
  const page = await browser.newPage();
  page.on("pageerror", (error) => pageErrors.push(redactSensitiveText(error.message)));
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      console.log(`BROWSER_${message.type().toUpperCase()}: ${redactSensitiveText(message.text())}`);
    }
  });

  await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForSelector("#room-shell", { timeout: 10000 });
  const joinButton = await page.$("#join-room");
  if (joinButton) {
    await joinButton.click();
  }
  await page.waitForFunction(() => {
    const status = document.querySelector("#status")?.textContent?.toLowerCase() ?? "";
    return status.includes("connected");
  }, null, { timeout: 30000 });

  const connectedStatus = await page.locator("#status").textContent();
  const summary = await page.locator("#session-summary").evaluate((element) => element.textContent ?? "");
  const log = await page.locator("#event-log").evaluate((element) => element.textContent ?? "");
  if (/access_token=|join_request=|gj_session_|gj_report_|eyJ[a-zA-Z0-9_-]+\./.test(`${summary}\n${log}`)) {
    throw new Error("raw token appeared in visible browser text");
  }

  await page.click("#leave-room");
  await page.waitForFunction(() => {
    const status = document.querySelector("#status")?.textContent?.toLowerCase() ?? "";
    return status.includes("disconnected");
  }, null, { timeout: 10000 });
  const disconnectedStatus = await page.locator("#status").textContent();
  if (pageErrors.length) {
    throw new Error(`browser page errors: ${pageErrors.join(" | ")}`);
  }
  console.log("BROWSER_SMOKE_OK", connectedStatus, "->", disconnectedStatus);
} finally {
  await browser.close();
}
