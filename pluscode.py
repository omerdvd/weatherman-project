"""Decode Google Maps Plus Codes (Open Location Codes) into GPS coordinates.

Implements the Open Location Code algorithm (https://plus.codes) so the
service doesn't depend on any external geocoding API for this step. Short
codes (e.g. "V33Q+3Q5") omit the leading digits and need an approximate
reference location nearby to be recovered unambiguously.
"""

import math

CODE_ALPHABET = "23456789CFGHJMPQRVWX"
SEPARATOR = "+"
SEPARATOR_POSITION = 8
PADDING_CHAR = "0"
ENCODING_BASE = len(CODE_ALPHABET)
LATITUDE_MAX = 90
LONGITUDE_MAX = 180
GRID_COLUMNS = 4
GRID_ROWS = 5
PAIR_CODE_LENGTH = 10


class PlusCodeError(ValueError):
    pass


def is_short_code(code):
    if SEPARATOR not in code:
        raise PlusCodeError(f"Not a valid plus code (missing '{SEPARATOR}'): {code!r}")
    return code.index(SEPARATOR) < SEPARATOR_POSITION


def decode(code):
    """Decode a full plus code (e.g. '8FVC9G8F+6X') to (lat, lon)."""
    code = code.upper()
    clean = code.replace(SEPARATOR, "").replace(PADDING_CHAR, "")
    lo_lat = -LATITUDE_MAX
    lo_lon = -LONGITUDE_MAX
    lat_res = 400.0
    lon_res = 400.0
    digit = 0
    n = min(len(clean), PAIR_CODE_LENGTH)
    while digit < n:
        lat_res /= 20.0
        lon_res /= 20.0
        lo_lat += lat_res * CODE_ALPHABET.index(clean[digit])
        lo_lon += lon_res * CODE_ALPHABET.index(clean[digit + 1])
        digit += 2
    if len(clean) > PAIR_CODE_LENGTH:
        row_res = lat_res / GRID_ROWS
        col_res = lon_res / GRID_COLUMNS
        for ch in clean[PAIR_CODE_LENGTH:]:
            val = CODE_ALPHABET.index(ch)
            row = val // GRID_COLUMNS
            col = val % GRID_COLUMNS
            lo_lat += row * row_res
            lo_lon += col * col_res
            row_res /= GRID_ROWS
            col_res /= GRID_COLUMNS
        lat_res = row_res
        lon_res = col_res
    return lo_lat + lat_res / 2.0, lo_lon + lon_res / 2.0


def encode(lat, lon, code_length=10):
    lat += LATITUDE_MAX
    lon += LONGITUDE_MAX
    code = ""
    lat_res = 400.0
    lon_res = 400.0
    digit = 0
    while digit < min(code_length, PAIR_CODE_LENGTH):
        lat_res /= 20.0
        lon_res /= 20.0
        lat_digit = int(lat / lat_res)
        lon_digit = int(lon / lon_res)
        lat -= lat_digit * lat_res
        lon -= lon_digit * lon_res
        code += CODE_ALPHABET[lat_digit] + CODE_ALPHABET[lon_digit]
        digit += 2
        if digit == SEPARATOR_POSITION:
            code += SEPARATOR
    while len(code.replace(SEPARATOR, "")) < 8:
        code += PADDING_CHAR
    if len(code.replace(SEPARATOR, "")) == SEPARATOR_POSITION and SEPARATOR not in code:
        code += SEPARATOR
    return code


def recover_nearest(short_code, ref_lat, ref_lon):
    """Recover a short plus code's full coordinates using a nearby reference point."""
    short_code = short_code.upper()
    if SEPARATOR not in short_code:
        raise PlusCodeError(f"Not a valid plus code (missing '{SEPARATOR}'): {short_code!r}")
    padding_length = SEPARATOR_POSITION - short_code.index(SEPARATOR)
    if padding_length <= 0:
        return decode(short_code)
    resolution = ENCODING_BASE ** (2 - (padding_length // 2))
    half_res = resolution / 2.0
    rounded_lat = math.floor((ref_lat + LATITUDE_MAX) / resolution) * resolution - LATITUDE_MAX
    rounded_lon = math.floor((ref_lon + LONGITUDE_MAX) / resolution) * resolution - LONGITUDE_MAX

    best = None
    for cl in (rounded_lat, rounded_lat + resolution, rounded_lat - resolution):
        for co in (rounded_lon, rounded_lon + resolution, rounded_lon - resolution):
            center_lat = cl + half_res
            center_lon = co + half_res
            d = (center_lat - ref_lat) ** 2 + (center_lon - ref_lon) ** 2
            if best is None or d < best[0]:
                best = (d, cl, co)
    _, base_lat, base_lon = best
    prefix = encode(base_lat + half_res, base_lon + half_res, padding_length)[:padding_length]
    return decode(prefix + short_code)


def resolve(code, ref_lat=None, ref_lon=None):
    """Resolve any plus code to (lat, lon). Short codes require a reference point."""
    code = code.strip().upper()
    if is_short_code(code):
        if ref_lat is None or ref_lon is None:
            raise PlusCodeError(
                "This is a short plus code and needs an approximate reference "
                "location (nearby city or GPS coordinates) to decode accurately."
            )
        return recover_nearest(code, ref_lat, ref_lon)
    return decode(code)
