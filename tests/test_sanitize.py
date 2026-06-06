import unittest
from unittest.mock import AsyncMock, MagicMock
from convertcord.sanitize import SanitizePlatforms, contains_url, extract_and_sanitize

class AsyncContextManagerMock:
    def __init__(self, return_value):
        self.return_value = return_value
    async def __aenter__(self):
        return self.return_value
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class SanitizeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session = MagicMock()

    def test_contains_supported_url(self) -> None:
        self.assertTrue(contains_url("https://clips.twitch.tv/FancyClipSlug"))

    async def test_twitch_clip_outputs_markdown(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value='<meta property="og:title" content="TestUser - Clip Title">')
        self.session.get.return_value = AsyncContextManagerMock(mock_resp)

        results = await extract_and_sanitize("https://clips.twitch.tv/FancyClipSlug", self.session)
        self.assertEqual(
            results,
            ["[@TestUser via Twitch](https://fxtwitch.seria.moe/clip/FancyClipSlug)"],
        )

    async def test_twitch_user_clip_outputs_markdown(self) -> None:
        results = await extract_and_sanitize("https://www.twitch.tv/testuser/clip/FancyClipSlug", self.session)
        self.assertEqual(
            results,
            ["[@testuser via Twitch](https://fxtwitch.seria.moe/testuser/clip/FancyClipSlug)"],
        )

    async def test_spoiler_state_is_preserved(self) -> None:
        # Mock for Twitch clip username lookup
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value='<meta property="og:title" content="TestUser - Clip Title">')
        self.session.get.return_value = AsyncContextManagerMock(mock_resp)

        results = await extract_and_sanitize("|| https://clips.twitch.tv/FancyClipSlug ||", self.session)
        self.assertEqual(
            results,
            ["|| [@TestUser via Twitch](https://fxtwitch.seria.moe/clip/FancyClipSlug) ||"],
        )

    async def test_markdown_link_drops_trailing_parenthesis(self) -> None:
        # Mock for Twitch clip username lookup
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value='<meta property="og:title" content="TestUser - Clip Title">')
        self.session.get.return_value = AsyncContextManagerMock(mock_resp)

        results = await extract_and_sanitize("[clip](https://clips.twitch.tv/FancyClipSlug)", self.session)
        self.assertEqual(
            results,
            ["[@TestUser via Twitch](https://fxtwitch.seria.moe/clip/FancyClipSlug)"],
        )

    async def test_twitch_can_be_disabled(self) -> None:
        platforms = SanitizePlatforms(twitch=False)
        self.assertFalse(contains_url("https://clips.twitch.tv/FancyClipSlug", platforms))
        results = await extract_and_sanitize("https://clips.twitch.tv/FancyClipSlug", self.session, platforms)
        self.assertEqual(results, [])

    async def test_other_platforms_still_work_when_twitch_disabled(self) -> None:
        platforms = SanitizePlatforms(twitch=False)
        self.assertTrue(contains_url("https://x.com/test/status/123", platforms))
        results = await extract_and_sanitize("https://x.com/test/status/123", self.session, platforms)
        self.assertEqual(
            results,
            ["[@test via Twitter](https://fxtwitter.com/test/status/123)"],
        )

    async def test_tiktok_short_link_resolves_username(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 302
        mock_resp.headers = {"Location": "https://www.tiktok.com/@realuser/video/789"}
        self.session.get.return_value = AsyncContextManagerMock(mock_resp)

        results = await extract_and_sanitize("https://vm.tiktok.com/ABC/", self.session)
        self.assertEqual(
            results,
            ["[@realuser via TikTok](https://vm.kktiktok.com/ABC/)"],
        )

    async def test_instagram_reel_detection(self) -> None:
        results = await extract_and_sanitize("https://www.instagram.com/reels/XYZ/", self.session)
        self.assertEqual(
            results,
            ["[Reel via Instagram](https://www.kkinstagram.com/reels/XYZ/)"],
        )

if __name__ == "__main__":
    unittest.main()
