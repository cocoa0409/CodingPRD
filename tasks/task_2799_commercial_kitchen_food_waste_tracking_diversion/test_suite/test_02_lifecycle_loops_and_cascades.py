"""Repeatable lifecycle loops and the multi-hop consequences of a single request.

Review cycles run more than once on the same row, a consignment's billing axis cycles
while its physical axis stays pinned, and a rejected baseline recomputes its freeze over
data that moved underneath it. The cascade groups follow one write four hops out, from a
capture through a service period and its coaching alerts to the site's posture, and along
the money path from a period close to an expired alert.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_baseline_period,
    assert_coaching_alert,
    assert_coaching_posture_ladder,
    assert_consignment,
    assert_effective_cost_selection,
    assert_hauler_ticket,
    assert_reduction_target,
    assert_settlement_breakdown,
    assert_shift,
    assert_site_cost_ledger,
    assert_timestamp_has_three_fractional_digits,
    assert_waste_entry,
    api_client,
    factories,
    fixtures,
    make_platform_admin_headers,
    validate_error,
    validate_paginated,
)

CAPTURE_DAY = "2026-06-10"
CAPTURE_AT = "2026-06-10T10:00:00Z"
CALIBRATION_DUE = "2027-01-01T00:00:00Z"
DEFAULT_CLOCK_PREFIX = "2026-08-01T00:00:00"


def _prep_bench_and_catalog(**site_overrides):
    """A site with one PREP station and the 640 cents/kg prepared food type."""
    site = fixtures.create_site(
        name="Harbor Kitchen", site_code="HK-01", region_code="NE", **site_overrides
    )
    station = fixtures.create_station(
        site["id"],
        station_code="PREP-1",
        station_kind="PREP",
        calibration_due_at=CALIBRATION_DUE,
        capture_lock_seconds=30,
    )
    food_type = fixtures.create_food_type(
        name="Braised Chicken Portion",
        category="PREPARED",
        default_cost_per_kg_cents=640,
        donation_eligible=True,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=24,
    )
    return site, station, food_type


def _one_capture_on_a_quiet_shift():
    """A single 1000 gram capture on a 1000-meal period, far below any coaching threshold."""
    site, station, food_type = _prep_bench_and_catalog()
    shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=1000)
    entry = fixtures.capture_entry(
        station["id"],
        shift["id"],
        food_type["id"],
        weight_grams=1000,
        loss_reason="TRIM",
        captured_at=CAPTURE_AT,
    )
    return site, station, food_type, shift, entry


def _flag_clear_flag(entry_id):
    """Walk the review cycle twice, ending FLAGGED on the second reason."""
    fixtures.flag_entry(entry_id, flag_reason="suspected double weigh")
    fixtures.clear_entry_flag(entry_id)
    return fixtures.flag_entry(entry_id, flag_reason="scale drift confirmed")


class TestCaptureReviewCycleAndRestore:
    """The flag loop repeats, and a voided correction hands the predecessor back as RECORDED."""

    def test_the_review_cycle_repeats_without_moving_a_single_gram(self):
        """RECORDED to FLAGGED to RECORDED to FLAGGED, versions 1 through 4, totals untouched.

        PRD Coverage:
        "Flagging marks a capture as needing review without removing a single gram from any total. It advances `RECORDED → FLAGGED`, requires a `flag_reason` in the request, and increments the capture's `version` by 1."
        "Clearing the flag advances `FLAGGED → RECORDED`, takes no request body, retains the previously recorded `flag_reason` for audit rather than nulling it, likewise changes no aggregate, and increments `version` by 1. These two edges together form a repeatable review cycle: a capture may be flagged, cleared, and flagged again."

        Design: Difficulty/non_linear_state_machine/waste_entry_flag_loop_twice_then_supersede_and_compensating_restore_to_recorded
        """
        site, station, food_type, shift, entry = _one_capture_on_a_quiet_shift()
        assert entry["status"] == "RECORDED"
        assert entry["version"] == 1

        first_flag = fixtures.flag_entry(entry["id"], flag_reason="suspected double weigh")
        assert first_flag["status"] == "FLAGGED"
        assert first_flag["version"] == 2
        assert first_flag["flag_reason"] == "suspected double weigh"

        cleared = fixtures.clear_entry_flag(entry["id"])
        assert cleared["status"] == "RECORDED"
        assert cleared["version"] == 3
        assert cleared["flag_reason"] == "suspected double weigh"

        second_flag = fixtures.flag_entry(entry["id"], flag_reason="scale drift confirmed")
        assert second_flag["status"] == "FLAGGED"
        assert second_flag["version"] == 4
        assert second_flag["flag_reason"] == "scale drift confirmed"

        site_now = fixtures.read_site(site["id"])
        assert site_now["total_captured_weight_grams"] == 1000
        assert site_now["valued_waste_cost_cents"] == 640
        assert fixtures.read_shift(shift["id"])["shift_waste_grams"] == 1000

    def test_correcting_a_flagged_capture_creates_an_inheriting_successor(self):
        """The successor copies placement, instant and loss reason and reprices at 768 cents.

        PRD Coverage:
        "A **new** capture is created in status `RECORDED` with `corrects_entry_id` pointing at the original's `id`."
        "The new record copies `station_id`, `shift_id` and `captured_at` from the original, takes `weight_grams`, `food_type_id`, `loss_reason` and `recipe_id` from the request where supplied and falls back to the original's values for each field omitted, stores the supplied `correction_note`, and stamps `captured_by_user_id` with the correcting `ShiftLead`'s own `X-User-ID` — which means that lead becomes the identity barred from later voiding the correction."

        Design: Difficulty/non_linear_state_machine/waste_entry_flag_loop_twice_then_supersede_and_compensating_restore_to_recorded
        """
        site, station, food_type, shift, entry = _one_capture_on_a_quiet_shift()
        flagged = _flag_clear_flag(entry["id"])

        corrector = fixtures.correct_entry(
            entry["id"],
            flagged["version"],
            user_id="sl-1",
            correction_note="reweighed on calibrated scale",
            weight_grams=1200,
        )

        assert_waste_entry(corrector)
        assert corrector["id"] != entry["id"]
        assert corrector["status"] == "RECORDED"
        assert corrector["corrects_entry_id"] == entry["id"]
        assert corrector["correction_note"] == "reweighed on calibrated scale"
        assert corrector["weight_grams"] == 1200
        assert corrector["station_id"] == station["id"]
        assert corrector["shift_id"] == shift["id"]
        assert corrector["food_type_id"] == food_type["id"]
        assert corrector["captured_at"] == entry["captured_at"]
        assert corrector["loss_reason"] == "TRIM"
        assert corrector["provisional_cost_cents"] == 768
        assert corrector["effective_cost_cents"] == 768
        assert corrector["captured_by_user_id"] == TEST_USERS["shift_lead"]["user_id"]

    def test_the_corrected_original_is_superseded_and_leaves_the_totals(self):
        """The predecessor steps out of every aggregation set at version 5.

        PRD Coverage:
        "On success the original capture's status becomes `SUPERSEDED`, which removes it from every `RECORDED`-or-`FLAGGED` aggregation set while leaving it visible to the compliance numerator, and its `version` is incremented by 1."

        Design: Difficulty/non_linear_state_machine/waste_entry_flag_loop_twice_then_supersede_and_compensating_restore_to_recorded
        """
        site, station, food_type, shift, entry = _one_capture_on_a_quiet_shift()
        flagged = _flag_clear_flag(entry["id"])

        fixtures.correct_entry(
            entry["id"],
            flagged["version"],
            user_id="sl-1",
            correction_note="reweighed on calibrated scale",
            weight_grams=1200,
        )

        superseded = fixtures.read_entry(entry["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == 5

        site_now = fixtures.read_site(site["id"])
        assert site_now["total_captured_weight_grams"] == 1200
        assert site_now["valued_waste_cost_cents"] == 768

    def test_voiding_the_correction_hands_the_predecessor_back_as_recorded(self, api, platform_admin_headers):
        """The restore lands on RECORDED, never FLAGGED, and returns the ledger to the exact cent.

        PRD Coverage:
        "When a correcting capture is itself voided, the predecessor it superseded transitions `SUPERSEDED → RECORDED`, re-entering every aggregation set before the service period's and the site's aggregates are recomputed, and its `version` is incremented by 1. The restored status is always `RECORDED`, never `FLAGGED`, even when the entry happened to be `FLAGGED` at the moment it was superseded. Because every aggregate is a full recompute rather than a running delta, this restores the site's `valued_waste_cost_cents` to exactly its pre-correction value with zero drift."

        Design: Difficulty/non_linear_state_machine/waste_entry_flag_loop_twice_then_supersede_and_compensating_restore_to_recorded
        """
        site, station, food_type, shift, entry = _one_capture_on_a_quiet_shift()
        flagged = _flag_clear_flag(entry["id"])
        corrector = fixtures.correct_entry(
            entry["id"],
            flagged["version"],
            user_id="sl-1",
            correction_note="reweighed on calibrated scale",
            weight_grams=1200,
        )

        voided = fixtures.void_entry(
            corrector["id"], user_id="sl-2", void_reason="correction entered against the wrong ticket"
        )

        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "correction entered against the wrong ticket"

        restored = fixtures.read_entry(entry["id"])
        assert restored["status"] == "RECORDED"
        assert restored["version"] == 6
        assert restored["flag_reason"] == "scale drift confirmed"

        site_now = fixtures.read_site(site["id"])
        assert site_now["total_captured_weight_grams"] == 1000
        assert site_now["valued_waste_cost_cents"] == 640
        assert_site_cost_ledger(site_now, [restored, fixtures.read_entry(corrector["id"])])

        rows, meta = validate_paginated(api.list_waste_entries(platform_admin_headers, shift_id=shift["id"]))
        assert meta["total_count"] == 2


def _dispatched_thousand_gram_compost_load():
    """One 1000 gram capture, fully routed, staged and dispatched on a zero-tare container."""
    site, station, food_type = _prep_bench_and_catalog()
    hauler = fixtures.create_approved_hauler(
        name="Green Loop Compost",
        channels=["COMPOST"],
        rate_cents_per_tonne=52000,
        stop_fee_cents=1800,
        capacity_kg_per_pickup=500,
        max_concurrent_pickups=1,
    )
    shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=1000)
    entry = fixtures.capture_entry(
        station["id"],
        shift["id"],
        food_type["id"],
        weight_grams=1000,
        loss_reason="TRIM",
        captured_at=CAPTURE_AT,
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
    fixtures.stage_consignment(site["id"], consignment["id"])
    consignment = fixtures.dispatch_consignment(site["id"], consignment["id"])
    return site, hauler, consignment, entry


class TestSettlementAxisCycle:
    """Billing cycles through a dispute and back while the physical axis holds at DISPATCHED."""

    def test_the_billing_axis_cycles_while_the_physical_axis_stays_pinned(self):
        """Four consecutive observations show the settlement axis move and logistics stand still.

        PRD Coverage:
        "`logistics_status` tracks physical movement through `DRAFT`, `STAGED`, `DISPATCHED`, `COMPLETED` and `CANCELLED`, starting at `DRAFT`. `settlement_status` tracks billing through `UNBILLED`, `TICKET_SUBMITTED`, `SETTLED` and `DISPUTED`, starting at `UNBILLED`."
        "It advances the ticket `SUBMITTED → DISPUTED` and sets the consignment's `settlement_status` to `DISPUTED` while `logistics_status` stays `DISPATCHED` throughout."
        "The disputed ticket itself stays `DISPUTED` forever; it is never reopened. Instead the hauler files a **replacement** ticket with a fresh `ticket_number` against the same consignment, which is permitted precisely because `settlement_status` is `DISPUTED`, and which returns the settlement dimension to `TICKET_SUBMITTED`. That gives the settlement axis its own cycle, `TICKET_SUBMITTED → DISPUTED → TICKET_SUBMITTED`, repeatable as often as the parties disagree, entirely independent of the logistics axis which remains `DISPATCHED` the whole time."

        Design: Difficulty/non_linear_state_machine/consignment_settlement_dimension_cycles_while_logistics_dimension_is_pinned
        """
        site, hauler, consignment, entry = _dispatched_thousand_gram_compost_load()
        assert_consignment(consignment)
        observed = [(consignment["settlement_status"], consignment["logistics_status"])]

        first = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1000, ticket_number="GLC-1", ticket_date="2026-06-11"
        )
        after_first = fixtures.read_consignment(consignment["id"])
        observed.append((after_first["settlement_status"], after_first["logistics_status"]))

        fixtures.dispute_ticket(site["id"], first["id"], dispute_note="weighbridge printout unreadable")
        after_dispute = fixtures.read_consignment(consignment["id"])
        observed.append((after_dispute["settlement_status"], after_dispute["logistics_status"]))

        fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1200, ticket_number="GLC-2", ticket_date="2026-06-11"
        )
        after_replacement = fixtures.read_consignment(consignment["id"])
        observed.append((after_replacement["settlement_status"], after_replacement["logistics_status"]))

        assert observed == [
            ("UNBILLED", "DISPATCHED"),
            ("TICKET_SUBMITTED", "DISPATCHED"),
            ("DISPUTED", "DISPATCHED"),
            ("TICKET_SUBMITTED", "DISPATCHED"),
        ]

    def test_the_replacement_ticket_earns_a_variance_credit_the_first_one_did_not(self):
        """1000 net matches the staged weight exactly; 1200 net is 20.00 percent over and pays 186.

        PRD Coverage:
        "**Step six** measures the scale disagreement: `variance_pct` is the absolute difference between `net_weight_grams` and the consignment's frozen `staged_weight_grams`, divided by that `staged_weight_grams`, multiplied by 100 and rounded half up to 2 decimal places; `variance_credit_cents` is 10 percent of `settlement_subtotal_cents`, rounded half up to a whole number of cents, when `variance_pct` is **strictly greater** than a 5.00 percent tolerance, and 0 otherwise — a variance of exactly 5.00 percent earns no credit."
        "**Step seven**: `settlement_total_cents` is `settlement_subtotal_cents` minus `variance_credit_cents`."

        Design: Difficulty/non_linear_state_machine/consignment_settlement_dimension_cycles_while_logistics_dimension_is_pinned
        """
        site, hauler, consignment, entry = _dispatched_thousand_gram_compost_load()

        first = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1000, ticket_number="GLC-1", ticket_date="2026-06-11"
        )
        assert_hauler_ticket(first)
        assert_settlement_breakdown(
            first,
            net_weight_grams=1000,
            billable_tonnes=0.0010,
            base_haul_fee_cents=1852,
            fuel_surcharge_pct=0.00,
            fuel_surcharge_cents=0,
            settlement_subtotal_cents=1852,
            variance_pct=0.00,
            variance_credit_cents=0,
            settlement_total_cents=1852,
        )

        fixtures.dispute_ticket(site["id"], first["id"], dispute_note="weighbridge printout unreadable")
        second = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1200, ticket_number="GLC-2", ticket_date="2026-06-11"
        )

        assert_settlement_breakdown(
            second,
            net_weight_grams=1200,
            billable_tonnes=0.0012,
            base_haul_fee_cents=1862,
            fuel_surcharge_pct=0.00,
            fuel_surcharge_cents=0,
            settlement_subtotal_cents=1862,
            variance_pct=20.00,
            variance_credit_cents=186,
            settlement_total_cents=1676,
        )

    def test_accepting_the_replacement_moves_both_dimensions_in_one_request(self):
        """Settlement reaches SETTLED and logistics reaches COMPLETED together, crediting line grams.

        PRD Coverage:
        "The first hop flips both consignment dimensions in the same request: `settlement_status` advances `TICKET_SUBMITTED → SETTLED` and `logistics_status` advances `DISPATCHED → COMPLETED`."
        "`diverted_weight_grams_settled` is the sum of `allocated_weight_grams` over the site's allocation lines whose consignment has reached `SETTLED` on the settlement dimension and has not been `CANCELLED` on the logistics dimension; `diversion_rate_pct` is the settled diverted grams divided by the total captured grams, multiplied by 100 and rounded half up to 2 decimal places, and is null whenever `total_captured_weight_grams` is 0"

        Design: Difficulty/non_linear_state_machine/consignment_settlement_dimension_cycles_while_logistics_dimension_is_pinned
        """
        site, hauler, consignment, entry = _dispatched_thousand_gram_compost_load()
        first = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1000, ticket_number="GLC-1", ticket_date="2026-06-11"
        )
        fixtures.dispute_ticket(site["id"], first["id"], dispute_note="weighbridge printout unreadable")
        second = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1200, ticket_number="GLC-2", ticket_date="2026-06-11"
        )

        accepted = fixtures.accept_ticket(site["id"], second["id"])

        assert accepted["status"] == "ACCEPTED"
        settled = fixtures.read_consignment(consignment["id"])
        assert settled["settlement_status"] == "SETTLED"
        assert settled["logistics_status"] == "COMPLETED"

        site_now = fixtures.read_site(site["id"])
        assert site_now["diverted_weight_grams_settled"] == 1000
        assert site_now["total_captured_weight_grams"] == 1000
        assert site_now["diversion_rate_pct"] == pytest.approx(100.00, abs=0.01)

    def test_a_disputed_ticket_never_reopens_even_after_its_consignment_settles(
        self, api, site_manager_headers
    ):
        """The child stays DISPUTED for good, so a second acceptance is refused.

        PRD Coverage:
        "The disputed ticket itself stays `DISPUTED` forever; it is never reopened. Instead the hauler files a **replacement** ticket with a fresh `ticket_number` against the same consignment, which is permitted precisely because `settlement_status` is `DISPUTED`, and which returns the settlement dimension to `TICKET_SUBMITTED`. That gives the settlement axis its own cycle, `TICKET_SUBMITTED → DISPUTED → TICKET_SUBMITTED`, repeatable as often as the parties disagree, entirely independent of the logistics axis which remains `DISPATCHED` the whole time."
        "Acceptance requires the ticket to be `SUBMITTED`, refused otherwise with `ERR_INVALID_TICKET_STATE`"

        Design: Difficulty/non_linear_state_machine/consignment_settlement_dimension_cycles_while_logistics_dimension_is_pinned
        """
        site, hauler, consignment, entry = _dispatched_thousand_gram_compost_load()
        first = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1000, ticket_number="GLC-1", ticket_date="2026-06-11"
        )
        fixtures.dispute_ticket(site["id"], first["id"], dispute_note="weighbridge printout unreadable")
        second = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 1200, ticket_number="GLC-2", ticket_date="2026-06-11"
        )
        fixtures.accept_ticket(site["id"], second["id"])

        stale = fixtures.read_ticket(first["id"])
        assert stale["status"] == "DISPUTED"

        response = api.accept_hauler_ticket(first["id"], site_manager_headers(site["id"]))

        validate_error(response, ApiErrorId.INVALID_TICKET_STATE.value)
        assert fixtures.read_ticket(first["id"])["status"] == "DISPUTED"


def _june_tenth_service_and_an_open_june_window():
    """3000 grams over 250 meals on a closed June 10 period, inside an OPEN June window."""
    site, station, prep_food = _prep_bench_and_catalog()
    spoil_food = fixtures.create_food_type(
        name="Mixed Produce Trim",
        category="PRODUCE",
        default_cost_per_kg_cents=210,
        donation_eligible=False,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=12,
    )
    first_shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=250)
    for food, grams, reason, at in (
        (prep_food, 1200, "TRIM", "2026-06-10T10:00:00Z"),
        (prep_food, 1000, "TRIM", "2026-06-10T10:05:00Z"),
        (spoil_food, 800, "SPOILAGE", "2026-06-10T10:10:00Z"),
    ):
        fixtures.capture_entry(
            station["id"], first_shift["id"], food["id"], weight_grams=grams, loss_reason=reason, captured_at=at
        )
    fixtures.close_shift(first_shift["id"])
    period = fixtures.open_baseline(site["id"], start_date="2026-06-01", end_date="2026-06-30")
    return site, station, spoil_food, period


def _add_june_eleventh_service(site, station, spoil_food):
    """A second closed period inside the same window: 500 grams over 100 meals."""
    shift = fixtures.open_shift(site["id"], shift_date="2026-06-11", shift_code="AM", meals_served=100)
    fixtures.capture_entry(
        station["id"],
        shift["id"],
        spoil_food["id"],
        weight_grams=500,
        loss_reason="SPOILAGE",
        captured_at="2026-06-11T10:00:00Z",
    )
    return fixtures.close_shift(shift["id"])


class TestBaselineRevisionLoop:
    """Each lap of the revision cycle recomputes the freeze from whatever data now exists."""

    def test_the_first_submission_freezes_the_june_tenth_figures(self):
        """Three captures, 3000 grams, 250 meals and 1576 cents of effective cost are frozen.

        PRD Coverage:
        "Over the qualifying capture set, `baseline_entry_count` is the number of captures, `baseline_waste_grams` is the sum of their `weight_grams`, `baseline_waste_kg` is those grams divided by 1000 and rounded half up to 3 decimal places, and `baseline_cost_cents` is the sum of their `effective_cost_cents`."
        "Finally `baseline_intensity_kg_per_1k_meals` is `baseline_waste_grams` divided by `baseline_meals_served`, rounded half up to 3 decimal places, and is null when `baseline_meals_served` is 0."

        Design: Difficulty/non_linear_state_machine/baseline_period_rejection_loop_reruns_metrics_over_changed_source_data
        """
        site, station, spoil_food, period = _june_tenth_service_and_an_open_june_window()

        submitted = fixtures.submit_baseline(site["id"], period["id"])

        assert_baseline_period(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["baseline_entry_count"] == 3
        assert submitted["baseline_waste_grams"] == 3000
        assert submitted["baseline_waste_kg"] == pytest.approx(3.000, abs=0.01)
        assert submitted["baseline_meals_served"] == 250
        assert submitted["baseline_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)
        assert submitted["baseline_cost_cents"] == 1576
        assert submitted["rejection_count"] == 0

    def test_rejection_returns_the_window_to_open_and_clears_the_freeze(self):
        """The lap counter advances, the note survives and the frozen totals are wiped.

        PRD Coverage:
        "Rejection advances `SUBMITTED → OPEN`, stores the supplied `rejection_note`, increases `rejection_count` by 1, and clears every frozen baseline metric back to null or zero so that the next submission recomputes them from current data rather than reusing a stale freeze; the `rejection_note` itself is retained after the period cycles back to `OPEN`, and `version` is incremented by 1."
        "Because that edge returns the period to a submittable state, the revision cycle `OPEN → SUBMITTED → OPEN` is repeatable without limit and `rejection_count` is its loop counter."

        Design: Difficulty/non_linear_state_machine/baseline_period_rejection_loop_reruns_metrics_over_changed_source_data
        """
        site, station, spoil_food, period = _june_tenth_service_and_an_open_june_window()
        fixtures.submit_baseline(site["id"], period["id"])

        rejected = fixtures.reject_baseline(period["id"], rejection_note="June 11 service was omitted")

        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1
        assert rejected["rejection_note"] == "June 11 service was omitted"

        cleared = fixtures.read_baseline(period["id"])
        assert cleared["rejection_note"] == "June 11 service was omitted"
        assert cleared["baseline_entry_count"] == 0
        assert cleared["baseline_waste_grams"] == 0
        assert cleared["baseline_meals_served"] == 0
        assert cleared["baseline_cost_cents"] == 0

    def test_the_next_lap_re_derives_the_freeze_over_the_enlarged_source_set(self):
        """A second closed period joins the window, so the numbers come back different, then stable.

        PRD Coverage:
        "Only closed periods contribute meals; an `OPEN` period is excluded from the meals total even when its captures fall squarely inside the window, and those captures still count toward the waste total."
        "Because that edge returns the period to a submittable state, the revision cycle `OPEN → SUBMITTED → OPEN` is repeatable without limit and `rejection_count` is its loop counter."

        Design: Difficulty/non_linear_state_machine/baseline_period_rejection_loop_reruns_metrics_over_changed_source_data
        """
        site, station, spoil_food, period = _june_tenth_service_and_an_open_june_window()
        fixtures.submit_baseline(site["id"], period["id"])
        fixtures.reject_baseline(period["id"], rejection_note="June 11 service was omitted")
        _add_june_eleventh_service(site, station, spoil_food)

        second = fixtures.submit_baseline(site["id"], period["id"])

        assert second["baseline_entry_count"] == 4
        assert second["baseline_waste_grams"] == 3500
        assert second["baseline_waste_kg"] == pytest.approx(3.500, abs=0.01)
        assert second["baseline_meals_served"] == 350
        assert second["baseline_intensity_kg_per_1k_meals"] == pytest.approx(10.000, abs=0.01)
        assert second["baseline_cost_cents"] == 1681

        rejected_again = fixtures.reject_baseline(period["id"], rejection_note="recheck the produce cost basis")
        assert rejected_again["rejection_count"] == 2
        assert rejected_again["baseline_waste_grams"] == 0

        third = fixtures.submit_baseline(site["id"], period["id"])
        assert third["baseline_entry_count"] == 4
        assert third["baseline_waste_grams"] == 3500
        assert third["baseline_meals_served"] == 350
        assert third["baseline_intensity_kg_per_1k_meals"] == pytest.approx(10.000, abs=0.01)
        assert third["baseline_cost_cents"] == 1681
        assert third["rejection_count"] == 2

    def test_certification_makes_the_loop_unenterable(self, api, corporate_lead_headers, site_manager_headers):
        """The freeze becomes immutable and neither edge of the cycle is available again.

        PRD Coverage:
        "Certification advances `SUBMITTED → CERTIFIED`, additionally requires `baseline_meals_served` to be greater than 0 — certifying a window with frozen meals of zero is refused with `ERR_BASELINE_NO_DATA` — stamps `certified_at` with the current logical clock, makes the frozen metrics immutable, and increments `version` by 1. Certifying or rejecting a period that is not `SUBMITTED` is refused with `ERR_INVALID_BASELINE_STATE`."

        Design: Difficulty/non_linear_state_machine/baseline_period_rejection_loop_reruns_metrics_over_changed_source_data
        """
        site, station, spoil_food, period = _june_tenth_service_and_an_open_june_window()
        fixtures.submit_baseline(site["id"], period["id"])
        fixtures.reject_baseline(period["id"], rejection_note="June 11 service was omitted")
        _add_june_eleventh_service(site, station, spoil_food)
        fixtures.submit_baseline(site["id"], period["id"])
        fixtures.reject_baseline(period["id"], rejection_note="recheck the produce cost basis")
        fixtures.submit_baseline(site["id"], period["id"])

        certified = fixtures.certify_baseline(period["id"])

        assert certified["status"] == "CERTIFIED"
        assert certified["certified_at"].startswith(DEFAULT_CLOCK_PREFIX)
        assert_timestamp_has_three_fractional_digits(certified["certified_at"])
        assert certified["rejection_count"] == 2
        assert certified["baseline_waste_grams"] == 3500
        assert certified["baseline_meals_served"] == 350
        assert certified["baseline_cost_cents"] == 1681

        rejection = api.reject_baseline_period(
            period["id"], factories.reject_baseline_payload(), corporate_lead_headers
        )
        validate_error(rejection, ApiErrorId.INVALID_BASELINE_STATE.value)

        resubmission = api.submit_baseline_period(period["id"], site_manager_headers(site["id"]))
        validate_error(resubmission, ApiErrorId.INVALID_BASELINE_STATE.value)
        assert fixtures.read_baseline(period["id"])["status"] == "CERTIFIED"


def _period_sitting_on_exactly_twelve_intensity():
    """3000 grams over 250 meals against a 10.000 target: one breach alert, INTERVENTION posture."""
    site, station, prep_food = _prep_bench_and_catalog(target_intensity_kg_per_1k_meals=10.000)
    spoil_food = fixtures.create_food_type(
        name="Mixed Produce Trim",
        category="PRODUCE",
        default_cost_per_kg_cents=210,
        donation_eligible=False,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=12,
    )
    shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=250)
    entries = [
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            prep_food["id"],
            weight_grams=1200,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:00:00Z",
        ),
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            prep_food["id"],
            weight_grams=1000,
            loss_reason="TRIM",
            captured_at="2026-06-10T10:05:00Z",
        ),
        fixtures.capture_entry(
            station["id"],
            shift["id"],
            spoil_food["id"],
            weight_grams=800,
            loss_reason="SPOILAGE",
            captured_at="2026-06-10T10:10:00Z",
        ),
    ]
    alerts, meta = validate_paginated(
        api_client.list_alerts(make_platform_admin_headers(), shift_id=shift["id"])
    )
    return site, shift, entries, alerts, meta


class TestVoidCascadeToCoachingPosture:
    """Voiding one capture reaches the site's posture four hops later."""

    def test_the_breach_alert_and_intervention_posture_stand_before_the_void(self):
        """An intensity of exactly 12.000 has already opened one medium breach alert.

        PRD Coverage:
        "When the period's recomputed `waste_intensity_kg_per_1k_meals` is not null and has reached 12.000 kilograms per thousand meals or more — the comparison is inclusive and is made against the already-3-decimal-rounded value, so exactly 12.000 fires it — and no coaching alert for this service period with `alert_type` `INTENSITY_BREACH` is currently in status `OPEN` or `ACKNOWLEDGED`, one alert is created with that `alert_type`."
        "`coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Difficulty/transitive_cascade/void_entry_cascades_four_hops_to_site_coaching_posture
        """
        site, shift, entries, alerts, meta = _period_sitting_on_exactly_twelve_intensity()

        before = fixtures.read_site(site["id"])
        assert before["total_captured_weight_grams"] == 3000
        assert before["valued_waste_cost_cents"] == 1576
        assert before["open_alert_count"] == 1
        assert before["coaching_posture"] == "INTERVENTION"
        assert_coaching_posture_ladder(before)

        assert meta["total_count"] == 1
        alert = alerts[0]
        assert_coaching_alert(alert)
        assert alert["status"] == "OPEN"
        assert alert["alert_type"] == "INTENSITY_BREACH"
        assert alert["severity"] == "MEDIUM"
        assert alert["observed_intensity"] == pytest.approx(12.000, abs=0.01)

    def test_the_void_recomputes_the_period_without_leaking_into_the_score(self):
        """Hops one and two: the row leaves the set and the period falls to 8.800, score still unstruck.

        PRD Coverage:
        "The void cascade proceeds in four hops, each caused by the previous one. In the first hop the capture's status becomes `VOIDED`, `void_reason` is stored, and the entry leaves every `RECORDED`-or-`FLAGGED` aggregation set."
        "In the second hop, caused by that departure, the owning service period recomputes `shift_waste_grams`, `waste_intensity_kg_per_1k_meals`, `capture_compliance_pct` and `pre_consumer_share_pct` — and, when the period has already been closed, its `leaderboard_score` as well."

        Design: Difficulty/transitive_cascade/void_entry_cascades_four_hops_to_site_coaching_posture
        """
        site, shift, entries, alerts, meta = _period_sitting_on_exactly_twelve_intensity()

        voided = fixtures.void_entry(
            entries[2]["id"], user_id="sl-1", void_reason="duplicate of the 10:05 weigh-in"
        )

        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "duplicate of the 10:05 weigh-in"
        assert voided["version"] == 2

        period = fixtures.read_shift(shift["id"])
        assert_shift(period)
        assert period["status"] == "OPEN"
        assert period["shift_waste_grams"] == 2200
        assert period["waste_intensity_kg_per_1k_meals"] == pytest.approx(8.800, abs=0.01)
        assert period["leaderboard_score"] is None

    def test_the_new_intensity_auto_resolves_the_breach_without_rewriting_history(self):
        """Hop three: the alert closes itself, but its observed figure stays at 12.000.

        PRD Coverage:
        "In the third hop, caused by the period's new intensity value, every coaching alert of that period whose `alert_type` is `INTENSITY_BREACH` and whose status is `OPEN` or `ACKNOWLEDGED` transitions to `AUTO_RESOLVED` with `resolved_at` set to the current logical clock — but only when the recomputed `waste_intensity_kg_per_1k_meals` is either null or has fallen strictly below the 12.000 coaching threshold."

        Design: Difficulty/transitive_cascade/void_entry_cascades_four_hops_to_site_coaching_posture
        """
        site, shift, entries, alerts, meta = _period_sitting_on_exactly_twelve_intensity()
        alert_id = alerts[0]["id"]

        fixtures.void_entry(entries[2]["id"], user_id="sl-1", void_reason="duplicate of the 10:05 weigh-in")

        resolved = fixtures.read_alert(alert_id)
        assert resolved["status"] == "AUTO_RESOLVED"
        assert resolved["resolved_at"].startswith(DEFAULT_CLOCK_PREFIX)
        assert_timestamp_has_three_fractional_digits(resolved["resolved_at"])
        assert resolved["observed_intensity"] == pytest.approx(12.000, abs=0.01)

    def test_the_auto_resolution_walks_the_posture_back_to_monitoring(self, api, platform_admin_headers):
        """Hop four, plus the direct money effect: 2200 grams, 1408 cents, nothing hard-deleted.

        PRD Coverage:
        "In the fourth hop, caused by those alerts leaving the open-or-acknowledged set, the site's `open_alert_count` is decremented once per auto-resolved alert and `coaching_posture` is recomputed from the new count."
        "`coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Difficulty/transitive_cascade/void_entry_cascades_four_hops_to_site_coaching_posture
        """
        site, shift, entries, alerts, meta = _period_sitting_on_exactly_twelve_intensity()

        fixtures.void_entry(entries[2]["id"], user_id="sl-1", void_reason="duplicate of the 10:05 weigh-in")

        after = fixtures.read_site(site["id"])
        assert after["open_alert_count"] == 0
        assert after["coaching_posture"] == "MONITORING"
        assert_coaching_posture_ladder(after)
        assert after["total_captured_weight_grams"] == 2200
        assert after["valued_waste_cost_cents"] == 1408

        rows, listing = validate_paginated(api.list_waste_entries(platform_admin_headers, shift_id=shift["id"]))
        assert listing["total_count"] == 3
        assert sorted(row["status"] for row in rows) == ["RECORDED", "RECORDED", "VOIDED"]


def _ticketed_july_diversion_against_a_certified_june_baseline():
    """June 3000 g certified, July 2700 g closed and ticketed, a 40.00 floor still unmet."""
    site, station, food_type = _prep_bench_and_catalog()
    hauler = fixtures.create_approved_hauler(
        name="Green Loop Compost",
        channels=["COMPOST"],
        rate_cents_per_tonne=52000,
        stop_fee_cents=1800,
        capacity_kg_per_pickup=500,
        max_concurrent_pickups=1,
    )
    june = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=1000)
    for grams, at in ((2000, "2026-06-10T10:00:00Z"), (1000, "2026-06-10T10:05:00Z")):
        fixtures.capture_entry(
            station["id"], june["id"], food_type["id"], weight_grams=grams, loss_reason="TRIM", captured_at=at
        )
    fixtures.close_shift(june["id"])
    period = fixtures.open_baseline(site["id"], start_date="2026-06-01", end_date="2026-06-30")
    fixtures.submit_baseline(site["id"], period["id"])
    fixtures.certify_baseline(period["id"])

    july = fixtures.open_shift(site["id"], shift_date="2026-07-10", shift_code="AM", meals_served=1000)
    july_entries = [
        fixtures.capture_entry(
            station["id"], july["id"], food_type["id"], weight_grams=grams, loss_reason="TRIM", captured_at=at
        )
        for grams, at in ((1500, "2026-07-10T10:00:00Z"), (1200, "2026-07-10T10:05:00Z"))
    ]
    fixtures.close_shift(july["id"])

    target = fixtures.propose_target(
        site["id"],
        period["id"],
        fixtures.read_site(site["id"])["version"],
        basis="ABSOLUTE",
        target_reduction_pct=10.00,
        min_diversion_rate_pct=40.00,
        window_start="2026-07-01",
        window_end="2026-07-31",
    )
    target = fixtures.activate_target(target["id"])

    consignment = fixtures.open_consignment(
        site["id"],
        hauler["id"],
        channel="COMPOST",
        pickup_window_start="2026-07-11T08:00:00Z",
        pickup_window_end="2026-07-11T10:00:00Z",
        container_tare_grams=0,
    )
    fixtures.add_line(site["id"], consignment["id"], july_entries[0]["id"], 1500)
    fixtures.add_line(site["id"], consignment["id"], july_entries[1]["id"], 1200)
    fixtures.stage_consignment(site["id"], consignment["id"])
    fixtures.dispatch_consignment(site["id"], consignment["id"])
    return site, hauler, consignment, target


class TestAcceptTicketCascadeToTargetAttainment:
    """Settling a haul clears a diversion floor three hops away from the money."""

    def test_the_target_activates_behind_on_the_diversion_floor_alone(self):
        """The percentage target is already met; only the unsatisfied floor holds it at BEHIND.

        PRD Coverage:
        "On success `activated_at` is stamped with the current logical clock, the full attainment evaluation runs immediately, and `version` is incremented by 1. Activation never resolves a target to `ACHIEVED` or `MISSED`, however far past its window the clock already stands — only a clock advance can do that."
        "Over captures at the target's site with status `RECORDED` or `FLAGGED` whose `captured_at` date falls inside the inclusive performance window, `performance_waste_grams` is the sum of `weight_grams`. Over the site's `CLOSED` service periods whose `shift_date` falls inside that same inclusive window, `performance_meals_served` is the sum of `meals_served`. `performance_intensity_kg_per_1k_meals` is the performance grams divided by the performance meals, rounded half up to 3 decimal places, and is null when the meals figure is 0."
        "The diversion floor reads the site's live `diversion_rate_pct`, with a null value read as 0.00, and is satisfied when that value has reached `min_diversion_rate_pct` or more. This is why accepting a weigh ticket can flip a target from `BEHIND` to `ACHIEVED_PENDING` without a single gram of waste changing."

        Design: Difficulty/transitive_cascade/accept_ticket_cascades_three_hops_to_flip_reduction_target_attainment
        """
        site, hauler, consignment, target = _ticketed_july_diversion_against_a_certified_june_baseline()

        assert_reduction_target(target)
        assert target["status"] == "ACTIVE"
        assert target["performance_waste_grams"] == 2700
        assert target["performance_meals_served"] == 1000
        assert target["performance_intensity_kg_per_1k_meals"] == pytest.approx(2.700, abs=0.01)
        assert target["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert target["effective_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert target["attainment_state"] == "BEHIND"

        site_now = fixtures.read_site(site["id"])
        assert site_now["diverted_weight_grams_settled"] == 0
        assert site_now["diversion_rate_pct"] == pytest.approx(0.00, abs=0.01)

    def test_filing_the_ticket_credits_no_diverted_grams_at_all(self):
        """The haul is priced at 1940 cents, but nothing is settled and the target stays BEHIND.

        PRD Coverage:
        "**Step three**: `base_haul_fee_cents` is `billable_tonnes` multiplied by the hauler's `rate_cents_per_tonne`, rounded half up to a whole number of cents, and then increased by the hauler's flat `stop_fee_cents`."
        "`diverted_weight_grams_settled` is the sum of `allocated_weight_grams` over the site's allocation lines whose consignment has reached `SETTLED` on the settlement dimension and has not been `CANCELLED` on the logistics dimension; `diversion_rate_pct` is the settled diverted grams divided by the total captured grams, multiplied by 100 and rounded half up to 2 decimal places, and is null whenever `total_captured_weight_grams` is 0"

        Design: Difficulty/transitive_cascade/accept_ticket_cascades_three_hops_to_flip_reduction_target_attainment
        """
        site, hauler, consignment, target = _ticketed_july_diversion_against_a_certified_june_baseline()

        ticket = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 2700, ticket_number="GLC-77", ticket_date="2026-07-11"
        )

        assert_settlement_breakdown(
            ticket,
            net_weight_grams=2700,
            billable_tonnes=0.0027,
            base_haul_fee_cents=1940,
            fuel_surcharge_pct=0.00,
            fuel_surcharge_cents=0,
            settlement_subtotal_cents=1940,
            variance_pct=0.00,
            variance_credit_cents=0,
            settlement_total_cents=1940,
        )

        unmoved = fixtures.read_target(target["id"])
        assert unmoved["attainment_state"] == "BEHIND"
        assert fixtures.read_site(site["id"])["diverted_weight_grams_settled"] == 0

    def test_acceptance_settles_the_haul_and_lifts_the_site_diversion_rate(self):
        """Hops one and two: both dimensions flip and 2700 of 5700 captured grams count as diverted.

        PRD Coverage:
        "The first hop flips both consignment dimensions in the same request: `settlement_status` advances `TICKET_SUBMITTED → SETTLED` and `logistics_status` advances `DISPATCHED → COMPLETED`."
        "The second hop is caused by that settlement flip: the consignment's lines now qualify for the settled-diversion filter, so the site's `diverted_weight_grams_settled` and `diversion_rate_pct` are recomputed."
        "`total_captured_weight_grams` is the sum of `weight_grams` over the site's captures whose status is either `RECORDED` or `FLAGGED`"

        Design: Difficulty/transitive_cascade/accept_ticket_cascades_three_hops_to_flip_reduction_target_attainment
        """
        site, hauler, consignment, target = _ticketed_july_diversion_against_a_certified_june_baseline()
        ticket = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 2700, ticket_number="GLC-77", ticket_date="2026-07-11"
        )

        fixtures.accept_ticket(site["id"], ticket["id"])

        settled = fixtures.read_consignment(consignment["id"])
        assert settled["settlement_status"] == "SETTLED"
        assert settled["logistics_status"] == "COMPLETED"

        site_now = fixtures.read_site(site["id"])
        assert site_now["diverted_weight_grams_settled"] == 2700
        assert site_now["total_captured_weight_grams"] == 5700
        assert site_now["diversion_rate_pct"] == pytest.approx(47.37, abs=0.01)

    def test_the_cleared_floor_flips_the_active_target_to_achieved_pending(self):
        """Hop three: not a gram of waste moved, yet the target now counts as attained.

        PRD Coverage:
        "The third hop is caused by the site's new diversion rate: every reduction target of that site with status `ACTIVE` re-evaluates its `attainment_state`, which can flip from `BEHIND` to `ACHIEVED_PENDING` purely because the diversion floor is now satisfied."
        "`attainment_state` then holds `ACHIEVED_PENDING` when three conditions all hold — `effective_reduction_pct` is not null, it has reached `target_reduction_pct` or more with the comparison inclusive, and the diversion floor is satisfied — and `BEHIND` in every other case."

        Design: Difficulty/transitive_cascade/accept_ticket_cascades_three_hops_to_flip_reduction_target_attainment
        """
        site, hauler, consignment, target = _ticketed_july_diversion_against_a_certified_june_baseline()
        ticket = fixtures.submit_ticket(
            hauler["id"], consignment["id"], 2700, ticket_number="GLC-77", ticket_date="2026-07-11"
        )

        fixtures.accept_ticket(site["id"], ticket["id"])

        flipped = fixtures.read_target(target["id"])
        assert flipped["attainment_state"] == "ACHIEVED_PENDING"
        assert flipped["status"] == "ACTIVE"
        assert flipped["absolute_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert flipped["performance_waste_grams"] == 2700

        view = fixtures.read_attainment(target["id"])
        assert view["attainment_state"] == "ACHIEVED_PENDING"
        assert view["effective_reduction_pct"] == pytest.approx(10.00, abs=0.01)
        assert view["site_diversion_rate_pct"] == pytest.approx(47.37, abs=0.01)


def _period_mixing_recipe_and_catalog_rows_at_twelve_intensity():
    """3000 grams over 250 meals: one recipe-attributed row, one plain row, one produce row."""
    site, station, prep_food = _prep_bench_and_catalog(target_intensity_kg_per_1k_meals=10.000)
    spoil_food = fixtures.create_food_type(
        name="Mixed Produce Trim",
        category="PRODUCE",
        default_cost_per_kg_cents=210,
        donation_eligible=False,
        animal_feed_eligible=True,
        compostable=True,
        donation_shelf_life_hours=12,
    )
    recipe = fixtures.create_published_recipe(recipe_code="BRZ-CHK", name="Braised Chicken Thigh")
    shift = fixtures.open_shift(site["id"], shift_date=CAPTURE_DAY, shift_code="AM", meals_served=250)
    recipe_entry = fixtures.capture_entry(
        station["id"],
        shift["id"],
        prep_food["id"],
        weight_grams=1200,
        loss_reason="TRIM",
        recipe_id=recipe["id"],
        captured_at="2026-06-10T10:00:00Z",
    )
    plain_entry = fixtures.capture_entry(
        station["id"],
        shift["id"],
        prep_food["id"],
        weight_grams=1000,
        loss_reason="TRIM",
        captured_at="2026-06-10T10:05:00Z",
    )
    spoil_entry = fixtures.capture_entry(
        station["id"],
        shift["id"],
        spoil_food["id"],
        weight_grams=800,
        loss_reason="SPOILAGE",
        captured_at="2026-06-10T10:10:00Z",
    )
    alerts, meta = validate_paginated(
        api_client.list_alerts(make_platform_admin_headers(), shift_id=shift["id"])
    )
    return site, shift, (recipe_entry, plain_entry, spoil_entry), alerts, meta


class TestShiftCloseCascadeAlongTheMoneyPath:
    """Closing a period revalues every row, rolls the money up and expires the open alert."""

    def test_the_provisional_money_and_the_open_alert_stand_before_the_close(self):
        """1576 cents of provisional valuation and one open breach hold while the period is OPEN.

        PRD Coverage:
        "`provisional_cost_cents` is that product taken against `catalog_cost_basis_cents`, ignoring recipe attribution entirely."
        "`coaching_posture` is derived purely from that count — `MONITORING` when the count is exactly 0, `ESCALATED` when the count is 3 or more, and `INTERVENTION` for every count in between."

        Design: Difficulty/transitive_cascade/close_shift_cascades_four_hops_along_the_money_path_and_expires_the_alert
        """
        site, shift, entries, alerts, meta = _period_mixing_recipe_and_catalog_rows_at_twelve_intensity()

        before = fixtures.read_site(site["id"])
        assert before["valued_waste_cost_cents"] == 1576
        assert before["total_captured_weight_grams"] == 3000
        assert before["open_alert_count"] == 1
        assert before["coaching_posture"] == "INTERVENTION"

        assert meta["total_count"] == 1
        assert alerts[0]["status"] == "OPEN"
        assert alerts[0]["alert_type"] == "INTENSITY_BREACH"
        assert alerts[0]["observed_intensity"] == pytest.approx(12.000, abs=0.01)

    def test_closing_revalues_every_row_on_its_own_basis(self):
        """Hops one and two: the recipe row jumps to 1235 while the catalog rows simply repeat.

        PRD Coverage:
        "Four further hops follow, and the causal chain matters. Closure recomputes the period's `shift_waste_grams`, `waste_intensity_kg_per_1k_meals`, `capture_compliance_pct` and `pre_consumer_share_pct`, then computes `leaderboard_score`, which stays null for as long as a period remains `OPEN`."
        "The final figure uses the recipe basis when the capture has one: `final_cost_cents` is the capture's kilogram weight — `weight_grams` divided by 1000, exact and unrounded — multiplied by `recipe_cost_basis_cents` and rounded half up to a whole number of cents, when `recipe_cost_basis_cents` is not null; when it is null the same multiplication is performed against `catalog_cost_basis_cents`, so a capture with no recipe attribution finishes with a final figure identical to its provisional one."
        "`valuation_delta_cents` is `final_cost_cents` minus `provisional_cost_cents`."

        Design: Difficulty/transitive_cascade/close_shift_cascades_four_hops_along_the_money_path_and_expires_the_alert
        """
        site, shift, entries, alerts, meta = _period_mixing_recipe_and_catalog_rows_at_twelve_intensity()
        recipe_entry, plain_entry, spoil_entry = entries

        closed = fixtures.close_shift(shift["id"])

        assert closed["status"] == "CLOSED"
        assert closed["closed_at"].startswith(DEFAULT_CLOCK_PREFIX)
        assert_timestamp_has_three_fractional_digits(closed["closed_at"])
        assert closed["shift_waste_grams"] == 3000
        assert closed["waste_intensity_kg_per_1k_meals"] == pytest.approx(12.000, abs=0.01)

        revalued = fixtures.read_entry(recipe_entry["id"])
        assert revalued["provisional_cost_cents"] == 768
        assert revalued["final_cost_cents"] == 1235
        assert revalued["valuation_delta_cents"] == 467
        assert revalued["effective_cost_cents"] == 1235
        assert_effective_cost_selection(revalued)

        for entry_id, expected in ((plain_entry["id"], 640), (spoil_entry["id"], 168)):
            fallen_back = fixtures.read_entry(entry_id)
            assert fallen_back["final_cost_cents"] == expected
            assert fallen_back["valuation_delta_cents"] == 0
            assert fallen_back["effective_cost_cents"] == expected

    def test_the_revalued_rows_roll_up_without_moving_a_gram(self):
        """Hop three on the money branch: 2043 cents against an unchanged 3000 grams.

        PRD Coverage:
        "The second hop is caused by the effective-cost switch: the owning site recomputes `valued_waste_cost_cents`."
        "`valued_waste_cost_cents` is the sum of `effective_cost_cents` over exactly that same set of captures"

        Design: Difficulty/transitive_cascade/close_shift_cascades_four_hops_along_the_money_path_and_expires_the_alert
        """
        site, shift, entries, alerts, meta = _period_mixing_recipe_and_catalog_rows_at_twelve_intensity()

        fixtures.close_shift(shift["id"])

        after = fixtures.read_site(site["id"])
        assert after["valued_waste_cost_cents"] == 2043
        assert after["total_captured_weight_grams"] == 3000
        assert_site_cost_ledger(after, [fixtures.read_entry(entry["id"]) for entry in entries])

    def test_the_close_expires_the_open_alert_and_repostures_the_site(self):
        """Hops three and four on the alert branch, alongside a 95.0 leaderboard figure.

        PRD Coverage:
        "The third hop is caused by the period leaving `OPEN`: every coaching alert of this period whose status is `OPEN` transitions to `EXPIRED` with `resolved_at` set to the current logical clock, while alerts already in `ACKNOWLEDGED` are deliberately left untouched — someone took ownership of those, and closing the period does not absolve them. The fourth hop is caused by each alert leaving the open-or-acknowledged set in the third: the site's `open_alert_count` is decremented once per expired alert and `coaching_posture` is recomputed."
        "The raw score is 100 minus the intensity penalty, minus the compliance penalty, plus the bonus. That raw figure is then clamped into the range from 0 to 100 inclusive — first floored at 0, then capped at 100 — and rounded half up to 1 decimal place to become `leaderboard_score`."

        Design: Difficulty/transitive_cascade/close_shift_cascades_four_hops_along_the_money_path_and_expires_the_alert
        """
        site, shift, entries, alerts, meta = _period_mixing_recipe_and_catalog_rows_at_twelve_intensity()
        alert_id = alerts[0]["id"]

        closed = fixtures.close_shift(shift["id"])

        expired = fixtures.read_alert(alert_id)
        assert expired["status"] == "EXPIRED"
        assert expired["resolved_at"].startswith(DEFAULT_CLOCK_PREFIX)
        assert_timestamp_has_three_fractional_digits(expired["resolved_at"])

        after = fixtures.read_site(site["id"])
        assert after["open_alert_count"] == 0
        assert after["coaching_posture"] == "MONITORING"
        assert_coaching_posture_ladder(after)

        assert closed["capture_compliance_pct"] == pytest.approx(1.0000, abs=0.01)
        assert closed["pre_consumer_share_pct"] == pytest.approx(1.0000, abs=0.01)
        assert closed["leaderboard_score"] == pytest.approx(95.0, abs=0.01)

    def test_a_second_close_is_refused_so_the_money_cannot_drift(self, api, shift_lead_headers):
        """The revaluation cannot be applied twice on top of itself.

        PRD Coverage:
        "The period must currently be `OPEN`; closing an already-`CLOSED` period is refused with `ERR_INVALID_SHIFT_STATE`."

        Design: Difficulty/transitive_cascade/close_shift_cascades_four_hops_along_the_money_path_and_expires_the_alert
        """
        site, shift, entries, alerts, meta = _period_mixing_recipe_and_catalog_rows_at_twelve_intensity()
        fixtures.close_shift(shift["id"])

        response = api.close_shift(shift["id"], shift_lead_headers)

        validate_error(response, ApiErrorId.INVALID_SHIFT_STATE.value)
        assert fixtures.read_site(site["id"])["valued_waste_cost_cents"] == 2043
        assert fixtures.read_shift(shift["id"])["status"] == "CLOSED"
