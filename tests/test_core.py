from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from extractor.facebook_story import StoryExtractionError, parse_story_url
from extractor.media_parser import normalize_items
from storage import JobNotFoundError, JobStore


class ParserTests(unittest.TestCase):
    def test_facebook_url_is_accepted(self):
        parsed = parse_story_url("https://www.facebook.com/stories/123/456")
        self.assertEqual(parsed["host"], "www.facebook.com")
        self.assertTrue(parsed["is_story_url"])

    def test_non_facebook_url_is_rejected(self):
        with self.assertRaises(StoryExtractionError):
            parse_story_url("https://example.com/story")

    def test_normalize_items_assigns_stable_names(self):
        items = normalize_items([
            {"type": "video", "url": "https://cdn.example/video", "extension": "mp4"},
            {"type": "image", "url": "https://cdn.example/image", "extension": "jpg"},
        ])
        self.assertEqual(items[0]["filename"], "story_01.mp4")
        self.assertEqual(items[1]["filename"], "story_02.jpg")


class StorageTests(unittest.TestCase):
    def test_create_update_and_delete_job(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir))
            job = store.create_job(
                source_url="https://www.facebook.com/stories/123/456",
                items=[{"id": "item-01", "order": 1, "type": "video", "url": "https://cdn.example/video.mp4", "filename": "story_01.mp4"}],
                extraction_method="test", title="Test story",
            )
            self.assertEqual(store.get_job(job["id"])["item_count"], 1)
            item = store.get_job(job["id"])["items"][0]
            item["downloaded_name"] = "story_01.mp4"
            store.replace_item(job["id"], item)
            self.assertEqual(store.get_job(job["id"])["items"][0]["downloaded_name"], "story_01.mp4")
            store.delete_job(job["id"])
            with self.assertRaises(JobNotFoundError):
                store.get_job(job["id"])


if __name__ == "__main__":
    unittest.main()
