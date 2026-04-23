from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Sequence


def render_weather_card(
    *,
    location_display: str,
    condition: str,
    condition_icon: str,
    temperature_c: float,
    feels_c: Optional[float],
    humidity: Optional[int],
    dew_point_c: Optional[float],
    wind_kmh: Optional[float],
    gust_kmh: Optional[float],
    wind_direction: Optional[str],
    pressure_hpa: Optional[float],
    precip_probability: Optional[int],
    cloud_cover: Optional[int],
    visibility_text: Optional[str],
    sunrise: Optional[str],
    sunset: Optional[str],
    uv_text: Optional[str],
    aqi_text: Optional[str],
    observed_text: Optional[str],
    hourly_cards: Sequence[Dict[str, object]],
    daily_cards: Sequence[Dict[str, object]],
    forecast_rows: Sequence[str],
    accent_rgb: tuple[int, int, int],
) -> Optional[bytes]:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    width, height = 1500, 1060
    image = Image.new("RGB", (width, height), "#1a4db3")
    draw = ImageDraw.Draw(image)

    top = _blend((39, 95, 219), accent_rgb, 0.16)
    bottom = (22, 69, 172)
    _draw_vertical_gradient(draw, width, height, top, bottom)
    shell = (48, 48, width - 48, height - 48)
    draw.rounded_rectangle(shell, radius=34, fill="#16439f", outline="#0b1730", width=6)

    text = "#f5fbff"
    muted = "#c9dbff"
    soft = "#95b4ff"
    peach = "#ffbd8a"
    panel = "#2052ae"
    panel2 = "#2a5dbc"

    small = _load_font(20)
    body = _load_font(24)
    body_bold = _load_font(24, bold=True)
    heading = _load_font(34, bold=True)
    hero_temp = _load_font(104, bold=True)
    hero_sub = _load_font(30)
    section = _load_font(28, bold=True)
    card_label = _load_font(18)
    card_temp = _load_font(24, bold=True)

    draw.rounded_rectangle((86, 84, width - 86, 356), radius=30, fill="#1b4ca9")
    draw.text((116, 104), location_display, font=body_bold, fill=text)
    draw.text((116, 146), condition, font=hero_sub, fill=muted)
    _paste_icon(image, condition_icon, (120, 192), 118)
    draw.text((264, 176), f"{round(temperature_c):.0f}°C / {round(_c_to_f(temperature_c)):.0f}°F", font=hero_temp, fill=text)
    if feels_c is not None:
        draw.text((272, 292), f"Feels {round(feels_c):.0f}°C / {round(_c_to_f(feels_c)):.0f}°F", font=body, fill=peach)
    if observed_text:
        draw.text((116, 326), observed_text, font=small, fill=soft)

    metrics = [
        ("Humidity", f"{humidity}%" if humidity is not None else None),
        ("Wind", f"{wind_direction + ' ' if wind_direction else ''}{wind_kmh:.1f} km/h ({_kmh_to_mph(wind_kmh):.1f} mph)" if wind_kmh is not None else None),
        ("Pressure", f"{pressure_hpa:.0f} hPa" if pressure_hpa is not None else None),
        ("Precip", f"{precip_probability}%" if precip_probability is not None else None),
        ("Sunrise", sunrise),
        ("Sunset", sunset),
        ("UV", uv_text),
        ("AQI", aqi_text),
    ]
    metrics = [item for item in metrics if item[1]]
    _draw_metric_grid(draw, metrics, origin=(850, 108), size=(248, 68), gap=(24, 14), label_font=small, value_font=body_bold, label_color=soft, value_color=text, fill="#2f63bd")

    details_y = 392
    box_w = 308
    gap = 20
    sections = [
        ("Now", [
            f"{round(temperature_c):.0f}°C / {round(_c_to_f(temperature_c)):.0f}°F",
            f"Feels {round(feels_c):.0f}°C / {round(_c_to_f(feels_c)):.0f}°F" if feels_c is not None else None,
            observed_text,
        ]),
        ("Air", [
            f"Humidity {humidity}%" if humidity is not None else None,
            f"Dew point {round(dew_point_c):.0f}°C / {round(_c_to_f(dew_point_c)):.0f}°F" if dew_point_c is not None else None,
            f"Pressure {pressure_hpa:.0f} hPa" if pressure_hpa is not None else None,
        ]),
        ("Sky", [
            f"Clouds {cloud_cover}%" if cloud_cover is not None else None,
            f"Visibility {visibility_text}" if visibility_text else None,
            f"Precip {precip_probability}%" if precip_probability is not None else None,
        ]),
        ("Wind", [
            f"{wind_direction + ' ' if wind_direction else ''}{wind_kmh:.1f} km/h ({_kmh_to_mph(wind_kmh):.1f} mph)" if wind_kmh is not None else None,
            f"Gusts {gust_kmh:.1f} km/h ({_kmh_to_mph(gust_kmh):.1f} mph)" if gust_kmh is not None else None,
        ]),
    ]
    for idx, (title, lines) in enumerate(sections):
        x1 = 86 + idx * (box_w + gap)
        x2 = x1 + box_w
        y2 = details_y + 180
        draw.rounded_rectangle((x1, details_y, x2, y2), radius=24, fill="#1b4ca9")
        draw.text((x1 + 20, details_y + 16), title, font=section, fill=text)
        line_y = details_y + 58
        for line in [line for line in lines if line]:
            draw.text((x1 + 20, line_y), line, font=body, fill=muted if title != "Now" else text)
            line_y += 34

    hourly_y = 600
    draw.text((86, hourly_y), "Hourly", font=heading, fill=text)
    x = 86
    for idx, card in enumerate(hourly_cards[:6]):
        w = 204
        h = 126
        y1 = hourly_y + 48
        draw.rounded_rectangle((x, y1, x + w, y1 + h), radius=22, fill=panel2 if idx == 0 else panel)
        draw.text((x + 18, y1 + 16), str(card["label"]), font=card_label, fill=soft)
        _paste_icon(image, str(card["icon"]), (x + 18, y1 + 42), 42)
        draw.text((x + 18, y1 + 82), str(card["temp"]), font=card_temp, fill=text)
        x += w + 16

    forecast_y = 798
    draw.text((86, forecast_y), "Forecast", font=heading, fill=text)
    row_y = forecast_y + 48
    for idx, row in enumerate(forecast_rows[:3]):
        draw.rounded_rectangle((86, row_y, width - 86, row_y + 62), radius=18, fill=panel if idx else panel2)
        draw.text((108, row_y + 18), row, font=body, fill=text)
        row_y += 78

    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _draw_metric_grid(draw, metrics, *, origin, size, gap, label_font, value_font, label_color, value_color, fill):
    x0, y0 = origin
    cell_w, cell_h = size
    gap_x, gap_y = gap
    for idx, (label, value) in enumerate(metrics):
        col = idx % 2
        row = idx // 2
        x = x0 + col * (cell_w + gap_x)
        y = y0 + row * (cell_h + gap_y)
        draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=20, fill=fill)
        draw.text((x + 16, y + 10), label, font=label_font, fill=label_color)
        draw.text((x + 16, y + 34), value, font=value_font, fill=value_color)


def _load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _draw_vertical_gradient(draw, width: int, height: int, top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> None:
    for y in range(height):
        mix = y / max(1, height - 1)
        color = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * mix) for i in range(3))
        draw.line((0, y, width, y), fill=color)


def _blend(base: tuple[int, int, int], accent: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(base[i] + (accent[i] - base[i]) * amount) for i in range(3))


def _rgb_to_hex(value: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % value


def _c_to_f(value_c: float) -> float:
    return (value_c * 9.0 / 5.0) + 32.0


def _kmh_to_mph(value_kmh: float) -> float:
    return value_kmh * 0.621371


def _paste_icon(image, icon_name: str, position: tuple[int, int], size: int) -> None:
    icon = _load_icon(icon_name, size)
    if icon is None:
        return
    image.paste(icon, position, icon)


@lru_cache(maxsize=128)
def _load_icon(icon_name: str, size: int):
    try:
        import cairosvg
        from PIL import Image
    except ImportError:
        return None

    icon_path = Path(__file__).resolve().parent.parent / "data" / "weather-icons" / f"{icon_name}.svg"
    if not icon_path.exists():
        return None
    png_bytes = cairosvg.svg2png(url=str(icon_path), output_width=size, output_height=size)
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")
