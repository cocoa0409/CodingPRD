"""Single events whose consequences reach four and five hops away.

A grower lot recall walks loads, runs, the rework chain and cases; an
environmental confirmation walks a corrective action, a line's posture, both
axes of two runs, nine hundred cases and a grower's trailing score.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    QA_MANAGER_HEADERS,
    SANITATION_TECH_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_TECH_B,
    USER_QA_TECH_C,
    make_qa_technician_headers,
)

# The second grower lot, whose product is the only raw material the rework run
# ever draws on - so nothing but the rework edge can explain its hold.
LOT_TWO_OVERRIDES = {
    "grower_code": "GRW-300",
    "ranch_block": "B3",
    "harvest_datetime": "2026-08-01T18:00:00Z",
    "water_source": c.WATER_MUNICIPAL,
}
LOT_TWO_RECEIVED_AT = "2026-08-03T11:00:00Z"
LOT_TWO_ACCEPTED_LB = 7000.00

REWORK_PLANNED_START_AT = "2026-08-03T13:00:00Z"
REWORK_PLANNED_END_AT = "2026-08-03T16:00:00Z"
REWORK_CLOSE_AT = "2026-08-03T15:00:00Z"
REWORK_READING_PPM = 24.0
REWORK_CREW_SIZE = 5
REWORK_CONSUMED_LB = 6000.00
REWORK_CASES_PRODUCED = 180
REWORK_REQUIRED_DWELL = 132
REWORK_CODE_DATE = "2026-08-17"
RECEIPT_REMAINING_AFTER_RUN = 6000.00


def _rework_chain(api):
    """Run 1 rejected and destroyed, run 2 reworking it, released and part shipped."""
    world = fx.closed_world(api)

    lot_two = fx.approved_grower_lot(api, **LOT_TWO_OVERRIDES)
    receipt_two = fx.create_receipt(
        api,
        lot_two["id"],
        received_at=LOT_TWO_RECEIVED_AT,
        pulp_temp_c=3.0,
        gross_weight_lb=8000.00,
        tare_weight_lb=500.00,
    )
    receipt_two = fx.disposition_receipt(
        api, receipt_two["id"], c.DECISION_ACCEPT, trim_loss_lb=500.00
    )
    assert receipt_two["accepted_lb"] == LOT_TWO_ACCEPTED_LB

    # Run 1's own hold comes back positive, so its product is destroyed.
    fx.submit_sample(
        api, world.hold_id, c.TEST_LISTERIA, make_qa_technician_headers(USER_QA_TECH_B)
    )
    fx.record_result(api, world.hold_id, c.RESULT_POSITIVE, resulted_by=USER_QA_TECH_B)
    fx.reject_hold(api, world.hold_id, rejected_by=USER_QA_MANAGER_A)

    run_two = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=REWORK_PLANNED_START_AT,
        planned_end_at=REWORK_PLANNED_END_AT,
        crew_size=REWORK_CREW_SIZE,
        rework_source_run_id=world.run_id,
    )
    fx.set_clock(api, REWORK_PLANNED_START_AT)
    fx.create_reading(
        api,
        world.wash_system_id,
        REWORK_PLANNED_START_AT,
        REWORK_READING_PPM,
        headers=SANITATION_TECH_HEADERS,
        turbidity_ntu=1.8,
    )
    run_two = fx.start_run(api, run_two["id"])
    assert run_two["required_dwell_seconds_at_start"] == REWORK_REQUIRED_DWELL
    fx.consume(
        api,
        run_two["id"],
        receipt_two["id"],
        run_two["version"],
        consumed_lb=REWORK_CONSUMED_LB,
    )
    fx.set_clock(api, REWORK_CLOSE_AT)
    run_two = fx.close_run(
        api,
        run_two["id"],
        actual_dwell_seconds=140,
        spin_seconds=30,
        water_gal_used=REWORK_CONSUMED_LB,
        cases_produced=REWORK_CASES_PRODUCED,
    )
    assert run_two["yield_pct"] == c.BASE_YIELD_PCT

    hold_two = fx.list_holds(api, run_two["id"])[0]
    fx.clear_hold(
        api,
        hold_two["id"],
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )

    first_case = fx.list_cases(api, run_two["id"], {"limit": c.MIN_LIMIT})[0]
    assert first_case["code_date"] == REWORK_CODE_DATE
    shipped = fx.ship_case(api, first_case["id"])
    assert shipped["status"] == c.CASE_SHIPPED

    return world, lot_two, receipt_two, run_two


def test_a_recall_walks_the_rework_edge_to_a_run_that_never_touched_the_lot(api):
    """The sweep skips the rejected run, then descends from it to its rework.

    PRD: The recall first drives the lot to `RECALLED` and stamps `recalled_at` from the logical clock.
    PRD: Caused by that, every load whose `grower_lot_id` names the lot and whose `status` is `PENDING_INSPECTION` or `ACCEPTED` moves to `QUARANTINED`, processed in `received_at` ascending order with `created_at` ascending as the tie-break.
    PRD: Starting from **every** run that holds an `ACTIVE` consumption of a load quarantined in this recall — including the runs the previous hop skipped because their `disposition_status` was already `REJECTED`, which are precisely the runs a later rework run is allowed to name — the system walks downward along `rework_source_run_id` edges to a maximum depth of five hops.
    PRD: Every descendant reached whose `disposition_status` is not already `REJECTED` moves to `HELD` with its own hold record carrying `reason` of `RECALL`, and its cases follow the same `ON_HOLD` treatment.

    Design: Difficulty/transitive_cascade/grower_lot_recall_cascades_to_cases_and_rework_runs
    """
    world, _lot_two, _receipt_two, run_two = _rework_chain(api)

    recalled = get_success_data(
        api.recall_grower_lot(world.grower_lot_id, QA_MANAGER_HEADERS)
    )
    assert recalled["status"] == c.LOT_RECALLED
    a.assert_instant_equals(recalled["recalled_at"], REWORK_CLOSE_AT, "recalled_at")

    # Hop 2: the load is unusable, but its pound balance is not rewritten.
    quarantined = fx.read_receipt(api, world.receipt_id)
    assert quarantined["status"] == c.RECEIPT_QUARANTINED
    assert quarantined["remaining_lb"] == RECEIPT_REMAINING_AFTER_RUN

    # Hop 3 skips the rejected run: REJECTED is terminal and takes no new hold.
    run_one = fx.read_run(api, world.run_id)
    assert run_one["disposition_status"] == c.DISPOSITION_REJECTED
    a.assert_case_counters(run_one, available=0, on_hold=0, shipped=0,
                           destroyed=c.CLOSE_CASES_PRODUCED)
    assert fx.list_holds(api, world.run_id, {"reason": c.REASON_RECALL}) == []

    # Hop 5 reaches the rework run and reverts its disposition axis only.
    held = fx.read_run(api, run_two["id"])
    assert held["run_status"] == c.RUN_CLOSED
    assert held["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(held, available=0, on_hold=REWORK_CASES_PRODUCED - 1,
                           shipped=1, destroyed=0)

    recall_hold = fx.list_holds(api, run_two["id"], {"reason": c.REASON_RECALL})[0]
    assert recall_hold["reason"] == c.REASON_RECALL
    assert recall_hold["status"] == c.HOLD_HELD
    assert recall_hold["cases_held_count"] == REWORK_CASES_PRODUCED - 1
    assert recall_hold["shipped_case_count"] == 1


def test_the_recalled_lot_never_appears_in_the_held_runs_traceability(api):
    """Only the rework walk explains the hold: the lots do not overlap.

    PRD: It returns the run's own `process_run_id`, the `product_code` of the product it packed and the `customer_code` of the specification it packed to, the identifiers and grower codes of every lot that fed it as `grower_lot_ids` and `grower_codes`, the `raw_receipt_ids` of every load drawn, the `active_consumption_count` and `voided_consumption_count` of its consumption records, the `case_count` of cases it produced together with the `shipped_case_count`, `on_hold_case_count` and `destroyed_case_count` breakdown, the `effective_code_date` currently in force on the run's product, and the rework ancestry as the immediate `rework_source_run_id` plus the full chain of `rework_ancestor_run_ids`.
    PRD: A `QAManager` may also **recall** a lot that is `APPROVED` or `SUSPENDED`, which drives it to the terminal `RECALLED` state and runs the containment sweep described in §3.9.

    Design: Difficulty/transitive_cascade/grower_lot_recall_cascades_to_cases_and_rework_runs
    """
    world, lot_two, receipt_two, run_two = _rework_chain(api)

    get_success_data(api.recall_grower_lot(world.grower_lot_id, QA_MANAGER_HEADERS))

    trace = fx.read_traceability(api, run_two["id"])
    assert trace["process_run_id"] == run_two["id"]
    assert trace["rework_source_run_id"] == world.run_id
    assert world.run_id in trace["rework_ancestor_run_ids"]
    assert trace["grower_lot_ids"] == [lot_two["id"]]
    assert world.grower_lot_id not in trace["grower_lot_ids"]
    assert trace["raw_receipt_ids"] == [receipt_two["id"]]
    assert trace["shipped_case_count"] == 1
    assert trace["on_hold_case_count"] == REWORK_CASES_PRODUCED - 1
    assert trace["destroyed_case_count"] == 0
    assert trace["case_count"] == REWORK_CASES_PRODUCED
    assert trace["active_consumption_count"] == 1
    assert trace["voided_consumption_count"] == 0


# The drain swab that freezes the line, and the second run the freeze cancels.
SWAB_SITE_CODE = "L1-DRAIN-04"
SWAB_COLLECTED_AT = "2026-08-03T10:00:00Z"
NEXT_RUN_PLANNED_START_AT = "2026-08-03T13:00:00Z"
NEXT_RUN_PLANNED_END_AT = "2026-08-03T16:00:00Z"
TRAILING_AFTER_ONE_ENV_POSITIVE_RUN = 88


def _line_with_a_presumptive_drain_swab(api):
    """A released run, a planned run and a ZONE_1 swab one result short of confirmed."""
    world = fx.closed_world(api)
    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )

    released = fx.read_run(api, world.run_id)
    assert released["disposition_status"] == c.DISPOSITION_RELEASED
    a.assert_case_counters(released, available=c.CLOSE_CASES_PRODUCED, on_hold=0,
                           shipped=0, destroyed=0)
    a.assert_shelf_life(released, final_days=c.FINAL_SHELF_LIFE_DAYS_LOW_APC)

    next_run = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        planned_start_at=NEXT_RUN_PLANNED_START_AT,
        planned_end_at=NEXT_RUN_PLANNED_END_AT,
        crew_size=5,
    )
    assert next_run["run_status"] == c.RUN_SETUP
    assert next_run["disposition_status"] == c.DISPOSITION_UNRESTRICTED

    swab = fx.create_swab(
        api,
        world.line_id,
        zone=c.ZONE_1,
        site_code=SWAB_SITE_CODE,
        collected_at=SWAB_COLLECTED_AT,
    )
    assert swab["result"] == c.SWAB_RESULT_PENDING
    fx.record_swab_result(
        api,
        swab["id"],
        c.SWAB_RESULT_PRESUMPTIVE_POSITIVE,
        make_qa_technician_headers(USER_QA_TECH_C),
    )

    # The presumptive stage restricts the line and opens nothing.
    restricted = fx.read_line(api, world.line_id)
    assert restricted["posture"] == c.POSTURE_RESTRICTED
    assert restricted["open_corrective_action_count"] == 0

    return world, next_run, swab


def test_a_confirmed_zone_one_swab_freezes_the_line_and_contains_its_product(api):
    """One result cancels a planned run, re-holds a released one and marks the grower.

    PRD: First, the confirmation opens a corrective action against the swab's line with `status` of `OPEN`, `source_type` of `ENV_SWAB`, `source_ref_id` pointing at the swab, and `severity` of `CRITICAL` when the swab's `zone` is `ZONE_1` and `MAJOR` for every other zone; the line's `open_corrective_action_count` is incremented.
    PRD: Second, the line's posture is recomputed, which yields `FROZEN` for a `CRITICAL` action and `RESTRICTED` for a `MAJOR` one.
    PRD: Third — and **only** when the posture became `FROZEN` — production on the line is contained: every run on the line with `run_status` of `SETUP` moves `SETUP → CANCELLED` in `planned_start_at` ascending order, and every run on the line with `run_status` of `RUNNING`, together with every run on the line with `run_status` of `CLOSED` whose `closed_at` is at or after the swab's `collected_at` minus 24 hours, whose `disposition_status` is not already `REJECTED`, moves its disposition `UNRESTRICTED → HELD` or `RELEASED → HELD` with a new hold record whose `reason` is `ENVIRONMENTAL_POSITIVE`.
    PRD: Fourth, for every run just held, its cases with `status` of `IN_INVENTORY` move to `ON_HOLD` in `case_sequence` ascending order, the new hold's `cases_held_count` and `shipped_case_count` are recorded, the run's four case counters are recomputed, and every grower lot consumed by that run has its `env_positive_run_count` incremented and its trailing risk score recomputed — which may in turn move those lots `APPROVED → SUSPENDED`.

    Design: Difficulty/transitive_cascade/env_swab_confirmation_freezes_line_and_holds_runs
    """
    world, next_run, swab = _line_with_a_presumptive_drain_swab(api)

    confirmed = fx.record_swab_result(
        api,
        swab["id"],
        c.SWAB_RESULT_CONFIRMED_POSITIVE,
        make_qa_technician_headers(USER_QA_TECH_C),
    )
    assert confirmed["result"] == c.SWAB_RESULT_CONFIRMED_POSITIVE
    a.assert_instant_equals(confirmed["resulted_at"], c.CLOCK_CLOSE, "resulted_at")

    actions = fx.list_line_corrective_actions(api, world.line_id)
    assert len(actions) == 1
    action = actions[0]
    assert action["severity"] == c.SEVERITY_CRITICAL
    assert action["source_type"] == c.SOURCE_ENV_SWAB
    assert action["source_ref_id"] == swab["id"]
    assert action["status"] == c.CA_OPEN

    frozen = fx.read_line(api, world.line_id)
    assert frozen["posture"] == c.POSTURE_FROZEN
    assert frozen["open_corrective_action_count"] == 1

    cancelled = fx.read_run(api, next_run["id"])
    assert cancelled["run_status"] == c.RUN_CANCELLED
    assert cancelled["disposition_status"] == c.DISPOSITION_UNRESTRICTED

    reheld = fx.read_run(api, world.run_id)
    assert reheld["run_status"] == c.RUN_CLOSED
    assert reheld["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(reheld, available=0, on_hold=c.CLOSE_CASES_PRODUCED,
                           shipped=0, destroyed=0)

    env_hold = fx.list_holds(
        api, world.run_id, {"reason": c.REASON_ENVIRONMENTAL_POSITIVE}
    )[0]
    assert env_hold["cases_held_count"] == c.CLOSE_CASES_PRODUCED
    assert env_hold["shipped_case_count"] == 0

    grower_lot = fx.read_grower_lot(api, world.grower_lot_id)
    assert grower_lot["env_positive_run_count"] == 1
    a.assert_risk_scores(
        grower_lot,
        preharvest=c.RISK_START,
        trailing=TRAILING_AFTER_ONE_ENV_POSITIVE_RUN,
        status=c.LOT_APPROVED,
    )


def test_verifying_the_corrective_action_reopens_the_line_and_reverses_nothing(api):
    """The containment sweep is not self-reversing at any hop.

    PRD: An `outcome` of `PASS` moves the action `VERIFICATION_PENDING → VERIFIED`, stamps `verified_at` and `verified_by_user_id`, decrements the line's `open_corrective_action_count`, and recomputes the posture — which may move the line `FROZEN → RESTRICTED` or `FROZEN → OPEN` depending on what else is still open.
    PRD: Verifying the corrective action that froze a line does not un-cancel the runs the freeze cancelled, and it does not release the holds the freeze opened.
    PRD: Product comes off hold only through the release path described above, one hold record at a time.

    Design: Difficulty/transitive_cascade/env_swab_confirmation_freezes_line_and_holds_runs
    """
    world, next_run, swab = _line_with_a_presumptive_drain_swab(api)
    fx.record_swab_result(
        api,
        swab["id"],
        c.SWAB_RESULT_CONFIRMED_POSITIVE,
        make_qa_technician_headers(USER_QA_TECH_C),
    )
    action = fx.list_line_corrective_actions(api, world.line_id)[0]

    verified = fx.verified_corrective_action(
        api,
        action["id"],
        implemented_by=USER_QA_TECH_C,
        verified_by=USER_QA_MANAGER_A,
    )
    assert verified["status"] == c.CA_VERIFIED
    assert verified["verified_by_user_id"] == USER_QA_MANAGER_A
    a.assert_instant(verified["verified_at"], "verified_at")

    reopened = fx.read_line(api, world.line_id)
    assert reopened["posture"] == c.POSTURE_OPEN
    assert reopened["open_corrective_action_count"] == 0

    assert fx.read_run(api, next_run["id"])["run_status"] == c.RUN_CANCELLED
    still_held = fx.read_run(api, world.run_id)
    assert still_held["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(still_held, available=0, on_hold=c.CLOSE_CASES_PRODUCED,
                           shipped=0, destroyed=0)
    env_hold = fx.list_holds(
        api, world.run_id, {"reason": c.REASON_ENVIRONMENTAL_POSITIVE}
    )[0]
    assert env_hold["status"] == c.HOLD_HELD
