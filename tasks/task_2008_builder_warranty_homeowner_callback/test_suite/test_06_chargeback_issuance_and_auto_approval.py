"""Chargeback issuance: provisional vs final amounts, the deductible/cap/fee
formula, zero-final auto-voiding, eligibility, uniqueness, and the contest window."""
from test_helpers import (
    ApiErrorId,
    complete_work_order,
    create_approved_request,
    create_trade_partner,
    dispatch_work_order,
    issue_chargeback,
    set_clock,
    setup_dispatched_work_order,
    setup_home,
    setup_issued_chargeback,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_chargeback_payload
from test_helpers.test_users import TEST_USERS, make_trade_partner_headers

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["rep_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestChargebackProvisionalVsFinal:
    def test_provisional_amount_from_estimate(self, api):
        """PRD §3.6: "From the cost basis, subtract the 25,000-cent deductible —
        two hundred fifty dollars — flooring the result at zero; cap the
        recoverable portion at 500,000 cents; then add an administration fee of
        ten percent of the capped amount, rounded half-up to whole cents
        immediately after the multiplication and itself capped at 15,000 cents.
        The payable amount is the capped portion plus the fee."
        PRD §3.6: "Issuance denormalizes the partner onto the chargeback as its
        `trade_partner_id`, stamps `issued_at`, sets the ten-day contest window
        `contest_deadline_at` — inclusive, like the dispute window — and records a
        `provisional_amount_cents` computed from the work order's
        `estimated_cost_cents`, with `amount_basis` `PROVISIONAL` and nothing yet
        collected."

        Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final
        """
        ctx = setup_issued_chargeback(estimated_cost_cents=150_000)
        cb = ctx["chargeback"]
        assert cb["provisional_amount_cents"] == 137_500, (
            "recoverable max(0, 150000-25000) = 125000 + fee min(12500, 15000)"
        )
        assert cb["amount_basis"] == "PROVISIONAL"
        assert cb["payable_amount_cents"] == 137_500, (
            "payable is the provisional amount while the basis is PROVISIONAL"
        )
        assert cb["collected_cents"] == 0

    def test_final_amount_from_actual_cost(self, api):
        """PRD §3.4: "And a linked chargeback still provisional and sitting in
        `ISSUED` or `CONTESTED` is refinalized against the invoiced cost:
        `final_amount_cents` is recomputed by the chargeback formula of §3.6, and
        `amount_basis` moves to `FINAL`".
        PRD §3.6: "`payable_amount_cents` is the final amount once `amount_basis`
        is `FINAL`, and the provisional amount while the basis is still
        `PROVISIONAL`."

        Design: Difficulty/dual_variant_calc/chargeback_provisional_vs_final
        """
        ctx = setup_issued_chargeback(estimated_cost_cents=150_000)
        assert ctx["chargeback"]["provisional_amount_cents"] == 137_500
        complete_work_order(ctx["work_order"]["id"], ctx["partner"]["id"], 110_000)

        cb = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
        assert cb["final_amount_cents"] == 93_500, (
            "recoverable max(0, 110000-25000) = 85000 + fee 8500; same formula, "
            "different cost basis than the 137500 provisional"
        )
        assert cb["amount_basis"] == "FINAL"
        assert cb["payable_amount_cents"] == 93_500
        assert cb["provisional_amount_cents"] == 137_500


class TestChargebackCapAndFeeTiers:
    def test_provisional_fee_max_binds(self, api):
        """PRD §3.6: "then add an administration fee of ten percent of the capped
        amount, rounded half-up to whole cents immediately after the
        multiplication and itself capped at 15,000 cents."

        Design: Difficulty/combinatorial_formula/chargeback_cap_and_fee_tier_min_max
        """
        ctx = setup_issued_chargeback(estimated_cost_cents=500_000)
        cb = ctx["chargeback"]
        assert cb["provisional_amount_cents"] == 490_000, (
            "recoverable 475000 + fee min(47500, 15000) = 15000"
        )

    def test_final_cap_and_fee_max_both_bind(self, api):
        """PRD §3.6: "From the cost basis, subtract the 25,000-cent deductible —
        two hundred fifty dollars — flooring the result at zero; cap the
        recoverable portion at 500,000 cents; then add an administration fee of
        ten percent of the capped amount, rounded half-up to whole cents
        immediately after the multiplication and itself capped at 15,000 cents.
        The payable amount is the capped portion plus the fee."

        Design: Difficulty/combinatorial_formula/chargeback_cap_and_fee_tier_min_max
        """
        ctx = setup_issued_chargeback(estimated_cost_cents=500_000)
        complete_work_order(ctx["work_order"]["id"], ctx["partner"]["id"], 2_000_000)

        cb = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
        assert cb["final_amount_cents"] == 515_000, (
            "recoverable min(1975000, 500000) = 500000 (cap binds) + fee "
            "min(50000, 15000) = 15000 (fee max binds)"
        )
        assert cb["amount_basis"] == "FINAL"


class TestChargebackZeroFinalAutoVoid:
    def _setup_voided(self, api):
        ctx = setup_issued_chargeback(estimated_cost_cents=100_000)
        assert ctx["chargeback"]["provisional_amount_cents"] == 82_500, (
            "recoverable 75000 + fee 7500"
        )
        complete_work_order(ctx["work_order"]["id"], ctx["partner"]["id"], 25_000)
        return ctx

    def test_cost_at_deductible_voids_chargeback(self, api):
        """PRD §3.6: "When the formula yields zero — a cost at or under the
        deductible — the chargeback voids itself rather than stand for nothing."
        PRD §3.4: "And a linked chargeback still provisional and sitting in
        `ISSUED` or `CONTESTED` is refinalized against the invoiced cost:
        `final_amount_cents` is recomputed by the chargeback formula of §3.6, and
        `amount_basis` moves to `FINAL` — or, when the recomputed final amount is
        zero, the chargeback voids itself automatically."

        Design: Difficulty/boundary_precision_check/chargeback_zero_final_auto_void
        """
        ctx = self._setup_voided(api)
        cb = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
        assert cb["final_amount_cents"] == 0, (
            "max(0, 25000-25000) = 0 recoverable, fee on 0 is 0"
        )
        assert cb["status"] == "VOID"
        assert cb["outstanding_cents"] == 0

    def test_voided_chargeback_is_terminal(self, api):
        """PRD §3.6: "`PAID`, `WAIVED`, and `VOID` are terminal."
        PRD §2.7: "If the target sits in a terminal state for its lifecycle — a
        `CLOSED` service request; an `ACCEPTED` or `CANCELLED` work order; a
        `PAID`, `WAIVED`, or `VOID` chargeback; a `PAID` or `DENIED` claim — the
        rejection is `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/boundary_precision_check/chargeback_zero_final_auto_void
        """
        ctx = self._setup_voided(api)
        resp = api.record_payment(
            ctx["chargeback"]["id"], {"amount_cents": 1}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


def test_non_subcontractor_work_order_not_chargebackable(api):
    """PRD §3.6: "When the triage attribution is `SUBCONTRACTOR`, the
    representative may issue a chargeback against the work order — but only while
    the work order is still `SCHEDULED`, and only if no non-`VOID` chargeback
    already exists for it."
    PRD §3.6: "The uniqueness check fires first, as `ERR_DUPLICATE_CHARGEBACK`;
    only then does eligibility bite, with `ERR_NOT_CHARGEBACKABLE` for a wrong
    attribution or a work order that has already left `SCHEDULED`."

    Design: Corner/validations/non_subcontractor_work_order_not_chargebackable
    """
    ctx = setup_dispatched_work_order(
        estimated_cost_cents=60_000, defect_responsibility="BUILDER"
    )
    resp = api.create_chargeback(
        create_chargeback_payload(ctx["work_order"]["id"]), REP
    )
    validate_error(resp, ApiErrorId.ERR_NOT_CHARGEBACKABLE)

    data, meta = validate_paginated(
        api.list_chargebacks(REP, params={"work_order_id": ctx["work_order"]["id"]})
    )
    assert meta["total_count"] == 0 and data == []


def test_duplicate_chargeback_rejected(api):
    """PRD §3.6: "The uniqueness check fires first, as `ERR_DUPLICATE_CHARGEBACK`;
    only then does eligibility bite, with `ERR_NOT_CHARGEBACKABLE` for a wrong
    attribution or a work order that has already left `SCHEDULED`."

    Design: Corner/validations/duplicate_chargeback_rejected
    """
    ctx = setup_issued_chargeback(estimated_cost_cents=110_000)
    resp = api.create_chargeback(
        create_chargeback_payload(ctx["work_order"]["id"]), REP
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CHARGEBACK)

    original = validate_success(api.get_chargeback(ctx["chargeback"]["id"], REP), 200)
    assert original["status"] == "ISSUED", "original chargeback unchanged"


def test_contest_window_inclusive_then_closed(api):
    """PRD §3.6: "The charged partner — and only that partner — may contest within
    the window, filing a `contest_reason` that moves the chargeback to
    `CONTESTED`; after the deadline the attempt is `ERR_CONTEST_WINDOW_CLOSED`."
    PRD §3.6: "Issuance denormalizes the partner onto the chargeback as its
    `trade_partner_id`, stamps `issued_at`, sets the ten-day contest window
    `contest_deadline_at` — inclusive, like the dispute window — and records a
    `provisional_amount_cents` computed from the work order's
    `estimated_cost_cents`, with `amount_basis` `PROVISIONAL` and nothing yet
    collected."

    Design: Corner/validations/contest_window_inclusive_then_closed
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    partner = create_trade_partner()
    sr1 = create_approved_request(home["id"], homeowner["id"], description="Job 1")
    sr2 = create_approved_request(home["id"], homeowner["id"], description="Job 2")
    wo1 = dispatch_work_order(
        sr1["id"], partner["id"],
        window_start="2026-08-05T09:00:00Z", window_end="2026-08-05T11:00:00Z",
        estimated_cost_cents=110_000,
    )
    wo2 = dispatch_work_order(
        sr2["id"], partner["id"],
        window_start="2026-08-06T09:00:00Z", window_end="2026-08-06T11:00:00Z",
        estimated_cost_cents=110_000,
    )
    cb1 = issue_chargeback(wo1["id"])
    cb2 = issue_chargeback(wo2["id"])
    # Issued at the 2026-08-01T00:00:00Z default clock: deadline 2026-08-11T00:00:00Z.
    set_clock("2026-08-11T00:00:00Z")
    contested = validate_success(
        api.contest_chargeback(
            cb1["id"],
            {"contest_reason": "At the wire"},
            make_trade_partner_headers(partner["id"]),
        ),
        200,
    )
    assert contested["status"] == "CONTESTED", "contest exactly at the deadline is accepted"

    set_clock("2026-08-11T00:00:01Z")
    resp = api.contest_chargeback(
        cb2["id"],
        {"contest_reason": "One second late"},
        make_trade_partner_headers(partner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONTEST_WINDOW_CLOSED)
    after = validate_success(api.get_chargeback(cb2["id"], REP), 200)
    assert after["status"] == "ISSUED"


def test_cb_auto_approve_sweep_threshold_and_deadline(api):
    """PRD §3.6: "Or the chargeback is approved, moving to `APPROVED`: manually by
    the `WarrantyManager`, optionally with `approve_notes` — the only route for
    amounts above the auto-approval cap — or automatically by the operations
    sweep, which walks `ISSUED` chargebacks from earliest `issued_at` first,
    breaking ties by creation order, and approves each whose contest deadline has
    strictly passed and whose payable amount is at most 100,000 cents; a payable
    exactly at the one-thousand-dollar cap is approved."

    Design: Corner/state_machines/cb_auto_approve_sweep_threshold_and_deadline
    """
    homeowner, home = setup_home(closing_date="2026-06-01")
    partner = create_trade_partner()
    specs = [
        ("Job 1", "2026-08-05", 110_000),  # payable 93500 <= cap
        ("Job 2", "2026-08-06", 150_000),  # payable 137500 > cap
        ("Job 3", "2026-08-07", 90_000),   # payable 71500 <= cap
    ]
    chargebacks = []
    for description, day, estimate in specs:
        sr = create_approved_request(
            home["id"], homeowner["id"], description=description
        )
        wo = dispatch_work_order(
            sr["id"], partner["id"],
            window_start=f"{day}T09:00:00Z", window_end=f"{day}T11:00:00Z",
            estimated_cost_cents=estimate,
        )
        chargebacks.append(issue_chargeback(wo["id"]))
    # Issued at the 2026-08-01 default clock: contest deadline 2026-08-11T00:00:00Z.
    set_clock("2026-08-11T00:00:00Z")
    at_deadline = validate_success(api.run_sweep(MANAGER), 200)
    assert at_deadline["chargebacks_auto_approved"] == 0, (
        "the sweep requires now strictly later than contest_deadline_at; at the "
        "deadline instant itself nothing is auto-approved"
    )

    set_clock("2026-08-12T00:00:00Z")
    past_deadline = validate_success(api.run_sweep(MANAGER), 200)
    assert past_deadline["chargebacks_auto_approved"] == 2

    s1 = validate_success(api.get_chargeback(chargebacks[0]["id"], REP), 200)
    s2 = validate_success(api.get_chargeback(chargebacks[1]["id"], REP), 200)
    s3 = validate_success(api.get_chargeback(chargebacks[2]["id"], REP), 200)
    assert s1["status"] == "APPROVED" and s3["status"] == "APPROVED", (
        "payable 93500 and 71500 are both at most 100000"
    )
    assert s2["status"] == "ISSUED", (
        "137500 exceeds the auto-approval cap; it needs manual manager approval"
    )
