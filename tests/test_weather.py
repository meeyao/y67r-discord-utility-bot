import unittest
import tempfile

from convertcord import service
from convertcord.service import (
    _describe_weather_code,
    _format_daily_forecast,
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
        self.assertIn("**Today**: Overcast", forecast)
        self.assertIn("**Fri**: Rain", forecast)
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
        self.assertAlmostEqual(index["AUH"]["lat"], 24.440966)
        self.assertAlmostEqual(index["AUH"]["lon"], 54.649237)


if __name__ == "__main__":
    unittest.main()
