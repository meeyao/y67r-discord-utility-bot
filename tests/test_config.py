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

    def test_load_blacklist_user_ids(self) -> None:
        with tempfile.NamedTemporaryFile("w+", suffix=".yaml") as handle:
            handle.write(
                textwrap.dedent(
                    """
                    discord:
                      alias: "$convert"
                    blacklist:
                      instagram_user_ids:
                        - 529128711258374144
                    """
                ).strip()
            )
            handle.flush()

            config = load_config(handle.name)

            self.assertEqual(config.blacklist.instagram_user_ids, [529128711258374144])

    def test_load_blacklist_instagram_domains(self) -> None:
        with tempfile.NamedTemporaryFile("w+", suffix=".yaml") as handle:
            handle.write(
                textwrap.dedent(
                    """
                    discord:
                      alias: "$convert"
                    blacklist:
                      instagram_domains:
                        - Example-Short.xyz
                    """
                ).strip()
            )
            handle.flush()

            config = load_config(handle.name)

            self.assertEqual(config.blacklist.instagram_domains, ["example-short.xyz"])


if __name__ == "__main__":
    unittest.main()
