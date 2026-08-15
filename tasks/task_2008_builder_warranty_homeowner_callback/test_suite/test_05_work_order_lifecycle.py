"""Work order completion, verification, the rework loop, closure, and the
completion-time cost cascade into the request roll-up and the reserve ledger."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equal,
    assert_ledger_conservation,
    complete_work_order,
    create_approved_request,
    create_trade_partner,
    dispatch_work_order,
    get_reserve_for_home,
    issue_chargeback,
    list_reserve_entries,
    run_sweep,
    set_clock,
    setup_dispatched_work_order,
    setup_home,
    setup_issued_chargeback,
    setup_pending_followup_request,
    validate_error,
    validate_success,
    verify_work_order,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS, make_homeowner_headers, make_trade_partner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]


def test_wo_rework_cycle_reject_then_reschedule(api):
    """PRD §3.4: "an `outcome` of `REJECT` requires a `rejection_reason` and moves
    the work order to `REJECTED`, opening the workmanship rework loop."
    PRD §3.4: "Returning from `REJECTED` to `SCHEDULED` also bumps
    `open_work_order_count` by one and clears `completed_at`; the retained
    `actual_cost_cents` stays on the record for audit but drops out of the parent
    request's rolled-up cost until the visit completes again, because the roll-up
    counts only `COMPLETED` and `ACCEPTED` work orders."

    Design: Corner/state_machines/wo_rework_cycle_reject_then_reschedule
    """
    ctx = setup_dispatched_work_order(
        item_category="FLOORING",
        trade="FLOORING",
        estimated_cost_cents=90_000,
        defect_responsibility="SUBCONTRACTOR",
        request_description="Tile lippage",
    )
    wo = complete_work_order(ctx["work_order"]["id"], ctx["partner"]["id"], 80_000)
    assert wo["status"] == "COMPLETED"

    resp = api.verify_work_order(
        wo["id"], {"outcome": "REJECT"}, make_homeowner_headers(ctx["homeowner"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    still_completed = validate_success(api.get_work_order(wo["id"], REP), 200)
    assert still_completed["status"] == "COMPLETED", (
        "REJECT without rejection_reason is a shape error; state untouched"
    )

    rejected = verify_work_order(
        wo["id"],
        ctx["homeowner"]["id"],
        outcome="REJECT",
        rejection_reason="Grout lines still uneven",
    )
    assert rejected["status"] == "REJECTED"

    resp = api.reschedule_work_order(
        wo["id"],
        {"window_start": "2026-08-12T09:00:00Z", "window_end": "2026-08-12T11:00:00Z"},
        REP,
    )
    rearmed = validate_success(resp, 200)
    assert rearmed["status"] == "SCHEDULED"
    assert_instant_equal(
        rearmed["window_start"], "2026-08-12T09:00:00Z", "window_start"
    )
    assert rearmed.get("completed_at") is None, "reschedule re-arms the visit"
    assert rearmed["actual_cost_cents"] == 80_000, (
        "actual cost retained on the record for audit"
    )

    partner = validate_success(api.get_trade_partner(ctx["partner"]["id"], MANAGER), 200)
    assert partner["open_work_order_count"] == 1, (
        "REJECTED -> SCHEDULED re-enters the partner's open count"
    )


def test_cb_cancelled_work_order_voids_chargeback_lockdown(api):
    """PRD §3.4: "Cancelling a `SCHEDULED` work order, optionally with a
    `cancel_reason`, moves it to `CANCELLED`, decrements the partner's count by
    one, and voids a linked provisional chargeback still in `ISSUED`."
    PRD §3.6: "`PAID`, `WAIVED`, and `VOID` are terminal."
    PRD §2.7: "If the target sits in a terminal state for its lifecycle — a
    `CLOSED` service request; an `ACCEPTED` or `CANCELLED` work order; a `PAID`,
    `WAIVED`, or `VOID` chargeback; a `PAID` or `DENIED` claim — the rejection is
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/cb_cancelled_work_order_voids_chargeback_lockdown
    """
    ctx = setup_issued_chargeback(estimated_cost_cents=110_000)
    resp = api.cancel_work_order(
        ctx["work_order"]["id"], {"cancel_reason": "Duplicate dispatch"}, REP
    )
    cancelled = validate_success(resp, 200)
    assert cancelled["status"] == "CANCELLED"

    chargeback = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
    assert chargeback["status"] == "VOID", (
        "cancel cascade voided the provisional chargeback"
    )

    err = api.contest_chargeback(
        ctx["chargeback"]["id"],
        {"contest_reason": "Too late anyway"},
        make_trade_partner_headers(ctx["partner"]["id"]),
    )
    validate_error(err, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_sr_auto_close_after_followup_window(api):
    """PRD §3.5: "Alternatively, a request left waiting in `PENDING_FOLLOWUP` is
    closed by the operations sweep once the clock reaches `followup_entered_at`
    plus fourteen days, stamping `closed_at` without a score."

    Design: Corner/state_machines/sr_auto_close_after_followup_window
    """
    ctx = setup_pending_followup_request(actual_cost_cents=60_000)
    assert ctx["work_order"]["status"] == "ACCEPTED"
    waiting = validate_success(api.get_service_request(ctx["request"]["id"], REP), 200)
    assert waiting["status"] == "PENDING_FOLLOWUP"
    # followup entered at the 2026-08-01T00:00:00Z default clock; +14 days exactly.
    set_clock("2026-08-15T00:00:00Z")
    sweep = run_sweep()
    assert sweep["requests_auto_closed"] == 1, (
        "boundary is inclusive: now == followup_entered_at + 14 days auto-closes"
    )

    closed = validate_success(api.get_service_request(ctx["request"]["id"], REP), 200)
    assert closed["status"] == "CLOSED"
    assert_instant_equal(closed["closed_at"], "2026-08-15T00:00:00Z", "closed_at")


def test_sla_completion_breach_on_late_followup_entry(api):
    """PRD §3.4: "Acceptance also bubbles upward: when every work order of the
    parent request sits in `ACCEPTED` or `CANCELLED` and at least one is
    `ACCEPTED`, the request advances itself from `IN_SERVICE` to
    `PENDING_FOLLOWUP`, stamping `followup_entered_at` — and if that instant is
    strictly later than `completion_due_at`, `completion_breached` is set and
    `escalation_level` rises to 2."

    Design: Corner/state_machines/sla_completion_breach_on_late_followup_entry
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    request = create_approved_request(
        home["id"],
        homeowner["id"],
        item_category="ELECTRICAL",
        description="Dead outlet",
    )
    # Approved at the 2026-08-01 default clock: completion due 2026-08-31T00:00:00Z.
    partner = create_trade_partner(
        company_name="VoltLine Electric",
        trade="ELECTRICAL",
        contact_email="sched@voltline.example.com",
    )
    set_clock("2026-09-02T00:00:00Z")
    work_order = dispatch_work_order(
        request["id"],
        partner["id"],
        window_start="2026-09-03T09:00:00Z",
        window_end="2026-09-03T11:00:00Z",
        estimated_cost_cents=52_000,
        defect_responsibility="BUILDER",
    )
    complete_work_order(work_order["id"], partner["id"], 52_000)
    verify_work_order(work_order["id"], homeowner["id"], outcome="ACCEPT")

    after = validate_success(api.get_service_request(request["id"], REP), 200)
    assert after["status"] == "PENDING_FOLLOWUP"
    assert after["completion_breached"] is True, (
        "entry at 2026-09-02 is strictly later than the 2026-08-31 due instant"
    )
    assert after["escalation_level"] == 2
    assert after["response_breached"] is False, (
        "response leg was met: assessed at the same instant it was reported"
    )


class TestTradeOpenWorkOrderCardinality:
    def _setup_two_requests_one_order(self, api):
        homeowner, home = setup_home(closing_date="2026-06-01")
        partner = create_trade_partner()
        sr1 = create_approved_request(
            home["id"], homeowner["id"], description="Job A"
        )
        sr2 = create_approved_request(
            home["id"], homeowner["id"], description="Job B"
        )
        wo1 = dispatch_work_order(
            sr1["id"],
            partner["id"],
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T11:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        return homeowner, home, partner, sr2, wo1

    def test_cancel_decrements_open_count(self, api):
        """PRD §3.4: "Cancelling a `SCHEDULED` work order, optionally with a
        `cancel_reason`, moves it to `CANCELLED`, decrements the partner's count
        by one, and voids a linked provisional chargeback still in `ISSUED`."
        PRD §3.1: "Two counters track each partner's exposure:
        `open_work_order_count`, the number of its visits currently `SCHEDULED`,
        and `outstanding_chargeback_cents`, its unpaid chargeback balance (§3.6)."

        Design: Difficulty/compensating_invariant/trade_open_work_order_cardinality
        """
        _ho, _home, partner, _sr2, wo1 = self._setup_two_requests_one_order(api)
        before = validate_success(api.get_trade_partner(partner["id"], MANAGER), 200)
        assert before["open_work_order_count"] == 1

        resp = api.cancel_work_order(
            wo1["id"], {"cancel_reason": "Homeowner traveling"}, REP
        )
        cancelled = validate_success(resp, 200)
        assert cancelled["status"] == "CANCELLED"

        after = validate_success(api.get_trade_partner(partner["id"], MANAGER), 200)
        assert after["open_work_order_count"] == 0, "cancel decremented the cardinality"

    def test_compensating_dispatch_restores_count(self, api):
        """PRD §3.3: "A created work order starts `SCHEDULED`, bumps the partner's
        `open_work_order_count` by one, and — when it is the request's first
        dispatch — automatically moves the parent request from `APPROVED` to
        `IN_SERVICE`."
        PRD §3.4: "Cancelling a `SCHEDULED` work order, optionally with a
        `cancel_reason`, moves it to `CANCELLED`, decrements the partner's count
        by one, and voids a linked provisional chargeback still in `ISSUED`."

        Design: Difficulty/compensating_invariant/trade_open_work_order_cardinality
        """
        _ho, _home, partner, sr2, wo1 = self._setup_two_requests_one_order(api)
        before = validate_success(api.get_trade_partner(partner["id"], MANAGER), 200)
        assert before["open_work_order_count"] == 1

        api.cancel_work_order(wo1["id"], {"cancel_reason": "Homeowner traveling"}, REP)
        wo2 = dispatch_work_order(
            sr2["id"],
            partner["id"],
            window_start="2026-08-11T09:00:00Z",
            window_end="2026-08-11T11:00:00Z",
            estimated_cost_cents=60_000,
            defect_responsibility="BUILDER",
        )
        assert wo2["status"] == "SCHEDULED"
        final = validate_success(api.get_trade_partner(partner["id"], MANAGER), 200)
        assert final["open_work_order_count"] == before["open_work_order_count"] == 1, (
            "cancel (-1) paired with the replacement dispatch (+1) leaves the "
            "conserved count unchanged"
        )


class TestWorkOrderCompletionCostCascade:
    def _setup_and_complete(self, api):
        """Home closing 2026-06-01; sweep posts 2 accruals (balance 3334) at the
        default clock; approved PLUMBING request; SUBCONTRACTOR work order
        estimated 150000 with an issued chargeback; then completion at 110000."""
        homeowner, home = setup_home(closing_date="2026-06-01")
        run_sweep()  # two monthly accruals of 1667 at the 2026-08-01 default clock
        request = create_approved_request(
            home["id"],
            homeowner["id"],
            item_category="PLUMBING",
            description="Water heater leak",
        )
        partner = create_trade_partner()
        work_order = dispatch_work_order(
            request["id"],
            partner["id"],
            window_start="2026-08-10T09:00:00Z",
            window_end="2026-08-10T11:00:00Z",
            estimated_cost_cents=150_000,
            defect_responsibility="SUBCONTRACTOR",
        )
        chargeback = issue_chargeback(work_order["id"])
        completed = complete_work_order(work_order["id"], partner["id"], 110_000)
        return homeowner, home, request, partner, work_order, chargeback, completed

    def test_cascade_request_rollup_and_chargeback_finalization(self, api):
        """PRD §3.4: "The parent request's `actual_cost_cents` is recomputed as the
        sum of invoiced costs over its work orders in `COMPLETED` or `ACCEPTED`."
        PRD §3.4: "And a linked chargeback still provisional and sitting in
        `ISSUED` or `CONTESTED` is refinalized against the invoiced cost:
        `final_amount_cents` is recomputed by the chargeback formula of §3.6, and
        `amount_basis` moves to `FINAL` — or, when the recomputed final amount is
        zero, the chargeback voids itself automatically."

        Design: Difficulty/transitive_cascade/work_order_completion_cost_cascade
        """
        _ho, _home, request, _tp, work_order, chargeback, completed = (
            self._setup_and_complete(api)
        )
        assert completed["status"] == "COMPLETED"
        assert completed["actual_cost_cents"] == 110_000

        parent = validate_success(api.get_service_request(request["id"], REP), 200)
        assert parent["actual_cost_cents"] == 110_000, (
            "request cost roll-up recomputed from the completed work order"
        )

        cb = validate_success(api.get_chargeback(chargeback["id"], REP), 200)
        assert cb["final_amount_cents"] == 93_500, (
            "recoverable max(0, 110000-25000) = 85000 + fee 8500"
        )
        assert cb["amount_basis"] == "FINAL"
        assert cb["status"] == "ISSUED", (
            "refinalization is not approval; the chargeback remains ISSUED"
        )

    def test_cascade_reserve_draw_and_alert(self, api):
        """PRD §3.4: "The home's reserve posts a `DRAW` entry of negative the
        invoiced cost with `work_order_ref` set, recomputing `balance_cents` and
        `drawn_to_date_cents` and re-evaluating the trend alert."
        PRD §3.7: "A balance below zero is `DEPLETED`."

        Design: Difficulty/transitive_cascade/work_order_completion_cost_cascade
        """
        _ho, home, _req, _tp, work_order, _cb, _completed = (
            self._setup_and_complete(api)
        )
        reserve = get_reserve_for_home(home["id"])
        assert reserve["drawn_to_date_cents"] == 110_000
        assert reserve["balance_cents"] == -106_666, (
            f"3334 accrual minus 110000 draw == -106666, got {reserve['balance_cents']}"
        )
        assert reserve["alert_status"] == "DEPLETED", "balance below zero"

        draws = list_reserve_entries(reserve["id"], kind="DRAW")
        assert len(draws) == 1
        assert draws[0]["amount_cents"] == -110_000
        assert draws[0]["work_order_ref"] == work_order["id"]
        entries = list_reserve_entries(reserve["id"])
        assert_ledger_conservation(reserve, entries)
