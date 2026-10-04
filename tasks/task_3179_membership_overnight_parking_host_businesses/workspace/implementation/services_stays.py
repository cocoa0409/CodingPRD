"""StayRequest services: the full lifecycle machine with its guarded transitions."""

import calculations as calc
import errors
import recompute
import serializers
import stay_domain as sd
import store
import validation as v
from envelope import created_object, ok_array, ok_object, parse_iso
from recompute import recompute_host

STAY_STATUSES = (
    "REQUESTED",
    "CONFIRMED",
    "DECLINED",
    "CANCELLED",
    "CHECKED_IN",
    "CHECKED_OUT",
    "NO_SHOW",
)


def load_stay(stay_id):
    stay = store.get(store.STAYS, stay_id)
    if stay is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No stay request with that id.")
    return stay


def _load_host_of(stay):
    host = store.get(store.HOSTS, stay.get("host_id"))
    if host is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "The stay's host no longer exists.")
    return host


def _load_member_of(stay):
    member = store.get(store.MEMBERS, stay.get("member_id"))
    if member is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "The stay's member no longer exists.")
    return member


def _load_vehicle_of(stay):
    vehicle = store.get(store.VEHICLES, stay.get("vehicle_id"))
    if vehicle is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "The stay's vehicle no longer exists.")
    return vehicle


# --------------------------------------------------------------------------
# POST /api/stay-requests
# --------------------------------------------------------------------------

def create_stay(actor, body):
    v.authorize(actor, ("Member",))
    # priority 4: required payload members and their declarable sets.
    v.require_fields(body, ["host_id", "member_id", "vehicle_id", "arrival_date", "nights"])
    host_id = v.text_field(body, "host_id")
    member_id = v.text_field(body, "member_id")
    vehicle_id = v.text_field(body, "vehicle_id")
    arrival_date = v.arrival_param(v.require(body, "arrival_date"))
    nights = v.int_field(body, "nights", minimum=1)
    party_size = v.int_field(body, "party_size", default=1, minimum=1)
    electric_code = v.enum_field(
        body,
        "electric_request_code",
        ("NONE", "ELECTRIC_30A", "ELECTRIC_50A"),
        default="NONE",
    )
    depth = v.int_field(body, "request_depth", default=0, minimum=0)
    same_day_hold = v.bool_field(body, "same_day_hold", default=False)
    # No other endpoint accepts a version field (PRD 2.9).
    v.optional_fields(
        body,
        ("expected_host_version", "expected_request_version", "expected_window_version"),
    )

    # priority 2: a Member acting on a stay must own the referenced member_id.
    v.require_member_scope(actor, member_id)
    # priority 3: path/body ids resolve; the outer host is reported first.
    host = _require_host(host_id)
    member = _require_member(member_id)
    vehicle = _require_vehicle(vehicle_id)
    # priority 5: the host must be accepting stays at all.
    sd.require_host_accepting(host)

    stay = {
        "id": store.new_id(),
        "host_id": host_id,
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "party_size": party_size,
        "electric_request_code": electric_code,
        "request_depth": depth,
        "request_status": "REQUESTED",
        "same_day_hold": same_day_hold,
        "confirmed_site_id": None,
        "ancillary_charge_cents": 0,
        "cancellation_fee_cents": 0,
        "checked_in_at": None,
        "checked_out_at": None,
        "no_show_recorded_at": None,
        "request_origin": "MEMBER_INITIATED",
    }
    stay.update(store.create_common())
    sd.apply_dates(stay, host, arrival_date, nights)

    # priority 8: the 48-hour lead-time guard.
    sd.require_lead_time(stay)
    # priority 10: the half-open date interval on the vehicle.
    sd.require_no_vehicle_conflict(vehicle_id, stay["arrival_date"], stay["departure_date"])
    # priority 12: the host must not be UNAVAILABLE and must have room for one
    # more site beyond the stays already counted (the new request is not yet in
    # committed_sites, so its own reservation is not excluded here).
    sd.require_capacity(host, own_reservation=False)
    # priority 15/16/17: fit, pedestal and self-containment.
    _require_self_containment(host, vehicle)
    # priority 18: member eligibility.
    _require_member_eligible(member)
    # priority 23: the fiscal guard.
    _check_balance(member)

    store.add(store.STAYS, stay)
    recompute_host(host)
    return created_object(serializers.stay_row(stay))


def _require_host(host_id):
    host = store.get(store.HOSTS, host_id)
    if host is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")
    return host


def _require_member(member_id):
    member = store.get(store.MEMBERS, member_id)
    if member is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No member with that id.")
    return member


def _require_vehicle(vehicle_id):
    vehicle = store.get(store.VEHICLES, vehicle_id)
    if vehicle is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No vehicle with that id.")
    return vehicle


def _require_self_containment(host, vehicle):
    if not sd.self_containment_ok(host, vehicle):
        errors.fail("ERR_VEHICLE_NOT_SELF_CONTAINED")


def _require_member_eligible(member):
    if not sd.member_eligible(member):
        errors.fail("ERR_MEMBER_NOT_ELIGIBLE")


def _check_balance(member):
    """priority 23: unsettled dues or unpaid cancellation fees block a request."""
    if member.get("balance_due_cents"):
        errors.fail("ERR_BALANCE_DUE")


# --------------------------------------------------------------------------
# GET /api/stay-requests
# --------------------------------------------------------------------------

def list_stays(actor):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    limit, offset = v.pagination()
    filters = {
        "host_id": v.query("host_id"),
        "member_id": v.query("member_id"),
        "vehicle_id": v.query("vehicle_id"),
        "confirmed_site_id": v.query("confirmed_site_id"),
        "request_status": v.query("request_status"),
    }
    from_raw = v.query("from_date")
    from_date = v.date_param(from_raw, "from_date") if from_raw is not None else None
    rows = []
    for stay in store.all_of(store.STAYS):
        if any(
            filters[key] is not None and stay.get(key) != filters[key]
            for key in filters
        ):
            continue
        if from_date is not None and not (
            stay.get("occupancy_end") is None or stay.get("occupancy_end") >= from_date
        ):
            continue
        rows.append(serializers.stay_row(stay))
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def get_stay(actor, stay_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    stay = load_stay(stay_id)
    return ok_object(serializers.stay_row(stay))


# --------------------------------------------------------------------------
# POST /api/stay-requests/{requestId}/decisions
# --------------------------------------------------------------------------

def decide_stay(actor, stay_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    # priority 4: required payload members, including the version precondition.
    v.require_fields(body, ["decision", "expected_host_version"])
    decision = v.enum_field(body, "decision", ("CONFIRM", "DECLINE"))
    site_id = v.text_field(body, "site_id")
    expected_host_version = v.int_field(body, "expected_host_version")

    stay = load_stay(stay_id)
    host = _load_host_of(stay)
    v.require_host_scope(actor, host["id"])

    # priority 7: the request must still be REQUESTED.
    if stay.get("request_status") != "REQUESTED":
        errors.fail("ERR_INVALID_STATE")

    if decision == "DECLINE":
        if expected_host_version != host["version"]:
            errors.fail("ERR_STALE_HOST_VERSION")
        member = _load_member_of(stay)
        stay["request_status"] = "DECLINED"
        # A decline advances the depth by one: a first-round request lands at
        # depth 1 (the value the later counter-request depends on) and a
        # second-round request, already at depth 2, lands at depth 3.
        stay["request_depth"] = (stay.get("request_depth") or 0) + 1
        store.stamp(stay)
        recompute_host(host)
        recompute.recompute_member(member)
        return ok_object(serializers.stay_row(stay))

    # --- CONFIRM: the most heavily guarded transition, checks in order ------
    # priority 5: the host must be APPROVED with posture OPEN or LIMITED.
    sd.require_host_accepting(host)
    if host.get("posture") not in calc.WINDOW_ACTIVE_BASES:
        errors.fail("ERR_HOST_CAPACITY_FULL")
    # priority 8: the lead-time guard is re-evaluated at confirmation.
    sd.require_lead_time(stay)

    # priority 3/4: the named site must exist on this host.
    if site_id is not None:
        site = store.get(store.SITES, site_id)
        if site is None or site.get("host_id") != host["id"]:
            errors.fail("ERR_RESOURCE_NOT_FOUND", "No parking site with that id on this host.")
    else:
        site = _auto_site(stay, host)
    vehicle = _load_vehicle_of(stay)
    member = _load_member_of(stay)

    # priority 15: the rig must fit the assigned site.
    if not sd.vehicle_fits_site(vehicle, site):
        errors.fail("ERR_VEHICLE_LENGTH_EXCEEDS_SITE")
    # priority 16: the pedestal must be at least as capable as requested.
    if not sd.electric_compatible(stay.get("electric_request_code"), site):
        errors.fail("ERR_SITE_ELECTRIC_INCOMPATIBLE")
    # priority 17: self-containment.
    _require_self_containment(host, vehicle)
    # priority 11: the blocked-approach rule over the 2-hour buffered interval.
    if sd.site_blocked(
        host["id"],
        site,
        stay["occupancy_start"],
        stay["occupancy_end"],
        exclude_id=stay["id"],
    ) is not None:
        errors.fail("ERR_SITE_APPROACH_BLOCKED")
    # priority 12: capacity, with the request's own reservation excluded.
    sd.require_capacity(host, own_reservation=True)
    # priority 24: the host version precondition, matched after every other check.
    if expected_host_version != host["version"]:
        errors.fail("ERR_STALE_HOST_VERSION")

    stay["request_status"] = "CONFIRMED"
    stay["confirmed_site_id"] = site["id"]
    stay["ancillary_charge_cents"] = calc.ancillary_charge_cents(stay, vehicle, member)
    store.stamp(stay)
    recompute_host(host)
    return ok_object(serializers.stay_row(stay))


def _auto_site(stay, host):
    """The first active site on the host that satisfies fit, pedestal and approach."""
    vehicle = _load_vehicle_of(stay)
    for site in store.all_of(store.SITES):
        if site.get("host_id") != host["id"] or not site.get("is_active"):
            continue
        if not sd.vehicle_fits_site(vehicle, site):
            continue
        if not sd.electric_compatible(stay.get("electric_request_code"), site):
            continue
        if sd.site_blocked(
            host["id"],
            site,
            stay["occupancy_start"],
            stay["occupancy_end"],
            exclude_id=stay["id"],
        ) is not None:
            continue
        return site
    errors.fail("ERR_HOST_CAPACITY_FULL", "No assignable parking site satisfies this request.")


# --------------------------------------------------------------------------
# POST /api/stay-requests/{requestId}/cancellations
# --------------------------------------------------------------------------

def cancel_stay(actor, stay_id, body):
    v.authorize(actor, ("Member",))
    stay = load_stay(stay_id)
    v.require_member_scope(actor, stay.get("member_id"))
    status = stay.get("request_status")
    if status not in ("REQUESTED", "CONFIRMED"):
        errors.fail("ERR_INVALID_STATE")

    host = _load_host_of(stay)
    member = _load_member_of(stay)
    if status == "REQUESTED":
        # A first-round withdrawal: no charge, no depth advance, no conduct.
        stay["request_status"] = "CANCELLED"
        stay["cancellation_fee_cents"] = 0
        store.stamp(stay)
        recompute_host(host)
        return ok_object(serializers.stay_row(stay))

    stay["request_status"] = "CANCELLED"
    stay["request_depth"] = (stay.get("request_depth") or 0) + 1
    stay["cancellation_fee_cents"] = calc.late_cancellation_fee_cents(
        sd.days_before_arrival(stay), stay.get("ancillary_charge_cents") or 0
    )
    store.stamp(stay)
    recompute_host(host)
    recompute.recompute_member(member)
    return ok_object(serializers.stay_row(stay))


# --------------------------------------------------------------------------
# POST /api/stay-requests/{requestId}/counter_requests
# --------------------------------------------------------------------------

def counter_request(actor, stay_id, body):
    v.authorize(actor, ("Member",))
    stay = load_stay(stay_id)
    # priority 2: role and ownership precede the state gate.
    v.require_member_scope(actor, stay.get("member_id"))
    host = _load_host_of(stay)
    member = _load_member_of(stay)
    vehicle = _load_vehicle_of(stay)

    status = stay.get("request_status")
    depth = stay.get("request_depth") or 0
    if status == "DECLINED":
        if depth != 1:
            errors.fail("ERR_INVALID_STATE")
    elif status in ("CANCELLED", "NO_SHOW"):
        if depth > 1:
            errors.fail("ERR_INVALID_STATE")
    else:
        errors.fail("ERR_INVALID_STATE")

    # priority 9: a counter-request may only be filed while the window is open.
    if store.now() > stay["occupancy_end"]:
        errors.fail("ERR_STAY_WINDOW_PASSED")

    arrival_raw = body.get("arrival_date")
    nights = v.int_field(body, "nights", minimum=1)
    party_size = v.int_field(body, "party_size", minimum=1)
    arrival = v.arrival_param(arrival_raw) if arrival_raw is not None else stay["arrival_date"]
    nights = nights if nights is not None else stay["nights"]
    if party_size is not None:
        stay["party_size"] = party_size
    sd.apply_dates(stay, host, arrival, nights)

    sd.require_host_accepting(host)
    sd.require_lead_time(stay)
    sd.require_no_vehicle_conflict(
        vehicle["id"], stay["arrival_date"], stay["departure_date"], exclude_id=stay["id"]
    )
    sd.require_capacity(host)
    _require_self_containment(host, vehicle)
    _require_member_eligible(member)

    stay["request_status"] = "REQUESTED"
    stay["request_depth"] = 2
    store.stamp(stay)
    recompute_host(host)
    recompute.recompute_member(member)
    return ok_object(serializers.stay_row(stay))


# --------------------------------------------------------------------------
# Check-in / check-out / no-show
# --------------------------------------------------------------------------

def check_in(actor, stay_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    stay = load_stay(stay_id)
    host = _load_host_of(stay)
    v.require_host_scope(actor, host["id"])
    if stay.get("request_status") != "CONFIRMED":
        errors.fail("ERR_INVALID_STATE")
    if store.now() < stay["occupancy_start"]:
        errors.fail("ERR_INVALID_STATE", "The arrival window has not opened yet.")
    stay["request_status"] = "CHECKED_IN"
    stay["checked_in_at"] = store.now()
    store.stamp(stay)
    return ok_object(serializers.stay_row(stay))


def check_out(actor, stay_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    stay = load_stay(stay_id)
    host = _load_host_of(stay)
    v.require_host_scope(actor, host["id"])
    if stay.get("request_status") != "CHECKED_IN":
        errors.fail("ERR_INVALID_STATE")
    if store.now() < stay["occupancy_end"]:
        errors.fail("ERR_INVALID_STATE", "The departure boundary has not been reached yet.")
    member = _load_member_of(stay)
    stay["request_status"] = "CHECKED_OUT"
    stay["checked_out_at"] = store.now()
    store.stamp(stay)
    recompute_host(host)
    # total_stays_completed rises by one and the pass pool is recalculated only
    # when the member has no other in-flight stay.
    recompute.recompute_member(member)
    return ok_object(serializers.stay_row(stay))


def record_no_show(actor, stay_id, body):
    v.authorize(actor, ("HostOperator", "PlatformAdmin"))
    stay = load_stay(stay_id)
    host = _load_host_of(stay)
    v.require_host_scope(actor, host["id"])
    narrative = v.text_field(body, "narrative", required=True)
    if stay.get("request_status") != "CONFIRMED":
        errors.fail("ERR_INVALID_STATE")
    # A no-show is recorded after the departure morning; the host may record it
    # as soon as the arrival window it never showed up for has opened.
    if store.now() < stay["occupancy_start"]:
        errors.fail("ERR_INVALID_STATE", "The arrival window has not opened yet.")

    member = _load_member_of(stay)
    stay["request_status"] = "NO_SHOW"
    stay["no_show_recorded_at"] = store.now()
    store.stamp(stay)

    from services_members import _new_incident

    _new_incident(member["id"], host["id"], "MAJOR", "STAFF_FILING", narrative)
    recompute.recompute_member(member)
    recompute_host(host)
    return ok_object(serializers.stay_row(stay))