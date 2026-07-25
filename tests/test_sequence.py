from __future__ import annotations

import unittest
from collections import deque

from extractor.browser_story import (
    _extract_graphql_media,
    _story_owner,
    sequence_url,
)


class StorySequenceUrlTests(unittest.TestCase):
    def test_single_view_flags_are_removed(self):
        value = sequence_url(
            "https://www.facebook.com/stories/109/abc/?"
            "view_single=1&source=shared_permalink&mibextid=wwXIfr&keep=yes"
        )
        self.assertNotIn("view_single", value)
        self.assertNotIn("source=", value)
        self.assertNotIn("mibextid", value)
        self.assertIn("keep=yes", value)

    def test_fragment_is_removed(self):
        value = sequence_url("https://www.facebook.com/stories/109/abc/#item")
        self.assertNotIn("#", value)

    def test_story_owner_is_detected(self):
        self.assertEqual(
            _story_owner("https://web.facebook.com/stories/109442564543088/token/"),
            "109442564543088",
        )

    def test_graphql_video_url_is_captured(self):
        responses = deque(maxlen=20)
        _extract_graphql_media(
            '{"data":{"story":{"playable_url_quality_hd":'
            '"https:\\/\\/video.xx.fbcdn.net\\/story.mp4?x=1"}}}',
            responses,
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["type"], "video")
        self.assertIn("story.mp4", responses[0]["url"])


if __name__ == "__main__":
    unittest.main()
