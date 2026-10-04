"""Composite setup helpers for the closeout deal workflow.

Every helper builds its preconditions from scratch through the API's own
endpoints, because each test starts against an empty database.  Setup calls
go through the lenient success validator so that a broken precondition
surfaces as "Setup failed" rather than as a confusing assertion deep inside
a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import JURISDICTION_CA
from .factories import (
    complete_screening_payload,
    create_aisle_assignment_payload,
    create_allocation_payload,
    create_disposition_payload,
    create_event_payload,
    create_jurisdiction_rule_payload,
    create_lot_payload,
    create_member_payload,
    create_store_payload,
    create_vendor_payload,
    price_lot_payload,
    purchase_payload,
)
from .test_users import (
    ALLOCATION_MANAGER_USER,
    BUYER_USER,
    PRICING_LEAD_USER,
    SAFETY_OFFICER_USER,
    STORE_MANAGER_USER,
    TEST_USERS,
    make_allocation_manager_headers,
    make_club_member_headers,
    make_pricing_lead_headers,
    make_safety_officer_headers,
    make_sourcing_buyer_headers,
    make_store_manager_headers,
)

ADMIN = TEST_USERS["admin_headers"]
BUYER = TEST_USERS["sourcing_buyer_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]
OFFICER_ALT = TEST_USERS["safety_officer_alt_headers"]
PRICING = TEST_USERS["pricing_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
FLOOR = TEST_USERS["store_manager_headers"]
GUEST = TEST_USERS["anonymous_headers"]

LIST_ALL = {"limit": 100, "offset": 0}


def _setup_fail(step: str, resp) -> AssertionError:
    return AssertionError(f"Setup failed at {step}: {resp.status_code} {resp.text}")


# ==========================================================================
# Tier 0 -- single-call helpers
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_jurisdiction(**overrides) -> dict:
    overrides.setdefault("jurisdiction_code", JURISDICTION_CA["jurisdiction_code"])
    return get_success_data(api.create_jurisdiction_rule(
        create_jurisdiction_rule_payload(**overrides), PRICING))


def create_default_jurisdiction() -> dict:
    """The was/now-window jurisdiction (CA) used by most scenarios."""
    return get_success_data(api.create_jurisdiction_rule(dict(JURISDICTION_CA), PRICING))


def create_vendor(**overrides) -> dict:
    return get_success_data(api.create_vendor(create_vendor_payload(**overrides), BUYER))


def create_store(jurisdiction_id: str, **overrides) -> dict:
    return get_success_data(api.create_store(
        create_store_payload(jurisdiction_id, **overrides), ADMIN))


def create_lot(vendor_id: str, jurisdiction_id: str, buyer_headers=None, **overrides) -> dict:
    """Create a lot in SOURCED.  created_by_user_id is the caller's X-User-ID,
    which becomes the segregation-of-duties anchor for screening."""
    hdrs = buyer_headers if buyer_headers is not None else BUYER
    return get_success_data(api.create_lot(
        create_lot_payload(vendor_id, jurisdiction_id, **overrides), hdrs))


def create_member(home_store_id: str, **overrides) -> dict:
    return get_success_data(api.create_member(
        create_member_payload(home_store_id, **overrides), GUEST))


def open_screening(lot_id: str, officer_headers=None) -> dict:
    hdrs = officer_headers if officer_headers is not None else OFFICER
    return get_success_data(api.create_screening(lot_id, hdrs))


def complete_screening(lot_id: str, screening_id: str, officer_headers=None, **overrides) -> dict:
    hdrs = officer_headers if officer_headers is not None else OFFICER
    return get_success_data(api.complete_screening(
        lot_id, screening_id, complete_screening_payload(**overrides), hdrs))


def pass_screening(lot_id: str, officer_headers=None, **grade_overrides) -> dict:
    """Open + complete a passing screening.  Grade counts default to all-A at
    the lot's quantity_total unless overridden."""
    screening = open_screening(lot_id, officer_headers)
    return complete_screening(lot_id, screening["id"], officer_headers, **grade_overrides)


def price_lot(lot_id: str, **overrides) -> dict:
    return get_success_data(api.price_lot(lot_id, price_lot_payload(**overrides), PRICING))


def propose_allocation(lot_id: str, store_id: str, qty_requested: int) -> dict:
    return get_success_data(api.create_allocation(
        lot_id, create_allocation_payload(store_id, qty_requested), ALLOCATOR))


def commit_allocations(lot_id: str) -> dict:
    return get_success_data(api.commit_allocations(lot_id, ALLOCATOR))


def ship_allocation(lot_id: str, allocation_id: str) -> dict:
    return get_success_data(api.ship_allocation(lot_id, allocation_id, ALLOCATOR))


def receive_allocation(lot_id: str, allocation_id: str) -> dict:
    return get_success_data(api.receive_allocation(lot_id, allocation_id, ALLOCATOR))


def get_store(store_id: str) -> dict:
    return get_success_data(api.get_store(store_id, ADMIN))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api.get_lot(lot_id, ADMIN))


def get_lot_summary(lot_id: str) -> dict:
    return get_success_data(api.get_lot_summary(lot_id, ADMIN))


def create_assignment(store_id: str, lot_id: str, expected_store_version: int,
                      **overrides) -> dict:
    return get_success_data(api.create_aisle_assignment(
        store_id,
        create_aisle_assignment_payload(lot_id, expected_store_version, **overrides),
        FLOOR))


def assign_aisle(store_id: str, lot_id: str, **overrides) -> dict:
    """Create an aisle assignment, reading the current store version first so
    the OCC field is always fresh."""
    version = get_store(store_id)["version"]
    return create_assignment(store_id, lot_id, version, **overrides)


def create_event(lot_id: str, **overrides) -> dict:
    return get_success_data(api.create_early_access_event(
        lot_id, create_event_payload(**overrides), PRICING))


def guest_purchase(store_id: str, lot_id: str, qty: int) -> dict:
    return get_success_data(api.create_purchase(
        store_id, purchase_payload(lot_id, qty), GUEST))


def member_purchase(store_id: str, lot_id: str, qty: int, member_id: str) -> dict:
    return get_success_data(api.create_purchase(
        store_id, purchase_payload(lot_id, qty, member_id=member_id),
        make_club_member_headers(member_id)))


def create_disposition(lot_id: str, **overrides) -> dict:
    """Create a disposition, reading the current lot version first so the OCC
    field is always fresh (pass expected_lot_version explicitly to pin)."""
    if "expected_lot_version" not in overrides:
        overrides["expected_lot_version"] = get_lot(lot_id)["version"]
    return get_success_data(api.create_disposition(
        lot_id, create_disposition_payload(**overrides), BUYER))


def apply_disposition(lot_id: str, disposition_id: str) -> dict:
    return get_success_data(api.apply_disposition(lot_id, disposition_id, BUYER))


# ==========================================================================
# Tier 1 -- lot lifecycle progression
# ==========================================================================

def create_cleared_lot(vendor_id: str, jurisdiction_id: str,
                       buyer_headers=None, officer_headers=None, **lot_overrides) -> dict:
    """SOURCED -> SCREENING -> CLEARED via one passing screening."""
    lot = create_lot(vendor_id, jurisdiction_id, buyer_headers, **lot_overrides)
    pass_screening(lot["id"], officer_headers,
                   qty_grade_a=lot["quantity_total"], qty_grade_b=0, qty_grade_c=0)
    return get_lot(lot["id"])


def create_priced_lot(vendor_id: str, jurisdiction_id: str,
                      buyer_headers=None, officer_headers=None,
                      lot_overrides=None, **price_overrides) -> dict:
    """Cleared lot priced (CLEARED -> PRICED)."""
    lot = create_cleared_lot(vendor_id, jurisdiction_id, buyer_headers, officer_headers,
                             **(lot_overrides or {}))
    return price_lot(lot["id"], **price_overrides)


# ==========================================================================
# Tier 2 -- on-sale scenarios
# ==========================================================================

def setup_on_sale_lot(jurisdiction_id=None, store_tier="TIER_1", qty=100,
                      alloc_qty=60, retail_price_cents=4000,
                      lot_overrides=None, receive=True):
    """Full pipeline: jurisdiction + vendor + store + lot -> screened ->
    priced -> allocation proposed and committed (lot -> ON_SALE).

    With receive=True the allocation is also shipped and received, giving the
    store alloc_qty units of store_on_hand_qty.  Returns a dict with the lot,
    store, allocation, jurisdiction, and vendor records."""
    jur = jurisdiction_id or create_default_jurisdiction()["id"]
    vendor = create_vendor()
    store = create_store(jur, performance_tier=store_tier)
    lot = create_priced_lot(vendor["id"], jur,
                            lot_overrides={"quantity_total": qty,
                                           "est_sellable_qty": qty,
                                           **(lot_overrides or {})},
                            retail_price_cents=retail_price_cents)
    allocation = propose_allocation(lot["id"], store["id"], alloc_qty)
    commit_allocations(lot["id"])
    if receive:
        ship_allocation(lot["id"], allocation["id"])
        allocation = receive_allocation(lot["id"], allocation["id"])
    return {
        "jurisdiction_id": jur,
        "vendor": vendor,
        "store": store,
        "lot": get_lot(lot["id"]),
        "allocation": get_success_data(
            api.get_allocation(lot["id"], allocation["id"], ADMIN)),
    }


def setup_sellable_store(jurisdiction_id=None, qty=100, alloc_qty=60,
                         retail_price_cents=4000, daily_unit_limit=10,
                         lot_overrides=None, store_tier="TIER_1"):
    """On-sale lot with stock received AND an ACTIVE aisle assignment, ready
    for purchases.  Returns the setup dict plus the aisle assignment."""
    ctx = setup_on_sale_lot(jurisdiction_id, store_tier, qty, alloc_qty,
                            retail_price_cents, lot_overrides, receive=True)
    assignment = assign_aisle(ctx["store"]["id"], ctx["lot"]["id"],
                              daily_unit_limit=daily_unit_limit)
    ctx["assignment"] = assignment
    return ctx


def setup_disposition_review_lot(qty=100, alloc_qty=60,
                                 pace_target_units_per_week=10):
    """On-sale lot with zero sales; advancing the clock three selling days
    triggers the pacing review.  Returns (ctx, lot_at_review) with the lot in
    DISPOSITION_REVIEW."""
    ctx = setup_on_sale_lot(
        qty=qty, alloc_qty=alloc_qty,
        lot_overrides={"pace_target_units_per_week": pace_target_units_per_week},
        receive=False)
    set_clock("2026-09-04T00:00:00Z")
    lot = get_lot(ctx["lot"]["id"])
    assert lot["commercial_status"] == "DISPOSITION_REVIEW", (
        f"Setup failed: lot did not enter DISPOSITION_REVIEW, got "
        f"{lot['commercial_status']}")
    ctx["lot"] = lot
    return ctx
