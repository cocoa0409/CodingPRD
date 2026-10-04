"""Member, MemberVehicle, Incident and ConductDisposition services."""

import calculations as calc
import errors
import recompute
import serializers
import store
import validation as v
from envelope import created_object, ok_array, ok_object, parse_iso

PLAN_TIERS = ("CLASSIC", "PLUS", "PREMIER")
VEHICLE_CLASSES = calc.VEHICLE_CLASSES
SEVERITIES = ("MINOR", "MAJOR", "SEVERE")
ORIGINS = ("MEMBER_REPORT", "STAFF_FILING", "REVIEW_REPORT")
INSPECTIONS = ("", "NONE", "ELECTRIC_30A", "ELECTRIC_50A")
SUBSCRIPTION_ACTIONS = ("ACTIVATE", "LAPSE", "RENEW", "SET_GUEST_PASSES")
DISPOSITION_ACTIONS = ("UPHOLD", "DISMISS", "WITHDRAW")
RESOLVE_AS = ("OPEN", "UPHOLD", "DISMISS", "WITHDRAW")


def load_member(member_id):
    member = store.get(store.MEMBERS, member_id)
    if member is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No member with that id.")
    return member


def require_ownership(actor, member_id):
    """A Member acting on another member's resource is unauthorized."""
    if actor["role"] == "Member" and actor["id"] != member_id:
        errors.fail("ERR_UNAUTHORIZED")


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------

def create_member(actor, body):
    v.authorize(actor, ("Anonymous", "PlatformAdmin"))
    email = v.text_field(body, "email", required=True)
    full_name = v.text_field(body, "full_name", required=True)
    plan_tier = v.enum_field(body, "plan_tier", PLAN_TIERS, required=True)
    home_state_code = v.text_field(body, "home_state_code", required=True)
    for other in store.all_of(store.MEMBERS):
        if (other.get("email") or "").lower() == email.lower():
            errors.fail("ERR_MEMBER_EMAIL_DUPLICATE")

    member = {
        "id": store.new_id(),
        "email": email,
        "full_name": full_name,
        "plan_tier": plan_tier,
        "subscription_status": "PENDING",
        "standing_score": calc.BASE_SCORE,
        "strike_count": 0,
        "removal_status": "NONE",
        "guest_passes_remaining": calc.guest_pass_allotment(plan_tier),
        "home_state_code": home_state_code,
        "total_stays_completed": 0,
        "member_rating_average": 0.00,
    }
    member.update(store.create_common())
    store.add(store.MEMBERS, member)
    recompute.recompute_member(member)
    return created_object(serializers.member_row(member))


def list_members(actor):
    v.authorize(actor, ("PlatformAdmin",))
    limit, offset = v.pagination()
    plan_tier = v.query("plan_tier")
    subscription = v.query("subscription_status")
    removal = v.query("removal_status")
    rows = []
    for member in store.all_of(store.MEMBERS):
        if plan_tier is not None and member.get("plan_tier") != plan_tier:
            continue
        if subscription is not None and member.get("subscription_status") != subscription:
            continue
        if removal is not None and member.get("removal_status") != removal:
            continue
        rows.append(serializers.member_row(member))
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def get_member(actor, member_id):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    require_ownership(actor, member_id)
    member = load_member(member_id)
    return ok_object(serializers.member_row(member))


def subscription_action(actor, member_id, body):
    v.authorize(actor, ("PlatformAdmin",))
    member = load_member(member_id)
    action = v.enum_field(body, "action", SUBSCRIPTION_ACTIONS, required=True)
    pinned = v.int_field(body, "guest_passes_remaining", minimum=0)
    status = member.get("subscription_status")

    if action == "ACTIVATE":
        if status != "PENDING":
            errors.fail("ERR_INVALID_STATE")
        member["subscription_status"] = "ACTIVE"
    elif action == "LAPSE":
        if status not in ("ACTIVE", "CANCELLED"):
            errors.fail("ERR_INVALID_STATE")
        if status == "ACTIVE" and recompute.member_has_in_flight(member_id):
            errors.fail("ERR_INVALID_STATE", "The member has a stay in flight.")
        member["subscription_status"] = "LAPSED"
    elif action == "RENEW":
        if status != "LAPSED":
            errors.fail("ERR_INVALID_STATE")
        member["subscription_status"] = "ACTIVE"
    else:  # SET_GUEST_PASSES
        if pinned is None:
            errors.fail("ERR_INVALID_REQUEST", "guest_passes_remaining is required.")
        member["guest_passes_remaining"] = pinned
    recompute.recompute_member(member)
    return ok_object(serializers.member_row(member))


def cancel_subscription(actor, member_id, body):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    require_ownership(actor, member_id)
    member = load_member(member_id)
    if member.get("subscription_status") not in ("ACTIVE", "LAPSED"):
        errors.fail("ERR_INVALID_STATE")
    member["subscription_status"] = "CANCELLED"
    recompute.recompute_member(member)
    return ok_object(serializers.member_row(member))


# --------------------------------------------------------------------------
# MemberVehicle
# --------------------------------------------------------------------------

def load_vehicle(member_id, vehicle_id):
    member = store.get(store.MEMBERS, member_id)
    if member is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No member with that id.")
    vehicle = store.get(store.VEHICLES, vehicle_id)
    if vehicle is None or vehicle.get("member_id") != member_id:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No vehicle with that id for this member.")
    return member, vehicle


def _inspection_expiry(member, inspection_state_code, supplied, present):
    """Required when the inspecting state differs from the member's home state."""
    differs = inspection_state_code != member.get("home_state_code")
    if differs:
        if not present or supplied is None:
            errors.fail(
                "ERR_INVALID_REQUEST",
                "inspection_expires_on is required when the inspecting state differs "
                "from the member's home state.",
            )
        return parse_iso(supplied)
    if present and supplied is not None:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "inspection_expires_on must be absent when the inspecting state matches "
            "the member's home state.",
        )
    return None


def create_vehicle(actor, member_id, body):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    require_ownership(actor, member_id)
    member = load_member(member_id)
    vehicle_class = v.enum_field(body, "vehicle_class", VEHICLE_CLASSES, required=True)
    length_feet = v.int_field(body, "length_feet", required=True, minimum=0)
    self_contained = v.bool_field(body, "self_contained", required=True)
    inspection_state_code = v.text_field(body, "inspection_state_code", required=True)
    present = "inspection_expires_on" in body and body["inspection_expires_on"] is not None
    expires = _inspection_expiry(member, inspection_state_code, body.get("inspection_expires_on"), present)

    existing = [
        veh for veh in store.all_of(store.VEHICLES) if veh.get("member_id") == member_id
    ]
    vehicle = {
        "id": store.new_id(),
        "member_id": member_id,
        "vehicle_class": vehicle_class,
        "length_feet": length_feet,
        "self_contained": self_contained,
        "inspection_state_code": inspection_state_code,
        "inspection_expires_on": expires,
        "is_primary": len(existing) == 0,
    }
    vehicle["created_at"] = store.now()
    store.add(store.VEHICLES, vehicle)
    return created_object(serializers.vehicle_row(vehicle))


def list_vehicles(actor, member_id):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    require_ownership(actor, member_id)
    load_member(member_id)
    limit, offset = v.pagination()
    rows = [
        serializers.vehicle_row(veh)
        for veh in store.all_of(store.VEHICLES)
        if veh.get("member_id") == member_id
    ]
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def patch_vehicle(actor, member_id, vehicle_id, body):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    require_ownership(actor, member_id)
    member, vehicle = load_vehicle(member_id, vehicle_id)
    vehicle_class = v.enum_field(body, "vehicle_class", VEHICLE_CLASSES)
    length_feet = v.int_field(body, "length_feet", minimum=0)
    self_contained = v.bool_field(body, "self_contained")
    inspection_state_code = v.text_field(body, "inspection_state_code")
    present = "inspection_expires_on" in body and body["inspection_expires_on"] is not None

    if inspection_state_code is not None or present:
        expires = _inspection_expiry(
            member,
            inspection_state_code or vehicle.get("inspection_state_code"),
            body.get("inspection_expires_on"),
            present,
        )
    else:
        expires = None

    if vehicle_class is not None:
        vehicle["vehicle_class"] = vehicle_class
    if length_feet is not None:
        vehicle["length_feet"] = length_feet
    if self_contained is not None:
        vehicle["self_contained"] = self_contained
    if inspection_state_code is not None:
        vehicle["inspection_state_code"] = inspection_state_code
    if inspection_state_code is not None or present:
        vehicle["inspection_expires_on"] = expires
    return ok_object(serializers.vehicle_row(vehicle))


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------

def load_incident(incident_id):
    incident = store.get(store.INCIDENTS, incident_id)
    if incident is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No incident with that id.")
    return incident


def file_incident(actor, body):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    member_id = v.text_field(body, "member_id", required=True)
    host_id = v.text_field(body, "host_id", required=True)
    severity = v.enum_field(body, "severity", SEVERITIES, required=True)
    narrative = v.text_field(body, "narrative", required=True)
    origin = v.enum_field(body, "origin", ORIGINS, default="STAFF_FILING")
    member = load_member(member_id)
    if store.get(store.HOSTS, host_id) is None:
        errors.fail("ERR_RESOURCE_NOT_FOUND", "No host business with that id.")

    incident = _new_incident(member_id, host_id, severity, origin, narrative)
    recompute.recompute_member(member)
    return created_object(serializers.incident_row(incident))


def _new_incident(member_id, host_id, severity, origin, narrative):
    incident = {
        "id": store.new_id(),
        "member_id": member_id,
        "host_id": host_id,
        "severity": severity,
        "origin": origin,
        "incident_status": "OPEN",
        "narrative": narrative,
        "waived_days_remaining": 0,
    }
    incident.update(store.create_common())
    store.add(store.INCIDENTS, incident)
    return incident


def list_incidents(actor):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    limit, offset = v.pagination()
    member_id = v.query("member_id")
    host_id = v.query("host_id")
    status = v.query("incident_status")
    severity = v.query("severity")
    rows = []
    for incident in store.all_of(store.INCIDENTS):
        if member_id is not None and incident.get("member_id") != member_id:
            continue
        if host_id is not None and incident.get("host_id") != host_id:
            continue
        if status is not None and incident.get("incident_status") != status:
            continue
        if severity is not None and incident.get("severity") != severity:
            continue
        rows.append(serializers.incident_row(incident))
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def get_incident(actor, incident_id):
    v.authorize(actor, ("Member", "HostOperator", "PlatformAdmin"))
    incident = load_incident(incident_id)
    return ok_object(serializers.incident_row(incident))


# --------------------------------------------------------------------------
# ConductDisposition
# --------------------------------------------------------------------------

def load_dispositions_checks():
    return None


def _name_collision(deciding_member_id, display_name):
    """The deciding member's own full_name is exempt from the comparison."""
    for member in store.all_of(store.MEMBERS):
        if member["id"] == deciding_member_id:
            continue
        if member.get("full_name") == display_name:
            return True
    return False


def rule_on_incident(actor, incident_id, body):
    v.authorize(actor, ("Member",))
    incident = load_incident(incident_id)
    action = v.enum_field(body, "action", DISPOSITION_ACTIONS, required=True)
    display_name = v.text_field(body, "decided_by_display_name", required=True)
    requested = v.enum_field(body, "requested_decision", ("UPHOLD", "DISMISS"))

    # priority 7 (state) precedes priority 20 (name segmentation).
    if incident.get("incident_status") != "OPEN":
        errors.fail("ERR_INCIDENT_NOT_OPEN")
    if _name_collision(actor["id"], display_name):
        errors.fail("ERR_DISPOSITION_NAME_COLLISION")

    member = load_member(incident.get("member_id"))

    if action == "WITHDRAW":
        incident["incident_status"] = "WITHDRAWN"
        incident["waived_days_remaining"] = 0
        decision = "WITHDRAWN"
    elif action == "DISMISS":
        incident["incident_status"] = "DISMISSED"
        incident["waived_days_remaining"] = 0
        decision = "DISMISSED"
    else:  # UPHOLD
        source_review = _source_review(incident)
        if incident.get("origin") == "REVIEW_REPORT" and (
            source_review is None or source_review.get("review_status") == "WITHDRAWN"
        ):
            incident["incident_status"] = "WITHDRAWN"
            incident["waived_days_remaining"] = 0
            decision = "WITHDRAWN"
        else:
            incident["incident_status"] = "UPHELD"
            if incident.get("severity") == "SEVERE":
                incident["waived_days_remaining"] = 7
            else:
                incident["waived_days_remaining"] = 3
            decision = "UPHELD"
    store.stamp(incident)

    disposition = {
        "id": store.new_id(),
        "incident_id": incident["id"],
        "member_id": incident.get("member_id"),
        "requested_decision": requested,
        "decided_by_display_name": display_name,
        "decision": decision,
        "decided_at": store.now(),
    }
    disposition["created_at"] = store.now()
    store.add(store.DISPOSITIONS, disposition)

    recompute.recompute_member(member)
    return ok_object(serializers.incident_row(incident))


def _source_review(incident):
    """The withdrawn-review link carried on a REVIEW_REPORT incident, if any."""
    review_id = incident.get("source_review_id")
    if review_id:
        return store.get(store.REVIEWS, review_id)
    signature = "review:%s" % incident["id"]
    for review in store.all_of(store.REVIEWS):
        if review.get("incident_signature") == signature:
            return review
    return None


def list_member_dispositions(actor, member_id):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    require_ownership(actor, member_id)
    load_member(member_id)
    limit, offset = v.pagination()
    rows = [
        serializers.disposition_row(d)
        for d in store.all_of(store.DISPOSITIONS)
        if d.get("member_id") == member_id
    ]
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


def list_incident_dispositions(actor, incident_id):
    v.authorize(actor, ("Member", "PlatformAdmin"))
    load_incident(incident_id)
    limit, offset = v.pagination()
    rows = [
        serializers.disposition_row(d)
        for d in store.all_of(store.DISPOSITIONS)
        if d.get("incident_id") == incident_id
    ]
    window, total = v.page(rows, limit, offset)
    return ok_array(window, limit, offset, total)


# --------------------------------------------------------------------------
# Test-driving namespace: conduct injections
# --------------------------------------------------------------------------

def conduct_injection(actor, member_id, body):
    v.authorize(actor, ("PlatformAdmin",))
    severity = v.enum_field(body, "severity", SEVERITIES, required=True)
    resolve_as = v.enum_field(body, "resolve_as", RESOLVE_AS, required=True)
    narrative = v.text_field(body, "narrative", required=True)
    member = load_member(member_id)

    incident = _new_incident(member_id, None, severity, "STAFF_FILING", narrative)
    if resolve_as != "OPEN":
        if resolve_as == "UPHOLD":
            incident["incident_status"] = "UPHELD"
            incident["waived_days_remaining"] = 7 if severity == "SEVERE" else 3
            decision = "UPHELD"
        elif resolve_as == "DISMISS":
            incident["incident_status"] = "DISMISSED"
            decision = "DISMISSED"
        else:
            incident["incident_status"] = "WITHDRAWN"
            incident["waived_days_remaining"] = 0
            decision = "WITHDRAWN"
        store.stamp(incident)
        disposition = {
            "id": store.new_id(),
            "incident_id": incident["id"],
            "member_id": member_id,
            "requested_decision": "UPHOLD" if resolve_as == "UPHOLD" else "DISMISS",
            "decided_by_display_name": _injection_reviewer_name(incident["id"]),
            "decision": decision,
            "decided_at": store.now(),
        }
        disposition["created_at"] = store.now()
        store.add(store.DISPOSITIONS, disposition)

    recompute.recompute_member(member)
    # The incident is created, but unless `resolve_as` is OPEN the call also
    # drives the incident through its disposition state transition -- and the
    # PRD's status-code rule gives 200 OK to an operation that drives a state
    # transition, so this endpoint answers 200 rather than 201.
    return ok_object(serializers.incident_row(incident))


def _injection_reviewer_name(incident_id):
    """A display name guaranteed to be segmented from every member's name."""
    base = "Platform Review Board"
    for member in store.all_of(store.MEMBERS):
        if member.get("full_name") == base:
            return "Platform Review Board %s" % incident_id[:8]
    return base