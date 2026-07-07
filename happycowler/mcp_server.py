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
) -> str:
    """Search for vegan and vegetarian restaurants on HappyCow.net for a given city.

    Crawls the HappyCow city listing page and returns structured restaurant data
    including name, type, rating, address, phone, hours, cuisine, and description.

    HappyCow URL format:
        https://www.happycow.net/{region}/{country}/{city}/

    Common region slugs:
        europe, north_america, south_america, asia, africa, oceania, middle_east

    URL examples:
        Lima, Peru        -> https://www.happycow.net/south_america/peru/lima/
        Tokyo, Japan      -> https://www.happycow.net/asia/japan/tokyo/
        Berlin, Germany   -> https://www.happycow.net/europe/germany/berlin/
        New York, USA     -> https://www.happycow.net/north_america/usa/new-york/
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

    Returns:
        JSON array of restaurant objects. Each object contains:
          - name        (str): Restaurant name
          - type        (str): "Vegan", "Vegetarian", or "Veg-friendly"
          - rating      (str): Star rating like "4.5", "3.0", or "unknown"
          - reviews     (str): Number of reviews (e.g. "16"), or "" if none
          - address     (str): Street address
          - phone       (str): Phone number
          - hours       (str): Opening hours summary
          - cuisine     (str): Cuisine type(s)
          - description (str): Short description of the restaurant

        On error returns: {"error": "<message>"}
    """
    try:
        hc = HappyCowler(city_url)
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
