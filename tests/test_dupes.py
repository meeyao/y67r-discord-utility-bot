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
            ("https://twitter.com/user/status/123", "https://twitter.com/user/status/123"),
            ("https://x.com/user/status/123", "https://twitter.com/user/status/123"),
            ("https://fxtwitter.com/user/status/123", "https://twitter.com/user/status/123"),
            ("https://vxtwitter.com/user/status/123", "https://twitter.com/user/status/123"),
            ("https://fixupx.com/user/status/123", "https://twitter.com/user/status/123"),
            ("https://twitter.com/user/status/123?s=20", "https://twitter.com/user/status/123"),
            ("https://X.COM/User/Status/123", "https://twitter.com/user/status/123"),
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
        channel_id = 1
        msg_id1 = 101
        content1 = "Check this: https://twitter.com/user/status/123"
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id1, content1))
        
        msg_id2 = 102
        content2 = "Duplicate: https://x.com/user/status/123"
        result = await self.checker.check_and_add(channel_id, msg_id2, content2)
        self.assertEqual(result, msg_id1)
        
        msg_id3 = 103
        content3 = "Different channel: https://twitter.com/user/status/123"
        self.assertIsNone(await self.checker.check_and_add(2, msg_id3, content3))

    async def test_different_youtube_videos_are_not_dupes(self):
        channel_id = 1
        msg_id1 = 301
        msg_id2 = 302

        self.assertIsNone(
            await self.checker.check_and_add(
                channel_id,
                msg_id1,
                "https://www.youtube.com/watch?v=VIDEO_A",
            )
        )
        self.assertIsNone(
            await self.checker.check_and_add(
                channel_id,
                msg_id2,
                "https://www.youtube.com/watch?v=VIDEO_B",
            )
        )

    async def test_same_youtube_video_variants_are_dupes(self):
        channel_id = 1
        msg_id1 = 401
        msg_id2 = 402

        self.assertIsNone(
            await self.checker.check_and_add(
                channel_id,
                msg_id1,
                "https://www.youtube.com/watch?v=VIDEO_A&t=30",
            )
        )
        self.assertEqual(
            await self.checker.check_and_add(
                channel_id,
                msg_id2,
                "https://youtu.be/VIDEO_A?si=abc",
            ),
            msg_id1,
        )

    async def test_same_instagram_post_variants_are_dupes(self):
        channel_id = 1
        msg_id1 = 501
        msg_id2 = 502

        self.assertIsNone(
            await self.checker.check_and_add(
                channel_id,
                msg_id1,
                "https://www.instagram.com/p/ABC/?igsh=share",
            )
        )
        self.assertEqual(
            await self.checker.check_and_add(
                channel_id,
                msg_id2,
                "https://kkinstagram.com/p/ABC/",
            ),
            msg_id1,
        )

    async def test_same_reddit_post_variants_are_dupes(self):
        channel_id = 1
        msg_id1 = 601
        msg_id2 = 602

        self.assertIsNone(
            await self.checker.check_and_add(
                channel_id,
                msg_id1,
                "https://old.reddit.com/r/test/comments/abc/title?utm_source=share",
            )
        )
        self.assertEqual(
            await self.checker.check_and_add(
                channel_id,
                msg_id2,
                "https://rxddit.com/r/test/comments/abc/title",
            ),
            msg_id1,
        )

    async def test_media_exclusion(self):
        channel_id = 1
        msg_id = 201
        
        # Test image link
        content_img = "Cool pic: https://example.com/image.jpg"
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id, content_img))
        # Should NOT be a dupe if posted again because it was ignored
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id + 1, content_img))
        
        # Test Discord proxy link
        content_discord = "Embed: https://images-ext-1.discordapp.net/external/hash/https/example.com/image.png"
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id + 2, content_discord))
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id + 3, content_discord))
        
        # Test Tenor
        content_tenor = "GIF: https://tenor.com/view/some-gif-123"
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id + 4, content_tenor))
        self.assertIsNone(await self.checker.check_and_add(channel_id, msg_id + 5, content_tenor))

if __name__ == "__main__":
    unittest.main()
