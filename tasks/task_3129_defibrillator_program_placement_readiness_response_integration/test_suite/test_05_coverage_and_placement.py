"""Coverage reporting and placement planning: dual response-time variants,
per-zone-then-sum rounding, and the inclusive target boundary.

Design: Difficulty/dual_variant_calc/response_time_straight_line_vs_walk_path_diverge,
        Difficulty/combinatorial_formula/coverage_score_mode_b_per_zone_then_sum_rounding,
        Difficulty/boundary_precision_check/response_time_target_equality_boundary,
        Corner/endpoints/coverage_report_returns_per_zone_and_aggregate,
        Corner/endpoints/paginated_device_list_filter_by_readiness_posture.
"""

from test_helpers import (
    create_cabinet,
    create_campus,
    create_device,
    create_device_model,
    create_zone,
    set_clock,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]


def _zone_entry(report, zone_id):
    for entry in report["per_zone"]:
        if entry.get("zone_id") == zone_id:
            return entry
    raise AssertionError(
        f"per_zone has no entry for zone {zone_id}: {report['per_zone']!r}"
    )


class TestResponseTimeVariantDivergence:

    def test_straight_line_and_walk_path_diverge_for_same_cabinet(self, api):
        """PRD: "The response-time estimate between a zone's centroid and a
        cabinet is computed in two pinned variants that deliberately produce
        different numbers for the same inputs." PRD: "The **optimistic,
        straight-line variant** — used for placement plan drafts — takes the
        distance as the Euclidean straight line: the square root of the sum of
        the squared horizontal and vertical offsets, with no obstruction
        adjustment. The **pessimistic, walk-path variant** — used for compliance
        attestation — takes the distance as the Manhattan walk path: the
        horizontal offset plus the vertical offset, multiplied by a 1.30
        obstruction multiplier."

        Design: Difficulty/dual_variant_calc/response_time_straight_line_vs_walk_path_diverge
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus(response_time_target_seconds=120)
        zone = create_zone(campus["id"], zone_code="Z1",
                           avg_walk_speed_mps=1.5, requires_elevator=False,
                           elevator_delay_seconds=0)
        cabinet = create_cabinet(zone["id"], location_label="L1",
                                 centroid_x_m=100.0, centroid_y_m=100.0)

        report = validate_success(api.get_coverage_report(campus["id"], PM))
        entry = _zone_entry(report, zone["id"])

        # Optimistic: round_half_up(sqrt(100^2+100^2) / 1.5) = round(94.28) = 94.
        assert entry["optimistic_response_time_seconds"] == 94
        # Pessimistic: round_half_up((100+100) * 1.30 / 1.5) = round(173.33) = 173.
        assert entry["pessimistic_response_time_seconds"] == 173
        assert entry["optimistic_response_time_seconds"] != entry[
            "pessimistic_response_time_seconds"
        ]

    def test_pessimistic_variant_gates_zone_coverage_not_optimistic(self, api):
        """PRD: "A zone counts as covered when it has at least one cabinet whose
        pessimistic, walk-path response time from the zone centroid is at or
        below the campus's `response_time_target_seconds`."

        Design: Difficulty/dual_variant_calc/response_time_straight_line_vs_walk_path_diverge
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus(response_time_target_seconds=120)
        zone = create_zone(campus["id"], zone_code="Z1",
                           avg_walk_speed_mps=1.5, requires_elevator=False,
                           elevator_delay_seconds=0)
        create_cabinet(zone["id"], location_label="L1",
                       centroid_x_m=100.0, centroid_y_m=100.0)

        report = validate_success(api.get_coverage_report(campus["id"], PM))
        entry = _zone_entry(report, zone["id"])
        # Optimistic 94 <= 120 but pessimistic 173 > 120: NOT covered.
        assert entry["optimistic_response_time_seconds"] == 94
        assert entry["pessimistic_response_time_seconds"] == 173
        assert entry["covered"] in (0, False)
        assert report["coverage_pct"] == 0


class TestCoveragePerZoneThenSum:

    def test_two_of_three_zones_covered_yields_67_percent(self, api):
        """PRD: "The campus `coverage_pct` is computed in a pinned order: each
        zone first contributes a whole 1 when covered or 0 when not; those
        per-zone integers are summed; the sum is multiplied by 100 and divided
        by the total number of zones; and the result is rounded half-up exactly
        once at that final step to an integer percent."

        Design: Difficulty/combinatorial_formula/coverage_score_mode_b_per_zone_then_sum_rounding
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus(response_time_target_seconds=100)
        za = create_zone(campus["id"], zone_code="ZA", avg_walk_speed_mps=1.5,
                         requires_elevator=False, elevator_delay_seconds=0)
        zb = create_zone(campus["id"], zone_code="ZB", avg_walk_speed_mps=1.5,
                         requires_elevator=False, elevator_delay_seconds=0)
        zc = create_zone(campus["id"], zone_code="ZC", avg_walk_speed_mps=1.5,
                         requires_elevator=False, elevator_delay_seconds=0)
        # Zones A/B: manhattan 10 -> 10*1.3/1.5 = 8.667 -> round_half_up = 9s.
        create_cabinet(za["id"], location_label="LA",
                       centroid_x_m=10.0, centroid_y_m=0.0)
        create_cabinet(zb["id"], location_label="LB",
                       centroid_x_m=10.0, centroid_y_m=0.0)
        # Zone C: manhattan 200 -> 200*1.3/1.5 = 173.33 -> 173s.
        create_cabinet(zc["id"], location_label="LC",
                       centroid_x_m=200.0, centroid_y_m=0.0)

        report = validate_success(api.get_coverage_report(campus["id"], PM))
        assert _zone_entry(report, za["id"])["covered"] in (1, True)
        assert _zone_entry(report, zb["id"])["covered"] in (1, True)
        assert _zone_entry(report, zc["id"])["covered"] in (0, False)
        # 2 * 100 / 3 = 66.67 -> round_half_up = 67.
        assert report["coverage_pct"] == 67

    def test_one_of_six_zones_covered_yields_17_percent(self, api):
        """PRD: "each zone first contributes a whole 1 when covered or 0 when
        not; those per-zone integers are summed; the sum is multiplied by 100
        and divided by the total number of zones; and the result is rounded
        half-up exactly once at that final step to an integer percent.
        Computing fractional per-zone coverage first and rounding the sum is
        not the same calculation and is not acceptable."

        Design: Difficulty/combinatorial_formula/coverage_score_mode_b_per_zone_then_sum_rounding
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus(response_time_target_seconds=100)
        zones = [
            create_zone(campus["id"], zone_code=f"Z{i}", avg_walk_speed_mps=1.5,
                        requires_elevator=False, elevator_delay_seconds=0)
            for i in range(6)
        ]
        # Only zone 0 gets a cabinet inside the target (9s <= 100s).
        create_cabinet(zones[0]["id"], location_label="L0",
                       centroid_x_m=10.0, centroid_y_m=0.0)
        report = validate_success(api.get_coverage_report(campus["id"], PM))
        # 1 * 100 / 6 = 16.67 -> round_half_up = 17.
        assert report["coverage_pct"] == 17
        assert _zone_entry(report, zones[0]["id"])["covered"] in (1, True)
        for z in zones[1:]:
            assert _zone_entry(report, z["id"])["covered"] in (0, False)


class TestCoverageTargetBoundary:

    def test_pessimistic_equal_to_target_is_covered_one_second_over_is_not(self, api):
        """PRD: "A zone counts as covered when it has at least one cabinet whose
        pessimistic, walk-path response time from the zone centroid is at or
        below the campus's `response_time_target_seconds`."

        Design: Difficulty/boundary_precision_check/response_time_target_equality_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus(response_time_target_seconds=9)
        za = create_zone(campus["id"], zone_code="ZA", avg_walk_speed_mps=1.5,
                         requires_elevator=False, elevator_delay_seconds=0)
        zb = create_zone(campus["id"], zone_code="ZB", avg_walk_speed_mps=1.5,
                         requires_elevator=False, elevator_delay_seconds=0)
        # Zone A: manhattan 10 -> 8.667 -> round_half_up 9s == target (covered).
        create_cabinet(za["id"], location_label="LA",
                       centroid_x_m=10.0, centroid_y_m=0.0)
        # Zone B: manhattan 12 -> 10.4 -> round_half_up 10s > target (not).
        create_cabinet(zb["id"], location_label="LB",
                       centroid_x_m=12.0, centroid_y_m=0.0)

        report = validate_success(api.get_coverage_report(campus["id"], PM))
        entry_a = _zone_entry(report, za["id"])
        entry_b = _zone_entry(report, zb["id"])
        assert entry_a["pessimistic_response_time_seconds"] == 9
        assert entry_a["covered"] in (1, True)
        assert entry_b["pessimistic_response_time_seconds"] == 10
        assert entry_b["covered"] in (0, False)
        # 1 * 100 / 2 = 50.
        assert report["coverage_pct"] == 50

    def test_one_second_below_target_is_covered(self, api):
        """PRD: "A zone counts as covered when it has at least one cabinet whose
        pessimistic, walk-path response time from the zone centroid is at or
        below the campus's `response_time_target_seconds`."

        Design: Difficulty/boundary_precision_check/response_time_target_equality_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus(response_time_target_seconds=10)
        za = create_zone(campus["id"], zone_code="ZA", avg_walk_speed_mps=1.5,
                         requires_elevator=False, elevator_delay_seconds=0)
        # manhattan 10 -> 9s <= 10s target: covered.
        create_cabinet(za["id"], location_label="LA",
                       centroid_x_m=10.0, centroid_y_m=0.0)
        report = validate_success(api.get_coverage_report(campus["id"], PM))
        entry_a = _zone_entry(report, za["id"])
        assert entry_a["pessimistic_response_time_seconds"] == 9
        assert entry_a["covered"] in (1, True)
        assert report["coverage_pct"] == 100


class TestCoverageReportShape:

    def test_report_has_coverage_pct_and_per_zone_array(self, api):
        """PRD: "The report expresses, for each zone, whether that zone is
        covered, and rolls the per-zone results up into a single integer
        `coverage_pct` for the campus alongside a `per_zone` array of per-zone
        detail."

        Design: Corner/endpoints/coverage_report_returns_per_zone_and_aggregate
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus()
        zone = create_zone(campus["id"], zone_code="Z")
        create_cabinet(zone["id"], location_label="L")
        report = validate_success(api.get_coverage_report(campus["id"], PM))
        assert isinstance(report["coverage_pct"], int)
        assert isinstance(report["per_zone"], list)
        assert len(report["per_zone"]) == 1


class TestDeviceListReadinessFilter:

    def test_readiness_posture_filter_returns_matching_devices_only(self, api):
        """PRD (endpoint table): "GET | `/api/devices` | List Devices,
        filterable by `campus_id`, `cabinet_id`, `device_model_id`, `status`,
        `readiness_posture`". PRD: "A freshly registered device starts with
        lifecycle `status` equal to `REGISTERED`, ... and — because it has no
        consumables — with `readiness_posture` equal to `OUT_OF_SERVICE`".

        Design: Corner/endpoints/paginated_device_list_filter_by_readiness_posture
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus = create_campus()
        create_device(campus["id"], model["id"], serial_number="SN-F-1")
        create_device(campus["id"], model["id"], serial_number="SN-F-2")

        ready, meta_ready = validate_paginated(
            api.list_devices(PM, params={"campus_id": campus["id"],
                                         "readiness_posture": "READY"})
        )
        assert ready == []
        assert meta_ready["total_count"] == 0

        oos, meta_oos = validate_paginated(
            api.list_devices(PM, params={"campus_id": campus["id"],
                                         "readiness_posture": "OUT_OF_SERVICE"})
        )
        assert len(oos) == 2
        assert meta_oos["total_count"] == 2
