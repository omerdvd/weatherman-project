"""Resolve a user-friendly city name to an IANA timezone identifier.

Most IANA zone IDs (e.g. "America/New_York", "Europe/London") already are a
representative city, so a substring search over the full zone list covers
most of the world. A curated alias table fills in well-known cities that
share a zone with another city and wouldn't otherwise match by name (e.g.
Tel Aviv and Jerusalem both use "Asia/Jerusalem").
"""

from zoneinfo import available_timezones

# city (lowercase) -> IANA zone, for cities that don't literally appear in
# the zone name they use.
CITY_ALIASES = {
    "tel aviv": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem",
    "haifa": "Asia/Jerusalem",
    "eilat": "Asia/Jerusalem",
    "beersheba": "Asia/Jerusalem",
    "washington": "America/New_York",
    "washington dc": "America/New_York",
    "boston": "America/New_York",
    "atlanta": "America/New_York",
    "miami": "America/New_York",
    "philadelphia": "America/New_York",
    "orlando": "America/New_York",
    "buffalo": "America/New_York",
    "rochester": "America/New_York",
    "syracuse": "America/New_York",
    "albany": "America/New_York",
    "pittsburgh": "America/New_York",
    "charlotte": "America/New_York",
    "raleigh": "America/New_York",
    "nashville": "America/Chicago",
    "memphis": "America/Chicago",
    "kansas city": "America/Chicago",
    "st louis": "America/Chicago",
    "milwaukee": "America/Chicago",
    "sacramento": "America/Los_Angeles",
    "san jose": "America/Los_Angeles",
    "fresno": "America/Los_Angeles",
    "portland": "America/Los_Angeles",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "salt lake city": "America/Denver",
    "albuquerque": "America/Denver",
    "toronto": "America/Toronto",
    "montreal": "America/Toronto",
    "ottawa": "America/Toronto",
    "vancouver": "America/Vancouver",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "las vegas": "America/Los_Angeles",
    "san diego": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "dallas": "America/Chicago",
    "austin": "America/Chicago",
    "minneapolis": "America/Chicago",
    "mexico city": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago",
    "bogota": "America/Bogota",
    "lima": "America/Lima",
    "london": "Europe/London",
    "manchester": "Europe/London",
    "birmingham": "Europe/London",
    "edinburgh": "Europe/London",
    "dublin": "Europe/Dublin",
    "paris": "Europe/Paris",
    "marseille": "Europe/Paris",
    "lyon": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "munich": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "hamburg": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "barcelona": "Europe/Madrid",
    "rome": "Europe/Rome",
    "milan": "Europe/Rome",
    "naples": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "vienna": "Europe/Vienna",
    "zurich": "Europe/Zurich",
    "geneva": "Europe/Zurich",
    "bern": "Europe/Zurich",
    "stockholm": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki",
    "warsaw": "Europe/Warsaw",
    "krakow": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "budapest": "Europe/Budapest",
    "athens": "Europe/Athens",
    "lisbon": "Europe/Lisbon",
    "porto": "Europe/Lisbon",
    "istanbul": "Europe/Istanbul",
    "ankara": "Europe/Istanbul",
    "moscow": "Europe/Moscow",
    "st petersburg": "Europe/Moscow",
    "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv",
    "bucharest": "Europe/Bucharest",
    "sofia": "Europe/Sofia",
    "cairo": "Africa/Cairo",
    "alexandria": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    "pretoria": "Africa/Johannesburg",
    "lagos": "Africa/Lagos",
    "abuja": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "addis ababa": "Africa/Addis_Ababa",
    "casablanca": "Africa/Casablanca",
    "dubai": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai",
    "riyadh": "Asia/Riyadh",
    "jeddah": "Asia/Riyadh",
    "doha": "Asia/Qatar",
    "kuwait city": "Asia/Kuwait",
    "amman": "Asia/Amman",
    "beirut": "Asia/Beirut",
    "tehran": "Asia/Tehran",
    "baghdad": "Asia/Baghdad",
    "karachi": "Asia/Karachi",
    "lahore": "Asia/Karachi",
    "islamabad": "Asia/Karachi",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "calcutta": "Asia/Kolkata",
    "dhaka": "Asia/Dhaka",
    "kathmandu": "Asia/Kathmandu",
    "colombo": "Asia/Colombo",
    "bangkok": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta",
    "bali": "Asia/Makassar",
    "singapore": "Asia/Singapore",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "manila": "Asia/Manila",
    "ho chi minh city": "Asia/Ho_Chi_Minh",
    "saigon": "Asia/Ho_Chi_Minh",
    "hanoi": "Asia/Ho_Chi_Minh",
    "phnom penh": "Asia/Phnom_Penh",
    "hong kong": "Asia/Hong_Kong",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai",
    "guangzhou": "Asia/Shanghai",
    "taipei": "Asia/Taipei",
    "seoul": "Asia/Seoul",
    "busan": "Asia/Seoul",
    "pyongyang": "Asia/Pyongyang",
    "tokyo": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "kyoto": "Asia/Tokyo",
    "yokohama": "Asia/Tokyo",
    "sydney": "Australia/Sydney",
    "canberra": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
    "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland",
    "christchurch": "Pacific/Auckland",
    "honolulu": "Pacific/Honolulu",
    "fiji": "Pacific/Fiji",
    "reykjavik": "Atlantic/Reykjavik",
}


def _norm(s):
    return s.strip().lower().replace("_", " ").replace("-", " ")


def search(query):
    """Return a list of candidate IANA zone IDs matching the given city name.

    Exact alias matches come first, then exact city-name matches, then
    substring matches (deduplicated, order preserved).
    """
    q = _norm(query)
    if not q:
        return []

    zones = sorted(available_timezones())
    results = []

    alias_hit = CITY_ALIASES.get(q)
    if alias_hit:
        results.append(alias_hit)

    exact = []
    partial = []
    for zone in zones:
        if zone == alias_hit:
            continue
        city = _norm(zone.rsplit("/", 1)[-1])
        if city == q:
            exact.append(zone)
        elif q in city or q in _norm(zone):
            partial.append(zone)

    for group in (exact, partial):
        for zone in group:
            if zone not in results:
                results.append(zone)

    return results
