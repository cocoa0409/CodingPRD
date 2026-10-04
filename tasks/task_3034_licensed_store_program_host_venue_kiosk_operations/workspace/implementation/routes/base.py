"""Base resources: licensees, host venues, product items, distributors,
employees, loyalty members."""
from flask import Blueprint, request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc

bp = Blueprint("base", __name__)

VENUE_TYPES = ("GROCERY", "AIRPORT", "CAMPUS", "HOSPITAL")
PRODUCT_CATEGORIES = (
    "BEVERAGE_CORE", "BEVERAGE_SEASONAL", "FOOD", "MERCHANDISE", "PROPRIETARY_INGREDIENT",
)
ROLE_TAGS = ("BARISTA", "SHIFT_LEAD", "STORE_MANAGER")


def pub_licensee(l):
    return {
        "id": l["id"], "name": l["name"], "legal_entity_code": l["legal_entity_code"],
        "created_at": l["created_at"], "updated_at": l["updated_at"], "version": l["version"],
    }


def pub_venue(v):
    return {
        "id": v["id"], "name": v["name"], "venue_type": v["venue_type"],
        "open_time_utc": v["open_time_utc"], "close_time_utc": v["close_time_utc"],
        "access_restricted": v["access_restricted"],
        "max_equipment_footprint_units": v["max_equipment_footprint_units"],
        "security_badge_required": v["security_badge_required"],
        "created_at": v["created_at"], "updated_at": v["updated_at"], "version": v["version"],
    }


def pub_product(p):
    return {
        "id": p["id"], "sku": p["sku"], "name": p["name"], "category": p["category"],
        "proprietary": p["proprietary"],
        "venue_type_restrictions": list(p["venue_type_restrictions"]),
        "unit_cost_cents": p["unit_cost_cents"],
        "case_pack_units": p["case_pack_units"],
        "footprint_units": p["footprint_units"],
        "created_at": p["created_at"], "updated_at": p["updated_at"], "version": p["version"],
    }


def pub_distributor(d):
    return {
        "id": d["id"], "name": d["name"], "approved": d["approved"],
        "lead_time_days": d["lead_time_days"],
        "created_at": d["created_at"], "updated_at": d["updated_at"], "version": d["version"],
    }


def pub_employee(e):
    return {
        "id": e["id"], "licensee_id": e["licensee_id"], "full_name": e["full_name"],
        "role_tag": e["role_tag"], "active": e["active"],
        "created_at": e["created_at"], "updated_at": e["updated_at"], "version": e["version"],
    }


def pub_member(m):
    return {
        "id": m["id"], "email": m["email"], "points_balance": m["points_balance"],
        "lifetime_earned": m["lifetime_earned"], "lifetime_redeemed": m["lifetime_redeemed"],
        "created_at": m["created_at"], "updated_at": m["updated_at"], "version": m["version"],
    }


# ---------------------------------------------------------------------------
# Licensees
# ---------------------------------------------------------------------------

@bp.post("/licensing/licensees")
def create_licensee():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    name = mw.req_str(b, "name")
    code = mw.req_str(b, "legal_entity_code")
    for l in db.licensees.values():
        if l["legal_entity_code"] == code:
            raise E.err_uniqueness("legal_entity_code already in use")
    rec = mw.make_resource({"name": name, "legal_entity_code": code})
    db.licensees[rec["id"]] = rec
    return success_object(pub_licensee(rec), 201)


@bp.get("/licensing/licensees/<lid>")
def get_licensee(lid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    l = db.licensees.get(lid)
    if l is None:
        raise E.err_not_found("licensee not found")
    mw.check_licensee_scope(uid, role, l["id"])
    return success_object(pub_licensee(l))


@bp.get("/licensing/licensees")
def list_licensees():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    page, limit, offset, total = mw.paginate(db.licensees.values())
    return success_list([pub_licensee(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Host venues
# ---------------------------------------------------------------------------

@bp.post("/licensing/host-venues")
def create_venue():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    name = mw.req_str(b, "name")
    vtype = mw.req_enum(b, "venue_type", VENUE_TYPES)
    open_t = mw.req_time_hhmm(b, "open_time_utc")
    close_t = mw.req_time_hhmm(b, "close_time_utc")
    access_restricted = mw.req_bool(b, "access_restricted")
    max_fp = mw.req_int(b, "max_equipment_footprint_units", minimum=1)
    badge = mw.req_bool(b, "security_badge_required")
    if close_t <= open_t:
        raise E.err_invalid_request("close_time_utc must be strictly after open_time_utc")
    rec = mw.make_resource({
        "name": name, "venue_type": vtype, "open_time_utc": open_t,
        "close_time_utc": close_t, "access_restricted": access_restricted,
        "max_equipment_footprint_units": max_fp, "security_badge_required": badge,
    })
    db.host_venues[rec["id"]] = rec
    return success_object(pub_venue(rec), 201)


@bp.get("/licensing/host-venues/<vid>")
def get_venue(vid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "HostVenueManager", "LicenseeManager"))
    v = db.host_venues.get(vid)
    if v is None:
        raise E.err_not_found("host venue not found")
    return success_object(pub_venue(v))


@bp.get("/licensing/host-venues")
def list_venues():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    vtype = request.args.get("venue_type")
    items = [v for v in db.host_venues.values() if vtype is None or v["venue_type"] == vtype]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_venue(x) for x in page], limit, offset, total)


@bp.patch("/licensing/host-venues/<vid>")
def patch_venue(vid):
    uid, role = mw.auth()
    mw.require_role(role, ("HostVenueManager", "BrandProgramAdmin"))
    v = db.host_venues.get(vid)
    if v is None:
        raise E.err_not_found("host venue not found")
    if role == "HostVenueManager" and uid != vid:
        raise E.err_forbidden("HostVenueManager may only update its own venue")
    b = mw.body()
    new_open = mw.opt_time_hhmm(b, "open_time_utc", v["open_time_utc"])
    new_close = mw.opt_time_hhmm(b, "close_time_utc", v["close_time_utc"])
    new_access = mw.opt_bool(b, "access_restricted", v["access_restricted"])
    new_badge = mw.opt_bool(b, "security_badge_required", v["security_badge_required"])
    new_max = mw.opt_int(b, "max_equipment_footprint_units", v["max_equipment_footprint_units"], minimum=1)
    if new_close <= new_open:
        raise E.err_invalid_request("close_time_utc must be strictly after open_time_utc")
    usage = calc.venue_footprint_usage(vid)
    if usage > new_max:
        raise E.err_footprint("new cap is below the venue's current footprint usage")
    v["open_time_utc"] = new_open
    v["close_time_utc"] = new_close
    v["access_restricted"] = new_access
    v["security_badge_required"] = new_badge
    v["max_equipment_footprint_units"] = new_max
    mw.touch(v)
    return success_object(pub_venue(v))


# ---------------------------------------------------------------------------
# Product items
# ---------------------------------------------------------------------------

@bp.post("/licensing/product-items")
def create_product():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    sku = mw.req_str(b, "sku")
    name = mw.req_str(b, "name")
    category = mw.req_enum(b, "category", PRODUCT_CATEGORIES)
    proprietary = mw.req_bool(b, "proprietary")
    restrictions = b.get("venue_type_restrictions")
    if not isinstance(restrictions, list):
        raise E.err_invalid_request("venue_type_restrictions must be an array")
    for r in restrictions:
        if r not in VENUE_TYPES:
            raise E.err_invalid_request("venue_type_restrictions contains an invalid venue type")
    unit_cost = mw.req_int(b, "unit_cost_cents", minimum=1)
    case_pack = mw.req_int(b, "case_pack_units", minimum=1)
    footprint = mw.req_int(b, "footprint_units", minimum=0)
    for p in db.product_items.values():
        if p["sku"] == sku:
            raise E.err_uniqueness("sku already in use")
    rec = mw.make_resource({
        "sku": sku, "name": name, "category": category, "proprietary": proprietary,
        "venue_type_restrictions": list(restrictions), "unit_cost_cents": unit_cost,
        "case_pack_units": case_pack, "footprint_units": footprint,
    })
    db.product_items[rec["id"]] = rec
    return success_object(pub_product(rec), 201)


@bp.get("/licensing/product-items/<pid>")
def get_product(pid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    p = db.product_items.get(pid)
    if p is None:
        raise E.err_not_found("product not found")
    return success_object(pub_product(p))


@bp.get("/licensing/product-items")
def list_products():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    cat = request.args.get("category")
    items = [p for p in db.product_items.values() if cat is None or p["category"] == cat]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_product(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Distributors
# ---------------------------------------------------------------------------

@bp.post("/licensing/distributors")
def create_distributor():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    name = mw.req_str(b, "name")
    lead = mw.req_int(b, "lead_time_days", minimum=0)
    rec = mw.make_resource({"name": name, "approved": False, "lead_time_days": lead})
    db.distributors[rec["id"]] = rec
    return success_object(pub_distributor(rec), 201)


@bp.get("/licensing/distributors/<did>")
def get_distributor(did):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "DistributorAgent", "LicenseeManager"))
    d = db.distributors.get(did)
    if d is None:
        raise E.err_not_found("distributor not found")
    return success_object(pub_distributor(d))


@bp.get("/licensing/distributors")
def list_distributors():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    approved_q = request.args.get("approved")
    items = list(db.distributors.values())
    if approved_q is not None:
        if approved_q.lower() == "true":
            items = [d for d in items if d["approved"]]
        elif approved_q.lower() == "false":
            items = [d for d in items if not d["approved"]]
        else:
            raise E.err_invalid_request("'approved' must be true or false")
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_distributor(x) for x in page], limit, offset, total)


@bp.patch("/licensing/distributors/<did>")
def patch_distributor(did):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    d = db.distributors.get(did)
    if d is None:
        raise E.err_not_found("distributor not found")
    b = mw.body()
    new_approved = mw.opt_bool(b, "approved", d["approved"])
    new_lead = mw.opt_int(b, "lead_time_days", d["lead_time_days"], minimum=0)
    d["approved"] = new_approved
    d["lead_time_days"] = new_lead
    mw.touch(d)
    return success_object(pub_distributor(d))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

@bp.post("/licensing/licensees/<lid>/employees")
def create_employee(lid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    l = db.licensees.get(lid)
    if l is None:
        raise E.err_not_found("licensee not found")
    mw.check_licensee_scope(uid, role, lid)
    b = mw.body()
    full_name = mw.req_str(b, "full_name")
    role_tag = mw.req_enum(b, "role_tag", ROLE_TAGS)
    active = mw.opt_bool(b, "active", True)
    rec = mw.make_resource({
        "licensee_id": lid, "full_name": full_name, "role_tag": role_tag, "active": active,
    })
    db.employees[rec["id"]] = rec
    return success_object(pub_employee(rec), 201)


@bp.get("/licensing/employees/<eid>")
def get_employee(eid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "BrandInspector"))
    e = db.employees.get(eid)
    if e is None:
        raise E.err_not_found("employee not found")
    mw.check_licensee_scope(uid, role, e["licensee_id"])
    return success_object(pub_employee(e))


@bp.get("/licensing/employees")
def list_employees():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    items = list(db.employees.values())
    if role == "LicenseeManager":
        items = [e for e in items if e["licensee_id"] == uid]
    lic = request.args.get("licensee_id")
    if lic is not None:
        items = [e for e in items if e["licensee_id"] == lic]
    rt = request.args.get("role_tag")
    if rt is not None:
        items = [e for e in items if e["role_tag"] == rt]
    act = request.args.get("active")
    if act is not None:
        if act.lower() == "true":
            items = [e for e in items if e["active"]]
        elif act.lower() == "false":
            items = [e for e in items if not e["active"]]
        else:
            raise E.err_invalid_request("'active' must be true or false")
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_employee(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Loyalty members
# ---------------------------------------------------------------------------

@bp.post("/licensing/loyalty-members")
def create_member():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    b = mw.body()
    email = mw.req_str(b, "email")
    for m in db.loyalty_members.values():
        if m["email"] == email:
            raise E.err_uniqueness("member email already in use")
    rec = mw.make_resource({
        "email": email, "points_balance": 0, "lifetime_earned": 0, "lifetime_redeemed": 0,
    })
    db.loyalty_members[rec["id"]] = rec
    return success_object(pub_member(rec), 201)


@bp.get("/licensing/loyalty-members/<mid>")
def get_member(mid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "LoyaltyMember"))
    m = db.loyalty_members.get(mid)
    if m is None:
        raise E.err_not_found("loyalty member not found")
    mw.check_member_scope(uid, role, mid)
    return success_object(pub_member(m))
