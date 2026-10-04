"""Role permissions, store-day gating, optimistic concurrency and void-receiving guards."""
import pytest

from test_helpers import api_client, validate_success, validate_error, validate_paginated, ApiErrorId
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN, MANAGER, LEAD, PLANNER, RETAIL_CASHIER, ANON,
    server_for, cashier_for,
    create_item, setup_store, setup_open_day, open_store_day, create_shift, start_shift,
    create_check, create_receipt, create_transfer, stock_item, post_guest_counts,
    get_store_day, get_transfer,
)

BOAT = "ITM-BOAT-6400"


def _boat():
    return create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)


# ==========================================================================
# Difficulty queue A — non_linear_state_machine (parallel store-day dimensions)
# ==========================================================================

def test_the_store_day_traffic_and_gate_dimensions_move_independently_of_its_lifecycle(api):
    """PRD §2.10: "A store day carries two independent state axes. `day_status` is `OPEN` or
    `CLOSED`, and it governs whether the day may still be mutated at all"
    PRD §3.1: "A count at or above 120 guests moves `traffic_state` to `RUSH` and
    simultaneously moves `conversion_gate` to `GATED_RESTRICTED`"

    Design: Difficulty/non_linear_state_machine/store_day_parallel_dimensions_gate_versus_lifecycle_versus_traffic
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})

    first = post_guest_counts(day["id"], day["version"], 108, 1080000, 20, 10)
    assert first["traffic_state"] == "STEADY"
    assert first["conversion_gate"] == "OPEN"

    second = post_guest_counts(day["id"], first["version"], 120, 1200000, 24, 12)
    assert second["traffic_state"] == "RUSH"
    assert second["conversion_gate"] == "GATED_RESTRICTED"

    third = post_guest_counts(day["id"], second["version"], 119, 1190000, 24, 12)
    assert third["traffic_state"] == "STEADY"
    assert third["conversion_gate"] == "OPEN"
    assert third["day_status"] == "OPEN", "the lifecycle axis never moved"


def test_the_lifecycle_dimension_stays_open_across_each_gate_transition(api):
    """PRD §2.10: "`traffic_state` is `QUIET`, `STEADY` or `RUSH`, and it is derived purely
    from `restaurant_guest_count`"
    PRD §3.1: "Posting a count is a transition even when the day neither opens nor closes,
    and it has four distinct outcomes depending on where the count lands."

    Design: Difficulty/non_linear_state_machine/store_day_parallel_dimensions_gate_versus_lifecycle_versus_traffic
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    version = day["version"]

    for guests, traffic, gate in ((108, "STEADY", "OPEN"),
                                  (120, "RUSH", "GATED_RESTRICTED"),
                                  (119, "STEADY", "OPEN")):
        state = post_guest_counts(day["id"], version, guests, guests * 10000, 24, 12)
        assert state["traffic_state"] == traffic
        assert state["conversion_gate"] == gate
        assert state["day_status"] == "OPEN"
        version = state["version"]


# ==========================================================================
# Corner queue B — validations (restricted gate)
# ==========================================================================

def test_a_restricted_gate_refuses_new_backroom_load(api):
    """PRD §2.10: "A `GATED_RESTRICTED` gate still admits sales-floor writes but refuses new
    backroom load, and a receiving refused on that ground - as opposed to on the suspended
    ground - is reported with `ERR_STORE_DAY_GATE_RESTRICTED` (HTTP 409) instead."
    PRD §3.1: "A count at or above 120 guests moves `traffic_state` to `RUSH` and
    simultaneously moves `conversion_gate` to `GATED_RESTRICTED`"

    Design: Corner/validations/eligibility_gate_restricted_refuses_new_backroom_load
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 30})
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 60)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    restricted = post_guest_counts(day["id"], day["version"], 140, 1400000, 30, 15)
    assert restricted["conversion_gate"] == "GATED_RESTRICTED"

    validate_error(api.receive_transfer(transfer["id"], {"received_units": 60}, LEAD),
                   ApiErrorId.ERR_STORE_DAY_GATE_RESTRICTED.value)
    assert get_transfer(transfer["id"])["status"] == "IN_TRANSIT"


def test_a_restricted_gate_still_admits_a_sales_floor_ring(api):
    """PRD §2.10: "A `GATED_RESTRICTED` gate still admits sales-floor writes but refuses new
    backroom load"
    PRD §3.1: "a full dining room restricts the retail floor's backroom intake without
    shutting the floor itself"

    Design: Corner/validations/eligibility_gate_restricted_refuses_new_backroom_load
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 30})
    boat = _boat()
    restricted = post_guest_counts(day["id"], day["version"], 140, 1400000, 30, 15)
    assert restricted["conversion_gate"] == "GATED_RESTRICTED"

    data = validate_success(
        api.create_receipt(f.create_receipt_payload(
            loc["id"], day["id"], "R-1042-0110",
            [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")]), LEAD),
        201,
    )
    assert data["status"] == "DRAFT"


# ==========================================================================
# Corner queue B — endpoints (stale store-day version)
# ==========================================================================

def test_a_stale_store_day_version_is_refused_with_the_stale_status(api):
    """PRD §2.6: "Posting guest counts against a store day requires `expected_store_day_version`
    ... If the store day's `version` has advanced, the post is refused with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "The `expected_store_day_version` is mandatory and carries the `version` of
    the store day the caller last read"

    Design: Corner/endpoints/stale_store_day_version_returns_412_on_the_guest_count_write
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    stale_version = day["version"]
    advanced = post_guest_counts(day["id"], stale_version, 40, 400000, 10, 5)

    validate_error(
        api.post_guest_counts(day["id"], {
            "expected_store_day_version": stale_version,
            "restaurant_guest_count": 60,
            "restaurant_sales_cents": 600000,
            "waiting_area_shopper_count": 12,
            "waiting_area_converted_count": 6,
        }, MANAGER),
        ApiErrorId.ERR_STALE_VERSION.value,
    )


def test_a_stale_guest_count_write_leaves_the_day_untouched(api):
    """PRD §2.6: "The refusal is specifically version-driven"
    PRD §3.1: "Posting a count is a transition even when the day neither opens nor closes,
    and it has four distinct outcomes depending on where the count lands."

    Design: Corner/endpoints/stale_store_day_version_returns_412_on_the_guest_count_write
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    stale_version = day["version"]
    post_guest_counts(day["id"], stale_version, 40, 400000, 10, 5)
    api.post_guest_counts(day["id"], {
        "expected_store_day_version": stale_version,
        "restaurant_guest_count": 60,
        "restaurant_sales_cents": 600000,
        "waiting_area_shopper_count": 12,
        "waiting_area_converted_count": 6,
    }, MANAGER)

    current = get_store_day(day["id"])
    assert current["restaurant_guest_count"] == 40, "the stale write changed nothing"


# ==========================================================================
# Corner queue B — state_machines (void receiving)
# ==========================================================================

def test_voiding_a_transfer_within_tolerance_is_refused(api):
    """PRD §3.7: "A transfer may be voided only when it is `RECEIVED`, only when its
    `variance_bps` exceeds the brand's `transfer_variance_tolerance_bps` - the same
    threshold that would have permitted reconciliation now becomes the gate that permits
    reversal"
    PRD §2.12: "The receiving-tolerance rule is priority 27 and reports
    `ERR_TRANSFER_VARIANCE_EXCEEDED` (HTTP 422)."

    Design: Corner/state_machines/transfer_void_receiving_requires_the_received_state_and_a_tolerance_breach
    """
    brand, loc, day = setup_open_day(brand_overrides={"transfer_variance_tolerance_bps": 200,
                                                      "food_storage_corridor_units": 310})
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 40)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    validate_success(api.receive_transfer(transfer["id"], {"received_units": 40}, LEAD))

    validate_error(api.void_receiving(transfer["id"], MANAGER),
                   ApiErrorId.ERR_TRANSFER_VARIANCE_EXCEEDED.value)
    assert get_transfer(transfer["id"])["status"] == "RECEIVED"


def test_voiding_a_transfer_beyond_tolerance_succeeds(api):
    """PRD §3.7: "A larger shortfall cannot be reconciled at all and is refused with
    `ERR_TRANSFER_VARIANCE_EXCEEDED` (HTTP 422) at priority 27; such a transfer stays
    un-reconciled until it is voided or re-dispatched."
    PRD §3.7: "Voiding moves the status to `VOID_RECEIVING`"

    Design: Corner/state_machines/transfer_void_receiving_requires_the_received_state_and_a_tolerance_breach
    """
    brand, loc, day = setup_open_day(brand_overrides={"transfer_variance_tolerance_bps": 200,
                                                      "food_storage_corridor_units": 310})
    boat = _boat()
    transfer = create_transfer(loc["id"], day["id"], boat["id"], 40)
    validate_success(api.dispatch_transfer(transfer["id"], LEAD))
    received = validate_success(api.receive_transfer(transfer["id"], {"received_units": 30}, LEAD))
    assert received["variance_bps"] == 2500, "above the 200 bps tolerance"

    voided = validate_success(api.void_receiving(transfer["id"], MANAGER))

    assert voided["status"] == "VOID_RECEIVING"


# ==========================================================================
# Corner queue B — rbac
# ==========================================================================

def test_the_planner_cannot_ring_a_retail_receipt(api):
    """PRD §2.1: "A `RetailLead` alone rings receipts, reconciles and settles them"
    PRD §2.1: "Presenting a well-formed role that is not permitted for the requested
    operation is a different failure and is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/assortment_planner_cannot_ring_retail_or_close_a_store_day
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    payload = f.create_receipt_payload(loc["id"], day["id"], "R-1042-0090",
                                       [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")])

    validate_error(api.create_receipt(payload, PLANNER), ApiErrorId.ERR_UNAUTHORIZED.value)
    validate_success(api.create_receipt(payload, LEAD), 201)


def test_the_manager_cannot_publish_a_planogram(api):
    """PRD §2.1: "An `AssortmentPlanner` alone creates items, creates and updates planogram
    versions, publishes and retires them"
    PRD §2.1: "An `AssortmentPlanner` alone creates items, creates and updates planogram
    versions, publishes and retires them, and creates and reshapes planogram slots"

    Design: Corner/rbac/assortment_planner_cannot_ring_retail_or_close_a_store_day
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    boat = _boat()
    version = api.create_planogram_version(
        f.create_planogram_version_payload(loc["id"], effective_date="2026-10-01T00:00:00Z"),
        PLANNER).json()["data"]
    for pos in range(1, 7):
        api.create_planogram_slot(
            f.create_planogram_slot_payload(version["id"], boat["id"], pos), PLANNER)

    validate_error(api.publish_planogram_version(version["id"], MANAGER),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_platform_admin_configures_but_cannot_operate_the_retail_floor(api):
    """PRD §2.1: "A `PlatformAdmin` alone creates and updates the chain-level configuration"
    PRD §2.1: "An `AssortmentPlanner` alone creates items"

    Design: Corner/rbac/platform_admin_can_configure_but_cannot_operate_the_retail_floor
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})

    brands = validate_success(api.list_brands(ADMIN))
    assert brands, "the brand read is shared with PlatformAdmin"

    validate_error(api.create_item(f.create_item_payload(sku="ITM-ADMIN-0001"), ADMIN),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_brand_configuration_is_admin_exclusive(api):
    """PRD §2.1: "A `PlatformAdmin` alone creates and updates the chain-level configuration
    - brand creation and brand update"
    PRD §3.7: "A `PlatformAdmin` later updates the brand to change any of those
    configuration values"

    Design: Corner/rbac/platform_admin_can_configure_but_cannot_operate_the_retail_floor
    """
    brand, loc, day = setup_open_day(brand_overrides={"food_storage_corridor_units": 310})

    updated = validate_success(api.update_brand(brand["id"], {"fiscal_period": "2026-Q4"}, ADMIN))
    assert updated["fiscal_period"] == "2026-Q4"
    validate_error(api.update_brand(brand["id"], {"fiscal_period": "2026-Q5"}, MANAGER),
                   ApiErrorId.ERR_UNAUTHORIZED.value)


def test_a_shift_backed_role_persists_the_acting_shift_on_the_check(api):
    """PRD §2.1: "When `X-User-Role` is `Cashier` or `Server`, `X-User-ID` is the `id` of
    the acting `StaffShift`"
    PRD §2.1: "the `presented_shift_id` carried on a `GuestCheck` is checked against the caller"

    Design: Corner/rbac/shift_backed_roles_require_a_real_shift_identifier
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    validate_success(api.set_clock("2026-09-21T12:00:00Z", ADMIN))
    shift = create_shift(loc["id"], employee_id="E-801", workcode="SERVER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-21T08:00:00Z", end_utc="2026-09-21T12:00:00Z")
    start_shift(shift["id"])

    check = validate_success(api.create_guest_check(
        f.create_guest_check_payload(loc["id"], day["id"], shift["id"], table_number="18",
                                     restaurant_guest_count=2, restaurant_subtotal_cents=3000),
        server_for(shift["id"])), 201)

    assert check["presented_shift_id"] == shift["id"]
    rows, meta = validate_paginated(
        api.list_guest_checks(MANAGER, {"presented_shift_id": shift["id"]})
    )
    assert meta["total_count"] == 1


def test_a_server_cannot_finalize_a_check(api):
    """PRD §2.1: "A `Cashier` alone finalizes and settles combined checks, and shares tip
    posting, check attachment and check reads. A `Server` alone opens dining checks"
    PRD §2.1: "Presenting a well-formed role that is not permitted for the requested
    operation is a different failure and is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/shift_backed_roles_require_a_real_shift_identifier
    """
    brand, loc = setup_store(brand_overrides={"food_storage_corridor_units": 310})
    day = open_store_day(loc["id"], "2026-09-21T00:00:00Z")
    validate_success(api.set_clock("2026-09-21T12:00:00Z", ADMIN))
    shift = create_shift(loc["id"], employee_id="E-802", workcode="SERVER",
                         tip_eligible_claim=True,
                         start_utc="2026-09-21T08:00:00Z", end_utc="2026-09-21T12:00:00Z")
    start_shift(shift["id"])
    check = create_check(loc["id"], day["id"], shift["id"], restaurant_subtotal_cents=3000)

    validate_error(api.finalize_guest_check(check["id"], server_for(shift["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED.value)