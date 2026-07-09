# -*- coding: utf-8 -*-
"""
Crawler and parser for HappyCow.net.

Originally created 2016 by Peter Wittek. Rewritten in 2026 after HappyCow
migrated to a JavaScript-rendered front end: the old city listing pages no
longer server-render their venue cards, so the previous class-name scraping
(``div.row.venue-list-item`` etc.) broke. The current approach is:

  1. Fetch the city listing page only to read the map seed coordinates.
  2. Page through HappyCow's own JSON endpoint
     ``/ajax/views/searchmap/venues`` to collect every venue (name, URL, type,
     coordinates) in a handful of requests.
  3. Optionally "deep crawl" each venue's review page, reading the stable
     schema.org microdata (ratingValue, address, telephone, description) plus
     the opening-hours summary.
"""
from __future__ import division, print_function

import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from math import asin, cos, radians, sin, sqrt

from bs4 import BeautifulSoup

# HappyCow sits behind Imperva/Incapsula, which fingerprints the TLS handshake
# (JA3) and serves a bot challenge to plain urllib3/requests clients. curl_cffi
# impersonates a real browser's TLS stack and sails through it; requests is kept
# only as a last-resort fallback (it will usually get challenged).
try:
    from curl_cffi import requests as _http
    from curl_cffi.requests.exceptions import RequestException as _RequestException
    _IMPERSONATE = "chrome"
except ImportError:  # pragma: no cover - fallback path
    import requests as _http
    from requests.exceptions import RequestException as _RequestException
    _IMPERSONATE = None

RequestException = _RequestException

from .file_io import append_results_to_file, write_footer, write_header

BASE_URL = "https://www.happycow.net"
LISTING_ENDPOINT = BASE_URL + "/ajax/views/searchmap/venues"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# The city page embeds map links such as ``/searchmap?lat=-12.06&lng=-77.03``.
# Ampersands may be HTML-escaped (``&amp;``) in the served markup.
_LATLNG_RE = re.compile(r"lat=(-?\d+(?:\.\d+)?)&(?:amp;)?lng=(-?\d+(?:\.\d+)?)")

# HappyCow's data-type / category-label values that map onto the classic
# Vegan / Vegetarian / Veg-friendly buckets the MCP type_filter understands.
_RESTAURANT_TYPE = {
    "vegan": "Vegan",
    "vegetarian": "Vegetarian",
    "veg-options": "Veg-friendly",
    "veg options": "Veg-friendly",
    "veg-friendly": "Veg-friendly",
}


class HappyCowError(Exception):
    """Raised when HappyCow cannot be crawled: bad URL, blocked, or the page
    structure changed so the expected data could not be located."""


# Global politeness throttle: at most one request to HappyCow per interval,
# across all threads (deep crawls run in a pool). Keeps the crawler a good
# citizen and below the WAF's suspicion threshold. Override (or disable with
# 0) via the HAPPYCOW_MIN_REQUEST_INTERVAL environment variable.
_MIN_REQUEST_INTERVAL = float(os.environ.get("HAPPYCOW_MIN_REQUEST_INTERVAL", "1.0"))
_throttle_lock = threading.Lock()
_last_request_at = [0.0]


def _throttle():
    if _MIN_REQUEST_INTERVAL <= 0:
        return
    with _throttle_lock:
        wait = _last_request_at[0] + _MIN_REQUEST_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at[0] = time.monotonic()


# Best-effort local disk cache for city listing crawls and venue detail
# pages. A city crawl costs dozens of throttled requests, and repeat queries
# against the same city (with different sorts/filters, which are applied
# client-side) are common. Entries newer than the TTL are served from disk.
# Env overrides: HAPPYCOW_CACHE_TTL (seconds; 0 disables) and
# HAPPYCOW_CACHE_DIR (default ~/.cache/happycowler).
_CACHE_TTL = float(os.environ.get("HAPPYCOW_CACHE_TTL", str(24 * 3600)))
_CACHE_DIR = os.environ.get("HAPPYCOW_CACHE_DIR") or os.path.join(
    os.path.expanduser("~"), ".cache", "happycowler")


def _cache_path(kind, key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return os.path.join(_CACHE_DIR, "{}-{}.json".format(kind, digest))


def _cache_read(kind, key):
    if _CACHE_TTL <= 0:
        return None
    try:
        with open(_cache_path(kind, key)) as f:
            entry = json.load(f)
    except (OSError, ValueError):
        return None
    if time.time() - entry.get("fetched_at", 0) > _CACHE_TTL:
        return None
    return entry.get("data")


def _cache_write(kind, key, data):
    if _CACHE_TTL <= 0:
        return
    path = _cache_path(kind, key)
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fetched_at": time.time(), "data": data}, f)
        os.replace(tmp, path)  # atomic: readers never see partial writes
    except OSError:
        pass  # the cache is an optimization, never an error


def normalize(text):
    """Escape ampersands (so downstream XML/KML/GPX output is valid) and strip."""
    processed_text = (text or "").replace("&", "&amp;")
    if sys.version_info.major == 3:
        return processed_text.strip()
    return processed_text.encode("utf-8").strip()


def _new_session(user_agent=DEFAULT_USER_AGENT):
    kwargs = {"impersonate": _IMPERSONATE} if _IMPERSONATE else {}
    session = _http.Session(**kwargs)
    session.headers.update({
        "User-Agent": user_agent,
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def _http_get(session, url, xhr=False, as_json=False, timeout=30):
    _throttle()
    headers = {}
    if xhr:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if as_json:
        headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    response = session.get(url, headers=headers, timeout=timeout)
    if response.status_code == 404:
        raise HappyCowError(
            "HappyCow returned 404 for {}. Check the city URL: region slugs use "
            "underscores (e.g. 'south_america', 'north_america'), not hyphens."
            .format(url)
        )
    response.raise_for_status()
    if as_json:
        try:
            return response.json()
        except ValueError as exc:
            raise HappyCowError(
                "Expected JSON from {} but the response was not JSON: {}"
                .format(url, exc)
            )
    return response.text


def get_parsed_html(url, session=None):
    """Fetch ``url`` and return a parsed BeautifulSoup document."""
    session = session or _new_session()
    return BeautifulSoup(_http_get(session, url), "html.parser")


def extract_latlng(city_html):
    """Derive the (lat, lng) map seed from a city listing page.

    The page carries no canonical coordinates for the city itself — its
    ``/searchmap?lat=..&lng=..`` links are the *nearby cities* sidebar (~20
    suburbs). Taking the first link seeds the crawl on a random suburb and
    makes distances/coverage wobble between fetches, so use the
    component-wise median of all links: the suburbs surround the city, their
    median lands near its center, and it is stable regardless of link order.
    """
    matches = _LATLNG_RE.findall(city_html)
    if not matches:
        raise HappyCowError(
            "Could not find map coordinates on the city page. HappyCow's page "
            "structure may have changed, or this is not a valid city listing URL."
        )
    lats = sorted(float(lat) for lat, _ in matches)
    lngs = sorted(float(lng) for _, lng in matches)
    mid = len(matches) // 2
    return repr(lats[mid]), repr(lngs[mid])


def classify_type(data_type, vegan="0", vegonly="0"):
    """Map HappyCow's ``data-type`` (+ vegan flags) to a human-readable tag.

    Restaurants collapse to the classic Vegan / Vegetarian / Veg-friendly
    buckets. Other categories (stores, delivery, catering, coffee & tea, ...)
    keep their label, prefixed with the venue's vegan status so a "Vegan"
    filter still matches a fully-vegan store or delivery kitchen.
    """
    dt = (data_type or "").strip()
    key = dt.lower()
    if key in _RESTAURANT_TYPE:
        return _RESTAURANT_TYPE[key]
    label = dt or "Other"
    if vegan == "1" and vegonly == "1":
        return "Vegan " + label
    if vegan == "1":
        return "Vegetarian " + label
    return label


# A listing card shows its rating as two adjacent divs inside an <li>:
# ``<div>4.5</div><div>(12)</div>``.
_CARD_RATING_RE = re.compile(r"^[0-5](\.\d)?$")
_CARD_COUNT_RE = re.compile(r"^\((\d+)\)$")


def _norm_token(text):
    """Normalize a label for matching: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


# The cuisine and category vocabularies HappyCow uses (venue pages show them
# as tag pills in .venue-info). Stored normalized via _norm_token.
CUISINES = {_norm_token(c) for c in (
    "African", "American", "Asian", "Australian", "Brazilian", "British",
    "Caribbean", "Chinese", "European", "French", "Fusion", "German",
    "Indian", "International", "Italian", "Japanese", "Korean", "Latin",
    "Mediterranean", "Mexican", "Middle Eastern", "Spanish", "Taiwanese",
    "Thai", "Vietnamese", "Western",
)}
CATEGORIES = {_norm_token(c) for c in (
    "Delivery", "Take-out", "Breakfast", "Gluten-free", "Organic", "Pizza",
    "Bakery", "Beer/Wine", "Buffet", "Catering", "Fast food", "Juice Bar",
    "Macrobiotic", "Raw food", "Salad Bar", "Kosher",
)}
_VEG_LEVEL_PILLS = {_norm_token(c) for c in (
    "Vegan", "Vegetarian", "Vegan-friendly", "Veg-friendly", "Vegan Options",
)}

# For reference: the /ajax/views/searchmap/venues endpoint also accepts
# server-side narrowing via &filters=<slug> (single value; unknown slugs are
# silently ignored) and &radius=<miles>. Verified working slugs: vegan,
# vegetarian, veg-options, bakery, coffee-tea, health-store, delivery,
# catering, bnb, farmers-market, organization, spa, other, icecream,
# juicebar, foodtruck, vegshop, marketvendor. The crawler filters
# client-side instead so one cached base crawl serves every combination.


def _card_price(card):
    """Price level 0-3 from a card's dollar icons (yellow = filled)."""
    return sum(1 for svg in card.select(".price-range-item")
               if "text-yellow-500" in (svg.get("class") or []))


def _card_rating(card):
    """Read the rating and review count shown on a listing card."""
    for div in card.find_all("div"):
        text = div.get_text(strip=True)
        if div.parent.name == "li" and _CARD_RATING_RE.match(text):
            reviews = ""
            sibling = div.find_next_sibling("div")
            if sibling:
                match = _CARD_COUNT_RE.match(sibling.get_text(strip=True))
                if match:
                    reviews = match.group(1)
            return text, reviews
    return "unknown", ""


def parse_listing_fragment(fragment_html):
    """Parse the HTML fragment returned by the ``/ajax/.../venues`` endpoint.

    Returns a list of dicts with keys: name, url, tag, coordinates, rating,
    reviews. Rating/reviews come from the card itself, so they are available
    even without a deep crawl of the venue page.
    """
    soup = BeautifulSoup(fragment_html or "", "html.parser")
    venues = []
    for card in soup.select("div.card-listing.venue-item"):
        link = card.find(
            "a", href=lambda h: h and h.startswith("/reviews/") and "#" not in h
        )
        if link is None:
            continue
        heading = card.find(["h4", "h3", "h2"])
        name = heading.get_text(strip=True) if heading else link.get("title", "").strip()
        details = card.select_one(".details")
        if details is not None:
            data_type = details.get("data-type", "")
            vegan = details.get("data-vegan", "0")
            vegonly = details.get("data-vegonly", "0")
            coords = (details.get("data-lat", ""), details.get("data-lng", ""))
        else:
            data_type, vegan, vegonly, coords = "", "0", "0", ("", "")
        rating, reviews = _card_rating(card)
        venues.append({
            "name": name,
            "url": BASE_URL + link["href"],
            "tag": classify_type(data_type, vegan, vegonly),
            "coordinates": coords,
            "rating": rating,
            "reviews": reviews,
            "price": _card_price(card),
            "top": (details.get("data-top") == "1") if details else False,
        })
    return venues


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(radians, (float(lat1), float(lng1),
                                           float(lat2), float(lng2)))
    a = sin((lat2 - lat1) / 2) ** 2 + \
        cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * asin(sqrt(a))


def _microdata(soup, prop):
    """Read a schema.org microdata value: prefer the ``content`` attribute,
    else the element text. Returns '' when the property is absent."""
    el = soup.find(attrs={"itemprop": prop})
    if el is None:
        return ""
    return (el.get("content") or el.get_text(" ", strip=True)).strip()


# --- opening-hours parsing (for the open-now filter) -----------------------

_DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4,
              "sat": 5, "sun": 6}
_HOURS_SEG_RE = re.compile(r"([A-Za-z]{3})(?:-([A-Za-z]{3}))?\s+(.+)")
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?(am|pm)-(\d{1,2})(?::(\d{2}))?(am|pm)", re.I)


def _to_minutes(hour, minute, ampm):
    hour, minute = int(hour), int(minute or 0)
    if ampm.lower() == "pm" and hour != 12:
        hour += 12
    if ampm.lower() == "am" and hour == 12:
        hour = 0
    return hour * 60 + minute


def parse_hours(summary):
    """Parse an hours summary like ``Mon-Thu 12:00pm-9:00pm, Sun 12:00pm-9:00pm``
    into (day_index 0=Mon, open_minute, close_minute) tuples. Close times past
    midnight exceed 1440. Returns [] when nothing parses."""
    spans = []
    for seg in (summary or "").split(","):
        seg = seg.strip()
        if not seg:
            continue
        if "24 h" in seg.lower() or "24 hours" in seg.lower():
            for d in range(7):
                spans.append((d, 0, 1440))
            continue
        m = _HOURS_SEG_RE.match(seg)
        if not m:
            continue
        d1 = _DAY_INDEX.get(m.group(1).lower()[:3])
        d2 = _DAY_INDEX.get((m.group(2) or m.group(1)).lower()[:3])
        if d1 is None or d2 is None:
            continue
        days = [(d1 + i) % 7 for i in range((d2 - d1) % 7 + 1)]
        for t in _TIME_RANGE_RE.finditer(m.group(3)):
            start = _to_minutes(t.group(1), t.group(2), t.group(3))
            end = _to_minutes(t.group(4), t.group(5), t.group(6))
            if end <= start:
                end += 1440  # closes after midnight (or 12:00am close)
            for d in days:
                spans.append((d, start, end))
    return spans


def is_open_at(summary, weekday, minute):
    """Is a venue with this hours summary open at (weekday 0=Mon, minute)?
    Returns None when the hours can't be parsed (unknown)."""
    spans = parse_hours(summary)
    if not spans:
        return None
    for d, start, end in spans:
        if d == weekday and start <= minute < min(end, 1440):
            return True
        if end > 1440 and (d + 1) % 7 == weekday and minute < end - 1440:
            return True  # overnight spill past midnight
    return False


_PRICE_RANGE_WORDS = {"inexpensive": 1, "moderate": 2, "expensive": 3}


def parse_venue_detail(review_html):
    """Parse a venue review page. Returns a dict with keys: rating, reviews,
    address, phone, hours, cuisine, cuisines, categories, features, price,
    description."""
    soup = BeautifulSoup(review_html, "html.parser")

    rating_value = _microdata(soup, "ratingValue")
    try:
        rating = "{:.1f}".format(float(rating_value)) if rating_value else "unknown"
    except ValueError:
        rating = "unknown"

    # Prefer composing a clean address from its parts; fall back to the blob.
    parts = [_microdata(soup, p)
             for p in ("streetAddress", "addressLocality", "addressCountry")]
    address = ", ".join(p for p in parts if p) or _microdata(soup, "address")

    hours = ""
    hours_el = soup.select_one(".hours-summary")
    if hours_el:
        hours = re.sub(r"^Open\s+", "", hours_el.get_text(" ", strip=True)).rstrip(".")

    # Tag pills in .venue-info: veg level, then cuisines and categories
    # (the last pill is the description blob — filtered out by length).
    cuisines, categories = [], []
    info = soup.select_one(".venue-info")
    if info is not None:
        for pill in info.find_all("div", recursive=False):
            text = pill.get_text(strip=True)
            token = _norm_token(text)
            if not text or len(text) > 40 or token in _VEG_LEVEL_PILLS:
                continue
            if token in CUISINES:
                cuisines.append(text)
            elif token in CATEGORIES:
                categories.append(text)

    # Feature list items carry their label in a title attribute
    # (e.g. <li title="Accepts credit cards">).
    features = []
    for li in soup.find_all("li", title=True):
        title = li["title"].strip()
        if title and title not in features and len(title) < 40:
            features.append(title)

    price = _PRICE_RANGE_WORDS.get(
        _microdata(soup, "priceRange").lower(), 0)

    return {
        "rating": rating,
        "reviews": _microdata(soup, "reviewCount"),
        "address": address,
        "phone": _microdata(soup, "telephone"),
        "hours": hours,
        "cuisine": ", ".join(cuisines),
        "cuisines": cuisines,
        "categories": categories,
        "features": features,
        "price": price,
        "description": _microdata(soup, "description"),
    }


_EMPTY_DETAIL = {
    "rating": "unknown", "reviews": "", "address": "", "phone": "",
    "hours": "", "cuisine": "", "cuisines": [], "categories": [],
    "features": [], "price": 0, "description": "",
}


class HappyCowler(object):
    """Crawl the HappyCow database for a city.

    :param city_url: HappyCow city listing URL, or a list of them, e.g.
                     ``https://www.happycow.net/south_america/peru/lima/``.
    :param target_file: Optional ``.kml`` / ``.gpx`` file to write results to.
    :param verbose: 0 quiet (default), 1 progress to stdout.
    :param type_filter: Optional 'vegan' / 'vegetarian' / 'veg-friendly' to
                        collect only matching venues (cheaper: fewer deep
                        crawls). ``None`` / 'all' collects everything.
    :param max_results: Cap the number of venues per city (bounds deep crawls).
    :param deep_crawl: When True (default) fetch each venue's review page to
                       fill rating/address/phone/hours/description.
    :param sort_by: 'distance' (from the city's map seed point, nearest
                    first), 'rating' (stars, best first), 'popularity'
                    (review count, most first), or None/'default' for
                    HappyCow's own listing order. Sorting happens before
                    ``max_results`` slicing, so "top N by X" works.
    :param min_rating: Only keep venues whose star rating is at least this
                       value (venues with no rating are dropped).
    :param radius_miles: Only keep venues within this distance of the city's
                         map seed point. 0/None disables the filter.
    :param refresh: Skip the local cache and re-crawl (fresh results are
                    still written back to the cache).
    :param max_pages: Safety cap on listing-endpoint pagination.
    :param workers: Thread pool size for concurrent deep crawls.
    :param request_delay: Optional politeness delay (seconds) between listing
                          pages.
    :param session: Optional pre-built ``requests.Session``.
    """

    SORTS = ("default", "distance", "rating", "popularity", "name", "veg",
             "price_asc", "price_desc")
    _SORT_ALIASES = {
        "stars": "rating", "most popular": "popularity", "a-z": "name",
        "az": "name", "alphabetical": "name", "veg friendliness": "veg",
        "veg-friendliness": "veg", "price": "price_asc",
        "price-asc": "price_asc", "price-desc": "price_desc",
        "cheapest": "price_asc", "priciest": "price_desc",
    }

    def __init__(self, city_url, target_file=None, verbose=0, type_filter=None,
                 max_results=None, deep_crawl=True, sort_by=None,
                 min_rating=None, radius_miles=None, refresh=False,
                 venue_types=None, cuisines=None, categories=None,
                 features=None, vegan_only=False, hide_chains=False,
                 open_now=False, at=None, detail_scan_limit=80,
                 max_pages=25, workers=8, request_delay=0.0, session=None):
        self.refresh = bool(refresh)
        self.city_url = city_url if isinstance(city_url, list) else [city_url]
        self.target_file = target_file
        self.verbose = verbose
        self.type_filter = self._normalize_filter(type_filter)
        self.max_results = max_results
        self.deep_crawl = deep_crawl
        self.sort_by = self._normalize_sort(sort_by)
        self.min_rating = float(min_rating) if min_rating else None
        self.radius_miles = float(radius_miles) if radius_miles else None
        self.venue_types = self._csv_tokens(venue_types)
        self.cuisines = self._csv_tokens(cuisines)
        self.categories = self._csv_tokens(categories)
        self.features = self._csv_tokens(features)
        self.vegan_only = bool(vegan_only)
        self.hide_chains = bool(hide_chains)
        self.open_now = bool(open_now)
        self.at = self._parse_at(at)
        self.detail_scan_limit = detail_scan_limit
        self.max_pages = max_pages
        self.workers = max(1, workers)
        self.request_delay = request_delay
        self.session = session or _new_session()
        self._detail_cache = {}
        self.scan_truncated = False

        # Public result columns (kept for backwards compatibility; the
        # `cuisines` constructor arg is a filter, the result column of the
        # same concept is `venue_cuisines`).
        self.coordinates = []
        self.names = []
        self.tags = []
        self.ratings = []
        self.reviews = []
        self.distances = []
        self.prices = []
        self.venue_cuisines = []
        self.venue_categories = []
        self.venue_features = []
        self.addresses = []
        self.phone_numbers = []
        self.opening_hours = []
        self.descriptions = []
        self.total_entries = 0
        self.processed_entries = 0

    @staticmethod
    def _normalize_filter(type_filter):
        if not type_filter:
            return None
        return {
            "vegan": "Vegan",
            "vegetarian": "Vegetarian",
            "veg-friendly": "Veg-friendly",
            "vegan options": "Veg-friendly",
            "veg-options": "Veg-friendly",
        }.get(type_filter.lower())

    @classmethod
    def _normalize_sort(cls, sort_by):
        if not sort_by or sort_by == "default":
            return None
        key = str(sort_by).lower().strip()
        key = cls._SORT_ALIASES.get(key, key)
        if key not in cls.SORTS:
            raise HappyCowError(
                "Unknown sort_by {!r}; expected one of {} (aliases: {})."
                .format(sort_by, ", ".join(cls.SORTS),
                        ", ".join(sorted(cls._SORT_ALIASES))))
        return None if key == "default" else key

    @staticmethod
    def _csv_tokens(value):
        """Accept a CSV string or a list; return normalized match tokens."""
        if not value:
            return []
        items = value.split(",") if isinstance(value, str) else list(value)
        return [t for t in (_norm_token(i) for i in items) if t]

    @staticmethod
    def _parse_at(at):
        """Parse 'Sat 19:30' / 'sat 7:30pm' into (weekday, minute), or None."""
        if not at:
            return None
        m = re.match(
            r"\s*([A-Za-z]{3})[a-z]*[\s,]+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$",
            str(at), re.I)
        if not m or m.group(1).lower()[:3] not in _DAY_INDEX:
            raise HappyCowError(
                "Could not parse at={!r}; expected e.g. 'Sat 19:30' or "
                "'Sat 7:30pm'.".format(at))
        hour, minute = int(m.group(2)), int(m.group(3) or 0)
        if m.group(4):
            return (_DAY_INDEX[m.group(1).lower()[:3]],
                    _to_minutes(hour, minute, m.group(4)))
        return (_DAY_INDEX[m.group(1).lower()[:3]], hour * 60 + minute)

    def _collect_listings(self, city_url):
        if not self.refresh:
            cached = _cache_read("listing", city_url)
            # Listings cached before the price/top fields existed can't
            # serve price sorts — treat them as a miss.
            if cached is not None and all("price" in v for v in cached[:1]):
                # JSON round-trip turns coordinate tuples into lists.
                return [dict(v, coordinates=tuple(v["coordinates"]))
                        for v in cached]
        city_html = _http_get(self.session, city_url)
        lat, lng = extract_latlng(city_html)
        collected, seen = [], set()
        for page in range(1, self.max_pages + 1):
            url = "{}?lat={}&lng={}&page={}&s=3".format(
                LISTING_ENDPOINT, lat, lng, page)
            payload = _http_get(self.session, url, xhr=True, as_json=True)
            fragment = payload.get("data", "") if isinstance(payload, dict) else ""
            new = [v for v in parse_listing_fragment(fragment) if v["url"] not in seen]
            if not new:
                break  # last page reached
            for v in new:
                seen.add(v["url"])
            collected.extend(new)
            if self.request_delay:
                time.sleep(self.request_delay)
        for v in collected:
            v["distance_miles"] = self._distance_from(v, (lat, lng))
        if collected:
            _cache_write("listing", city_url, collected)
        return collected

    @staticmethod
    def _distance_from(venue, seed):
        try:
            return haversine_miles(seed[0], seed[1], *venue["coordinates"])
        except (TypeError, ValueError):
            return None

    # Seconds to wait before retrying a fetch the WAF answered with a
    # challenge page (a 200 with no microdata) instead of data.
    CHALLENGE_BACKOFF = 5.0

    def _fetch_detail(self, venue, force=False, fast=False):
        """Fetch (and cache) a venue's detail page.

        ``fast=True`` is the detail-scan mode: one attempt, no challenge
        backoff — a WAF-challenged venue is skipped cheaply and stays
        uncached so a later pass can pick it up. After several consecutive
        challenges the HTTP session is rotated (fresh TLS fingerprint +
        cookies), which usually clears the challenge streak."""
        if not (self.deep_crawl or force):
            return dict(_EMPTY_DETAIL)
        url = venue["url"]
        if url in self._detail_cache:
            return self._detail_cache[url]
        if not self.refresh:
            cached = _cache_read("venue", url)
            # Entries written before the cuisines/categories/features/price
            # fields existed can't serve those filters — treat as a miss.
            if cached is not None and "cuisines" in cached:
                self._detail_cache[url] = cached
                return cached
        for attempt in (1, 2):
            try:
                detail = parse_venue_detail(_http_get(self.session, url))
            except (HappyCowError, RequestException):
                detail = dict(_EMPTY_DETAIL)
            if detail != _EMPTY_DETAIL:
                self._challenge_streak = 0
                self._detail_cache[url] = detail
                _cache_write("venue", url, detail)
                return detail
            self._challenge_streak = getattr(self, "_challenge_streak", 0) + 1
            if self._challenge_streak >= 5:
                self.session = _new_session()  # rotate identity
                self._challenge_streak = 0
            if fast:
                break
            if attempt == 1:
                time.sleep(self.CHALLENGE_BACKOFF)  # let the WAF cool off
        return dict(_EMPTY_DETAIL)  # never cache failures

    @staticmethod
    def _rating_value(venue):
        try:
            return float(venue.get("rating", ""))
        except ValueError:
            return None

    @staticmethod
    def _chain_names(listings):
        """Names of non-veg businesses with 3+ locations in this listing
        (the app's 'Hide Chains' definition). Branch suffixes after ' - '
        are ignored when grouping."""
        from collections import Counter
        base = lambda v: _norm_token(v["name"].split(" - ")[0])
        counts = Counter(base(v) for v in listings)
        return {base(v) for v in listings
                if counts[base(v)] >= 3 and v["tag"] == "Veg-friendly"}

    def _apply_filters(self, listings):
        if self.type_filter:
            # Exact match: the app's restaurant veg-type chips. Vegan stores
            # and food trucks are venue_types/vegan_only territory.
            listings = [v for v in listings if v["tag"] == self.type_filter]
        if self.venue_types:
            listings = [v for v in listings
                        if any(t in _norm_token(v["tag"]) or
                               _norm_token(v["tag"]).endswith(t)
                               for t in self.venue_types)]
        if self.vegan_only:
            listings = [v for v in listings if v["tag"].startswith("Vegan")]
        if self.hide_chains:
            chains = self._chain_names(listings)
            listings = [v for v in listings
                        if _norm_token(v["name"].split(" - ")[0]) not in chains]
        if self.radius_miles:
            listings = [v for v in listings
                        if v["distance_miles"] is not None
                        and v["distance_miles"] <= self.radius_miles]
        if self.min_rating:
            listings = [v for v in listings
                        if self._rating_value(v) is not None
                        and self._rating_value(v) >= self.min_rating]
        return listings

    def _apply_sort(self, listings):
        if self.sort_by == "distance":
            return sorted(listings, key=lambda v: (
                v["distance_miles"] is None, v["distance_miles"] or 0))
        if self.sort_by == "rating":
            return sorted(listings, key=lambda v: (
                -(self._rating_value(v) or -1), -int(v["reviews"] or 0)))
        if self.sort_by == "name":
            return sorted(listings, key=lambda v: v["name"].lower())
        if self.sort_by == "veg":
            rank = {"Vegan": 0, "Vegetarian": 1, "Veg-friendly": 2}
            return sorted(listings, key=lambda v: (
                rank.get(v["tag"], 1 if v["tag"].startswith("Vegan") else 3),
                -(self._rating_value(v) or -1)))
        if self.sort_by in ("price_asc", "price_desc"):
            sign = 1 if self.sort_by == "price_asc" else -1
            return sorted(listings, key=lambda v: (
                v.get("price", 0) == 0, sign * v.get("price", 0)))
        if self.sort_by == "popularity":
            # "Top Rated" cards hide their review count; fill those (and only
            # those) from the venue page's reviewCount before ranking.
            for v in listings:
                if not v["reviews"] and self._rating_value(v) is not None:
                    detail = self._fetch_detail(v, force=True)
                    v["reviews"] = detail["reviews"] or v["reviews"]
            return sorted(listings, key=lambda v: -int(v["reviews"] or 0))
        return listings

    def _detail_predicates(self):
        """Predicates that need the venue detail page. Each takes a detail
        dict and returns True/False."""
        preds = []
        if self.cuisines:
            preds.append(lambda d: any(
                t in {_norm_token(c) for c in d["cuisines"]}
                for t in self.cuisines))
        if self.categories:
            preds.append(lambda d: any(
                t in {_norm_token(c) for c in d["categories"]}
                for t in self.categories))
        if self.features:
            preds.append(lambda d: all(
                any(t in _norm_token(f) for f in d["features"])
                for t in self.features))
        if self.open_now or self.at:
            if self.at:
                weekday, minute = self.at
            else:
                now = time.localtime()
                weekday, minute = now.tm_wday, now.tm_hour * 60 + now.tm_min
            preds.append(
                lambda d: is_open_at(d["hours"], weekday, minute) is True)
        return preds

    def _detail_scan(self, listings, preds):
        """Walk the (sorted) listings fetching details until max_results
        venues satisfy every detail predicate. Bounded by detail_scan_limit
        so a rare filter in a huge city can't scan forever."""
        wanted = self.max_results if self.max_results is not None else len(listings)
        matched, scanned = [], 0
        for v in listings:
            if len(matched) >= wanted or scanned >= self.detail_scan_limit:
                break
            scanned += 1
            detail = self._fetch_detail(v, force=True, fast=True)
            if detail == _EMPTY_DETAIL:
                continue  # challenged/blocked: skip cheaply, stays uncached
            if all(p(detail) for p in preds):
                matched.append(v)
        self.scan_truncated = (scanned >= self.detail_scan_limit
                               and len(matched) < wanted)
        return matched

    def _store(self, listings):
        if self.deep_crawl and len(listings) > 1:
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                details = list(pool.map(self._fetch_detail, listings))
        else:
            details = [self._fetch_detail(v) for v in listings]

        coordinates, names, tags, ratings, reviews = [], [], [], [], []
        addresses, phones, hours, cuisines, descriptions = [], [], [], [], []
        for venue, detail in zip(listings, details):
            self.processed_entries += 1
            if self.verbose:
                sys.stdout.write("\r\x1b[KProcessed: " + venue["name"])
                sys.stdout.flush()
            coordinates.append(venue["coordinates"])
            self.distances.append(venue.get("distance_miles"))
            names.append(normalize(venue["name"]))
            tags.append(normalize(venue["tag"]))
            # Prefer detail-page values; fall back to the listing card's own
            # rating/count/price (covers deep_crawl=False and blocked fetches).
            rating = detail["rating"]
            if rating == "unknown":
                rating = venue.get("rating", "unknown")
            ratings.append(rating)
            reviews.append(detail["reviews"] or venue.get("reviews", ""))
            self.prices.append(detail["price"] or venue.get("price", 0))
            self.venue_cuisines.append(list(detail["cuisines"]))
            self.venue_categories.append(list(detail["categories"]))
            self.venue_features.append(list(detail["features"]))
            addresses.append(normalize(detail["address"]))
            phones.append(normalize(detail["phone"]))
            hours.append(normalize(detail["hours"]))
            cuisines.append(normalize(detail["cuisine"]))
            descriptions.append(normalize(detail["description"]))
        if self.verbose:
            sys.stdout.write("\n")

        if self.target_file is not None:
            append_results_to_file(self.target_file, coordinates, names, tags,
                                   ratings, addresses, phones, hours, cuisines,
                                   descriptions)
        self.coordinates += coordinates
        self.names += names
        self.tags += tags
        self.ratings += ratings
        self.reviews += reviews
        self.addresses += addresses
        self.phone_numbers += phones
        self.opening_hours += hours
        self.descriptions += descriptions

    def crawl(self):
        """Crawl every configured city and populate the result columns."""
        if self.target_file is not None:
            write_header(self.target_file)
        for city_url in self.city_url:
            if self.verbose:
                print(city_url)
            listings = self._apply_filters(self._collect_listings(city_url))
            self.total_entries += len(listings)
            listings = self._apply_sort(listings)
            preds = self._detail_predicates()
            if preds:
                listings = self._detail_scan(listings, preds)
            elif self.max_results is not None:
                listings = listings[:self.max_results]
            self._store(listings)
        if self.target_file is not None:
            write_footer(self.target_file)
