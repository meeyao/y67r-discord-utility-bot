# ConvertCord

ConvertCord is a lightweight Discord bot focused on quick conversions between metric / imperial measurements, common currencies, temperatures, plus a handful of fun utilities (random percentages, dice rolls, a “magic conch”, and quick time/weather lookups) – perfect for EU ↔ NA chatter. The trigger alias is configurable (default `$convert`), so you can drop it into any friend server without colliding with existing bots.

## Features
- Convert temperatures between °C, °F, and K.
- Currency lookups backed by exchangerate.host with caching to avoid rate limits.
- Measurement support for length, weight, volume, speed, and area units (metric + imperial counterparts).
- Smart defaults: `!convert 5km` automatically shows miles, but `!convert 5km ft` forces a specific target.
- Optional channel/guild allowlists plus configurable status text.
- Built-in aliases let you add shortcut commands like `$roll`, `$conch`, `$time`, and `$weather`.
- Duplicate Link Detection: If a link is posted that was already seen in the same channel within the last 24 hours, the bot reacts with ♻️. It automatically normalizes variants like `x.com`, `twitter.com`, `fxtwitter.com`, `vxtwitter.com`, and `fixupx.com` to catch cross-posts.
- Quick utility commands: % for a random percentage, $roll [sides] to roll dice, $conch for a magic answer, $time [city], and $weather [city] with current conditions plus a 3-day forecast.
- Weather lookups can also accept airport codes from the bundled CSV in `data/airport-codes.csv`, so queries like `!weather LAX`, `!weather AUH 12 hours`, or `!weather BOM 3 days` work without spelling out the city.

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

The weather image renderer now uses React + Tailwind + Playwright Core with your system Chromium. If Chromium is installed in a non-standard path, set `CHROMIUM_PATH=/path/to/chromium`.

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

With everything running you can DM the bot or run commands such as:
```
!convert 70f c
!convert 5km mi
!convert 20 usd cad
$currency 100 usd eur
!roll 20
!conch should I sleep?
!time london
!weather austin
```
