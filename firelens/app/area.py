"""Geometry for FireLens: polygons, point-in-area tests and areas, in plain numpy.

Used by the app (district search, drawn areas) and tested in tests/test_area.py.
Coordinates are GeoJSON order: [longitude, latitude] in degrees (WGS 84).
"""

from __future__ import annotations

import numpy as np

KM_PER_DEGREE = 111.32


def polygons(geometry: dict) -> list:
    """Polygon coordinate lists from any geometry; stray lines and points are dropped."""
    kind = geometry["type"]
    if kind == "Polygon":
        return [geometry["coordinates"]]
    if kind == "MultiPolygon":
        return list(geometry["coordinates"])
    if kind == "GeometryCollection":
        return [p for part in geometry["geometries"] for p in polygons(part)]
    return []


def ring_contains(lon: np.ndarray, lat: np.ndarray, ring) -> np.ndarray:
    """Vectorised ray casting: which points lie inside one closed ring of [lon, lat]."""
    xy = np.asarray(ring, dtype=float)[:, :2]
    if len(xy) and (xy[0] != xy[-1]).any():
        xy = np.vstack([xy, xy[:1]])
    inside = np.zeros(len(lon), dtype=bool)
    for (x1, y1), (x2, y2) in zip(xy[:-1], xy[1:]):
        if y1 == y2:
            continue
        crosses = ((y1 > lat) != (y2 > lat)) & (lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1))
        inside ^= crosses
    return inside


def area_contains(geometry: dict, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """Points inside a Polygon or MultiPolygon (outside its holes)."""
    lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
    inside = np.zeros(len(lon), dtype=bool)
    for rings in polygons(geometry):
        outer = np.asarray(rings[0], dtype=float)[:, :2]
        box = ((lon >= outer[:, 0].min()) & (lon <= outer[:, 0].max())
               & (lat >= outer[:, 1].min()) & (lat <= outer[:, 1].max()))
        index = np.flatnonzero(box)
        if not len(index):
            continue
        hit = ring_contains(lon[index], lat[index], outer)
        for hole in rings[1:]:
            hit &= ~ring_contains(lon[index], lat[index], hole)
        inside[index[hit]] = True
    return inside


def area_km2(geometry: dict) -> float:
    """Approximate area: shoelace on longitude scaled by cos(latitude), good to ~1 % here."""
    total = 0.0
    for rings in polygons(geometry):
        for i, ring in enumerate(rings):
            xy = np.asarray(ring, dtype=float)[:, :2]
            if len(xy) < 3:
                continue
            x = xy[:, 0] * np.cos(np.radians(xy[:, 1].mean())) * KM_PER_DEGREE
            y = xy[:, 1] * KM_PER_DEGREE
            ring_area = 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))
            total += ring_area if i == 0 else -ring_area
    return total


def box_geometry(south: float, west: float, north: float, east: float) -> dict:
    """A latitude/longitude box as a GeoJSON polygon."""
    return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north],
                                                [west, north], [west, south]]]}


def valid_area(geometry) -> bool:
    try:
        return bool(polygons(geometry)) and area_km2(geometry) > 0
    except (KeyError, TypeError, ValueError, IndexError):
        return False
