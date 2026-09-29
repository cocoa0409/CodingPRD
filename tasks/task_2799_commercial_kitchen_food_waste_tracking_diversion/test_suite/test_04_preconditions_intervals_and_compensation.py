"""Writes gated on a foreign row's state, two opposite interval conventions, and exact compensation.

Every test builds its own world from an empty database with the logical clock at its process-start
value, using only the endpoints the specification declares.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_baseline_period,
    assert_consignment,
    assert_corporate_rollup,
    assert_data_quality_finding,
    assert_gram_conservation,
    assert_reduction_target,
    assert_site_cost_ledger,
    assert_waste_entry,
    factories,
    fixtures,
    get_success_data,
    make_corporate_lead_headers,
    make_hauler_operator_headers,
    make_kitchen_staff_headers,
    make_shift_lead_headers,
    make_site_sustainability_manager_headers,
    validate_error,
    validate_paginated,
)

CALIBRATION_DUE_AT = "2027-01-01T00:00:00Z"
CLOCK_INSTANT = "2026-08-01T00:00:00.000Z"


def _assert_instant(actual, expected):
    """Compare two UTC instants, tolerating the fractional-digit spelling of either side."""

    def canonical(value):
        assert isinstance(value, str) and value.endswith("Z"), f"not a UTC instant: {value!r}"
        body = value[:-1]
        if "." not in body:
            body += ".000"
        head, fraction = body.split(".")
        return f"{head}.{(fraction + '000')[:3]}Z"

    assert canonical(actual) == canonical(expected), f"instant {actual!r} is not {expected!r}"


def _prepared_food_type(**overrides):
    """The catalog entry every world below discards: 640 cents per kilogram, donation eligible."""
    payload = {
        "name": "Braised Chicken Portion",
        "category": "PREPARED",
        "default_cost_per_kg_cents": 640,
        "donation_eligible": True,
        "animal_feed_eligible": True,
        "compostable": True,
        "donation_shelf_life_hours": 24,
    }
    payload.update(overrides)
    return fixtures.create_food_type(**payload)


class TestTargetActivationRequiresACertifiedBaseline:
    """A reduction goal cannot go live against a measuring window corporate has not signed off."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()

        june_shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        for weight, captured_at in ((2000, "2026-06-10T10:00:00Z"), (1000, "2026-06-10T10:05:00Z")):
            fixtures.capture_entry(
                station["id"],
                june_shift["id"],
                food_type["id"],
                weight_grams=weight,
                loss_reason="TRIM",
                captured_at=captured_at,
            )
        fixtures.close_shift(june_shift["id"])

        july_shift = fixtures.open_shift(
            site["id"], shift_date="2026-07-10", shift_code="AM", meals_served=1000
        )
        fixtures.capture_entry(
            station["id"],
            july_shift["id"],
            food_type["id"],
            weight_grams=2700,
            loss_reason="TRIM",
            captured_at="2026-07-10T10:00:00Z",
        )
        fixtures.close_shift(july_shift["id"])

        period = fixtures.open_baseline(
            site["id"], start_date="2026-06-01", end_date="2026-06-30"
        )
        period = fixtures.submit_baseline(site["id"], period["id"])

        site = fixtures.read_site(site["id"])
        target = fixtures.propose_target(
            site["id"],
            period["id"],
            site["version"],
            basis="ABSOLUTE",
            target_reduction_pct=10.00,
            window_start="2026-07-01",
            window_end="2026-07-31",
        )
        return site, period, target

    def test_activation_against_a_merely_submitted_window_is_refused(self):
        """Corporate review has not happened yet, so the goal may not start measuring.

        PRD Coverage: "Activation advances `PROPOSED → ACTIVE` and is refused from any other status with `ERR_INVALID_TARGET_STATE`. It additionally requires the bound baseline period to be `CERTIFIED`; a target bound to a period still `OPEN` or `SUBMITTED` is refused with `ERR_BASELINE_NOT_CERTIFIED`." "12. Cross-entity state preconditions — station active and calibrated, service period open, recipe published, baseline certified, hauler approved."

        Design: Difficulty/cross_entity_state_dependency/target_activation_requires_certified_baseline_period
        """
        _site, _period, target = self._world()

        response = api_client.activate_reduction_target(
            target["id"], make_corporate_lead_headers("csl-1")
        )
        validate_error(response, ApiErrorId.BASELINE_NOT_CERTIFIED.value)

        stored = fixtures.read_target(target["id"])
        assert stored["status"] == "PROPOSED"
        assert stored["activated_at"] is None
        assert stored["attainment_state"] == "BEHIND"

    def test_the_submitted_window_already_carries_all_six_frozen_metrics(self):
        """The refusal is about review, not about missing numbers: the freeze already happened.

        PRD Coverage: "Submission freezes the numbers." "Over the qualifying capture set, `baseline_entry_count` is the number of captures, `baseline_waste_grams` is the sum of their `weight_grams`, `baseline_waste_kg` is those grams divided by 1000 and rounded half up to 3 decimal places, and `baseline_cost_cents` is the sum of their `effective_cost_cents`." "Finally `baseline_intensity_kg_per_1k_meals` is `baseline_waste_grams` divided by `baseline_meals_served`, rounded half up to 3 decimal places, and is null when `baseline_meals_served` is 0."

        Design: Difficulty/cross_entity_state_dependency/target_activation_requires_certified_baseline_period
        """
        _site, period, _target = self._world()

        stored = fixtures.read_baseline(period["id"])
        assert_baseline_period(stored)
        assert stored["status"] == "SUBMITTED"
        assert stored["baseline_entry_count"] == 2
        assert stored["baseline_waste_grams"] == 3000
        assert stored["baseline_waste_kg"] == pytest.approx(3.000, abs=0.01)
        assert stored["baseline_meals_served"] == 1000
        assert stored["baseline_intensity_kg_per_1k_meals"] == pytest.approx(3.000, abs=0.01)
        assert stored["baseline_cost_cents"] == 1920

    def test_certifying_the_window_moves_the_window_alone(self):
        """Corporate sign-off touches the measuring window and leaves the goal where it was.

        PRD Coverage: "Certification advances `SUBMITTED → CERTIFIED`, additionally requires `baseline_meals_served` to be greater than 0 — certifying a window with frozen meals of zero is refused with `ERR_BASELINE_NO_DATA` — stamps `certified_at` with the current logical clock, makes the frozen metrics immutable, and increments `version` by 1." "The new target itself opens in status `PROPOSED` with `activated_at` and `resolved_at` null, `performance_waste_grams` and `performance_meals_served` at 0, and `attainment_state` at `BEHIND`."

        Design: Difficulty/cross_entity_state_dependency/target_activation_requires_certified_baseline_period
        """
        _site, period, target = self._world()

        blocked = api_client.activate_reduction_target(
            target["id"], make_corporate_lead_headers("csl-1")
        )
        validate_error(blocked, ApiErrorId.BASELINE_NOT_CERTIFIED.value)

        before = fixtures.read_target(target["id"])
        certified = fixtures.certify_baseline(period["id"])
        assert certified["status"] == "CERTIFIED"
        _assert_instant(certified["certified_at"], CLOCK_INSTANT)
        assert certified["baseline_waste_grams"] == 3000
        assert certified["baseline_meals_served"] == 1000

        after = fixtures.read_target(target["id"])
        assert after["status"] == "PROPOSED"
        assert after["version"] == before["version"]
        assert after["performance_waste_grams"] == 0
        assert after["performance_meals_served"] == 0

    def test_the_identical_activation_then_succeeds_and_evaluates_attainment(self):
        """Nothing about the request changed, only the window's status, and the goal goes live.

        PRD Coverage: "On success `activated_at` is stamped with the current logical clock, the full attainment evaluation runs immediately, and `version` is incremented by 1." "Over captures at the target's site with status `RECORDED` or `FLAGGED` whose `captured_at` date falls inside the inclusive performance window, `performance_waste_grams` is the sum of `weight_grams`. Over the site's `CLOSED` service periods whose `shift_date` falls inside that same inclusive window, `performance_meals_served` is the sum of `meals_served`. `performance_intensity_kg_per_1k_meals` is the performance grams divided by the performance meals, rounded half up to 3 decimal places, and is null when the meals figure is 0." "`absolute_reduction_pct` is the baseline grams minus the performance grams, divided by the baseline grams, multiplied by 100 and rounded half up to 2 decimal places; it is null when the frozen `baseline_waste_grams` is 0." "`effective_reduction_pct` is the absolute figure when `basis` is `ABSOLUTE` and the intensity figure when `basis` is `INTENSITY`." "The diversion floor reads the site's live `diversion_rate_pct`, with a null value read as 0.00, and is satisfied when that value has reached `min_diversion_rate_pct` or more."

        Design: Difficulty/cross_entity_state_dependency/target_activation_requires_certified_baseline_period
        """
        _site, period, target = self._world()

        blocked = api_client.activate_reduction_target(
            target["id"], make_corporate_lead_headers("csl-1")
        )
        validate_error(blocked, ApiErrorId.BASELINE_NOT_CERTIFIED.value)
        fixtures.certify_baseline(period["id"])

        response = api_client.activate_reduction_target(
            target["id"], make_corporate_lead_headers("csl-1")
        )
        activated = get_success_data(response, 200)
        assert_reduction_target(activated)
        assert activated["status"] == "ACTIVE"
        _assert_instant(activated["activated_at"], CLOCK_INSTANT)
        assert activated["performance_waste_grams"] == 2700
        assert activated["performance_meals_served"] == 1000
        assert activated["performance_intensity_kg_per_1k_meals"] == pytest.approx(2.700, abs=0.01)
        assert activated["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert activated["intensity_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert activated["effective_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert activated["attainment_state"] == "ACHIEVED_PENDING"


class TestDispatchRequiresAnApprovedHauler:
    """The collector's contract status gates the truck leaving, not the pallet being built."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        hauler = fixtures.create_hauler(
            name="Green Loop Compost",
            channels=["COMPOST"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=1,
        )
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-06-11T08:00:00Z",
            pickup_window_end="2026-06-11T10:00:00Z",
            container_tare_grams=0,
        )
        fixtures.add_line(site["id"], consignment["id"], entry["id"], 1000)
        return site, hauler, consignment

    def test_an_unapproved_collector_may_still_hold_a_staged_load(self):
        """Building and locking the pallet is allowed while the contract is still pending.

        PRD Coverage: "A hauler is created with `status` `PENDING`, which may only ever hold `PENDING` or `APPROVED`. A `PENDING` hauler may hold consignments in `DRAFT` or `STAGED` but may never receive a dispatch."

        Design: Difficulty/cross_entity_state_dependency/consignment_dispatch_requires_approved_hauler_while_staging_does_not
        """
        site, hauler, consignment = self._world()

        assert fixtures.read_hauler(hauler["id"])["status"] == "PENDING"
        staged = fixtures.stage_consignment(site["id"], consignment["id"])
        assert_consignment(staged)
        assert staged["logistics_status"] == "STAGED"
        _assert_instant(staged["staged_at"], CLOCK_INSTANT)
        assert staged["line_count"] == 1
        assert staged["staged_weight_grams"] == 1000

    def test_dispatch_to_an_unapproved_collector_is_refused(self):
        """The truck may not leave, and the refusal leaves the load exactly as it was.

        PRD Coverage: "The hauler must be `APPROVED`; dispatching to a hauler still `PENDING` is refused with `ERR_HAULER_NOT_APPROVED`." "12. Cross-entity state preconditions — station active and calibrated, service period open, recipe published, baseline certified, hauler approved."

        Design: Difficulty/cross_entity_state_dependency/consignment_dispatch_requires_approved_hauler_while_staging_does_not
        """
        site, _hauler, consignment = self._world()
        fixtures.stage_consignment(site["id"], consignment["id"])

        response = api_client.dispatch_consignment(
            consignment["id"], make_site_sustainability_manager_headers(site["id"])
        )
        validate_error(response, ApiErrorId.HAULER_NOT_APPROVED.value)

        stored = fixtures.read_consignment(consignment["id"])
        assert stored["logistics_status"] == "STAGED"
        assert stored["dispatched_at"] is None
        assert stored["settlement_status"] == "UNBILLED"

    def test_approving_the_collector_touches_the_collector_alone(self):
        """The contract signature moves the hauler row and leaves the load's version alone.

        PRD Coverage: "Approval belongs to `CorporateSustainabilityLead`, advances `PENDING → APPROVED`, is refused with `ERR_INVALID_HAULER_STATE` when the hauler is already approved, makes every consignment already staged against that hauler dispatchable, and increments the hauler's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/consignment_dispatch_requires_approved_hauler_while_staging_does_not
        """
        site, hauler, consignment = self._world()
        staged = fixtures.stage_consignment(site["id"], consignment["id"])

        approved = fixtures.approve_hauler(hauler["id"])
        assert approved["status"] == "APPROVED"

        after = fixtures.read_consignment(consignment["id"])
        assert after["logistics_status"] == "STAGED"
        assert after["version"] == staged["version"]
        assert after["dispatched_at"] is None

    def test_the_identical_dispatch_then_succeeds(self):
        """Only the collector's contract changed, and the same request now sends the truck.

        PRD Coverage: "On success `dispatched_at` is stamped with the current logical clock, the consignment becomes ticket-eligible on the settlement dimension, and `version` is incremented by 1." "The two axes evolve independently and there is exactly one coupling point between them, described in §3.8."

        Design: Difficulty/cross_entity_state_dependency/consignment_dispatch_requires_approved_hauler_while_staging_does_not
        """
        site, hauler, consignment = self._world()
        fixtures.stage_consignment(site["id"], consignment["id"])
        headers = make_site_sustainability_manager_headers(site["id"])

        blocked = api_client.dispatch_consignment(consignment["id"], headers)
        validate_error(blocked, ApiErrorId.HAULER_NOT_APPROVED.value)
        fixtures.approve_hauler(hauler["id"])

        dispatched = get_success_data(api_client.dispatch_consignment(consignment["id"], headers), 200)
        assert dispatched["logistics_status"] == "DISPATCHED"
        _assert_instant(dispatched["dispatched_at"], CLOCK_INSTANT)
        assert dispatched["settlement_status"] == "UNBILLED"

    def test_a_weigh_ticket_cannot_precede_the_dispatch_it_settles(self):
        """Billing opens only after the load has physically left, whatever the contract says.

        PRD Coverage: "The consignment's `logistics_status` must be `DISPATCHED`; filing against anything else is refused with `ERR_INVALID_CONSIGNMENT_STATE`."

        Design: Difficulty/cross_entity_state_dependency/consignment_dispatch_requires_approved_hauler_while_staging_does_not
        """
        site, hauler, consignment = self._world()
        fixtures.stage_consignment(site["id"], consignment["id"])

        response = api_client.create_hauler_ticket(
            factories.create_hauler_ticket_payload(consignment["id"], 1000),
            make_hauler_operator_headers(hauler["id"]),
        )
        validate_error(response, ApiErrorId.INVALID_CONSIGNMENT_STATE.value)

        stored = fixtures.read_consignment(consignment["id"])
        assert stored["settlement_status"] == "UNBILLED"
        assert stored["logistics_status"] == "STAGED"


class TestRollupPublicationWaitsOnUnexaminedDefects:
    """A corporate report cannot be signed off while a kitchen in scope has an unjudged defect."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        prep = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            status="ACTIVE",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        hot_line = fixtures.create_station(
            site["id"],
            station_code="LINE-1",
            station_kind="HOT_LINE",
            status="ACTIVE",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        entry = fixtures.capture_entry(
            prep["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        findings = fixtures.run_scan(site["id"], "2026-06-10")
        rollup = fixtures.prepare_rollup(
            [site["id"]], user_id="csl-1", period_start="2026-06-01", period_end="2026-06-30"
        )
        return site, hot_line, shift, entry, findings, rollup

    def test_the_scan_raises_exactly_one_finding_for_the_unused_station(self):
        """The hot line served the period without a single weighing, which is a missing row.

        PRD Coverage: "The `MISSED_CAPTURE` rule walks every pairing of an in-scope station with an in-scope shift, ordered by the station's `station_code` ascending and then by the shift's `shift_code` in the order `AM`, `PM`, `NIGHT`, and emits one finding for a pairing when no capture exists carrying that `station_id` and that `shift_id` with `status` `RECORDED`, `FLAGGED` or `SUPERSEDED` — a superseded capture still proves the station was used, so a corrected station is not also a missed one. The finding's `waste_entry_id` is null, because the defect is the absence of a row." "Its `status` begins at `OPEN`, which may only ever hold `OPEN`, `CONFIRMED` or `DISMISSED`, and its `resolved_by_user_id` is null while open."

        Design: Difficulty/cross_entity_state_dependency/rollup_publication_blocked_by_any_open_data_quality_finding_on_an_in_scope_site
        """
        site, hot_line, shift, _entry, findings, _rollup = self._world()

        assert len(findings) == 1
        finding = findings[0]
        assert_data_quality_finding(finding)
        assert finding["finding_type"] == "MISSED_CAPTURE"
        assert finding["status"] == "OPEN"
        assert finding["site_id"] == site["id"]
        assert finding["station_id"] == hot_line["id"]
        assert finding["shift_id"] == shift["id"]
        assert finding["waste_entry_id"] is None
        assert finding["resolved_by_user_id"] is None
        _assert_instant(finding["detected_at"], CLOCK_INSTANT)

    def test_the_draft_report_computes_live_metrics_but_stays_unsigned(self):
        """The report can be assembled in full; it simply may not be published yet.

        PRD Coverage: "The rollup's `status` begins at `DRAFT`, which may only ever hold `DRAFT` or `PUBLISHED`, `prepared_by_user_id` is stamped with the acting `X-User-ID` — the value that segregation of duties will later be measured against — and `published_by_user_id`, `published_at` and `published_metrics` are all null." "`diversion_rate_pct` is `total_diverted_weight_grams` divided by `total_captured_weight_grams`, multiplied by 100 and rounded half up to 2 decimal places, and is null when the captured denominator is 0." "From that count, `goal_attainment_state` is `ALL_ON_TRACK` when `sites_on_track_count` equals `in_scope_site_count`, `NONE_ON_TRACK` when `sites_on_track_count` is 0, and `PARTIAL` in every other case."

        Design: Difficulty/cross_entity_state_dependency/rollup_publication_blocked_by_any_open_data_quality_finding_on_an_in_scope_site
        """
        _site, _hot_line, _shift, _entry, _findings, rollup = self._world()

        assert_corporate_rollup(rollup)
        assert rollup["status"] == "DRAFT"
        assert rollup["in_scope_site_count"] == 1
        assert rollup["total_captured_weight_grams"] == 1000
        assert rollup["total_valued_cost_cents"] == 640
        assert rollup["total_diverted_weight_grams"] == 0
        assert rollup["diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)
        assert rollup["sites_on_track_count"] == 0
        assert rollup["goal_attainment_state"] == "NONE_ON_TRACK"
        assert rollup["published_metrics"] is None

    def test_publication_is_refused_while_the_finding_is_still_open(self):
        """A defect nobody has judged holds the whole company report back.

        PRD Coverage: "And there must be zero findings with `status` `OPEN` whose `site_id` appears in the rollup's `site_ids`, refused otherwise with `ERR_ROLLUP_DATA_QUALITY_BLOCKED`; the finding's `detected_at` is irrelevant to this test, so an open finding from long before the reporting period blocks publication just as firmly as one raised this morning, and the remedy is to resolve it either way, not to argue about its date."

        Design: Difficulty/cross_entity_state_dependency/rollup_publication_blocked_by_any_open_data_quality_finding_on_an_in_scope_site
        """
        _site, _hot_line, _shift, _entry, _findings, rollup = self._world()

        response = api_client.publish_rollup(rollup["id"], make_corporate_lead_headers("csl-2"))
        validate_error(response, ApiErrorId.ROLLUP_DATA_QUALITY_BLOCKED.value)

        stored = fixtures.read_rollup(rollup["id"])
        assert stored["status"] == "DRAFT"
        assert stored["published_at"] is None
        assert stored["published_by_user_id"] is None
        assert stored["published_metrics"] is None

    def test_dismissing_the_finding_unblocks_the_identical_publication(self):
        """Judging the defect as noise counts as examining it, and the report goes out unchanged.

        PRD Coverage: "Both outcomes have identical downstream force: a confirmed finding and a dismissed finding equally stop blocking corporate publication, because the block is on unexamined defects, not on defects." "On success the metrics are recomputed one final time and that fresh result is copied into `published_metrics` as a frozen object carrying `total_captured_weight_grams`, `total_valued_cost_cents`, `total_diverted_weight_grams`, `diversion_rate_pct`, `sites_on_track_count` and `goal_attainment_state`; `published_by_user_id` is stamped with the acting `X-User-ID`, `published_at` with the current logical clock, `status` advances `DRAFT → PUBLISHED`, and `version` is incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/rollup_publication_blocked_by_any_open_data_quality_finding_on_an_in_scope_site
        """
        site, _hot_line, _shift, _entry, findings, rollup = self._world()

        blocked = api_client.publish_rollup(rollup["id"], make_corporate_lead_headers("csl-2"))
        validate_error(blocked, ApiErrorId.ROLLUP_DATA_QUALITY_BLOCKED.value)

        resolved = fixtures.resolve_finding(
            site["id"],
            findings[0]["id"],
            resolution="DISMISSED",
            resolution_note="LINE-1 was closed for maintenance that service",
        )
        assert resolved["status"] == "DISMISSED"
        assert resolved["resolved_by_user_id"] == site["id"]

        published = get_success_data(
            api_client.publish_rollup(rollup["id"], make_corporate_lead_headers("csl-2")), 200
        )
        assert published["status"] == "PUBLISHED"
        assert published["published_by_user_id"] == "csl-2"
        _assert_instant(published["published_at"], CLOCK_INSTANT)
        frozen = published["published_metrics"]
        assert frozen is not None
        assert frozen["total_captured_weight_grams"] == 1000
        assert frozen["total_valued_cost_cents"] == 640
        assert frozen["total_diverted_weight_grams"] == 0
        assert frozen["diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)
        assert frozen["sites_on_track_count"] == 0
        assert frozen["goal_attainment_state"] == "NONE_ON_TRACK"


class TestStationReservationIsAClosedInterval:
    """One tray's weighing reserves its own scale, both ends inclusive, and nobody else's."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        prep = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        hot_line = fixtures.create_station(
            site["id"],
            station_code="LINE-1",
            station_kind="HOT_LINE",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        first = fixtures.capture_entry(
            prep["id"],
            shift["id"],
            food_type["id"],
            weight_grams=500,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        return site, prep, hot_line, food_type, shift, first

    @staticmethod
    def _capture_payload(station_id, shift_id, food_type_id, captured_at, weight_grams=300):
        return factories.create_waste_entry_payload(
            station_id,
            shift_id,
            food_type_id,
            weight_grams=weight_grams,
            loss_reason="TRIM",
            captured_at=captured_at,
        )

    def test_the_stored_window_end_excludes_the_turnaround_allowance(self):
        """The persisted field is the lock alone; the extra minute lives only in the check.

        PRD Coverage: "The stored `capture_window_end` on each capture is its `captured_at` plus the station's `capture_lock_seconds`, and is the upper bound of the occupation interval before the turnaround allowance is added."

        Design: Difficulty/resource_temporal_overlap/station_lock_is_a_closed_interval_of_capture_lock_plus_sixty_seconds
        """
        _site, _prep, _hot_line, _food_type, _shift, first = self._world()

        assert_waste_entry(first)
        _assert_instant(first["captured_at"], "2026-06-10T10:00:00.000Z")
        _assert_instant(first["capture_window_end"], "2026-06-10T10:00:30.000Z")

    def test_the_far_end_of_the_reservation_still_blocks_the_same_scale(self):
        """Ninety seconds after the first weighing the scale is occupied to the last second.

        PRD Coverage: "The reserved stretch of a capture runs from its `captured_at` through `captured_at` plus the station's `capture_lock_seconds` plus a fixed one-minute turnaround allowance, and **both ends of that stretch are inclusive**." "A new capture whose `captured_at` falls anywhere inside the reserved stretch of an existing capture at the same station whose status is `RECORDED` or `FLAGGED` is refused with `ERR_STATION_OCCUPIED`; a capture landing exactly one second past the far end of the stretch is accepted."

        Design: Difficulty/resource_temporal_overlap/station_lock_is_a_closed_interval_of_capture_lock_plus_sixty_seconds
        """
        _site, prep, _hot_line, food_type, shift, _first = self._world()

        response = api_client.create_waste_entry(
            self._capture_payload(prep["id"], shift["id"], food_type["id"], "2026-06-10T10:01:30Z"),
            make_kitchen_staff_headers("ks-2"),
        )
        validate_error(response, ApiErrorId.STATION_OCCUPIED.value)

    def test_the_reservation_binds_one_scale_only(self):
        """The same blocked instant is free at the hot line, because each scale reserves itself.

        PRD Coverage: "Each capture reserves the station for a stretch of time so two operators cannot double-post the same tray." "A new capture whose `captured_at` falls anywhere inside the reserved stretch of an existing capture at the same station whose status is `RECORDED` or `FLAGGED` is refused with `ERR_STATION_OCCUPIED`; a capture landing exactly one second past the far end of the stretch is accepted."

        Design: Difficulty/resource_temporal_overlap/station_lock_is_a_closed_interval_of_capture_lock_plus_sixty_seconds
        """
        _site, prep, hot_line, food_type, shift, _first = self._world()

        blocked = api_client.create_waste_entry(
            self._capture_payload(prep["id"], shift["id"], food_type["id"], "2026-06-10T10:01:30Z"),
            make_kitchen_staff_headers("ks-2"),
        )
        validate_error(blocked, ApiErrorId.STATION_OCCUPIED.value)

        elsewhere = api_client.create_waste_entry(
            self._capture_payload(hot_line["id"], shift["id"], food_type["id"], "2026-06-10T10:01:30Z"),
            make_kitchen_staff_headers("ks-2"),
        )
        accepted = get_success_data(elsewhere, 201)
        assert accepted["station_id"] == hot_line["id"]
        _assert_instant(accepted["capture_window_end"], "2026-06-10T10:02:00.000Z")

    def test_one_second_past_the_reservation_is_free_again(self):
        """The turnaround finishes at ninety seconds, so ninety-one seconds is a clean scale.

        PRD Coverage: "A new capture whose `captured_at` falls anywhere inside the reserved stretch of an existing capture at the same station whose status is `RECORDED` or `FLAGGED` is refused with `ERR_STATION_OCCUPIED`; a capture landing exactly one second past the far end of the stretch is accepted." "The owning service period recomputes `shift_waste_grams`, the sum of `weight_grams` over its captures whose status is `RECORDED` or `FLAGGED`"

        Design: Difficulty/resource_temporal_overlap/station_lock_is_a_closed_interval_of_capture_lock_plus_sixty_seconds
        """
        _site, prep, _hot_line, food_type, shift, _first = self._world()

        blocked = api_client.create_waste_entry(
            self._capture_payload(prep["id"], shift["id"], food_type["id"], "2026-06-10T10:01:30Z"),
            make_kitchen_staff_headers("ks-2"),
        )
        validate_error(blocked, ApiErrorId.STATION_OCCUPIED.value)

        accepted = get_success_data(
            api_client.create_waste_entry(
                self._capture_payload(prep["id"], shift["id"], food_type["id"], "2026-06-10T10:01:31Z"),
                make_kitchen_staff_headers("ks-2"),
            ),
            201,
        )
        assert accepted["station_id"] == prep["id"]

        assert fixtures.read_shift(shift["id"])["shift_waste_grams"] == 800
        _rows, meta = validate_paginated(
            api_client.list_waste_entries(make_kitchen_staff_headers("ks-2"), station_id=prep["id"])
        )
        assert meta["total_count"] == 2


class TestPickupWindowsAreHalfOpen:
    """A collector with one truck can take back-to-back pickups but not overlapping ones."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        hauler = fixtures.create_approved_hauler(
            name="Green Loop Compost",
            channels=["COMPOST"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=1,
        )
        incumbent = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-08-10T08:00:00Z",
            pickup_window_end="2026-08-10T10:00:00Z",
        )
        return site, hauler, incumbent

    def test_a_one_minute_overlap_consumes_the_only_truck(self):
        """A window reaching back one minute into the incumbent's slot genuinely intersects it.

        PRD Coverage: "The pickup window is then checked against the hauler's aggregate concurrency: counting only the hauler's consignments whose `logistics_status` is `DRAFT`, `STAGED` or `DISPATCHED`, the number whose half-open interval from `pickup_window_start` up to but excluding `pickup_window_end` intersects the requested half-open interval must remain strictly below `max_concurrent_pickups`, otherwise the request is refused with `ERR_HAULER_WINDOW_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/hauler_window_capacity_is_half_open_so_touching_windows_are_allowed
        """
        site, hauler, _incumbent = self._world()

        response = api_client.create_consignment(
            factories.create_consignment_payload(
                site["id"],
                hauler["id"],
                channel="COMPOST",
                pickup_window_start="2026-08-10T09:59:00Z",
                pickup_window_end="2026-08-10T11:00:00Z",
            ),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.HAULER_WINDOW_CAPACITY.value)

        _rows, meta = validate_paginated(
            api_client.list_consignments(
                make_site_sustainability_manager_headers(site["id"]), hauler_id=hauler["id"]
            )
        )
        assert meta["total_count"] == 1

    def test_a_window_starting_exactly_where_the_last_ends_is_allowed(self):
        """Touching slots do not overlap, so one truck can serve both without a second one.

        PRD Coverage: "Two windows that merely touch at an endpoint — one ending exactly where the next begins — do not intersect and do not consume capacity." "A new consignment also has `staged_weight_grams` and `line_count` at 0, and `cancel_reason`, `staged_at` and `dispatched_at` all null."

        Design: Difficulty/resource_temporal_overlap/hauler_window_capacity_is_half_open_so_touching_windows_are_allowed
        """
        site, hauler, _incumbent = self._world()

        blocked = api_client.create_consignment(
            factories.create_consignment_payload(
                site["id"],
                hauler["id"],
                channel="COMPOST",
                pickup_window_start="2026-08-10T09:59:00Z",
                pickup_window_end="2026-08-10T11:00:00Z",
            ),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(blocked, ApiErrorId.HAULER_WINDOW_CAPACITY.value)

        touching = get_success_data(
            api_client.create_consignment(
                factories.create_consignment_payload(
                    site["id"],
                    hauler["id"],
                    channel="COMPOST",
                    pickup_window_start="2026-08-10T10:00:00Z",
                    pickup_window_end="2026-08-10T11:00:00Z",
                ),
                make_site_sustainability_manager_headers(site["id"]),
            ),
            201,
        )
        assert_consignment(touching)
        assert touching["logistics_status"] == "DRAFT"
        assert touching["settlement_status"] == "UNBILLED"
        assert touching["staged_weight_grams"] == 0
        assert touching["line_count"] == 0
        assert touching["staged_at"] is None

        _rows, meta = validate_paginated(
            api_client.list_consignments(
                make_site_sustainability_manager_headers(site["id"]),
                hauler_id=hauler["id"],
                logistics_status="DRAFT",
            )
        )
        assert meta["total_count"] == 2

    def test_a_zero_length_window_reserves_nothing_and_is_rejected(self):
        """A slot that begins and ends at the same instant is not a pickup at all.

        PRD Coverage: "A consignment is opened by the owning `SiteSustainabilityManager` with the `site_id` the material leaves from, the `hauler_id` collecting it, a `channel` drawn from the same four values, and a reserved pickup interval given by `pickup_window_start` inclusive and `pickup_window_end` exclusive, where the end must be strictly after the start."

        Design: Difficulty/resource_temporal_overlap/hauler_window_capacity_is_half_open_so_touching_windows_are_allowed
        """
        site, hauler, _incumbent = self._world()

        response = api_client.create_consignment(
            factories.create_consignment_payload(
                site["id"],
                hauler["id"],
                channel="COMPOST",
                pickup_window_start="2026-08-10T12:00:00Z",
                pickup_window_end="2026-08-10T12:00:00Z",
            ),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        _rows, meta = validate_paginated(
            api_client.list_consignments(
                make_site_sustainability_manager_headers(site["id"]), hauler_id=hauler["id"]
            )
        )
        assert meta["total_count"] == 1


class TestDeletingAnAllocationRestoresTheGramSplit:
    """Un-routing grams is the exact inverse of routing them, with no drift anywhere."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        hauler = fixtures.create_approved_hauler(
            name="Green Loop Compost",
            channels=["COMPOST"],
            rate_cents_per_tonne=52000,
            stop_fee_cents=1800,
            capacity_kg_per_pickup=500,
            max_concurrent_pickups=1,
        )
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        entry = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        )
        consignment = fixtures.open_consignment(
            site["id"],
            hauler["id"],
            channel="COMPOST",
            pickup_window_start="2026-06-11T08:00:00Z",
            pickup_window_end="2026-06-11T10:00:00Z",
            container_tare_grams=0,
        )
        line = fixtures.add_line(site["id"], consignment["id"], entry["id"], 400)
        return site, entry, consignment, line

    def test_a_partial_allocation_splits_the_capture(self):
        """Four hundred of a thousand grams leave the kitchen; six hundred stay available.

        PRD Coverage: "A line names its `consignment_id`, the `waste_entry_id` whose weight is being routed, and the `allocated_weight_grams` being routed, which may be a partial slice of the capture — the same capture can be split across several consignments and channels." "Every line insertion and deletion re-derives four figures from the surviving source rows. For the affected capture, `routed_weight_grams` becomes the sum of `allocated_weight_grams` over all its lines whose consignment's `logistics_status` is anything other than `CANCELLED`, and `unrouted_weight_grams` becomes its `weight_grams` minus that routed figure. For the consignment, `staged_weight_grams` becomes the sum of `allocated_weight_grams` over its lines and `line_count` becomes the number of lines attached."

        Design: Difficulty/compensating_invariant/deleting_a_consignment_line_restores_the_gram_conservation_exactly
        """
        _site, entry, consignment, _line = self._world()

        stored_entry = fixtures.read_entry(entry["id"])
        assert_waste_entry(stored_entry)
        assert stored_entry["weight_grams"] == 1000
        assert stored_entry["routed_weight_grams"] == 400
        assert stored_entry["unrouted_weight_grams"] == 600

        stored_consignment = fixtures.read_consignment(consignment["id"])
        assert stored_consignment["line_count"] == 1
        assert stored_consignment["staged_weight_grams"] == 400

    def test_deleting_the_allocation_restores_the_split_exactly(self):
        """Removing the line puts every gram back where it started, with the identity intact.

        PRD Coverage: "Deleting a line — permitted only while the consignment is `DRAFT`, and available to the same two roles — restores the capture's unrouted grams exactly, so the identity that a capture's `weight_grams` equals its routed plus its unrouted grams holds continuously and with zero drift."

        Design: Difficulty/compensating_invariant/deleting_a_consignment_line_restores_the_gram_conservation_exactly
        """
        site, entry, consignment, line = self._world()

        fixtures.delete_line(site["id"], line["id"])

        restored = fixtures.read_entry(entry["id"])
        assert_gram_conservation(restored)
        assert restored["weight_grams"] == 1000
        assert restored["routed_weight_grams"] == 0
        assert restored["unrouted_weight_grams"] == 1000

        emptied = fixtures.read_consignment(consignment["id"])
        assert emptied["line_count"] == 0
        assert emptied["staged_weight_grams"] == 0

        _rows, meta = validate_paginated(
            api_client.list_consignment_lines(
                make_site_sustainability_manager_headers(site["id"]), consignment_id=consignment["id"]
            )
        )
        assert meta["total_count"] == 0

    def test_the_released_grams_are_genuinely_routable_again(self):
        """The full thousand grams can now be allocated, and a second thousand cannot.

        PRD Coverage: "Finally `allocated_weight_grams` must be at least 1 and no greater than the capture's current `unrouted_weight_grams`; over-allocation is refused with `ERR_ALLOCATION_EXCEEDS_UNROUTED`."

        Design: Difficulty/compensating_invariant/deleting_a_consignment_line_restores_the_gram_conservation_exactly
        """
        site, entry, consignment, line = self._world()
        fixtures.delete_line(site["id"], line["id"])

        fixtures.add_line(site["id"], consignment["id"], entry["id"], 1000)
        refilled = fixtures.read_entry(entry["id"])
        assert refilled["routed_weight_grams"] == 1000
        assert refilled["unrouted_weight_grams"] == 0

        response = api_client.create_consignment_line(
            factories.create_consignment_line_payload(consignment["id"], entry["id"], 1000),
            make_site_sustainability_manager_headers(site["id"]),
        )
        validate_error(response, ApiErrorId.ALLOCATION_EXCEEDS_UNROUTED.value)

    def test_the_site_scoreboard_never_moves_across_the_round_trip(self):
        """Routing and un-routing are logistics events; the captured and settled totals hold still.

        PRD Coverage: "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`; `valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures; `diverted_weight_grams_settled` is the sum of `allocated_weight_grams` over the site's allocation lines whose consignment has reached `SETTLED` on the settlement dimension and has not been `CANCELLED` on the logistics dimension"

        Design: Difficulty/compensating_invariant/deleting_a_consignment_line_restores_the_gram_conservation_exactly
        """
        site, _entry, _consignment, line = self._world()

        before = fixtures.read_site(site["id"])
        assert before["total_captured_weight_grams"] == 1000
        assert before["diverted_weight_grams_settled"] == 0

        fixtures.delete_line(site["id"], line["id"])

        after = fixtures.read_site(site["id"])
        assert after["total_captured_weight_grams"] == 1000
        assert after["diverted_weight_grams_settled"] == 0

    def test_the_compensation_is_only_available_before_the_load_is_locked(self):
        """Once the pallet is staged the line set is frozen and the inverse is unavailable.

        PRD Coverage: "The consignment must still be in `DRAFT`; once it has left `DRAFT` no line may be added or deleted and the attempt is refused with `ERR_INVALID_CONSIGNMENT_STATE`." "On success `staged_at` is stamped with the current logical clock, `staged_weight_grams` is frozen for the later ticket variance comparison, no further line may be added or deleted, and `version` is incremented by 1."

        Design: Difficulty/compensating_invariant/deleting_a_consignment_line_restores_the_gram_conservation_exactly
        """
        site, entry, consignment, line = self._world()
        fixtures.stage_consignment(site["id"], consignment["id"])

        response = api_client.delete_consignment_line(
            line["id"], make_site_sustainability_manager_headers(site["id"])
        )
        validate_error(response, ApiErrorId.INVALID_CONSIGNMENT_STATE.value)

        unchanged = fixtures.read_entry(entry["id"])
        assert unchanged["routed_weight_grams"] == 400
        assert unchanged["unrouted_weight_grams"] == 600
        assert fixtures.read_consignment(consignment["id"])["line_count"] == 1


class TestVoidingACorrectionRestoresTheCostLedger:
    """The supersede-then-retract cycle returns the site's money figure to the exact cent."""

    @staticmethod
    def _world():
        site = fixtures.create_site()
        station = fixtures.create_station(
            site["id"],
            station_code="PREP-1",
            station_kind="PREP",
            calibration_due_at=CALIBRATION_DUE_AT,
            capture_lock_seconds=30,
        )
        food_type = _prepared_food_type()
        shift = fixtures.open_shift(
            site["id"], shift_date="2026-06-10", shift_code="AM", meals_served=1000
        )
        original = fixtures.capture_entry(
            station["id"],
            shift["id"],
            food_type["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
            user_id="ks-1",
        )
        return site, shift, original

    @staticmethod
    def _correct(original, weight_grams=1500):
        return fixtures.correct_entry(
            original["id"],
            original["version"],
            user_id="sl-1",
            correction_note="scale under-read by 500 g",
            weight_grams=weight_grams,
        )

    def test_the_original_capture_puts_its_own_cents_on_the_site(self):
        """A kilogram of the catalog item at 640 cents per kilogram values at 640 cents.

        PRD Coverage: "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`; `valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures"

        Design: Difficulty/compensating_invariant/voiding_a_correcting_entry_restores_the_site_cost_ledger_to_the_exact_cent
        """
        site, _shift, original = self._world()

        assert original["captured_by_user_id"] == "ks-1"
        assert original["provisional_cost_cents"] == 640
        assert original["effective_cost_cents"] == 640

        stored_site = fixtures.read_site(site["id"])
        assert stored_site["valued_waste_cost_cents"] == 640
        assert stored_site["total_captured_weight_grams"] == 1000

    def test_the_correction_replaces_the_original_rather_than_adding_to_it(self):
        """Only the successor counts, so the site never shows 2500 grams or 1600 cents.

        PRD Coverage: "On success the original capture's status becomes `SUPERSEDED`, which removes it from every `RECORDED`-or-`FLAGGED` aggregation set while leaving it visible to the compliance numerator, and its `version` is incremented by 1." "stores the supplied `correction_note`, and stamps `captured_by_user_id` with the correcting `ShiftLead`'s own `X-User-ID` — which means that lead becomes the identity barred from later voiding the correction."

        Design: Difficulty/compensating_invariant/voiding_a_correcting_entry_restores_the_site_cost_ledger_to_the_exact_cent
        """
        site, _shift, original = self._world()

        corrector = self._correct(original)
        assert corrector["corrects_entry_id"] == original["id"]
        assert corrector["captured_by_user_id"] == "sl-1"
        assert corrector["weight_grams"] == 1500
        assert corrector["provisional_cost_cents"] == 960
        assert fixtures.read_entry(original["id"])["status"] == "SUPERSEDED"

        stored_site = fixtures.read_site(site["id"])
        assert stored_site["valued_waste_cost_cents"] == 960
        assert stored_site["total_captured_weight_grams"] == 1500

        rows, meta = validate_paginated(
            api_client.list_waste_entries(make_shift_lead_headers("sl-1"), site_id=site["id"])
        )
        assert meta["total_count"] == 2
        assert_site_cost_ledger(stored_site, rows)

    def test_voiding_the_correction_restores_the_ledger_to_the_exact_cent(self):
        """The predecessor comes back and the money figure lands on 640 with zero drift.

        PRD Coverage: "When a correcting capture is itself voided, the predecessor it superseded transitions `SUPERSEDED → RECORDED`, re-entering every aggregation set before the service period's and the site's aggregates are recomputed, and its `version` is incremented by 1." "Because every aggregate is a full recompute rather than a running delta, this restores the site's `valued_waste_cost_cents` to exactly its pre-correction value with zero drift."

        Design: Difficulty/compensating_invariant/voiding_a_correcting_entry_restores_the_site_cost_ledger_to_the_exact_cent
        """
        site, _shift, original = self._world()
        corrector = self._correct(original)

        fixtures.void_entry(
            corrector["id"],
            user_id="sl-2",
            void_reason="correction belonged to the PM service",
        )

        restored_site = fixtures.read_site(site["id"])
        assert restored_site["valued_waste_cost_cents"] == 640
        assert restored_site["total_captured_weight_grams"] == 1000

        restored_original = fixtures.read_entry(original["id"])
        assert restored_original["status"] == "RECORDED"
        assert restored_original["effective_cost_cents"] == 640

    def test_the_retracted_correction_keeps_its_own_valuation_for_audit(self):
        """The void hides the successor from the totals but does not erase what it said.

        PRD Coverage: "In the first hop the capture's status becomes `VOIDED`, `void_reason` is stored, and the entry leaves every `RECORDED`-or-`FLAGGED` aggregation set." "The restored status is always `RECORDED`, never `FLAGGED`, even when the entry happened to be `FLAGGED` at the moment it was superseded."

        Design: Difficulty/compensating_invariant/voiding_a_correcting_entry_restores_the_site_cost_ledger_to_the_exact_cent
        """
        site, shift, original = self._world()
        corrector = self._correct(original)
        fixtures.void_entry(
            corrector["id"],
            user_id="sl-2",
            void_reason="correction belonged to the PM service",
        )

        voided = fixtures.read_entry(corrector["id"])
        assert voided["status"] == "VOIDED"
        assert voided["weight_grams"] == 1500
        assert voided["effective_cost_cents"] == 960
        assert voided["void_reason"] == "correction belonged to the PM service"

        stored_shift = fixtures.read_shift(shift["id"])
        assert stored_shift["shift_waste_grams"] == 1000
        assert stored_shift["waste_intensity_kg_per_1k_meals"] == pytest.approx(1.000, abs=0.01)

        _alerts, meta = validate_paginated(
            api_client.list_alerts(make_shift_lead_headers("sl-1"), site_id=site["id"])
        )
        assert meta["total_count"] == 0

    def test_the_correcting_lead_may_not_retract_their_own_correction(self):
        """The lead who wrote the successor is the identity barred from voiding it.

        PRD Coverage: "The acting `ShiftLead`'s `X-User-ID` must differ from the capture's `captured_by_user_id`; a lead attempting to erase their own capture is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/compensating_invariant/voiding_a_correcting_entry_restores_the_site_cost_ledger_to_the_exact_cent
        """
        site, _shift, original = self._world()
        corrector = self._correct(original)

        response = api_client.void_waste_entry(
            corrector["id"],
            factories.void_payload(void_reason="correction belonged to the PM service"),
            make_shift_lead_headers("sl-1"),
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)

        assert fixtures.read_entry(corrector["id"])["status"] == "RECORDED"
        assert fixtures.read_site(site["id"])["valued_waste_cost_cents"] == 960

    def test_the_restored_capture_may_not_be_corrected_a_second_time(self):
        """Coming back to RECORDED does not clear the fact that it already has a successor.

        PRD Coverage: "A given capture may be corrected at most once — a second correction against a capture that already has a successor is refused with `ERR_ENTRY_ALREADY_CORRECTED`."

        Design: Difficulty/compensating_invariant/voiding_a_correcting_entry_restores_the_site_cost_ledger_to_the_exact_cent
        """
        site, _shift, original = self._world()
        corrector = self._correct(original)
        fixtures.void_entry(
            corrector["id"],
            user_id="sl-2",
            void_reason="correction belonged to the PM service",
        )

        restored = fixtures.read_entry(original["id"])
        response = api_client.correct_waste_entry(
            restored["id"],
            factories.correction_payload(
                restored["version"],
                correction_note="second attempt at the same tray",
                weight_grams=1200,
            ),
            make_shift_lead_headers("sl-1"),
        )
        validate_error(response, ApiErrorId.ENTRY_ALREADY_CORRECTED.value)

        assert fixtures.read_site(site["id"])["valued_waste_cost_cents"] == 640
