"""Corner coverage: endpoint reads, clock default, fulfillment ledger, pools."""
from test_helpers import (
    ADMIN,
    ANALYST,
    checkout,
    create_consortium,
    create_library,
    create_fund,
    create_license_via_order,
    create_order,
    create_patron,
    fulfill_order,
    make_library_admin_headers,
    make_patron_headers,
    place_hold,
    propose_order,
    approve_order,
    setup_base,
    setup_base_with_title,
    validate_success,
)


def test_consortium_get_returns_stored_configuration(api):
    """PRD §3.1: "A `ConsortiumAdmin` begins by creating the consortium itself,
    supplying a display `name` and optionally overriding three policy defaults:
    `cpc_discount_pct` (the fraction knocked off each cost-per-circulation
    checkout charge, defaulting to 0.0 and always at least 0 and strictly less
    than 1), `host_share_floor_pct` (the minimum fraction of a shared title's
    invoiced license cost that the purchasing host library must absorb,
    defaulting to 0.25 and always between 0 and 1 inclusive), and
    `invoice_period` (a cadence label, `MONTHLY` or `QUARTERLY`, defaulting to
    `MONTHLY`). A new consortium starts with `status` `ACTIVE` and `version`
    1."

    Design: Corner/endpoints/consortium_get_returns_stored_configuration
    """
    consortium = create_consortium()
    resp = api.get_consortium(consortium["id"], ANALYST)
    data = validate_success(resp)
    assert data["cpc_discount_pct"] == 0.15
    assert data["host_share_floor_pct"] == 0.25
    assert data["invoice_period"] == "MONTHLY"
    assert data["status"] == "ACTIVE"


def test_availability_computed_read_matches_queue_state(api):
    """PRD §3.6: "The title-level availability view reports, from the
    perspective of a chosen library (the `library_id` query parameter,
    defaulting to the requesting patron's home library), four numbers:
    `copies_available`, the `active_holds` queue depth, and the
    `optimistic_wait_days` and `pessimistic_wait_days` a new arrival should
    expect."
    PRD §3.9: "C is the effective lendable copy count for the patron's home
    library: the sum of `copies_total` over `ACTIVE` `OCOU` licenses visible to
    that library."

    Design: Corner/endpoints/availability_computed_read_matches_queue_state
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
    place_hold(p2["id"], ctx["title"]["id"])
    resp = api.get_title_availability(
        ctx["title"]["id"], ANALYST, params={"library_id": lib["id"]},
    )
    avail = validate_success(resp)
    assert avail["copies_available"] == 1, "2 copies - 1 active loan"
    assert avail["active_holds"] == 2
    assert avail["optimistic_wait_days"] == 21, "ceil(2/2) * 21"
    assert avail["pessimistic_wait_days"] == 63, "ceil(2/2) * (21 + 2*21)"


def test_clock_default_is_fixed_seed_datetime(api):
    """PRD §2.5: "At server startup, before any clock-set call, the logical
    clock reads exactly `2026-09-01T00:00:00Z`."
    PRD §3.3: "A registered card starts `ACTIVE`, and the server computes
    `card_expires_at` as the registration date plus the library's
    `card_validity_days`."

    Design: Corner/endpoints/clock_default_is_fixed_seed_datetime
    """
    # Deliberately NO clock-set call: the startup default must be in effect.
    consortium = create_consortium(name="Consortium Default Clock")
    library = create_library(consortium["id"], name="Library Default Clock")
    patron = create_patron(library["id"], external_card_number="D-0",
                           full_name="Default Clock")
    assert patron["created_at"] == "2026-09-01T00:00:00Z"
    assert patron["card_expires_at"] == "2028-08-31T00:00:00Z", (
        "default clock + 730 days"
    )


def test_fulfill_with_higher_invoice_than_estimate_moves_ledger_by_actuals(api):
    """PRD §3.10: "It creates the license exactly as §3.8 describes, moves the
    ledger — subtracting `estimated_cost_cents` from `committed_cents` and
    adding `invoiced_cost_cents` to `spent_cents`, with the fund's `version`
    incrementing."

    Design: Corner/endpoints/fulfill_with_higher_invoice_than_estimate_moves_ledger_by_actuals
    """
    ctx = setup_base_with_title()
    lib = ctx["library"]
    lib_admin = make_library_admin_headers(lib["id"])
    order = create_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                         model="OCOU", copies=1)
    propose_order(lib["id"], order["id"])
    approve_order(lib["id"], order["id"])
    resp = api.fulfill_order(order["id"], {"invoiced_cost_cents": 5500}, lib_admin)
    fulfilled = validate_success(resp)
    assert fulfilled["status"] == "FULFILLED"
    assert fulfilled["invoiced_cost_cents"] == 5500
    fund = validate_success(api.get_fund(ctx["fund"]["id"], lib_admin))
    assert fund["committed_cents"] == 0
    assert fund["spent_cents"] == 5500
    assert fund["available_committed_cents"] == 994500
    assert fund["available_actual_cents"] == 994500


def test_simultaneous_use_license_supports_unbounded_concurrent_loans(api):
    """PRD §2.6: "`SIMULTANEOUS_USE` grants unlimited concurrent loans for a
    fixed term — `expires_at` set from the title's `simultaneous_use_days`."
    PRD §3.5: "computes `due_at` as `checkout_at` plus the loan days —
    `skip_the_line_loan_days` for a skip-the-line checkout, `loan_period_days`
    otherwise — with one clamp: for `METERED_TIME` and `SIMULTANEOUS_USE`
    licenses, `due_at` never extends beyond the license's `expires_at`."

    Design: Corner/endpoints/simultaneous_use_license_supports_unbounded_concurrent_loans
    """
    ctx = setup_base_with_title(
        title_overrides={"simultaneous_use_allowed": True}
    )
    lib = ctx["library"]
    create_license_via_order(lib["id"], ctx["fund"]["id"], ctx["title"]["id"],
                             model="SIMULTANEOUS_USE", invoiced_cost_cents=9000)
    loans = []
    for i in range(3):
        p = create_patron(lib["id"], external_card_number=f"P-{i}",
                          full_name=f"Patron {i}")
        loans.append(checkout(p["id"], ctx["title"]["id"]))
    for loan in loans:
        assert loan["status"] == "ACTIVE"
        assert loan["due_at"] == "2026-09-22T00:00:00Z", (
            f"loan period, clamped only by the 180-day license term, got {loan['due_at']}"
        )
