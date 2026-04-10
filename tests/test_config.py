import tempfile
import textwrap
import unittest

from convertcord.config import load_config, update_sanitize_config


class ConfigTests(unittest.TestCase):
    def test_update_sanitize_config_persists_change(self) -> None:
        with tempfile.NamedTemporaryFile("w+", suffix=".yaml") as handle:
            handle.write(
                textwrap.dedent(
                    """
                    discord:
                      alias: "$convert"
                    sanitize:
                      instagram: true
                      reddit: true
                      tiktok: true
                      twitch: true
                      twitter: true
                    """
                ).strip()
            )
            handle.flush()

            update_sanitize_config(handle.name, twitch=False)
            config = load_config(handle.name)

            self.assertFalse(config.sanitize.twitch)
            self.assertTrue(config.sanitize.twitter)


if __name__ == "__main__":
    unittest.main()
