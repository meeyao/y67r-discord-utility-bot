import unittest

from convertcord.sanitize import SanitizePlatforms, contains_url, extract_and_sanitize


class SanitizeTests(unittest.TestCase):
    def test_contains_supported_url(self) -> None:
        self.assertTrue(contains_url("https://clips.twitch.tv/FancyClipSlug"))

    def test_twitch_clip_outputs_raw_fix_url(self) -> None:
        self.assertEqual(
            extract_and_sanitize("https://clips.twitch.tv/FancyClipSlug"),
            ["https://fxtwitch.seria.moe/clip/FancyClipSlug"],
        )

    def test_twitch_user_clip_outputs_raw_fix_url(self) -> None:
        self.assertEqual(
            extract_and_sanitize("https://www.twitch.tv/testuser/clip/FancyClipSlug"),
            ["https://fxtwitch.seria.moe/testuser/clip/FancyClipSlug"],
        )

    def test_spoiler_state_is_preserved(self) -> None:
        self.assertEqual(
            extract_and_sanitize("|| https://clips.twitch.tv/FancyClipSlug ||"),
            ["|| https://fxtwitch.seria.moe/clip/FancyClipSlug ||"],
        )

    def test_markdown_link_drops_trailing_parenthesis(self) -> None:
        self.assertEqual(
            extract_and_sanitize("[clip](https://clips.twitch.tv/FancyClipSlug)"),
            ["https://fxtwitch.seria.moe/clip/FancyClipSlug"],
        )

    def test_twitch_can_be_disabled(self) -> None:
        platforms = SanitizePlatforms(twitch=False)
        self.assertFalse(contains_url("https://clips.twitch.tv/FancyClipSlug", platforms))
        self.assertEqual(
            extract_and_sanitize("https://clips.twitch.tv/FancyClipSlug", platforms),
            [],
        )

    def test_other_platforms_still_work_when_twitch_disabled(self) -> None:
        platforms = SanitizePlatforms(twitch=False)
        self.assertTrue(contains_url("https://x.com/test/status/123", platforms))
        self.assertEqual(
            extract_and_sanitize("https://x.com/test/status/123", platforms),
            ["https://fxtwitter.com/test/status/123"],
        )


if __name__ == "__main__":
    unittest.main()
