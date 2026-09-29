"""Four-hop cascades and the millisecond and zero-count boundaries."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import fixtures as F
from test_helpers.test_users import (
    clerk_headers,
    make_clerk_headers,
    make_manager_headers,
    manager_headers,
)

RECORDER_USER_ID = "clerk-7"
VERIFIER_USER_ID = "mgr-3"


def _build_applied_seafood_lot_with_recorded_shrink(api):
    """SEAFOOD lot marked down and APPLIED, with all six units sitting in RECORDED shrink."""
    chain = F.build_seafood_chain(api)
    F.set_clock(api, "2026-08-12T00:00:00.000Z")

    chain.label = F.cut_markdown(api, chain.lot, headers=manager_headers())
    F.print_label(api, chain.label["id"], headers=clerk_headers())
    F.apply_label(api, chain.label["id"], headers=clerk_headers())

    chain.department_before = F.reload_department(api, chain.department["id"])
    chain.shrink = F.record_shrink(
        api,
        chain.lot["id"],
        6,
        "SPOILAGE",
        note="cooler failure overnight",
        headers=make_clerk_headers(RECORDER_USER_ID),
    )
    return chain


def _labels_for_lot(api, lot_id):
    rows, _meta = validate_paginated(
        api.list_markdown_labels(clerk_headers(), params={"lot_id": lot_id, "limit": 100})
    )
    return rows


def test_verifying_one_shrink_event_moves_units_and_depletes_the_lot(api):
    """Hops one and two: units move off the shelf and the emptied lot becomes DEPLETED.

    PRD 3.6: "`cost_value_cents` is the fully loaded cost of the shrink: the units
    written off multiplied by that cost snapshot, then increased by a
    waste-handling surcharge of 3.5 percent, then rounded half up to whole cents.
    `retail_value_cents` is the units written off multiplied by the lot's
    `current_price_cents` at record time."

    PRD 3.6: "First, the lot's `units_shrunk` grows by the event's
    `quantity_units` and its `quantity_on_hand` shrinks by the same amount.
    Second, **because** `quantity_on_hand` reached zero, the lot's status becomes
    `DEPLETED`".

    Six units at an 800-cent cost snapshot is 4,800 cents, and the 3.5 percent
    waste-handling surcharge lifts that to exactly 4,968; the same six units at the
    marked-down 1,020-cent shelf price is 6,120.

    Design: Difficulty/transitive_cascade/shrink_verify_depth_four_cascade_to_department_watch
    """
    chain = _build_applied_seafood_lot_with_recorded_shrink(api)

    verified = F.verify_shrink(
        api, chain.shrink["id"], headers=make_manager_headers(VERIFIER_USER_ID)
    )

    A.assert_fields(
        verified,
        status="VERIFIED",
        cost_value_cents=4968,
        retail_value_cents=6120,
        verified_by_user_id=VERIFIER_USER_ID,
    )
    A.assert_instant_equals(
        verified["verified_at"], "2026-08-12T00:00:00.000Z", "verified_at"
    )

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, units_shrunk=6, quantity_on_hand=0, status="DEPLETED")
    A.assert_lot_units_conservation(lot)


def test_the_same_verification_voids_the_label_and_flips_the_department_to_watch(api):
    """Hops three and four: liability drains to zero and the ratio trips the budget.

    PRD 3.6: "Third, **because** the lot is no longer sellable, every label on it in
    `QUEUED`, `PRINTED` or `APPLIED` transitions to `VOIDED` and the department's
    `markdown_liability_cents` is recomputed. Fourth, **because** the department's
    shrink cost has moved, its `shrink_cost_ratio_pct` is recomputed and its
    `compliance_status` becomes `WATCH` when that ratio ends up strictly above the
    department's `shrink_budget_pct`."

    PRD 2.9: "`markdown_liability_cents` [...] is the sum, over every lot belonging
    to the department's items whose `status` is `FRESH`, `MARKED_DOWN` or
    `DONATION_PENDING`, of that lot's `quantity_on_hand` multiplied by the
    difference between its item's `base_retail_cents` and the lot's
    `current_price_cents`. Lots that are `DONATED`, `WITHDRAWN` or `DEPLETED` are
    excluded entirely."

    Before the trigger the exposure is 6 units times (1200 - 1020), which is 1,080
    cents; afterwards the lot is `DEPLETED` and drops out of the sum entirely.  The
    4,968-cent shrink cost is the whole denominator of the trailing-seven-day ratio,
    so the ratio lands on 100.00 percent -- strictly above the 0.10 percent budget.

    Design: Difficulty/transitive_cascade/shrink_verify_depth_four_cascade_to_department_watch
    """
    chain = _build_applied_seafood_lot_with_recorded_shrink(api)

    A.assert_department_posture(
        chain.department_before,
        "COMPLIANT",
        shrink_cost_ratio_pct=0,
        markdown_liability_cents=1080,
    )

    F.verify_shrink(api, chain.shrink["id"], headers=make_manager_headers(VERIFIER_USER_ID))

    label = F.reload_label(api, chain.label["id"])
    assert label["status"] == "VOIDED", f"label status expected VOIDED, got {label['status']}"
    assert [row["status"] for row in _labels_for_lot(api, chain.lot["id"])] == ["VOIDED"]

    department = F.reload_department(api, chain.department["id"])
    A.assert_department_posture(
        department,
        "WATCH",
        shrink_cost_ratio_pct=100.00,
        markdown_liability_cents=0,
    )


def _build_escalated_bakery_audit(api):
    """BAKERY lot 72 hours past date, swept to CRITICAL and escalated to BLOCKED."""
    chain = F.build_bakery_chain(
        api,
        department_overrides={
            "shelf_life_days_default": 10,
            "past_date_tolerance_hours": 4,
            "shrink_budget_pct": 2.5,
        },
    )
    F.set_clock(api, "2026-08-18T00:00:00.000Z")

    chain.audit = F.open_audit(
        api,
        chain.department["id"],
        "2026-08-17T00:00:00.000Z",
        "2026-08-20T00:00:00.000Z",
    )
    chain.swept = F.sweep_audit(api, chain.audit["id"])
    chain.findings = F.findings_for_audit(api, chain.audit["id"])
    return chain


def _shrink_events_for_lot(api, lot_id):
    rows, _meta = validate_paginated(
        api.list_shrink_events(manager_headers(), params={"lot_id": lot_id, "limit": 100})
    )
    return rows


def test_sweeping_a_72_hour_past_date_lot_escalates_the_department_to_blocked(api):
    """The severity bands lift one 20-unit lot to CRITICAL and the escalation blocks the department.

    PRD 3.8: "The multiplier bands the elapsed time against the department's own
    tolerance: it is **1** when `hours_past_date` is at or below the department's
    `past_date_tolerance_hours`, **3** when it is above that tolerance but at or
    below 48 hours, and **6** when it exceeds 48 hours. `severity_points` is
    `units_on_shelf` multiplied by that multiplier, rounded half up to a whole
    number."

    PRD 3.8: "`severity` is banded from that total: `NONE` at exactly 0 points,
    `MINOR` from 1 through 9 points, `MAJOR` from 10 through 29 points, and
    `CRITICAL` at 30 points or more."

    PRD 2.8: "If any `ComplianceAudit` of the department has `disposition_status`
    equal to `ESCALATED`, the posture is `BLOCKED`."

    The lot sells by 2026-08-15T00:00:00.000Z and the clock reads
    2026-08-18T00:00:00.000Z, exactly 72 whole hours later, so the multiplier is 6
    and 20 units on the shelf score 120 points.

    Design: Difficulty/transitive_cascade/finding_remediation_depth_four_cascade_unblocks_department
    """
    chain = _build_escalated_bakery_audit(api)

    assert len(chain.findings) == 1, f"expected exactly one finding, got {chain.findings}"
    A.assert_fields(
        chain.findings[0],
        hours_past_date=72,
        severity_multiplier=6,
        severity_points=120,
        status="OPEN",
        remediation="NONE",
    )
    A.assert_fields(
        chain.swept,
        severity_points_total=120,
        severity="CRITICAL",
        past_date_lot_count=1,
        past_date_units_total=20,
        sweep_status="SWEPT",
        disposition_status="PENDING",
    )
    assert F.reload_lot(api, chain.lot["id"])["past_date_flag"] is True

    escalated = F.escalate_audit(
        api, chain.audit["id"], escalation_note="72 hours past date on 20 units"
    )

    assert escalated["disposition_status"] == "ESCALATED"
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]), "BLOCKED", open_finding_count=1
    )


def test_remediating_the_last_finding_withdraws_the_lot_and_unblocks_the_department(api):
    """Four hops the other way: RESOLVED, WITHDRAWN, REMEDIATED, then COMPLIANT again.

    PRD 3.8: "It cascades four levels: first the finding itself takes `remediation`
    `WITHDRAWN`, records `resolved_by_user_id` from the acting `X-User-ID`, moves
    `status` from `OPEN` to `RESOLVED`, and increments its `version` by one. Second,
    **because** the finding resolved with a withdrawal, the lot transitions to
    `WITHDRAWN` and a shrink event with `cause_code` `SPOILAGE`, `origin`
    `WITHDRAWAL_AUTO` and `status` `VERIFIED` is synthesised for its remaining
    units."

    PRD 3.5: "its `verified_by_user_id` is the literal string `system` -- the
    withdrawal supplies its own verification, so the segregation-of-duties rule is
    not consulted."

    PRD 3.8: "Once the audit has been swept and every one of its findings has
    reached `RESOLVED` or `WAIVED`, the audit's `disposition_status` moves to
    `REMEDIATED` -- from `PENDING` or from `ESCALATED` alike".

    PRD 3.9: "The department's own stored `shrink_cost_ratio_pct` uses the same
    per-line rounding as the report but a different window: a **trailing seven
    days**, running from seven days before the current logical clock through the
    logical clock itself, closed at both ends, over the department's lots whose
    `created_at` falls inside that window."  The lot was received at
    2026-08-10T08:00:00.000Z, before the window opens at 2026-08-11T00:00:00.000Z,
    so its withdrawal cost never enters the ratio and the ratio stays 0.

    Design: Difficulty/transitive_cascade/finding_remediation_depth_four_cascade_unblocks_department
    """
    chain = _build_escalated_bakery_audit(api)
    F.escalate_audit(
        api, chain.audit["id"], escalation_note="72 hours past date on 20 units"
    )

    resolved = F.remediate_finding(
        api,
        chain.findings[0]["id"],
        remediation="WITHDRAWN",
        resolution_note="product pulled and destroyed",
    )

    A.assert_fields(resolved, status="RESOLVED", remediation="WITHDRAWN")

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_fields(lot, status="WITHDRAWN", quantity_on_hand=0, units_shrunk=20)
    A.assert_lot_units_conservation(lot)

    events = _shrink_events_for_lot(api, chain.lot["id"])
    assert len(events) == 1, f"expected exactly one synthesised event, got {events}"
    A.assert_fields(
        events[0],
        origin="WITHDRAWAL_AUTO",
        status="VERIFIED",
        quantity_units=20,
        cause_code="SPOILAGE",
        verified_by_user_id="system",
    )

    audit = F.reload_audit(api, chain.audit["id"])
    A.assert_fields(audit, disposition_status="REMEDIATED", sweep_status="SWEPT")
    A.assert_department_posture(
        F.reload_department(api, chain.department["id"]),
        "COMPLIANT",
        shrink_cost_ratio_pct=0,
        open_finding_count=0,
    )


def test_at_four_whole_days_remaining_no_ladder_rung_is_reachable_yet(api):
    """One millisecond too early, the quote itself is refused with ERR_RUNG_NOT_REACHED.

    PRD 3.2: "**Days remaining** [...] is the number of whole days between the
    logical clock and the lot's `sell_by_at`, obtained by taking the difference in
    seconds, dividing by 86,400, and taking the floor toward negative infinity."

    PRD 3.3: "If no rung qualifies at all -- that is, days remaining exceeds the
    `days_remaining_max` of the very first rung, which is the largest one because
    the array strictly decreases -- the request is refused with
    `ERR_RUNG_NOT_REACHED` and HTTP 422." and "When no rung is satisfied at all, the
    quote itself is refused with `ERR_RUNG_NOT_REACHED`."

    At exactly 2026-08-11T00:00:00.000Z the gap to the lot's 2026-08-15T00:00:00.000Z
    sell-by is a whole 4.000 days, so days remaining is 4 -- above the shallowest
    rung's `days_remaining_max` of 3.

    Design: Difficulty/boundary_precision_check/ladder_rung_boundary_days_remaining_three_vs_four_on_markdown_quote
    """
    chain = F.build_meat_four_rung_chain(api)
    F.set_clock(api, "2026-08-11T00:00:00.000Z")

    refused = api.get_markdown_quote(chain.lot["id"], manager_headers())

    validate_error(refused, "ERR_RUNG_NOT_REACHED", expected_status=422)

    lot = F.reload_lot(api, chain.lot["id"])
    A.assert_unchanged(chain.lot, lot, "version", "status", "current_price_cents")
    A.assert_fresh_unpriced_lot(lot, 599)


def test_one_millisecond_later_the_quote_prices_rung_zero_at_509_cents(api):
    """The very next millisecond floors days remaining to 3 and the shallowest rung applies.

    PRD 3.3: "The comparison boundary is inclusive, so a lot with exactly as many
    days remaining as a rung's `days_remaining_max` does select that rung."

    PRD 3.3: "Before committing, an administrator, manager or clerk may ask for a
    read-only markdown quote on a lot, which prices it under **both** ladder
    readings and writes nothing at all -- in particular the lot's `version` is left
    untouched."

    At 2026-08-11T00:00:00.001Z the gap is one millisecond short of 4 days, which
    floors to 3, selecting rung 0 at 15 percent: 599 cents less 15 percent is 509.15,
    which rounds half up to 509 cents, comfortably above the 168-cent cost floor.

    Design: Difficulty/boundary_precision_check/ladder_rung_boundary_days_remaining_three_vs_four_on_markdown_quote
    """
    chain = F.build_meat_four_rung_chain(api)
    F.set_clock(api, "2026-08-11T00:00:00.001Z")

    quote = validate_success(api.get_markdown_quote(chain.lot["id"], manager_headers()))

    A.assert_fields(
        quote,
        days_remaining=3,
        base_rung_index=0,
        ladder_days_price_cents=509,
    )

    lot = F.reload_lot(api, chain.lot["id"])
    assert lot["version"] == chain.lot["version"], (
        f"a quote must not write: version moved from {chain.lot['version']} to {lot['version']}"
    )
    A.assert_fresh_unpriced_lot(lot, 599)


def _build_draft_produce_manifest(api):
    """A SCHEDULED PRODUCE pickup whose manifest is DRAFT with no lines on it at all."""
    chain = F.build_produce_chain(
        api,
        store_overrides={"dock_door_codes": ["D1"], "donation_program_enabled": True},
        department_overrides={"shelf_life_days_default": 8},
        item_overrides={
            "upc": "000555666777",
            "description": "Salad Kit",
            "base_retail_cents": 599,
            "unit_cost_cents": 250,
            "daily_forecast_units": 8.00,
            "donation_eligible": True,
        },
        lot_overrides={"production_date": "2026-08-05", "quantity_original": 20},
    )
    F.set_clock(api, "2026-08-12T00:00:00.000Z")
    chain.pickup = F.book_pickup(
        api,
        chain.store["id"],
        chain.partner["id"],
        dock_door_code="D1",
        scheduled_window_start="2026-08-12T14:00:00.000Z",
        scheduled_window_end="2026-08-12T16:00:00.000Z",
        headers=manager_headers(),
    )
    return chain


def test_sealing_a_manifest_with_zero_lines_is_refused_and_leaves_it_draft(api):
    """At assignment_count 0 the seal is refused with ERR_EMPTY_MANIFEST.

    PRD 3.7: "sealing requires `manifest_status` to be `DRAFT` [...] and requires
    `assignment_count` to be at least 1, refusing an empty manifest with
    `ERR_EMPTY_MANIFEST` and HTTP 422."

    PRD 2.11: "A manifest carries at least one line, on manifest sealing --
    `ERR_EMPTY_MANIFEST` (422)."

    A freshly booked pickup carries no lines, so its `assignment_count` is exactly 0
    at the boundary the seal tests.

    Design: Difficulty/boundary_precision_check/empty_manifest_seal_zero_assignment_count_boundary
    """
    chain = _build_draft_produce_manifest(api)

    assert chain.pickup["assignment_count"] == 0, (
        f"a new pickup must start empty, got {chain.pickup['assignment_count']}"
    )

    refused = api.seal_donation_pickup(chain.pickup["id"], manager_headers())

    validate_error(refused, "ERR_EMPTY_MANIFEST", expected_status=422)

    pickup = F.reload_pickup(api, chain.pickup["id"])
    A.assert_fields(
        pickup, manifest_status="DRAFT", assignment_count=0, logistics_status="SCHEDULED"
    )


def test_one_line_is_enough_and_the_identical_seal_now_values_the_manifest(api):
    """At assignment_count 1 the same seal succeeds and writes the tier-one valuation.

    PRD 3.7: "Sealing moves `manifest_status` from `DRAFT` to `SEALED`, leaves
    `logistics_status` untouched, increments the pickup's `version` by one, and runs
    the manifest valuation in four pinned steps".

    PRD 3.7: "`credit_rate_pct` is selected from that provisional total by tier:
    62.50 percent when the provisional value is below 50,000 cents (that is, under
    five hundred dollars)".

    Twenty units at the 599-cent snapshot is a provisional 11,980 cents, below the
    50,000-cent boundary, so the rate is 62.5 percent and the single line's credit is
    11,980 at 62.5 percent, which is 7,487.5 rounded half up to 7,488 cents.

    Design: Difficulty/boundary_precision_check/empty_manifest_seal_zero_assignment_count_boundary
    """
    chain = _build_draft_produce_manifest(api)

    line = F.pledge_lot(api, chain.pickup["id"], chain.lot["id"], 20)
    sealed = F.seal_pickup(api, chain.pickup["id"], headers=manager_headers())

    A.assert_fields(
        sealed,
        assignment_count=1,
        manifest_status="SEALED",
        provisional_value_cents=11980,
        credit_rate_pct=62.5,
        manifest_credit_cents=7488,
    )

    credited = validate_success(api.get_donation_assignment(line["id"], manager_headers()))
    A.assert_money_cents(credited["line_credit_cents"], 7488, "line_credit_cents")
