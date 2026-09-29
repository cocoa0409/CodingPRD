"""Optimistic concurrency, in-place reconciliation and immediate consistency.

Covers PRD sections 2.7, 3.2, 3.8 and the immediate consistency model: the two
self-invalidating version tokens, a re-forecast that rewrites its own row rather
than appending one, the per-queue breach run with its reset edge, and derived
fields that are already settled inside the response of the write that moved them.
"""

from test_helpers import (
    DUTY_MANAGER_HEADERS,
    MANAGER_HEADERS,
    PLANNER_HEADERS,
    ApiErrorId,
    assert_breach_counters,
    assert_cents,
    assert_forecast,
    assert_instant,
    assert_lane_snapshot,
    assert_list_meta,
    assert_officer_ledger,
    assert_plan_cost,
    assert_position_ledger,
    assert_posture,
    assert_publication,
    factories as f,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    BAND_1000,
    CLOCK_0800,
    FLIGHT_1030,
    OPERATIONAL_DATE,
    Scenario,
)

CLOCK_0805 = "2026-09-10T08:05:00Z"
NEXT_OPERATIONAL_DATE = "2026-09-11"
DETAIL_WINDOW_1200 = "2026-09-10T12:00:00Z"
DETAIL_WINDOW_1300 = "2026-09-10T13:00:00Z"


def _checkpoint(scenario: Scenario) -> dict:
    return validate_success(
        scenario.api.get_checkpoint(scenario.checkpoint_id, MANAGER_HEADERS)
    )


def _create_plan(scenario: Scenario, version: int, operational_date: str = OPERATIONAL_DATE):
    return scenario.api.create_staffing_plan(
        f.staffing_plan_payload(scenario.checkpoint_id, operational_date, version),
        PLANNER_HEADERS,
    )


class TestPlanCreateOptimisticConcurrency:
    """PRD 2.7 - the checkpoint token is invalidated by the create that used it."""

    def test_a_successful_create_invalidates_the_very_token_it_consumed(
        self, base: Scenario
    ):
        """Two identical creates cannot both succeed, and an unrelated PATCH is enough.

        Design: Corner/cross-cutting complexity layers/plan_create_occ_rejects_a_version_its_own_predecessor_advanced
        """
        first_version = base.checkpoint_version()
        assert first_version == 1, "a freshly created checkpoint starts at version 1"

        first = validate_success(_create_plan(base, first_version), 201)
        assert first["state"] == "DRAFT"

        validate_error(
            _create_plan(base, first_version),
            ApiErrorId.STALE_CHECKPOINT_VERSION,
            412,
        )

        second_version = base.checkpoint_version()
        assert second_version == 2, "creating a plan advances the checkpoint"
        # The product deliberately permits a second plan for the same checkpoint
        # and operational_date, so only the stale token stood in the way.
        second = validate_success(_create_plan(base, second_version), 201)
        assert second["id"] != first["id"]
        assert second["state"] == "DRAFT"

        third_version = base.checkpoint_version()
        assert third_version == 3

        patched = validate_success(
            base.api.update_checkpoint(
                base.checkpoint_id,
                f.checkpoint_patch_payload(wait_threshold_minutes_standard=14),
                MANAGER_HEADERS,
            )
        )
        assert patched["version"] == 4

        validate_error(
            _create_plan(base, third_version, NEXT_OPERATIONAL_DATE),
            ApiErrorId.STALE_CHECKPOINT_VERSION,
            412,
        )

        rows, meta = validate_paginated(
            base.api.list_staffing_plans(PLANNER_HEADERS, {"checkpoint_id": base.checkpoint_id})
        )
        assert len(rows) == 2, "neither rejected create left a partial row behind"
        assert_list_meta(meta, total_count=2)
        assert {row["id"] for row in rows} == {first["id"], second["id"]}


def _request_detail(
    scenario: Scenario, version: int, window_start_utc: str = DETAIL_WINDOW_1300
):
    return scenario.api.create_surge_detail(
        f.surge_detail_payload(
            scenario.plan_id,
            scenario.officer_id,
            window_start_utc,
            30,
            version,
            event_code="SPORTING_EVENT",
        ),
        PLANNER_HEADERS,
    )


class TestSurgeDetailOptimisticConcurrency:
    """PRD 2.7 - the officer token pins the ledger a decision by another role moves."""

    def test_a_decision_taken_by_another_role_invalidates_the_requesters_token(
        self, submitted_plan: Scenario
    ):
        """The token protects committed_duty_minutes, not the detail row being created.

        Design: Corner/cross-cutting complexity layers/surge_detail_occ_pins_the_officer_ledger_the_requester_read
        """
        scenario = submitted_plan
        officer = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        first_version = officer["version"]
        assert_officer_ledger(
            officer, committed_duty_minutes=30, approved_detail_minutes=0
        )

        first = validate_success(
            _request_detail(scenario, first_version, DETAIL_WINDOW_1200), 201
        )
        assert first["state"] == "REQUESTED"
        assert first["detail_cost_cents"] is None

        validate_error(
            _request_detail(scenario, first_version),
            ApiErrorId.STALE_OFFICER_VERSION,
            412,
        )

        second_version = scenario.officer_version(scenario.officer_id)
        assert second_version == first_version + 1, "creating the detail bumped the officer"

        approved = validate_success(
            scenario.api.decide_surge_detail(
                first["id"], f.surge_decision_payload("APPROVE"), DUTY_MANAGER_HEADERS
            )
        )
        assert approved["state"] == "APPROVED"
        assert_cents(approved["detail_cost_cents"], 3000, "detail_cost_cents")

        # The decision was made by a DutyManager the planner never coordinated
        # with, and it is exactly that write the token defends against.
        validate_error(
            _request_detail(scenario, second_version),
            ApiErrorId.STALE_OFFICER_VERSION,
            412,
        )

        after = validate_success(
            scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)
        )
        assert after["version"] == second_version + 1
        assert_officer_ledger(
            after, committed_duty_minutes=60, approved_detail_minutes=30
        )

        retried = validate_success(_request_detail(scenario, after["version"]), 201)
        assert retried["state"] == "REQUESTED"


def _two_lane_half_multiplier_floor(base: Scenario) -> Scenario:
    """Two equipped lanes, a 100-passenger flight and a band multiplied by 0.50."""
    base.build_equipped_lane(position_index=1, serial_prefix="L1")
    base.build_equipped_lane(position_index=2, serial_prefix="L2", secondary_positions=0)
    base.create_flight(
        FLIGHT_1030, flight_number="AA700", seats_sold=100, load_factor_pct=100
    )
    base.band = base.create_band(
        BAND_1000, expedited_share_pct=0, seasonal_multiplier=0.50
    )
    return base


class TestReForecastOverwritesInPlace:
    """PRD 3.2 - a re-forecast reconciles the stored row instead of appending one."""

    def test_switching_variants_rewrites_every_derived_field_and_is_reversible(
        self, base: Scenario
    ):
        """The seasonal multiplier separates the variants and both directions are lossless.

        Design: Corner/cross-cutting complexity layers/re_forecasting_a_band_overwrites_the_variant_fields_in_place
        """
        scenario = _two_lane_half_multiplier_floor(base)
        # The multiplier is a two-decimal percentage-style number, so it is
        # compared numerically rather than as a rendered string.
        assert float(scenario.band["seasonal_multiplier"]) == 0.50

        schedule_only = scenario.forecast(scenario.band_id, "SCHEDULE_ONLY")
        # The whole 30-minute curve window lands inside the band, and this
        # variant ignores the seasonal multiplier entirely.
        assert_forecast(
            schedule_only,
            forecast_pax_count=100,
            forecast_variant="SCHEDULE_ONLY",
            required_standard_lanes=2,
            unmet_standard_demand=0,
            forecast_computed_at_utc=CLOCK_0800,
        )

        scenario.set_clock(CLOCK_0805)
        blended = scenario.forecast(scenario.band_id, "CURVE_BLENDED")
        # round_half_up(100 * 1.00 * 30/30 * (1 - 0) * 0.50) is 50, which one
        # lane of 90 absorbs on its own.
        assert_forecast(
            blended,
            forecast_pax_count=50,
            forecast_variant="CURVE_BLENDED",
            required_standard_lanes=1,
            unmet_standard_demand=0,
            forecast_computed_at_utc=CLOCK_0805,
        )
        assert blended["id"] == scenario.band_id

        rows, meta = validate_paginated(
            scenario.api.list_time_bands(
                PLANNER_HEADERS, {"checkpoint_id": scenario.checkpoint_id}
            )
        )
        assert len(rows) == 1, "the re-forecast overwrote the row rather than appending"
        assert_list_meta(meta, total_count=1)
        assert rows[0]["id"] == scenario.band_id
        assert rows[0]["forecast_pax_count"] == 50

        # A DutyManager may forecast too, and switching back restores the
        # earlier numbers exactly.
        restored = validate_success(
            scenario.api.forecast_time_band(
                scenario.band_id, f.forecast_payload("SCHEDULE_ONLY"), DUTY_MANAGER_HEADERS
            )
        )
        assert_forecast(
            restored,
            forecast_pax_count=100,
            forecast_variant="SCHEDULE_ONLY",
            required_standard_lanes=2,
            unmet_standard_demand=0,
            forecast_computed_at_utc=CLOCK_0805,
        )


def _observe(scenario: Scenario, lane_type: str, sampled_wait_seconds: int) -> dict:
    return scenario.post_observation(
        headers=scenario.supervisor_headers,
        lane_type=lane_type,
        sampled_wait_seconds=sampled_wait_seconds,
        measurement_method="BLE_SENSOR",
        sample_size=10,
    )


def _standard_tickets(scenario: Scenario) -> list:
    rows, _meta = validate_paginated(
        scenario.api.list_escalation_tickets(
            MANAGER_HEADERS,
            {"checkpoint_id": scenario.checkpoint_id, "lane_type_scope": "STANDARD"},
        )
    )
    return rows


class TestBreachCounterPerQueue:
    """PRD 3.8 - a cumulative run per lane_type, with a reset edge that expires tickets."""

    def test_the_run_is_scoped_per_queue_and_one_good_publication_disarms_it(
        self, supervised_floor: Scenario
    ):
        """An expedited breach never advances the standard run, and 11 minutes wipes it.

        Design: Corner/cross-cutting complexity layers/breach_counter_advances_per_lane_type_and_resets_below_threshold
        """
        scenario = supervised_floor

        # Thin data: one sample, so the publication is that sample - 960 s is 16
        # minutes, at or above the 15-minute standard threshold.
        first = _observe(scenario, "STANDARD", 960)
        assert first["published_wait_minutes_snapshot"] == 16
        assert first["breached_threshold"] is True
        opening = _checkpoint(scenario)
        assert_breach_counters(opening, standard=1)
        assert_posture(opening, "NORMAL")
        assert _standard_tickets(scenario) == [], "one breach raises nothing"

        second = _observe(scenario, "STANDARD", 960)
        assert second["published_wait_minutes_snapshot"] == 16
        raised = _standard_tickets(scenario)
        assert len(raised) == 1, "the second consecutive breach raises exactly one ticket"
        standard_ticket = raised[0]
        assert standard_ticket["state"] == "RAISED"
        assert standard_ticket["lane_type_scope"] == "STANDARD"
        assert standard_ticket["trigger_reason"] == "WAIT_THRESHOLD_BREACH"
        assert standard_ticket["published_wait_minutes_at_raise"] == 16

        expedited_first = _observe(scenario, "EXPEDITED", 960)
        assert expedited_first["published_wait_minutes_snapshot"] == 16
        assert expedited_first["breached_threshold"] is True
        split = _checkpoint(scenario)
        assert_breach_counters(split, standard=2, expedited=1)
        assert_posture(split, "ELEVATED")

        _observe(scenario, "EXPEDITED", 960)
        assert_posture(_checkpoint(scenario), "SURGE")

        good = _observe(scenario, "STANDARD", 60)
        # Three standard samples now qualify for the weighted average, and every
        # weight is 3 * 10, so (960 + 960 + 60) / 3 is 660 seconds.
        assert good["published_wait_minutes_snapshot"] == 11
        assert good["breached_threshold"] is False

        publication = validate_success(
            scenario.api.get_published_wait_time(
                scenario.checkpoint_id, MANAGER_HEADERS, {"lane_type": "STANDARD"}
            )
        )
        assert_publication(
            publication,
            published_wait_minutes=11,
            weighted_average_seconds="660.00",
            sample_count=3,
            threshold_minutes=15,
            breached=False,
        )

        disarmed = _checkpoint(scenario)
        assert_breach_counters(disarmed, standard=0, expedited=2)
        assert_posture(disarmed, "ELEVATED")

        expired = validate_success(
            scenario.api.get_escalation_ticket(standard_ticket["id"], MANAGER_HEADERS)
        )
        assert expired["state"] == "EXPIRED", "a RAISED ticket is auto-expired"

        # A fourth breach-level SAMPLE is not a breach-level PUBLICATION:
        # 2940 / 4 is 735 seconds, which publishes as 12 minutes.
        fourth = _observe(scenario, "STANDARD", 960)
        assert fourth["published_wait_minutes_snapshot"] == 12
        assert fourth["breached_threshold"] is False
        assert_breach_counters(_checkpoint(scenario), standard=0)


class TestImmediateConsistency:
    """PRD 2.9 / 3.3 / 3.6 - every derived field is settled inside the write itself."""

    def test_the_writes_own_response_already_carries_the_recomputed_fields(
        self, draft_plan_floor: Scenario
    ):
        """No follow-up read, retry or delay is needed anywhere for a value to converge.

        Design: Corner/consistency model/every_derived_field_is_current_in_the_same_response
        """
        scenario = draft_plan_floor

        created = validate_success(
            scenario.api.create_lane_assignment(
                f.lane_assignment_payload(
                    scenario.plan_id, scenario.lane_id, scenario.officer_id, scenario.band_id
                ),
                PLANNER_HEADERS,
            ),
            201,
        )
        assert created["planned_minutes"] == 30, (
            "the computed figure is present in the create response itself"
        )
        assert_instant(created["created_at"], CLOCK_0800, "created_at")

        priced = validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        )
        assert_plan_cost(
            priced,
            subtotal_cents=3000,
            admin_fee_rate="0.060",
            admin_fee_cents=180,
            total_cost_cents=3180,
        )
        assert_officer_ledger(
            validate_success(scenario.api.get_officer(scenario.officer_id, PLANNER_HEADERS)),
            committed_duty_minutes=30,
        )

        faulted = validate_success(
            scenario.api.report_equipment_state(
                scenario.units["ADVANCED_IMAGING"]["id"],
                f.report_state_payload("OUT_OF_SERVICE", note="imaging fault"),
                MANAGER_HEADERS,
            )
        )
        assert faulted["state"] == "OUT_OF_SERVICE"

        lane = validate_success(scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS))
        assert_lane_snapshot(
            lane,
            lane_state="PAUSED",
            equipment_state="OUT_OF_SERVICE",
            paused_reason_code="EQUIPMENT_FAULT",
        )

        checkpoint = _checkpoint(scenario)
        assert_posture(checkpoint, "ELEVATED")
        assert_position_ledger(checkpoint, [])
        assert checkpoint["available_lane_positions"] == 6

        # Repeating every read returns identical values, so nothing converged late.
        assert validate_success(
            scenario.api.get_lane(scenario.lane_id, MANAGER_HEADERS)
        ) == lane
        assert _checkpoint(scenario) == checkpoint
        assert validate_success(
            scenario.api.get_plan_cost_summary(scenario.plan_id, PLANNER_HEADERS)
        ) == priced
