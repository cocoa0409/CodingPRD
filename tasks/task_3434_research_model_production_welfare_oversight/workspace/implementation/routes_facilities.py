"""Facilities and barrier rooms (PRD 3.1)."""
from flask import Blueprint

import calc
import domain
import validation as V
from auth import ALL_ROLES, authenticate, require_role
from responses import ApiError, success_object
from store import db, new_id, next_seq, now, touch

bp = Blueprint("facilities", __name__)


def _invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# --------------------------------------------------------------------------
# Facilities
# --------------------------------------------------------------------------

@bp.post("/api/facilities")
def create_facility():
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    b = V.body()
    # Priority 8: required fields and types.
    name = V.v_str(b, "name")
    site_code = V.v_str(b, "site_code")
    reg_num = V.v_str(b, "registration_number")
    expires = V.v_dt(b, "registration_expires_at")
    # Priority 8: uniqueness.
    for f in db["facilities"].values():
        if f["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_KEY", 409, "site_code already exists")
    fid = new_id()
    db["facilities"][fid] = {
        "id": fid,
        "name": name,
        "site_code": site_code,
        "registration_number": reg_num,
        "registration_status": "REGISTERED",
        "registration_expires_at": expires,
        "suspension_reason": None,
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_facility(db["facilities"][fid]), 201)


@bp.get("/api/facilities/<fid>")
def get_facility(fid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    return success_object(calc.ser_facility(V.get_or_404("facilities", fid)))


@bp.post("/api/facilities/<fid>/transition")
def facility_transition(fid):
    uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    fac = V.get_or_404("facilities", fid)
    b = V.body()
    target = V.v_str(b, "target_state")
    cur = fac["registration_status"]
    if target == "UNDER_INSPECTION":
        if cur != "REGISTERED":
            raise _invalid_state("Facility cannot enter UNDER_INSPECTION from %s" % cur)
        fac["registration_status"] = "UNDER_INSPECTION"
    elif target == "REGISTERED":
        if cur not in ("UNDER_INSPECTION", "SUSPENDED"):
            raise _invalid_state("Facility cannot be reinstated from %s" % cur)
        if cur == "SUSPENDED":
            for insp in db["inspections"].values():
                if insp["facility_id"] == fid and insp["status"] == "ESCALATED":
                    raise _invalid_state("An escalated inspection blocks reinstatement")
        expires = V.v_dt(b, "registration_expires_at")
        if not expires > now():
            raise V.invalid("registration_expires_at must be strictly after the current logical clock")
        fac["registration_expires_at"] = expires
        fac["suspension_reason"] = None
        fac["registration_status"] = "REGISTERED"
    elif target == "SUSPENDED":
        if cur != "REGISTERED":
            raise _invalid_state("Facility cannot be suspended from %s" % cur)
        reason = b.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise V.invalid("reason must be a string")
        domain.facility_suspend(fac, reason)
        return success_object(calc.ser_facility(fac))
    elif target == "REVOKED":
        if cur != "UNDER_INSPECTION":
            raise _invalid_state("Facility cannot be revoked from %s" % cur)
        fac["registration_status"] = "REVOKED"
        touch("facilities", fid)
        domain.facility_transport_cascade(fid)
        return success_object(calc.ser_facility(fac))
    else:
        raise _invalid_state("Unknown target_state %s" % target)
    touch("facilities", fid)
    return success_object(calc.ser_facility(fac))


@bp.get("/api/facilities/<fid>/rooms")
def facility_rooms(fid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("facilities", fid)
    items = [r for r in db["rooms"].values() if r["facility_id"] == fid]
    return V.paginate(items, calc.ser_room)


@bp.get("/api/facilities/<fid>/protocols")
def facility_protocols(fid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("facilities", fid)
    items = [p for p in db["protocols"].values() if p["facility_id"] == fid]
    return V.paginate(items, calc.ser_protocol)


@bp.get("/api/facilities/<fid>/inspections")
def facility_inspections(fid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("facilities", fid)
    items = [i for i in db["inspections"].values() if i["facility_id"] == fid]
    return V.paginate(items, calc.ser_inspection)


# --------------------------------------------------------------------------
# Barrier rooms
# --------------------------------------------------------------------------

@bp.post("/api/rooms")
def create_room():
    uid, role = authenticate()
    require_role(role, ["FacilityManager", "PlatformAdmin"])
    b = V.body()
    # Priority 4: present body foreign keys resolve.
    if b.get("facility_id") is not None:
        V.get_or_404("facilities", b["facility_id"])
    # Priority 8: fields, enums, value constraints.
    facility_id = V.v_str(b, "facility_id")
    room_code = V.v_str(b, "room_code")
    level = V.v_enum(b, "barrier_level", V.BARRIER_LEVELS)
    agents = V.req(b, "excluded_agents")
    if not isinstance(agents, list) or len(agents) == 0 or not all(isinstance(x, str) for x in agents):
        raise V.invalid("excluded_agents must be a non-empty array of agent name strings")
    cap = V.v_int(b, "cage_capacity", minv=1)
    for r in db["rooms"].values():
        if r["facility_id"] == facility_id and r["room_code"] == room_code:
            raise ApiError("ERR_DUPLICATE_KEY", 409, "room_code already exists within the facility")
    rid = new_id()
    db["rooms"][rid] = {
        "id": rid,
        "facility_id": facility_id,
        "room_code": room_code,
        "barrier_level": level,
        "excluded_agents": list(agents),
        "cage_capacity": cap,
        "status": "ACTIVE",
        "quarantined_at": None,
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    return success_object(calc.ser_room(db["rooms"][rid]), 201)


@bp.get("/api/rooms/<rid>")
def get_room(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    return success_object(calc.ser_room(V.get_or_404("rooms", rid)))


@bp.post("/api/rooms/<rid>/transition")
def room_transition(rid):
    uid, role = authenticate()
    require_role(role, ["FacilityManager", "Veterinarian"])
    room = V.get_or_404("rooms", rid)
    b = V.body()
    target = V.v_str(b, "target_state")
    if target == "QUARANTINED":
        require_role(role, ["Veterinarian"])
        if room["status"] != "ACTIVE":
            raise _invalid_state("Room cannot be quarantined from %s" % room["status"])
        # Manual quarantine records quarantined_at but does NOT downgrade.
        room["status"] = "QUARANTINED"
        room["quarantined_at"] = now()
    elif target == "ACTIVE":
        require_role(role, ["Veterinarian"])
        if room["status"] != "QUARANTINED":
            raise _invalid_state("Room is not quarantined")
        ok = any(
            hs["room_id"] == rid
            and hs["status"] == "RESULTED_NEGATIVE"
            and hs["resulted_at"] is not None
            and hs["resulted_at"] > room["quarantined_at"]
            for hs in db["health_screens"].values()
        )
        if not ok:
            raise _invalid_state("No RESULTED_NEGATIVE screen recorded after quarantined_at")
        room["status"] = "ACTIVE"
        room["quarantined_at"] = None
    elif target == "DECOMMISSIONED":
        require_role(role, ["FacilityManager"])
        if room["status"] != "ACTIVE":
            raise _invalid_state("Only an ACTIVE room can be decommissioned")
        for co in db["colonies"].values():
            if co["room_id"] == rid and co["lifecycle_status"] != "RETIRED":
                raise _invalid_state("Room still houses non-retired colonies")
        for c in db["cohorts"].values():
            colony = db["colonies"].get(c["colony_id"])
            if colony and colony["room_id"] == rid and c["status"] in V.LIVE_COHORT_STATUSES:
                raise _invalid_state("Room still houses live cohorts")
        room["status"] = "DECOMMISSIONED"
    else:
        raise _invalid_state("Unknown target_state %s" % target)
    touch("rooms", rid)
    return success_object(calc.ser_room(room))


@bp.get("/api/rooms/<rid>/health-screens")
def room_health_screens(rid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    V.get_or_404("rooms", rid)
    items = [h for h in db["health_screens"].values() if h["room_id"] == rid]
    return V.paginate(items, calc.ser_health_screen)
