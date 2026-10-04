"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (and empties the database)
before every individual test. Setup calls use ``get_success_data`` so a broken
precondition surfaces as a clear "Setup failed" error rather than a confusing
assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    access_event_payload,
    application_decision_payload,
    availability_event_payload,
    community_signal_payload,
    driving_record_report_payload,
    fuel_transaction_payload,
    incident_maintenance_order_payload,
    incident_payload,
    maintenance_order_payload,
    membership_payload,
    party_split_payload,
    pod_payload,
    report_decision_payload,
    reservation_payload,
    return_payload,
    shift_bundle_payload,
    tier_restore_entitlement_payload,
    vehicle_payload,
    wallet_adjustment_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_admin_headers,
    make_member_headers,
)

FLEET = TEST_USERS["fleet_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
ACCOUNT_ADMIN = TEST_USERS["university_account_admin_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

# PRD §3.6: the confirmation cascade stamps the planned window and holds 2000 cents.
DEFAULT_START = "2026-09-05T09:00:00Z"
DEFAULT_END = "2026-09-05T13:00:00Z"
# The cycles that accumulate CLOSED reservations start outside every default
# window so a placeholder trip's booking never overlaps them.
ACCUMULATION_START = "2026-09-06T00:00:00Z"
DEFAULT_RESERVED_HOURS = 4
SAMPLE_INSTANT = "2026-09-10T12:00:00Z"


# ─── Tier 1: State progression ────────────────────────

def create_member(full_name="Test Member", kind="INDIVIDUAL", email=None, **overrides):
    """Register a Member application (PRD §3.1). Returns the Member row."""
    payload = {
        "full_name": full_name,
        "kind": kind,
    }
    if email is not None:
        payload["email"] = email
    from .factories import member_registration_payload

    merged = member_registration_payload(**payload)
    # Caller-supplied registration inputs (last_accident_fee_block and friends)
    # win over the factory's generated defaults.
    merged.update(overrides)
    res = api_client.register_member(merged, ANONYMOUS)
    return get_success_data(res, 201)


def submit_report(member_id, decision=None, license_years_held=8, license_state="CA"):
    """Submit a driving-record report as the member themselves (PRD §3.1)."""
    payload = driving_record_report_payload(
        license_state=license_state, license_years_held=license_years_held
    )
    if decision is not None:
        payload["report_decision"] = decision
    res = api_client.submit_driving_record_report(member_id, payload, make_member_headers(member_id))
    return get_success_data(res, 201)


def record_decision(report_id, decision="CLEAR"):
    """Record the screener decision on a report (PRD §3.1)."""
    res = api_client.record_report_decision(report_id, report_decision_payload(decision), OPERATOR)
    return get_success_data(res, 200)


def decide_application(member_id, decision="APPROVE"):
    """Approve or decline a screened application (PRD §3.1)."""
    res = api_client.decide_application(member_id, application_decision_payload(decision), OPERATOR)
    return get_success_data(res, 200)


def approve_member(full_name="Approved Member", kind="INDIVIDUAL", email=None,
                   license_years_held=8, decision="CLEAR", **overrides):
    """Register → submit report → record decision → approve.

    Returns (member, report). For INDIVIDUAL kind the approval auto-creates the
    primary STANDARD membership, exactly as PRD §3.1 describes. ``overrides``
    carry the optional registration inputs (e.g. ``last_accident_fee_block``),
    but caller keyword arguments take precedence over the generated defaults.
    """
    member = create_member(full_name=full_name, kind=kind, email=email, **overrides)
    report = submit_report(member["id"], decision=decision, license_years_held=license_years_held)
    record_decision(report["id"], decision)
    member = decide_application(member["id"], "APPROVE")
    return member, report


def get_primary_membership(member_id):
    """Read back the member's primary membership (created automatically on approval)."""
    res = api_client.list_member_memberships(member_id, OPERATOR)
    data = get_success_data(res, 200)
    assert data, f"Setup failed: member {member_id} has no membership row"
    return data[0]


def approve_member_with_membership(**kwargs):
    """Approved INDIVIDUAL member plus their auto-created primary membership."""
    member, report = approve_member(**kwargs)
    return member, get_primary_membership(member["id"])


# ─── Tier 2: Entity hierarchy ─────────────────────────

def create_pod(name="Test Pod", site_type="CAMPUS", capacity=4, fuel_floor_pct=None, **overrides):
    """Create a Pod as FleetAdmin (PRD §3.5)."""
    payload = pod_payload(name=name, site_type=site_type, capacity=capacity, **overrides)
    if fuel_floor_pct is not None:
        payload["fuel_floor_pct"] = fuel_floor_pct
    else:
        payload["fuel_floor_pct"] = {"NEIGHBORHOOD": 25, "CAMPUS": 20, "AIRPORT": 35}[site_type]
    res = api_client.create_pod(payload, FLEET)
    return get_success_data(res, 201)


def set_pod_site_type(pod_id, site_type):
    """Reclassify a pod around the site-type cycle (PRD §3.5)."""
    res = api_client.reclassify_pod(pod_id, {"site_type": site_type}, FLEET)
    return get_success_data(res, 200)


def create_vehicle(pod_id, vin=None, model="Prius", capacity_seats=5, **overrides):
    """Place a vehicle into a pod (PRD §3.5)."""
    payload = vehicle_payload(pod_id, model=model, capacity_seats=capacity_seats, **overrides)
    if vin is not None:
        payload["vin"] = vin
    res = api_client.create_vehicle(payload, FLEET)
    return get_success_data(res, 201)


def create_pod_with_vehicle(capacity=4, site_type="CAMPUS", pod_name="Test Pod"):
    """One pod plus one AVAILABLE vehicle placed in it. Returns (pod, vehicle)."""
    pod = create_pod(name=pod_name, site_type=site_type, capacity=capacity)
    vehicle = create_vehicle(pod["id"])
    pod = get_success_data(api_client.get_pod(pod["id"], FLEET), 200)
    return pod, vehicle


def set_vehicle_out_of_service(vehicle_id):
    res = api_client.post_availability_event(vehicle_id, availability_event_payload("OUT_OF_SERVICE"), OPERATOR)
    return get_success_data(res, 200)


def retire_vehicle(vehicle_id):
    res = api_client.post_availability_event(vehicle_id, availability_event_payload("RETIRE"), FLEET)
    return get_success_data(res, 200)


# ─── Tier 3: Full lifecycle shortcuts ─────────────────

def create_reservation(member_id, pod_id, vehicle_id, expected_vehicle_version,
                       start_at=DEFAULT_START, end_at=DEFAULT_END,
                       reserved_hours=DEFAULT_RESERVED_HOURS, **overrides):
    """Create and confirm a reservation as its own member (PRD §3.6)."""
    payload = reservation_payload(
        member_id=member_id,
        pod_id=pod_id,
        vehicle_id=vehicle_id,
        expected_vehicle_version=expected_vehicle_version,
        start_at=start_at,
        end_at=end_at,
        reserved_hours=reserved_hours,
        **overrides,
    )
    res = api_client.create_reservation(payload, make_member_headers(member_id))
    return get_success_data(res, 201)


def setup_confirmed_reservation(vehicle_count=1, pod_capacity=4, site_type="CAMPUS",
                                pod_name="Test Pod", start_at=DEFAULT_START,
                                end_at=DEFAULT_END, reserved_hours=DEFAULT_RESERVED_HOURS,
                                fuel_floor_pct=None, member_kwargs=None, pod_kwargs=None):
    """Approved member + membership + pod + AVAILABLE vehicle + CONFIRMED reservation.

    ``fuel_floor_pct`` overrides the pod's site-type floor (PRD §3.5: "`fuel_floor_pct`
    is the minimum acceptable fuel level at return for that site type"). Several charge
    fixtures pin an AIRPORT pod whose measured deficit is set against the declared floor
    rather than the site-type default.

    Returns a dict with the full setup: member, membership, pod, vehicle,
    reservation, and the pod/vehicle re-read after the confirmation cascade.
    """
    member, membership = approve_member_with_membership(**(member_kwargs or {}))
    pod = create_pod(name=pod_name, site_type=site_type, capacity=pod_capacity,
                     fuel_floor_pct=fuel_floor_pct, **(pod_kwargs or {}))
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(
        member["id"], pod["id"], vehicle["id"], vehicle["version"],
        start_at=start_at, end_at=end_at, reserved_hours=reserved_hours,
    )
    return {
        "member": member,
        "membership": membership,
        "pod": pod,
        "vehicle": vehicle,
        "reservation": reservation,
        "vehicle_after": get_success_data(api_client.get_vehicle(vehicle["id"], FLEET), 200),
        "pod_after": get_success_data(api_client.get_pod(pod["id"], FLEET), 200),
    }


def start_trip(member_id, reservation_id, method="APP"):
    """Record a SUCCESSFUL access attempt, moving the reservation to IN_USE."""
    res = api_client.create_access_event(
        access_event_payload(reservation_id, member_id, method=method),
        make_member_headers(member_id),
    )
    return get_success_data(res, 201)


def post_fuel_transaction(member_id, reservation_id, vehicle_id, amount_cents=4000,
                          gallons_hundredths=1000):
    """Post a fuel-card purchase (PRD §3.12)."""
    res = api_client.create_fuel_transaction(
        fuel_transaction_payload(reservation_id, vehicle_id, amount_cents, gallons_hundredths),
        make_member_headers(member_id),
    )
    return get_success_data(res, 201)


def return_vehicle(member_id, reservation_id, pod_id, odometer_miles, fuel_level_pct,
                   contamination_level=0):
    """Return the vehicle to its booked pod (PRD §3.8)."""
    res = api_client.return_reservation(
        reservation_id,
        return_payload(pod_id, odometer_miles, fuel_level_pct, contamination_level),
        make_member_headers(member_id),
    )
    return get_success_data(res, 200)


def open_incident(reservation_id, vehicle_id, member_id, repair_cost_cents=None,
                  incident_type="DAMAGE", **overrides):
    """Open an incident against a reservation (PRD §3.13)."""
    payload = incident_payload(reservation_id, vehicle_id, member_id, **overrides)
    payload["incident_type"] = incident_type
    if repair_cost_cents is not None:
        payload["repair_cost_cents"] = repair_cost_cents
    res = api_client.create_incident(payload, OPERATOR)
    return get_success_data(res, 201)


def party_split(incident_id, expected_incident_version):
    """Assess responsibility on an incident (PRD §3.13)."""
    res = api_client.party_split(
        incident_id, party_split_payload(expected_incident_version), OPERATOR
    )
    return get_success_data(res, 200)


def scheduled_order_from_incident(pod_id, incident_id, **overrides):
    """Raise a blocking maintenance order from an incident (PRD §3.12)."""
    res = api_client.create_incident_maintenance_order(
        incident_id, incident_maintenance_order_payload(pod_id, **overrides), OPERATOR
    )
    return get_success_data(res, 201)


def schedule_maintenance_order(vehicle_id, reason="TYRE_ROTATION", blocking=True, **overrides):
    """Schedule a maintenance order directly against a vehicle (PRD §3.12)."""
    res = api_client.create_maintenance_order(
        maintenance_order_payload(vehicle_id, reason=reason, blocking=blocking, **overrides),
        OPERATOR,
    )
    return get_success_data(res, 201)


# ─── Tier 4: Threshold / boundary targeting ───────────

def setup_overdue_trip(clock, pod_name, site_type="AIRPORT", pod_capacity=4,
                       fuel_floor_pct=None, reserved_hours=DEFAULT_RESERVED_HOURS,
                       start_at=DEFAULT_START, end_at=DEFAULT_END):
    """CONFIRMED reservation whose window has elapsed, swept into OVERDUE.

    Advances the logical clock past ``end_at`` and runs the lateness sweep, so the
    reservation carries a preserved ``status_before_overdue`` anchor (PRD §3.10:
    the sweep's entry edges run from ``CLOSED`` and ``RETURNED``). Returns the
    full setup dict plus the swept reservation under ``reopened``.
    """
    setup = setup_confirmed_reservation(
        pod_name=pod_name, site_type=site_type, pod_capacity=pod_capacity,
        fuel_floor_pct=fuel_floor_pct, reserved_hours=reserved_hours,
        start_at=start_at, end_at=end_at,
    )
    get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    setup["reopened"] = get_success_data(
        api_client.reopen_overdue(setup["reservation"]["id"], OPERATOR), 200
    )
    setup["clock"] = clock
    return setup


def setup_overdue_reservation(end_at="2026-09-05T13:00:00Z", clock="2026-09-10T12:00:00Z",
                              reserved_hours=DEFAULT_RESERVED_HOURS, fuel_amount_cents=None,
                              site_type="CAMPUS", pod_capacity=4, pod_name="Overdue Pod"):
    """CONFIRMED reservation whose window has elapsed, swept into OVERDUE.

    Advances the logical clock past ``end_at`` and runs the lateness sweep, so
    the reservation carries a preserved ``status_before_overdue`` anchor.
    Returns the full setup dict plus the reopened reservation.
    """
    setup = setup_confirmed_reservation(
        pod_capacity=pod_capacity, site_type=site_type, pod_name=pod_name,
        start_at=end_at.replace("T13:00:00Z", "T09:00:00Z"), end_at=end_at,
        reserved_hours=reserved_hours,
    )
    if fuel_amount_cents is not None:
        post_fuel_transaction(
            setup["member"]["id"], setup["reservation"]["id"], setup["vehicle"]["id"],
            amount_cents=fuel_amount_cents,
        )
    get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    res = api_client.reopen_overdue(setup["reservation"]["id"], OPERATOR)
    setup["overdue"] = get_success_data(res, 200)
    setup["clock"] = clock
    return setup


def setup_late_return(late_minutes, pod_fuel_floor=20, site_type="CAMPUS",
                      clock=None, reserved_hours=DEFAULT_RESERVED_HOURS,
                      returned_fuel_level_pct=None, pod_name="Late Pod"):
    """A trip already in IN_USE, with the logical clock parked `late_minutes` past end_at.

    The caller performs the return itself, so the same helper drives the
    extension of the return charge's grace band and the late-return penalty's
    tier selection. Returns the setup dict.
    """
    setup = setup_confirmed_reservation(
        pod_capacity=4, site_type=site_type, pod_name=pod_name, reserved_hours=reserved_hours
    )
    start_trip(setup["member"]["id"], setup["reservation"]["id"])
    end_at = setup["reservation"]["end_at"]
    if clock is None:
        from datetime import datetime, timedelta

        parsed = datetime.strptime(end_at, "%Y-%m-%dT%H:%M:%SZ")
        clock = (parsed + timedelta(minutes=late_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    setup["clock"] = clock
    setup["returned_fuel_level_pct"] = (
        pod_fuel_floor if returned_fuel_level_pct is None else returned_fuel_level_pct
    )
    return setup


def _reservation_for_window(pod_id, vehicle_id, member_id, start_at):
    """The open reservation of this vehicle whose window starts at ``start_at``."""
    res = api_client.list_reservations(
        OPERATOR, {"vehicle_id": vehicle_id, "member_id": member_id, "start_at": start_at}
    )
    rows = get_success_data(res, 200)
    assert rows, (
        f"Setup failed: no {start_at} reservation exists for vehicle {vehicle_id}"
    )
    return rows[0]


def drive_trip_to_close(member_id, reservation, pod_id, vehicle_id,
                        odometer_miles=41000, fuel_level_pct=60):
    """Walk an existing CONFIRMED reservation through IN_USE → RETURNED → CLOSED.

    The reservation is booked by the caller (a CONFIRMED row already holds the
    vehicle, PRD §3.6), so this helper only drives the remaining declared edges.
    A posted fuel-card transaction is required before the close, exactly as
    PRD §3.11 states.
    """
    start_trip(member_id, reservation["id"])
    return_vehicle(
        member_id, reservation["id"], pod_id,
        odometer_miles=odometer_miles,
        fuel_level_pct=fuel_level_pct,
    )
    post_fuel_transaction(member_id, reservation["id"], vehicle_id)
    closed = get_success_data(
        api_client.close_reservation(reservation["id"], make_member_headers(member_id)), 200
    )
    return closed


def accumulate_closed_reservations(target_count, pod_id, vehicle_id, member_id,
                                   first_start=ACCUMULATION_START, step_hours=6,
                                   return_fuel_level_pct=60):
    """Drive a vehicle to ``target_count`` CLOSED reservations inside the trailing window.

    Each cycle is CONFIRMED → IN_USE → RETURNED → CLOSED with a posted fuel-card
    transaction, so the close-hop consequences (hold release, utilization-service
    order at 8 closes, referral credit past the threshold) are exercised for real.
    Every cycle books its own reservation through ``POST /car-share/reservations``
    against the vehicle's current version, so the vehicle's own ``version`` keeps
    advancing across the run. Windows are spaced ``step_hours`` apart so they never
    overlap. Returns the list of closed reservations.
    """
    from datetime import datetime, timedelta

    base = datetime.strptime(first_start, "%Y-%m-%dT%H:%M:%SZ")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    closed = []
    for i in range(target_count):
        start_dt = base + timedelta(hours=i * step_hours)
        end_dt = start_dt + timedelta(hours=4)
        vehicle = get_success_data(api_client.get_vehicle(vehicle_id, FLEET), 200)
        created = create_reservation(
            member_id, pod_id, vehicle_id, vehicle["version"],
            start_at=start_dt.strftime(fmt), end_at=end_dt.strftime(fmt),
            reserved_hours=4,
        )
        trip = _reservation_for_window(pod_id, vehicle_id, member_id, created["start_at"])
        closed.append(drive_trip_to_close(member_id, trip, pod_id, vehicle_id,
                                          fuel_level_pct=return_fuel_level_pct))
    return closed


# ─── Tier 5: Finalization / terminal state ────────────

def freeze_membership_via_split(repair_cost_cents=12000, pod_name="Cascade Pod",
                                clock=None, member_kwargs=None):
    """Approved member + trip + DAMAGE incident + high-severity split.

    The split's severity score must reach the at-least-4 threshold so the freeze
    cascade fires (PRD §3.13); ``last_accident_fee_block`` is supplied at
    registration and the repair cost is set at or above the 10000-cent third term
    to reach it. The trip is started first so the split's fee cascade has a live
    HELD/CONFIRMED reservation of the member to act on (PRD §3.4). Returns the
    setup dict with the frozen membership.
    """
    kwargs = {"last_accident_fee_block": 2, "full_name": "Cascade Member"}
    kwargs.update(member_kwargs or {})
    member, membership = approve_member_with_membership(**kwargs)
    pod = create_pod(name=pod_name, site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])
    if clock is not None:
        get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    incident = open_incident(
        reservation["id"], vehicle["id"], member["id"], repair_cost_cents=repair_cost_cents
    )
    split = party_split(incident["id"], incident["version"])
    return {
        "member": member,
        "membership": membership,
        "pod": pod,
        "vehicle": vehicle,
        "reservation": reservation,
        "incident": incident,
        "split": split,
        "membership_after": get_success_data(
            api_client.get_membership(membership["id"], OPERATOR), 200
        ),
    }


def setup_frozen_membership_with_incident(pod_name="Frozen Pod"):
    """Frozen membership plus the incident that caused the freeze (still open).

    Returns the setup dict; ``maintenance_order`` is the blocking order raised
    from the incident, which is the join path back to CLOSED.
    """
    setup = freeze_membership_via_split(pod_name=pod_name)
    incident = setup["incident"]
    order = scheduled_order_from_incident(
        setup["pod"]["id"], incident["id"], reason="COLLISION_REPAIR", blocking=True,
        scheduled_start="2026-09-20T09:00:00Z", scheduled_end="2026-09-20T11:00:00Z",
    )
    setup["maintenance_order"] = order
    return setup


def setup_frozen_membership_with_pending_entitlement(tier="PREMIUM", pod_name="Entitlement Pod"):
    """Frozen membership plus a PENDING tier-restore entitlement recorded on it."""
    setup = freeze_membership_via_split(pod_name=pod_name)
    entitlement = get_success_data(
        api_client.create_tier_restore_entitlement(
            setup["membership"]["id"],
            tier_restore_entitlement_payload(tier=tier, reason="LOYALTY"),
            ACCOUNT_ADMIN,
        ),
        201,
    )
    setup["entitlement"] = entitlement
    return setup


def setup_bundle_step_up(pod_name="Legacy Campus"):
    """An AIRPORT pod carrying a single remaining vehicle, used for band stepping.

    The other three vehicles are placed in the source pod, so parking one of them
    back into the airport pod flips the balance band.
    """
    dest = create_pod(name=pod_name, site_type="AIRPORT", capacity=6, fuel_floor_pct=35)
    parked = create_vehicle(dest["id"])
    source = create_pod(name=f"{pod_name} Source", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    moved = [create_vehicle(source["id"]) for _ in range(3)]
    return {"dest": dest, "parked": parked, "source": source, "moved": moved}


def setup_source_with_retained_vehicles(retained=2, moving=1, source_capacity=6,
                                        dest_capacity=6, source_name="Retained Source",
                                        dest_name="Retained Dest"):
    """A source pod holding ``retained`` vehicles that are NOT moved, plus the moved set."""
    source = create_pod(name=source_name, site_type="CAMPUS", capacity=source_capacity, fuel_floor_pct=20)
    dest = create_pod(name=dest_name, site_type="CAMPUS", capacity=dest_capacity, fuel_floor_pct=20)
    kept = [create_vehicle(source["id"]) for _ in range(retained)]
    moved = [create_vehicle(source["id"]) for _ in range(moving)]
    return {"source": source, "dest": dest, "kept": kept, "moved": moved}


def apply_bundle(source_pod_id, dest_pod_id, monthly_pods, expected_pod_version_profile,
                 scheduled_start="2026-09-12T02:00:00Z", scheduled_end="2026-09-12T06:00:00Z"):
    """Apply a relocation bundle as PodOperator (PRD §3.5)."""
    payload = shift_bundle_payload(
        source_pod_id, dest_pod_id, monthly_pods, expected_pod_version_profile,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    res = api_client.apply_shift_bundle(payload, OPERATOR)
    return get_success_data(res, 201)


def assign_shift_bundle(source_pod_id, dest_pod_id, moved, expected_pod_version_profile,
                        **overrides):
    """Raw bundle apply returning the requests.Response (for error-path assertions)."""
    payload = shift_bundle_payload(
        source_pod_id, dest_pod_id, [v["id"] for v in moved], expected_pod_version_profile,
        **overrides,
    )
    return api_client.apply_shift_bundle(payload, OPERATOR)


def move_vehicle_to_pod(vehicle_id, dest_pod_id, scheduled_start="2026-09-15T02:00:00Z",
                        scheduled_end="2026-09-15T06:00:00Z"):
    """Relocate one vehicle through a bundle, reading the destination version first."""
    vehicle = get_success_data(api_client.get_vehicle(vehicle_id, FLEET), 200)
    dest = get_success_data(api_client.get_pod(dest_pod_id, FLEET), 200)
    source_pod_id = vehicle["home_pod_id"] or vehicle["pod_id"]
    return apply_bundle(
        source_pod_id, dest_pod_id, [vehicle_id], dest["version"],
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )


def setup_wallet_balance(member_id, amount_cents):
    """Credit a member wallet outside the automatic penalty paths (PRD §3.14)."""
    res = api_client.adjust_wallet(
        member_id, wallet_adjustment_payload(amount_cents, "GOODWILL"), OPERATOR
    )
    return get_success_data(res, 200)


def create_account(primary_member_id, name="Test University", type_="UNIVERSITY", **overrides):
    """Create a university or business program account (PRD §3.14)."""
    from .factories import account_payload

    payload = account_payload(primary_member_id, name=name, **overrides)
    payload["type"] = type_
    res = api_client.create_account(payload, ANONYMOUS)
    return get_success_data(res, 201)


def create_sponsored_membership(member_id, account_id=None, tier="STANDARD",
                                primary_flag=True, department_code=None):
    """Add a membership under an account as its UniversityAccountAdmin (PRD §3.3)."""
    payload = membership_payload(member_id, tier=tier, primary_flag=primary_flag)
    if account_id is not None:
        payload["account_id"] = account_id
    if department_code is not None:
        payload["department_code"] = department_code
    headers = make_account_admin_headers(account_id) if account_id else ACCOUNT_ADMIN
    res = api_client.create_membership(payload, headers)
    return get_success_data(res, 201)


def raise_cleanliness_signal(member_id, pod_id, vehicle_id, message="Vehicle is dirty"):
    """Raise a CLEANLINESS signal as a member (PRD §3.12)."""
    payload = community_signal_payload(
        pod_id, signal_type="CLEANLINESS", message=message, vehicle_id=vehicle_id
    )
    res = api_client.create_community_signal(payload, make_member_headers(member_id))
    return get_success_data(res, 201)