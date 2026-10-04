"""Corner coverage: business-rule violations mapped to their error IDs."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    checkout,
    create_fund,
    create_license_via_order,
    create_order,
    create_patron,
    create_title,
    fund_version,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    propose_order,
    approve_order,
    setup_base,
    setup_base_with_title,
    setup_ocou_library,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_checkout_blocked_by_existing_hold_queue(api):
    """PRD §3.5: "Direct checkout is gated hard against queue-jumping: while
    any hold on the title exists in `PLACED`, `READY`, or `SUSPENDED` —
    anyone's hold, from any library in scope — a plain direct checkout is
    rejected with `ERR_CHECKOUT_BLOCKED_BY_HOLDS`."

    Design: Corner/validations/checkout_blocked_by_existing_hold_queue
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=2, invoiced_cost_cents=10000)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    p2 = create_patron(lib["id"], external_card_number="P-2", full_name="Patron Two")
    checkout(p0["id"], ctx["title"]["id"])
    place_hold(p1["id"], ctx["title"]["id"])
    resp = api.checkout({"patron_id": p2["id"], "title_id": ctx["title"]["id"]},
                        make_patron_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_CHECKOUT_BLOCKED_BY_HOLDS)
    patron = validate_success(api.get_patron(p2["id"], make_patron_headers(p2["id"])))
    assert patron["active_loan_count"] == 0


def test_duplicate_hold_same_patron_title_rejected(api):
    """PRD §3.4: "Placement is refused when the patron's card is not `ACTIVE`
    (`ERR_PATRON_NOT_ACTIVE`), when the card has expired (`ERR_CARD_EXPIRED`),
    when the patron already holds `max_concurrent_holds` active queue positions
    (`ERR_HOLD_LIMIT_EXCEEDED`), or when the same patron already has a hold in
    `PLACED`, `READY`, or `SUSPENDED` on that title (`ERR_DUPLICATE_HOLD`)."

    Design: Corner/validations/duplicate_hold_same_patron_title_rejected
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    checkout(p0["id"], ctx["title"]["id"])
    hold1 = place_hold(p1["id"], ctx["title"]["id"])
    resp = api.place_hold({"patron_id": p1["id"], "title_id": ctx["title"]["id"]},
                          make_patron_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_HOLD)
    resp = api.cancel_hold(hold1["id"], make_patron_headers(p1["id"]))
    assert resp.status_code == 200, resp.text
    resp = api.place_hold({"patron_id": p1["id"], "title_id": ctx["title"]["id"]},
                          make_patron_headers(p1["id"]))
    hold1b = validate_success(resp, expected_status=201)
    assert hold1b["id"] != hold1["id"]
    patron = validate_success(api.get_patron(p1["id"], make_patron_headers(p1["id"])))
    assert patron["active_hold_count"] == 1


def test_loan_cap_enforced_at_checkout(api):
    """PRD §3.5: "the patron's `active_loan_count` must be below the library's
    `max_concurrent_loans` (`ERR_LOAN_LIMIT_EXCEEDED`)."

    Design: Corner/validations/loan_cap_enforced_at_checkout
    """
    ctx = setup_base(library_overrides={"max_concurrent_loans": 2})
    lib = ctx["library"]
    titles = [create_title(ctx["consortium"]["id"]) for _ in range(3)]
    for t in titles:
        create_license_via_order(lib["id"], ctx["fund"]["id"], t["id"],
                                 model="OCOU", copies=1)
    p0 = create_patron(lib["id"], external_card_number="C-0", full_name="Cap Zero")
    checkout(p0["id"], titles[0]["id"])
    checkout(p0["id"], titles[1]["id"])
    resp = api.checkout({"patron_id": p0["id"], "title_id": titles[2]["id"]},
                        make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_LOAN_LIMIT_EXCEEDED)
    patron = validate_success(api.get_patron(p0["id"], make_patron_headers(p0["id"])))
    assert patron["active_loan_count"] == 2


def test_renew_beyond_metered_time_license_term_rejected(api):
    """PRD §3.7: "for `METERED_TIME` and `SIMULTANEOUS_USE` licenses the
    extended due date must not run past the license's `expires_at`
    (`ERR_RENEWAL_BEYOND_LICENSE_TERM`)."

    Design: Corner/validations/renew_beyond_metered_time_license_term_rejected
    """
    ctx = setup_base_with_title(title_overrides={"metered_time_days": 30})
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="METERED_TIME", invoiced_cost_cents=4000)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    assert loan0["due_at"] == "2026-09-22T00:00:00Z"
    resp = api.renew_loan(loan0["id"], make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_RENEWAL_BEYOND_LICENSE_TERM)
    loan = validate_success(api.get_loan(loan0["id"], make_patron_headers(p0["id"])))
    assert loan["due_at"] == "2026-09-22T00:00:00Z"
    assert loan["renewals_used"] == 0


def test_order_create_with_body_fk_unknown_returns_reference_not_found(api):
    """PRD §2.9: "Fifth, body-supplied foreign keys — `library_id`,
    `budget_fund_id`, `title_id`, `patron_id` — must resolve to existing
    entities, else `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/order_create_with_body_fk_unknown_returns_reference_not_found
    """
    ctx = setup_base()
    lib = ctx["library"]
    resp = api.create_order(
        {"library_id": lib["id"], "budget_fund_id": ctx["fund"]["id"],
         "title_id": NON_EXISTENT_UUID, "model": "OCOU", "copies": 1,
         "expected_budget_fund_version": ctx["fund"]["version"]},
        make_library_admin_headers(lib["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


def test_budget_exceeded_at_approval_when_committed_variant_negative(api):
    """PRD §3.10: "the order's `estimated_cost_cents` must not exceed the
    fund's `available_committed_cents` (`ERR_BUDGET_EXCEEDED`)."

    Design: Corner/validations/budget_exceeded_at_approval_when_committed_variant_negative
    """
    ctx = setup_base(fund_overrides={"budget_cents": 10000})
    lib = ctx["library"]
    title1 = create_title(ctx["consortium"]["id"], price_ocou_cents=5000)
    title2 = create_title(ctx["consortium"]["id"], price_ocou_cents=6000)
    order1 = create_order(lib["id"], ctx["fund"]["id"], title1["id"],
                          model="OCOU", copies=1)
    propose_order(lib["id"], order1["id"])
    approve_order(lib["id"], order1["id"])
    order2 = create_order(lib["id"], ctx["fund"]["id"], title2["id"],
                          model="OCOU", copies=1)
    propose_order(lib["id"], order2["id"])
    resp = api.approve_order(order2["id"], make_library_admin_headers(lib["id"]))
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
    lib_admin = make_library_admin_headers(lib["id"])
    fresh = validate_success(api.get_order(order2["id"], lib_admin))
    assert fresh["status"] == "PROPOSED"
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["committed_cents"] == 5000
