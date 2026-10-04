"""Difficulty-design tests: temporal overlap semantics and compensating
invariants.

Covers half-open stringer window overlap (touching endpoints legal), the
closed-interval aggregate stringer-hour budget, the accept/void compensation
restoring contest totals exactly, and the publish/retract pair netting the
monthly invoice (PRD §3.2, §3.3, §3.4, §3.8).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_assignment,
    create_assignment_payload,
    create_stringer,
    get_contest,
    get_tabulation,
    list_customer_deliveries,
    propose_coverage,
    review_coverage,
    retract_call,
    setup_complete_contest,
    setup_published_call,
    setup_standard_universe,
    validate_error,
    validate_paginated,
    validate_success,
    void_report,
    generate_invoice,
)


def test_stringer_windows_half_open_overlap(api):
    """PRD §3.3: "One stringer cannot be in two places at once: no stringer may
    hold two assignments in `SCHEDULED` or `ACTIVE` status whose half-open
    windows overlap. Touching endpoints are permitted, so a window that ends at
    the exact instant another begins is legal; a genuinely overlapping request is
    rejected with `ERR_ASSIGNMENT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/stringer_windows_half_open_overlap
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    alameda_id = universe["counties"]["alameda"]["id"]
    sally = create_stringer()
    create_assignment(
        event_id, alameda_id, stringer_id=sally["id"],
        window_start="2026-11-03T08:00:00Z", window_end="2026-11-03T20:00:00Z",
    )

    overlap_payload = create_assignment_payload(
        alameda_id,
        window_start="2026-11-03T19:00:00Z",
        window_end="2026-11-03T23:00:00Z",
        stringer_id=sally["id"],
    )
    resp = api.create_assignment(
        event_id, overlap_payload, TEST_USERS["coordinator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_WINDOW_OVERLAP)

    touching_payload = create_assignment_payload(
        alameda_id,
        window_start="2026-11-03T20:00:00Z",
        window_end="2026-11-03T23:00:00Z",
        stringer_id=sally["id"],
    )
    resp_ok = api.create_assignment(
        event_id, touching_payload, TEST_USERS["coordinator_headers"],
    )
    adjacent = validate_success(resp_ok, 201)
    assert adjacent["status"] == "SCHEDULED"

    _rows, meta = validate_paginated(
        api.list_stringer_assignments(
            sally["id"], TEST_USERS["coordinator_headers"],
        )
    )
    assert meta["total_count"] == 2


def test_coverage_budget_closed_interval_aggregate_capacity(api):
    """PRD §3.2: "Approval is budgeted: the sum of `allocated_stringer_hours`
    over the event's decisions already in `APPROVED` or `FUNDED` status whose
    closed coverage intervals intersect this decision's closed interval, plus
    this decision's own hours, must not exceed the event's
    `total_stringer_hour_budget`; if the total would breach the budget, the
    review is rejected with `ERR_COVERAGE_BUDGET_EXCEEDED`."
    PRD §3.2: "Because intersection is judged on closed intervals, two decisions
    that share exactly one boundary day do intersect."

    Design: Difficulty/resource_temporal_overlap/coverage_budget_closed_interval_aggregate_capacity
    """
    universe = setup_standard_universe(advance_to="SETUP")
    event_id = universe["event"]["id"]
    contest_id = universe["contest"]["id"]

    d1 = propose_coverage(event_id, contest_id, 250, "2026-10-30", "2026-11-03")
    d1 = review_coverage(d1["id"], "APPROVE")
    assert d1["status"] == "APPROVED"
    d2 = propose_coverage(event_id, contest_id, 200, "2026-11-03", "2026-11-05")
    d3 = propose_coverage(event_id, contest_id, 150, "2026-11-03", "2026-11-04")

    # 250 + 200 = 450 > 400: the shared boundary day 2026-11-03 intersects.
    resp = api.review_coverage_decision(
        d2["id"], "APPROVE", TEST_USERS["admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_BUDGET_EXCEEDED)

    # 250 + 150 = 400 <= 400: the inclusive cap admits the third decision.
    d3_after = review_coverage(d3["id"], "APPROVE")
    assert d3_after["status"] == "APPROVED"

    rows, _meta = validate_paginated(
        api.list_event_coverage_decisions(event_id, TEST_USERS["admin_headers"])
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[d2["id"]]["status"] == "PROPOSED"
    assert by_id[d1["id"]]["status"] == "APPROVED"


def test_accept_then_void_restores_contest_totals(api):
    """PRD §3.4: "VOID is the compensation path: it moves an `ACCEPTED` report to
    `VOIDED`, resets `accepted_at` to null, and recomputes the rollup with the
    report removed — incrementing the contest's `version` again, and reopening
    the contest from `COMPLETE` back to `REPORTING` if the reporting county
    thereby loses the complete latest accepted report that had closed it."
    PRD §3.4: "Because only `ACCEPTED` reports ever feed the rollup, VOID
    compensates ACCEPT exactly: the contest's totals return to their
    pre-acceptance values."

    Design: Difficulty/compensating_invariant/accept_then_void_restores_contest_totals
    """
    universe = setup_complete_contest()
    contest_id = universe["contest"]["id"]
    rep_b = universe["reports"][1]

    voided = void_report(rep_b["id"])
    assert voided["status"] == "VOIDED"
    assert voided["accepted_at"] is None

    contest = get_contest(contest_id)
    assert contest["total_votes"] == 10000
    assert contest["reported_precincts"] == 10
    assert contest["tabulation_status"] == "REPORTING"

    board = get_tabulation(contest_id)
    assert board["total_votes"] == 10000
    # 6000 - 4000 = 2000 over 10000 pins the restored per-candidate split.
    assert board["margin_pct"] == 0.2


def test_publish_then_retract_nets_invoice_to_zero(api):
    """PRD §3.8: "Retracting a published call — whether by the desk or by the
    recount cascade — flips every `CALL` delivery of the contest still in `SENT`
    status to `STALE`, and creates for each customer that received such a
    delivery a compensating `CALL_CREDIT` delivery in `SENT` status whose
    `fee_cents` is the exact negation of the original `CALL` delivery's fee."
    PRD §3.8: "both `SENT` and `STALE` rows are billed, and `CALL_CREDIT` rows
    count"

    Design: Difficulty/compensating_invariant/publish_then_retract_nets_invoice_to_zero
    """
    universe = setup_published_call(
        link_contra_costa=False, customers=("premium",),
    )
    contest_id = universe["contest"]["id"]
    customer = universe["customers"]["premium"]

    retract_call(universe["call"]["id"], "bad exit-poll feed integration")

    invoice = generate_invoice(customer["id"], "2026-11")
    assert invoice["delivery_count"] == 3
    assert invoice["total_fee_cents"] == 999

    rows, meta = list_customer_deliveries(customer["id"])
    assert meta["total_count"] == 3
    by_type = {row["content_type"]: row for row in rows}
    assert by_type["VOTE_UPDATE"]["fee_cents"] == 999
    assert by_type["VOTE_UPDATE"]["status"] == "SENT"
    assert by_type["CALL"]["fee_cents"] == 4999
    assert by_type["CALL"]["status"] == "STALE"
    assert by_type["CALL_CREDIT"]["fee_cents"] == -4999
    assert by_type["CALL_CREDIT"]["status"] == "SENT"

    assert get_contest(contest_id)["call_status"] == "UNCALLED"
