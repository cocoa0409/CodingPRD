"""Vendor qualification and component-lot procurement routes."""
from datetime import timedelta

from flask import Blueprint, request

from calc import derive_qualified_variant, recompute_vendor_flags
from errors import (ApiError, ERR_AUDIT_OVERLAP, ERR_DUPLICATE,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_PROCUREMENT_GATE)
from rbac import require_role
from store import (DB, apply_pagination, base_record, iso_ms, paginate_args,
                   parse_iso, serialize, sort_by_created, success_list,
                   success_object, touch)
from validation import get_or_404, json_body, v_bool, v_int, v_iso, v_str

bp = Blueprint("vendors", __name__, url_prefix="/licensing")

ACTIVE_QUAL_STATUSES = ("AUDIT_SCHEDULED", "CONDITIONALLY_QUALIFIED", "FULLY_QUALIFIED")
OVERLAP_DAYS = 14


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


@bp.post("/vendors")
def create_vendor():
    require_role("SupplyChainManager")
    body = json_body()
    name = v_str(body, "name")
    scope = v_str(body, "capability_scope")
    if any(v["name"] == name for v in DB["vendor"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "vendor name already exists")
    vendor = base_record("vendor", {
        "name": name,
        "capability_scope": scope,
        "qualified": False,
        "has_active_qualification": False,
    })
    DB["vendor"][vendor["id"]] = vendor
    return success_object(serialize(vendor), status=201)


@bp.get("/vendors/<id>")
def get_vendor(id):
    require_role()
    return success_object(serialize(get_or_404("vendor", id)))


@bp.post("/vendors/<vendor_id>/qualifications")
def schedule_qualification(vendor_id):
    require_role("VendorAuditor")
    get_or_404("vendor", vendor_id)
    body = json_body()
    audit_date = v_iso(body, "audit_date")
    defects = v_int(body, "defects_found", minimum=0)

    # overlap: +/-14 days against any non-superseded qualification of the vendor
    for q in DB["vendor_qualification"].values():
        if q["vendor_id"] != vendor_id or q["status"] == "SUPERSEDED":
            continue
        existing = parse_iso(q["audit_date"])
        if abs((audit_date - existing).total_seconds()) < OVERLAP_DAYS * 86400:
            raise ApiError(ERR_AUDIT_OVERLAP, 409,
                           "audit_date overlaps an existing qualification audit")

    # supersede the prior active qualification
    for q in DB["vendor_qualification"].values():
        if q["vendor_id"] == vendor_id and q["status"] in ACTIVE_QUAL_STATUSES:
            q["status"] = "SUPERSEDED"
            q["qualified_variant"] = derive_qualified_variant(q["status"], q["defects_found"])
            touch(q)

    cycle = max([q["cycle_number"] for q in DB["vendor_qualification"].values()
                 if q["vendor_id"] == vendor_id], default=0) + 1
    qual = base_record("vendor_qualification", {
        "vendor_id": vendor_id,
        "cycle_number": cycle,
        "audit_date": iso_ms(audit_date),
        "defects_found": defects,
        "status": "AUDIT_SCHEDULED",
        "qualified_variant": derive_qualified_variant("AUDIT_SCHEDULED", defects),
    })
    DB["vendor_qualification"][qual["id"]] = qual
    recompute_vendor_flags(vendor_id)
    return success_object(serialize(qual), status=201)


@bp.get("/vendor-qualifications")
def list_qualifications():
    require_role()
    items = list(DB["vendor_qualification"].values())
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        items = [q for q in items if q["vendor_id"] == vendor_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(q) for q in page], total, limit, offset)


@bp.get("/vendor-qualifications/<id>")
def get_qualification(id):
    require_role()
    return success_object(serialize(get_or_404("vendor_qualification", id)))


def _get_nested_qual(vendor_id, qual_id):
    get_or_404("vendor", vendor_id)
    qual = get_or_404("vendor_qualification", qual_id)
    if qual["vendor_id"] != vendor_id:
        raise ApiError(ERR_NOT_FOUND, 404, "qualification does not belong to vendor")
    return qual


@bp.post("/vendors/<vendor_id>/qualifications/<id>/complete-audit")
def complete_audit(vendor_id, id):
    require_role("VendorAuditor")
    qual = _get_nested_qual(vendor_id, id)
    if qual["status"] != "AUDIT_SCHEDULED":
        raise _invalid("qualification is not AUDIT_SCHEDULED")
    qual["status"] = "CONDITIONALLY_QUALIFIED" if qual["defects_found"] >= 1 else "FULLY_QUALIFIED"
    qual["qualified_variant"] = derive_qualified_variant(qual["status"], qual["defects_found"])
    touch(qual)
    recompute_vendor_flags(vendor_id)
    return success_object(serialize(qual))


@bp.post("/vendors/<vendor_id>/qualifications/<id>/upgrade")
def upgrade_qual(vendor_id, id):
    require_role("VendorAuditor")
    qual = _get_nested_qual(vendor_id, id)
    if qual["status"] != "CONDITIONALLY_QUALIFIED":
        raise _invalid("qualification is not CONDITIONALLY_QUALIFIED")
    if qual["defects_found"] >= 3:
        raise _invalid("defects_found at or above the qualification threshold")
    qual["status"] = "FULLY_QUALIFIED"
    qual["qualified_variant"] = derive_qualified_variant(qual["status"], qual["defects_found"])
    touch(qual)
    recompute_vendor_flags(vendor_id)
    return success_object(serialize(qual))


@bp.post("/vendors/<vendor_id>/qualifications/<id>/disqualify")
def disqualify_qual(vendor_id, id):
    require_role("VendorAuditor")
    qual = _get_nested_qual(vendor_id, id)
    if qual["status"] == "AUDIT_SCHEDULED":
        if qual["defects_found"] < 3:
            raise _invalid("disqualification from AUDIT_SCHEDULED requires defects >= 3")
    elif qual["status"] != "CONDITIONALLY_QUALIFIED":
        raise _invalid("qualification cannot be disqualified from its current state")
    was_conditional = qual["status"] == "CONDITIONALLY_QUALIFIED"
    qual["status"] = "DISQUALIFIED"
    qual["qualified_variant"] = derive_qualified_variant(qual["status"], qual["defects_found"])
    touch(qual)
    if was_conditional:
        # cascade: PROCURED lots of this vendor -> REJECTED
        for lot in DB["component_lot"].values():
            if lot["vendor_id"] == vendor_id and lot["status"] == "PROCURED":
                lot["status"] = "REJECTED"
                touch(lot)
    recompute_vendor_flags(vendor_id)
    return success_object(serialize(qual))


# ---------------------------------------------------------------------------
# Component lots
# ---------------------------------------------------------------------------
@bp.post("/component-lots")
def create_lot():
    require_role("SupplyChainManager")
    body = json_body()
    vendor_id = v_str(body, "vendor_id")
    program_id = v_str(body, "program_id")
    component_type = v_str(body, "component_type")
    quantity = v_int(body, "quantity", minimum=1)
    nuclear_grade = v_bool(body, "nuclear_grade", required=False, default=True)

    vendor = get_or_404("vendor", vendor_id)
    program = get_or_404("test_program", program_id)

    if nuclear_grade:
        if not vendor.get("qualified") or program["status"] != "ADEQUATE":
            raise ApiError(ERR_PROCUREMENT_GATE, 422,
                           "nuclear-grade procurement requires a qualified vendor and an ADEQUATE program")

    lot = base_record("component_lot", {
        "vendor_id": vendor_id,
        "program_id": program_id,
        "component_type": component_type,
        "nuclear_grade": nuclear_grade,
        "quantity": quantity,
        "status": "PROCURED",
    })
    DB["component_lot"][lot["id"]] = lot
    return success_object(serialize(lot), status=201)


@bp.get("/component-lots")
def list_lots():
    require_role()
    items = list(DB["component_lot"].values())
    for param in ("vendor_id", "program_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if l[param] == val]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(l) for l in page], total, limit, offset)


@bp.get("/component-lots/<id>")
def get_lot(id):
    require_role()
    return success_object(serialize(get_or_404("component_lot", id)))


@bp.post("/component-lots/<id>/deliver")
def deliver_lot(id):
    require_role("SupplyChainManager")
    lot = get_or_404("component_lot", id)
    if lot["status"] != "PROCURED":
        raise _invalid("lot is not PROCURED")
    vendor = get_or_404("vendor", lot["vendor_id"])
    if not vendor.get("qualified"):
        raise ApiError(ERR_PROCUREMENT_GATE, 422, "vendor is no longer qualified")
    lot["status"] = "DELIVERED"
    touch(lot)
    return success_object(serialize(lot))


@bp.post("/component-lots/<id>/release")
def release_lot(id):
    require_role("SupplyChainManager")
    lot = get_or_404("component_lot", id)
    if lot["status"] != "DELIVERED":
        raise _invalid("lot is not DELIVERED")
    program = get_or_404("test_program", lot["program_id"])
    if program["status"] != "ADEQUATE":
        raise ApiError(ERR_PROCUREMENT_GATE, 422, "program is no longer ADEQUATE")
    lot["status"] = "RELEASED"
    touch(lot)
    return success_object(serialize(lot))
