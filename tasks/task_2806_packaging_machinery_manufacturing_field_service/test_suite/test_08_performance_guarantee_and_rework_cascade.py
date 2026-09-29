"""Scoring the machine against the guarantee, and what a failed run costs.

The reference rate is chosen by the basis pinned on the order, the pass test is
inclusive at the floor, and a failure drags the slot, the line ledger and the
next customer's booking along with it.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    INSPECTOR,
    PLANNER,
    ApiErrorId,
    advance_commercial,
    api_client,
    book_test,
    finalize_acceptance_test_payload,
    read_customer,
    read_line,
    read_model,
    read_order,
    read_slot,
    read_test,
    reserve_slot,
    setup_engineered_order,
    setup_fat_in_progress,
    setup_reference_data,
    start_test,
)


def _variable_product_run(guarantee_basis):
    """A FAT on the rig for a customer whose product varies by 10.00%."""
    env = setup_reference_data(customer={"product_variation_pct": 10.00}, line={})
    return setup_fat_in_progress(env, order_overrides={"guarantee_basis": guarantee_basis})


def test_nameplate_basis_scores_against_the_raw_catalog_rate_and_misses_the_floor():
    """Under the nameplate basis the customer's declared variability buys the machine
    nothing, so a good run at 552 cpm and 97.00% efficiency still misses a 90.00%
    guarantee.

    PRD: "Under the `NAMEPLATE` basis the reference rate is simply the model's
    `nameplate_rate_cpm`, so the customer's product variability is ignored entirely
    and a variable product depresses attainment."

    Design: Difficulty/dual_variant_calc/guarantee_attainment_nameplate_basis_misses_guarantee
    """
    env = _variable_product_run("NAMEPLATE")

    data = validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(552, 97.00), INSPECTOR
        )
    )

    assert data["attainment_pct"] == pytest.approx(89.24, abs=0.01)
    assert data["guarantee_met"] is False
    assert data["status"] == "FAILED"
    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "FAT_FAILED"
    assert order["fat_failure_count"] == 1


def test_the_nameplate_miss_is_the_pinned_basis_and_not_a_lower_threshold():
    """Nothing about the customer or the catalog changed: the order's pinned basis is
    the whole reason the 10.00% variation was discarded when the reference rate was
    chosen.

    PRD: "`attainment_pct` is then the measured rate divided by that reference rate,
    multiplied by `measured_efficiency_pct`, with a single half-up rounding to two
    decimal places applied once after the whole expression — there is no
    intermediate rounding of the ratio."

    Design: Difficulty/dual_variant_calc/guarantee_attainment_nameplate_basis_misses_guarantee
    """
    env = _variable_product_run("NAMEPLATE")

    validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(552, 97.00), INSPECTOR
        )
    )

    assert read_order(env["order"]["id"])["guarantee_basis"] == "NAMEPLATE"
    assert read_customer(env["customer"]["id"])["product_variation_pct"] == pytest.approx(
        10.00, abs=0.01
    )
    model = read_model(env["model"]["id"])
    assert model["nameplate_rate_cpm"] == 600
    assert read_test(env["fat"]["id"])["attainment_pct"] < model["guarantee_efficiency_pct"]


def test_product_adjusted_basis_derates_the_reference_rate_and_meets_the_floor():
    """Byte-identical run data clears the same 90.00% guarantee once the reference
    rate is derated by the declared variation — a different number, not a different
    threshold.

    PRD: "Under the `PRODUCT_ADJUSTED` basis the reference rate is the model's
    `nameplate_rate_cpm` multiplied by one minus the customer's
    `product_variation_pct` divided by one hundred, so identical run data yields a
    strictly higher attainment whenever the declared variation is above zero; the
    derated reference rate is never allowed below 1 container per minute."

    Design: Difficulty/dual_variant_calc/guarantee_attainment_product_adjusted_basis_meets_guarantee
    """
    env = _variable_product_run("PRODUCT_ADJUSTED")

    data = validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(552, 97.00), INSPECTOR
        )
    )

    assert data["attainment_pct"] == pytest.approx(99.16, abs=0.01)
    assert data["guarantee_met"] is True
    assert data["status"] == "PASSED"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "FAT_PASSED"


def test_the_passing_factory_run_completes_the_slot_and_frees_the_line():
    """The pass is not only a score: the slot leaves the committed set, handing every
    booked day back to the line.

    PRD: "When a **factory run passes**, the test moves to `PASSED`, the order's
    `fulfillment_status` moves from `IN_BUILD` to `FAT_PASSED`, the order's slot that
    was `IN_BUILD` moves to `COMPLETED`, and that line's `committed_slot_days` is
    re-derived — a completed slot leaves the committed set, freeing the days for
    other work."

    Design: Difficulty/dual_variant_calc/guarantee_attainment_product_adjusted_basis_meets_guarantee
    """
    env = _variable_product_run("PRODUCT_ADJUSTED")
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20

    validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(552, 97.00), INSPECTOR
        )
    )

    assert read_slot(env["slot"]["id"])["status"] == "COMPLETED"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 0


def test_attainment_exactly_equal_to_the_guarantee_floor_passes_the_machine():
    """600 cpm at 90.00% efficiency against a 600 cpm nameplate lands exactly on the
    90.00 floor, and the comparison is inclusive.

    PRD: "`guarantee_met` is true exactly when `attainment_pct` is at least the
    model's `guarantee_efficiency_pct`; attainment exactly equal to the floor
    passes."

    Design: Difficulty/boundary_precision_check/attainment_exactly_equal_to_guarantee_threshold_passes
    """
    env = setup_fat_in_progress(setup_reference_data(line={}))

    data = validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(600, 90.00), INSPECTOR
        )
    )

    assert data["attainment_pct"] == pytest.approx(90.00, abs=0.01)
    assert data["guarantee_met"] is True
    assert data["status"] == "PASSED"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "FAT_PASSED"
    assert read_slot(env["slot"]["id"])["status"] == "COMPLETED"


def test_attainment_one_hundredth_of_a_point_below_the_floor_fails_the_machine():
    """A single container per minute short puts attainment at 89.85, below the same
    floor, so the edge really is at 90.00 and not merely near it.

    PRD: "`guarantee_met` is true exactly when `attainment_pct` is at least the
    model's `guarantee_efficiency_pct`; attainment exactly equal to the floor
    passes."

    Design: Difficulty/boundary_precision_check/attainment_exactly_equal_to_guarantee_threshold_passes
    """
    env = setup_fat_in_progress(setup_reference_data(line={}))

    data = validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(599, 90.00), INSPECTOR
        )
    )

    assert data["attainment_pct"] == pytest.approx(89.85, abs=0.01)
    assert data["guarantee_met"] is False
    assert data["status"] == "FAILED"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "FAT_FAILED"


def _line_with_two_bookings():
    """One line carrying a started build for order A and a later reservation for a
    different customer's order B, clear of A under the 5-day changeover buffer."""
    env = setup_engineered_order(setup_reference_data(line={}))
    advance_commercial(env, "PO_RECEIVED")
    env = reserve_slot(env)
    downstream = setup_engineered_order(dict(env))
    downstream = reserve_slot(downstream, start_date="2026-08-31", requested_slot_days=10)
    validate_success(api_client.confirm_build_slot(env["slot"]["id"], PLANNER))
    validate_success(api_client.start_build_build_slot(env["slot"]["id"], PLANNER))
    env = start_test(book_test(env, "FAT"), "FAT")
    return env, downstream


def test_a_failed_factory_run_buys_the_build_another_week_of_the_line():
    """The quality event, not a scheduling call, is what lengthens the slot: seven
    rework days push the twenty-day booking out to twenty-seven.

    PRD: "Hop two: the order's `IN_BUILD` slot moves to `REWORK_HOLD`, and its
    `slot_days` and `end_date` are recomputed from the enlarged `rework_days` — the
    slot now occupies a week more of the line for each failure so far."

    Design: Difficulty/transitive_cascade/fat_failure_cascade_extends_slot_and_displaces_downstream_slot
    """
    env, _downstream = _line_with_two_bookings()
    assert read_line(env["line"]["id"])["committed_slot_days"] == 30

    data = validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(540, 95.00), INSPECTOR
        )
    )

    assert data["attainment_pct"] == pytest.approx(85.50, abs=0.01)
    assert data["guarantee_met"] is False
    order = read_order(env["order"]["id"])
    assert order["fulfillment_status"] == "FAT_FAILED"
    assert order["rework_days"] == 7
    slot = read_slot(env["slot"]["id"])
    assert slot["status"] == "REWORK_HOLD"
    assert slot["slot_days"] == 27
    assert slot["end_date"] == "2026-09-02"


def test_the_failed_run_knocks_out_the_next_customers_booking_on_the_same_line():
    """The sweep reaches a slot belonging to an entirely different order, and the
    line ledger is left holding only the reworked slot's days.

    PRD: "Hop three: that line's `committed_slot_days` is re-derived against the
    longer slot, and then a displacement sweep runs over the same line: every later
    slot whose `start_date` now falls inside the reworked slot's interval extended
    forward by the line's `changeover_buffer_days` is knocked out, moving from
    `RESERVED` or `CONFIRMED` to `DISPLACED`."

    Design: Difficulty/transitive_cascade/fat_failure_cascade_extends_slot_and_displaces_downstream_slot
    """
    env, downstream = _line_with_two_bookings()

    validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(540, 95.00), INSPECTOR
        )
    )

    assert read_slot(downstream["slot"]["id"])["status"] == "DISPLACED"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 27
    assert read_order(downstream["order"]["id"])["fulfillment_status"] == "ENGINEERED"


def test_a_reworked_build_re_enters_in_build_through_a_second_predecessor():
    """The same start-build endpoint is legal twice on one slot: the first time out of
    CONFIRMED and the second time out of REWORK_HOLD, so the fulfillment track is
    not a one-way street.

    PRD: "A `REWORK_HOLD` slot also moves to `IN_BUILD`, and this is the rework cycle
    edge: it requires the order to be in `FAT_FAILED` and cascades the order's
    `fulfillment_status` from `FAT_FAILED` back to `IN_BUILD`, again with a `version`
    increment."

    Design: Difficulty/non_linear_state_machine/machine_order_fat_failure_reenters_in_build_from_rework_hold
    """
    env = setup_fat_in_progress(setup_reference_data(line={}))
    failed = validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(540, 95.00), INSPECTOR
        )
    )
    assert failed["attainment_pct"] == pytest.approx(85.50, abs=0.01)
    assert failed["status"] == "FAILED"

    data = validate_success(api_client.start_build_build_slot(env["slot"]["id"], PLANNER))

    assert data["status"] == "IN_BUILD"
    assert read_order(env["order"]["id"])["fulfillment_status"] == "IN_BUILD"


def test_the_second_entry_into_in_build_carries_a_longer_slot_than_the_first():
    """State alone does not describe the row: the resumed build occupies twenty-seven
    days of the line where the first pass occupied twenty.

    PRD: "Hop one: the order's `fat_failure_count` increments by 1, its `rework_days`
    grows by seven days, and its `fulfillment_status` moves from `IN_BUILD` to
    `FAT_FAILED`."

    Design: Difficulty/non_linear_state_machine/machine_order_fat_failure_reenters_in_build_from_rework_hold
    """
    env = setup_fat_in_progress(setup_reference_data(line={}))
    validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(540, 95.00), INSPECTOR
        )
    )

    resumed = validate_success(api_client.start_build_build_slot(env["slot"]["id"], PLANNER))

    assert resumed["slot_days"] == 27
    assert resumed["end_date"] == "2026-09-02"
    order = read_order(env["order"]["id"])
    assert order["rework_days"] == 7
    assert order["fat_failure_count"] == 1
    assert read_line(env["line"]["id"])["committed_slot_days"] == 27


def test_a_scored_run_cannot_be_re_finalized_after_the_verdict_is_in():
    """PASSED and FAILED are terminal, so a second finalize on the failed run is
    refused and the recorded verdict stands.

    PRD: "`PASSED` and `FAILED` are the terminal test states."

    Design: Corner/errors/acceptance_test_finalize_before_start_returns_409_invalid_test_state
    """
    env = setup_fat_in_progress(setup_reference_data(line={}))
    validate_success(
        api_client.finalize_acceptance_test(
            env["fat"]["id"], finalize_acceptance_test_payload(540, 95.00), INSPECTOR
        )
    )

    response = api_client.finalize_acceptance_test(
        env["fat"]["id"], finalize_acceptance_test_payload(600, 99.00), INSPECTOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_TEST_STATE.value, 409)
    test = read_test(env["fat"]["id"])
    assert test["status"] == "FAILED"
    assert test["attainment_pct"] == pytest.approx(85.50, abs=0.01)
