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
    night_mode = "night" in condition_icon
    palette = _build_palette(accent_rgb, night_mode)

    image = Image.new("RGBA", (width, height), palette["sky_top"])
    draw = ImageDraw.Draw(image)
    _draw_vertical_gradient(draw, width, height, palette["sky_top"], palette["sky_bottom"])
    _draw_atmosphere(image, palette, night_mode)

    shell = (42, 36, width - 42, height - 36)
    _draw_shell(image, shell, palette)

    text = palette["text"]
    muted = palette["muted"]
    soft = palette["soft"]
    warm = palette["warm"]

    label_font = _load_font(22)
    body_font = _load_font(28)
    body_bold = _load_font(30, bold=True)
    title_font = _load_font(34, bold=True)
    hero_label = _load_font(30, bold=True)
    hero_temp = _load_font(116, bold=True)
    hero_meta = _load_font(36)
    chip_label = _load_font(20)
    chip_value = _load_font(27, bold=True)
    small_font = _load_font(18)
    hourly_temp = _load_font(34, bold=True)
    forecast_temp = _load_font(28, bold=True)

    hero_box = (76, 66, 1060, 420)
    _draw_glass_panel(image, hero_box, radius=42, fill=palette["glass"], outline=palette["line"], shadow=palette["shadow"])
    _draw_glass_panel(
        image,
        (1068, 66, 1424, 972),
        radius=40,
        fill=palette["glass_strong"],
        outline=palette["line"],
        shadow=palette["shadow"],
    )
    _draw_glass_panel(
        image,
        (76, 442, 1060, 972),
        radius=34,
        fill=palette["glass_soft"],
        outline=palette["line_soft"],
        shadow=palette["shadow"],
    )

    _draw_top_band(image, (96, 84, 1028, 126), palette)
    draw = ImageDraw.Draw(image)
    _draw_fitted_text(draw, (112, 94, 660, 130), location_display, hero_label, text)
    draw.text((112, 142), condition, font=hero_meta, fill=muted)
    draw.text((112, 194), f"{round(temperature_c):.0f}°C", font=hero_temp, fill=text)
    draw.text((430, 252), f"/ {round(_c_to_f(temperature_c)):.0f}°F", font=_load_font(58, bold=True), fill=soft)
    if feels_c is not None:
        draw.text(
            (118, 328),
            f"Feels like {round(feels_c):.0f}°C / {round(_c_to_f(feels_c)):.0f}°F",
            font=body_font,
            fill=warm,
        )
    if observed_text:
        draw.text((118, 368), observed_text, font=label_font, fill=soft)

    _draw_hero_orb(image, (842, 108, 1016, 282), palette, night_mode)
    _paste_icon(image, condition_icon, (760, 120), 224)

    metric_cards = [
        ("Humidity", f"{humidity}%" if humidity is not None else None),
        ("Wind", _compact_wind(wind_direction, wind_kmh)),
        ("UV", uv_text),
        ("AQI", aqi_text),
    ]
    _draw_metric_chips(
        image,
        [item for item in metric_cards if item[1]],
        origin=(112, 438),
        columns=4,
        cell_size=(222, 78),
        gap=(18, 0),
        label_font=chip_label,
        value_font=chip_value,
        label_color=soft,
        value_color=text,
        palette=palette,
    )

    section_draw = ImageDraw.Draw(image)
    section_draw.text((108, 536), "Right now", font=title_font, fill=text)
    section_draw.text((108, 816), "Hourly outlook", font=title_font, fill=text)

    detail_panels = [
        (
            "Air",
            [
                _detail_line("Humidity", f"{humidity}%"),
                _detail_line("Dew point", _temp_pair_compact(dew_point_c)),
                _detail_line("Pressure", f"{pressure_hpa:.0f} hPa" if pressure_hpa is not None else None),
            ],
        ),
        (
            "Sky",
            [
                _detail_line("Cloud cover", f"{cloud_cover}%"),
                _detail_line("Visibility", visibility_text),
                _detail_line("Precip", f"{precip_probability}%"),
            ],
        ),
        (
            "Wind",
            [
                _detail_line("Flow", _wind_full(wind_direction, wind_kmh)),
                _detail_line("Gusts", _speed_pair(gust_kmh)),
                _detail_line("Sun cycle", _sun_cycle(sunrise, sunset)),
            ],
        ),
    ]

    info_box = (100, 584, 1034, 680)
    _draw_info_ribbon(image, info_box, palette)
    ribbon_draw = ImageDraw.Draw(image)
    ribbon_draw.text((124, 612), f"{round(temperature_c):.0f}°C / {round(_c_to_f(temperature_c)):.0f}°F", font=body_bold, fill=text)
    ribbon_draw.text((404, 612), f"{condition} • {_value_or_dash(observed_text)}", font=body_font, fill=muted)

    panel_x = 100
    for title, lines in detail_panels:
        box = (panel_x, 704, panel_x + 290, 804)
        _draw_glass_panel(image, box, radius=28, fill=palette["glass_alt"], outline=palette["line_soft"], shadow=None)
        panel_draw = ImageDraw.Draw(image)
        panel_draw.text((box[0] + 20, box[1] + 18), title, font=body_bold, fill=text)
        y = box[1] + 56
        for line in [entry for entry in lines if entry]:
            panel_draw.text((box[0] + 20, y), line, font=label_font, fill=muted)
            y += 26
        panel_x += 306

    hourly_y = 866
    hourly_x = 100
    for idx, card in enumerate(hourly_cards[:5]):
        box = (hourly_x, hourly_y, hourly_x + 176, hourly_y + 138)
        _draw_glass_panel(
            image,
            box,
            radius=26,
            fill=palette["glass_strong"] if idx == 0 else palette["glass_alt"],
            outline=palette["line_soft"],
            shadow=None,
        )
        hour_draw = ImageDraw.Draw(image)
        hour_draw.text((box[0] + 18, box[1] + 18), str(card.get("label", "--")), font=chip_label, fill=soft)
        _paste_icon(image, str(card.get("icon", "cloudy")), (box[0] + 14, box[1] + 44), 56)
        hour_draw.text((box[0] + 82, box[1] + 54), str(card.get("temp", "--")), font=hourly_temp, fill=text)
        if card.get("precip"):
            hour_draw.text((box[0] + 18, box[1] + 104), str(card["precip"]), font=small_font, fill=muted)
        if card.get("wind"):
            hour_draw.text((box[0] + 18, box[1] + 122), str(card["wind"]), font=small_font, fill=soft)
        hourly_x += 188

    forecast_draw = ImageDraw.Draw(image)
    forecast_draw.text((1092, 96), "Forecast", font=title_font, fill=text)
    forecast_draw.text((1092, 136), "Next few days", font=label_font, fill=soft)

    daily_y = 180
    cards = daily_cards[:5]
    if not cards and forecast_rows:
        cards = [{"label": "Forecast", "summary": row, "icon": "cloudy", "temps": "--"} for row in forecast_rows[:5]]
    for idx, card in enumerate(cards):
        box = (1088, daily_y, 1406, daily_y + 136)
        _draw_glass_panel(
            image,
            box,
            radius=28,
            fill=palette["glass_alt"] if idx else palette["glass_strong"],
            outline=palette["line_soft"],
            shadow=None,
        )
        day_draw = ImageDraw.Draw(image)
        day_draw.text((box[0] + 22, box[1] + 16), str(card.get("label", "--")), font=body_bold, fill=text)
        summary = str(card.get("summary", "Current conditions"))
        _draw_fitted_text(day_draw, (box[0] + 22, box[1] + 52, box[0] + 214, box[1] + 82), summary, chip_label, muted)
        _paste_icon(image, str(card.get("icon", "cloudy")), (box[0] + 214, box[1] + 34), 74)
        day_draw.text((box[0] + 22, box[1] + 92), str(card.get("temps", "--")), font=forecast_temp, fill=warm)
        detail = str(card.get("detail", "") or "")
        if detail:
            _draw_fitted_text(day_draw, (box[0] + 22, box[1] + 120, box[0] + 170, box[1] + 132), detail, small_font, soft)
        daily_y += 150

    footer_box = (1088, 930, 1406, 972)
    _draw_glass_panel(image, footer_box, radius=20, fill=palette["glass_alt"], outline=palette["line_soft"], shadow=None)
    footer_draw = ImageDraw.Draw(image)
    footer_text = forecast_rows[0] if forecast_rows else f"{condition} • {_temp_pair_compact(temperature_c)}"
    _draw_fitted_text(footer_draw, (1106, 942, 1388, 966), footer_text, small_font, muted)

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _build_palette(accent_rgb: tuple[int, int, int], night_mode: bool) -> Dict[str, object]:
    if night_mode:
        sky_top = _blend((10, 22, 52), accent_rgb, 0.18)
        sky_bottom = _blend((5, 12, 28), accent_rgb, 0.08)
        glass = (19, 31, 67, 160)
        glass_soft = (16, 28, 60, 144)
        glass_strong = (26, 42, 84, 184)
        glass_alt = (20, 36, 76, 170)
        line = (188, 221, 255, 86)
        line_soft = (170, 210, 255, 52)
        shadow = (2, 8, 20, 140)
        warm = "#ffe4a6"
        orb = _blend((241, 245, 255), accent_rgb, 0.18)
    else:
        sky_top = _blend((66, 126, 230), accent_rgb, 0.20)
        sky_bottom = _blend((17, 76, 175), accent_rgb, 0.12)
        glass = (20, 62, 143, 152)
        glass_soft = (18, 58, 136, 134)
        glass_strong = (28, 76, 164, 176)
        glass_alt = (24, 70, 154, 160)
        line = (232, 245, 255, 88)
        line_soft = (218, 237, 255, 54)
        shadow = (8, 24, 55, 100)
        warm = "#ffe6b0"
        orb = _blend((255, 244, 198), accent_rgb, 0.24)
    return {
        "sky_top": sky_top,
        "sky_bottom": sky_bottom,
        "glass": glass,
        "glass_soft": glass_soft,
        "glass_strong": glass_strong,
        "glass_alt": glass_alt,
        "line": line,
        "line_soft": line_soft,
        "shadow": shadow,
        "text": "#f7fbff",
        "muted": "#dceaff",
        "soft": "#aac9ff",
        "warm": warm,
        "orb": orb,
        "accent": accent_rgb,
    }


def _draw_shell(image, box, palette: Dict[str, object]) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (box[0], box[1] + 12, box[2], box[3] + 12),
        radius=42,
        fill=palette["shadow"],
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    overlay.alpha_composite(shadow)

    shell_draw = ImageDraw.Draw(overlay)
    shell_draw.rounded_rectangle(box, radius=42, fill=(10, 22, 48, 44), outline=palette["line"], width=2)
    shell_draw.rounded_rectangle(
        (box[0] + 10, box[1] + 10, box[2] - 10, box[3] - 10),
        radius=34,
        outline=palette["line_soft"],
        width=1,
    )
    image.alpha_composite(overlay)


def _draw_atmosphere(image, palette: Dict[str, object], night_mode: bool) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    _draw_radial_glow(overlay, (280, 140), 320, (*palette["orb"], 150))
    _draw_radial_glow(overlay, (1210, 120), 220, (*palette["accent"], 92))
    _draw_radial_glow(overlay, (780, 640), 420, (*palette["accent"], 60))

    shape = ImageDraw.Draw(overlay)
    shape.ellipse((1120, 54, 1340, 274), fill=(*palette["orb"], 56))
    shape.ellipse((88, 742, 480, 1120), fill=(*palette["accent"], 32))
    shape.ellipse((948, 726, 1560, 1260), fill=(*palette["accent"], 22))

    mist = Image.new("RGBA", image.size, (0, 0, 0, 0))
    mist_draw = ImageDraw.Draw(mist)
    mist_color = (255, 255, 255, 38 if night_mode else 56)
    mist_draw.ellipse((150, 250, 760, 650), fill=mist_color)
    mist_draw.ellipse((350, 210, 1030, 620), fill=mist_color)
    mist_draw.ellipse((600, 250, 1180, 660), fill=mist_color)
    overlay.alpha_composite(mist.filter(ImageFilter.GaussianBlur(34)))

    if night_mode:
        star_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        star_draw = ImageDraw.Draw(star_layer)
        stars = [
            (164, 92), (242, 138), (390, 118), (488, 70), (660, 134),
            (904, 92), (1008, 144), (1188, 88), (1310, 150), (1380, 108),
        ]
        for x, y in stars:
            star_draw.ellipse((x, y, x + 4, y + 4), fill=(255, 255, 255, 160))
        overlay.alpha_composite(star_layer.filter(ImageFilter.GaussianBlur(1)))

    image.alpha_composite(overlay)


def _draw_top_band(image, box, palette: Dict[str, object]) -> None:
    from PIL import Image, ImageDraw

    band = Image.new("RGBA", image.size, (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    band_draw.rounded_rectangle(box, radius=21, fill=(*palette["accent"], 44), outline=palette["line_soft"])
    image.alpha_composite(band)


def _draw_hero_orb(image, box, palette: Dict[str, object], night_mode: bool) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    fill = (*palette["orb"], 170 if night_mode else 196)
    draw.ellipse(box, fill=fill)
    draw.ellipse((box[0] + 24, box[1] + 24, box[2] - 52, box[3] - 52), fill=(255, 255, 255, 34))
    draw.ellipse((box[0] + 120, box[1] + 28, box[0] + 158, box[1] + 66), fill=(255, 255, 255, 95))
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(2)))


def _draw_metric_chips(
    image,
    metrics,
    *,
    origin,
    columns: int,
    cell_size,
    gap,
    label_font,
    value_font,
    label_color,
    value_color,
    palette: Dict[str, object],
) -> None:
    from PIL import ImageDraw

    x0, y0 = origin
    cell_w, cell_h = cell_size
    gap_x, gap_y = gap
    for idx, (label, value) in enumerate(metrics):
        col = idx % columns
        row = idx // columns
        box = (
            x0 + col * (cell_w + gap_x),
            y0 + row * (cell_h + gap_y),
            x0 + col * (cell_w + gap_x) + cell_w,
            y0 + row * (cell_h + gap_y) + cell_h,
        )
        _draw_glass_panel(image, box, radius=24, fill=palette["glass_alt"], outline=palette["line_soft"], shadow=None)
        draw = ImageDraw.Draw(image)
        draw.text((box[0] + 16, box[1] + 16), label, font=label_font, fill=label_color)
        _draw_fitted_text(draw, (box[0] + 16, box[1] + 42, box[2] - 16, box[3] - 14), value, value_font, value_color)


def _draw_info_ribbon(image, box, palette: Dict[str, object]) -> None:
    _draw_glass_panel(image, box, radius=26, fill=palette["glass_alt"], outline=palette["line_soft"], shadow=None)


def _draw_glass_panel(image, box, *, radius: int, fill, outline, shadow) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    if shadow is not None:
        shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        shadow_draw.rounded_rectangle(
            (box[0], box[1] + 8, box[2], box[3] + 8),
            radius=radius,
            fill=shadow,
        )
        layer.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(18)))

    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)
    draw.line((box[0] + 20, box[1] + 20, box[2] - 20, box[1] + 20), fill=(255, 255, 255, 18), width=2)
    image.alpha_composite(layer)


def _draw_radial_glow(image, center, radius: int, color) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    size = radius * 2
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((0, 0, size - 1, size - 1), fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(radius / 3))
    image.alpha_composite(glow, dest=(center[0] - radius, center[1] - radius))


def _draw_fitted_text(draw, box, text: str, font, fill) -> None:
    if not text:
        return
    current = font
    left, top, right, bottom = box
    text_value = text
    while True:
        bbox = draw.textbbox((0, 0), text_value, font=current)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width <= (right - left) and height <= (bottom - top):
            draw.text((left, top), text_value, font=current, fill=fill)
            return
        if getattr(current, "size", 0) > 16:
            current = _load_font(current.size - 2, bold=_is_bold_font(current))
            continue
        while len(text_value) > 3:
            text_value = text_value[:-2].rstrip() + "…"
            bbox = draw.textbbox((0, 0), text_value, font=current)
            if bbox[2] - bbox[0] <= (right - left):
                draw.text((left, top), text_value, font=current, fill=fill)
                return
        draw.text((left, top), text_value, font=current, fill=fill)
        return


def _is_bold_font(font) -> bool:
    name = getattr(font, "path", "")
    return "Bold" in str(name)


def _load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        "/usr/share/fonts/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Medium.ttf" if bold else "/usr/share/fonts/noto/NotoSans-Regular.ttf",
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


def _compact_wind(direction: Optional[str], wind_kmh: Optional[float]) -> Optional[str]:
    if wind_kmh is None:
        return None
    prefix = f"{direction} " if direction else ""
    return f"{prefix}{wind_kmh:.0f} km/h"


def _wind_full(direction: Optional[str], wind_kmh: Optional[float]) -> Optional[str]:
    if wind_kmh is None:
        return None
    prefix = f"{direction} " if direction else ""
    return f"{prefix}{wind_kmh:.1f} km/h ({_kmh_to_mph(wind_kmh):.1f} mph)"


def _speed_pair(speed_kmh: Optional[float]) -> Optional[str]:
    if speed_kmh is None:
        return None
    return f"{speed_kmh:.1f} km/h ({_kmh_to_mph(speed_kmh):.1f} mph)"


def _temp_pair_compact(value_c: Optional[float]) -> Optional[str]:
    if value_c is None:
        return None
    return f"{value_c:.0f}°C / {_c_to_f(value_c):.0f}°F"


def _detail_line(label: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return f"{label}: {value}"


def _sun_cycle(sunrise: Optional[str], sunset: Optional[str]) -> Optional[str]:
    if sunrise and sunset:
        return f"{sunrise} / {sunset}"
    return sunrise or sunset


def _value_or_dash(value: Optional[str]) -> str:
    return value or "No recent observation"
