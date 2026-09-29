"""Derived values: shelf life, filtered input sets, thresholds and aggregates."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories
from test_helpers import fixtures as F
from test_helpers.test_users import (
    auditor_headers,
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    manager_headers,
)

RECORDER_USER_ID = "u-clerk-1"
VERIFIER_USER_ID = "u-mgr-1"
APPROVER_USER_ID = "u-mgr-2"


def test_the_item_shelf_life_wins_over_the_department_default_lot_by_lot(api):
    """Two lots packed the same day diverge by which shelf life their item declares.

    PRD 3.2: "The effective shelf life is the item's own `shelf_life_days` when that value
    is present, and the owning department's `shelf_life_days_default` when the item's value
    is null. The sell-by instant is then midnight UTC at the start of the
    `production_date`, advanced by that many days, each day counted as 86,400 seconds".

    PRD 3.2: "**Days remaining** is the quantity every date-code rule turns on. It is the
    number of whole days between the logical clock and the lot's `sell_by_at`, obtained by
    taking the difference in seconds, dividing by 86,400, and taking the floor toward
    negative infinity."

    PRD 3.3: "If no rung qualifies at all -- that is, days remaining exceeds the
    `days_remaining_max` of the very first rung, which is the largest one because the array
    strictly decreases -- the request is refused with `ERR_RUNG_NOT_REACHED` and HTTP 422."

    PRD 3.3: "When no rung is satisfied at all, the quote itself is refused with
    `ERR_RUNG_NOT_REACHED`."

    The short item declares 3 days, so 2026-08-10 sells by 2026-08-13T00:00:00.000Z, which
    is 2 whole days from the 08:00 clock and inside rung 0's ceiling of 3.  The long item
    declares nothing and inherits the department's 10 days, selling by
    2026-08-20T00:00:00.000Z -- 9 whole days out, beyond every rung.

    Design: Corner/calculations/sell_by_instant_prefers_item_shelf_life_over_department_default
    """
    chain = F.build_meat_chain(
        api,
        with_lot=False,
        item_overrides={
            "upc": "000111222333",
            "description": "Ground Chuck 1lb",
            "base_retail_cents": 499,
            "unit_cost_cents": 350,
            "daily_forecast_units": 6.00,
            "shelf_life_days": 3,
        },
    )
    item_long = F.build_item(
        api,
        chain.department["id"],
        upc="000111222334",
        description="Beef Jerky Pack",
        base_retail_cents=899,
        unit_cost_cents=500,
        daily_forecast_units=2.00,
    )
    A.assert_fields(chain.item, shelf_life_days=3)
    A.assert_absent_or_none(item_long, "shelf_life_days")
    F.set_clock(api, "2026-08-10T08:00:00.000Z")

    lot_short = F.build_lot(
        api, chain.item["id"], production_date="2026-08-10", quantity_original=12
    )
    lot_long = F.build_lot(
        api, item_long["id"], production_date="2026-08-10", quantity_original=12
    )

    A.assert_instant_equals(
        lot_short["sell_by_at"], "2026-08-13T00:00:00.000Z", "sell_by_at"
    )
    A.assert_instant_equals(
        lot_long["sell_by_at"], "2026-08-20T00:00:00.000Z", "sell_by_at"
    )
    for lot in (lot_short, lot_long):
        A.assert_fields(lot, past_date_flag=False, status="FRESH")

    quote = validate_success(api.get_markdown_quote(lot_short["id"], manager_headers()))
    A.assert_fields(quote, days_remaining=2, base_rung_index=0)

    unreachable = api.get_markdown_quote(lot_long["id"], manager_headers())
    validate_error(unreachable, "ERR_RUNG_NOT_REACHED", expected_status=422)


def test_sampling_shrink_is_kept_out_of_the_order_feedback_loop(api):
    """Four verified SAMPLING units move the lot but never the recommendation.

    PRD 3.9: "**Only events whose `cause_code` is `SPOILAGE`, `DAMAGE` or `THEFT` count;
    `SAMPLING` shrink is deliberately excluded**, because sampling is a merchandising cost
    the department chose to incur, not a forecasting error."

    PRD 3.9: "`received_units` is the sum of `quantity_original` across every lot of the
    item created inside the window" and "`open_units` is the sum of `quantity_on_hand`
    across the item's lots whose `status` is `FRESH` or `MARKED_DOWN`".

    PRD 3.9: "Finally `recommended_order_units` is the item's `daily_forecast_units`
    multiplied by a three-day order horizon, dampened by the shrink rate [...] with
    `open_units` subtracted, the result rounded half up to a whole number".

    PRD 3.6: "`SAMPLING` is special: it is only accepted when the lot's item has
    `sampling_allowed` set true".

    Only the 2 SPOILAGE units count against 24 received, which is 8.33 percent once
    rounded; 20.00 forecast units times 3 days times (1 - 8.33 / 100) is 55.002, less the
    18 open units, which rounds half up to 37.  An unfiltered sum of all 6 verified units
    would have produced 25.00 percent and 27 units instead.

    Design: Corner/calculations/order_feedback_input_set_excludes_sampling_shrink
    """
    chain = F.build_meat_chain(
        api,
        item_overrides={
            "upc": "000111222333",
            "description": "Ribeye Steak 12oz",
            "base_retail_cents": 599,
            "unit_cost_cents": 420,
            "daily_forecast_units": 20.00,
            "sampling_allowed": True,
        },
    )
    F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        2,
        "SPOILAGE",
        recorder_headers=make_clerk_headers(RECORDER_USER_ID),
        verifier_headers=make_manager_headers(VERIFIER_USER_ID),
    )
    F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        4,
        "SAMPLING",
        recorder_headers=make_clerk_headers(RECORDER_USER_ID),
        verifier_headers=make_manager_headers(VERIFIER_USER_ID),
    )

    recommendation = F.build_recommendation(
        api,
        F.reload_item(api, chain.item["id"]),
        "2026-08-10",
        "2026-08-10",
        method="CHRONOLOGICAL_ACTUAL",
    )

    A.assert_fields(
        recommendation,
        received_units=24,
        shrink_units=2,
        open_units=18,
        recommended_order_units=37,
        status="DRAFT",
        method="CHRONOLOGICAL_ACTUAL",
    )
    A.assert_percent(recommendation["shrink_rate_pct"], 8.33, "shrink_rate_pct")
    assert recommendation["shrink_units"] != 6, "SAMPLING units must not be counted"

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, quantity_on_hand=18, units_shrunk=6)
    A.assert_lot_units_conservation(lot)


def test_the_enforcement_boundary_is_walked_from_both_sides_by_three_scans(api):
    """24 cents over only flags, 1 cent under only flags, 26 cents over withdraws.

    PRD 3.4: "`outcome` classifies the sign: `MATCH` when the variance is exactly zero,
    `OVERCHARGE` when the variance is positive (the customer was charged more than the
    shelf price), and `UNDERCHARGE` when it is negative."

    PRD 3.4: "In every remaining case -- any `UNDERCHARGE`, and an `OVERCHARGE` smaller
    than 25 cents -- the action is `PRICE_CORRECTION`, which flags the discrepancy without
    moving product. The 25-cent boundary is inclusive: a variance of exactly 25 cents
    withdraws the lot, while 24 cents only raises a correction."

    PRD 3.5: "Sales are only accepted on a lot whose status is `FRESH` or `MARKED_DOWN`;
    posting against a `DONATION_PENDING`, `DONATED`, `WITHDRAWN` or `DEPLETED` lot is
    refused with `ERR_LOT_NOT_PRICEABLE`."

    PRD 3.4: "A scan-price check is append-only: it is written once, carries no
    `updated_at` and no `version`, and there is no endpoint that can revise or delete one."

    Design: Corner/calculations/scan_price_variance_below_and_above_the_enforcement_boundary
    """
    chain = F.build_meat_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    F.cut_and_apply_markdown(
        api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers()
    )

    def scan(scanned_price_cents):
        return validate_success(
            api.create_scan_price_check(
                chain.lot["id"],
                factories.create_scan_price_check_payload(
                    scanned_price_cents, register_lane_code="L07"
                ),
                clerk_headers(),
            ),
            expected_status=201,
        )

    just_under = scan(533)
    A.assert_fields(
        just_under,
        variance_cents=24,
        outcome="OVERCHARGE",
        enforcement_action="PRICE_CORRECTION",
    )
    intact = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(intact, status="MARKED_DOWN", quantity_on_hand=24)

    undercharge = scan(508)
    A.assert_fields(
        undercharge,
        variance_cents=-1,
        outcome="UNDERCHARGE",
        enforcement_action="PRICE_CORRECTION",
    )
    assert F.reload_lot(api, chain.lot["id"])["status"] == "MARKED_DOWN"

    over_the_line = scan(535)
    A.assert_fields(
        over_the_line,
        variance_cents=26,
        outcome="OVERCHARGE",
        enforcement_action="LOT_WITHDRAWN",
    )
    pulled = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(pulled, status="WITHDRAWN", quantity_on_hand=0, units_shrunk=24)
    A.assert_lot_units_conservation(pulled)

    refused_sale = api.post_sale(chain.lot["id"], {"quantity_units": 1}, clerk_headers())
    validate_error(refused_sale, "ERR_LOT_NOT_PRICEABLE", expected_status=409)

    rows, meta = validate_paginated(
        api.list_scan_price_checks(
            clerk_headers(), params={"lot_id": chain.lot["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 3
    A.assert_contains_ids(
        rows, [just_under["id"], undercharge["id"], over_the_line["id"]]
    )


def test_the_liability_aggregate_is_recomputed_and_drops_the_withdrawn_lot(api):
    """Two marked-down lots expose 3,060 cents; withdrawing one leaves exactly 900.

    PRD 2.9: "It is the sum, over every lot belonging to the department's items whose
    `status` is `FRESH`, `MARKED_DOWN` or `DONATION_PENDING`, of that lot's
    `quantity_on_hand` multiplied by the difference between its item's `base_retail_cents`
    and the lot's `current_price_cents`. Lots that are `DONATED`, `WITHDRAWN` or `DEPLETED`
    are excluded entirely."

    PRD 2.9: "Three department-level aggregates are **recomputed in full from current
    state** whenever a triggering operation fires, never adjusted by an incremental
    delta".

    PRD 3.5: "Because the lot now holds zero units, every label on it in `QUEUED`,
    `PRINTED` or `APPLIED` transitions to `VOIDED`, and the department's
    `markdown_liability_cents` is recomputed -- the withdrawn lot drops out of the exposure
    entirely."

    Each unit of either lot carries 599 - 509 = 90 cents of giveback exposure, so 34 units
    expose 3,060 cents and the surviving 10 units expose 900.

    Design: Corner/calculations/department_liability_sums_priceable_lots_and_drops_withdrawn_ones
    """
    chain = F.build_meat_chain(api)
    lot_b = F.build_lot(
        api, chain.item["id"], production_date="2026-08-05", quantity_original=10
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    F.cut_markdown(api, chain.lot, pricing_variant="LADDER_DAYS", headers=clerk_headers())
    F.cut_markdown(api, lot_b, pricing_variant="LADDER_DAYS", headers=clerk_headers())

    both_priced = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        both_priced["markdown_liability_cents"], 3060, "markdown_liability_cents"
    )

    withdrawn = F.withdraw_lot(
        api, chain.lot["id"], reason_note="case cooler failure", headers=manager_headers()
    )
    A.assert_fields(withdrawn, status="WITHDRAWN", quantity_on_hand=0)

    one_left = F.reload_department(api, chain.department["id"])
    A.assert_money_cents(
        one_left["markdown_liability_cents"], 900, "markdown_liability_cents"
    )

    survivor = F.reload_lot(api, lot_b["id"])
    A.assert_fields(survivor, status="MARKED_DOWN", quantity_on_hand=10)
    A.assert_money_cents(survivor["current_price_cents"], 509, "current_price_cents")


def test_the_forty_eight_hour_severity_band_is_inclusive_at_its_ceiling(api):
    """The same lot scores 72 points at 48 hours past date and 144 points at 49.

    PRD 3.8: "Each finding records `hours_past_date`, the whole hours between the lot's
    `sell_by_at` and the sweep instant, obtained by taking the difference in seconds,
    dividing by 3,600, and taking the floor; `units_on_shelf`, the lot's `quantity_on_hand`
    at sweep time; a `severity_multiplier`; and `severity_points`."

    PRD 3.8: "The multiplier bands the elapsed time against the department's own tolerance:
    it is **1** when `hours_past_date` is at or below the department's
    `past_date_tolerance_hours`, **3** when it is above that tolerance but at or below 48
    hours, and **6** when it exceeds 48 hours."

    PRD 3.8: "`severity` is banded from that total: `NONE` at exactly 0 points, `MINOR` from
    1 through 9 points, `MAJOR` from 10 through 29 points, and `CRITICAL` at 30 points or
    more."

    PRD 3.8: "the sweep moves `sweep_status` from `NOT_STARTED` to `SWEPT`, stamps
    `swept_at` with the current logical clock, **leaves `disposition_status` at `PENDING`**
    [...] sets `past_date_flag` true on every lot it wrote a finding against, increases the
    department's `open_finding_count` by the number of findings created".

    PRD 3.8: "windows that merely abut are accepted." -- the second audit starts at exactly
    the instant the first one ends, so the two half-open windows do not overlap.

    Design: Corner/calculations/severity_multiplier_tier_boundary_at_fortyeight_hours_past_date
    """
    chain = F.build_meat_chain(api)
    A.assert_fields(chain.department, past_date_tolerance_hours=4)
    A.assert_instant_equals(
        chain.lot["sell_by_at"], "2026-08-15T00:00:00.000Z", "sell_by_at"
    )

    F.set_clock(api, "2026-08-17T00:00:00.000Z")
    audit_a = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-16T00:00:00.000Z",
        "2026-08-17T00:00:00.001Z",
    )
    swept_a = F.sweep_audit(api, audit_a["id"], headers=auditor_headers())

    A.assert_fields(
        swept_a,
        sweep_status="SWEPT",
        disposition_status="PENDING",
        past_date_lot_count=1,
        past_date_units_total=24,
        severity_points_total=72,
        severity="CRITICAL",
    )
    A.assert_instant_equals(swept_a["swept_at"], "2026-08-17T00:00:00.000Z", "swept_at")

    findings_a = F.findings_for_audit(api, audit_a["id"])
    assert len(findings_a) == 1
    A.assert_fields(
        findings_a[0],
        hours_past_date=48,
        units_on_shelf=24,
        severity_multiplier=3,
        severity_points=72,
        status="OPEN",
        remediation="NONE",
    )

    F.set_clock(api, "2026-08-17T01:00:00.000Z")
    audit_b = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-17T00:00:00.001Z",
        "2026-08-18T00:00:00.000Z",
    )
    swept_b = F.sweep_audit(api, audit_b["id"], headers=auditor_headers())

    A.assert_fields(
        swept_b, severity_points_total=144, severity="CRITICAL", past_date_lot_count=1
    )
    findings_b = F.findings_for_audit(api, audit_b["id"])
    assert len(findings_b) == 1
    A.assert_fields(
        findings_b[0], hours_past_date=49, severity_multiplier=6, severity_points=144
    )

    assert F.reload_lot(api, chain.lot["id"])["past_date_flag"] is True
    department = F.reload_department(api, chain.department["id"])
    assert department["open_finding_count"] == 2


def test_an_escalated_audit_outranks_a_still_true_watch_clause_and_gates_pricing(api):
    """Two posture clauses fire at once and the pinned order resolves to BLOCKED.

    PRD 2.8: "1. If any `ComplianceAudit` of the department has `disposition_status` equal
    to `ESCALATED`, the posture is `BLOCKED`." and "3. Otherwise, if the department's
    `shrink_cost_ratio_pct` is strictly greater than its `shrink_budget_pct`, the posture is
    `WATCH`."

    PRD 2.8: "Because the clauses are ordered, `BLOCKED` outranks `WATCH` and `WATCH`
    outranks `COMPLIANT`: an escalated audit holds the department at `BLOCKED` even when the
    shrink ratio is comfortably inside budget".

    PRD 2.8: "While a department is `BLOCKED`, four operations on that department's lots are
    refused with `ERR_DEPARTMENT_COMPLIANCE_BLOCKED` and HTTP 409: cutting a markdown,
    voiding a lot's live markdown, posting register sales, and adding a lot to a donation
    manifest."

    PRD 2.11 pins the gate ahead of the pricing checks: clause 13 is the "Department
    compliance gate on markdown creation, markdown void, sale posting and manifest-line
    creation", while clause 33 is "Manager approval supplied where the rung or override
    demands it".

    The single verified 2-unit write-off costs round-half-up of 2 * 420 * 1.035 = 869.4,
    that is 869 cents, and with nothing sold and nothing donated the denominator is the same
    869, so the ratio is exactly 100.00 percent against a 2.50 percent budget.  The sweep
    then scores the 22 units still on the shelf at multiplier 3, which is 66 points and so
    `CRITICAL`.

    Design: Corner/calculations/blocked_posture_outranks_the_watch_clause_and_stops_pricing
    """
    chain = F.build_meat_chain(api)
    F.record_and_verify_shrink(
        api,
        chain.lot["id"],
        2,
        "SPOILAGE",
        recorder_headers=make_clerk_headers(RECORDER_USER_ID),
        verifier_headers=make_manager_headers(VERIFIER_USER_ID),
    )
    watching = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(watching, "WATCH", shrink_cost_ratio_pct=100.00)

    F.set_clock(api, "2026-08-17T00:00:00.000Z")
    audit = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-16T00:00:00.000Z",
        "2026-08-18T00:00:00.000Z",
    )
    swept = F.sweep_audit(api, audit["id"], headers=auditor_headers())
    A.assert_fields(swept, severity_points_total=66, severity="CRITICAL")

    escalated = F.escalate_audit(
        api,
        audit["id"],
        escalation_note="22 units 48h past date on the case",
        headers=auditor_headers(),
    )
    A.assert_fields(escalated, disposition_status="ESCALATED", sweep_status="SWEPT")

    blocked = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(blocked, "BLOCKED", shrink_cost_ratio_pct=100.00)

    priced = F.reload_lot(api, chain.lot["id"])
    refused = api.create_markdown(
        priced["id"],
        factories.create_markdown_payload(
            priced["version"],
            pricing_variant="LADDER_DAYS",
            approval_manager_user_id=APPROVER_USER_ID,
        ),
        make_manager_headers(VERIFIER_USER_ID),
    )
    validate_error(refused, "ERR_DEPARTMENT_COMPLIANCE_BLOCKED", expected_status=409)

    untouched = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(untouched, status="FRESH", current_rung_index=-1)
    rows, meta = validate_paginated(
        api.list_markdown_labels(
            manager_headers(), params={"lot_id": priced["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, f"no label may have been cut: {rows}"


def test_reconciliation_recredits_the_picked_up_line_and_drops_the_rejected_one(api):
    """A sealed 11,980-cent manifest reconciles down to the single line that travelled.

    PRD 3.7: "It moves `manifest_status` from `SEALED` to `RECONCILED`, increments `version`
    by one, and reruns all four valuation steps with the input set narrowed to lines in
    `PICKED_UP` only -- so `provisional_value_cents`, `credit_rate_pct`, every surviving
    line's `line_credit_cents` and the pickup's `manifest_credit_cents` are all rewritten,
    and lines that ended up `REJECTED` drop out of the credit entirely."

    PRD 3.7: "`credit_rate_pct` is selected from that provisional total by tier: 62.50
    percent when the provisional value is below 50,000 cents".

    PRD 3.7: "every manifest line in `ASSIGNED` becomes `PICKED_UP`; each pledged lot's
    `units_donated` grows and its `quantity_on_hand` shrinks by the line's `quantity_units`.
    A lot whose line took its whole remaining balance [...] is drained to zero and becomes
    `DONATED`" and "sets [...] `units_picked_up_total` to the sum of `quantity_units` over
    the pickup's `PICKED_UP` lines, increments the partner's `pickups_completed_count` and
    adds those units to the partner's `units_received_total`".

    Sealing values both 10-unit lines at 599 cents each, so 11,980 provisional at the 62.50
    percent tier and two individually rounded line credits of round-half-up(5,990 * 0.625) =
    3,744, totalling 7,488.  Withdrawing the first lot rejects its line, so reconciliation
    re-runs the same four steps over the one `PICKED_UP` line and lands on 5,990 provisional,
    the same 62.50 percent tier, and 3,744 of credit.

    Design: Corner/calculations/manifest_reconcile_revalues_over_picked_up_lines_only
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

    sealed = F.seal_pickup(api, pickup["id"], headers=manager_headers())
    A.assert_fields(
        sealed,
        manifest_status="SEALED",
        provisional_value_cents=11980,
        credit_rate_pct=62.5,
        manifest_credit_cents=7488,
    )

    F.withdraw_lot(
        api, lot_p1["id"], reason_note="mould found after sealing", headers=manager_headers()
    )
    assert (
        validate_success(api.get_donation_assignment(line_1["id"], manager_headers()))[
            "status"
        ]
        == "REJECTED"
    )

    F.confirm_pickup(api, pickup["id"], chain.partner["id"])
    F.complete_pickup(api, pickup["id"], chain.partner["id"])

    reconciled = validate_success(
        api.reconcile_donation_pickup(pickup["id"], manager_headers()),
        expected_status=200,
    )
    A.assert_fields(
        reconciled,
        manifest_status="RECONCILED",
        logistics_status="COMPLETED",
        provisional_value_cents=5990,
        credit_rate_pct=62.5,
        manifest_credit_cents=3744,
        units_picked_up_total=10,
        assignment_count=1,
    )

    survivor = validate_success(
        api.get_donation_assignment(line_2["id"], manager_headers())
    )
    A.assert_fields(survivor, status="PICKED_UP", quantity_units=10)
    A.assert_money_cents(
        survivor["unit_price_cents_snapshot"], 599, "unit_price_cents_snapshot"
    )
    A.assert_money_cents(survivor["line_value_cents"], 5990, "line_value_cents")
    A.assert_money_cents(survivor["line_credit_cents"], 3744, "line_credit_cents")
    assert (
        validate_success(api.get_donation_assignment(line_1["id"], manager_headers()))[
            "status"
        ]
        == "REJECTED"
    )

    donated = F.reload_lot(api, lot_p2["id"])
    A.assert_fields(donated, status="DONATED", units_donated=10, quantity_on_hand=0)
    A.assert_lot_units_conservation(donated)
    assert F.reload_lot(api, lot_p1["id"])["status"] == "WITHDRAWN"

    partner = validate_success(
        api.get_food_bank_partner(chain.partner["id"], manager_headers())
    )
    A.assert_fields(partner, pickups_completed_count=1, units_received_total=10)
