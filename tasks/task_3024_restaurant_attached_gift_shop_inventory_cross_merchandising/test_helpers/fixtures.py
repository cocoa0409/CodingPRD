"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and returns plain dicts as read off the
response bodies. Setup calls use the lenient `get_success_data()` validator so a
broken precondition reports a "Setup failed" message rather than an assertion
deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import (
    TEST_USERS,
    make_cashier_headers,
    make_server_headers,
)

# --- Role header shortcuts ------------------------------------------------
ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["assortment_planner_headers"]
MANAGER = TEST_USERS["boutique_manager_headers"]
LEAD = TEST_USERS["retail_lead_headers"]
RETAIL_CASHIER = TEST_USERS["retail_cashier_headers"]
ANON = TEST_USERS["anonymous_headers"]

# Shared constants for the entity-backed roles. These carry a placeholder
# X-User-ID and are safe only for calls that do NOT compare a foreign key
# against the caller. Ownership-gated calls must use make_cashier_headers() /
# make_server_headers() with the real StaffShift id.
CASHIER = TEST_USERS["cashier_headers"]
SERVER = TEST_USERS["server_headers"]


def cashier_for(shift_id: str) -> dict:
    return make_cashier_headers(shift_id)


def server_for(shift_id: str) -> dict:
    return make_server_headers(shift_id)


# ==========================================================================
# Tier 0 — clock
# ==========================================================================

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ==========================================================================
# Tier 1 — single-entity creation
# ==========================================================================

def create_brand(**overrides) -> dict:
    return get_success_data(api_client.create_brand(f.create_brand_payload(**overrides), ADMIN), 201)


def create_location(brand_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_location(f.create_location_payload(brand_id, **overrides), ADMIN), 201
    )


def create_item(**overrides) -> dict:
    return get_success_data(api_client.create_item(f.create_item_payload(**overrides), PLANNER), 201)


def open_store_day(location_id: str, business_date: str = "2026-09-01T00:00:00Z", **overrides) -> dict:
    return get_success_data(
        api_client.create_store_day(f.create_store_day_payload(location_id, business_date, **overrides), MANAGER),
        201,
    )


def create_shift(location_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_staff_shift(f.create_staff_shift_payload(location_id, **overrides), MANAGER), 201
    )


def start_shift(shift_id: str) -> dict:
    return get_success_data(api_client.start_staff_shift(shift_id, MANAGER))


def create_check(location_id: str, store_day_id: str, shift_id: str, **overrides) -> dict:
    """Open a dining check as the presenting shift (ownership-gated)."""
    payload = f.create_guest_check_payload(location_id, store_day_id, shift_id, **overrides)
    return get_success_data(
        api_client.create_guest_check(payload, make_server_headers(shift_id)), 201
    )


def create_receipt(location_id: str, store_day_id: str, lines, receipt_number: str,
                   headers=None, **overrides) -> dict:
    payload = f.create_receipt_payload(location_id, store_day_id, receipt_number, lines, **overrides)
    return get_success_data(api_client.create_receipt(payload, headers or LEAD), 201)


def create_transfer(location_id: str, store_day_id: str, item_id: str, declared_units: int,
                    **overrides) -> dict:
    payload = f.create_transfer_payload(
        location_id, store_day_id, item_id, declared_units, **overrides
    )
    return get_success_data(api_client.create_transfer(payload, LEAD), 201)


def create_capacity_reading(location_id: str, payload, **kwargs) -> dict:
    return get_success_data(
        api_client.create_capacity_reading(location_id, payload, MANAGER), 201
    )


def create_clearance_schedule(location_id: str, item_id: str, expected_item_version: int,
                              **overrides) -> dict:
    payload = f.create_clearance_schedule_payload(
        location_id, item_id, expected_item_version, **overrides
    )
    return get_success_data(api_client.create_clearance_schedule(payload, MANAGER), 201)


def create_planogram_version(location_id: str, **overrides) -> dict:
    payload = f.create_planogram_version_payload(location_id, **overrides)
    return get_success_data(api_client.create_planogram_version(payload, PLANNER), 201)


def create_planogram_slot(version_id: str, item_id: str, slot_position: int, **overrides) -> dict:
    payload = f.create_planogram_slot_payload(version_id, item_id, slot_position, **overrides)
    return get_success_data(api_client.create_planogram_slot(payload, PLANNER), 201)


# ==========================================================================
# Tier 1 — state progression
# ==========================================================================

def post_guest_counts(day_id: str, expected_version: int, restaurant_guest_count: int,
                      restaurant_sales_cents: int = 0,
                      waiting_area_shopper_count: int = 0,
                      waiting_area_converted_count: int = 0,
                      headers=None) -> dict:
    payload = {
        "expected_store_day_version": expected_version,
        "restaurant_guest_count": restaurant_guest_count,
        "restaurant_sales_cents": restaurant_sales_cents,
        "waiting_area_shopper_count": waiting_area_shopper_count,
        "waiting_area_converted_count": waiting_area_converted_count,
    }
    return get_success_data(api_client.post_guest_counts(day_id, payload, headers or MANAGER))


def close_store_day(day_id: str, expected_version: int) -> dict:
    return get_success_data(
        api_client.close_store_day(day_id, {"expected_store_day_version": expected_version}, MANAGER)
    )


def reconcile_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.reconcile_receipt(receipt_id, LEAD))


def settle_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.settle_receipt(receipt_id, {}, LEAD))


def dispute_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.dispute_receipt(receipt_id, MANAGER))


def resolve_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.resolve_receipt(receipt_id, MANAGER))


def finalize_check(check_id: str, shift_id: str) -> dict:
    return get_success_data(api_client.finalize_guest_check(check_id, make_cashier_headers(shift_id)))


def post_tip(check_id: str, tip_cents: int, shift_id: str) -> dict:
    return get_success_data(api_client.post_tip(check_id, {"tip_cents": tip_cents}, make_cashier_headers(shift_id)))


def get_item(item_id: str) -> dict:
    return get_success_data(api_client.get_item(item_id, PLANNER))


def get_store_day(day_id: str) -> dict:
    return get_success_data(api_client.get_store_day(day_id, MANAGER))


def current_day_version(day_id: str) -> int:
    """Re-read the day's live version.

    PRD 2.6 makes `expected_store_day_version` mandatory and non-skipped on the
    guest-count post, and PRD 2.8 increments the day's version on every cascade,
    so a fixture that holds a version captured before an intervening receipt write
    must refresh it before posting again.
    """
    return get_store_day(day_id)["version"]


def get_location(location_id: str) -> dict:
    return get_success_data(api_client.get_location(location_id, MANAGER))


def get_brand(brand_id: str) -> dict:
    return get_success_data(api_client.get_brand(brand_id, MANAGER))


def get_receipt(receipt_id: str) -> dict:
    return get_success_data(api_client.get_receipt(receipt_id, LEAD))


def get_clearance_schedule(schedule_id: str) -> dict:
    return get_success_data(api_client.get_clearance_schedule(schedule_id, MANAGER))


def get_transfer(transfer_id: str) -> dict:
    return get_success_data(api_client.get_transfer(transfer_id, LEAD))


# ==========================================================================
# Tier 2 — entity hierarchy
# ==========================================================================

def setup_store(brand_overrides=None, location_overrides=None):
    """Brand + one location. Returns (brand, location)."""
    brand = create_brand(**(brand_overrides or {}))
    location = create_location(brand["id"], **(location_overrides or {}))
    return brand, location


def setup_open_day(brand_overrides=None, location_overrides=None,
                   business_date="2026-09-01T00:00:00Z"):
    """Brand + location + one OPEN store day. Returns (brand, location, day)."""
    brand, location = setup_store(brand_overrides, location_overrides)
    day = open_store_day(location["id"], business_date)
    return brand, location, day


def setup_day_with_items(item_overrides_list=(), business_date="2026-09-01T00:00:00Z",
                         brand_overrides=None, location_overrides=None):
    """Brand + location + OPEN day + N items. Returns (brand, location, day, [items])."""
    brand, location, day = setup_open_day(brand_overrides, location_overrides, business_date)
    items = [create_item(**ov) for ov in item_overrides_list]
    return brand, location, day, items


# ==========================================================================
# Tier 3 — full lifecycle shortcuts
# ==========================================================================

def scheduled_started_shift(location_id: str, **overrides) -> dict:
    """Create a shift and start it. Returns the IN_PROGRESS shift."""
    shift = create_shift(location_id, **overrides)
    return start_shift(shift["id"])


def reconciled_receipt(location_id: str, store_day_id: str, lines, receipt_number: str,
                       headers=None, **overrides) -> dict:
    receipt = create_receipt(location_id, store_day_id, lines, receipt_number, headers, **overrides)
    return reconcile_receipt(receipt["id"])


def settled_receipt(location_id: str, store_day_id: str, lines, receipt_number: str,
                    headers=None, **overrides) -> dict:
    receipt = reconciled_receipt(location_id, store_day_id, lines, receipt_number, headers, **overrides)
    return settle_receipt(receipt["id"])


def received_transfer(location_id: str, store_day_id: str, item_id: str,
                      declared_units: int, received_units=None) -> dict:
    """Create → dispatch → receive. Returns the RECEIVED transfer."""
    transfer = create_transfer(location_id, store_day_id, item_id, declared_units,
                               received_units=0, receiving_zone="BACKROOM")
    get_success_data(api_client.dispatch_transfer(transfer["id"], LEAD))
    got = received_units if received_units is not None else declared_units
    return get_success_data(
        api_client.receive_transfer(transfer["id"], {"received_units": got}, LEAD)
    )


def dispatched_transfer(location_id: str, store_day_id: str, item_id: str, declared_units: int) -> dict:
    transfer = create_transfer(location_id, store_day_id, item_id, declared_units,
                               received_units=0, receiving_zone="BACKROOM")
    return get_success_data(api_client.dispatch_transfer(transfer["id"], LEAD))


def stock_item(location_id: str, store_day_id: str, item_id: str, units: int) -> dict:
    """Put `units` on hand for the item via a clean BACKROOM receiving."""
    return received_transfer(location_id, store_day_id, item_id, units, units)


def stock_item_on_separate_day(location_id: str, item_id: str, units: int,
                               stocking_date: str = "2026-09-19T00:00:00Z",
                               arrival_day_id: str = None) -> dict:
    """Stock the item without disturbing a business day the caller then mutates.

    A receiving appends a capacity reading and can flip the receiving day's gate
    to GATED_RESTRICTED (PRD 3.7), so tests whose later steps post guest counts
    against that same day against a *cached* version will trip the mandatory
    `expected_store_day_version` check (PRD 2.6). Stocking on a separate day
    leaves the day under test untouched.
    """
    if arrival_day_id is None:
        arrival_day_id = open_store_day(location_id, stocking_date)["id"]
    return stock_item(location_id, arrival_day_id, item_id, units)


def finished_check(location_id: str, store_day_id: str, shift_id: str,
                   tip_cents=None, **overrides) -> dict:
    """Open → (tip) → finalize a check presented by `shift_id`."""
    check = create_check(location_id, store_day_id, shift_id, **overrides)
    if tip_cents is not None:
        post_tip(check["id"], tip_cents, shift_id)
    return finalize_check(check["id"], shift_id)


# ==========================================================================
# Tier 4 — accumulation / threshold targeting
# ==========================================================================

def activate_clearance(item_id: str, location_id: str,
                       start_date="2026-09-01T00:00:00Z", end_date="2026-10-01T00:00:00Z"):
    """Create a schedule against the item's live version and activate it.
    Returns the ACTIVE schedule (stage S1)."""
    item = get_item(item_id)
    schedule = create_clearance_schedule(
        location_id, item_id, item["version"], start_date=start_date, end_date=end_date
    )
    return get_success_data(api_client.activate_clearance_schedule(schedule["id"], MANAGER))


def advance_cadence(trigger_transfer_id: str, to_iso8601: str) -> dict:
    """Walk the clearance cadence forward by raising a marketing-reset event.
    The endpoint also sets the logical clock. Returns the store day."""
    return get_success_data(
        api_client.advance_transfer(trigger_transfer_id, {"from_iso8601": to_iso8601}, MANAGER)
    )


def clearance_at_s4(location_id: str, transfer_id: str, item_id: str,
                    start_date="2026-09-01T00:00:00Z", end_date="2026-10-01T00:00:00Z",
                    activated_clock="2026-09-01T00:00:00Z"):
    """Activate a schedule and walk four whole weeks so the stage reaches S4.
    Returns (item, schedule)."""
    schedule = activate_clearance(item_id, location_id, start_date, end_date)
    advance_cadence(transfer_id, shift_iso(activated_clock, days=28))
    return get_item(item_id), get_clearance_schedule(schedule["id"])


def shift_iso(iso: str, days: int = 0, hours: int = 0, seconds: int = 0) -> str:
    """Small helper for building ISO instants relative to another."""
    from datetime import datetime, timedelta

    dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ") + timedelta(
        days=days, hours=hours, seconds=seconds
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ==========================================================================
# Tier 5 — finalization / terminal state
# ==========================================================================

def closed_day_with_settled_receipt(location_id: str, business_date: str, lines,
                                    receipt_number: str, guest_count: int):
    """Open a day, ring+reconcile+settle a receipt, close the day.
    The close accepts `expected_store_day_version`, so the day's version after
    the receipt writes is re-read before closing. Returns (day, receipt)."""
    day = open_store_day(location_id, business_date)
    receipt = settled_receipt(location_id, day["id"], lines, receipt_number)
    current = get_store_day(day["id"])
    day = close_store_day(day["id"], current["version"])
    return day, get_receipt(receipt["id"])


def store_day_with_disputed_receipt(location_id: str, business_date: str, item_id: str,
                                    receipt_number: str = "R-1042-0011",
                                    guest_count: int = 30):
    """Build a store day whose gate has been re-derived to SUSPENDED: a low guest
    count plus at least one DISPUTED receipt of that day.

    Returns (day_at_suspended_gate, disputed_receipt).
    """
    day = open_store_day(location_id, business_date)
    day = post_guest_counts(day["id"], day["version"], guest_count, 300000, 8, 4)
    receipt = create_receipt(
        location_id, day["id"],
        [f.retail_line(item_id, 1, 6400)],
        receipt_number,
    )
    receipt = reconcile_receipt(receipt["id"])
    receipt = dispute_receipt(receipt["id"])
    # Re-post the same low count so the gate is re-derived with the dispute live.
    # The day's version advanced on the receipt create/reconcile/dispute cascades
    # (PRD 2.8), so the expected version is re-read rather than the stale one.
    day = post_guest_counts(day["id"], current_day_version(day["id"]), guest_count, 300000, 8, 4)
    return day, receipt