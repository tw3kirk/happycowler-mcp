# -*- coding: utf-8 -*-
"""
Tests for the HappyCowler MCP server (happycowler/mcp_server.py).

There are three test suites here:

  TestMCPSearchRestaurants   – unit tests; mock HappyCowler so no HTTP is
                               needed.  These always run.

  TestSearchEndToEnd         – unit tests; run search_restaurants over the
                               real parser against the bundled rendered-text
                               fixture (only the Playwright fetch is mocked).
                               Always run.

  TestLiveHappyCow           – integration tests that hit happycow.net over
                               the network.  Skipped by default.  Enable with:

                                   HAPPYCOW_RUN_LIVE_TESTS=1 python -m pytest tests/ -v

                               These are the definitive "does it work with the
                               current site?" check.
"""
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from happycowler import HappyCowler
from happycowler.mcp_server import search_restaurants

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# Four sample entries covering all three restaurant types (and some empty
# optional fields) used by the unit tests.
_SAMPLE_ENTRIES = [
    {
        "name": "Green Heaven",
        "tag": "Vegan",
        "rating": "5.0",
        "reviews": "16",
        "address": "10 Elm St, Worms, Germany",
        "phone": "+49 6241 12345",
        "hours": "Mon-Fri 11am-9pm",
        "cuisine": "Cuisine: International",
        "description": "Best fully vegan restaurant in town.",
    },
    {
        "name": "Veggie Palace",
        "tag": "Vegetarian",
        "rating": "4.5",
        "address": "5 Oak Ave, Worms, Germany",
        "phone": "+49 6241 67890",
        "hours": "Mon-Sun 10am-10pm",
        "cuisine": "Cuisine: Indian",
        "description": "Vegetarian food with vegan options.",
    },
    {
        "name": "Flex Bistro",
        "tag": "Veg-friendly",
        "rating": "3.5",
        "address": "2 Pine Rd, Worms, Germany",
        "phone": "",
        "hours": "",
        "cuisine": "",
        "description": "Omnivore bistro with several vegan dishes.",
    },
    {
        "name": "Pure Vegan Cafe",
        "tag": "Vegan",
        "rating": "4.0",
        "address": "8 Maple Lane",
        "phone": "+49 6241 11111",
        "hours": "Tue-Sun 9am-6pm",
        "cuisine": "Cuisine: Cafe",
        "description": "Cozy vegan cafe.",
    },
]


def _make_mock_hc(entries):
    """Return a MagicMock that looks like a crawled HappyCowler instance."""
    hc = MagicMock()
    hc.names         = [e["name"]        for e in entries]
    hc.tags          = [e["tag"]         for e in entries]
    hc.ratings       = [e["rating"]      for e in entries]
    hc.reviews       = [e.get("reviews", "") for e in entries]
    hc.addresses     = [e["address"]     for e in entries]
    hc.phone_numbers = [e["phone"]       for e in entries]
    hc.opening_hours = [e["hours"]       for e in entries]
    hc.cuisines      = [e["cuisine"]     for e in entries]
    hc.descriptions  = [e["description"] for e in entries]
    return hc


# ---------------------------------------------------------------------------
# Suite 1: MCP tool unit tests (all HTTP mocked)
# ---------------------------------------------------------------------------

class TestMCPSearchRestaurants(unittest.TestCase):
    """Unit tests for the search_restaurants MCP tool.

    HappyCowler.crawl() is mocked so no network access is required.
    """

    # -- output shape -------------------------------------------------------

    @patch("happycowler.mcp_server.HappyCowler")
    def test_returns_valid_json_array(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        result = search_restaurants("https://www.happycow.net/test/")
        data = json.loads(result)
        self.assertIsInstance(data, list)

    @patch("happycowler.mcp_server.HappyCowler")
    def test_all_required_fields_present(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES[:1])
        data = json.loads(search_restaurants("https://www.happycow.net/test/"))
        required = {"name", "type", "rating", "reviews", "address", "phone",
                    "hours", "cuisine", "description"}
        for field in required:
            self.assertIn(field, data[0], f"Missing field: {field}")

    @patch("happycowler.mcp_server.HappyCowler")
    def test_field_values_match_source(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES[:1])
        r = json.loads(search_restaurants("https://www.happycow.net/test/"))[0]
        self.assertEqual(r["name"],        "Green Heaven")
        self.assertEqual(r["type"],        "Vegan")
        self.assertEqual(r["rating"],      "5.0")
        self.assertEqual(r["address"],     "10 Elm St, Worms, Germany")
        self.assertEqual(r["phone"],       "+49 6241 12345")
        self.assertEqual(r["hours"],       "Mon-Fri 11am-9pm")
        self.assertEqual(r["description"], "Best fully vegan restaurant in town.")

    # -- type_filter --------------------------------------------------------

    @patch("happycowler.mcp_server.HappyCowler")
    def test_default_returns_all_types(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data = json.loads(search_restaurants("https://www.happycow.net/test/"))
        self.assertEqual(len(data), len(_SAMPLE_ENTRIES))

    @patch("happycowler.mcp_server.HappyCowler")
    def test_filter_vegan_only(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data = json.loads(
            search_restaurants("https://www.happycow.net/test/", type_filter="vegan")
        )
        self.assertEqual(len(data), 2)
        self.assertTrue(all("Vegan" in r["type"] for r in data))

    @patch("happycowler.mcp_server.HappyCowler")
    def test_filter_vegetarian_only(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data = json.loads(
            search_restaurants("https://www.happycow.net/test/", type_filter="vegetarian")
        )
        self.assertEqual(len(data), 1)
        self.assertIn("Vegetarian", data[0]["type"])

    @patch("happycowler.mcp_server.HappyCowler")
    def test_filter_veg_friendly(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data = json.loads(
            search_restaurants("https://www.happycow.net/test/", type_filter="veg-friendly")
        )
        self.assertEqual(len(data), 1)
        self.assertIn("Veg-friendly", data[0]["type"])

    @patch("happycowler.mcp_server.HappyCowler")
    def test_filter_is_case_insensitive(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data_upper = json.loads(
            search_restaurants("https://www.happycow.net/test/", type_filter="VEGAN")
        )
        self.assertEqual(len(data_upper), 2)

    # -- max_results --------------------------------------------------------

    @patch("happycowler.mcp_server.HappyCowler")
    def test_max_results_caps_output(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data = json.loads(
            search_restaurants("https://www.happycow.net/test/", max_results=2)
        )
        self.assertEqual(len(data), 2)

    @patch("happycowler.mcp_server.HappyCowler")
    def test_max_results_larger_than_available(self, MockHC):
        MockHC.return_value = _make_mock_hc(_SAMPLE_ENTRIES)
        data = json.loads(
            search_restaurants("https://www.happycow.net/test/", max_results=999)
        )
        self.assertEqual(len(data), len(_SAMPLE_ENTRIES))

    # -- XML entity unescaping ----------------------------------------------

    @patch("happycowler.mcp_server.HappyCowler")
    def test_xml_entities_unescaped_in_output(self, MockHC):
        """normalize() encodes & as &amp; - mcp_server must reverse that."""
        entry = {
            "name": "Caf&amp; Vegan",
            "tag": "Vegan",
            "rating": "4.0",
            "address": "Rue &amp; Tram",
            "phone": "",
            "hours": "",
            "cuisine": "",
            "description": "Fresh &amp; tasty food",
        }
        MockHC.return_value = _make_mock_hc([entry])
        r = json.loads(search_restaurants("https://www.happycow.net/test/"))[0]
        self.assertEqual(r["name"],        "Caf& Vegan")
        self.assertEqual(r["address"],     "Rue & Tram")
        self.assertEqual(r["description"], "Fresh & tasty food")

    # -- error handling -----------------------------------------------------

    @patch("happycowler.mcp_server.HappyCowler")
    def test_crawl_exception_returns_error_json(self, MockHC):
        MockHC.return_value.crawl.side_effect = Exception("Connection refused")
        result = search_restaurants("https://www.happycow.net/test/")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("Connection refused", data["error"])

    @patch("happycowler.mcp_server.HappyCowler")
    def test_empty_crawl_results(self, MockHC):
        MockHC.return_value = _make_mock_hc([])
        data = json.loads(search_restaurants("https://www.happycow.net/test/"))
        self.assertEqual(data, [])


# ---------------------------------------------------------------------------
# Suite 2: End-to-end through the real parser (only the browser fetch mocked)
# ---------------------------------------------------------------------------

_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_pages/")


def _fixture_text():
    with open(_DATA_PATH + "montrose_listing.txt", "r") as f:
        return f.read()


class TestSearchEndToEnd(unittest.TestCase):
    """Run search_restaurants over the real HappyCowler + parser.

    Only ``_render_text`` (the Playwright subprocess) is patched, so this
    covers URL normalization, crawl(), parse_listing_text() and the JSON
    shaping in one pass.
    """

    def _search(self, **kwargs):
        with patch("happycowler.happycowler._render_text",
                   return_value=_fixture_text()):
            return json.loads(
                search_restaurants(
                    "https://www.happycow.net/north_america/usa/montrose/",
                    **kwargs,
                )
            )

    def test_returns_all_fixture_venues(self):
        data = self._search()
        self.assertEqual(
            [r["name"] for r in data],
            ["Pure Roots Cafe", "Green Sprout Kitchen", "Camp Robber",
             "Natural Grocers"],
        )

    def test_vegan_filter(self):
        data = self._search(type_filter="vegan")
        self.assertEqual([r["name"] for r in data], ["Pure Roots Cafe"])
        self.assertEqual(data[0]["rating"], "5.0")
        self.assertEqual(data[0]["reviews"], "12")

    def test_full_record_shape(self):
        r = self._search()[1]  # Green Sprout Kitchen
        self.assertEqual(r["type"],        "Vegetarian")
        self.assertEqual(r["rating"],      "4.5")
        self.assertEqual(r["reviews"],     "8")
        self.assertEqual(r["address"],     "5 Oak Ave, Montrose, Colorado, USA")
        self.assertEqual(r["phone"],       "")  # "Add a phone number" placeholder
        self.assertEqual(r["hours"],       "Closed")
        self.assertEqual(r["cuisine"],     "Vegetarian, Indian")

    def test_hyphenated_region_url_accepted(self):
        with patch("happycowler.happycowler._render_text",
                   return_value=_fixture_text()) as mock_render:
            search_restaurants(
                "https://www.happycow.net/north-america/usa/montrose/")
        fetched_url = mock_render.call_args[0][0]
        self.assertIn("/north_america/", fetched_url)

    def test_crawler_coordinates_placeholder(self):
        with patch("happycowler.happycowler._render_text",
                   return_value=_fixture_text()):
            hc = HappyCowler("https://www.happycow.net/north_america/usa/montrose/")
            hc.crawl()
        n = len(hc.names)
        self.assertEqual(n, 4)
        for attr in ("tags", "ratings", "reviews", "addresses", "phone_numbers",
                     "opening_hours", "cuisines", "descriptions", "coordinates"):
            self.assertEqual(len(getattr(hc, attr)), n)
        for coord in hc.coordinates:
            self.assertEqual(coord, ("", ""))


# ---------------------------------------------------------------------------
# Suite 3: Live integration tests (skipped unless opt-in)
# ---------------------------------------------------------------------------

_LIVE = os.getenv("HAPPYCOW_RUN_LIVE_TESTS")

@unittest.skipUnless(_LIVE, "skipped: set HAPPYCOW_RUN_LIVE_TESTS=1 to run")
class TestLiveHappyCow(unittest.TestCase):
    """Integration tests against the live happycow.net website.

    These are the definitive check that the fetcher + parser still work with
    HappyCow's *current* site.  They launch a real headless Chrome.

    Usage:
        HAPPYCOW_RUN_LIVE_TESTS=1 python -m pytest tests/test_mcp_server.py::TestLiveHappyCow -v
    """

    # Worms, Germany - small, stable listing, good for smoke tests
    WORMS_URL = "https://www.happycow.net/europe/germany/worms/"

    def _fetch(self, **kwargs):
        result = search_restaurants(self.WORMS_URL, **kwargs)
        data = json.loads(result)
        if isinstance(data, dict) and "error" in data:
            self.fail(f"Crawler returned error: {data['error']}")
        return data

    def test_returns_at_least_one_restaurant(self):
        data = self._fetch(max_results=5)
        self.assertGreater(len(data), 0,
                           "Expected at least one restaurant for Worms, Germany")

    def test_all_required_fields_present(self):
        required = {"name", "type", "rating", "reviews", "address",
                    "phone", "hours", "cuisine", "description"}
        for r in self._fetch(max_results=5):
            missing = required - set(r.keys())
            self.assertEqual(missing, set(), f"Restaurant missing fields: {missing}")

    def test_name_is_nonempty_string(self):
        for r in self._fetch(max_results=5):
            self.assertIsInstance(r["name"], str)
            self.assertTrue(r["name"].strip(), "Restaurant name should not be empty")

    def test_type_is_known_value(self):
        valid = {"Vegan", "Vegetarian", "Veg-friendly", "Other", "Catering",
                 "Health Food Store", "Cafe", "Bakery", "Food Truck",
                 "Juice Bar", "Market", ""}
        for r in self._fetch(max_results=10):
            self.assertTrue(
                any(t in r["type"] for t in valid),
                f"Unexpected type value: {r['type']!r}",
            )

    def test_vegan_filter_returns_only_vegan(self):
        for r in self._fetch(type_filter="vegan", max_results=10):
            self.assertIn("Vegan", r["type"],
                          f"Non-vegan result slipped through: {r['type']!r}")

    def test_rating_is_numeric_or_unknown(self):
        for r in self._fetch(max_results=10):
            if r["rating"] != "unknown":
                try:
                    float(r["rating"])
                except ValueError:
                    self.fail(f"Rating is not numeric or 'unknown': {r['rating']!r}")


if __name__ == "__main__":
    unittest.main()
