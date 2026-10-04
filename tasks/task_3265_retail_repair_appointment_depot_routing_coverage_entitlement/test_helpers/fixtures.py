"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test starts against an empty database). Setup calls use the
lenient get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: Customer and Technician are entity-backed roles, so any
ownership/location-gated call uses make_customer_headers(customer["id"]) /
make_technician_headers(technician["id"]) rather than the shared constants.
"""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID, get_success_data

from .api_client import api_client
from .constants import DEFAULT_LOGICAL_START
from .factories import (
    create_appointment_payload,
    create_coverage_entitlement_payload,
    create_coverage_plan_payload,
    create_customer_payload,
    create_device_payload,
    create_part_inventory_payload,
    create_part_payload,
    create_quality_follow_up_payload,
    create_repair_order_payload,
    create_security_verification_payload,
    create_service_location_payload,
    create_technician_payload,
    set_clock_payload,
)
from .test_users import (
    make_anonymous_headers,
    make_customer_headers,
    make_customer_service_headers,
    make_platform_admin_headers,
    make_technician_headers,
)


def _setup_ok(resp, what: str):
    data = get_success_data(resp)
    assert resp.status_code in (200, 201), (
        f"Setup failed ({what}): HTTP {resp.status_code} {resp.text}"
    )
    return data


def set_clock(to_iso8601=DEFAULT_LOGICAL_START):
    """Drive the logical clock (PlatformAdmin-only capability)."""
    resp = api_client.set_clock(
        set_clock_payload(to_iso8601), make_platform_admin_headers()
    )
    return _setup_ok(resp, "set_clock")


# --- Tier 1: single-entity creators -----------------------------------------


def create_customer(**overrides):
    payload = create_customer_payload(**overrides)
    resp = api_client.create_customer(payload, make_anonymous_headers())
    return _setup_ok(resp, "create_customer")


def create_device(customer, **overrides):
    payload = create_device_payload(customer["id"], **overrides)
    resp = api_client.create_device(payload, make_customer_service_headers())
    return _setup_ok(resp, "create_device")


def create_location(**overrides):
    payload = create_service_location_payload(**overrides)
    resp = api_client.create_service_location(payload, make_platform_admin_headers())
    return _setup_ok(resp, "create_service_location")


def create_technician(location, **overrides):
    payload = create_technician_payload(location["id"], **overrides)
    resp = api_client.create_technician(payload, make_platform_admin_headers())
    return _setup_ok(resp, "create_technician")


def create_part(**overrides):
    payload = create_part_payload(**overrides)
    resp = api_client.create_part(payload, make_platform_admin_headers())
    return _setup_ok(resp, "create_part")


def create_inventory(location, part, on_hand_quantity=5, express_replacement_quantity=0):
    payload = create_part_inventory_payload(
        location["id"], part["id"],
        on_hand_quantity=on_hand_quantity,
        express_replacement_quantity=express_replacement_quantity,
    )
    resp = api_client.create_part_inventory(payload, make_platform_admin_headers())
    return _setup_ok(resp, "create_part_inventory")


def create_coverage_plan(device, **overrides):
    payload = create_coverage_plan_payload(device["id"], **overrides)
    resp = api_client.create_coverage_plan(payload, make_customer_service_headers())
    return _setup_ok(resp, "create_coverage_plan")


# PRD §3.4 scores parts availability per required part category but never
# enumerates the issue-category -> required-parts mapping, so seeding one
# stocked component part in EVERY category for the device's model guarantees
# triage selects SAME_DAY_IN_STORE regardless of that mapping.
_ALL_PART_CATEGORIES = ("DISPLAY", "BATTERY", "LOGIC_BOARD", "CAMERA",
                        "ENCLOSURE", "OTHER")


def seed_same_day_parts(location, device, on_hand_quantity=10):
    """Stock every component part category for the device's model at the
    location so triage scores the location SAME_DAY_IN_STORE."""
    for category in _ALL_PART_CATEGORIES:
        part = create_part(model_code=device["model_code"],
                           part_category=category)
        create_inventory(location, part, on_hand_quantity=on_hand_quantity)


# --- Tier 2: hierarchy (network + customer/device) ---------------------------


def setup_customer_and_device(customer_overrides=None, device_overrides=None):
    """One customer + one owned device. Returns (customer, device)."""
    customer = create_customer(**(customer_overrides or {}))
    device = create_device(customer, **(device_overrides or {}))
    return customer, device


def setup_network(supports_same_day_repair=True, supports_express_replacement=False,
                  certification_level="ADVANCED"):
    """One retail location + one technician. Returns (location, technician)."""
    location = create_location(
        supports_same_day_repair=supports_same_day_repair,
        supports_express_replacement=supports_express_replacement,
    )
    technician = create_technician(location, certification_level=certification_level)
    return location, technician


def setup_customer_device_and_network(customer_overrides=None, device_overrides=None,
                                      network_overrides=None):
    """Customer + device + retail location + technician.

    Returns (customer, device, location, technician).
    """
    customer, device = setup_customer_and_device(customer_overrides, device_overrides)
    network_overrides = network_overrides or {}
    location, technician = setup_network(**network_overrides)
    return customer, device, location, technician


# --- Tier 2/3: appointment + repair order ------------------------------------


def get_device(device_id):
    resp = api_client.get_device(device_id, make_customer_service_headers())
    return _setup_ok(resp, "get_device")


def get_repair_order(ro_id):
    resp = api_client.get_repair_order(ro_id, make_customer_service_headers())
    return _setup_ok(resp, "get_repair_order")


def get_coverage_plan(plan_id):
    resp = api_client.get_coverage_plan(plan_id, make_customer_service_headers())
    return _setup_ok(resp, "get_coverage_plan")


def book_appointment(customer, device, location, technician,
                     slot_start="2026-09-02T10:00:00Z",
                     slot_end="2026-09-02T10:30:00Z",
                     issue_category="SOFTWARE"):
    """Book an appointment as CustomerService using the device's current version.

    Booking bumps the device version; the returned appointment dict carries a
    refreshed device under key "_device".
    """
    fresh_device = get_device(device["id"])
    payload = create_appointment_payload(
        customer["id"], device["id"], location["id"], technician["id"],
        fresh_device["version"], slot_start=slot_start, slot_end=slot_end,
        issue_category=issue_category,
    )
    resp = api_client.create_appointment(payload, make_customer_service_headers())
    appointment = _setup_ok(resp, "create_appointment")
    appointment["_device"] = get_device(device["id"])
    return appointment


def open_repair_order(appointment, customer, location, issue_category=None,
                      is_accidental_damage=False,
                      data_backup_acknowledged=True, privacy_wipe_consent=True):
    """Create a repair order against an appointment. The appointment must carry
    the refreshed device under "_device" (book_appointment does this).

    The returned repair order carries the refreshed device under "_device".
    """
    device = appointment["_device"]
    payload = create_repair_order_payload(
        appointment["id"], device["id"], customer["id"], location["id"],
        device["version"],
        issue_category=issue_category or appointment["issue_category"],
        is_accidental_damage=is_accidental_damage,
        data_backup_acknowledged=data_backup_acknowledged,
        privacy_wipe_consent=privacy_wipe_consent,
    )
    resp = api_client.create_repair_order(payload, make_technician_headers(
        appointment["technician_id"]))
    repair_order = _setup_ok(resp, "create_repair_order")
    repair_order["_device"] = get_device(device["id"])
    return repair_order


def setup_appointment(customer_overrides=None, device_overrides=None,
                      network_overrides=None, slot_start="2026-09-02T10:00:00Z",
                      slot_end="2026-09-02T10:30:00Z", issue_category="SOFTWARE"):
    """Customer + device + location + technician + one booked appointment.

    Returns (customer, device, location, technician, appointment).
    """
    customer, device, location, technician = setup_customer_device_and_network(
        customer_overrides, device_overrides, network_overrides)
    appointment = book_appointment(
        customer, device, location, technician,
        slot_start=slot_start, slot_end=slot_end, issue_category=issue_category)
    return customer, device, location, technician, appointment


def setup_repair_order(customer_overrides=None, device_overrides=None,
                       network_overrides=None, issue_category="SOFTWARE",
                       is_accidental_damage=False,
                       data_backup_acknowledged=True,
                       privacy_wipe_consent=True,
                       slot_start="2026-09-02T10:00:00Z",
                       slot_end="2026-09-02T10:30:00Z",
                       seed_parts=False):
    """Full chain through a TRIAGED repair order.

    seed_parts=True stocks every part category at the location BEFORE the order
    is opened so triage selects SAME_DAY_IN_STORE (PRD §3.4), enabling the
    same-day walk to READY_FOR_PICKUP.

    Returns (customer, device, location, technician, appointment, repair_order).
    """
    customer, device, location, technician, appointment = setup_appointment(
        customer_overrides, device_overrides, network_overrides,
        slot_start=slot_start, slot_end=slot_end, issue_category=issue_category)
    if seed_parts:
        seed_same_day_parts(location, device)
    repair_order = open_repair_order(
        appointment, customer, location,
        issue_category=issue_category,
        is_accidental_damage=is_accidental_damage,
        data_backup_acknowledged=data_backup_acknowledged,
        privacy_wipe_consent=privacy_wipe_consent)
    return customer, device, location, technician, appointment, repair_order


# --- Tier 3: entitlements and security gate ----------------------------------


def create_entitlement(repair_order, technician, coverage_plan_id=NON_EXISTENT_UUID):
    payload = create_coverage_entitlement_payload(repair_order["id"], coverage_plan_id)
    resp = api_client.create_coverage_entitlement(
        payload, make_technician_headers(technician["id"]))
    return _setup_ok(resp, "create_coverage_entitlement")


def resolve_entitlement(entitlement, plan, technician):
    """Resolve with the plan's current version; returns the resolved entitlement."""
    fresh_plan = get_coverage_plan(plan["id"])
    resp = api_client.resolve_entitlement(
        entitlement["id"],
        {"expected_coverage_plan_version": fresh_plan["version"]},
        make_technician_headers(technician["id"]),
    )
    return _setup_ok(resp, "resolve_entitlement")


def create_and_verify_security(repair_order, technician,
                               verification_type="ACTIVATION_LOCK_REMOVAL"):
    verification = create_security_verification(
        repair_order, technician, verification_type=verification_type)
    resp = api_client.verify_security_verification(
        verification["id"], make_technician_headers(technician["id"]))
    return _setup_ok(resp, "verify_security_verification")


def create_security_verification(repair_order, technician,
                                 verification_type="ACTIVATION_LOCK_REMOVAL"):
    payload = create_security_verification_payload(
        repair_order["id"], verification_type=verification_type)
    resp = api_client.create_security_verification(
        payload, make_technician_headers(technician["id"]))
    return _setup_ok(resp, "create_security_verification")


def clear_security_gate(repair_order, device, technician):
    """Create + verify the security verifications the device needs.

    Only creates a verification when the corresponding device flag is not
    already satisfied (the gate is an either/or per PRD §3.5).
    """
    if device.get("activation_lock_enabled"):
        create_and_verify_security(repair_order, technician, "ACTIVATION_LOCK_REMOVAL")
    if not device.get("proof_of_purchase_on_file"):
        create_and_verify_security(repair_order, technician, "OWNERSHIP_PROOF")


# --- Tier 3/5: repair lifecycle shortcuts ------------------------------------


def walk_to_parts_allocated(repair_order, device, technician):
    clear_security_gate(repair_order, device, technician)
    resp = api_client.allocate_parts(
        repair_order["id"], make_technician_headers(technician["id"]))
    return _setup_ok(resp, "allocate_parts")


def walk_to_in_progress(repair_order, device, technician):
    walk_to_parts_allocated(repair_order, device, technician)
    resp = api_client.start_repair(
        repair_order["id"], make_technician_headers(technician["id"]))
    return _setup_ok(resp, "start_repair")


def walk_to_quality_check(repair_order, device, technician):
    walk_to_in_progress(repair_order, device, technician)
    resp = api_client.complete_repair(
        repair_order["id"], make_technician_headers(technician["id"]))
    return _setup_ok(resp, "complete_repair")


def walk_to_ready_for_pickup(repair_order, device, technician):
    """QUALITY_CHECK -> READY_FOR_PICKUP (same-day in-store path)."""
    walk_to_quality_check(repair_order, device, technician)
    resp = api_client.pass_quality_check(
        repair_order["id"], make_technician_headers(technician["id"]))
    return _setup_ok(resp, "pass_quality_check")


def walk_to_completed(repair_order, device, technician, customer):
    walk_to_ready_for_pickup(repair_order, device, technician)
    resp = api_client.complete_pickup(
        repair_order["id"], make_customer_headers(customer["id"]))
    return _setup_ok(resp, "complete_pickup")


def setup_ready_for_pickup_order(customer_overrides=None, device_overrides=None,
                                 network_overrides=None, issue_category="SOFTWARE",
                                 is_accidental_damage=False,
                                 with_plan=False, plan_overrides=None,
                                 with_part=False, on_hand_quantity=5,
                                 part_overrides=None):
    """Full same-day setup up to READY_FOR_PICKUP.

    When with_part is True, seeds a DISPLAY part + inventory BEFORE opening the
    repair order so triage scores it SAME_DAY_IN_STORE.

    Returns dict with keys: customer, device, location, technician, appointment,
    repair_order, and optionally plan, entitlement, part, inventory.
    """
    ctx = {}
    customer, device, location, technician = setup_customer_device_and_network(
        customer_overrides, device_overrides, network_overrides)
    ctx.update(customer=customer, device=device, location=location,
               technician=technician)

    if with_part:
        part = create_part(**(part_overrides or {}))
        inventory = create_inventory(
            location, part, on_hand_quantity=on_hand_quantity)
        ctx.update(part=part, inventory=inventory)
    else:
        # Same-day completion requires SAME_DAY_IN_STORE triage; stock every
        # part category so the PRD §3.4 score reaches the threshold no matter
        # which categories the issue requires.
        seed_same_day_parts(location, device)

    plan = None
    if with_plan:
        plan = create_coverage_plan(device, **(plan_overrides or {}))
        ctx["plan"] = plan

    appointment = book_appointment(customer, device, location, technician,
                                   issue_category=issue_category)
    repair_order = open_repair_order(
        appointment, customer, location, issue_category=issue_category,
        is_accidental_damage=is_accidental_damage)
    ctx.update(appointment=appointment, repair_order=repair_order)

    if with_plan:
        entitlement = create_entitlement(repair_order, technician, plan["id"])
        entitlement = resolve_entitlement(entitlement, plan, technician)
        ctx["entitlement"] = entitlement

    walk_to_ready_for_pickup(repair_order, device, technician)
    ctx["repair_order"] = get_repair_order(repair_order["id"])
    return ctx


def setup_completed_order(**kwargs):
    """Full lifecycle through COMPLETED (same-day path). Same kwargs as
    setup_ready_for_pickup_order."""
    ctx = setup_ready_for_pickup_order(**kwargs)
    resp = api_client.complete_pickup(
        ctx["repair_order"]["id"], make_customer_headers(ctx["customer"]["id"]))
    ctx["repair_order"] = _setup_ok(resp, "complete_pickup")
    return ctx


def setup_completed_order_with_follow_up(**kwargs):
    """COMPLETED order plus an OPEN quality follow-up."""
    ctx = setup_completed_order(**kwargs)
    payload = create_quality_follow_up_payload(
        ctx["repair_order"]["id"], ctx["customer"]["id"])
    resp = api_client.create_quality_follow_up(
        payload, make_customer_service_headers())
    ctx["follow_up"] = _setup_ok(resp, "create_quality_follow_up")
    return ctx


# --- Tier 3: mail-in depot path ----------------------------------------------


def setup_mail_in_order_in_quality_check(issue_category="WATER_DAMAGE",
                                         is_accidental_damage=True):
    """Repair order triaged MAIL_IN_DEPOT (no parts stocked at the origin store)
    walked to QUALITY_CHECK. A depot location also exists.

    Returns dict with keys: customer, device, store, depot, technician,
    appointment, repair_order.
    """
    customer, device = setup_customer_and_device()
    store = create_location(supports_same_day_repair=False)
    depot = create_location(location_type="MAIL_IN_DEPOT",
                            supports_same_day_repair=False)
    technician = create_technician(store, certification_level="EXPERT")
    appointment = book_appointment(customer, device, store, technician,
                                   issue_category=issue_category)
    repair_order = open_repair_order(
        appointment, customer, store, issue_category=issue_category,
        is_accidental_damage=is_accidental_damage)
    walk_to_quality_check(repair_order, device, technician)
    return dict(customer=customer, device=device, store=store, depot=depot,
                technician=technician, appointment=appointment,
                repair_order=get_repair_order(repair_order["id"]))


# --- Tier 4: accumulation / threshold targeting -------------------------------


def complete_accidental_repair_with_plan(customer, device, location, technician,
                                         plan, slot_start, slot_end,
                                         issue_category="SCREEN_DAMAGE"):
    """One full accidental-damage repair resolved ENTITLED and completed,
    consuming exactly one incident on the plan.

    Returns the completed repair order dict.
    """
    seed_same_day_parts(location, device)
    appointment = book_appointment(
        customer, device, location, technician,
        slot_start=slot_start, slot_end=slot_end, issue_category=issue_category)
    repair_order = open_repair_order(
        appointment, customer, location, issue_category=issue_category,
        is_accidental_damage=True)
    entitlement = create_entitlement(repair_order, technician, plan["id"])
    resolve_entitlement(entitlement, plan, technician)
    walk_to_ready_for_pickup(repair_order, device, technician)
    resp = api_client.complete_pickup(
        repair_order["id"], make_customer_headers(customer["id"]))
    return _setup_ok(resp, "complete_pickup")


def open_accidental_repair_with_entitlement(customer, device, location, technician,
                                            plan, slot_start, slot_end,
                                            issue_category="SCREEN_DAMAGE",
                                            seed_parts=False):
    """Open a new accidental-damage repair order + pending entitlement against
    the plan. Returns (repair_order, entitlement).

    seed_parts=True stocks every part category first so the order triages
    SAME_DAY_IN_STORE (needed when the caller later walks the same-day path)."""
    if seed_parts:
        seed_same_day_parts(location, device)
    appointment = book_appointment(
        customer, device, location, technician,
        slot_start=slot_start, slot_end=slot_end, issue_category=issue_category)
    repair_order = open_repair_order(
        appointment, customer, location, issue_category=issue_category,
        is_accidental_damage=True)
    entitlement = create_entitlement(repair_order, technician, plan["id"])
    return repair_order, entitlement
