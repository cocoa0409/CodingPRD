"""Composite setup helpers for the warehouse club cross-dock domain.

Every helper builds its preconditions from scratch against a freshly restarted
server (the runner restarts the API before every test, so the database starts
empty and the logical clock reads 2026-09-01T00:00:00Z).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_allocation_payload,
    create_appointment_payload,
    create_club_payload,
    create_complaint_payload,
    create_cross_dock_run_payload,
    create_depot_payload,
    create_item_payload,
    create_member_payload,
    create_pallet_payload,
    create_purchase_payload,
    create_region_payload,
    create_vendor_payload,
)
from .test_users import TEST_USERS, make_vendor_rep_headers

RO = TEST_USERS["regional_ops_headers"]
CM = TEST_USERS["category_manager_headers"]
DM = TEST_USERS["depot_manager_headers"]
DP = TEST_USERS["depot_planner_headers"]
MD = TEST_USERS["membership_desk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity setup
# ---------------------------------------------------------------------------

def create_region(**overrides):
    return get_success_data(api.create_region(create_region_payload(**overrides), RO))


def create_vendor(**overrides):
    return get_success_data(api.create_vendor(create_vendor_payload(**overrides), RO))


def create_club(region_id, **overrides):
    return get_success_data(api.create_club(create_club_payload(region_id, **overrides), RO))


def create_depot(region_id, **overrides):
    return get_success_data(api.create_depot(create_depot_payload(region_id, **overrides), DM))


def create_draft_item(vendor_id, **overrides):
    return get_success_data(api.create_item(create_item_payload(vendor_id, **overrides), CM))


def create_active_item(vendor_id, **overrides):
    """Create an item and activate it. Returns the ACTIVE item."""
    item = create_draft_item(vendor_id, **overrides)
    return get_success_data(api.activate_item(item["id"], CM))


def create_member(club_id, **overrides):
    return get_success_data(api.create_member(create_member_payload(club_id, **overrides), MD))


def setup_region_vendor(**vendor_overrides):
    region = create_region()
    vendor = create_vendor(**vendor_overrides)
    return region, vendor


# ---------------------------------------------------------------------------
# Tier 2: receiving dock — appointments and pallets
# ---------------------------------------------------------------------------

def book_appointment(depot_id, vendor_id, delivery_date, **overrides):
    """Book an appointment as the vendor's own representative."""
    payload = create_appointment_payload(depot_id, vendor_id, delivery_date, **overrides)
    return get_success_data(api.create_appointment(payload, make_vendor_rep_headers(vendor_id)))


def check_in_appointment(appointment_id):
    return get_success_data(api.check_in_appointment(appointment_id, DM))


def receive_pallet(appointment_id, item_id, unit_qty):
    payload = create_pallet_payload(appointment_id, item_id, unit_qty)
    return get_success_data(api.create_pallet(payload, DM))


def setup_received_pallets(delivery_date="2026-09-02", num_pallets=1, item_overrides=None,
                           club_capacity=40, member_base=1000, appointment_start="09:00",
                           checkin_time=None, pallet_unit_qty=None):
    """Full receiving-dock setup ending with pallets RECEIVED on delivery_date.

    Clock ends at checkin_time (default delivery_date 09:05). Returns a dict
    with region, vendor, club, depot, item, appointment, pallets.
    """
    if checkin_time is None:
        checkin_time = f"{delivery_date}T09:05:00Z"
    region = create_region()
    vendor = create_vendor()
    club = create_club(region["id"], floor_slot_capacity=club_capacity, member_base=member_base)
    depot = create_depot(region["id"])
    item = create_active_item(vendor["id"], **(item_overrides or {}))
    appt = book_appointment(depot["id"], vendor["id"], delivery_date,
                            start_time=appointment_start, pallet_count=num_pallets)
    api.set_clock(checkin_time, RO)
    check_in_appointment(appt["id"])
    qty = pallet_unit_qty if pallet_unit_qty is not None else item["pallet_qty_units"]
    pallets = [receive_pallet(appt["id"], item["id"], qty) for _ in range(num_pallets)]
    return {
        "region": region, "vendor": vendor, "club": club, "depot": depot,
        "item": item, "appointment": appt, "pallets": pallets,
    }


# ---------------------------------------------------------------------------
# Tier 3: cross-dock run and allocation chaining
# ---------------------------------------------------------------------------

def create_open_run(depot_id, run_date="2026-09-02", cutoff_time="16:00"):
    payload = create_cross_dock_run_payload(depot_id, run_date, cutoff_time=cutoff_time)
    return get_success_data(api.create_cross_dock_run(payload, DP))


def allocate_pallet(run_id, pallet_id, club_id, expected_run_version,
                    regional_ops_approved=None):
    """Propose one allocation, chaining the run version via the OCC echo.

    Returns the created Allocation (status PROPOSED).
    """
    overrides = {}
    if regional_ops_approved is not None:
        overrides["regional_ops_approved"] = regional_ops_approved
    payload = create_allocation_payload(pallet_id, club_id, expected_run_version, **overrides)
    return get_success_data(api.create_allocation(run_id, payload, DP))


def allocate_many(run_id, run_version, pallets, club_id, approved_from_index=None):
    """Allocate a list of pallets to one club in order, chaining run versions.

    approved_from_index: when set, allocations at position >= this index carry
    regional_ops_approved: true. Returns (allocations, final_run_version).
    """
    allocations = []
    version = run_version
    for i, pallet in enumerate(pallets):
        approved = True if (approved_from_index is not None and i >= approved_from_index) else None
        alloc = allocate_pallet(run_id, pallet["id"], club_id, version, approved)
        allocations.append(alloc)
        version = alloc["run_version"]
    return allocations, version


def setup_run_with_allocations(delivery_date="2026-09-02", num_pallets=1, club_capacity=40,
                               approved_from_index=None, item_overrides=None):
    """Received pallets + OPEN run for the same date + all pallets allocated.

    Returns a dict with the receiving-dock context plus run and allocations.
    """
    ctx = setup_received_pallets(delivery_date=delivery_date, num_pallets=num_pallets,
                                 item_overrides=item_overrides, club_capacity=club_capacity)
    run = create_open_run(ctx["depot"]["id"], run_date=delivery_date)
    allocations, final_version = allocate_many(
        run["id"], run["version"], ctx["pallets"], ctx["club"]["id"],
        approved_from_index=approved_from_index,
    )
    ctx.update({"run": run, "allocations": allocations, "run_version": final_version})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: purchases and complaints
# ---------------------------------------------------------------------------

def record_purchase(member_id, club_id, item_id, unit_qty):
    payload = create_purchase_payload(member_id, club_id, item_id, unit_qty)
    return get_success_data(api.create_purchase(payload, MD))


def file_complaint(member_id, item_id, category):
    payload = create_complaint_payload(member_id, item_id, category)
    return get_success_data(api.create_complaint(payload, MD))


# ---------------------------------------------------------------------------
# Tier 5: chargeback lifecycles
# ---------------------------------------------------------------------------

def confirm_chargeback(chargeback_id, vendor_id):
    """Appeal (as the owning vendor rep) then resolve with CONFIRM."""
    get_success_data(api.appeal_chargeback(chargeback_id, make_vendor_rep_headers(vendor_id)))
    return get_success_data(api.resolve_chargeback(chargeback_id, {"outcome": "CONFIRM"}, DM))


def setup_vendor_with_confirmed_no_shows(num_no_shows, delivery_date="2026-09-01",
                                         rollover_to="2026-09-02T00:00:01Z",
                                         dock_open="08:00", dock_close="18:00"):
    """Vendor with `num_no_shows` CONFIRMED NO_SHOW chargebacks.

    Books one never-checked-in appointment per no-show, advances the clock past
    the delivery date end-of-day (firing auto NO_SHOW + assessment), then
    appeals and CONFIRMs each chargeback. Returns (region, vendor, depot,
    list of chargebacks). Clock ends at `rollover_to`.
    """
    region = create_region()
    vendor = create_vendor()
    depot = create_depot(region["id"], dock_hours_open=dock_open, dock_hours_close=dock_close)
    base_hour = int(dock_open.split(":")[0])
    for i in range(num_no_shows):
        start = f"{base_hour + i:02d}:00"
        end = f"{base_hour + i:02d}:30"
        book_appointment(depot["id"], vendor["id"], delivery_date,
                         start_time=start, end_time=end)
    api.set_clock(rollover_to, RO)
    cbs, _meta = _list_chargebacks(vendor["id"], reason="NO_SHOW")
    assert len(cbs) == num_no_shows, (
        f"Setup failed: expected {num_no_shows} NO_SHOW chargebacks, got {len(cbs)}"
    )
    confirmed = [confirm_chargeback(cb["id"], vendor["id"]) for cb in cbs]
    return region, vendor, depot, confirmed


def _list_chargebacks(vendor_id, **params):
    from prd_bench_local_runner.testing import validate_paginated
    query = {"vendor_id": vendor_id}
    query.update(params)
    return validate_paginated(api.list_chargebacks(DM, params=query))
