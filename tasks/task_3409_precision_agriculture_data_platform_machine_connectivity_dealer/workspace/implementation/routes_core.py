"""Clock, organizations, and dealers (PRD sections 2.4 and 3.1)."""

from flask import Blueprint

from auth import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    as_dt,
    body_json,
    caller,
    get_or_404,
    need,
    require_role,
    access_denied,
)
from db import STORES, iso, now, set_clock
from domain import (
    cascade_org_suspended,
    clock_sweep,
    new_record,
    serialize,
    touch,
)
from envelope import created, ok
from errors import ERR_INVALID_REQUEST, ApiError, invalid_state

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def clock_set():
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    newt = as_dt(need(b, "current_utc"), "current_utc")
    if newt < now():
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "current_utc must be monotonically non-decreasing",
        )
    set_clock(newt)
    clock_sweep()
    return ok({"current_utc": iso(newt)})


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------

@bp.post("/organizations")
def create_organization():
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    name = as_str(need(b, "name"), "name")
    region_code = as_str(need(b, "region_code"), "region_code")
    rtr = b.get("right_to_repair_enabled", False)
    if not isinstance(rtr, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "right_to_repair_enabled must be a boolean")
    ism = b.get("independent_session_max_minutes", 60)
    as_int(ism, "independent_session_max_minutes")
    rec = new_record(
        {
            "name": name,
            "region_code": region_code,
            "right_to_repair_enabled": rtr,
            "independent_session_max_minutes": ism,
            "status": "ACTIVE",
        }
    )
    STORES["organizations"][rec["id"]] = rec
    return created(serialize(rec))


@bp.post("/organizations/<oid>/suspend")
def suspend_organization(oid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    org = get_or_404("organizations", oid, "organization")
    if org["status"] != "ACTIVE":
        raise invalid_state("organization is not ACTIVE")
    org["status"] = "SUSPENDED"
    touch(org)
    cascade_org_suspended(org)
    return ok(serialize(org))


@bp.post("/organizations/<oid>/resume")
def resume_organization(oid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    org = get_or_404("organizations", oid, "organization")
    if org["status"] != "SUSPENDED":
        raise invalid_state("organization is not SUSPENDED")
    org["status"] = "ACTIVE"
    touch(org)
    # Deliberately revives nothing: plans, grants, sessions and failed
    # deliveries must each be resumed or retried individually.
    return ok(serialize(org))


# ---------------------------------------------------------------------------
# Dealers
# ---------------------------------------------------------------------------

@bp.post("/dealers")
def create_dealer():
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    b = body_json()
    dealer_code = as_str(need(b, "dealer_code"), "dealer_code")
    name = as_str(need(b, "name"), "name")
    region_code = as_str(need(b, "region_code"), "region_code")
    service_tier = as_enum(need(b, "service_tier"), "service_tier", {"STANDARD", "PREMIUM"})
    for d in STORES["dealers"].values():
        if d["dealer_code"] == dealer_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "dealer_code must be unique")
    rec = new_record(
        {
            "dealer_code": dealer_code,
            "name": name,
            "region_code": region_code,
            "service_tier": service_tier,
            "status": "ACTIVE",
            "warranty_reserve_cents": 0,
            "warranty_paid_cents": 0,
        }
    )
    STORES["dealers"][rec["id"]] = rec
    return created(serialize(rec))


@bp.get("/dealers/<did>")
def get_dealer(did):
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "DealerTechnician"})
    d = get_or_404("dealers", did, "dealer")
    if role == "DealerTechnician" and uid != did:
        raise access_denied("a dealer technician may read only their own dealer record")
    return ok(serialize(d))


@bp.post("/dealers/<did>/suspend")
def suspend_dealer(did):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    d = get_or_404("dealers", did, "dealer")
    if d["status"] != "ACTIVE":
        raise invalid_state("dealer is not ACTIVE")
    d["status"] = "SUSPENDED"
    touch(d)
    # Existing OPEN sessions and SUBMITTED claims are deliberately unaffected.
    return ok(serialize(d))
