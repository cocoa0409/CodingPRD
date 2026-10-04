"""Corner coverage — RBAC role denials (PRD §2.1 plus the §4 endpoint role
table), entity-backed ownership enforcement for Collector callers (§2.1,
§2.7 rung 3), and the purchaser-status gate re-checked at allocation confirm
(§3.8)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import BOOT_CLOCK_UTC
from test_helpers.factories import (
    billing_cycle_payload,
    create_allocation_payload,
    create_product_payload,
    destroy_payload,
)
from test_helpers.fixtures import (
    create_allocation_offer,
    create_authorized_purchaser,
    create_collector,
    create_denomination,
    create_fed_order,
    create_program,
    create_run,
    place_order,
    set_ap_status,
    set_clock,
    setup_bullion_issue,
    setup_on_sale_product,
    setup_quarantined_case,
    setup_subscription,
)
from test_helpers.test_users import make_bullion_dealer_headers, make_collector_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
LIAISON = TEST_USERS["fed_liaison_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
# Shared fallbacks, used only where the call is rejected before any ownership
# check can matter (role-gate 403s) or the caller legitimately owns nothing.
COLLECTOR = TEST_USERS["collector_headers"]
INSPECTOR_ALT = TEST_USERS["quality_inspector_alt_headers"]


def test_collector_cannot_create_products(api):
    """PRD §2.1: "A request whose role is declared but not listed among the
    roles authorized for the invoked endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mint/products | Create a numismatic product (created in
    SCHEDULED); enforces the family release gap and program mintage ceiling |
    ProgramManager |"

    Design: Corner/rbac/collector_cannot_create_products
    """
    set_clock(api, BOOT_CLOCK_UTC)

    resp = api.create_product(
        create_product_payload(
            product_code="RBAC-1", product_family="F1",
            release_datetime="2026-10-01T14:00:00Z"),
        COLLECTOR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)  # 403 auto-checked

    _, meta = validate_paginated(api.list_products(MANAGER))
    assert meta["total_count"] == 0, "a role-rejected create must not persist a product"


def test_quality_inspector_cannot_certify_destruction(api):
    """PRD §2.1: "A request whose role is declared but not listed among the
    roles authorized for the invoked endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mint/error-coin-cases/{id}/destroy | Certify
    destruction of a quarantined case with two distinct certifier ids |
    DestructionCertifier |"
    PRD §2.7: "Validations are evaluated as a fixed ladder; the earliest rung
    that fails produces the response, and later rungs are never consulted."

    Design: Corner/rbac/quality_inspector_cannot_certify_destruction
    """
    case, _, _, _, _ = setup_quarantined_case(api)  # QUARANTINED, reported by qi-1

    # The supplied certifier ids are distinct from each other and from the
    # reporter, so only the rung-2 role gate can reject this call.
    resp = api.destroy_error_coin_case(
        case["id"], destroy_payload("dc-1", "dc-2"), INSPECTOR_ALT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)  # 403 auto-checked


def test_program_manager_cannot_disburse_surcharges(api):
    """PRD §2.1: "A request whose role is declared but not listed among the
    roles authorized for the invoked endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mint/commemorative-programs/{id}/disburse-surcharges |
    Disburse accrued surcharges to the statutory beneficiary | FinanceOfficer |"

    Design: Corner/rbac/program_manager_cannot_disburse_surcharges
    """
    program = create_program(api)  # DESIGN_REVIEW; state never reached at rung 2

    resp = api.disburse_surcharges(program["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)  # 403 auto-checked


def test_fedliaison_cannot_start_production_run(api):
    """PRD §2.1: "A request whose role is declared but not listed among the
    roles authorized for the invoked endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mint/production-runs/{id}/start | Start striking from
    PLANNED or REWORK; reserves blanks from denomination stock |
    ProductionPlanner |"

    Design: Corner/rbac/fedliaison_cannot_start_production_run
    """
    set_clock(api, BOOT_CLOCK_UTC)
    create_denomination(api)
    fed_order = create_fed_order(api)
    run = create_run(api, fed_order["id"])  # PLANNED

    resp = api.start_production_run(run["id"], LIAISON)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)  # 403 auto-checked

    after = validate_success(api.get_production_run(run["id"], PLANNER))
    assert after["status"] == "PLANNED", (
        f"a role-rejected start must leave the run PLANNED, got {after['status']}")


def test_collector_cannot_run_billing_cycle(api):
    """PRD §2.1: "A request whose role is declared but not listed among the
    roles authorized for the invoked endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mint/subscriptions/{id}/billing-cycle | Run the billing
    cycle when due; creates the PENDING invoice and advances
    next_billing_date; OCC-guarded | PlatformAdmin |"

    Design: Corner/rbac/collector_cannot_run_billing_cycle
    """
    _, collector, subscription = setup_subscription(api)  # ACTIVE, owned by collector

    # The caller IS the subscriber and carries the current OCC version, so
    # only the rung-2 role gate can reject this call.
    resp = api.run_billing_cycle(
        subscription["id"], billing_cycle_payload(subscription["version"]),
        make_collector_headers(collector["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)  # 403 auto-checked


def test_bullion_dealer_cannot_create_allocation_offer(api):
    """PRD §2.1: "A request whose role is declared but not listed among the
    roles authorized for the invoked endpoint is rejected with
    `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: "| POST | /mint/bullion-issues/{id}/allocations | Offer an
    allocation to an APPROVED authorized purchaser; decrements the pool;
    OCC-guarded | ProgramManager |"

    Design: Corner/rbac/bullion_dealer_cannot_create_allocation_offer
    """
    issue = setup_bullion_issue(api)  # GOLD spot set; pool 1000; version 1
    ap = create_authorized_purchaser(api)

    resp = api.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=5,
            expected_bullion_issue_version=issue["version"]),
        make_bullion_dealer_headers(ap["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)  # 403 auto-checked

    after = validate_success(api.get_bullion_issue(issue["id"], MANAGER))
    assert after["remaining_pool_units"] == 1000, (
        f"a role-rejected offer must not touch the pool, got "
        f"{after['remaining_pool_units']}")


def test_collector_reading_others_order_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Collector`, `X-User-ID` is the `id`
    of the acting `Collector`; ownership checks on orders, subscriptions, and
    invoices compare the resource's `collector_id` (or its parent
    subscription's `collector_id`) against `X-User-ID`, and a Collector
    calling a list endpoint with a `collector_id` filter must pass their own
    id."
    PRD §2.1: "A violation of either ownership rule is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
    PRD §4: "| GET | /mint/orders/{id} | Read an order (Collector callers: own
    orders only) | Collector, ProgramManager, MintDirector, PlatformAdmin |"

    Design: Corner/rbac/collector_reading_others_order_forbidden
    """
    product = setup_on_sale_product(api)
    c1 = create_collector(api, full_name="Owner", email="own@example.com",
                          household_id="HH-1")
    c2 = create_collector(api, full_name="Other", email="oth@example.com",
                          household_id="HH-2")
    order = place_order(api, product["id"], c1, 1)

    resp = api.get_order(order["id"], make_collector_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)  # 403 auto-checked


def test_collector_listing_with_foreign_collector_filter_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Collector`, `X-User-ID` is the `id`
    of the acting `Collector`; ownership checks on orders, subscriptions, and
    invoices compare the resource's `collector_id` (or its parent
    subscription's `collector_id`) against `X-User-ID`, and a Collector
    calling a list endpoint with a `collector_id` filter must pass their own
    id."
    PRD §2.1: "A violation of either ownership rule is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."
    PRD §4: "| GET | /mint/orders | List orders with optional filters;
    Collector callers must pass their own collector_id | Collector,
    ProgramManager, MintDirector, PlatformAdmin |"

    Design: Corner/rbac/collector_listing_with_foreign_collector_filter_forbidden
    """
    product = setup_on_sale_product(api)
    c1 = create_collector(api, full_name="Lister One", email="l1@example.com",
                          household_id="HH-1")
    c2 = create_collector(api, full_name="Lister Two", email="l2@example.com",
                          household_id="HH-2")
    place_order(api, product["id"], c1, 1)

    foreign = api.list_orders(
        make_collector_headers(c2["id"]), params={"collector_id": c1["id"]})
    validate_error(foreign, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)  # 403 auto-checked

    own = api.list_orders(
        make_collector_headers(c2["id"]), params={"collector_id": c2["id"]})
    rows, meta = validate_paginated(own)
    assert meta["total_count"] == 0 and rows == [], (
        "c2 has placed no orders, so their own-id filter must return an empty page")


def test_allocation_confirm_while_ap_suspended_rejected(api):
    """PRD §3.8: "A `BullionDealer` confirms an allocation still in `OFFERED`
    — anything else is rejected with `ERR_ALLOCATION_NOT_CONFIRMABLE` (422) —
    with the caller's `X-User-ID` equal to the allocation's
    `authorized_purchaser_id` (`ERR_FORBIDDEN_OWNERSHIP`, 403), with the firm
    still `APPROVED` (`ERR_AP_NOT_APPROVED`, 422), and before
    `offer_expires_at`; because the clock sweep expires offers eagerly, a
    lapsed offer is already `EXPIRED` and fails the state check."
    PRD §2.7: "Referential integrity — body references resolve:
    `denomination_code` to an existing denomination (`ERR_UNKNOWN_DENOMINATION`,
    422), a supplied `program_id` to an existing program
    (`ERR_UNKNOWN_PROGRAM`, 422), `product_id` to an existing product
    (`ERR_UNKNOWN_PRODUCT`, 422), a current spot price established for the
    commodity or metal (`ERR_SPOT_PRICE_MISSING`, 422), and the authorized
    purchaser existing in `APPROVED` status (`ERR_AP_NOT_APPROVED`, 422)."

    Design: Corner/rbac/allocation_confirm_while_ap_suspended_rejected
    """
    issue = setup_bullion_issue(api, clock_ts="2026-09-10T00:00:00Z")
    ap = create_authorized_purchaser(api, name="Flip Dealer", tier="T1")
    allocation, _ = create_allocation_offer(api, issue, ap, 10)  # OFFERED while APPROVED
    set_ap_status(api, ap["id"], "SUSPENDED")

    resp = api.confirm_allocation(
        allocation["id"], make_bullion_dealer_headers(ap["id"]))
    validate_error(resp, ApiErrorId.ERR_AP_NOT_APPROVED)  # 422 auto-checked

    after = validate_success(api.get_allocation(allocation["id"], MANAGER))
    assert after["status"] == "OFFERED", (
        f"the rejected confirm must leave the allocation OFFERED, got {after['status']}")
