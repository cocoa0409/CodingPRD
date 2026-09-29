"""Action endpoints, the bulk nightly run, cross-reference links and the read rollups."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as F
from test_helpers.constants import MEAT_TWO_RUNGS
from test_helpers.test_users import (
    admin_headers,
    auditor_headers,
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    manager_headers,
)

RECORDER_USER_ID = "u-clerk-1"
VERIFIER_USER_ID = "u-mgr-1"


def test_print_and_apply_are_ordered_and_only_apply_turns_the_lift_on(api):
    """Apply-before-print is refused, printing twice is refused, and the lift arrives last.

    PRD 3.4: "A `FreshClerk` or `DepartmentManager` prints it, which requires the label to
    still be `QUEUED` -- printing a label in any other status is refused with
    `ERR_LABEL_NOT_PRINTED` and HTTP 409 [...] Printing moves `status` from `QUEUED` to
    `PRINTED`, stamps `printed_at` with the current logical clock, and bumps the label's
    `version` by one."

    PRD 3.4: "It requires the label to be `PRINTED` -- applying anything else is refused with
    `ERR_LABEL_NOT_PRINTED` [...] Application moves `status` from `PRINTED` to `APPLIED`,
    stamps `applied_at` with the current logical clock, bumps the label's `version` by one,
    and recomputes the lot's `expected_sell_through_pct` -- which now, for the first time,
    includes the 10 percent promotional lift described in 3.2. Application is the single call
    that turns that lift on."

    PRD 3.2: "Second, the promotional lift: if at least one of the lot's markdown labels has
    reached `APPLIED`, one tenth of the lot's `quantity_on_hand` -- that is, 10 percent of it
    -- is added as extra projected movement".

    4.00 forecast units at the STANDARD multiplier over 3 days remaining is 12 projected units
    of 24, so 50.00 percent; the lift adds 2.4 units for 14.4 of 24, which is 60.00 percent.

    Design: Corner/endpoints/label_apply_refuses_a_queued_label_and_only_lifts_sell_through_once_applied
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    label = F.cut_markdown(api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers())

    too_early = api.apply_markdown_label(label["id"], clerk_headers())
    validate_error(too_early, "ERR_LABEL_NOT_PRINTED", expected_status=409)

    still_queued = F.reload_label(api, label["id"])
    A.assert_fields(still_queued, status="QUEUED")
    A.assert_absent_or_none(still_queued, "applied_at")

    queued_lot = F.reload_lot(api, chain.lot["id"])
    A.assert_lot_pricing(queued_lot, 509, 0, 15.03, status="MARKED_DOWN")
    A.assert_percent(
        queued_lot["expected_sell_through_pct"], 50.0, "expected_sell_through_pct"
    )

    printed = F.print_label(api, label["id"], headers=clerk_headers())
    A.assert_fields(printed, status="PRINTED")
    A.assert_instant_equals(printed["printed_at"], "2026-08-12T00:00:00.000Z", "printed_at")

    reprint = api.print_markdown_label(label["id"], clerk_headers())
    validate_error(reprint, "ERR_LABEL_NOT_PRINTED", expected_status=409)
    assert F.reload_label(api, label["id"])["status"] == "PRINTED"

    applied = F.apply_label(api, label["id"], headers=clerk_headers())
    A.assert_fields(applied, status="APPLIED")
    A.assert_instant_equals(applied["applied_at"], "2026-08-12T00:00:00.000Z", "applied_at")

    lifted_lot = F.reload_lot(api, chain.lot["id"])
    A.assert_percent(
        lifted_lot["expected_sell_through_pct"], 60.0, "expected_sell_through_pct"
    )


def test_the_nightly_run_skips_every_row_that_does_not_qualify_in_each_phase(api):
    """Three lots, two shrink events and two pickups, and each phase touches exactly one.

    PRD 3.9: "1. Every lot whose `sell_by_at` the logical clock has reached while the lot
    still holds units has `past_date_flag` set true.  2. Every `FRESH` or `MARKED_DOWN` lot
    whose days remaining has reached a strictly deeper ladder rung than the lot currently
    holds is marked down automatically, using the calendar (`LADDER_DAYS`) reading -- one
    markdown label is cut per lot and each affected lot's `version` is incremented.  3. Every
    shrink event in `VERIFIED` whose `verified_at` is at least 24 hours behind the logical
    clock moves to `POSTED`.  4. Every pickup of this department's store whose
    `logistics_status` is `SCHEDULED` or `CONFIRMED` and whose `scheduled_window_end` the
    logical clock has passed moves to `MISSED`".

    PRD 3.9: "The run increments the department's `sweep_epoch` by exactly one and reports
    back the `department_id`, the new `sweep_epoch`, the counts `lots_flagged_past_date`,
    `lots_auto_marked_down`, `shrink_events_posted` and `pickups_missed`, and the department's
    resulting `markdown_liability_cents`, `shrink_cost_ratio_pct` and `compliance_status`."

    PRD 3.9: "The department's own stored `shrink_cost_ratio_pct` uses the same per-line
    rounding as the report but a different window: a **trailing seven days** [...] It is the
    shrink-cost total divided by the sum of cost of goods, shrink cost and donation cost,
    multiplied by 100, rounded half up to two decimal places".

    Cost of goods is lot A's 10 sold units at 420 cents plus the 3.5 percent surcharge, which
    is exactly 4,347.  Shrink cost is lot A's 3 units, 1,260 times 1.035 is 1,304.1 so 1,304,
    plus lot C's 5 withdrawn units, 2,100 times 1.035 is 2,173.5 so 2,174 -- a total of 3,478
    over a denominator of 7,825, which is 44.45 percent against a 2.50 percent budget.  Only
    lot B carries giveback: 6 units at 599 less 509 is 540 cents.

    Design: Corner/endpoints/one_sweep_touches_only_the_qualifying_rows_in_each_phase

    The ladder carries the two rungs PRD 3.1 requires ("an ordered array of between 2 and 6
    objects"), with the deeper rung parked at `days_remaining_max` -3 so that it is out of
    reach at the sweep instant and lot B's calendar reading lands on rung 0.  PRD 3.2 states
    days remaining "is an integer and may be negative", and PRD 3.1 places no bound on a
    rung's `days_remaining_max` beyond the strictly-decreasing ordering.
    """
    chain = F.build_meat_chain(
        api,
        clock="2026-08-08T06:00:00.000Z",
        rungs=[
            dict(MEAT_TWO_RUNGS[0]),
            {
                "days_remaining_max": -3,
                "discount_pct": 50,
                "requires_manager_approval": True,
            },
        ],
        ladder_name="MEAT-SWEEP-2026",
        store_overrides={
            "dock_door_codes": ["D1"],
            "donation_program_enabled": True,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 24},
    )
    partner = F.build_partner(api, accepted_department_codes=["MEAT"])
    lot_a = chain.lot
    lot_b = F.build_lot(
        api, chain.item["id"], production_date="2026-07-30", quantity_original=6
    )
    lot_c = F.build_lot(
        api, chain.item["id"], production_date="2026-07-30", quantity_original=5
    )
    A.assert_instant_equals(lot_a["sell_by_at"], "2026-08-15T00:00:00.000Z", "sell_by_at")
    A.assert_instant_equals(lot_b["sell_by_at"], "2026-08-09T00:00:00.000Z", "sell_by_at")

    F.post_sale(api, lot_a["id"], 10, register_lane_code="L07")
    pickup_p1 = F.book_pickup(
        api,
        chain.store["id"],
        partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-09T14:00:00.000Z",
        scheduled_window_end="2026-08-09T15:00:00.000Z",
        headers=manager_headers(),
    )
    pickup_p2 = F.book_pickup(
        api,
        chain.store["id"],
        partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-11T14:00:00.000Z",
        scheduled_window_end="2026-08-11T15:00:00.000Z",
        headers=manager_headers(),
    )

    shrink_s1 = F.record_shrink(
        api, lot_a["id"], 2, cause_code="DAMAGE", headers=make_clerk_headers(RECORDER_USER_ID)
    )
    F.set_clock(api, "2026-08-09T08:00:00.000Z")
    F.verify_shrink(api, shrink_s1["id"], headers=make_manager_headers(VERIFIER_USER_ID))
    shrink_s2 = F.record_shrink(
        api, lot_a["id"], 1, cause_code="DAMAGE", headers=make_clerk_headers(RECORDER_USER_ID)
    )
    F.set_clock(api, "2026-08-09T08:00:00.001Z")
    F.verify_shrink(api, shrink_s2["id"], headers=make_manager_headers(VERIFIER_USER_ID))

    F.set_clock(api, "2026-08-10T07:00:00.000Z")
    F.withdraw_lot(api, lot_c["id"], reason_note="case cooler failure", headers=manager_headers())
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    swept = validate_success(
        api.run_date_code_sweep(chain.department["id"], manager_headers()),
        expected_status=200,
    )

    A.assert_fields(
        swept,
        department_id=chain.department["id"],
        sweep_epoch=1,
        lots_flagged_past_date=1,
        lots_auto_marked_down=1,
        shrink_events_posted=1,
        pickups_missed=1,
        compliance_status="WATCH",
    )
    A.assert_money_cents(swept["markdown_liability_cents"], 540, "markdown_liability_cents")
    A.assert_percent(swept["shrink_cost_ratio_pct"], 44.45, "shrink_cost_ratio_pct")

    marked = F.reload_lot(api, lot_b["id"])
    A.assert_fields(marked, past_date_flag=True)
    A.assert_lot_pricing(marked, 509, 0, 15.03, status="MARKED_DOWN")

    untouched = F.reload_lot(api, lot_a["id"])
    A.assert_fields(
        untouched, past_date_flag=False, status="FRESH", quantity_on_hand=11
    )
    A.assert_money_cents(untouched["current_price_cents"], 599, "current_price_cents")

    withdrawn = F.reload_lot(api, lot_c["id"])
    A.assert_fields(withdrawn, status="WITHDRAWN", past_date_flag=False)

    assert F.reload_shrink(api, shrink_s1["id"])["status"] == "POSTED"
    assert F.reload_shrink(api, shrink_s2["id"])["status"] == "VERIFIED"
    assert F.reload_pickup(api, pickup_p1["id"])["logistics_status"] == "MISSED"
    assert F.reload_pickup(api, pickup_p2["id"])["logistics_status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_markdown_labels(
            manager_headers(), params={"lot_id": lot_b["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "QUEUED"


def test_a_manifest_line_needs_a_real_lot_and_freezes_the_price_it_finds(api):
    """An unknown lot_id is a 404, and the accepted line pins 599 cents into itself.

    PRD 2.5: "The same catalogue serves foreign keys supplied in a request body: a `store_id`,
    `partner_id`, `markdown_ladder_id`, `department_id`, `item_id` or `lot_id` that names a row
    which does not exist produces the matching 404 code."

    PRD 3.7: "A successful pledge creates the line in `ASSIGNED`, snapshotting
    `unit_price_cents_snapshot` from the lot's `current_price_cents` **at assignment time** and
    computing `line_value_cents` as the pledged `quantity_units` multiplied by that snapshot.
    `line_credit_cents` stays 0 until the manifest is sealed. The lot moves from `FRESH` or
    `MARKED_DOWN` to `DONATION_PENDING` [...] The pickup's `assignment_count` is incremented,
    its `provisional_value_cents` is recomputed, and the lot's `version` is incremented by
    one."

    Units only move later, on completion: PRD 3.7 has "each pledged lot's `units_donated` grows
    and its `quantity_on_hand` shrinks by the line's `quantity_units`" under the completion
    cascade, so the pledge itself leaves `quantity_on_hand` at 10.

    Six units at the frozen 599 cents is 3,594 cents of line value.

    Design: Corner/endpoints/assignment_links_pickup_to_lot_and_snapshots_the_live_price
    """
    chain = F.build_produce_chain(
        api,
        store_overrides={"dock_door_codes": ["D1"], "donation_program_enabled": True},
        item_overrides={
            "upc": "000444555666",
            "description": "Blueberries 6oz",
            "base_retail_cents": 599,
            "unit_cost_cents": 300,
            "daily_forecast_units": 8.00,
        },
        lot_overrides={"production_date": "2026-08-10", "quantity_original": 10},
    )
    pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-13T14:00:00.000Z",
        scheduled_window_end="2026-08-13T15:00:00.000Z",
        headers=manager_headers(),
    )
    F.set_clock(api, "2026-08-13T00:00:00.000Z")

    dangling = api.create_donation_assignment(
        pickup["id"],
        {"lot_id": "00000000-0000-4000-8000-0000000000ff", "quantity_units": 10},
        clerk_headers(),
    )
    validate_error(dangling, "ERR_LOT_NOT_FOUND", expected_status=404)

    empty = F.reload_pickup(api, pickup["id"])
    A.assert_fields(empty, assignment_count=0)
    A.assert_money_cents(empty["provisional_value_cents"], 0, "provisional_value_cents")

    line = F.pledge_lot(api, pickup["id"], chain.lot["id"], 6)
    A.assert_fields(
        line,
        pickup_id=pickup["id"],
        lot_id=chain.lot["id"],
        status="ASSIGNED",
        quantity_units=6,
    )
    A.assert_money_cents(
        line["unit_price_cents_snapshot"], 599, "unit_price_cents_snapshot"
    )
    A.assert_money_cents(line["line_value_cents"], 3594, "line_value_cents")
    A.assert_money_cents(line["line_credit_cents"], 0, "line_credit_cents")

    linked = F.reload_pickup(api, pickup["id"])
    A.assert_fields(linked, assignment_count=1)
    A.assert_money_cents(
        linked["provisional_value_cents"], 3594, "provisional_value_cents"
    )

    reserved = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(reserved, status="DONATION_PENDING", quantity_on_hand=10)
    A.assert_lot_units_conservation(reserved)

    rows, meta = validate_paginated(
        api.list_donation_assignments(
            manager_headers(),
            params={
                "pickup_id": pickup["id"],
                "status": "ASSIGNED",
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 1
    A.assert_ids_equal(rows, [line["id"]])


def test_the_store_rollup_adds_cents_exactly_but_recomputes_its_percentages(api):
    """Two department reports add up to the cent; neither percentage is additive.

    PRD 3.9: "It evaluates the department report once per department of the store and adds the
    department totals, reporting `store_id`, the window, `department_count`, and the same nine
    money and percentage figures [...] Because each department's lines were rounded before its
    own totals were formed, and the rollup adds only those already-rounded department totals,
    **the rollup equals the sum of the department reports exactly** -- there is no second
    rounding pass and no drift."

    PRD 3.9: "Its cost-of-goods line is `units_sold` multiplied by its item's
    `unit_cost_cents`, increased by the 3.5 percent waste-handling surcharge, rounded half up
    to whole cents [...] `gross_margin_pct` is `gross_margin_cents` divided by
    `revenue_cents`, multiplied by 100, rounded half up to two decimal places".

    PRD 3.9: "it is a pure read: it writes nothing, and in particular it does **not** rewrite
    the department's stored `shrink_cost_ratio_pct`."

    MEAT sells 10 units of 599 for 5,990 with cost of goods 4,200 times 1.035 equal to 4,347
    and shrink 840 times 1.035 equal to 869.4, so 869, leaving 774 of margin at 12.92 percent.
    DELI sells 5 units of 499 for 2,495 with cost of goods 1,500 times 1.035 equal to 1,552.5,
    which rounds half up to 1,553, leaving 942 of margin at 37.76 percent.  The rollup's 1,716
    cents of margin on 8,485 of revenue is 20.22 percent, which is neither 12.92 plus 37.76
    nor their mean, and its 12.84 percent shrink ratio is not 16.66 plus 0.

    Design: Corner/endpoints/store_margin_rollup_is_the_exact_sum_of_its_department_reports
    """
    chain = F.build_meat_chain(api)
    ladder_deli = F.build_ladder(
        api,
        name="DELI-STD-2026",
        department_code="DELI",
        rungs=[
            {"days_remaining_max": 3, "discount_pct": 20, "requires_manager_approval": False},
            {"days_remaining_max": 1, "discount_pct": 55, "requires_manager_approval": True},
        ],
    )
    department_deli = F.build_department(
        api, chain.store["id"], ladder_deli["id"], code="DELI", shelf_life_days_default=6
    )
    item_deli = F.build_item(
        api,
        department_deli["id"],
        upc="000777888999",
        description="Rotisserie Chicken",
        base_retail_cents=499,
        unit_cost_cents=300,
        daily_forecast_units=6.00,
    )
    lot_deli = F.build_lot(
        api, item_deli["id"], production_date="2026-08-08", quantity_original=12
    )

    F.post_sale(api, chain.lot["id"], 10, register_lane_code="L07")
    F.post_sale(api, lot_deli["id"], 5, register_lane_code="L09")
    F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        2,
        "DAMAGE",
        recorder_headers=make_clerk_headers(RECORDER_USER_ID),
        verifier_headers=make_manager_headers(VERIFIER_USER_ID),
    )

    stored_before = F.reload_department(api, chain.department["id"])
    window = {"window_start_date": "2026-08-10", "window_end_date": "2026-08-10"}

    meat_report = validate_success(
        api.get_department_margin_report(
            chain.department["id"], manager_headers(), params=window
        ),
        expected_status=200,
    )
    A.assert_fields(meat_report, lot_count=1, department_id=chain.department["id"])
    A.assert_money_cents(meat_report["revenue_cents"], 5990, "revenue_cents")
    A.assert_money_cents(
        meat_report["markdown_giveback_cents"], 0, "markdown_giveback_cents"
    )
    A.assert_money_cents(meat_report["cogs_cents"], 4347, "cogs_cents")
    A.assert_money_cents(meat_report["shrink_cost_cents"], 869, "shrink_cost_cents")
    A.assert_money_cents(meat_report["donation_cost_cents"], 0, "donation_cost_cents")
    A.assert_money_cents(meat_report["gross_margin_cents"], 774, "gross_margin_cents")
    A.assert_percent(meat_report["gross_margin_pct"], 12.92, "gross_margin_pct")
    A.assert_percent(meat_report["shrink_cost_ratio_pct"], 16.66, "shrink_cost_ratio_pct")

    deli_report = validate_success(
        api.get_department_margin_report(
            department_deli["id"], manager_headers(), params=window
        ),
        expected_status=200,
    )
    A.assert_money_cents(deli_report["revenue_cents"], 2495, "revenue_cents")
    A.assert_money_cents(deli_report["cogs_cents"], 1553, "cogs_cents")
    A.assert_money_cents(deli_report["shrink_cost_cents"], 0, "shrink_cost_cents")
    A.assert_money_cents(deli_report["gross_margin_cents"], 942, "gross_margin_cents")
    A.assert_percent(deli_report["gross_margin_pct"], 37.76, "gross_margin_pct")
    A.assert_percent(deli_report["shrink_cost_ratio_pct"], 0.0, "shrink_cost_ratio_pct")

    rollup = validate_success(
        api.get_store_margin_rollup(chain.store["id"], admin_headers(), params=window),
        expected_status=200,
    )
    A.assert_fields(rollup, department_count=2, store_id=chain.store["id"])
    A.assert_money_cents(rollup["revenue_cents"], 8485, "revenue_cents")
    A.assert_money_cents(rollup["cogs_cents"], 5900, "cogs_cents")
    A.assert_money_cents(rollup["shrink_cost_cents"], 869, "shrink_cost_cents")
    A.assert_money_cents(rollup["donation_cost_cents"], 0, "donation_cost_cents")
    A.assert_money_cents(rollup["gross_margin_cents"], 1716, "gross_margin_cents")
    A.assert_percent(rollup["gross_margin_pct"], 20.22, "gross_margin_pct")
    A.assert_percent(rollup["shrink_cost_ratio_pct"], 12.84, "shrink_cost_ratio_pct")

    for money in ("revenue_cents", "cogs_cents", "shrink_cost_cents", "gross_margin_cents"):
        assert rollup[money] == meat_report[money] + deli_report[money], (
            f"{money} must be the exact sum of the two department reports"
        )

    stored_after = F.reload_department(api, chain.department["id"])
    A.assert_unchanged(
        stored_before, stored_after, "shrink_cost_ratio_pct", "version", "compliance_status"
    )


def test_a_waiver_is_open_only_to_the_finding_that_scored_at_multiplier_one(api):
    """The 26-hour finding cannot be waived; the 2-hour one can, and neither path is the other.

    PRD 3.8: "A waiver is only permitted when the finding scored at `severity_multiplier` 1 --
    that is, when `hours_past_date` fell at or inside the department's
    `past_date_tolerance_hours`. A finding whose multiplier is 3 or 6 cannot be waived, and
    the attempt is refused with `ERR_WAIVER_NOT_PERMITTED` and HTTP 422. A waiver moves
    `status` from `OPEN` to `WAIVED`, leaves `remediation` at `NONE`, records
    `resolved_by_user_id`, increments the finding's `version` by one, **leaves the lot on the
    shelf entirely untouched** -- no withdrawal, no shrink event, no price change, no unit
    movement -- decrements the department's `open_finding_count`".

    PRD 3.8: "first the finding itself takes `remediation` `WITHDRAWN`, records
    `resolved_by_user_id` from the acting `X-User-ID`, moves `status` from `OPEN` to
    `RESOLVED` [...] Second, **because** the finding resolved with a withdrawal, the lot
    transitions to `WITHDRAWN`".

    PRD 3.8: "Once the audit has been swept and every one of its findings has reached
    `RESOLVED` or `WAIVED`, the audit's `disposition_status` moves to `REMEDIATED` -- from
    `PENDING` or from `ESCALATED` alike -- and its `version` is incremented by one."

    PRD 2.3: "List results are ordered by `created_at` ascending, oldest first".

    Lot X is 2 hours past date inside the 4-hour tolerance, so 4 units at multiplier 1 is 4
    points; lot Y is 26 hours past, so 3 units at multiplier 3 is 9 points; 13 points in total
    is `MAJOR`.  The withdrawal of lot Y's 3 units costs 1,260 times 1.035, that is 1,304
    cents, against no cost of goods at all, so the trailing ratio is 100.00 percent and the
    posture stays `WATCH` even after the audit remediates.

    Design: Corner/endpoints/waiver_is_permitted_only_on_a_multiplier_one_finding
    """
    chain = F.build_meat_chain(
        api,
        clock="2026-08-08T06:00:00.000Z",
        lot_overrides={"production_date": "2026-07-30", "quantity_original": 4},
    )
    lot_x = chain.lot
    lot_y = F.build_lot(
        api, chain.item["id"], production_date="2026-07-29", quantity_original=3
    )
    A.assert_fields(chain.department, past_date_tolerance_hours=4)
    A.assert_instant_equals(lot_x["sell_by_at"], "2026-08-09T00:00:00.000Z", "sell_by_at")
    A.assert_instant_equals(lot_y["sell_by_at"], "2026-08-08T00:00:00.000Z", "sell_by_at")

    F.set_clock(api, "2026-08-09T02:00:00.000Z")
    audit = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-09T00:00:00.000Z",
        "2026-08-10T00:00:00.000Z",
    )
    swept = F.sweep_audit(api, audit["id"], headers=auditor_headers())
    A.assert_fields(
        swept,
        past_date_lot_count=2,
        past_date_units_total=7,
        severity_points_total=13,
        severity="MAJOR",
    )

    rows, meta = validate_paginated(
        api.list_audit_findings(
            auditor_headers(),
            params={"audit_id": audit["id"], "status": "OPEN", "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    finding_x, finding_y = rows
    A.assert_fields(
        finding_x,
        lot_id=lot_x["id"],
        hours_past_date=2,
        severity_multiplier=1,
        severity_points=4,
    )
    A.assert_fields(
        finding_y,
        lot_id=lot_y["id"],
        hours_past_date=26,
        severity_multiplier=3,
        severity_points=9,
    )

    refused = api.remediate_audit_finding(
        finding_y["id"],
        {"waive": True, "resolution_note": "aged out overnight"},
        auditor_headers(),
    )
    validate_error(refused, "ERR_WAIVER_NOT_PERMITTED", expected_status=422)
    assert F.reload_finding(api, finding_y["id"])["status"] == "OPEN"

    waived = F.remediate_finding(
        api,
        finding_x["id"],
        waive=True,
        resolution_note="inside tolerance, pulled at open",
        headers=auditor_headers(),
    )
    A.assert_fields(waived, status="WAIVED", remediation="NONE")
    assert waived["resolved_by_user_id"], "a waiver records who closed the finding"

    on_shelf = F.reload_lot(api, lot_x["id"])
    A.assert_fields(on_shelf, status="FRESH", quantity_on_hand=4, units_shrunk=0)

    resolved = F.remediate_finding(
        api,
        finding_y["id"],
        remediation="WITHDRAWN",
        resolution_note="off the shelf",
        headers=auditor_headers(),
    )
    A.assert_fields(resolved, status="RESOLVED", remediation="WITHDRAWN")

    pulled = F.reload_lot(api, lot_y["id"])
    A.assert_fields(pulled, status="WITHDRAWN", quantity_on_hand=0, units_shrunk=3)
    A.assert_lot_units_conservation(pulled)

    bubbled = F.reload_audit(api, audit["id"])
    A.assert_fields(bubbled, disposition_status="REMEDIATED", sweep_status="SWEPT")

    department = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(
        department, "WATCH", shrink_cost_ratio_pct=100.00, open_finding_count=0
    )
