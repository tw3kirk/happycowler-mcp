# -*- coding: utf-8 -*-
"""
Unit tests for the HappyCow text parser (happycowler/happycowler.py).

The 2026 rewrite fetches pages with headless Chrome and parses the rendered
*visible text* rather than the (obfuscated, frequently-redesigned) HTML.
These tests exercise ``parse_listing_text`` and ``normalize_url`` against a
bundled rendered-text fixture; no network access is required.
"""
import os
import unittest

from happycowler.happycowler import normalize_url, parse_listing_text

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_pages/")


def _load_fixture():
    with open(_DATA_PATH + "montrose_listing.txt", "r") as f:
        return f.read()


class TestNormalizeUrl(unittest.TestCase):

    def test_hyphenated_region_fixed(self):
        self.assertEqual(
            normalize_url("https://www.happycow.net/north-america/usa/montrose/"),
            "https://www.happycow.net/north_america/usa/montrose/",
        )

    def test_underscore_region_unchanged(self):
        url = "https://www.happycow.net/north_america/usa/montrose/"
        self.assertEqual(normalize_url(url), url)

    def test_single_word_region_unchanged(self):
        url = "https://www.happycow.net/europe/germany/worms/"
        self.assertEqual(normalize_url(url), url)


class TestParseListingText(unittest.TestCase):
    """Field-by-field regression baseline for the rendered-text parser."""

    @classmethod
    def setUpClass(cls):
        cls.venues = parse_listing_text(_load_fixture())

    def test_total_venue_count(self):
        self.assertEqual(len(self.venues), 4)

    def test_names(self):
        self.assertEqual(
            [v["name"] for v in self.venues],
            ["Pure Roots Cafe", "Green Sprout Kitchen", "Camp Robber",
             "Natural Grocers"],
        )

    def test_types_normalized(self):
        self.assertEqual(
            [v["type"] for v in self.venues],
            ["Vegan", "Vegetarian", "Veg-friendly", "Health Food Store"],
        )

    def test_ratings(self):
        self.assertEqual(
            [v["rating"] for v in self.venues],
            ["5.0", "4.5", "unknown", "4.0"],
        )

    def test_review_counts(self):
        self.assertEqual(
            [v["reviews"] for v in self.venues],
            ["12", "8", "", ""],
        )

    def test_addresses(self):
        self.assertEqual(
            [v["address"] for v in self.venues],
            [
                "123 Main St, Montrose, Colorado, USA",
                "5 Oak Ave, Montrose, Colorado, USA",
                "1515 Ogden Rd, Montrose, Colorado, USA",
                "3151 Woodgate Rd, Montrose, Colorado, USA",
            ],
        )

    def test_phone_numbers(self):
        # "Add a phone number" placeholder must come through as empty
        self.assertEqual(
            [v["phone"] for v in self.venues],
            ["970-555-0101", "", "970-240-1590", "970-555-0199"],
        )

    def test_hours_status(self):
        self.assertEqual(
            [v["hours"] for v in self.venues],
            ["Open Now", "Closed", "", "Open Now"],
        )

    def test_cuisines(self):
        self.assertEqual(
            [v["cuisine"] for v in self.venues],
            ["Vegan, Cafe", "Vegetarian, Indian", "Southwestern, American", ""],
        )

    def test_descriptions(self):
        self.assertEqual(
            [v["description"] for v in self.venues],
            [
                "All-vegan cafe with soups and grain bowls.",
                "Vegetarian kitchen with vegan options; daal and curry.",
                "Southwestern restaurant with some vegan-friendly dishes.",
                "Health food store with organic produce and bulk foods.",
            ],
        )

    def test_all_records_have_all_fields(self):
        required = {"name", "type", "rating", "reviews", "address", "phone",
                    "hours", "cuisine", "description"}
        for v in self.venues:
            self.assertEqual(required - set(v.keys()), set())

    def test_empty_text_yields_no_venues(self):
        self.assertEqual(parse_listing_text(""), [])


if __name__ == "__main__":
    unittest.main()
