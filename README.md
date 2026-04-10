# ConvertCord

ConvertCord is a lightweight Discord bot focused on quick conversions between metric / imperial measurements, common currencies, temperatures, plus a handful of fun utilities (random percentages, dice rolls, a “magic conch”, and quick time/weather lookups) – perfect for EU ↔ NA chatter. The trigger alias is configurable (default `$convert`), so you can drop it into any friend server without colliding with existing bots.

## Features
- Convert temperatures between °C, °F, and K.
- Currency lookups backed by exchangerate.host with caching to avoid rate limits.
- Measurement support for length, weight, volume, speed, and area units (metric + imperial counterparts).
- Smart defaults: `!convert 5km` automatically shows miles, but `!convert 5km ft` forces a specific target.
- Optional channel/guild allowlists plus configurable status text.
- Built-in aliases let you add shortcut commands like `$roll`, `$conch`, `$time`, and `$weather`.
- Quick utility commands: `%` for a random percentage, `$roll [sides]` to roll dice, `$conch` for a magic answer, `$time [city]`, and `$weather [city]`.

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

## Running locally
```bash
cd convertcord
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CONVERTCORD_TOKEN="your token"
python -m convertcord.bot
```

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
