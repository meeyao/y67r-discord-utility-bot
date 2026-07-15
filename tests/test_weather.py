import asyncio
import unittest
import tempfile
from unittest.mock import Mock

from convertcord import service
from convertcord.service import (
    ConversionError,
    ConvertService,
    _describe_weather_code,
    _format_aqi,
    _format_daily_forecast,
    _format_temp_pair_compact,
    _format_visibility,
    _format_wind_speed,
    _format_uv_index,
    _load_airport_code_index,
    _weather_color,
)


class WeatherFormattingTests(unittest.TestCase):
    def test_describe_weather_code_handles_day_and_night_clear(self) -> None:
        self.assertEqual(_describe_weather_code(0, True), "Clear sky")
        self.assertEqual(_describe_weather_code(0, False), "Clear night")

    def test_format_daily_forecast_builds_three_day_summary(self) -> None:
        forecast = _format_daily_forecast(
            {
                "time": ["2026-04-23", "2026-04-24", "2026-04-25"],
                "weather_code": [3, 61, 95],
                "temperature_2m_max": [22.0, 20.0, 18.0],
                "temperature_2m_min": [15.0, 14.0, 12.0],
                "precipitation_probability_max": [10, 60, 80],
            },
            "UTC",
        )

        self.assertIsNotNone(forecast)
        assert forecast is not None
        self.assertIn("**Today**", forecast)
        self.assertIn("Overcast", forecast)
        self.assertIn("**Fri**", forecast)
        self.assertIn("Rain", forecast)
        self.assertIn("Rain 80%", forecast)

    def test_weather_color_uses_expected_palette(self) -> None:
        self.assertEqual(_weather_color(95, True), service.discord.Colour.orange())
        self.assertEqual(_weather_color(61, True), service.discord.Colour.blue())
        self.assertEqual(_weather_color(0, False), service.discord.Colour.dark_blue())

    def test_airport_code_index_prefers_real_airport_match(self) -> None:
        with tempfile.NamedTemporaryFile("w+", suffix=".csv") as handle:
            handle.write(
                "\n".join(
                    [
                        "ident,type,name,elevation_ft,continent,iso_country,iso_region,municipality,icao_code,iata_code,gps_code,local_code,coordinates",
                        "KAUH,small_airport,Aurora Municipal Al Potter Field,1803,NA,US,US-NE,Aurora,,,KAUH,AUH,\"40.8941, -97.994598\"",
                        "OMAA,large_airport,Zayed International Airport,88,AS,AE,AE-AZ,Abu Dhabi,OMAA,AUH,OMAA,,\"24.440966, 54.649237\"",
                    ]
                )
            )
            handle.flush()

            index = _load_airport_code_index(handle.name)

        self.assertIn("AUH", index)
        self.assertEqual(index["AUH"]["display"], "Abu Dhabi (AUH), AE")
        self.assertEqual(index["AUH"]["country_code"], "AE")
        self.assertAlmostEqual(index["AUH"]["lat"], 24.440966)
        self.assertAlmostEqual(index["AUH"]["lon"], 54.649237)

    def test_weather_unit_system_uses_country_code(self) -> None:
        weather_service = ConvertService(
            alias="!weather",
            measurement_converter=Mock(),
            temperature_converter=Mock(),
            currency_converter=Mock(),
            http_session=Mock(),
        )

        self.assertEqual(weather_service._weather_unit_system({"country_code": "AE"}), "metric")
        self.assertEqual(weather_service._weather_unit_system({"country_code": "US"}), "imperial")

    def test_handle_returns_user_error_when_weather_raises_conversion_error(self) -> None:
        class FailingWeatherService(ConvertService):
            async def _handle_weather(self, args):
                raise ConversionError("Unable to fetch weather right now.")

        weather_service = FailingWeatherService(
            alias="!weather",
            measurement_converter=Mock(),
            temperature_converter=Mock(),
            currency_converter=Mock(),
            http_session=Mock(),
        )

        response = asyncio.run(weather_service.handle("AUH", invoked_alias="!weather"))

        self.assertTrue(response.error)
        self.assertEqual(response.content, "Unable to fetch weather right now.")

    def test_parse_weather_request_supports_7d_day_offset(self) -> None:
        weather_service = ConvertService(
            alias="!weather",
            measurement_converter=Mock(),
            temperature_converter=Mock(),
            currency_converter=Mock(),
            http_session=Mock(),
        )

        location, view = weather_service._parse_weather_request(["MCN", "7d"])

        self.assertEqual(location, "MCN")
        self.assertEqual(view, "7d")

    def test_uv_and_aqi_labels_are_human_readable(self) -> None:
        self.assertEqual(_format_uv_index(7.2), "7 High")
        self.assertEqual(_format_aqi(82), "82 Moderate")

    def test_weather_unit_helpers_prioritize_metric_by_default(self) -> None:
        self.assertEqual(_format_temp_pair_compact(20, "metric"), "20°C / 68°F")
        self.assertEqual(_format_wind_speed(10, "metric"), "10.0 km/h (6.2 mph)")
        self.assertEqual(_format_visibility(10000, "metric"), "10 km (6.2 mi)")

    def test_weather_unit_helpers_prioritize_imperial_when_requested(self) -> None:
        self.assertEqual(_format_temp_pair_compact(20, "imperial"), "68°F / 20°C")
        self.assertEqual(_format_wind_speed(10, "imperial"), "6.2 mph (10.0 km/h)")
        self.assertEqual(_format_visibility(10000, "imperial"), "6.2 mi (10.0 km)")


if __name__ == "__main__":
    unittest.main()
