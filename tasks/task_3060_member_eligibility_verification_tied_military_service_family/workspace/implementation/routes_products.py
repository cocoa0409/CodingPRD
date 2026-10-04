from flask import Blueprint, request

import auth
import store
from domain import (
    ser_offering, ser_entitlement, recompute_member_matrix,
    recompute_household, recompute_all_households, VALID_CATEGORIES,
)
from envelope import success
from errors import err
from helpers import (
    new_row, touch, require_field, require_enum, optional_bool,
    optional_int,
)
from store import clock_now_dt
from paginate import list_response

bp = Blueprint("products", __name__)

PRODUCT_LINES = {"BANKING", "INSURANCE", "INVESTMENT"}


def _get_member(member_id):
    m = store.T["members"].get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", 404, "member not found")
    return m


def _get_offering(offering_id):
    o = store.T["product_offerings"].get(offering_id)
    if o is None:
        raise err("ERR_NOT_FOUND", 404, "product offering not found")
    return o


def _get_entitlement(entitlement_id):
    e = store.T["entitlements"].get(entitlement_id)
    if e is None:
        raise err("ERR_NOT_FOUND", 404, "entitlement not found")
    return e


@bp.post("/membership/product-offerings")
def create_offering():
    c = auth.ctx()
    auth.require_roles(c, ["ProductAdministrator"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    code = require_field(body, "product_code")
    line = require_enum(body, "product_line", PRODUCT_LINES)
    name = require_field(body, "product_name")
    cats = require_field(body, "allowed_categories")
    if not isinstance(cats, list) or not all(isinstance(x, str) for x in cats):
        raise err("ERR_INVALID_REQUEST", 400, "allowed_categories must be a list of strings")
    for x in cats:
        if x not in VALID_CATEGORIES:
            raise err("ERR_INVALID_REQUEST", 400, "invalid eligibility category")
    ras = optional_bool(body, "requires_active_status", True)
    dep = optional_bool(body, "deployment_enhanced", False)

    row = new_row()
    row.update({
        "product_code": code,
        "product_line": line,
        "product_name": name,
        "allowed_categories": list(cats),
        "requires_active_status": ras,
        "deployment_enhanced": dep,
        "is_active_flag": True,
    })
    store.insert_row("product_offerings", row)
    # catalog change affects all member matrices + household aggregates
    for m in store.T["members"].values():
        recompute_member_matrix(m)
    recompute_all_households()
    return success(201, ser_offering(row), "object")


@bp.get("/membership/product-offerings")
def list_offerings():
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer",
                           "ProductAdministrator", "PlatformAdmin"])
    rows = list(store.T["product_offerings"].values())
    line = request.args.get("product_line")
    flag = request.args.get("is_active_flag")
    if line:
        rows = [o for o in rows if o["product_line"] == line]
    if flag is not None:
        want = flag.lower() == "true"
        rows = [o for o in rows if o["is_active_flag"] == want]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_offering(r) for r in rows], success)


@bp.get("/membership/product-offerings/<offering_id>")
def get_offering(offering_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer",
                           "ProductAdministrator", "PlatformAdmin"])
    return success(200, ser_offering(_get_offering(offering_id)), "object")


@bp.route("/membership/product-offerings/<offering_id>", methods=["PATCH"])
def patch_offering(offering_id):
    c = auth.ctx()
    auth.require_roles(c, ["ProductAdministrator"])
    o = _get_offering(offering_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")

    retiring = False
    cats_changed = False
    if "allowed_categories" in body:
        v = body["allowed_categories"]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise err("ERR_INVALID_REQUEST", 400, "allowed_categories must be a list")
        for x in v:
            if x not in VALID_CATEGORIES:
                raise err("ERR_INVALID_REQUEST", 400, "invalid eligibility category")
        if v != o["allowed_categories"]:
            cats_changed = True
        o["allowed_categories"] = list(v)
    if "requires_active_status" in body:
        v = body["requires_active_status"]
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", 400, "invalid requires_active_status")
        o["requires_active_status"] = v
    if "deployment_enhanced" in body:
        v = body["deployment_enhanced"]
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", 400, "invalid deployment_enhanced")
        o["deployment_enhanced"] = v
    if "is_active_flag" in body:
        v = body["is_active_flag"]
        if not isinstance(v, bool):
            raise err("ERR_INVALID_REQUEST", 400, "invalid is_active_flag")
        if o["is_active_flag"] and v is False:
            retiring = True
        o["is_active_flag"] = v

    touch(o)

    if retiring:
        # close all OPEN/GRANDFATHERED entitlements on this offering
        for e in store.T["entitlements"].values():
            if e["product_offering_id"] == o["id"] and e["status"] in ("OPEN", "GRANDFATHERED"):
                e["status"] = "CLOSED"
                e["closure_reason"] = "GRANDFATHERED_RETIRE"
                touch(e)
    elif cats_changed:
        # grandfather OPEN entitlements whose holder's category is no longer allowed
        for e in store.T["entitlements"].values():
            if e["product_offering_id"] != o["id"] or e["status"] != "OPEN":
                continue
            holder = store.T["members"].get(e["member_id"])
            if holder is None:
                continue
            if holder["eligibility_category"] not in o["allowed_categories"]:
                e["status"] = "GRANDFATHERED"
                e["grandfathered"] = True
                touch(e)

    # recompute matrices + household aggregates for affected members
    for m in store.T["members"].values():
        recompute_member_matrix(m)
    recompute_all_households()
    return success(200, ser_offering(o), "object")


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------

@bp.post("/membership/members/<member_id>/entitlements")
def create_entitlement(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "BenefitsOfficer"])
    auth.enforce_ownership(c, member_id)
    m = _get_member(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    offering_id = require_field(body, "product_offering_id")
    exposure = optional_int(body, "exposure_cents", 0)

    o = store.T["product_offerings"].get(offering_id)
    if o is None:
        raise err("ERR_INVALID_REFERENCE", 422, "product_offering_id does not resolve")

    # Priority 15: category gate
    if not o["is_active_flag"] or m["eligibility_category"] not in o["allowed_categories"]:
        raise err("ERR_PRODUCT_CATEGORY_FORBIDDEN", 422, "category gate forbids entitlement")

    row = new_row()
    row.update({
        "member_id": member_id,
        "product_offering_id": offering_id,
        "opened_at": clock_now_dt().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "closure_reason": None,
        "grandfathered": False,
        "exposure_cents": exposure,
        "status": "OPEN",
    })
    store.insert_row("entitlements", row)
    return success(201, ser_entitlement(row), "object")


@bp.get("/membership/members/<member_id>/entitlements")
def list_member_entitlements(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    rows = [e for e in store.T["entitlements"].values() if e["member_id"] == member_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_entitlement(r) for r in rows], success)


@bp.get("/membership/entitlements")
def list_entitlements():
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    rows = list(store.T["entitlements"].values())
    member_id = request.args.get("member_id")
    offering_id = request.args.get("product_offering_id")
    if member_id:
        rows = [e for e in rows if e["member_id"] == member_id]
    if offering_id:
        rows = [e for e in rows if e["product_offering_id"] == offering_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_entitlement(r) for r in rows], success)


@bp.get("/membership/entitlements/<entitlement_id>")
def get_entitlement(entitlement_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    e = _get_entitlement(entitlement_id)
    if c["role"] == "Member" and c["uid"] != e["member_id"]:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")
    return success(200, ser_entitlement(e), "object")


@bp.post("/membership/members/<member_id>/entitlements/<entitlement_id>/close")
def close_entitlement(member_id, entitlement_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "BenefitsOfficer"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    e = _get_entitlement(entitlement_id)
    if e["member_id"] != member_id:
        raise err("ERR_NOT_FOUND", 404, "entitlement not found for member")
    request.get_json(silent=True)

    if e["status"] not in ("OPEN", "GRANDFATHERED"):
        raise err("ERR_INVALID_STATE", 409, "entitlement not closable")

    e["status"] = "CLOSED"
    e["closure_reason"] = "VOLUNTARY"
    touch(e)
    m = store.T["members"][member_id]
    if m["household_id"]:
        recompute_household(store.T["households"][m["household_id"]])
    return success(200, ser_entitlement(e), "object")
