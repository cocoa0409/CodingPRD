"""Combinatorial formulas: floor-per-station-then-sum rounding order, and the
coverage score's nested min/cap/weighted-sum interaction."""

from test_helpers import (
    TEST_USERS,
    confirm_agreement,
    create_agreement,
    create_authorized_volunteer,
    create_event,
    create_event_site_locked,
    create_vetted_site,
    get_success_data,
    setup_station,
    submit_agreement,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
SL = TEST_USERS["station_lead_headers"]


class TestThroughputRoundPerStationThenSum:
    def test_floor_applied_per_station_before_summing(self, api):
        """PRD §2.8: "the station-throughput projection floors each station's
        contribution *before* summing, never after." Two 5-chair stations at a
        100-minute window and 30 minutes per patient contribute
        floor(5*100/30)=16 each, totalling 32; sum-then-floor would give 33.

        Design: Difficulty/combinatorial_formula/throughput_round_per_station_then_sum_pinned
        """
        site = create_vetted_site(
            site_type="SCHOOL", state_code="VA", square_footage=8000
        )
        event = create_event(
            host_state_code="VA",
            service_date="2026-10-10",
            doors_open_utc="2026-10-10T10:00:00Z",
            total_patient_capacity=200,
        )
        agreement = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site["id"],
            liability_cap_cents=5_000_000,
        )
        submit_agreement(event["id"], agreement["id"])
        confirm_agreement(event["id"], agreement["id"])
        station_payload = {
            "station_type": "DENTAL",
            "chair_count": 5,
            "minutes_per_patient": 30,
            "requires_sterilization": False,
            "service_window_open_utc": "2026-10-10T11:00:00Z",
            "service_window_close_utc": "2026-10-10T12:40:00Z",
        }
        st_a = setup_station(event["id"], station_label="DENTAL-A", **station_payload)
        st_b = setup_station(event["id"], station_label="DENTAL-B", **station_payload)
        get_success_data(api.mark_station_operational(event["id"], st_a["id"], SL))
        get_success_data(api.mark_station_operational(event["id"], st_b["id"], SL))

        event_now = validate_success(api.get_event(event["id"], ED))
        assert event_now["projected_servable_patients"] == 32
        assert event_now["dental_chair_count"] == 10

    def test_single_station_floor_drops_fractional_patient(self, api):
        """PRD §3.7: "The per-station contributions are floored *before*
        summing — summing raw values and flooring afterwards is forbidden
        because it yields a different integer — and the event's
        `projected_servable_patients` is the sum of the three discipline
        capacities."

        Design: Difficulty/combinatorial_formula/throughput_round_per_station_then_sum_pinned
        """
        site = create_vetted_site(
            site_type="SCHOOL", state_code="VA", square_footage=8000
        )
        event = create_event(
            host_state_code="VA",
            service_date="2026-10-10",
            doors_open_utc="2026-10-10T10:00:00Z",
            total_patient_capacity=200,
        )
        agreement = create_agreement(
            {"id": event["id"], "version": event["version"]},
            site["id"],
            liability_cap_cents=5_000_000,
        )
        submit_agreement(event["id"], agreement["id"])
        confirm_agreement(event["id"], agreement["id"])
        # 1 chair * 100 min / 30 min = 3.33... -> floored to 3.
        station = setup_station(
            event["id"],
            station_type="MEDICAL",
            chair_count=1,
            minutes_per_patient=30,
            requires_sterilization=False,
            service_window_open_utc="2026-10-10T11:00:00Z",
            service_window_close_utc="2026-10-10T12:40:00Z",
        )
        get_success_data(api.mark_station_operational(event["id"], station["id"], SL))
        event_now = validate_success(api.get_event(event["id"], ED))
        assert event_now["projected_servable_patients"] == 3


class TestCoverageScoreNestedMinMaxWeights:
    def test_per_discipline_cap_limits_overstaffed_dental(self, api):
        """PRD §3.4: "Per-discipline coverage is the authorized count divided
        by the station count (treating zero stations as a divisor of one),
        capped at 1.0. The three per-discipline coverages are then combined
        with fixed demand weights — dental carries weight 0.5, vision 0.3, and
        medical 0.2 — and the weighted sum is multiplied by 100 and rounded
        half-up to two decimal places. Weights are never renormalized: a
        discipline with zero stations simply contributes zero, and the weights
        sum to 1.0 by construction. An event's coverage floor is 60: the
        recompute that moves `STAFFING → READY` requires a score of at least
        60."

        Design: Difficulty/combinatorial_formula/coverage_score_nested_min_max_weights
        """
        event = create_event_site_locked(
            event_overrides={
                "host_state_code": "VA",
                "service_date": "2026-10-17",
                "doors_open_utc": "2026-10-17T10:00:00Z",
                "total_patient_capacity": 300,
            },
            site_overrides={
                "site_type": "FAIRGROUND",
                "state_code": "VA",
                "square_footage": 25000,
            },
        )
        for label in ("D-1", "D-2"):
            setup_station(
                event["id"],
                station_label=label,
                station_type="DENTAL",
                chair_count=2,
                minutes_per_patient=40,
                requires_sterilization=False,
            )
        # Three over-staffing DENTAL volunteers: coverage_DENTAL = min(3/2,1)=1.
        for _ in range(3):
            create_authorized_volunteer(
                event["id"], discipline="DENTAL", license_state_code="VA"
            )

        event_now = validate_success(api.get_event(event["id"], ED))
        # Score = round_half_up(100 * 0.5 * 1.0, 2) = 50.0 — below the 60
        # floor, so the event must remain in STAFFING even though dental is
        # over-staffed (the cap suppresses the surplus).
        assert event_now["posture"] == "STAFFING"

    def test_full_three_discipline_staffing_lifts_event_to_ready(self, api):
        """PRD §3.4: "An event's coverage floor is 60: the recompute that moves
        `STAFFING → READY` requires a score of at least 60."

        Design: Difficulty/combinatorial_formula/coverage_score_nested_min_max_weights
        """
        event = create_event_site_locked(
            event_overrides={
                "host_state_code": "VA",
                "service_date": "2026-10-17",
                "doors_open_utc": "2026-10-17T10:00:00Z",
                "total_patient_capacity": 300,
            },
            site_overrides={"state_code": "VA"},
        )
        setup_station(event["id"], station_type="DENTAL")
        setup_station(event["id"], station_type="VISION")
        setup_station(event["id"], station_type="MEDICAL")
        create_authorized_volunteer(event["id"], discipline="DENTAL", license_state_code="VA")
        create_authorized_volunteer(event["id"], discipline="VISION", license_state_code="VA")
        create_authorized_volunteer(event["id"], discipline="MEDICAL", license_state_code="VA")

        event_now = validate_success(api.get_event(event["id"], ED))
        # Coverage 1.0 per discipline -> score = 100 * (0.5+0.3+0.2) = 100.
        assert event_now["posture"] == "READY"
