"""Cross-cutting corner claims: OCC on privacy-zone update, heat map cell
visibility under the erasure cascade."""

from test_helpers import (
    ApiErrorId,
    create_active_segment,
    create_athlete,
    create_privacy_zone,
    make_athlete_headers,
    upload_heatmap_ride,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_privacy_zone_payload


class TestOccStaleVersionOnZoneUpdate:
    def test_stale_expected_athlete_version_rejected(self, api):
        """PRD 2.7: "If that value does not match the athlete's current `version` — because another writer has already advanced the athlete aggregate since the client last read it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), and no zone or activity fields are changed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_zone_update
        """
        athlete = create_athlete(api, email="oc_o@x.com", display_name="OC O")
        zone = create_privacy_zone(api, athlete["id"], center_lat=37.0, center_lng=-122.0, radius_m=500)
        headers = make_athlete_headers(athlete["id"])
        observed = validate_success(api.get_athlete(athlete["id"], headers), 200)["version"]
        # Intervening write on the athlete aggregate: a successful geometry
        # update increments the athlete's `version` by one (PRD 3.3), so the
        # previously observed version is now stale.
        validate_success(
            api.update_privacy_zone(
                zone["id"],
                {"center_lat": 37.1, "center_lng": -122.1, "radius_m": 600, "expected_athlete_version": observed},
                headers,
            ),
            200,
        )
        resp = api.update_privacy_zone(
            zone["id"],
            {"center_lat": 37.5, "center_lng": -122.5, "radius_m": 800, "expected_athlete_version": observed},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Zone fields are unchanged after the stale write.
        zone_after = validate_success(api.get_privacy_zone(zone["id"], headers), 200)
        assert zone_after["radius_m"] == 600
        assert zone_after["center_lat"] == 37.1

    def test_fresh_expected_athlete_version_succeeds(self, api):
        """PRD 2.7: "the request must carry `expected_athlete_version`, a non-optional field holding the athlete's `version` as last observed by the client."
        PRD 3.3: "a successful update increments the athlete's `version` by one and recomputes obfuscation across all of the owner's activities".

        Design: Corner/cross_cutting_layers/occ_stale_version_on_zone_update
        """
        athlete = create_athlete(api, email="oc_p@x.com", display_name="OC P")
        zone = create_privacy_zone(api, athlete["id"], center_lat=37.0, center_lng=-122.0, radius_m=500)
        headers = make_athlete_headers(athlete["id"])
        observed = validate_success(api.get_athlete(athlete["id"], headers), 200)["version"]
        updated = validate_success(
            api.update_privacy_zone(
                zone["id"],
                {"center_lat": 37.5, "center_lng": -122.5, "radius_m": 800, "expected_athlete_version": observed},
                headers,
            ),
            200,
        )
        assert updated["radius_m"] == 800
        assert updated["center_lat"] == 37.5


class TestHeatmapCellDropsBelowMinOnAccountDeletion:
    def test_deletion_drops_cell_below_minimum(self, api):
        """PRD 3.1: "Every `COMPLETED` activity the athlete owns moves to `REJECTED`".
        PRD 3.8: "Counts are recomputed exactly — incremented on new uploads, decremented on exclusion cascades (flag upheld, account deletion, auto-hide)".
        PRD 3.8: "A cell surfaces publicly only once its `contribution_count` reaches 3".

        Design: Corner/cross_cutting_layers/heatmap_cell_drops_below_min_on_account_deletion
        """
        owner = create_athlete(api, email="hd0@x.com", display_name="HD0")
        segment = create_active_segment(
            api, owner["id"], name="Deletion Ride", sport_type="RIDE",
            start_lat=68.00, start_lng=-153.00, end_lat=68.01, end_lng=-153.00,
            distance_m=1000, city="Delville",
        )
        hd1 = create_athlete(api, email="hd1@x.com", display_name="HD1")
        hd2 = create_athlete(api, email="hd2@x.com", display_name="HD2")
        hd3 = create_athlete(api, email="hd3@x.com", display_name="HD3")
        upload_heatmap_ride(api, segment, hd1["id"], started_at="2026-09-01T06:00:00Z", idempotency_key="hd-1")
        upload_heatmap_ride(api, segment, hd2["id"], started_at="2026-09-01T07:00:00Z", idempotency_key="hd-2")
        upload_heatmap_ride(api, segment, hd3["id"], started_at="2026-09-01T08:00:00Z", idempotency_key="hd-3")
        reader = make_athlete_headers(hd2["id"])
        before = validate_success(api.get_heatmap(reader, params={"city": "Delville", "sport_type": "RIDE"}), 200)
        assert len(before) == 1
        assert before[0]["contribution_count"] == 3
        validate_success(api.delete_athlete(hd1["id"], make_athlete_headers(hd1["id"])), 200)
        after = validate_success(api.get_heatmap(reader, params={"city": "Delville", "sport_type": "RIDE"}), 200)
        assert after == []

    def test_cell_visible_at_exactly_three_contributions(self, api):
        """PRD 3.8: "A cell surfaces publicly only once its `contribution_count` reaches 3; the boundary is inclusive".

        Design: Corner/cross_cutting_layers/heatmap_cell_drops_below_min_on_account_deletion
        """
        owner = create_athlete(api, email="hd9@x.com", display_name="HD9")
        segment = create_active_segment(api, owner["id"], sport_type="RIDE", city="Edgeville")
        riders = [create_athlete(api) for _ in range(3)]
        for i, r in enumerate(riders):
            upload_heatmap_ride(api, segment, r["id"], started_at=f"2026-09-01T0{6 + i}:00:00Z")
        cells = validate_success(api.get_heatmap(make_athlete_headers(riders[0]["id"]), params={"city": "Edgeville", "sport_type": "RIDE"}), 200)
        assert len(cells) == 1
        assert cells[0]["contribution_count"] == 3
