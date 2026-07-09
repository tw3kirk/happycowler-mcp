# -*- coding: utf-8 -*-
"""
MCP server exposing HappyCow restaurant search as a tool for LLM chatbots.
"""
import html
import json

from mcp.server.fastmcp import FastMCP

from happycowler import HappyCowler

mcp = FastMCP("HappyCowler")


def _clean(text):
    """Reverse the XML escaping applied by normalize() so JSON output is clean."""
    return html.unescape(text).strip()


@mcp.tool()
def search_restaurants(
    city_url: str,
    type_filter: str = "all",
    max_results: int = 50,
    sort_by: str = "default",
    min_rating: float = 0,
    radius_miles: float = 0,
    refresh: bool = False,
) -> str:
    """Search for vegan and vegetarian restaurants on HappyCow.net for a given city.

    Crawls the HappyCow city listing page and returns structured restaurant data
    including name, type, rating, review count, distance, address, phone, hours,
    and description. Supports sorting (distance / rating / popularity) and
    filtering (type / minimum stars / radius); sorting and filtering happen
    before max_results, so "top N by X" queries work as expected.

    HappyCow URL format:
        https://www.happycow.net/{region}/{country}/{city}/

    Common region slugs (note: multi-word regions use an UNDERSCORE, not a
    hyphen — e.g. south_america; a hyphen returns HTTP 404):
        europe, north_america, south_america, asia, africa, oceania, middle_east

    URL examples:
        Lima, Peru        -> https://www.happycow.net/south_america/peru/lima/
        Tokyo, Japan      -> https://www.happycow.net/asia/japan/tokyo/
        Berlin, Germany   -> https://www.happycow.net/europe/germany/berlin/
        New York City     -> https://www.happycow.net/north_america/usa/new_york/new_york_city/
                             (US cities nest under their state; underscores throughout)
        London, UK        -> https://www.happycow.net/europe/england/london/
        Sydney, Australia -> https://www.happycow.net/oceania/australia/sydney/
        Bangkok, Thailand -> https://www.happycow.net/asia/thailand/bangkok/
        Mexico City       -> https://www.happycow.net/north_america/mexico/mexico-city/

    Args:
        city_url: Full HappyCow URL for the city listing page.
        type_filter: Filter by restaurant type. One of:
            "all"          - all vegan, vegetarian, and veg-friendly places (default)
            "vegan"        - fully vegan restaurants only
            "vegetarian"   - vegetarian restaurants (may serve dairy/eggs)
            "veg-friendly" - restaurants with good vegan/vegetarian options
        max_results: Maximum number of restaurants to return (default 50).
        sort_by: Result ordering. One of:
            "default"     - HappyCow's own listing order
            "distance"    - nearest to the city center first
            "rating"      - highest star rating first (ties: more reviews first)
            "popularity"  - most-reviewed first
        min_rating: Only return venues rated at least this many stars
            (e.g. 4.0). Unrated venues are dropped. 0 disables (default).
        radius_miles: Only return venues within this many miles of the city
            center (e.g. 50). 0 disables (default).
        refresh: Force a fresh crawl. By default results come from a local
            cache when the same city was crawled within the last 24 hours
            (sorts/filters still apply — they run on the cached data).
            Env overrides: HAPPYCOW_CACHE_TTL seconds (0 disables caching),
            HAPPYCOW_CACHE_DIR (default ~/.cache/happycowler).

    Returns:
        JSON array of restaurant objects. Each object contains:
          - name           (str): Restaurant name
          - type           (str): "Vegan", "Vegetarian", or "Veg-friendly"
          - rating         (str): Star rating like "4.5", "3.0", or "unknown"
          - reviews        (str): Number of reviews (e.g. "16"), or "" if none
          - distance_miles (float|null): Miles from the city center
          - latitude       (str): Venue latitude
          - longitude      (str): Venue longitude
          - address        (str): Street address
          - phone          (str): Phone number
          - hours          (str): Opening hours summary
          - cuisine        (str): Cuisine type(s)
          - description    (str): Short description of the restaurant

        On error returns: {"error": "<message>"}
    """
    try:
        # Pass everything down so we only deep-crawl venues we'll return.
        hc = HappyCowler(city_url, type_filter=type_filter,
                         max_results=max_results, sort_by=sort_by,
                         min_rating=min_rating, radius_miles=radius_miles,
                         refresh=refresh)
        hc.crawl()
    except Exception as exc:
        return json.dumps({"error": str(exc)})

    type_filter_lower = type_filter.lower()
    type_map = {
        "vegan": "Vegan",
        "vegetarian": "Vegetarian",
        "veg-friendly": "Veg-friendly",
    }
    required_tag = type_map.get(type_filter_lower)

    restaurants = []
    for i in range(len(hc.names)):
        tag = _clean(hc.tags[i])
        if required_tag and required_tag not in tag:
            continue
        restaurants.append({
            "name": _clean(hc.names[i]),
            "type": tag,
            "rating": hc.ratings[i],
            "reviews": hc.reviews[i],
            "distance_miles": (round(hc.distances[i], 1)
                               if hc.distances[i] is not None else None),
            "latitude": hc.coordinates[i][0],
            "longitude": hc.coordinates[i][1],
            "address": _clean(hc.addresses[i]),
            "phone": _clean(hc.phone_numbers[i]),
            "hours": _clean(hc.opening_hours[i]),
            "cuisine": _clean(hc.cuisines[i]),
            "description": _clean(hc.descriptions[i]),
        })
        if len(restaurants) >= max_results:
            break

    return json.dumps(restaurants, ensure_ascii=False, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
