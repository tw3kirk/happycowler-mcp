import os
import time
import unittest
from unittest.mock import patch

from happycowler import happycowler as hc_mod
from happycowler.happycowler import (
    classify_type,
    extract_latlng,
    parse_listing_fragment,
    parse_venue_detail,
    HappyCowError,
)

data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'test_pages/')


class RequestThrottle(unittest.TestCase):

    def test_spaces_consecutive_requests(self):
        with patch.object(hc_mod, "_MIN_REQUEST_INTERVAL", 0.1):
            hc_mod._last_request_at[0] = 0.0
            start = time.monotonic()
            hc_mod._throttle()  # first call: no wait
            hc_mod._throttle()  # second call: must wait out the interval
            elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.1)

    def test_zero_interval_disables_throttle(self):
        with patch.object(hc_mod, "_MIN_REQUEST_INTERVAL", 0.0):
            start = time.monotonic()
            for _ in range(50):
                hc_mod._throttle()
            self.assertLess(time.monotonic() - start, 0.05)


class TypeClassification(unittest.TestCase):

    def test_restaurant_buckets(self):
        self.assertEqual(classify_type("vegan", "1", "1"), "Vegan")
        self.assertEqual(classify_type("vegetarian", "0", "1"), "Vegetarian")
        self.assertEqual(classify_type("veg-options", "0", "0"), "Veg-friendly")

    def test_store_keeps_label_with_vegan_prefix(self):
        # A fully-vegan delivery kitchen should still match a "Vegan" filter.
        self.assertEqual(classify_type("Delivery", "1", "1"), "Vegan Delivery")
        self.assertIn("Vegan", classify_type("Veg Store", "1", "1"))

    def test_non_veg_store_unprefixed(self):
        self.assertEqual(classify_type("Health Store", "0", "0"), "Health Store")


class LatLngExtraction(unittest.TestCase):

    def test_extracts_coordinates_with_escaped_amp(self):
        html = '<a href="/searchmap?lat=-12.062106&amp;lng=-77.036526">map</a>'
        self.assertEqual(extract_latlng(html), ("-12.062106", "-77.036526"))

    def test_missing_coordinates_raises(self):
        with self.assertRaises(HappyCowError):
            extract_latlng("<html><body>no map here</body></html>")

    def test_median_of_nearby_city_links(self):
        # The links are the nearby-cities sidebar; the median approximates
        # the city's own center and is stable regardless of link order.
        html = "".join(
            '<a href="/searchmap?lat={}&amp;lng={}">x</a>'.format(lat, lng)
            for lat, lng in [("39.9", "-105.2"), ("39.7", "-104.9"),
                             ("39.8", "-105.0")]
        )
        self.assertEqual(extract_latlng(html), ("39.8", "-105.0"))


class ListingFragmentParser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(data_path + "lima_listing_fragment.html") as f:
            cls.venues = parse_listing_fragment(f.read())

    def test_all_five_cards_parsed(self):
        self.assertEqual(len(self.venues), 5)

    def test_names_and_urls(self):
        first = self.venues[0]
        self.assertEqual(first["name"], "Chocotejas Veganas")
        self.assertTrue(first["url"].startswith("https://www.happycow.net/reviews/"))

    def test_coordinates_present(self):
        for v in self.venues:
            lat, lng = v["coordinates"]
            self.assertTrue(lat and lng)
            float(lat)
            float(lng)  # parseable

    def test_types_mapped(self):
        by_name = {v["name"]: v["tag"] for v in self.venues}
        self.assertEqual(by_name["Noqa Vegan"], "Vegan")
        self.assertEqual(by_name["ConSuLado Vegano"], "Vegan")

    def test_card_rating_and_review_count(self):
        by_name = {v["name"]: v for v in self.venues}
        self.assertEqual(by_name["Chocotejas Veganas"]["rating"], "4.5")
        self.assertEqual(by_name["Chocotejas Veganas"]["reviews"], "3")

    def test_all_cards_have_rating_keys(self):
        for v in self.venues:
            self.assertIn("rating", v)
            self.assertIn("reviews", v)


class TopRatedCardParser(unittest.TestCase):
    """"Top Rated" venues show a badge *instead of* a review count on their
    listing cards — the count only exists on the venue detail page. The card
    parser must still read the rating and leave reviews empty (not crash or
    mis-parse the badge)."""

    def test_top_rated_badge_hides_review_count(self):
        with open(data_path + "toprated_card_snippet.html") as f:
            venues = parse_listing_fragment(f.read())
        self.assertEqual(len(venues), 1)
        v = venues[0]
        self.assertEqual(v["name"], "Watercourse Foods")
        self.assertEqual(v["rating"], "4.5")
        self.assertEqual(v["reviews"], "")
        self.assertEqual(v["tag"], "Vegan")


class VenueDetailParser(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(data_path + "noqa_review_snippet.html") as f:
            cls.detail = parse_venue_detail(f.read())

    def test_rating_normalised(self):
        self.assertEqual(self.detail["rating"], "5.0")

    def test_review_count(self):
        self.assertEqual(self.detail["reviews"], "41")

    def test_address_composed_from_parts(self):
        self.assertEqual(self.detail["address"],
                         "Av Paseo de la República, Lima, Peru")

    def test_phone(self):
        self.assertEqual(self.detail["phone"], "+51-960550950")

    def test_hours_stripped(self):
        self.assertEqual(self.detail["hours"], "Mon-Sun 10:00am-6:30pm")

    def test_description(self):
        self.assertTrue(self.detail["description"].startswith("Vegan restaurant"))

    def test_missing_rating_is_unknown(self):
        self.assertEqual(parse_venue_detail("<html></html>")["rating"], "unknown")

    def test_missing_review_count_is_empty(self):
        self.assertEqual(parse_venue_detail("<html></html>")["reviews"], "")


if __name__ == '__main__':
    unittest.main()
