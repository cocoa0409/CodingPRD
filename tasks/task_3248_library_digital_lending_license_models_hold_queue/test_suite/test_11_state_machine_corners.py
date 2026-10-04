"""Corner coverage: state machine transitions and their side effects."""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    checkout,
    create_license_via_order,
    create_library,
    create_fund,
    create_order,
    create_patron,
    create_title,
    fulfill_order,
    propose_order,
    approve_order,
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


def test_hold_cancel_from_fulfilled_returns_hold_not_actionable(api):
    """PRD §3.4: "A hold in a state where the requested transition is not
    defined is rejected with `ERR_HOLD_NOT_ACTIONABLE`."
    PRD §3.4: "Whichever branch, the hold lands in `CANCELLED` and cannot leave
    it; `FULFILLED`, `EXPIRED`, and `CANCELLED` are the hold's terminal
    states."

    Design: Corner/state_machines/hold_cancel_from_fulfilled_returns_hold_not_actionable
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    hold1 = place_hold(p1["id"], ctx["title"]["id"])
    api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    resp = api.claim_hold(hold1["id"], make_patron_headers(p1["id"]))
    assert resp.status_code == 201, resp.text
    resp = api.cancel_hold(hold1["id"], make_patron_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_HOLD_NOT_ACTIONABLE)
    hold = validate_success(api.get_hold(hold1["id"], make_patron_headers(p1["id"])))
    assert hold["status"] == "FULFILLED"
    patron = validate_success(api.get_patron(p1["id"], make_patron_headers(p1["id"])))
    assert patron["active_hold_count"] == 0, (
        "the rejected cancel must not double-decrement the counter"
    )


def test_order_fulfill_from_draft_returns_order_invalid_state(api):
    """PRD §3.10: "Any order-state transition attempted from a state where it
    is not defined is rejected with `ERR_ORDER_INVALID_STATE`."

    Design: Corner/state_machines/order_fulfill_from_draft_returns_order_invalid_state
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    resp = api.fulfill_order(order["id"], {"invoiced_cost_cents": 5000}, lib_admin)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE)
    fresh = validate_success(api.get_order(order["id"], lib_admin))
    assert fresh["status"] == "DRAFT"
    licenses, _ = validate_paginated(
        api.list_licenses(lib_admin, params={"title_id": ctx["title"]["id"]})
    )
    assert len(licenses) == 0
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["spent_cents"] == 0


def test_patron_expiry_at_epoch_cascades_to_ready_holds(api):
    """PRD §3.3: "every one of the patron's `PLACED` or `SUSPENDED` holds is
    cancelled outright (with no copy release and no promotion, since those
    holds held no copy), and every `READY` hold moves to `EXPIRED`, releasing
    its reserved copy and triggering hold promotion for the affected title."

    Design: Corner/state_machines/patron_expiry_at_epoch_cascades_to_ready_holds
    """
    ctx = setup_base(library_overrides={"card_validity_days": 1,
                                        "pickup_window_hours": 72})
    lib = ctx["library"]
    title = create_title(ctx["consortium"]["id"])
    create_license_via_order(lib["id"], ctx["fund"]["id"], title["id"],
                             model="OCOU", copies=1)
    p0 = create_patron(lib["id"], external_card_number="F-0", full_name="Fast Zero")
    p1 = create_patron(lib["id"], external_card_number="F-1", full_name="Fast One")
    loan0 = checkout(p0["id"], title["id"])
    hold1 = place_hold(p1["id"], title["id"])
    # P2 is registered a day later so their card survives the epoch — the
    # cascade's re-promotion needs one living PLACED hold to land on. With
    # the original 1-day card for P2 the epoch would expire P2's card too,
    # making the asserted READY outcome unreachable under the PRD's own
    # card-expiry rule.
    set_clock("2026-09-02T00:00:00Z")
    p2 = create_patron(lib["id"], external_card_number="F-2", full_name="Fast Two")
    set_clock("2026-09-01T00:00:00Z")
    hold2 = place_hold(p2["id"], title["id"])
    api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    set_clock("2026-09-02T00:00:00Z")
    api.run_epoch(ADMIN)
    patron1 = validate_success(api.get_patron(p1["id"], make_patron_headers(p1["id"])))
    assert patron1["status"] == "EXPIRED"
    h1 = validate_success(api.get_hold(hold1["id"], make_patron_headers(p1["id"])))
    assert h1["status"] == "EXPIRED", (
        "the READY hold of the expired patron is expired by cascade"
    )
    h2 = validate_success(api.get_hold(hold2["id"], make_patron_headers(p2["id"])))
    assert h2["status"] == "READY"
    assert h2["ready_since"] == "2026-09-02T00:00:00Z"
    events1, _ = validate_paginated(
        api.list_hold_events(hold1["id"], ANALYST, params={"event_type": "HOLD_EXPIRED"})
    )
    events2, _ = validate_paginated(
        api.list_hold_events(hold2["id"], ANALYST, params={"event_type": "HOLD_READY"})
    )
    assert len(events1) == 1 and len(events2) == 1


def test_metered_circ_exhaustion_retires_license_at_epoch(api):
    """PRD §3.8: "a `METERED_CIRC` license whose `circs_consumed` has reached
    `circs_total`, or a `COST_PER_CIRC` license whose `balance_cents` has
    fallen below one discounted per-circulation charge, moves `ACTIVE` →
    `EXHAUSTED`."
    PRD §3.5: "If no eligible license exists, the checkout fails with
    `ERR_NO_LICENSE_AVAILABLE`."

    Design: Corner/state_machines/metered_circ_exhaustion_retires_license_at_epoch
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    license_ = create_license_via_order(
        lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
        model="METERED_CIRC", invoiced_cost_cents=3000,
    )
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    lib_admin = make_library_admin_headers(lib["id"])
    resp = api.drive_circulation(
        {"title_id": ctx["title"]["id"],
         "by_library": [{"library_id": lib["id"], "patron_id": p0["id"],
                         "checkouts": 26}]},
        ADMIN,
    )
    assert resp.status_code == 200, resp.text
    lic = validate_success(api.get_license(license_["id"], lib_admin))
    assert lic["status"] == "ACTIVE"
    assert lic["circs_consumed"] == 26 == lic["circs_total"]
    epoch = validate_success(api.run_epoch(ADMIN))
    assert epoch["exhausted_licenses"] >= 1
    lic = validate_success(api.get_license(license_["id"], lib_admin))
    assert lic["status"] == "EXHAUSTED"
    resp = api.checkout({"patron_id": p0["id"], "title_id": ctx["title"]["id"]},
                        make_patron_headers(p0["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_LICENSE_AVAILABLE)


def test_renew_uses_additive_due_date_not_from_now(api):
    """PRD §3.7: "The extension is additive from the current due date, never
    from the renewal instant — renewing a week early still yields the same new
    due date as renewing on the last day."

    Design: Corner/state_machines/renew_uses_additive_due_date_not_from_now
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    assert loan0["due_at"] == "2026-09-22T00:00:00Z"
    set_clock("2026-09-11T00:00:00Z")
    resp = api.renew_loan(loan0["id"], make_patron_headers(p0["id"]))
    loan = validate_success(resp)
    assert loan["due_at"] == "2026-10-13T00:00:00Z", (
        f"due 2026-09-22 + 21 days, got {loan['due_at']}"
    )
    assert loan["due_at"] != "2026-10-02T00:00:00Z"
    assert loan["renewals_used"] == 1
    assert loan["status"] == "ACTIVE"


def test_skip_the_line_bypasses_queue_with_short_nonrenewable_loan(api):
    """PRD §3.5: "The only exception is the skip-the-line path: when the
    request sets `skip_the_line` true, the hold-queue block does not apply, but
    the title must have `skip_the_line_enabled` or the request fails with
    `ERR_SKIP_THE_LINE_DISABLED`. A skip-the-line loan is flagged
    `is_skip_the_line` true, runs for the library's `skip_the_line_loan_days`
    instead of the standard period, and can never be renewed."

    Design: Corner/state_machines/skip_the_line_bypasses_queue_with_short_nonrenewable_loan
    """
    ctx = setup_base_with_title(title_overrides={"skip_the_line_enabled": True})
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="OCOU", copies=2, invoiced_cost_cents=10000)
    patrons = [create_patron(lib["id"], external_card_number=f"P-{i}",
                             full_name=f"P{i}") for i in range(5)]
    checkout(patrons[0]["id"], ctx["title"]["id"])
    for p in patrons[1:4]:
        place_hold(p["id"], ctx["title"]["id"])
    resp = api.checkout(
        {"patron_id": patrons[4]["id"], "title_id": ctx["title"]["id"],
         "skip_the_line": True},
        make_patron_headers(patrons[4]["id"]),
    )
    loan = validate_success(resp, expected_status=201)
    assert loan["is_skip_the_line"] is True
    assert loan["due_at"] == "2026-09-08T00:00:00Z", (
        f"7 days, not 21, got {loan['due_at']}"
    )
    resp = api.renew_loan(loan["id"], make_patron_headers(patrons[4]["id"]))
    validate_error(resp, ApiErrorId.ERR_RENEWAL_LIMIT_REACHED)
    holds, _ = validate_paginated(
        api.list_holds(ANALYST, params={"title_id": ctx["title"]["id"],
                                        "status": "PLACED"})
    )
    assert len(holds) == 3, "skip-the-line must not disturb the queue"


def test_hold_ready_expiry_at_pickup_window_boundary(api):
    """PRD §3.4: "A ready hold that is never claimed lapses at the epoch: when
    `ready_until` has been reached, the hold moves `READY` → `EXPIRED`, the
    reserved copy is released and the promotion selector immediately re-runs
    for that title."
    PRD §3.5: "a claim attempted after `ready_until` is rejected with
    `ERR_HOLD_NOT_ACTIONABLE`, since the hold is epoch-expirable."

    Design: Corner/state_machines/hold_ready_expiry_at_pickup_window_boundary
    """
    ctx = setup_ocou_library(copies=1)
    lib = ctx["library"]
    p0 = create_patron(lib["id"], external_card_number="P-0", full_name="Patron Zero")
    p1 = create_patron(lib["id"], external_card_number="P-1", full_name="Patron One")
    p2 = create_patron(lib["id"], external_card_number="P-2", full_name="Patron Two")
    loan0 = checkout(p0["id"], ctx["title"]["id"])
    hold1 = place_hold(p1["id"], ctx["title"]["id"])
    hold2 = place_hold(p2["id"], ctx["title"]["id"])
    api.return_loan(loan0["id"], make_patron_headers(p0["id"]))
    set_clock("2026-09-04T00:00:00Z")
    api.run_epoch(ADMIN)
    h1 = validate_success(api.get_hold(hold1["id"], make_patron_headers(p1["id"])))
    assert h1["status"] == "EXPIRED"
    h2 = validate_success(api.get_hold(hold2["id"], make_patron_headers(p2["id"])))
    assert h2["status"] == "READY"
    assert h2["ready_since"] == "2026-09-04T00:00:00Z"
    resp = api.claim_hold(hold1["id"], make_patron_headers(p1["id"]))
    validate_error(resp, ApiErrorId.ERR_HOLD_NOT_ACTIONABLE)


def test_order_revise_recompute_then_reapprove_cycle(api):
    """PRD §3.10: "revising sends `REJECTED` → `DRAFT` and may simultaneously
    change the `model`, `copies`, or `prepaid_balance_cents`, in which case
    `estimated_cost_cents` is recomputed."
    PRD §3.10: "A successful approval adds the estimate to the fund's
    `committed_cents` and increments the fund's `version` by 1."

    Design: Corner/state_machines/order_revise_recompute_then_reapprove_cycle
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                         model="OCOU", copies=1)
    propose_order(lib["id"], order["id"])
    resp = api.reject_order(order["id"], lib_admin)
    assert resp.status_code == 200, resp.text
    resp = api.revise_order(order["id"], {"model": "METERED_TIME"}, lib_admin)
    revised = validate_success(resp)
    assert revised["status"] == "DRAFT"
    assert revised["model"] == "METERED_TIME"
    assert revised["estimated_cost_cents"] == 4000, (
        f"recomputed from the metered-time price, got {revised['estimated_cost_cents']}"
    )
    propose_order(lib["id"], order["id"])
    approved = approve_order(lib["id"], order["id"])
    assert approved["status"] == "APPROVED"
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["committed_cents"] == 4000


def test_fund_close_blocked_with_open_commitments(api):
    """PRD §3.10: "Closing moves `OPEN` → `CLOSED` but is blocked while any
    order on the fund remains `APPROVED` — those are live commitments —
    surfacing `ERR_FUND_HAS_OPEN_COMMITMENTS`."

    Design: Corner/state_machines/fund_close_blocked_with_open_commitments
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"])
    propose_order(lib["id"], order["id"])
    approve_order(lib["id"], order["id"])
    resp = api.close_fund(ctx["fund"]["id"], lib_admin)
    validate_error(resp, ApiErrorId.ERR_FUND_HAS_OPEN_COMMITMENTS)
    resp = api.cancel_order(order["id"], lib_admin)
    assert resp.status_code == 200, resp.text
    resp = api.close_fund(ctx["fund"]["id"], lib_admin)
    fund = validate_success(resp)
    assert fund["status"] == "CLOSED"
