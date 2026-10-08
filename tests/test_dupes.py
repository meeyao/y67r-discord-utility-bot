import unittest
import os
from convertcord.dupes import DupeChecker

class DupeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_file = "data/test_dupes.db"
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
        self.checker = DupeChecker(self.db_file)

    async def asyncTearDown(self):
        if os.path.exists(self.db_file):
            os.remove(self.db_file)

    def test_twitter_normalization(self):
        test_cases = [
            ("https://twitter.com/user/status/123", "https://twitter.com/i/status/123"),
            ("https://x.com/user/status/123", "https://twitter.com/i/status/123"),
            ("https://fxtwitter.com/user/status/123", "https://twitter.com/i/status/123"),
            ("https://vxtwitter.com/user/status/123", "https://twitter.com/i/status/123"),
            ("https://fixupx.com/user/status/123", "https://twitter.com/i/status/123"),
            ("https://twitter.com/user/status/123?s=20", "https://twitter.com/i/status/123"),
            ("https://X.COM/User/Status/123", "https://twitter.com/i/status/123"),
            # /i/status/ path variant (same tweet, different username segment)
            ("https://x.com/i/status/2065594410008793412", "https://twitter.com/i/status/2065594410008793412"),
            ("https://twitter.com/i/status/2065594410008793412", "https://twitter.com/i/status/2065594410008793412"),
            # Trailing ? that URL_RE might capture from surrounding text
            ("https://x.com/i/status/2065594410008793412?", "https://twitter.com/i/status/2065594410008793412"),
            # Trailing period from sentence ending
            ("https://twitter.com/user/status/123.", "https://twitter.com/i/status/123"),
            ("https://x.com/user/status/123.", "https://twitter.com/i/status/123"),
        ]
        for input_url, expected in test_cases:
            self.assertEqual(self.checker.normalize_url(input_url), expected)

    def test_general_normalization(self):
        test_cases = [
            ("https://www.instagram.com/p/ABC/", "https://instagram.com/p/abc"),
            ("https://instagram.com/p/ABC/?igsh=1", "https://instagram.com/p/abc"),
            ("https://vxinstagram.com/p/ABC/", "https://instagram.com/p/abc"),
            ("https://kkinstagram.com/p/ABC/", "https://instagram.com/p/abc"),
            ("https://www.reddit.com/r/test", "https://reddit.com/r/test"),
            ("https://old.reddit.com/r/test", "https://reddit.com/r/test"),
            ("https://new.reddit.com/r/test", "https://reddit.com/r/test"),
            ("https://np.reddit.com/r/test", "https://reddit.com/r/test"),
            ("https://rxddit.com/r/test", "https://reddit.com/r/test"),
            ("https://www.tiktok.com/@user/video/123", "https://tiktok.com/@user/video/123"),
            ("https://kktiktok.com/@user/video/123", "https://tiktok.com/@user/video/123"),
        ]
        for input_url, expected in test_cases:
            self.assertEqual(self.checker.normalize_url(input_url), expected)

    def test_youtube_normalization_preserves_video_identity(self):
        test_cases = [
            ("https://www.youtube.com/watch?v=VIDEO_A", "https://youtube.com/watch?v=VIDEO_A"),
            ("https://youtube.com/watch?v=VIDEO_B&t=10s", "https://youtube.com/watch?v=VIDEO_B"),
            ("https://youtu.be/VIDEO_A?si=abc", "https://youtube.com/watch?v=VIDEO_A"),
            ("https://www.youtube.com/shorts/SHORT_A", "https://youtube.com/watch?v=SHORT_A"),
            ("https://www.youtube.com/embed/VIDEO_A", "https://youtube.com/watch?v=VIDEO_A"),
        ]
        for input_url, expected in test_cases:
            self.assertEqual(self.checker.normalize_url(input_url), expected)

    async def test_dupe_detection(self):
        guild_id = 1
        channel_id = 1
        msg_id1 = 101
        content1 = "Check this: https://twitter.com/user/status/123"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id1, content1))

        msg_id2 = 102
        content2 = "Duplicate: https://x.com/user/status/123"
        result = await self.checker.check_and_add(guild_id, channel_id, msg_id2, content2)
        self.assertEqual(result, (channel_id, msg_id1))

        # Same channel, different guild should NOT trigger dupe
        msg_id3 = 103
        content3 = "Different guild: https://twitter.com/user/status/123"
        self.assertIsNone(await self.checker.check_and_add(2, channel_id, msg_id3, content3))

    async def test_dupe_i_status_path(self):
        """/i/status/ and /username/status/ for the same tweet ID should be dupes."""
        guild_id = 1
        channel_id = 1
        msg_id1 = 701
        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id1,
                "https://x.com/usmnt/status/2065594410008793412",
            )
        )
        msg_id2 = 702
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id2,
                "https://x.com/i/status/2065594410008793412 ?",
            ),
            (channel_id, msg_id1),
        )

    async def test_dupe_tracker_in_text(self):
        """URL with tracking params embedded in a sentence should dupe a clean URL."""
        guild_id = 1
        channel_id = 1
        msg_id1 = 801
        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id1,
                "here: https://x.com/usmnt/status/2065594410008793412",
            )
        )
        msg_id2 = 802
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id2,
                "https://x.com/usmnt/status/2065594410008793412?s=46&t=d1VIndVDTFDSYTO1fhiXOg what happening in LA??",
            ),
            (channel_id, msg_id1),
        )

    async def test_dupe_trailing_question_mark(self):
        """URL with trailing ? captured by URL_RE should still dupe."""
        guild_id = 1
        channel_id = 1
        msg_id1 = 901
        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id1,
                "https://x.com/i/status/2065594410008793412",
            )
        )
        msg_id2 = 902
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id2,
                "https://x.com/i/status/2065594410008793412?",
            ),
            (channel_id, msg_id1),
        )

    async def test_dupe_different_i_and_username(self):
        """/i/status vs /username/status with different usernames and tracker."""
        guild_id = 1
        channel_id = 1
        msg_id1 = 1001
        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id1,
                "https://x.com/usmnt/status/2065594410008793412?s=46&t=d1VIndVDTFDSYTO1fhiXOg",
            )
        )
        msg_id2 = 1002
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id, msg_id2,
                "https://x.com/i/status/2065594410008793412",
            ),
            (channel_id, msg_id1),
        )

    async def test_different_youtube_videos_are_not_dupes(self):
        guild_id = 0
        channel_id = 1
        msg_id1 = 301
        msg_id2 = 302

        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id1,
                "https://www.youtube.com/watch?v=VIDEO_A",
            )
        )
        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id2,
                "https://www.youtube.com/watch?v=VIDEO_B",
            )
        )

    async def test_same_youtube_video_variants_are_dupes(self):
        guild_id = 0
        channel_id = 1
        msg_id1 = 401
        msg_id2 = 402

        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id1,
                "https://www.youtube.com/watch?v=VIDEO_A&t=30",
            )
        )
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id2,
                "https://youtu.be/VIDEO_A?si=abc",
            ),
            (channel_id, msg_id1),
        )

    async def test_same_instagram_post_variants_are_dupes(self):
        guild_id = 0
        channel_id = 1
        msg_id1 = 501
        msg_id2 = 502

        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id1,
                "https://www.instagram.com/p/ABC/?igsh=share",
            )
        )
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id2,
                "https://kkinstagram.com/p/ABC/",
            ),
            (channel_id, msg_id1),
        )

    async def test_same_reddit_post_variants_are_dupes(self):
        guild_id = 0
        channel_id = 1
        msg_id1 = 601
        msg_id2 = 602

        self.assertIsNone(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id1,
                "https://old.reddit.com/r/test/comments/abc/title?utm_source=share",
            )
        )
        self.assertEqual(
            await self.checker.check_and_add(
                guild_id, channel_id,
                msg_id2,
                "https://rxddit.com/r/test/comments/abc/title",
            ),
            (channel_id, msg_id1),
        )

    async def test_media_exclusion(self):
        guild_id = 0
        channel_id = 1
        msg_id = 201

        # Test image link
        content_img = "Cool pic: https://example.com/image.jpg"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id, content_img))
        # Should NOT be a dupe if posted again because it was ignored
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 1, content_img))

        # Test Discord proxy link
        content_discord = "Embed: https://images-ext-1.discordapp.net/external/hash/https/example.com/image.png"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 2, content_discord))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 3, content_discord))

        # Test Tenor
        content_tenor = "GIF: https://tenor.com/view/some-gif-123"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 4, content_tenor))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 5, content_tenor))

    async def test_gif_midpath_exclusion(self):
        """URLs with .gif anywhere in the path (not just at the end) should be excluded."""
        guild_id = 0
        channel_id = 1
        msg_id = 301

        # .gif mid-path (e.g. trailing segment after the extension)
        content = "https://pbs.twimg.com/tweet_video_thumb/ABC.gif:123"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id, content))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 1, content))

    async def test_gif_query_param_exclusion(self):
        """URLs with .gif in query params (e.g. ?format=gif) should be excluded."""
        guild_id = 0
        channel_id = 1
        msg_id = 401

        content = "https://pbs.twimg.com/tweet_video/ABC123?format=gif"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id, content))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 1, content))

    async def test_new_gif_domains_exclusion(self):
        """Newly added GIF domains should be excluded."""
        guild_id = 0
        channel_id = 1
        msg_id = 501

        domains = [
            "https://klipy.com/view/something",
            "https://gifdeliverynetwork.com/abc",
            "https://gifyusercontent.com/abc",
        ]
        for i, url in enumerate(domains):
            content = f"GIF: {url}"
            self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + i * 2, content))
            self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + i * 2 + 1, content))

    async def test_discord_cdn_gif_exclusion(self):
        """Discord CDN URLs that are GIFs should be excluded."""
        guild_id = 0
        channel_id = 1
        msg_id = 601

        # media.discordapp.net is now in EXCLUDED_DOMAINS
        content = "https://media.discordapp.net/attachments/123/456/file.gif"
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id, content))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, msg_id + 1, content))

    async def test_same_author_gets_3_tries(self):
        """Original poster can share the same link up to 3 times before it's flagged."""
        guild_id = 1
        channel_id = 1
        author_id = 100
        content = "Check this: https://twitter.com/user/status/999"

        # 1st post — allowed
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 1001, content, author_id=author_id))
        # 2nd post — allowed (under 3)
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 1002, content, author_id=author_id))
        # 3rd post — allowed (exactly 3)
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 1003, content, author_id=author_id))
        # 4th post — flagged as dupe (at 3+)
        result = await self.checker.check_and_add(guild_id, channel_id, 1004, content, author_id=author_id)
        self.assertEqual(result, (channel_id, 1001))

    async def test_different_author_flagged_immediately(self):
        """A different user posting the same link is flagged as a dupe right away."""
        guild_id = 1
        channel_id = 1
        content = "Check this: https://twitter.com/user/status/888"

        # Author A posts
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 2001, content, author_id=100))
        # Author B posts same link — dupe
        result = await self.checker.check_and_add(guild_id, channel_id, 2002, content, author_id=200)
        self.assertEqual(result, (channel_id, 2001))

    async def test_same_author_over_limit_different_author_always_dupe(self):
        """After original poster hits 3 tries, 4th is dupe. Different author is always dupe."""
        guild_id = 1
        channel_id = 1
        content = "Check this: https://twitter.com/user/status/777"

        # Author A posts 3 times — all allowed
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 3001, content, author_id=100))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 3002, content, author_id=100))
        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 3003, content, author_id=100))
        # Author A 4th time — dupe
        result = await self.checker.check_and_add(guild_id, channel_id, 3004, content, author_id=100)
        self.assertEqual(result, (channel_id, 3001))
        # Author B — also dupe
        result = await self.checker.check_and_add(guild_id, channel_id, 3005, content, author_id=200)
        self.assertEqual(result, (channel_id, 3001))

    async def test_no_author_id_defaults_to_dupe(self):
        """When author_id is 0 (not provided), old behavior: always dupe."""
        guild_id = 1
        channel_id = 1
        content = "Check this: https://twitter.com/user/status/666"

        self.assertIsNone(await self.checker.check_and_add(guild_id, channel_id, 4001, content))
        result = await self.checker.check_and_add(guild_id, channel_id, 4002, content)
        self.assertEqual(result, (channel_id, 4001))

if __name__ == "__main__":
    unittest.main()
