from __future__ import annotations

import unittest

from extractor.browser_story import sequence_url


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


if __name__ == "__main__":
    unittest.main()
