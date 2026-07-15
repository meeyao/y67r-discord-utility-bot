import fs from "node:fs/promises";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { chromium, type Browser } from "playwright-core";

import { WeatherCard, type WeatherPayload } from "./WeatherCard.tsx";

type RenderRequest = {
  payload: WeatherPayload;
  outputPath: string;
};

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rendererRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(rendererRoot, "..");

let browser: Browser | null = null;
let cssCache: string | null = null;

async function main() {
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    if (!line.trim()) continue;
    try {
      const request = JSON.parse(line) as RenderRequest;
      await renderRequest(request);
      process.stdout.write(`${JSON.stringify({ ok: true })}\n`);
    } catch (error) {
      process.stdout.write(
        `${JSON.stringify({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        })}\n`,
      );
    }
  }
}

async function renderRequest(request: RenderRequest) {
  const payload = await hydratePayload(request.payload);
  const css = await loadCss();
  const html = "<!doctype html>" + renderToStaticMarkup(
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <style>{css}</style>
      </head>
      <body>
        <WeatherCard payload={payload} />
      </body>
    </html>,
  );

  const activeBrowser = await getBrowser();
  const page = await activeBrowser.newPage({
    deviceScaleFactor: 1,
    viewport: { width: 1560, height: 1120 },
  });
  try {
    await page.setContent(html, { waitUntil: "load" });
    await page.locator("#weather-card-root").screenshot({ path: request.outputPath });
  } finally {
    await page.close();
  }
}

async function hydratePayload(payload: WeatherPayload): Promise<WeatherPayload> {
  return {
    ...payload,
    heroIconDataUri: await loadIconDataUri(payload.conditionIcon),
    hourlyCards: await Promise.all(
      payload.hourlyCards.map(async (hour) => ({
        ...hour,
        iconDataUri: await loadIconDataUri((hour as { iconName?: string }).iconName),
      })),
    ),
    dailyCards: await Promise.all(
      payload.dailyCards.map(async (day) => ({
        ...day,
        iconDataUri: await loadIconDataUri((day as { iconName?: string }).iconName),
      })),
    ),
  };
}

async function loadCss() {
  if (cssCache !== null) return cssCache;
  const cssPath = path.join(rendererRoot, "dist", "weather-card.css");
  cssCache = await fs.readFile(cssPath, "utf8");
  return cssCache;
}

async function getBrowser() {
  if (browser && browser.isConnected()) return browser;
  const executablePath = process.env.CHROMIUM_PATH || (await detectChromium());
  browser = await chromium.launch({
    executablePath,
    headless: true,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });
  return browser;
}

async function loadIconDataUri(iconName?: string | null) {
  if (!iconName) return null;
  const filePath = path.join(repoRoot, "data", "weather-icons", `${iconName}.svg`);
  try {
    const svg = await fs.readFile(filePath, "utf8");
    return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
  } catch {
    return null;
  }
}

async function detectChromium() {
  const candidates = [
    "/usr/bin/chromium",
    "/usr/sbin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
  ];
  for (const candidate of candidates) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  return undefined;
}

async function shutdown() {
  if (browser) {
    await browser.close();
    browser = null;
  }
}

process.once("SIGTERM", () => {
  shutdown().finally(() => process.exit(0));
});
process.once("SIGINT", () => {
  shutdown().finally(() => process.exit(0));
});

main()
  .catch((error) => {
    console.error(error instanceof Error ? error.stack || error.message : String(error));
    process.exit(1);
  })
  .finally(shutdown);
