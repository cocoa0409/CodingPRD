"""Segregation of duties: each role is refused the other role's exclusive operations."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    E,
    LEGAL_HEADERS,
    SOM_HEADERS,
    factories,
    validate_error,
    validate_success,
    fixtures,
)

MATRIX_QUOTE = (
    "Independently of authentication, every endpoint declares the set of roles permitted to call "
    "it; a request whose role is authenticated but not listed for that endpoint is rejected with "
    "`ERR_INSUFFICIENT_ROLE` and an HTTP 403 response."
)
SOD_QUOTE = (
    "The role matrix in §2.1 is not merely a permissions list; it encodes the controls the "
    "business relies on. The operator who quotes a vendor's landed cost is never the operator "
    "who attests that the shelf and the register agree."
)
BUYER_QUOTE = (
    "a `MerchandiseBuyer` cannot begin a store conversion, file its artefacts, or file a "
    "compliance audit."
)
LEGAL_QUOTE = (
    "`LegalCostEngineer` is also read-only, restricted to items, their landed-cost history, their "
    "break-even projections, stores and price-integrity audits, and deliberately holds no write "
    "operation at all so that the same operator cannot both author a cost and attest to it."
)
OPAQUE_QUOTE = (
    "in every case `X-User-ID` is an opaque operator identifier not tied to any persisted entity, "
    "is never resolved against a database row, and is never used in an ownership comparison."
)
DCO_QUOTE = (
    "A `DistributionCenterOperator` creates allocation lines and releases or shorts them, and "
    "cannot book, move or receive containers."
)
AUTO_ADVANCE_QUOTE = (
    "A container carrying no allocation lines at all never auto-advances, because the "
    "precondition requires at least one line to exist."
)


def test_the_buying_office_cannot_begin_a_store_conversion(api):
    """A MerchandiseBuyer is a 403 where the store team succeeds on the identical payload.

    PRD §2.1: "Independently of authentication, every endpoint declares the set of roles permitted
    to call it; a request whose role is authenticated but not listed for that endpoint is rejected
    with `ERR_INSUFFICIENT_ROLE` and an HTTP 403 response."
    PRD §2.1: "a `MerchandiseBuyer` cannot begin a store conversion, file its artefacts, or file
    a compliance audit."
    PRD §2.1: "in every case `X-User-ID` is an opaque operator identifier not tied to any
    persisted entity, is never resolved against a database row, and is never used in an ownership
    comparison."

    Design: Corner/rbac/merchandise_buyer_cannot_operate_a_store_conversion
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()

    refused = api.begin_conversion(store["id"], price_point["id"], BUYER_HEADERS)
    validate_error(refused, E.ERR_INSUFFICIENT_ROLE.value)

    allowed = validate_success(api.begin_conversion(store["id"], price_point["id"], SOM_HEADERS), 200)
    assert allowed["status"] == "CONVERTING"
    assert allowed["conversion_price_point_id"] == price_point["id"]
    assert allowed["sign_order_filed"] is False
    assert allowed["shelf_tag_filed"] is False
    assert allowed["register_file_locked"] is False


def test_the_independent_cost_reviewer_may_read_costs_but_not_file_a_visit(api):
    """The read-only reviewer holds no write operation on the record it reviews.

    PRD §2.1: "`LegalCostEngineer` is also read-only, restricted to items, their landed-cost
    history, their break-even projections, stores and price-integrity audits, and deliberately
    holds no write operation at all so that the same operator cannot both author a cost and
    attest to it."
    PRD §2.1: "The role matrix in §2.1 is not merely a permissions list; it encodes the controls
    the business relies on. The operator who quotes a vendor's landed cost is never the operator
    who attests that the shelf and the register agree."
    PRD §3.3: "A break-even read reports the item's `item_id`, its `break_even_units`, its
    `unit_retail_cents`, its `landed_cost_cents`, its `variable_store_cost_cents`, its
    `net_contribution_cents_per_unit`, and a `regime` string that reads `PRICE_PENDING`,
    `CONVERGENCE` or `DIVERGENCE_OR_ZERO_MARGIN` under exactly the conditions above."

    Design: Corner/rbac/legal_cost_engineer_is_read_only_on_costs_and_audits
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(price_point["id"], vendor["id"], sku="1001")
    audit = validate_success(
        api.create_audit(factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=80, mismatched_item_count=5),
            SOM_HEADERS),
        201,
    )

    history = validate_success(api.list_item_landed_costs(item["id"], LEGAL_HEADERS), 200)
    assert history == [], "the reviewer may read the history, which is empty so far"

    projection = validate_success(api.get_break_even(item["id"], LEGAL_HEADERS), 200)
    assert projection["regime"] == "PRICE_PENDING"
    assert projection["break_even_units"] == 0

    validate_error(
        api.create_audit(factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=10, mismatched_item_count=0),
            LEGAL_HEADERS),
        E.ERR_INSUFFICIENT_ROLE.value,
    )
    validate_error(
        api.resolve_audit(audit["id"], LEGAL_HEADERS), E.ERR_INSUFFICIENT_ROLE.value)

    still_open = validate_success(api.get_audit(audit["id"], LEGAL_HEADERS), 200)
    assert still_open["status"] == "OPEN"
    store_audits = validate_success(
        api.list_store_audits(store["id"], LEGAL_HEADERS), 200)
    assert len(store_audits) == 1


def test_the_buying_office_cannot_allocate_units_to_a_store(api):
    """Placement is the distribution center's act, so the buyer's request writes no line.

    PRD §2.1: "Independently of authentication, every endpoint declares the set of roles permitted
    to call it; a request whose role is authenticated but not listed for that endpoint is rejected
    with `ERR_INSUFFICIENT_ROLE` and an HTTP 403 response."
    PRD §2.1: "A `DistributionCenterOperator` creates allocation lines and releases or shorts
    them, and cannot book, move or receive containers."
    PRD §3.6: "A container carrying no allocation lines at all never auto-advances, because the
    precondition requires at least one line to exist."

    Design: Corner/rbac/merchant_buyer_cannot_allocate_container_units_to_a_store
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(price_point["id"], vendor["id"], sku="1001")
    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    payload = factories.create_allocation_line_payload(
        container["id"], store["id"], item["id"], sequence=1, requested_units=40)

    validate_error(
        api.create_allocation_line(payload, BUYER_HEADERS), E.ERR_INSUFFICIENT_ROLE.value)

    lines = validate_success(
        api.list_container_allocation_lines(container["id"], ANALYST_HEADERS), 200)
    assert lines == [], "the refused call wrote no line"

    read = validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "RECEIVED", (
        "a line-free container never auto-advances to ALLOCATED"
    )

    created = validate_success(api.create_allocation_line(payload, DCO_HEADERS), 201)
    assert created["status"] == "ALLOCATED"
    assert created["allocated_units"] == 40