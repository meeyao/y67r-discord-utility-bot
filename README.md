# ConvertCord

ConvertCord is a lightweight Discord bot focused on quick conversions between metric / imperial measurements, common currencies, temperatures, plus a handful of fun utilities (random percentages, dice rolls, a “magic conch”, and quick time/weather lookups) – perfect for EU ↔ NA chatter. The trigger alias is configurable (default `$convert`), so you can drop it into any friend server without colliding with existing bots.

## Features

### Conversions & Lookups
- **Convert** — temperatures (°C, °F, K), length, weight, volume, speed, and area (metric + imperial). Smart defaults: `!convert 5km` auto-shows miles, `!convert 5km ft` forces a specific target.
- **Currency** — `$convert 20 usd eur` or `$currency 100 eur`. Backed by open.er-api.com with configurable caching.
- **Urban Dictionary** — `!urban` or `!ud <word>` to look up definitions from the vendored Urban Dictionary API.
- **Temps** — `!temps` shows a quick reference table of common temperature conversions.

### Weather
- **Weather lookups** — `!weather <city>` with current conditions + 3-day forecast. Supports airport codes (IATA/ICAO) from the bundled CSV: `!weather LAX`, `!weather AUH 12 hours`, `!weather BOM 3 days`.
- **Saved weather location** — `!weather set <city>` saves your default location, so `!weather` or `!weather tomorrow` can use it later. Slash users can set this with `/weather-location`.
- **Local units first** — Weather replies prioritize Celsius/km/h for metric countries and Fahrenheit/mph for common imperial-weather countries.
- **Image rendering** — Weather forecasts are rendered as styled images via React + Tailwind + Playwright Core (Chromium). Includes custom weather icons.

### Time, Reminders & Timezones
- **Time** — `!time <city>` shows the current time for any city or IATA code. Supports broadcaster abbreviations (e.g. `!time asmongold`).
- **Timezone** — `!timezone <city>` sets your personal timezone for daily reminders.
- **Reminders** — `!remind <duration> <message>` for one-off reminders, `!daily-remind <HH:MM> <message>` for recurring daily reminders. List with `!reminders-list`, delete with `!reminders-delete`.
- **Rotate** — `!rotate <angle>` — reply to an image message or attach one to rotate it by a given angle.

### Utilities
- **Roll** — `!roll 20` rolls dice with configurable sides.
- **Conch** — `!conch <question>` — the Magic Conch answers your yes/no questions.
- **Percent** — `%` or `!percent` gives a random percentage.
- **GTA VI Countdown** — `!gta` displays a live countdown to the Grand Theft Auto VI launch.

### Football / World Cup
- **Football (Soccer)** — `!football` (or `!wc`, `!fifa`, `!soccer`, `!team`) with subcommands:
  - `live` — live scores from ongoing matches
  - `wc` / `worldcup` — next World Cup match schedule
  - `standings [group]` — group standings for the World Cup
  - `team <country>` — upcoming matches for a specific team
  - `stream` / `streamed` — combined stream sources from ppv.st and streamed.su
- Powered by football-data.org and api-sports.io.

### PPV Stream Finder
- `!ppv` — locates the next World Cup stream from ppv.st and alternative sources.
- `!ppv ufc` — finds the next UFC event stream.
- `!streamed` or `!stream` — shows combined stream listings from all available sources.
- Uses the bundled `ppv-resolver/` Node.js service for HLS stream resolution.

### Link Rewriting (Sanitize)
- Automatically rewrites links to fix cross-platform embeds. Toggle per platform via config or slash commands:
  - **Instagram** — `instagram.com` → `ddinstagram.com`
  - **Reddit** — `reddit.com` → `rxddit.com`
  - **TikTok** — `tiktok.com` → `vxtiktok.com` (resolves usernames)
  - **Twitch** — `twitch.tv/clips/...` → `clips.twitch.tv/...` (resolves streamer names)
  - **Twitter / X** — `twitter.com` / `x.com` → `fxtwitter.com` (normalizes `vxtwitter.com` / `fixupx.com` too)
- Slash commands: `/sanitize-status` shows current settings, `/sanitize-toggle <platform>` flips a platform on/off at runtime.

### Duplicate Link Detection
- If a link is posted that was already seen in the same channel within the last 24 hours, the bot reacts with ♻️.
- Automatically normalizes URL variants (`x.com`, `twitter.com`, `fxtwitter.com`, `vxtwitter.com`, `fixupx.com`, `instagram.com`/`ddinstagram.com`, and generic shortlinks) to catch cross-posts.
- Media file links (images, videos, audio) and Discord system domains are excluded from detection.

### Additional
- **Slash commands** — all major features available as `/convert`, `/weather`, `/weather-location`, `/time`, `/roll`, `/conch`, `/urban`, `/temps`, `/football`, `/ppv`, `/ufc`, `/gta`, `/remind`, `/daily-remind`, `/reminders-list`, `/reminders-delete`, `/timezone`, `/sanitize-status`, `/sanitize-toggle`.
- **Configurable trigger alias** — Default `$convert`, change via config or `CONVERTCORD_ALIAS` env var.
- **Channel / Guild allowlists** — Optional safety rails; leave empty to allow everywhere.
- **Runtime slash sync** — `!sync` instantly registers slash commands in the current guild.

## Configuration
1. Copy the example config and adjust it as needed:
   ```bash
   cp convertcord/config/config.yaml.example convertcord/config/config.yaml
   ```
2. Set the Discord token either in the config (`discord.token`) **or** via the `CONVERTCORD_TOKEN` env var.
3. Customize the alias (`discord.alias`, default `$convert`), add any `discord.additional_aliases` (each including the `$` prefix if desired), tweak presence text, and configure allowlists if needed.
4. Currency settings let you tweak the default targets shown when the user omits the destination currency and how long rates stay cached.
5. Sanitizer settings let you enable or disable per-platform link rewriting. For example, set `sanitize.twitch: false` if you prefer Discord's native Twitch clip embeds.

Guild admins can also change these at runtime with slash commands:
`/sanitize-status` shows the current platform settings.
`/sanitize-toggle` flips a single platform on or off and persists it back to the config file.

Environment overrides:
- `CONVERTCORD_CONFIG` – Path to the config file (defaults to `/config/config.yaml` inside Docker).
- `CONVERTCORD_TOKEN` – Discord bot token (takes precedence over the config file).
- `CONVERTCORD_ALIAS` – Force the primary trigger alias without touching the config (e.g. `?conv`).
- `CONVERTCORD_EXTRA_ALIASES` – Comma-delimited list of extra aliases (e.g. `$currency,$convert`) merged with config values.
- `CONVERTCORD_AIRPORT_CODES_CSV` – Optional override path for the airport code CSV used for IATA/ICAO weather lookups. By default the bot uses `data/airport-codes.csv` from the repo/image.
- `CONVERTCORD_URBAN_API_URL` – Base URL for the Urban API. In the bundled Docker image it defaults to the vendored local service at `http://127.0.0.1:8080/api`. Outside Docker it falls back to the public unofficial service unless you override it.
- `CONVERTCORD_FOOTBALL_API_KEY` – Override for the `football-data.org` API key (takes precedence over the config file).
- `CONVERTCORD_FOOTBALL_API_SPORTS_KEY` – Override for the `api-sports.io` API key (takes precedence over the config file).

## Running locally
```bash
cd convertcord
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd renderer
npm install
npm run build:css
cd ..
export CONVERTCORD_TOKEN="your token"
python -m convertcord.bot
```

The weather image renderer uses React + Tailwind + Playwright Core with your system Chromium. It keeps a warm renderer worker after the first request to avoid launching Chromium for every weather reply. If Chromium is installed in a non-standard path, set `CHROMIUM_PATH=/path/to/chromium`.

## Docker
A minimal image is included:
```bash
docker build -t convertcord ./convertcord
docker run --rm \
  -e CONVERTCORD_TOKEN=your-token \
  -e CONVERTCORD_CONFIG=/config/config.yaml \
  -v $(pwd)/convertcord/config:/config:ro \
  convertcord
```

The container now installs `nodejs`, `npm`, and `chromium`, starts the vendored Urban API alongside the bot, and points `/urban` at `http://127.0.0.1:8080/api` by default. You do not need to set `CONVERTCORD_URBAN_API_URL` unless you want to override that.

## docker-compose
Add the following service to `docker-compose.yaml`:
```yaml
convertcord:
  build:
    context: ./convertcord
  container_name: convertcord
  environment:
    - CONVERTCORD_CONFIG=/config/config.yaml
    - CONVERTCORD_TOKEN=${CONVERTCORD_TOKEN}
  volumes:
    - ./convertcord/config:/config:ro
  restart: unless-stopped
```

The vendored Urban API under `vendor/unofficial-urban-dictionary-api` includes a defensive scraper fix for the current Urban Dictionary markup change that broke the public hosted instance.

A `ppv-resolver/` service is also bundled and started alongside the bot for PPV stream resolution.

With everything running you can DM the bot or run commands such as:
```
!convert 70f c
!convert 5km mi
!convert 20 usd cad
$currency 100 usd eur
!roll 20
!conch should I sleep?
!time london
!weather set austin
!weather austin
!weather
!football live
!football standings
!football team Argentina
!football wc
!ppv
!ppv ufc
!gta
```
