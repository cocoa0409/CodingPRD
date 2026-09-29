"""Initial states, valid transitions, refused transitions and terminal lockdown."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories
from test_helpers import fixtures as F
from test_helpers.constants import MEAT_TWO_RUNGS
from test_helpers.test_users import (
    admin_headers,
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    manager_headers,
)

RECORDER_USER_ID = "u-clerk-1"
DISPUTER_USER_ID = "u-mgr-1"
VERIFIER_USER_ID = "u-mgr-2"


def test_activating_a_draft_ladder_stamps_the_logical_clock_and_bumps_the_version(api):
    """Activation reads the logical clock, not host wall time, and takes version to 2.

    PRD 3.1: "An administrator activates it, which requires the ladder to still be
    `DRAFT` [...] Activation moves `status` from `DRAFT` to `ACTIVE`, stamps
    `activated_at` with the current logical clock, and bumps the ladder's `version` by
    one."

    PRD 1: "every temporal rule in this service reads a logical clock, never the host
    wall clock".

    PRD 4: "endpoints that modify, transition or read an existing resource answer with
    HTTP 200".

    Design: Corner/state_machines/ladder_activate_moves_draft_to_active_and_stamps_activated_at
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    draft = validate_success(
        api.create_markdown_ladder(
            factories.create_markdown_ladder_payload(
                name="MEAT-STD-2026", department_code="MEAT", rungs=MEAT_TWO_RUNGS
            ),
            admin_headers(),
        ),
        expected_status=201,
    )
    assert draft["status"] == "DRAFT"

    activated = validate_success(
        api.activate_markdown_ladder(draft["id"], admin_headers()), expected_status=200
    )

    A.assert_fields(activated, id=draft["id"], status="ACTIVE", version=2)
    A.assert_instant_equals(
        activated["activated_at"], "2026-08-10T08:00:00.000Z", "activated_at"
    )

    rows, meta = validate_paginated(
        api.list_markdown_ladders(admin_headers(), params={"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1
    A.assert_ids_equal(rows, [draft["id"]])


def test_applying_a_still_queued_label_is_refused_until_it_has_been_printed(api):
    """Apply demands PRINTED, and only the apply turns the promotional lift on.

    PRD 3.4: "Applying the tag is a separate act. It requires the label to be `PRINTED`
    -- applying anything else is refused with `ERR_LABEL_NOT_PRINTED`".

    PRD 3.4: "Printing moves `status` from `QUEUED` to `PRINTED`, stamps `printed_at`
    with the current logical clock, and bumps the label's `version` by one."

    PRD 3.4: "Application moves `status` from `PRINTED` to `APPLIED`, stamps `applied_at`
    with the current logical clock, bumps the label's `version` by one, and recomputes
    the lot's `expected_sell_through_pct` -- which now, for the first time, includes the
    10 percent promotional lift described in 3.2."

    One tenth of the 24 units on hand is 2.4 projected units on top of 4.00 forecast
    units times the STANDARD multiplier 1.00 times 3 days remaining, so 14.4 over 24 is
    60.00 percent.

    Design: Corner/state_machines/label_apply_while_still_queued_returns_label_not_printed
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label = F.cut_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers()
    )
    assert label["status"] == "QUEUED"

    refused = api.apply_markdown_label(label["id"], clerk_headers())
    validate_error(refused, "ERR_LABEL_NOT_PRINTED", expected_status=409)

    still_queued = F.reload_label(api, label["id"])
    assert still_queued["status"] == "QUEUED"
    A.assert_absent_or_none(still_queued, "applied_at")

    printed = validate_success(
        api.print_markdown_label(label["id"], clerk_headers()), expected_status=200
    )
    A.assert_fields(printed, status="PRINTED")
    A.assert_instant_equals(printed["printed_at"], "2026-08-12T00:00:00.000Z", "printed_at")

    applied = validate_success(
        api.apply_markdown_label(label["id"], clerk_headers()), expected_status=200
    )
    A.assert_fields(applied, status="APPLIED")
    A.assert_instant_equals(applied["applied_at"], "2026-08-12T00:00:00.000Z", "applied_at")

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_percent(lot["expected_sell_through_pct"], 60.00, "expected_sell_through_pct")


def test_one_sale_writes_revenue_giveback_and_the_department_exposure_together(api):
    """Four units at the marked-down price move six figures at once, and void nothing.

    PRD 3.5: "The sold units are subtracted from `quantity_on_hand` and added to
    `units_sold`. `revenue_cents` grows by the units sold multiplied by the lot's
    `current_price_cents` at call time. `markdown_giveback_cents` grows by the units sold
    multiplied by the difference between the item's `base_retail_cents` and the lot's
    `current_price_cents` at call time".

    PRD 3.5: "The lot's `expected_sell_through_pct` and the department's
    `markdown_liability_cents` are recomputed, and the lot's `version` is incremented by
    one."

    PRD 3.5: "When a sale takes `quantity_on_hand` to exactly 0, the lot moves from
    `FRESH` or `MARKED_DOWN` to `DEPLETED` in the same operation, and every label on it
    still in `QUEUED`, `PRINTED` or `APPLIED` transitions to `VOIDED`."  This sale leaves
    20 units, so the label is left alone.

    Four units at 509 is 2,036 cents of revenue and 4 times (599 - 509) is 360 cents of
    giveback; the 20 units still on hand carry 20 times 90 = 1,800 cents of exposure; and
    with the label still `QUEUED` there is no promotional lift, so 4.00 times 1.00 times
    3 days over 20 units is 60.00 percent.

    Design: Corner/state_machines/sale_side_effects_write_revenue_giveback_and_department_liability
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label = F.cut_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers()
    )
    before = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        before["markdown_liability_cents"], 2160, "markdown_liability_cents"
    )

    sold = F.post_sale(api, chain.lot["id"], 4, register_lane_code="L07")

    A.assert_fields(
        sold,
        quantity_on_hand=20,
        units_sold=4,
        units_shrunk=0,
        units_donated=0,
        status="MARKED_DOWN",
        version=3,
    )
    A.assert_money_cents(sold["revenue_cents"], 2036, "revenue_cents")
    A.assert_money_cents(sold["markdown_giveback_cents"], 360, "markdown_giveback_cents")
    A.assert_money_cents(sold["current_price_cents"], 509, "current_price_cents")
    A.assert_percent(sold["expected_sell_through_pct"], 60.00, "expected_sell_through_pct")
    A.assert_lot_units_conservation(sold)

    after = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        after["markdown_liability_cents"], 1800, "markdown_liability_cents"
    )
    assert F.reload_label(api, label["id"])["status"] == "QUEUED"


def test_verify_is_not_one_of_the_two_exits_a_disputed_event_has(api):
    """DISPUTED exits by resubmit or void only, so verify is a 409 and no unit moves.

    PRD 3.6: "It requires the event to be in `RECORDED`; verifying an event in any other
    status is refused with `ERR_SHRINK_NOT_VERIFIABLE` and HTTP 409."

    PRD 3.6: "Disputing a `RECORDED` event is the cheap case: `status` becomes
    `DISPUTED`, `verified_by_user_id` and `verified_at` are set to null, the event's
    `version` is incremented by one, and **no unit movement occurs at all**".

    PRD 3.6: "A disputed event has two exits, and they belong to different people. A
    `FreshClerk` -- and only a `FreshClerk` -- resubmits it [...] Alternatively a
    `DepartmentManager` voids the event for good".

    Design: Corner/state_machines/shrink_verify_from_disputed_state_is_refused
    """
    chain = F.build_meat_chain(api)
    event = F.record_shrink(
        api,
        chain.lot["id"],
        2,
        "SPOILAGE",
        note="case cooler failure",
        headers=make_clerk_headers(RECORDER_USER_ID),
    )
    disputed = F.dispute_shrink(
        api,
        event["id"],
        dispute_note="count looks wrong",
        headers=make_manager_headers(DISPUTER_USER_ID),
    )
    assert disputed["status"] == "DISPUTED"

    refused = api.verify_shrink_event(event["id"], make_manager_headers(VERIFIER_USER_ID))
    validate_error(refused, "ERR_SHRINK_NOT_VERIFIABLE", expected_status=409)

    unchanged = F.reload_shrink(api, event["id"])
    assert unchanged["status"] == "DISPUTED"
    A.assert_absent_or_none(unchanged, "verified_at", "verified_by_user_id")

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, quantity_on_hand=24, units_shrunk=0)
    A.assert_lot_units_conservation(lot)


def test_a_new_lot_and_a_new_shrink_event_land_in_their_declared_initial_states(api):
    """A lot is born FRESH at rung -1 and a clerk's write-off is born RECORDED/MANUAL.

    PRD 3.2 fixes the opening pricing state of a lot, and PRD 3.3 fixes what rung -1
    means: "`current_rung_index` becomes the label's `rung_index`" only once a markdown
    exists.

    PRD 3.6: "A newly recorded event lands in `RECORDED` with `origin` `MANUAL` and
    `recorded_by_user_id` set to the acting `X-User-ID`."

    PRD 3.6: "`unit_cost_cents_snapshot` freezes the item's `unit_cost_cents` as it
    stands [...] `cost_value_cents` is the fully loaded cost of the shrink: the units
    written off multiplied by that cost snapshot, then increased by a waste-handling
    surcharge of 3.5 percent, then rounded half up to whole cents. `retail_value_cents`
    is the units written off multiplied by the lot's `current_price_cents` at record
    time."

    PRD 3.6: "**Recording moves no units whatsoever** -- the lot's `quantity_on_hand` and
    `units_shrunk` are untouched".

    Three units at the 420-cent snapshot is 1,260 cents, and the 3.5 percent surcharge
    takes that to 1,304.1 which rounds half up to 1,304; retail is 3 times the lot's
    undiscounted 599 cents, which is 1,797.

    Design: Corner/state_machines/lot_and_shrink_event_land_in_their_declared_initial_states
    """
    chain = F.build_meat_chain(api, with_lot=False)

    lot = F.build_lot(
        api, chain.item["id"], production_date="2026-08-05", quantity_original=24
    )
    A.assert_fields(lot, status="FRESH", current_rung_index=-1)

    event = F.record_shrink(
        api, lot["id"], 3, "DAMAGE", headers=make_clerk_headers(RECORDER_USER_ID)
    )

    A.assert_fields(
        event,
        status="RECORDED",
        origin="MANUAL",
        recorded_by_user_id=RECORDER_USER_ID,
        cause_code="DAMAGE",
        quantity_units=3,
    )
    A.assert_absent_or_none(event, "verified_by_user_id", "verified_at")
    A.assert_money_cents(
        event["unit_cost_cents_snapshot"], 420, "unit_cost_cents_snapshot"
    )
    A.assert_money_cents(event["cost_value_cents"], 1304, "cost_value_cents")
    A.assert_money_cents(event["retail_value_cents"], 1797, "retail_value_cents")

    still_full = F.reload_lot(api, lot["id"])
    A.assert_fields(still_full, quantity_on_hand=24, units_shrunk=0)
    A.assert_lot_units_conservation(still_full)


def test_once_the_nightly_run_posts_a_verified_event_dispute_is_locked_out(api):
    """POSTED is terminal: the same dispute that would have worked before now 409s.

    PRD 3.9: "Every shrink event in `VERIFIED` whose `verified_at` is at least 24 hours
    behind the logical clock moves to `POSTED`." and "The run increments the department's
    `sweep_epoch` by exactly one and reports back the `department_id`, the new
    `sweep_epoch`, the counts `lots_flagged_past_date`, `lots_auto_marked_down`,
    `shrink_events_posted` and `pickups_missed`".

    PRD 3.6: "**Posting** is the system's own final step, performed by the nightly
    date-code operations run rather than by any user. [...] Posting stamps `posted_at`
    with the current logical clock, increments `version` by one, and makes the event
    permanently immutable: from `POSTED` there is no dispute, no resubmission and no
    void."

    PRD 3.6: "Nor can a `POSTED` event ever be disputed. Both refusals carry
    `ERR_SHRINK_NOT_VERIFIABLE`." and "Posted shrink continues to count in `units_shrunk`
    and in every cost report, exactly as verified shrink does."

    The clock moves from the 2026-08-10T08:00:00.000Z verification to
    2026-08-11T09:00:00.000Z, which is 25 hours later and so past the 24-hour lag.  The
    lot's sell-by is still 2026-08-15, so nothing is flagged past date, while three days
    of remaining life do reach rung 0 for the first time.

    Design: Corner/state_machines/posted_shrink_event_can_no_longer_be_disputed
    """
    chain = F.build_meat_chain(api)
    event = F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        2,
        "SPOILAGE",
        recorder_headers=make_clerk_headers(RECORDER_USER_ID),
        verifier_headers=make_manager_headers(DISPUTER_USER_ID),
    )
    assert event["status"] == "VERIFIED"

    F.set_clock(api, "2026-08-11T09:00:00.000Z")
    sweep = validate_success(
        api.run_date_code_sweep(chain.department["id"], admin_headers()),
        expected_status=200,
    )

    A.assert_fields(
        sweep,
        department_id=chain.department["id"],
        sweep_epoch=1,
        shrink_events_posted=1,
        lots_flagged_past_date=0,
        lots_auto_marked_down=1,
    )

    posted = F.reload_shrink(api, event["id"])
    assert posted["status"] == "POSTED"
    A.assert_instant_equals(posted["posted_at"], "2026-08-11T09:00:00.000Z", "posted_at")

    refused = api.dispute_shrink_event(
        event["id"],
        {"dispute_note": "too late to argue"},
        make_manager_headers(DISPUTER_USER_ID),
    )
    validate_error(refused, "ERR_SHRINK_NOT_VERIFIABLE", expected_status=409)

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, quantity_on_hand=22, units_shrunk=2)
    A.assert_lot_units_conservation(lot)
    assert F.reload_shrink(api, event["id"])["status"] == "POSTED"


def test_activating_the_same_ladder_twice_never_restamps_the_first_activation(api):
    """Activation is not idempotent, and the refusal leaves both stamps alone.

    PRD 3.1: "An administrator activates it, which requires the ladder to still be
    `DRAFT` -- activating anything else is refused with `ERR_LADDER_NOT_DRAFT`".

    PRD 2.11: "12. Audit, finding, ladder and recommendation lifecycle states on [...]
    ladder activation and ladder retirement -- [...] `ERR_LADDER_NOT_DRAFT` or
    `ERR_LADDER_NOT_ACTIVE` (409)."

    PRD 2.4: "`version`, an integer that begins at 1 when the resource is created and
    increases by exactly 1 on every successful mutation of that resource."  The second
    call is not a successful mutation, so version stays at 2.

    Design: Corner/state_machines/ladder_activate_twice_is_rejected_on_the_second_call
    """
    F.set_clock(api, "2026-08-10T08:00:00.000Z")
    ladder = F.build_ladder(api, rungs=MEAT_TWO_RUNGS)
    A.assert_fields(ladder, status="ACTIVE", version=2)
    A.assert_instant_equals(
        ladder["activated_at"], "2026-08-10T08:00:00.000Z", "activated_at"
    )

    F.set_clock(api, "2026-08-10T09:00:00.000Z")
    refused = api.activate_markdown_ladder(ladder["id"], admin_headers())
    validate_error(refused, "ERR_LADDER_NOT_DRAFT", expected_status=409)

    after = validate_success(api.get_markdown_ladder(ladder["id"], admin_headers()))
    A.assert_fields(after, status="ACTIVE", version=2)
    A.assert_instant_equals(
        after["activated_at"], "2026-08-10T08:00:00.000Z", "activated_at"
    )
    A.assert_unchanged(ladder, after, "activated_at", "version", "status")


def test_an_overcharge_of_exactly_twenty_five_cents_pulls_the_whole_lot_off_the_shelf(api):
    """A write to one append-only child drives the widest cascade in the service.

    PRD 3.4: "The 25-cent boundary is inclusive: a variance of exactly 25 cents withdraws
    the lot, while 24 cents only raises a correction. When the action is `LOT_WITHDRAWN`,
    the check drives the lot's withdrawal transition and the entire withdrawal cascade
    described in 3.5, exactly as if a manager had pulled the lot by hand."

    PRD 3.5: "A shrink event is synthesised for the lot's entire remaining balance, with
    `cause_code` `SPOILAGE`, `origin` `WITHDRAWAL_AUTO`, `quantity_units` equal to the
    lot's `quantity_on_hand`, and `status` already `VERIFIED`. [...] its
    `verified_by_user_id` is the literal string `system`".

    PRD 3.5: "Because the lot now holds zero units, every label on it in `QUEUED`,
    `PRINTED` or `APPLIED` transitions to `VOIDED`, and the department's
    `markdown_liability_cents` is recomputed" and "its `shrink_cost_ratio_pct` is
    recomputed and its `compliance_status` is recomputed from the four clauses of 2.8".

    PRD 3.5: "**`WITHDRAWN` outranks `DEPLETED`**, so a lot zeroed by a withdrawal is
    `WITHDRAWN` and never `DEPLETED`".

    All 24 units are written off at the 420-cent snapshot, so the surcharged shrink cost
    is round-half-up of 24 * 420 * 1.035 = 10,432.8, which is 10,433 cents; nothing was
    sold and nothing donated, so that figure is also the whole denominator and the ratio
    is exactly 100.00 percent -- far above the 2.50 percent budget.

    Design: Corner/state_machines/scan_price_overcharge_at_enforcement_boundary_withdraws_the_lot
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label = F.cut_and_apply_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers()
    )
    before = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(
        before,
        "COMPLIANT",
        shrink_cost_ratio_pct=0.00,
        markdown_liability_cents=2160,
    )

    check = validate_success(
        api.create_scan_price_check(
            chain.lot["id"],
            factories.create_scan_price_check_payload(534, register_lane_code="L07"),
            clerk_headers(),
        ),
        expected_status=201,
    )

    A.assert_fields(
        check,
        expected_price_cents=509,
        variance_cents=25,
        outcome="OVERCHARGE",
        enforcement_action="LOT_WITHDRAWN",
    )

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, status="WITHDRAWN", quantity_on_hand=0, units_shrunk=24)
    A.assert_lot_units_conservation(lot)
    assert F.reload_label(api, label["id"])["status"] == "VOIDED"

    rows, meta = validate_paginated(
        api.list_shrink_events(
            manager_headers(),
            params={"lot_id": chain.lot["id"], "origin": "WITHDRAWAL_AUTO"},
        )
    )
    assert meta["total_count"] == 1
    A.assert_fields(
        rows[0],
        status="VERIFIED",
        cause_code="SPOILAGE",
        quantity_units=24,
        verified_by_user_id="system",
    )

    after = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(
        after, "WATCH", shrink_cost_ratio_pct=100.00, markdown_liability_cents=0
    )


def test_cancelling_a_pickup_only_unwinds_the_line_that_is_still_assigned(api):
    """The cancel cascade is conditional on each child's state, not blanket.

    PRD 3.7: "Cancellation moves `logistics_status` to `CANCELLED`, turns every `ASSIGNED`
    line into `REJECTED`, releases the dock window so a later pickup may occupy the
    overlapping interval, recomputes `markdown_liability_cents` for every affected
    department, and increments `version` by one."

    PRD 3.7: "each affected lot unwinds out of `DONATION_PENDING` -- but **only when that
    lot has no other manifest line still in `ASSIGNED` on any pickup whose
    `logistics_status` is `SCHEDULED` or `CONFIRMED`** [...] When the lot does unwind, its
    destination is fully determined by its own pricing history: `MARKED_DOWN` when
    `current_rung_index` is 0 or greater, `FRESH` when it is -1."

    PRD 3.5: "Every donation manifest line for this lot still in `ASSIGNED` becomes
    `REJECTED`; each affected pickup's `assignment_count` is decremented and its
    `provisional_value_cents` recomputed." -- which is what the earlier withdrawal of the
    first lot already did to the first line.

    Neither lot was ever marked down, so the surviving lot returns to `FRESH` at rung -1
    rather than to `MARKED_DOWN`, while the withdrawn lot stays `WITHDRAWN` because
    `WITHDRAWN` outranks every unwind destination.

    The post-cancel values of `assignment_count` and `provisional_value_cents` are not
    asserted: PRD 3.5 names both as effects of the *withdrawal* rejection, but PRD 3.7's
    cancellation clause enumerates its own effects (status, line rejection, dock release,
    `markdown_liability_cents`, `version`) without naming either counter, so the PRD does
    not uniquely determine whether cancellation re-derives them.

    Design: Corner/state_machines/pickup_cancel_unwinds_only_the_lines_still_assigned
    """
    chain = F.build_produce_chain(
        api,
        store_overrides={
            "dock_door_codes": ["D1", "D2"],
            "donation_program_enabled": True,
        },
        item_overrides={
            "upc": "000444555666",
            "description": "Blueberries 6oz",
            "base_retail_cents": 599,
            "unit_cost_cents": 300,
            "daily_forecast_units": 8.00,
        },
        lot_overrides={"production_date": "2026-08-10", "quantity_original": 10},
    )
    lot_p1 = chain.lot
    lot_p2 = F.build_lot(
        api, chain.item["id"], production_date="2026-08-10", quantity_original=10
    )
    A.assert_instant_equals(lot_p1["sell_by_at"], "2026-08-15T00:00:00.000Z", "sell_by_at")

    F.set_clock(api, "2026-08-13T12:00:00.000Z")
    pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )
    line_1 = F.pledge_lot(api, pickup["id"], lot_p1["id"], 10)
    line_2 = F.pledge_lot(api, pickup["id"], lot_p2["id"], 10)
    assert F.reload_pickup(api, pickup["id"])["assignment_count"] == 2

    withdrawn = F.withdraw_lot(
        api, lot_p1["id"], reason_note="mould found on the pallet", headers=manager_headers()
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert (
        validate_success(api.get_donation_assignment(line_1["id"], manager_headers()))[
            "status"
        ]
        == "REJECTED"
    )
    assert F.reload_pickup(api, pickup["id"])["assignment_count"] == 1

    cancelled = validate_success(
        api.cancel_donation_pickup(
            pickup["id"], {"cancel_reason": "partner truck broke down"}, manager_headers()
        ),
        expected_status=200,
    )

    A.assert_fields(
        cancelled,
        logistics_status="CANCELLED",
        manifest_status="DRAFT",
    )

    lines = {row["id"]: row for row in F.list_assignments_for_pickup(api, pickup["id"])}
    assert lines[line_1["id"]]["status"] == "REJECTED"
    assert lines[line_2["id"]]["status"] == "REJECTED"

    stayed_withdrawn = F.reload_lot(api, lot_p1["id"])
    A.assert_fields(stayed_withdrawn, status="WITHDRAWN", quantity_on_hand=0)
    unwound = F.reload_lot(api, lot_p2["id"])
    A.assert_fields(
        unwound, status="FRESH", quantity_on_hand=10, units_donated=0, current_rung_index=-1
    )
    A.assert_lot_units_conservation(unwound)
