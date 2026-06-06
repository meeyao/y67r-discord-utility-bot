import os
import unittest
from unittest.mock import patch

from convertcord.service import _urban_api_base_url


class ServiceTests(unittest.TestCase):
    def test_urban_api_base_url_defaults_to_public_api(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _urban_api_base_url(),
                "https://unofficialurbandictionaryapi.com/api",
            )

    def test_urban_api_base_url_appends_api_suffix_when_missing(self) -> None:
        with patch.dict(
            os.environ,
            {"CONVERTCORD_URBAN_API_URL": "http://urban-api:8080"},
            clear=True,
        ):
            self.assertEqual(_urban_api_base_url(), "http://urban-api:8080/api")

    def test_urban_api_base_url_keeps_existing_api_suffix(self) -> None:
        with patch.dict(
            os.environ,
            {"CONVERTCORD_URBAN_API_URL": "http://urban-api:8080/api/"},
            clear=True,
        ):
            self.assertEqual(_urban_api_base_url(), "http://urban-api:8080/api")


if __name__ == "__main__":
    unittest.main()
