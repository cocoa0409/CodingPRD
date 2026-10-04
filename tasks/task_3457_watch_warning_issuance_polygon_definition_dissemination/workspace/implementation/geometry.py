"""Polygon geometry: area, convexity, clipping, containment (PRD §3.4).

All area work happens in kilometer space; the issuing office's area_method
selects the east-west cosine factor (PLANAR: 1.0, GEODETIC: cos(centroid lat)).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from constants import KM_PER_DEG
from util import round_half_up_dec

_EPS = 1e-12


def cos_factor(vertices, area_method):
    if area_method == "GEODETIC":
        centroid_lat = sum(v["lat"] for v in vertices) / len(vertices)
        return math.cos(math.radians(centroid_lat))
    return 1.0


def to_km(vertices, area_method):
    cf = cos_factor(vertices, area_method)
    return [(v["lon"] * KM_PER_DEG * cf, v["lat"] * KM_PER_DEG) for v in vertices]


def shoelace(points):
    if len(points) < 3:
        return 0.0
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def polygon_area_sq_km(vertices, area_method):
    """Raw (unrounded) shoelace area in km^2."""
    return shoelace(to_km(vertices, area_method))


# ---------------------------------------------------------------------------
# validity: simple (non-self-intersecting), convex, non-degenerate
# ---------------------------------------------------------------------------
def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _proper_intersection(p1, p2, p3, p4):
    d1 = _cross(p3, p4, p1)
    d2 = _cross(p3, p4, p2)
    d3 = _cross(p1, p2, p3)
    d4 = _cross(p1, p2, p4)
    return ((d1 > _EPS) != (d2 > _EPS)) and ((d3 > _EPS) != (d4 > _EPS)) \
        and abs(d1) > _EPS and abs(d2) > _EPS and abs(d3) > _EPS and abs(d4) > _EPS


def is_simple_convex_nondegenerate(vertices):
    pts = [(v["lon"], v["lat"]) for v in vertices]
    n = len(pts)
    if n < 3:
        return False
    # self-intersection between non-adjacent edges
    for i in range(n):
        a1, a2 = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            if (i + 1) % n == j or (j + 1) % n == i:
                continue
            b1, b2 = pts[j], pts[(j + 1) % n]
            if _proper_intersection(a1, a2, b1, b2):
                return False
    # convexity: every turn same direction (collinear turns tolerated)
    sign = 0
    for i in range(n):
        c = _cross(pts[i], pts[(i + 1) % n], pts[(i + 2) % n])
        if abs(c) < _EPS:
            continue
        s = 1 if c > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    # non-degenerate: non-zero area
    if shoelace(pts) < _EPS:
        return False
    return True


# ---------------------------------------------------------------------------
# Sutherland-Hodgman clip of a convex polygon to an axis-aligned rectangle,
# both already in km space.
# ---------------------------------------------------------------------------
def _clip_edge(poly, inside, intersect):
    if not poly:
        return []
    out = []
    prev = poly[-1]
    prev_in = inside(prev)
    for cur in poly:
        cur_in = inside(cur)
        if cur_in:
            if not prev_in:
                out.append(intersect(prev, cur))
            out.append(cur)
        elif prev_in:
            out.append(intersect(prev, cur))
        prev, prev_in = cur, cur_in
    return out


def clip_to_rect_km(points, xmin, ymin, xmax, ymax):
    def ix(a, b, x):
        if abs(b[0] - a[0]) < _EPS:
            return (x, a[1])
        t = (x - a[0]) / (b[0] - a[0])
        return (x, a[1] + t * (b[1] - a[1]))

    def iy(a, b, y):
        if abs(b[1] - a[1]) < _EPS:
            return (a[0], y)
        t = (y - a[1]) / (b[1] - a[1])
        return (a[0] + t * (b[0] - a[0]), y)

    poly = _clip_edge(points, lambda p: p[0] >= xmin - _EPS, lambda a, b: ix(a, b, xmin))
    poly = _clip_edge(poly, lambda p: p[0] <= xmax + _EPS, lambda a, b: ix(a, b, xmax))
    poly = _clip_edge(poly, lambda p: p[1] >= ymin - _EPS, lambda a, b: iy(a, b, ymin))
    poly = _clip_edge(poly, lambda p: p[1] <= ymax + _EPS, lambda a, b: iy(a, b, ymax))
    return poly


def zone_overlap(vertices, zone, area_method):
    """Pinned rounding order (PRD §3.4): clipped area rounded to 2dp FIRST,
    then divided by surveyed area and rounded to 3dp. Returns
    (overlap_sq_km: Decimal 2dp, overlap_pct: Decimal 3dp)."""
    cf = cos_factor(vertices, area_method)
    pts = to_km(vertices, area_method)
    xmin = zone["lon_min"] * KM_PER_DEG * cf
    xmax = zone["lon_max"] * KM_PER_DEG * cf
    ymin = zone["lat_min"] * KM_PER_DEG
    ymax = zone["lat_max"] * KM_PER_DEG
    clipped = clip_to_rect_km(pts, xmin, ymin, xmax, ymax)
    area = shoelace(clipped)
    area_r = round_half_up_dec(area, 2)
    surveyed = zone.get("surveyed_area_sq_km") or 0
    if surveyed <= 0:
        return area_r, Decimal("0.000")
    pct = (area_r / Decimal(repr(float(surveyed)))).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    return area_r, pct


# ---------------------------------------------------------------------------
# point-in-polygon (verification matching); boundary counts as inside
# ---------------------------------------------------------------------------
def point_in_polygon(lat, lon, vertices):
    poly = [(v["lat"], v["lon"]) for v in vertices]
    n = len(poly)
    p = (lat, lon)

    def on_segment(a, b):
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if abs(cross) > 1e-9:
            return False
        return (
            min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
            and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9
        )

    for i in range(n):
        if on_segment(poly[i], poly[(i + 1) % n]):
            return True

    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat):
            x_int = xi + (xj - xi) * (lat - yi) / (yj - yi)
            if lon < x_int:
                inside = not inside
        j = i
    return inside
