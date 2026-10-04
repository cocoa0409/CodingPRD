"""Authentication and role-based access control (PRD §2.1)."""

from test_helpers import (
    ADMIN,
    HEALTH,
    PLANNER,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_active_commitment,
    create_complex,
    create_customer,
    create_disease_event,
    create_feed_contract,
    create_house,
    make_complex_manager_headers,
    make_customer_headers,
    read_commitment,
    receive_feed,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR

AUDITOR = TEST_USERS["quality_auditor_headers"]


def test_missing_auth_headers_returns_401(api):
    """A request with no X-User-Role / X-User-ID headers fails authentication
    before any other check.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting party, and `X-User-Role`, naming the caller's operational
    capacity. ... A request with missing headers, or whose role header names
    none of the nine, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    complex_ = create_complex()
    response = api.get_complex(complex_["id"], {})
    validate_error(response, ERR.ERR_UNAUTHENTICATED)


def test_unknown_role_returns_401(api):
    """A role header naming none of the nine declared roles is a 401, not 403.

    PRD §2.1: "The platform recognizes exactly nine roles, spelled as follows:
    `PlatformAdmin` ..., `ProductionPlanner` ..., `ComplexManager` ...,
    `PlantManager` ..., `ProcurementLead` ..., `HealthOfficial` ...,
    `QualityAuditor` ..., `SalesManager` ..., and `Customer` .... A request
    with missing headers, or whose role header names none of the nine, is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unknown_role_returns_401
    """
    complex_ = create_complex()
    response = api.get_complex(
        complex_["id"], build_user_headers("operator-7", "Warehouseman")
    )
    validate_error(response, ERR.ERR_UNAUTHENTICATED)


def test_customer_cannot_create_complex_returns_403(api):
    """Complex creation is PlatformAdmin-only; the Customer role is rejected.

    PRD §2.1: "A request whose role is recognized but not listed among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST `/api/complexes` | Create a production complex |
    PlatformAdmin".

    Design: Corner/rbac/customer_cannot_create_complex_returns_403
    """
    response = api.create_complex(
        {
            "name": "Rogue Farm",
            "region_code": "WEST",
            "mill_receiving_tons_per_day": 100,
        },
        make_customer_headers("cust-rogue"),
    )
    validate_error(response, ERR.ERR_FORBIDDEN)


def test_production_planner_cannot_confirm_disease(api):
    """Disease confirmation is HealthOfficial-exclusive.

    PRD §2.1: "A request whose role is recognized but not listed among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST `/api/disease-events/{id}/confirm` | Confirm a suspected
    event (biosecurity cascade) | HealthOfficial".

    Design: Corner/rbac/production_planner_cannot_confirm_disease
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex()
    house = create_house(complex_["id"], capacity_hens=50_000)
    event = create_disease_event(complex_["id"], [house["id"]])
    assert event["status"] == "SUSPECTED"

    validate_error(
        api.confirm_disease_event(event["id"], PLANNER), ERR.ERR_FORBIDDEN
    )

    # The event is untouched: still SUSPECTED, posture still ELEVATED.
    after = validate_success(api.get_disease_event(event["id"], HEALTH))
    assert after["status"] == "SUSPECTED"
    assert after["confirmed_at"] is None
    complex_after = validate_success(api.get_complex(complex_["id"], HEALTH))
    assert complex_after["biosecurity_posture"] == "ELEVATED"


def test_quality_auditor_cannot_publish_quotation(api):
    """Quotation publication is PlatformAdmin-exclusive.

    PRD §2.1: "A request whose role is recognized but not listed among the
    endpoint's authorized roles is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST `/api/market-quotations` | Publish a market quotation |
    PlatformAdmin".

    Design: Corner/rbac/quality_auditor_cannot_publish_quotation
    """
    auditor = AUDITOR
    response = api.create_market_quotation(
        {
            "region_code": "MIDWEST",
            "size_class": "LARGE",
            "price_cents_per_dozen": 150,
            "effective_date": "2026-09-07T00:00:00Z",
        },
        auditor,
    )
    validate_error(response, ERR.ERR_FORBIDDEN)
    rows, meta = validate_paginated(api.list_market_quotations(ADMIN))
    assert rows == [] and meta["total_count"] == 0


def test_customer_cannot_order_under_another_customers_commitment(api):
    """Entity-backed ownership: customer B cannot book under A's commitment.

    PRD §2.1: "booking an order, cancelling an order, reading a single order,
    and disputing a settlement all require the requesting Customer's
    `X-User-ID` to equal the owning commitment's `customer_id`, and a mismatch
    is `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_order_under_another_customers_commitment
    """
    set_clock("2026-09-01T00:00:00Z")
    customer_a = create_customer(name="Customer A")
    customer_b = create_customer(name="Customer B")
    commitment = create_active_commitment(
        customer_a["id"], weekly_dozen_committed=10_000,
    )

    version = read_commitment(commitment["id"])["version"]
    response = api.create_order(
        commitment["id"],
        {
            "ship_week_start": "2026-09-07T00:00:00Z",
            "dozen_ordered": 100,
            "size_class": "LARGE",
            "expected_commitment_version": version,
        },
        make_customer_headers(customer_b["id"]),
    )
    validate_error(response, ERR.ERR_FORBIDDEN)

    # The same payload under the owning customer's identity passes the gate.
    version = read_commitment(commitment["id"])["version"]
    created = validate_success(
        api.create_order(
            commitment["id"],
            {
                "ship_week_start": "2026-09-07T00:00:00Z",
                "dozen_ordered": 100,
                "size_class": "LARGE",
                "expected_commitment_version": version,
            },
            make_customer_headers(customer_a["id"]),
        ),
        201,
    )
    assert created["status"] == "BOOKED"


def test_complex_manager_cannot_batch_another_complex(api):
    """ComplexManager identity is the complex itself: a foreign complex id in
    the path fails ownership.

    PRD §2.1: "When `X-User-Role` is `ComplexManager`, `X-User-ID` is the `id`
    of the acting Complex; producing a feed batch requires the manager's
    `X-User-ID` to equal the path complex's `id`, again enforced as
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/complex_manager_cannot_batch_another_complex
    """
    set_clock("2026-09-01T00:00:00Z")
    mill_x = create_complex(
        name="Mill X", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    mill_y = create_complex(
        name="Mill Y", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    contract = create_feed_contract(mill_x["id"], total_tons=100)
    receive_feed(contract["id"], 100, 17_500)

    # Manager of Mill Y batching at Mill X: forbidden.
    response = api.create_feed_batch(
        mill_x["id"],
        {"program": "CONVENTIONAL", "corn_tons": 10, "soybean_tons": 0},
        make_complex_manager_headers(mill_y["id"]),
    )
    validate_error(response, ERR.ERR_FORBIDDEN)

    # Manager of Mill X batching at Mill X: created.
    batch = validate_success(
        api.create_feed_batch(
            mill_x["id"],
            {"program": "CONVENTIONAL", "corn_tons": 10, "soybean_tons": 0},
            make_complex_manager_headers(mill_x["id"]),
        ),
        201,
    )
    assert batch["tons_produced"] == 10
