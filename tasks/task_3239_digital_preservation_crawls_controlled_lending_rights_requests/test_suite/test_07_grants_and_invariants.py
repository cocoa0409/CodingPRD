"""Funding-grant depth: evaluation ordering, OPEN/EXHAUSTED cycle, boundary,
and compensating invariants."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data,
    ApiErrorId, TEST_USERS, make_patron_headers,
    set_clock,
    make_grant, make_budget_line, get_grant,
    setup_work_with_lendable_items, make_patron, checkout, get_patron, get_item,
    get_loan,
)

FINANCE = TEST_USERS["finance_admin_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_grant_settlement_reverse_ordering_balance_blocks_over_limit():
    """PRD 3.9: "if the grant's current utilization — the sum of
    `reserved_cents` and `spent_cents` — plus the new reservation would be
    strictly greater than `amount_cents`, the line is rejected with
    `ERR_GRANT_EXHAUSTED`. Equality is allowed, and it matters: a reservation
    that brings utilization exactly to `amount_cents` flips the grant from
    `OPEN` to `EXHAUSTED`."

    Design: Difficulty/combinatorial_formula/grant_settlement_reverse_ordering_balance
    """
    grant = make_grant(amount_cents=100000, donor_name="Mellon")
    line1 = make_budget_line(grant["id"], 100000, "STORAGE")
    grant_now = get_grant(grant["id"])
    assert grant_now["reserved_cents"] == 100000
    assert grant_now["status"] == "EXHAUSTED"

    resp = api_client.create_budget_line(
        {"grant_id": grant["id"], "category": "BANDWIDTH",
         "budget_reservation_cents": 1},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_EXHAUSTED)


def test_grant_settlement_reverse_ordering_balance_reopens_after_settle():
    """PRD 3.9: "its status is recomputed — a settle for less than the
    reservation can drop an `EXHAUSTED` grant back to `OPEN`"

    Design: Difficulty/combinatorial_formula/grant_settlement_reverse_ordering_balance
    """
    grant = make_grant(amount_cents=100000, donor_name="Mellon")
    line1 = make_budget_line(grant["id"], 100000, "STORAGE")
    version = get_grant(grant["id"])["version"]

    validate_success(api_client.settle_budget_line(
        line1["id"],
        {"actual_spend_cents": 80000, "expected_grant_version": version},
        FINANCE,
    ))
    grant_now = get_grant(grant["id"])
    assert grant_now["reserved_cents"] == 0
    assert grant_now["spent_cents"] == 80000
    assert grant_now["status"] == "OPEN"

    # now exactly 20000 of headroom remains: reserve it all and re-exhaust
    line2 = make_budget_line(grant["id"], 20000, "SCAN_LABOR")
    assert get_grant(grant["id"])["status"] == "EXHAUSTED"

    resp = api_client.create_budget_line(
        {"grant_id": grant["id"], "category": "PETABYTE_INSURANCE",
         "budget_reservation_cents": 1},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_EXHAUSTED)


def test_funding_grant_open_exhausted_cycle_release_reopens():
    """PRD 3.9: "Release is the quieter twin: releasing an `OPEN` line requires
    only `expected_grant_version`, moves the line to `RELEASED`, subtracts the
    reservation from `reserved_cents`, recomputes the grant's status — which
    can likewise cycle an `EXHAUSTED` grant back to `OPEN` — and increments the
    grant's `version`."

    Design: Difficulty/non_linear_state_machine/funding_grant_open_exhausted_cycle
    """
    grant = make_grant(amount_cents=50000, donor_name="Ford")
    v0 = grant["version"]
    line3 = make_budget_line(grant["id"], 30000, "STORAGE")
    line4 = make_budget_line(grant["id"], 20000, "BANDWIDTH")
    grant_now = get_grant(grant["id"])
    assert grant_now["status"] == "EXHAUSTED"
    assert grant_now["version"] == v0 + 2

    released = validate_success(api_client.release_budget_line(
        line4["id"],
        {"expected_grant_version": grant_now["version"]},
        FINANCE,
    ))
    assert released["status"] == "RELEASED"
    grant_after = get_grant(grant["id"])
    assert grant_after["status"] == "OPEN"
    assert grant_after["reserved_cents"] == 30000
    assert grant_after["version"] == v0 + 3


def test_funding_grant_open_exhausted_cycle_released_line_contributes_nothing():
    """PRD 3.9: "`reserved_cents` is the sum of `budget_reservation_cents` over
    the grant's lines in `OPEN` status; `spent_cents` is the sum of
    `actual_spend_cents` over lines in `SETTLED`; a `RELEASED` line contributes
    nothing to either."

    Design: Difficulty/non_linear_state_machine/funding_grant_open_exhausted_cycle
    """
    grant = make_grant(amount_cents=50000, donor_name="Ford")
    line3 = make_budget_line(grant["id"], 30000, "STORAGE")
    line4 = make_budget_line(grant["id"], 20000, "BANDWIDTH")
    version = get_grant(grant["id"])["version"]
    validate_success(api_client.release_budget_line(
        line4["id"], {"expected_grant_version": version}, FINANCE
    ))
    grant_after = get_grant(grant["id"])
    # the released 20000 line contributes nothing: utilization is 30000, not 50000
    assert grant_after["reserved_cents"] + grant_after["spent_cents"] == 30000
    # so a further 20000 reservation fits exactly and re-exhausts
    line5 = make_budget_line(grant["id"], 20000, "SCAN_LABOR")
    assert get_grant(grant["id"])["status"] == "EXHAUSTED"

def test_grant_utilization_equality_boundary_allowed_and_flips_status():
    """PRD 3.9: "Equality is allowed, and it matters: a reservation that brings
    utilization exactly to `amount_cents` flips the grant from `OPEN` to
    `EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/grant_utilization_equality_boundary
    """
    grant = make_grant(amount_cents=7777, donor_name="Sloan")
    line = make_budget_line(grant["id"], 7777, "STORAGE")
    assert line["status"] == "OPEN"
    grant_now = get_grant(grant["id"])
    assert grant_now["status"] == "EXHAUSTED"
    assert grant_now["reserved_cents"] == 7777
    assert grant_now["spent_cents"] == 0


def test_grant_utilization_equality_boundary_one_cent_over_rejected():
    """PRD 3.9: "if the grant's current utilization — the sum of
    `reserved_cents` and `spent_cents` — plus the new reservation would be
    strictly greater than `amount_cents`, the line is rejected with
    `ERR_GRANT_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/grant_utilization_equality_boundary
    """
    grant = make_grant(amount_cents=7777, donor_name="Sloan")
    make_budget_line(grant["id"], 7777, "STORAGE")
    resp = api_client.create_budget_line(
        {"grant_id": grant["id"], "category": "BANDWIDTH",
         "budget_reservation_cents": 1},
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_GRANT_EXHAUSTED)


def test_grant_release_settle_counter_invariant_release_compensates():
    """PRD 3.9: "Release is the quieter twin: releasing an `OPEN` line requires
    only `expected_grant_version`, moves the line to `RELEASED`, subtracts the
    reservation from `reserved_cents`, recomputes the grant's status — which
    can likewise cycle an `EXHAUSTED` grant back to `OPEN` — and increments the
    grant's `version`."

    Design: Difficulty/compensating_invariant/grant_release_settle_counter_invariant
    """
    grant = make_grant(amount_cents=40000, donor_name="Hewlett")
    line = make_budget_line(grant["id"], 15000, "STORAGE")
    version = get_grant(grant["id"])["version"]
    validate_success(api_client.release_budget_line(
        line["id"], {"expected_grant_version": version}, FINANCE
    ))
    grant_now = get_grant(grant["id"])
    assert grant_now["reserved_cents"] == 0
    assert grant_now["spent_cents"] == 0
    assert grant_now["status"] == "OPEN"


def test_grant_release_settle_counter_invariant_settle_conserves_utilization():
    """PRD 3.9: "The line moves to `SETTLED`, the grant's `reserved_cents`
    decreases by the line's `budget_reservation_cents`, its `spent_cents`
    increases by the line's `actual_spend_cents`, its status is recomputed —
    a settle for less than the reservation can drop an `EXHAUSTED` grant back
    to `OPEN` — and the grant's `version` increments by 1."

    Design: Difficulty/compensating_invariant/grant_release_settle_counter_invariant
    """
    grant = make_grant(amount_cents=40000, donor_name="Hewlett")
    line = make_budget_line(grant["id"], 9000, "BANDWIDTH")
    version = get_grant(grant["id"])["version"]
    validate_success(api_client.settle_budget_line(
        line["id"],
        {"actual_spend_cents": 9000, "expected_grant_version": version},
        FINANCE,
    ))
    grant_now = get_grant(grant["id"])
    assert grant_now["reserved_cents"] == 0
    assert grant_now["spent_cents"] == 9000
    assert grant_now["status"] == "OPEN"


def test_loan_checkout_return_counter_invariant_at_peak():
    """PRD 3.4: "The item moves from `LENDABLE` to `ON_LOAN`, and the patron's
    `active_loan_count` increases by 1."

    Design: Difficulty/compensating_invariant/loan_checkout_return_counter_invariant
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Invariant Tract", "author": "K. Balance",
                        "publication_year": 2018},
    )
    patron = make_patron(email="p14@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    assert get_patron(patron["id"])["active_loan_count"] == 1
    assert get_item(items[0]["id"])["status"] == "ON_LOAN"


def test_loan_checkout_return_counter_invariant_restored_after_return():
    """PRD 3.4: "The loan moves from `ACTIVE` to `RETURNED`, the item comes back
    from `ON_LOAN` to `LENDABLE`, the patron's `active_loan_count` decreases by
    1, and waitlist promotion runs for the returned item's work."
    PRD 3.1: "Only the expiry sweep ever increments `strike_count`, and nothing
    ever decrements it"

    Design: Difficulty/compensating_invariant/loan_checkout_return_counter_invariant
    """
    set_clock("2026-09-01T00:00:00Z")
    _lib, work, _batch, items = setup_work_with_lendable_items(
        num_items=1,
        work_overrides={"title": "Invariant Tract", "author": "K. Balance",
                        "publication_year": 2018},
    )
    patron = make_patron(email="p14@example.org")
    loan = checkout(items[0]["id"], patron["id"])
    validate_success(
        api_client.return_loan(loan["id"], make_patron_headers(patron["id"]))
    )
    assert get_patron(patron["id"])["active_loan_count"] == 0
    assert get_item(items[0]["id"])["status"] == "LENDABLE"

    active_rows, active_meta = validate_paginated(
        api_client.list_patron_loans(patron["id"], ADMIN, params={"status": "ACTIVE"})
    )
    assert len(active_rows) == 0
    returned_rows, _ = validate_paginated(
        api_client.list_item_loans(items[0]["id"], ADMIN, params={"status": "RETURNED"})
    )
    assert len(returned_rows) == 1
    assert get_patron(patron["id"])["strike_count"] == 0
