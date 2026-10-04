"""Cross-entity state dependencies: renew vs hold queue; approve vs closed fund."""
from test_helpers import (
    ApiErrorId,
    checkout,
    create_patron,
    create_order,
    propose_order,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    setup_base_with_title,
    setup_ocou_library,
    validate_error,
    validate_success,
)


def test_renew_blocked_while_another_patron_holds_the_title(api):
    """PRD §3.7: "no hold on the title may exist in `PLACED`, `READY`, or
    `SUSPENDED` status by any patron (`ERR_RENEWAL_BLOCKED_BY_HOLDS` — queued
    demand always beats an extension)."

    Design: Difficulty/cross_entity_state_dependency/renew_blocked_by_other_patrons_hold
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    place_hold(p1["id"], ctx["title"]["id"])
    resp = api.renew_loan(loan0["id"], make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_RENEWAL_BLOCKED_BY_HOLDS)


def test_renew_succeeds_after_the_blocking_hold_is_cancelled(api):
    """PRD §3.7: "The extension is additive from the current due date, never
    from the renewal instant — renewing a week early still yields the same new
    due date as renewing on the last day."

    Design: Difficulty/cross_entity_state_dependency/renew_blocked_by_other_patrons_hold
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    h1 = place_hold(p1["id"], ctx["title"]["id"])
    assert loan0["due_at"] == "2026-09-22T00:00:00Z"
    resp = api.cancel_hold(h1["id"], make_patron_headers(p1["id"]))
    assert resp.status_code == 200, resp.text
    resp = api.renew_loan(loan0["id"], make_patron_headers(p0["id"]))
    loan = validate_success(resp)
    assert loan["renewals_used"] == 1
    assert loan["due_at"] == "2026-10-13T00:00:00Z", (
        f"additive from due date: 2026-09-22 + 21 days, got {loan['due_at']}"
    )


def test_approve_rejected_once_fund_is_closed(api):
    """PRD §3.10: "Approving sends `PROPOSED` → `APPROVED` and is where the
    fiscal gates bite, in the validation order of §2.9: the fund must be `OPEN`
    (`ERR_FUND_CLOSED`)."

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_closed_fund
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    propose_order(lib["id"], order["id"])
    resp = api.close_fund(ctx["fund"]["id"], make_library_admin_headers(lib["id"]))
    assert resp.status_code == 200, resp.text
    resp = api.approve_order(order["id"], make_library_admin_headers(lib["id"]))
    validate_error(resp, ApiErrorId.ERR_FUND_CLOSED)


def test_approve_blocked_by_closed_fund_leaves_state_unchanged(api):
    """PRD §3.10: "Closing moves `OPEN` → `CLOSED` but is blocked while any
    order on the fund remains `APPROVED` — those are live commitments."

    Design: Difficulty/cross_entity_state_dependency/approve_blocked_by_closed_fund
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    propose_order(lib["id"], order["id"])
    api.close_fund(ctx["fund"]["id"], lib_admin)
    resp = api.approve_order(order["id"], lib_admin)
    validate_error(resp, ApiErrorId.ERR_FUND_CLOSED)
    fresh = validate_success(api.get_order(order["id"], lib_admin))
    assert fresh["status"] == "PROPOSED"
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["committed_cents"] == 0
