"""Corner — calculations: surge brackets, completion points floor, photo compliance, penalty cap, surcharge filter."""

from test_helpers import (
    set_clock,
    create_station,
    create_published_block,
    onboard_active_driver,
    run_surge_cycle,
    get_block,
    list_driver_rating_events,
    list_assignment_packages,
    complete_block_flow,
    complete,
)


class TestSurgeEscalationBoundary:
    def test_surge_escalation_boundary_at_exactly_120_minutes(self, api):
        """PRD §3.7: "Fourth — only when the station's `surge_enabled` is true — surge
        escalation runs over the station's `PUBLISHED` blocks whose start still lies in
        the future: the whole minutes remaining until start, flooring toward zero,
        select a multiplier bracket evaluated smallest first — 30 minutes or fewer sets
        `surge_multiplier_bp` to 17500, more than 30 up to and including 60 minutes sets
        15000, more than 60 up to and including 120 minutes sets 12500, and anything
        longer leaves the base 10000. The bracket boundary is inclusive, so exactly 120
        minutes still earns 12500 while 121 minutes does not."
        PRD §3.2: "Estimated pay is always the base pay multiplied by the surge
        multiplier in basis points and divided by 10000, rounded half-up to whole cents;
        it is recomputed on publish, on revise, and whenever a surge cycle adjusts the
        multiplier."

        Design: Corner/calculations/surge_escalation_boundary_at_exactly_120_minutes
        """
        set_clock()
        station = create_station()
        block_x = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )
        block_y = create_published_block(
            station["id"],
            starts_at="2026-09-01T02:01:00Z",
            ends_at="2026-09-01T04:00:00Z",
            base_pay_cents=4000,
        )

        # Clock 00:00: X starts in exactly 120 minutes; Y in 121 minutes.
        run_surge_cycle(station["id"], station["version"])

        bx = get_block(block_x["id"])
        by = get_block(block_y["id"])
        assert bx["surge_multiplier_bp"] == 12500
        assert bx["estimated_pay_cents"] == 5000
        assert by["surge_multiplier_bp"] == 10000
        assert by["estimated_pay_cents"] == 4000


class TestCompletionPointsFloor:
    def test_completion_points_floored_at_100(self, api):
        """PRD §3.6: "The rating points for a completion start from a perfect 500 and
        subtract for each defect: 100 points for each delivered package that was late
        (`on_time_delivery` false), 50 points for each delivered package whose photo was
        non-compliant (`photo_compliant` false), and 200 points for each package that
        ended the assignment `RETURNED_TO_STATION`. The result is floored at 100 — a
        disastrous route still contributes at least 100."
        PRD §3.6: "Every package still in `DELIVERY_FAILED` moves to
        `RETURNED_TO_STATION`."

        Design: Corner/calculations/completion_points_floored_at_100
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        # One late (-100) + one photo-noncompliant (-50) + one returned (-200):
        # raw 150, no floor needed; the second test drives raw below the floor.
        _b, _a, _ps, packages = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T13:00:00Z",
            base_pay_cents=5000,
            package_specs=[
                {
                    "tracking_code": "L-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T11:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T11:05:00Z",
                },
                {
                    "tracking_code": "L-2",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T11:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T10:30:00Z",
                    "photo_gps_tagged": False,
                },
                {
                    "tracking_code": "L-3",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T12:00:00Z",
                    "outcome": "failed",
                    "reason": "recipient refused",
                },
            ],
        )

        events = list_driver_rating_events(driver["id"])
        assert events[-1]["points"] == 150  # 500 - 100 - 50 - 200

        by_tracking = {row["tracking_code"]: row for row in packages}
        assert by_tracking["L-3"]["status"] == "RETURNED_TO_STATION"

    def test_completion_points_hit_floor_at_100(self, api):
        """PRD §3.6: "The rating points for a completion start from a perfect 500 and
        subtract for each defect: 100 points for each delivered package that was late
        (`on_time_delivery` false), 50 points for each delivered package whose photo was
        non-compliant (`photo_compliant` false), and 200 points for each package that
        ended the assignment `RETURNED_TO_STATION`. The result is floored at 100 — a
        disastrous route still contributes at least 100."

        Design: Corner/calculations/completion_points_floored_at_100
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        # One late (-100) + one photo-noncompliant (-50) + two returned (-400):
        # raw = 500 - 550 = -50, floored up to the 100-point minimum.
        _b, _a, _ps, packages = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T13:00:00Z",
            base_pay_cents=5000,
            package_specs=[
                {
                    "tracking_code": "L-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T11:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T11:05:00Z",
                },
                {
                    "tracking_code": "L-2",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T11:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T10:30:00Z",
                    "photo_gps_tagged": False,
                },
                {
                    "tracking_code": "L-3",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T12:00:00Z",
                    "outcome": "failed",
                    "reason": "recipient refused",
                },
                {
                    "tracking_code": "L-4",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T12:00:00Z",
                    "outcome": "failed",
                    "reason": "damaged in transit",
                },
            ],
        )

        events = list_driver_rating_events(driver["id"])
        assert events[-1]["points"] == 100


class TestPhotoCompliance:
    def test_photo_compliance_requires_url_and_gps_tag(self, api):
        """PRD §3.5: "Two compliance facts are computed and stored: `photo_compliant` is
        true exactly when `photo_url` is non-empty and `photo_gps_tagged` is true — an
        empty-string photo URL is permitted by the API but always counts as
        non-compliant — and `on_time_delivery` is true exactly when the delivery instant
        is at or before `promised_by`, with equality counting as on time."

        Design: Corner/calculations/photo_compliance_requires_url_and_gps_tag
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        _b, _a, _ps, packages = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T02:00:00Z",
            ends_at="2026-09-01T04:00:00Z",
            package_specs=[
                {
                    # empty URL with gps true: non-compliant
                    "tracking_code": "P-1",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T02:30:00Z",
                    "photo_url": "",
                    "photo_gps_tagged": True,
                },
                {
                    # both present: compliant
                    "tracking_code": "P-2",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T03:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T02:30:00Z",
                    "photo_url": "https://img.example/p2.jpg",
                    "photo_gps_tagged": True,
                },
            ],
        )

        by_tracking = {row["tracking_code"]: row for row in packages}
        assert by_tracking["P-1"]["photo_compliant"] is False
        assert by_tracking["P-2"]["photo_compliant"] is True


class TestPenaltyCap:
    def test_penalty_cap_binds_at_fifty_percent_of_gross_plus_bonus(self, api):
        """PRD §3.6: "Fourth, penalties are counted: 200 cents for each delivered
        package that was late, 150 cents for each delivered package with a non-compliant
        photo, and 500 cents for each package returned to the station. Fifth, the
        penalty total is capped at half of the gross plus tier bonus, rounded half-up,
        so `penalties_cents` is the smaller of the raw penalties and that cap. Finally,
        `final_pay_cents` is gross plus tier bonus plus surcharges minus the capped
        penalties."
        PRD §3.6: "Third, `surcharges_cents` is a per-package handling surcharge: for
        each package with status `DELIVERED`, the billable weight in kilograms is
        multiplied by 155 cents per kilogram and rounded half-up per package, and those
        per-package amounts are summed."

        Design: Corner/calculations/penalty_cap_binds_at_fifty_percent_of_gross_plus_bonus
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        specs = [
            {
                "tracking_code": f"F-{i}",
                "billable_weight_kg": 1.0,
                "promised_by": "2026-09-01T12:00:00Z",
                "outcome": "failed",
                "reason": "damaged",
            }
            for i in range(1, 7)
        ]
        _b, _a, ps, _pkgs = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T13:00:00Z",
            base_pay_cents=4000,
            package_specs=specs,
        )

        # raw penalties 6 * 500 = 3000; cap round_half_up(0.5 * 4000) = 2000 binds.
        assert ps["penalties_cents"] == 2000
        # surcharges count DELIVERED packages only — none here.
        assert ps["surcharges_cents"] == 0
        assert ps["final_pay_cents"] == 2000


class TestSurchargeFiltering:
    def test_surcharged_only_over_delivered_packages(self, api):
        """PRD §3.6: "Third, `surcharges_cents` is a per-package handling surcharge: for
        each package with status `DELIVERED`, the billable weight in kilograms is
        multiplied by 155 cents per kilogram and rounded half-up per package, and those
        per-package amounts are summed."
        PRD §3.6: "Finally, `final_pay_cents` is gross plus tier bonus plus surcharges
        minus the capped penalties."

        Design: Corner/calculations/surcharged_only_over_delivered_packages
        """
        set_clock()
        station = create_station()
        driver, vehicle, _s = onboard_active_driver()

        _b, _a, ps, _pkgs = complete_block_flow(
            station,
            driver,
            vehicle,
            starts_at="2026-09-01T10:00:00Z",
            ends_at="2026-09-01T13:00:00Z",
            base_pay_cents=4000,
            package_specs=[
                {
                    "tracking_code": "G-1",
                    "billable_weight_kg": 2.0,
                    "promised_by": "2026-09-01T12:00:00Z",
                    "outcome": "deliver",
                    "deliver_at": "2026-09-01T11:30:00Z",
                },
                {
                    "tracking_code": "G-2",
                    "billable_weight_kg": 1.0,
                    "promised_by": "2026-09-01T12:00:00Z",
                    "outcome": "failed",
                    "reason": "address not found",
                },
            ],
        )

        # Only the delivered 2.0kg package contributes: round_half_up(2.0 * 155) = 310.
        assert ps["surcharges_cents"] == 310
        # One returned package: 500 penalty (under the 2000 cap).
        assert ps["penalties_cents"] == 500
        assert ps["final_pay_cents"] == 3810  # 4000 + 0 + 310 - 500
