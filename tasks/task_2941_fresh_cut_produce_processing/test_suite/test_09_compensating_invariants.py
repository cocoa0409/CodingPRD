"""Reversals that must land exactly on the pre-operation figures.

A void must give the load back every pound it took, in three entities at once,
and a hold-and-release round trip must restore the case partition it disturbed
without recalling the cases that had already left the plant.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_MANAGER_C,
    USER_QA_TECH_B,
    USER_QA_TECH_D,
    make_qa_technician_headers,
)

# The flume figures the standing consumption produces, and the base it reverts to.
LOADED_WEIGHTED_LB = 30000.00
LOADED_INDEX = 0.750
LOADED_TARGET_PPM = 35.0
EMPTY_WEIGHTED_LB = 0.00
EMPTY_INDEX = 0.000
EMPTY_INPUT_LB = 0.00

# Two cases ship before the second hold is opened.
SHIPPED_BEFORE_HOLD = 2
AVAILABLE_BEFORE_HOLD = c.CLOSE_CASES_PRODUCED - SHIPPED_BEFORE_HOLD


def test_voiding_the_only_consumption_reverses_all_three_derived_balances(api):
    """The load, the run and the flume all return to their pre-consumption figures.

    PRD: The void sets `status` to `VOIDED` and stamps `voided_at` from the logical clock, restores the load's `remaining_lb` to exactly its pre-consumption value, lowers the run's `input_lb` by exactly the same pounds, recomputes the wash system's `weighted_load_lb`, `organic_load_index` and `target_free_chlorine_ppm`, and increments the run's `version` by 1. No residue is left behind.
    PRD: Consumptions on runs still in `SETUP` or already `CANCELLED` are excluded, as is any consumption whose `status` is `VOIDED`.

    Design: Difficulty/compensating_invariant/consumption_void_restores_receipt_pound_balance
    """
    world = fx.build_world(api, stop_after=fx.STOP_TWO_READINGS)

    assert world.consumption["status"] == c.CONSUMPTION_ACTIVE
    assert world.consumption["consumed_lb"] == c.CONSUMED_LB
    loaded_receipt = fx.read_receipt(api, world.receipt_id)
    assert loaded_receipt["accepted_lb"] == c.RECEIPT_ACCEPTED_LB
    assert loaded_receipt["remaining_lb"] == c.RECEIPT_ACCEPTED_LB - c.CONSUMED_LB
    loaded_run = fx.read_run(api, world.run_id)
    assert loaded_run["input_lb"] == c.CONSUMED_LB
    a.assert_wash_chemistry(
        fx.read_wash_system(api, world.wash_system_id),
        weighted_load_lb=LOADED_WEIGHTED_LB,
        organic_load_index=LOADED_INDEX,
        target_free_chlorine_ppm=LOADED_TARGET_PPM,
        status=c.WASH_IN_SERVICE,
    )

    voided = fx.void_consumption(
        api, world.consumption_id, loaded_run["version"]
    )
    assert voided["status"] == c.CONSUMPTION_VOIDED
    a.assert_instant_equals(voided["voided_at"], c.CLOCK_MID_RUN, "voided_at")

    restored = fx.read_receipt(api, world.receipt_id)
    assert restored["remaining_lb"] == c.RECEIPT_ACCEPTED_LB, (
        "the balance returns to exactly the pre-consumption figure"
    )
    emptied = fx.read_run(api, world.run_id)
    assert emptied["input_lb"] == EMPTY_INPUT_LB
    a.assert_version_is(emptied, loaded_run["version"] + 1, "process run")
    a.assert_wash_chemistry(
        fx.read_wash_system(api, world.wash_system_id),
        weighted_load_lb=EMPTY_WEIGHTED_LB,
        organic_load_index=EMPTY_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_BASE,
        status=c.WASH_IN_SERVICE,
    )


def test_a_voided_run_cannot_close_yet_still_lists_its_audit_row(api):
    """The reversal leaves the run exactly as unclosable as it was before the draw.

    PRD: Then at least one consumption on the run must have `status` of `ACTIVE`, so that `input_lb` is greater than zero; a run with nothing consumed is refused with `ERR_NO_LOTS_CONSUMED` (HTTP 422).
    PRD: From that moment the voided row is invisible to every aggregate in this document: it contributes no pounds to either balance, no organic load to the flume, no temperature grade to the shelf-life calculation and no harvest date to the harvest-lag calculation — though the row itself remains readable as part of the audit trail, and the consumption listings on both the run side and the load side will still return it when the `status` filter permits.

    Design: Difficulty/compensating_invariant/consumption_void_restores_receipt_pound_balance
    """
    world = fx.build_world(api, stop_after=fx.STOP_TWO_READINGS)
    fx.void_consumption(api, world.consumption_id, world.run["version"])

    fx.set_clock(api, c.CLOCK_CLOSE)
    validate_error(
        api.close_process_run(world.run_id, f.close_payload(), LINE_OPERATOR_HEADERS),
        ApiErrorId.NO_LOTS_CONSUMED,
    )
    still_running = fx.read_run(api, world.run_id)
    assert still_running["run_status"] == c.RUN_RUNNING
    assert still_running["closed_at"] is None

    # The void is auditable rather than a deletion: the row is still listed.
    rows = a.assert_page(
        api.list_run_lot_consumptions(world.run_id, LINE_OPERATOR_HEADERS),
        expected_total=1,
    )
    assert [row["id"] for row in rows] == [world.consumption_id]
    assert rows[0]["status"] == c.CONSUMPTION_VOIDED
    assert rows[0]["consumed_lb"] == c.CONSUMED_LB


def _released_run_with_two_cases_already_shipped(api):
    """The standing run released, then two cases shipped to a customer."""
    world = fx.closed_world(api)
    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )

    for case in fx.list_cases(api, world.run_id, {"limit": SHIPPED_BEFORE_HOLD}):
        assert fx.ship_case(api, case["id"])["status"] == c.CASE_SHIPPED

    before = fx.read_run(api, world.run_id)
    a.assert_case_counters(
        before,
        available=AVAILABLE_BEFORE_HOLD,
        on_hold=0,
        shipped=SHIPPED_BEFORE_HOLD,
        destroyed=0,
    )
    return world, before


def test_a_hold_captures_what_is_still_in_the_plant_and_counts_what_escaped(api):
    """898 cases are held and the two shipped cases are recorded, not recalled.

    PRD: Every case of the run with `status` of `IN_INVENTORY` moves to `ON_HOLD`; cases already `SHIPPED` or `DESTROYED` are left alone. The hold's `cases_held_count` records how many cases just moved, and its `shipped_case_count` records how many of the run's cases had already shipped at that moment — the customer notification list size.
    PRD: Opening it moves the run's disposition to `HELD` — from `UNRESTRICTED` or, when later evidence re-implicates a run that was already cleared, from `RELEASED`, because this dimension is deliberately not monotonic.

    Design: Difficulty/compensating_invariant/hold_then_release_restores_case_disposition_counts
    """
    world, _before = _released_run_with_two_cases_already_shipped(api)

    second_hold = fx.open_hold(api, world.run_id, c.REASON_SANITATION_FAILURE)
    assert second_hold["reason"] == c.REASON_SANITATION_FAILURE
    assert second_hold["status"] == c.HOLD_HELD
    assert second_hold["cases_held_count"] == AVAILABLE_BEFORE_HOLD
    assert second_hold["shipped_case_count"] == SHIPPED_BEFORE_HOLD

    held = fx.read_run(api, world.run_id)
    assert held["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(
        held,
        available=0,
        on_hold=AVAILABLE_BEFORE_HOLD,
        shipped=SHIPPED_BEFORE_HOLD,
        destroyed=0,
    )
    a.assert_case_counters_conserved(held)


def test_the_release_restores_the_pre_hold_pair_and_not_the_pre_shipment_pair(api):
    """cases_available comes back to 898 exactly, never to the original 900.

    PRD: Finally, every case of the run with `status` of `ON_HOLD` moves back to `IN_INVENTORY`, restoring `cases_available` and `cases_on_hold` to exactly their pre-hold values, so that the pair round-trips precisely.
    PRD: The final code date is then stamped onto every case of the run that is neither `SHIPPED` nor `DESTROYED`, rewriting both `code_date` and `code_date_label`; product already in a customer's hands keeps the label it left with.

    Design: Difficulty/compensating_invariant/hold_then_release_restores_case_disposition_counts
    """
    world, _before = _released_run_with_two_cases_already_shipped(api)
    second_hold = fx.open_hold(api, world.run_id, c.REASON_SANITATION_FAILURE)

    fx.submit_sample(
        api,
        second_hold["id"],
        c.TEST_LISTERIA,
        make_qa_technician_headers(USER_QA_TECH_D),
    )
    fx.record_result(
        api, second_hold["id"], c.RESULT_NEGATIVE, resulted_by=USER_QA_TECH_D
    )
    released = fx.release_hold(api, second_hold["id"], released_by=USER_QA_MANAGER_C)
    assert released["status"] == c.HOLD_RELEASED

    after = fx.read_run(api, world.run_id)
    assert after["disposition_status"] == c.DISPOSITION_RELEASED
    a.assert_case_counters(
        after,
        available=AVAILABLE_BEFORE_HOLD,
        on_hold=0,
        shipped=SHIPPED_BEFORE_HOLD,
        destroyed=0,
    )
    a.assert_case_counters_conserved(after)
    # No plate count on the releasing hold, so the final window does not move.
    a.assert_shelf_life(
        after,
        final_days=c.FINAL_SHELF_LIFE_DAYS_LOW_APC,
        final_code_date=c.FINAL_CODE_DATE_LOW_APC,
    )

    # The re-dating pass skips the cases that already left the plant.
    shipped_cases = fx.list_cases(api, world.run_id, {"status": c.CASE_SHIPPED})
    assert len(shipped_cases) == SHIPPED_BEFORE_HOLD
    for case in shipped_cases:
        assert case["status"] == c.CASE_SHIPPED
        assert case["code_date"] == c.FINAL_CODE_DATE_LOW_APC
