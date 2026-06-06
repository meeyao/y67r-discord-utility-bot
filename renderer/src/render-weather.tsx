import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { chromium } from "playwright-core";

import { WeatherCard, type WeatherPayload } from "./WeatherCard.tsx";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rendererRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(rendererRoot, "..");

async function main() {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) {
    throw new Error("Usage: render-weather <payload.json> <output.png>");
  }

  const payload = JSON.parse(await fs.readFile(inputPath, "utf8")) as WeatherPayload;
  const cssPath = path.join(rendererRoot, "dist", "weather-card.css");
  const css = await fs.readFile(cssPath, "utf8");

  payload.heroIconDataUri = await loadIconDataUri(payload.conditionIcon);
  payload.hourlyCards = await Promise.all(
    payload.hourlyCards.map(async (hour) => ({
      ...hour,
      iconDataUri: await loadIconDataUri((hour as { iconName?: string }).iconName),
    })),
  );
  payload.dailyCards = await Promise.all(
    payload.dailyCards.map(async (day) => ({
      ...day,
      iconDataUri: await loadIconDataUri((day as { iconName?: string }).iconName),
    })),
  );

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

  const executablePath = process.env.CHROMIUM_PATH || (await detectChromium());
  const browser = await chromium.launch({
    executablePath,
    headless: true,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });

  try {
    const page = await browser.newPage({
      deviceScaleFactor: 1,
      viewport: { width: 1560, height: 1120 },
    });
    await page.setContent(html, { waitUntil: "load" });
    await page.locator("#weather-card-root").screenshot({ path: outputPath });
  } finally {
    await browser.close();
  }
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

main().catch((error) => {
  console.error(error instanceof Error ? error.stack || error.message : String(error));
  process.exit(1);
});
