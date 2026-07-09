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
    venue_types: str = "",
    cuisines: str = "",
    categories: str = "",
    features: str = "",
    vegan_only: bool = False,
    hide_chains: bool = False,
    open_now: bool = False,
    at: str = "",
    refresh: bool = False,
) -> str:
    """Search vegan/vegetarian venues on HappyCow.net for a given city, with
    the full set of app-style sorts and filters.

    Sorting and filtering happen before max_results, so "top N by X" works.
    The first query for a city crawls it (slow, ~1 request/second politeness
    throttle); everything after runs from a 24h local cache and is fast.
    Filters marked [detail] below need venue pages: the first such query
    fetches them progressively (bounded scan) and caches them too.

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
            "name"        - alphabetical A->Z
            "veg"         - veg-friendliness: Vegan, then Vegetarian, then
                            veg-options (ties: rating)
            "price_asc" / "price_desc" - cheapest / priciest first ($..$$$;
                            venues without price info sort last)
        min_rating: Only return venues rated at least this many stars
            (e.g. 4.0). Unrated venues are dropped. 0 disables (default).
        radius_miles: Only return venues within this many miles of the city
            center (e.g. 50). 0 disables (default).
        venue_types: CSV of place types (default: restaurants and everything
            else). Values: restaurant veg-levels come from type_filter; here
            use e.g. "bakery", "coffee & tea", "ice cream", "juice bar",
            "food truck", "health store", "veg store", "delivery",
            "catering", "b&b", "farmers market", "market vendor",
            "organization", "spa", "other".
        cuisines: [detail] CSV of cuisines, e.g. "korean, thai, italian".
            Any listed cuisine matches. Full vocabulary: African, American,
            Asian, Australian, Brazilian, British, Caribbean, Chinese,
            European, French, Fusion, German, Indian, International, Italian,
            Japanese, Korean, Latin, Mediterranean, Mexican, Middle Eastern,
            Spanish, Taiwanese, Thai, Vietnamese, Western.
        categories: [detail] CSV of categories; any listed one matches.
            Vocabulary: Delivery, Take-out, Breakfast, Gluten-free, Organic,
            Pizza, Bakery, Beer/Wine, Buffet, Catering, Fast food, Juice Bar,
            Macrobiotic, Raw food, Salad Bar, Kosher.
        features: [detail] CSV; venue must have ALL listed features.
            Vocabulary: outdoor seating, reservation, wheelchair,
            credit cards, wi-fi.
        vegan_only: Only fully-vegan places (applies to stores/bakeries/etc.
            as well as restaurants — the app's "only show vegan places").
        hide_chains: Drop non-veg businesses with 3+ locations in this city
            (the app's "Hide Chains").
        open_now: [detail] Only venues open right now (uses this machine's
            local clock — accurate when searching your own timezone).
        at: [detail] Like open_now but for a specific local time, e.g.
            "Sat 19:30" or "Sun 11am". Venues with unparseable hours are
            treated as closed.
        refresh: Force a fresh crawl. By default results come from a local
            cache when the same city was crawled within the last 24 hours
            (sorts/filters still apply — they run on the cached data).
            Env overrides: HAPPYCOW_CACHE_TTL seconds (0 disables caching),
            HAPPYCOW_CACHE_DIR (default ~/.cache/happycowler).

    Returns:
        JSON array of restaurant objects. Each object contains:
          - name           (str): Restaurant name
          - type           (str): "Vegan", "Vegetarian", "Veg-friendly", or a
                                  store type like "Vegan Bakery"
          - rating         (str): Star rating like "4.5", "3.0", or "unknown"
          - reviews        (str): Number of reviews (e.g. "16"), or "" if none
          - price          (str): "$", "$$", "$$$", or "" if unknown
          - distance_miles (float|null): Miles from the city center
          - latitude       (str): Venue latitude
          - longitude      (str): Venue longitude
          - address        (str): Street address
          - phone          (str): Phone number
          - hours          (str): Opening hours summary
          - cuisines       (list): Cuisine tags, e.g. ["Asian", "Korean"]
          - categories     (list): Category tags, e.g. ["Take-out", "Kosher"]
          - features       (list): e.g. ["Accepts credit cards", "Wi-Fi"]
          - description    (str): Short description of the venue

        When a [detail] filter hits its scan bound before filling
        max_results, the array is wrapped as {"results": [...], "note": ...}.
        On error returns: {"error": "<message>"}
    """
    try:
        # Pass everything down so we only deep-crawl venues we'll return.
        hc = HappyCowler(city_url, type_filter=type_filter,
                         max_results=max_results, sort_by=sort_by,
                         min_rating=min_rating, radius_miles=radius_miles,
                         venue_types=venue_types, cuisines=cuisines,
                         categories=categories, features=features,
                         vegan_only=vegan_only, hide_chains=hide_chains,
                         open_now=open_now, at=at or None,
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
        if required_tag and tag != required_tag:
            continue
        restaurants.append({
            "name": _clean(hc.names[i]),
            "type": tag,
            "rating": hc.ratings[i],
            "reviews": hc.reviews[i],
            "price": "$" * hc.prices[i],
            "distance_miles": (round(hc.distances[i], 1)
                               if hc.distances[i] is not None else None),
            "latitude": hc.coordinates[i][0],
            "longitude": hc.coordinates[i][1],
            "address": _clean(hc.addresses[i]),
            "phone": _clean(hc.phone_numbers[i]),
            "hours": _clean(hc.opening_hours[i]),
            "cuisines": hc.venue_cuisines[i],
            "categories": hc.venue_categories[i],
            "features": hc.venue_features[i],
            "description": _clean(hc.descriptions[i]),
        })
        if len(restaurants) >= max_results:
            break

    if hc.scan_truncated:
        return json.dumps({
            "results": restaurants,
            "note": ("Detail-filter scan stopped at its bound before filling "
                     "max_results; more matches may exist deeper in the "
                     "listing. Narrow the search (radius/type) or re-run — "
                     "cached pages make each pass cheaper."),
        }, ensure_ascii=False, indent=2)
    return json.dumps(restaurants, ensure_ascii=False, indent=2)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
