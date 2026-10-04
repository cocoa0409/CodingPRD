"""Validation priority conflicts: state-vs-constraint and temporal-vs-fiscal."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    checkout,
    create_patron,
    create_title,
    get_success_data,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    set_clock,
    setup_base,
    setup_base_with_title,
    setup_ocou_library,
    create_order,
    propose_order,
    validate_error,
    validate_success,
)


def test_renew_with_suspended_patron_and_queue_reports_state_error(api):
    """PRD §2.9: "Every endpoint applies its checks in a fixed priority order,
    so that a request failing several rules always surfaces the earliest
    failure. ... Sixth, the target entity must be in the state the operation
    requires (patron `ACTIVE`, fund `OPEN`, order in the transition's
    from-state, hold in `PLACED`/`READY`/`SUSPENDED` as appropriate, loan
    `ACTIVE`, license `ACTIVE`), surfacing the specialization that matches —
    `ERR_PATRON_NOT_ACTIVE`, `ERR_FUND_CLOSED`, `ERR_ORDER_INVALID_STATE`,
    `ERR_HOLD_NOT_ACTIONABLE`, or `ERR_LOAN_NOT_ACTIVE`. ... Eighth, caps and
    uniqueness rules (loan and hold caps, duplicate holds and loans, hold-queue
    checkout blocks, renewal caps and blocks, fund period overlap,
    simultaneous-use and skip-the-line gating), surfacing the matching
    specialization."

    Design: Difficulty/priority_pair_validation_conflict/renew_patron_suspended_state_beats_hold_constraint
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    place_hold(p1["id"], ctx["title"]["id"])
    resp = api.suspend_patron(p0["id"], make_library_admin_headers(lib["id"]))
    assert resp.status_code == 200, resp.text
    resp = api.renew_loan(loan0["id"], make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_PATRON_NOT_ACTIVE)
    loan = validate_success(api.get_loan(loan0["id"], make_patron_headers(p0["id"])))
    assert loan["renewals_used"] == 0


def test_renew_state_error_is_not_reported_as_hold_block(api):
    """PRD §3.7: "the patron must be `ACTIVE` (`ERR_PATRON_NOT_ACTIVE`); skip-the-line loans can never renew (`ERR_RENEWAL_LIMIT_REACHED`); `renewals_used` must still be below the library's `max_renewals` (`ERR_RENEWAL_LIMIT_REACHED`); no hold on the title may exist in `PLACED`, `READY`, or `SUSPENDED` status by any patron (`ERR_RENEWAL_BLOCKED_BY_HOLDS` — queued demand always beats an extension)."
    PRD §2.9: "a request failing several rules always surfaces the earliest
    failure."

    Design: Difficulty/priority_pair_validation_conflict/renew_patron_suspended_state_beats_hold_constraint
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    place_hold(p1["id"], ctx["title"]["id"])
    original_due = loan0["due_at"]
    api.suspend_patron(p0["id"], make_library_admin_headers(lib["id"]))
    resp = api.renew_loan(loan0["id"], make_patron_headers(p0["id"]))
    err = validate_error(resp, ApiErrorId.ERR_PATRON_NOT_ACTIVE)
    assert err["error_id"] != ApiErrorId.ERR_RENEWAL_BLOCKED_BY_HOLDS.value
    loan = validate_success(api.get_loan(loan0["id"], make_patron_headers(p0["id"])))
    assert loan["due_at"] == original_due, "rejected renewal must not move due_at"


def test_approve_outside_period_and_over_budget_reports_temporal_error(api):
    """PRD §2.9: "Ninth, temporal windows (fiscal period containment, card
    validity, renewal term within license expiry, claim before pickup expiry).
    Money checks come last of all: the budget gate at order approval
    (`ERR_BUDGET_EXCEEDED`) and the prepaid-balance check at
    cost-per-circulation checkout (`ERR_LICENSE_BALANCE_DEPLETED`)."

    Design: Difficulty/priority_pair_validation_conflict/order_approve_temporal_beats_fiscal
    """
    ctx = setup_base()
    lib = ctx["library"]
    title = create_title(ctx["consortium"]["id"], price_ocou_cents=2000000)
    order = create_order(lib["id"], ctx["fund"]["id"], title["id"],
                         model="OCOU", copies=1)
    propose_order(lib["id"], order["id"])
    set_clock("2027-01-02T00:00:00Z")
    resp = api.approve_order(order["id"], make_library_admin_headers(lib["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_OUTSIDE_FISCAL_PERIOD)
    fresh = validate_success(
        api.get_order(order["id"], make_library_admin_headers(lib["id"]))
    )
    assert fresh["status"] == "PROPOSED"


def test_approve_temporal_error_is_not_reported_as_budget_exceeded(api):
    """PRD §3.10: "the fund must be `OPEN` (`ERR_FUND_CLOSED`), the current
    logical time must fall inside the fund's half-open period
    (`ERR_ORDER_OUTSIDE_FISCAL_PERIOD`), and the order's
    `estimated_cost_cents` must not exceed the fund's
    `available_committed_cents` (`ERR_BUDGET_EXCEEDED`)."
    PRD §2.9: "Money checks come last of all."

    Design: Difficulty/priority_pair_validation_conflict/order_approve_temporal_beats_fiscal
    """
    ctx = setup_base()
    lib = ctx["library"]
    title = create_title(ctx["consortium"]["id"], price_ocou_cents=2000000)
    order = create_order(lib["id"], ctx["fund"]["id"], title["id"],
                         model="OCOU", copies=1)
    propose_order(lib["id"], order["id"])
    set_clock("2027-01-02T00:00:00Z")
    resp = api.approve_order(order["id"], make_library_admin_headers(lib["id"]))
    err = validate_error(resp, ApiErrorId.ERR_ORDER_OUTSIDE_FISCAL_PERIOD)
    assert err["error_id"] != ApiErrorId.ERR_BUDGET_EXCEEDED.value
