"""Polygon geometry: area variants, zone-overlap inclusion boundary, ordering.

All assertions here are creation-time computed fields on DRAFT products; no
issuance is required (PRD §3.4 freezes them at creation).
"""

from test_helpers import (
    create_warning_draft,
    get_product,
    setup_office_with_storm,
)

# The byte-identical rectangle used for both area variants: centroid latitude
# exactly 60.0 degrees, where cos(60 deg) == 0.5 exactly (PRD §3.4).
RECTANGLE_AT_60 = {
    "vertices": [
        {"lat": 59.95, "lon": 0.0},
        {"lat": 59.95, "lon": 0.2},
        {"lat": 60.05, "lon": 0.2},
        {"lat": 60.05, "lon": 0.0},
    ]
}


def _warning_area(api, area_method, polygon):
    """Office with the given area_method + storm + one polygon warning draft;
    returns the freshly created draft body."""
    bundle = setup_office_with_storm(
        api,
        hazard_type="SEVERE_THUNDERSTORM",
        readings={"max_wind_mph": 60},
        office_overrides={"area_method": area_method},
    )
    return create_warning_draft(
        api,
        bundle.office,
        bundle.headers,
        bundle.storm,
        polygon=polygon,
        expires_at="2026-09-01T01:00:00Z",
    )


class TestPolygonAreaVariants:
    def test_polygon_area_planar_office_exact_area(self, api):
        """PRD §3.4: "Under the `PLANAR` method the cosine factor is 1.0 at all
        latitudes; under `GEODETIC` it is the cosine of the polygon centroid's
        latitude, so that at 60 degrees latitude the east-west extent is halved
        and the very same vertices yield a different area."
        PRD §3.4: "the final result is rounded half-up to 2 decimal places in a
        single rounding applied to the completed sum."

        Design: Difficulty/dual_variant_calc/polygon_area_planar_vs_geodetic_same_vertices
        """
        draft = _warning_area(api, "PLANAR", RECTANGLE_AT_60)
        # 0.2 deg x 111.0 km/deg = 22.2 km east-west; 0.1 deg = 11.1 km
        # north-south; 22.2 * 11.1 = 246.42 sq km.
        assert draft["polygon_area_sq_km"] == 246.42
        assert draft["status"] == "DRAFT" and draft["version"] == 1, (
            "the area is a creation-time computation, no issuance needed"
        )

    def test_polygon_area_geodetic_office_exact_area(self, api):
        """PRD §3.4: "Under the `PLANAR` method the cosine factor is 1.0 at all
        latitudes; under `GEODETIC` it is the cosine of the polygon centroid's
        latitude, so that at 60 degrees latitude the east-west extent is halved
        and the very same vertices yield a different area."

        Design: Difficulty/dual_variant_calc/polygon_area_planar_vs_geodetic_same_vertices
        """
        draft = _warning_area(api, "GEODETIC", RECTANGLE_AT_60)
        # cos(60 deg) = 0.5 halves the east-west extent: 11.1 km x 11.1 km.
        assert draft["polygon_area_sq_km"] == 123.21
        assert draft["polygon_area_sq_km"] != 246.42, (
            "byte-identical vertices diverge across area methods"
        )


class TestZoneOverlapInclusionBoundary:
    def test_overlap_pct_exactly_0100_includes_zone(self, api):
        """PRD §3.4: "A zone enters `resolved_zone_ids` exactly when that
        overlap percentage is at least 0.10 — ten percent of the zone's
        surveyed area — and mere point or edge contact, which yields zero
        overlap area, never qualifies a zone."
        PRD §3.4: "computing the clipped area, rounding it half-up to 2 decimal
        places first, then dividing by the zone's `surveyed_area_sq_km` and
        rounding the quotient half-up to 3 decimal places."

        Design: Difficulty/boundary_precision_check/overlap_pct_0100_included_0090_excluded
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 60}
        )
        # Clip width 0.01 deg = 1.11 km -> 12.321 -> 12.32 sq km;
        # 12.32 / 123.21 rounds to exactly 0.100 >= 0.10: included.
        polygon = {
            "vertices": [
                {"lat": 0.0, "lon": 0.0},
                {"lat": 0.0, "lon": 0.01},
                {"lat": 0.1, "lon": 0.01},
                {"lat": 0.1, "lon": 0.0},
            ]
        }
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            polygon=polygon, expires_at="2026-09-01T01:00:00Z",
        )
        product = get_product(api, draft["id"], bundle.headers)
        assert product["resolved_zone_ids"] == [bundle.zone["id"]]
        assert product["polygon_area_sq_km"] == 12.32

    def test_overlap_pct_0090_excludes_zone(self, api):
        """PRD §3.4: "A zone enters `resolved_zone_ids` exactly when that
        overlap percentage is at least 0.10 — ten percent of the zone's
        surveyed area — and mere point or edge contact, which yields zero
        overlap area, never qualifies a zone."

        Design: Difficulty/boundary_precision_check/overlap_pct_0100_included_0090_excluded
        """
        bundle = setup_office_with_storm(
            api,
            hazard_type="SEVERE_THUNDERSTORM",
            readings={"max_wind_mph": 60},
            zone_overrides={"lon_min": 0.2, "lon_max": 0.3, "zone_code": "ZOUT"},
        )
        # Clip width 0.009 deg = 0.999 km -> 11.0889 -> 11.09 sq km;
        # 11.09 / 123.21 rounds to 0.090 < 0.10: excluded.
        polygon = {
            "vertices": [
                {"lat": 0.0, "lon": 0.2},
                {"lat": 0.0, "lon": 0.209},
                {"lat": 0.1, "lon": 0.209},
                {"lat": 0.1, "lon": 0.2},
            ]
        }
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            polygon=polygon, expires_at="2026-09-01T01:00:00Z",
        )
        product = get_product(api, draft["id"], bundle.headers)
        assert product["resolved_zone_ids"] == []
        assert product["polygon_area_sq_km"] == 11.09
