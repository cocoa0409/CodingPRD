"""Corner coverage: error catalog paths not exercised elsewhere."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    NON_EXISTENT_UUID,
    checkout,
    create_consortium,
    create_library,
    create_fund,
    create_license_via_order,
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
    validate_error,
    validate_paginated,
    validate_success,
)


def test_error_hold_not_found(api):
    """PRD §2.9: "Fourth, path-template identifiers resolve, validated
    left-to-right (consortium before library before the child resource) with
    the corresponding not-found error (`ERR_NOT_FOUND` generically, or the
    entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/errors/error_hold_not_found
    """
    ctx = setup_base()
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    resp = api.get_hold(NON_EXISTENT_UUID, make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_HOLD_NOT_FOUND)


def test_error_loan_not_found(api):
    """PRD §2.9: "Fourth, path-template identifiers resolve, validated
    left-to-right (consortium before library before the child resource) with
    the corresponding not-found error (`ERR_NOT_FOUND` generically, or the
    entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/errors/error_loan_not_found
    """
    setup_base()
    resp = api.get_loan(NON_EXISTENT_UUID, ANALYST)
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_FOUND)


def test_error_order_not_found(api):
    """PRD §2.9: "Fourth, path-template identifiers resolve, validated
    left-to-right (consortium before library before the child resource) with
    the corresponding not-found error (`ERR_NOT_FOUND` generically, or the
    entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/errors/error_order_not_found
    """
    setup_base()
    resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_error_fund_not_found(api):
    """PRD §2.9: "Fourth, path-template identifiers resolve, validated
    left-to-right (consortium before library before the child resource) with
    the corresponding not-found error (`ERR_NOT_FOUND` generically, or the
    entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/errors/error_fund_not_found
    """
    setup_base()
    resp = api.get_fund(NON_EXISTENT_UUID, ANALYST)
    validate_error(resp, ApiErrorId.ERR_FUND_NOT_FOUND)


def test_error_invoice_not_found(api):
    """PRD §2.9: "Fourth, path-template identifiers resolve, validated
    left-to-right (consortium before library before the child resource) with
    the corresponding not-found error (`ERR_NOT_FOUND` generically, or the
    entity-specific `ERR_LIBRARY_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`,
    `ERR_TITLE_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_FUND_NOT_FOUND`,
    `ERR_INVOICE_NOT_FOUND`)."

    Design: Corner/errors/error_invoice_not_found
    """
    create_consortium()
    resp = api.get_invoice(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)


def test_error_skip_the_line_disabled(api):
    """PRD §3.5: "The only exception is the skip-the-line path: when the
    request sets `skip_the_line` true, the hold-queue block does not apply, but
    the title must have `skip_the_line_enabled` or the request fails with
    `ERR_SKIP_THE_LINE_DISABLED`."

    Design: Corner/errors/error_skip_the_line_disabled
    """
    ctx = setup_ocou_library(copies=1)
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    resp = api.checkout(
        {"patron_id": p0["id"], "title_id": ctx["title"]["id"],
         "skip_the_line": True},
        make_patron_headers(p0["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SKIP_THE_LINE_DISABLED)


def test_error_simultaneous_use_not_allowed(api):
    """PRD §3.10: "An order whose `model` is `SIMULTANEOUS_USE` is only valid
    on a title with `simultaneous_use_allowed`, else
    `ERR_SIMULTANEOUS_USE_NOT_ALLOWED`."

    Design: Corner/errors/error_simultaneous_use_not_allowed
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    resp = api.create_order(
        {"library_id": lib["id"], "budget_fund_id": ctx["fund"]["id"],
         "title_id": ctx["title"]["id"], "model": "SIMULTANEOUS_USE",
         "expected_budget_fund_version": ctx["fund"]["version"]},
        make_library_admin_headers(lib["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SIMULTANEOUS_USE_NOT_ALLOWED)


def test_error_license_in_use_on_retire(api):
    """PRD §3.8: "A `LibraryAdmin` may also retire a license outright — moving
    it `ACTIVE` → `RETIRED` — provided no `ACTIVE` loans remain against it
    (else `ERR_LICENSE_IN_USE`) and the caller's identity matches the license's
    `library_id`."

    Design: Corner/errors/error_license_in_use_on_retire
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    resp = api.retire_license(ctx["license"]["id"], lib_admin)
    validate_error(resp, ApiErrorId.ERR_LICENSE_IN_USE)
    api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    resp = api.retire_license(ctx["license"]["id"], lib_admin)
    lic = validate_success(resp)
    assert lic["status"] == "RETIRED"


def test_error_invoice_invalid_state_on_settle_from_draft(api):
    """PRD §3.12: "Any invoice transition attempted from a state where it is
    not defined is rejected with `ERR_INVOICE_INVALID_STATE`."

    Design: Corner/errors/error_invoice_invalid_state_on_settle_from_draft
    """
    ctx = setup_base()
    resp = api.generate_invoice(
        ctx["consortium"]["id"],
        {"period_start": "2026-09-01T00:00:00Z",
         "period_end": "2026-10-01T00:00:00Z"},
        ADMIN,
    )
    invoice = get_success_data(resp)
    resp = api.settle_invoice(invoice["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVOICE_INVALID_STATE)
    fresh = validate_success(api.get_invoice(invoice["id"], ADMIN))
    assert fresh["status"] == "DRAFT"


def test_error_card_expired_at_checkout(api):
    """PRD §3.5: "Every checkout also enforces the borrowing patron's standing:
    the card must be `ACTIVE` (`ERR_PATRON_NOT_ACTIVE`) and unexpired
    (`ERR_CARD_EXPIRED`)."

    Design: Corner/errors/error_card_expired_at_checkout
    """
    ctx = setup_base(library_overrides={"card_validity_days": 1})
    lib = ctx["library"]
    title = create_title(ctx["consortium"]["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], title["id"],
                             model="OCOU", copies=1)
    p0 = create_patron(lib["id"], external_card_number="X-0",
                       full_name="Expiring Patron")
    set_clock("2026-09-03T00:00:00Z")
    patron = validate_success(api.get_patron(p0["id"], make_patron_headers(p0["id"])))
    assert patron["status"] == "ACTIVE", "no epoch ran, so the flag is stale"
    resp = api.checkout({"patron_id": p0["id"], "title_id": title["id"]},
                        make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_CARD_EXPIRED)


def test_error_stale_fund_version_occ(api):
    """PRD §2.10: "If the fund's current `version` has advanced since that
    observation — because order creation itself, approvals, fulfillments,
    cancellations of approved orders, and auto-purchase sweeps all increment
    the fund's version — the create is rejected with `ERR_STALE_FUND_VERSION`
    (HTTP 412)."

    Design: Corner/errors/error_stale_fund_version_occ
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    title2 = create_title(ctx["consortium"]["id"])
    from test_helpers import create_order as _create_order
    _create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    stale_version = ctx["fund"]["version"]
    resp = api.create_order(
        {"library_id": lib["id"], "budget_fund_id": ctx["fund"]["id"],
         "title_id": title2["id"], "model": "OCOU", "copies": 1,
         "expected_budget_fund_version": stale_version},
        lib_admin,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FUND_VERSION)
    current = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    resp = api.create_order(
        {"library_id": lib["id"], "budget_fund_id": ctx["fund"]["id"],
         "title_id": title2["id"], "model": "OCOU", "copies": 1,
         "expected_budget_fund_version": current["version"]},
        lib_admin,
    )
    ok = validate_success(resp, expected_status=201)
    assert ok["id"]
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["version"] == ctx["fund"]["version"] + 2, (
        "version advances by exactly 1 per successful order create"
    )


def test_error_stale_library_version_occ(api):
    """PRD §2.10: "Updating a library's policy configuration requires the
    request to carry `expected_library_version`, holding the client's
    last-observed `version` of the Library; a mismatch with the library's
    current `version` is rejected with `ERR_STALE_LIBRARY_VERSION` (HTTP 412)."

    Design: Corner/errors/error_stale_library_version_occ
    """
    set_clock()
    consortium = create_consortium()
    library = create_library(consortium["id"])
    lib_admin = make_library_admin_headers(library["id"])
    resp = api.update_library(
        library["id"],
        {"expected_library_version": library["version"], "wait_target_days": 30},
        lib_admin,
    )
    assert resp.status_code == 200, resp.text
    resp = api.update_library(
        library["id"],
        {"expected_library_version": library["version"],
         "max_concurrent_loans": 5},
        lib_admin,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LIBRARY_VERSION)
    fresh = validate_success(api.get_library(library["id"], lib_admin))
    assert fresh["max_concurrent_loans"] == 10, "the stale PATCH applies nothing"
    assert fresh["wait_target_days"] == 30, "the first PATCH is kept"


def test_error_duplicate_loan_same_patron_title(api):
    """PRD §3.5: "the patron must not already hold an `ACTIVE` loan on the same
    title (`ERR_DUPLICATE_LOAN`)."

    Design: Corner/errors/error_duplicate_loan_same_patron_title
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=2, invoiced_cost_cents=10000)
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    checkout(p0["id"], ctx["title"]["id"])
    resp = api.checkout({"patron_id": p0["id"], "title_id": ctx["title"]["id"]},
                        make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LOAN)
    patron = validate_success(api.get_patron(p0["id"], make_patron_headers(p0["id"])))
    assert patron["active_loan_count"] == 1


def test_error_loan_not_active_on_double_return(api):
    """PRD §3.7: "A return attempted on a loan that is not `ACTIVE` is rejected
    with `ERR_LOAN_NOT_ACTIVE`."

    Design: Corner/errors/error_loan_not_active_on_double_return
    """
    ctx = setup_ocou_library(copies=1)
    p0 = create_patron(ctx["library"]["id"], external_card_number="P-0",
                       full_name="Patron Zero")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    resp = api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    assert resp.status_code == 200, resp.text
    resp = api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)
    patron = validate_success(api.get_patron(p0["id"], make_patron_headers(p0["id"])))
    assert patron["active_loan_count"] == 0, "no double decrement"


def test_error_hold_limit_exceeded(api):
    """PRD §3.4: "Placement is refused when the patron's card is not `ACTIVE`
    (`ERR_PATRON_NOT_ACTIVE`), when the card has expired (`ERR_CARD_EXPIRED`),
    when the patron already holds `max_concurrent_holds` active queue positions
    (`ERR_HOLD_LIMIT_EXCEEDED`), or when the same patron already has a hold in
    `PLACED`, `READY`, or `SUSPENDED` on that title (`ERR_DUPLICATE_HOLD`)."

    Design: Corner/errors/error_hold_limit_exceeded
    """
    ctx = setup_base(library_overrides={"max_concurrent_holds": 1})
    lib = ctx["library"]
    t1 = create_title(ctx["consortium"]["id"])
    t2 = create_title(ctx["consortium"]["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], t1["id"],
                             model="OCOU", copies=1)
    create_license_via_order(lib["id"], ctx["fund"]["id"], t2["id"],
                             model="OCOU", copies=1)
    holder = create_patron(lib["id"], external_card_number="H-0", full_name="Holder")
    other = create_patron(lib["id"], external_card_number="H-9", full_name="Other")
    checkout(other["id"], t1["id"])
    checkout(other["id"], t2["id"])
    place_hold(holder["id"], t1["id"])
    resp = api.place_hold({"patron_id": holder["id"], "title_id": t2["id"]},
                          make_patron_headers(holder["id"]))
    validate_error(resp, ApiErrorId.ERR_HOLD_LIMIT_EXCEEDED)
    patron = validate_success(
        api.get_patron(holder["id"], make_patron_headers(holder["id"]))
    )
    assert patron["active_hold_count"] == 1
