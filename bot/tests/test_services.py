import json
import unittest
from pathlib import Path

from cobalt_bot.services import match_service

COBALT_TESTS = Path(__file__).parents[2] / "api/src/util/tests"


class CobaltTestUrls(unittest.TestCase):
    """Every url cobalt's own test suite expects to work must pass our filter."""

    def test_cobalt_test_urls_are_supported(self):
        for file in sorted(COBALT_TESTS.glob("*.json")):
            for case in json.loads(file.read_text()):
                if case["expected"]["status"] == "error":
                    continue
                with self.subTest(service=file.stem, name=case["name"], url=case["url"]):
                    self.assertIsNotNone(match_service(case["url"]))


class Filtering(unittest.TestCase):
    def test_supported(self):
        cases = {
            "https://youtu.be/jNQXAC9IVRw": "youtube",
            "https://www.youtube.com/shorts/abcdefghijk": "youtube",
            "https://music.youtube.com/watch?v=abc&list=xyz": "youtube",
            "https://x.com/someone/status/123": "twitter",
            "https://vxtwitter.com/someone/status/123/photo/1": "twitter",
            "https://clips.twitch.tv/SomeClip": "twitch",
            "https://v.redd.it/abc123": "reddit",
            "https://old.reddit.com/r/videos/comments/abc/title/": "reddit",
            "https://www.tiktok.com/@user/video/123": "tiktok",
            "https://vm.tiktok.com/ZMabc/": "tiktok",
            "https://pin.it/abc": "pinterest",
            "https://vk.com/video-123_456": "vk",
            "https://www.instagram.com/reel/abc/": "instagram",
        }
        for url, service in cases.items():
            with self.subTest(url=url):
                self.assertEqual(match_service(url), service)

    def test_unsupported(self):
        for url in [
            "https://example.com/foo",
            "https://github.com/imputnet/cobalt",
            "https://www.youtube.com/",
            "https://www.youtube.com/@channel",
            "https://youtube.co.uk/watch?v=abc",
            "https://evil.youtube.com/watch?v=abc",
            "https://twitter.com/someone",
            "https://www.reddit.com/r/videos/",
            "https://[::1/",
        ]:
            with self.subTest(url=url):
                self.assertIsNone(match_service(url))


if __name__ == "__main__":
    unittest.main()
