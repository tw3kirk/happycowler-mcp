# -*- coding: utf-8 -*-
"""
HappyCow crawler/parser.

Rewritten (2026) for the current HappyCow site:
  * Fetching: the legacy ``incapsula-cracker`` approach is dead — HappyCow now
    sits behind Imperva/Incapsula. We render the page with headless Chrome
    (Playwright) in a subprocess (keeps Playwright's sync API out of any host
    asyncio loop) and parse the visible text, which is far more stable than the
    obfuscated, frequently-redesigned markup.
  * Parsing: ``parse_listing_text`` turns a city listing page's text into
    structured venue records.

The public ``HappyCowler`` class keeps its original attribute interface
(names, tags, ratings, addresses, phone_numbers, opening_hours, cuisines,
descriptions) so downstream callers (e.g. the MCP server) are unchanged.
"""
from __future__ import division, print_function

import os
import re
import subprocess
import sys

_FETCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fetch.py")

REST_CATS = {"Veg Options Restaurant", "Vegetarian Restaurant", "Vegan Restaurant"}
SHOP_CATS = {
    "Health Food Store", "Bakery", "Food Truck", "Other", "Vegan Professional",
    "Coffee Tea", "Juice Bar", "Market", "Cafe", "Catering", "Organization",
    "Vegan Store", "B&B", "Delivery",
}
STATUS = {"Open Now", "Closed", "Closing Soon", "Opening Soon",
          "Open 24 hrs", "Open 24 Hours"}
_BANNER = ("venues on HappyCow", "Vegan-Approved", "Help them grow")
_DELIMS = ("Read Reviews", "Add Review")
_SECTION = "Health Food Stores, Vegan Shops"
_PHONE_RE = re.compile(r"^\+?[\d][\d\-\s().]{5,}$")
_RATING_RE = re.compile(r"^\d+(\.\d+)?$")
_COUNT_RE = re.compile(r"^\(\d+\)$")
_START_RE = re.compile(r"^\s*\d+\s+Vegan\s*/\s*Vegetarian\s+Friendly\s+Restaurants\s*$")


_REGION_FIX = {
    "north-america": "north_america", "south-america": "south_america",
    "middle-east": "middle_east", "central-america": "central_america",
}


def normalize_url(url):
    """HappyCow uses underscores in multi-word region slugs (north_america).
    Accept the hyphenated form too and fix it."""
    for bad, good in _REGION_FIX.items():
        url = url.replace("/" + bad + "/", "/" + good + "/")
    return url


def _is_category(line):
    return line in REST_CATS or line in SHOP_CATS or line.endswith(" Restaurant")


def _normalize_type(raw):
    return {
        "Vegan Restaurant": "Vegan",
        "Vegetarian Restaurant": "Vegetarian",
        "Veg Options Restaurant": "Veg-friendly",
    }.get(raw, raw)


_STREET_RE = re.compile(
    r"\b(St|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|Pl|Place|Hwy|Highway|"
    r"Ste|Suite|Unit|Street|Ct|Court|Sq|Square|Pkwy|Pike|Trl|Trail)\b\.?", re.I)


def _looks_like_address(line):
    if "," not in line:
        return False
    if line[:1].isdigit():                       # street number
        return True
    if re.search(r"\b(Colorado|USA|United States)\b", line):
        return True
    if _STREET_RE.search(line):
        return True
    return False


def _looks_like_cuisine(line):
    if "," not in line:
        return False
    if line.endswith(".") or ". " in line:
        return False
    if _looks_like_address(line):
        return False
    return True


def _parse_chunk(chunk):
    """Turn one venue's lines into a record dict, or None if not a venue."""
    if len(chunk) < 2:
        return None
    ci = None
    for i in range(1, len(chunk)):           # skip name at index 0
        if _is_category(chunk[i]):
            ci = i
            break
    if ci is None:
        return None

    name = chunk[0]
    rating = "unknown"
    reviews = ""
    for line in chunk[1:ci]:
        if _RATING_RE.match(line):
            rating = line
        elif _COUNT_RE.match(line):
            reviews = line.strip("()")
    typ = _normalize_type(chunk[ci])

    j = ci + 1
    status = ""
    if j < len(chunk) and chunk[j] in STATUS:
        status = chunk[j]
        j += 1
    rest = chunk[j:]

    # phone (scan from end)
    phone = ""
    phone_idx = None
    for k in range(len(rest) - 1, -1, -1):
        if rest[k] == "Add a phone number":
            phone_idx = k
            break
        if _PHONE_RE.match(rest[k]):
            phone_idx, phone = k, rest[k]
            break
    rest2 = [x for i, x in enumerate(rest) if i != phone_idx] if phone_idx is not None else list(rest)

    # address (last address-like line)
    address = ""
    addr_idx = None
    for k in range(len(rest2) - 1, -1, -1):
        if _looks_like_address(rest2[k]):
            address, addr_idx = rest2[k], k
            break
    rest3 = [x for i, x in enumerate(rest2) if i != addr_idx] if addr_idx is not None else list(rest2)

    # cuisine + description
    cuisine, description = "", ""
    if rest3:
        if _looks_like_cuisine(rest3[0]):
            cuisine = rest3[0]
            description = " ".join(rest3[1:])
        else:
            description = " ".join(rest3)

    return {
        "name": name, "type": typ, "rating": rating, "reviews": reviews,
        "address": address, "phone": phone, "hours": status,
        "cuisine": cuisine, "description": description,
    }


def parse_listing_text(text):
    """Parse a HappyCow city listing page's visible text into venue records."""
    lines = text.split("\n")

    start = 0
    for i, line in enumerate(lines):
        if _START_RE.match(line):
            start = i + 1
            break
    else:
        for i, line in enumerate(lines):
            if line.strip().startswith("Find Vegan"):
                start = i + 1
                break

    end = len(lines)
    for i in range(start, len(lines)):
        s = lines[i].strip()
        if s.startswith("Note: For sorting") or s.startswith("Still hungry?"):
            end = i
            break

    venues, chunk = [], []
    for raw in lines[start:end]:
        s = raw.strip()
        if not s or s.startswith(_SECTION):
            continue
        if any(b in s for b in _BANNER) or s in ("All", "...are"):
            continue
        if s in _DELIMS:
            rec = _parse_chunk(chunk)
            if rec:
                venues.append(rec)
            chunk = []
            continue
        chunk.append(s)
    rec = _parse_chunk(chunk)
    if rec:
        venues.append(rec)
    return venues


def _render_text(url):
    """Fetch a HappyCow page's visible text via the Playwright subprocess."""
    try:
        proc = subprocess.run(
            [sys.executable, _FETCH, url],
            capture_output=True, text=True, timeout=150,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Timed out fetching HappyCow page")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Failed to fetch HappyCow page")
    return proc.stdout


class HappyCowler(object):
    """Crawl a HappyCow city listing page into structured lists."""

    def __init__(self, city_url, target_file=None, verbose=0):
        urls = city_url if isinstance(city_url, list) else [city_url]
        self.city_url = [normalize_url(u) for u in urls]
        self.target_file = target_file
        self.verbose = verbose
        self.coordinates = []
        self.names = []
        self.tags = []
        self.ratings = []
        self.reviews = []
        self.addresses = []
        self.phone_numbers = []
        self.opening_hours = []
        self.cuisines = []
        self.descriptions = []

    def crawl(self):
        for url in self.city_url:
            if self.verbose:
                print(url)
            for r in parse_listing_text(_render_text(url)):
                self.names.append(r["name"])
                self.tags.append(r["type"])
                self.ratings.append(r["rating"])
                self.reviews.append(r["reviews"])
                self.addresses.append(r["address"])
                self.phone_numbers.append(r["phone"])
                self.opening_hours.append(r["hours"])
                self.cuisines.append(r["cuisine"])
                self.descriptions.append(r["description"])
                self.coordinates.append(("", ""))
