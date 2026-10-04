"""Depth tests: boundary precision (auto-accept clock boundary, zero-available
stock depletion)."""
from test_helpers import (
    TEST_USERS,
    build_bus_to_accepted,
    build_bus_to_delivered,
    create_parts_stock_payload,
    create_warranty_claim_payload,
    get_success_data,
    make_warranty_admin_headers,
    setup_accepted_bus,
    setup_active_contract,
    validate_success,
)

PO = TEST_USERS["procurement_officer_headers"]
PP = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
WA = TEST_USERS["warranty_admin_headers"]
INSP = TEST_USERS["agency_inspector_headers"]


def test_auto_accept_at_exact_deadline_does_not_fire(api):
    """PRD section 3.8: "The boundary is strict: at exactly the deadline
    instant no auto-acceptance occurs; only a time strictly greater than the
    deadline triggers it."
    PRD section 3.8: "the system stamps `delivered_at` with the current
    logical time and computes `acceptance_deadline` as `delivered_at` plus 30
    days."

    Design: Difficulty/boundary_precision_check/auto_accept_deadline_strict_greater_boundary
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_delivered(setup)
    assert bus["status"] == "DELIVERED"
    # delivered at the clock epoch 2026-09-01T00:00:00Z; deadline +30 days.
    get_success_data(
        api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, ADMIN),
    )
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "DELIVERED", (
        "at exactly the acceptance_deadline no auto-acceptance occurs; got "
        f"{bus['status']}"
    )


def test_auto_accept_one_second_past_deadline_fires(api):
    """PRD section 3.8: "When the current logical time passes strictly beyond
    the `acceptance_deadline` without an agency decision, the system
    auto-accepts the bus from `DELIVERED` to `ACCEPTED`, recomputing the
    agency's `zev_ratio` and advancing `payment_status` from `UNPAID` to
    `INVOICED` exactly as a manual acceptance would."
    PRD section 3.8: "Auto-acceptance is evaluated when the logical clock is
    advanced."

    Design: Difficulty/boundary_precision_check/auto_accept_deadline_strict_greater_boundary
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = build_bus_to_delivered(setup)
    get_success_data(
        api.set_clock({"to_iso8601": "2026-10-01T00:00:01Z"}, ADMIN),
    )
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "ACCEPTED", (
        "a clock strictly greater than acceptance_deadline auto-accepts; got "
        f"{bus['status']}"
    )
    assert bus["payment_status"] == "INVOICED", (
        "auto-acceptance advances payment UNPAID -> INVOICED exactly as a "
        f"manual acceptance would; got {bus['payment_status']}"
    )


def _setup_approved_claim(api, stock_quantity, unit_cost_cents, claimed_amount):
    """ACCEPTED bus + parts stock row + approved warranty claim.
    Returns (setup, stock, claim)."""
    setup = setup_accepted_bus(
        component_overrides={"unit_cost_cents": unit_cost_cents},
    )
    component = setup["components"][0]
    resp = api.create_parts_stock(
        create_parts_stock_payload(
            setup["agency"]["id"], component["id"], quantity=stock_quantity
        ),
        WA,
    )
    stock = get_success_data(resp)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            setup["bus"]["id"], component["id"],
            defect_code="ENGINE_FAIL", claimed_amount_cents=claimed_amount,
        ),
        WA,
    )
    claim = get_success_data(resp)
    get_success_data(api.start_review_claim(claim["id"], WA))
    resp = api.approve_claim(claim["id"], make_warranty_admin_headers("wa-1"))
    claim = get_success_data(resp)
    return setup, stock, claim


def test_stock_depletes_at_exactly_zero_available(api):
    """PRD section 3.9: "When the available stock reaches zero the row
    auto-transitions from `ACTIVE` to `DEPLETED`, and a restock that raises
    `quantity` back above `reserved_quantity` flips it from `DEPLETED` to
    `ACTIVE`."
    PRD section 3.9: "Payment releases the stock reservation, decrements the
    stock row's `quantity` by the reserved units consumed, and moves the claim
    `APPROVED` → `PAID`."

    Design: Difficulty/boundary_precision_check/parts_stock_zero_available_depleted_boundary
    """
    # claimed 150000 with unit cost 75000 reserves ceil(150000/75000) = 2 units.
    setup, stock, claim = _setup_approved_claim(
        api, stock_quantity=2, unit_cost_cents=75000, claimed_amount=150000
    )
    assert claim["approved_amount_cents"] == 150000, (
        "bus age 0 days is fully covered; approved must equal claimed, got "
        f"{claim['approved_amount_cents']}"
    )
    stock = get_success_data(api.get_parts_stock(stock["id"], WA))
    assert stock["reserved_quantity"] == 2
    assert stock["status"] == "ACTIVE", (
        "before payment the reservation alone must not deplete the row; got "
        f"{stock['status']}"
    )

    resp = api.pay_claim(claim["id"], make_warranty_admin_headers("wa-2"))
    validate_success(resp)
    stock = get_success_data(api.get_parts_stock(stock["id"], WA))
    assert stock["quantity"] == 0
    assert stock["reserved_quantity"] == 0
    assert stock["status"] == "DEPLETED", (
        "available stock reaching exactly zero flips the row to DEPLETED; got "
        f"{stock['status']}"
    )


def test_stock_restock_above_reserved_reactivates(api):
    """PRD section 3.9: "When the available stock reaches zero the row
    auto-transitions from `ACTIVE` to `DEPLETED`, and a restock that raises
    `quantity` back above `reserved_quantity` flips it from `DEPLETED` to
    `ACTIVE`."

    Design: Difficulty/boundary_precision_check/parts_stock_zero_available_depleted_boundary
    """
    setup, stock, claim = _setup_approved_claim(
        api, stock_quantity=2, unit_cost_cents=75000, claimed_amount=150000
    )
    resp = api.pay_claim(claim["id"], make_warranty_admin_headers("wa-2"))
    validate_success(resp)
    stock = get_success_data(api.get_parts_stock(stock["id"], WA))
    assert stock["status"] == "DEPLETED"

    resp = api.restock_parts_stock(stock["id"], {"quantity": 3}, WA)
    restocked = validate_success(resp)
    assert restocked["quantity"] == 3
    assert restocked["status"] == "ACTIVE", (
        "restock above reserved_quantity flips DEPLETED -> ACTIVE; got "
        f"{restocked['status']}"
    )
