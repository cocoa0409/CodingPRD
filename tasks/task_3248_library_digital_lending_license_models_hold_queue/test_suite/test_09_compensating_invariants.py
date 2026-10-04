"""Compensating invariants: approve/cancel ledger restore; circ grace restore."""
from test_helpers import (
    ADMIN,
    checkout,
    create_license_via_order,
    create_order,
    create_patron,
    make_library_admin_headers,
    make_patron_headers,
    propose_order,
    approve_order,
    set_clock,
    setup_base_with_title,
    validate_success,
)


def test_approve_then_cancel_restores_committed_ledger(api):
    """PRD §3.10: "Cancelling an `APPROVED` order performs the mirror-image
    compensation, subtracting its `estimated_cost_cents` from `committed_cents`
    and incrementing the fund's `version`."

    Design: Difficulty/compensating_invariant/approve_then_cancel_restores_available_committed
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    propose_order(lib["id"], order["id"])
    approve_order(lib["id"], order["id"])
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["committed_cents"] == 5000
    assert fund["available_committed_cents"] == 995000
    resp = api.cancel_order(order["id"], lib_admin)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["committed_cents"] == 0
    assert fund["available_committed_cents"] == 1000000, (
        "the compensating cancel restores the invariant with zero drift"
    )


def test_approve_then_cancel_never_touches_spent_ledger(api):
    """PRD §3.10: "cancelling from `DRAFT` or `PROPOSED` touches no money."
    PRD §3.10: "A successful approval adds the estimate to the fund's
    `committed_cents` and increments the fund's `version` by 1."

    Design: Difficulty/compensating_invariant/approve_then_cancel_restores_available_committed
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    propose_order(lib["id"], order["id"])
    approve_order(lib["id"], order["id"])
    api.cancel_order(order["id"], lib_admin)
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["spent_cents"] == 0, (
        "cancel never touches the actuals ledger"
    )


def _setup_metered_circ_license():
    ctx = setup_base_with_title()
    lib = ctx["library"]
    license_ = create_license_via_order(
        lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
        model="METERED_CIRC", invoiced_cost_cents=3000,
    )
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    ctx.update({"license": license_, "p0": p0, "p1": p1})
    return ctx


def test_grace_return_within_two_hours_restores_circ(api):
    """PRD §3.7: "for `METERED_CIRC` there is an accidental-checkout
    protection — if the return happens within 2 hours of `checkout_at`, the
    consumed circulation is restored, decrementing `circs_consumed` by 1."

    Design: Difficulty/compensating_invariant/circ_checkout_then_grace_return_restores_circs
    """
    ctx = _setup_metered_circ_license()
    lib_admin = make_library_admin_headers(ctx["library"]["id"])
    loan0 = checkout(ctx["p0"]["id"], ctx["title"]["id"])
    set_clock("2026-09-01T01:00:00Z")
    api.return_loan(loan0["id"], make_patron_headers(ctx["p0"]["id"]))
    lic = validate_success(api.get_license(ctx["license"]["id"], lib_admin))
    assert lic["circs_consumed"] == 0, (
        "return one hour after checkout must restore the circ stock"
    )
    assert lic["circs_consumed"] + (lic["circs_total"] - lic["circs_consumed"]) == 26


def test_return_outside_grace_window_keeps_circ_consumed(api):
    """PRD §3.7: "if the return happens within 2 hours of `checkout_at`, the
    consumed circulation is restored, decrementing `circs_consumed` by 1."

    Design: Difficulty/compensating_invariant/circ_checkout_then_grace_return_restores_circs
    """
    ctx = _setup_metered_circ_license()
    lib_admin = make_library_admin_headers(ctx["library"]["id"])
    loan0 = checkout(ctx["p0"]["id"], ctx["title"]["id"])
    set_clock("2026-09-01T01:00:00Z")
    api.return_loan(loan0["id"], make_patron_headers(ctx["p0"]["id"]))
    loan1 = checkout(ctx["p1"]["id"], ctx["title"]["id"])
    set_clock("2026-09-01T04:00:01Z")
    api.return_loan(loan1["id"], make_patron_headers(ctx["p1"]["id"]))
    lic = validate_success(api.get_license(ctx["license"]["id"], lib_admin))
    assert lic["circs_consumed"] == 1, (
        "3h 1s after checkout is outside the 2-hour grace window"
    )
    assert lic["status"] == "ACTIVE"
