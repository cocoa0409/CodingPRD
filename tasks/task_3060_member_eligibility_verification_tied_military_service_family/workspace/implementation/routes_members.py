from flask import Blueprint, request

import auth
import store
from domain import (
    ser_member, matrix_response, recompute_member_matrix, recompute_household,
    cascade_entitlements_grandfather, cascade_entitlements_close_member_loss,
    cascade_descendants_suspend,
)
from envelope import success
from errors import err
from helpers import new_row, touch, require_field, optional_field, require_enum
from paginate import list_response

bp = Blueprint("members", __name__)

LOSS_TYPES = {"DOCUMENTATION_REVOKED", "FRAUD_CONFIRMED"}


def _get_member(member_id):
    m = store.T["members"].get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", 404, "member not found")
    return m


@bp.get("/membership/members")
def list_members():
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    rows = list(store.T["members"].values())
    status = request.args.get("status")
    cat = request.args.get("eligibility_category")
    hh = request.args.get("household_id")
    sponsor = request.args.get("sponsor_member_id")
    case_id = request.args.get("case_id")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if cat:
        rows = [r for r in rows if r["eligibility_category"] == cat]
    if hh:
        rows = [r for r in rows if r["household_id"] == hh]
    if sponsor:
        rows = [r for r in rows if r["sponsor_member_id"] == sponsor]
    if case_id:
        rows = [r for r in rows if r["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_member(r) for r in rows], success)


@bp.get("/membership/members/<member_id>")
def get_member(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    m = _get_member(member_id)
    return success(200, ser_member(m), "object")


@bp.get("/membership/members/<member_id>/product-matrix")
def get_product_matrix(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    m = _get_member(member_id)
    return success(200, matrix_response(m), "object")


@bp.post("/membership/members/<member_id>/eligibility-loss")
def eligibility_loss(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    m = _get_member(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    loss_type = require_enum(body, "loss_type", LOSS_TYPES)
    optional_field(body, "loss_note")

    # Determine valid transition from current state + loss_type
    if loss_type == "DOCUMENTATION_REVOKED":
        if m["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", 409, "documentation loss requires ACTIVE member")
        m["status"] = "SUSPENDED"
        m["_loss_timestamp"] = store.now_iso_ms()
        cascade_entitlements_grandfather(m)
    else:  # FRAUD_CONFIRMED
        if m["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", 409, "fraud revocation requires SUSPENDED member")
        m["status"] = "REVOKED"
        m["_loss_timestamp"] = store.now_iso_ms()
        cascade_entitlements_close_member_loss(m)
        cascade_descendants_suspend(m)

    recompute_member_matrix(m)
    touch(m)
    if m["household_id"]:
        recompute_household(store.T["households"][m["household_id"]])
    return success(200, ser_member(m), "object")


@bp.post("/membership/members/<member_id>/reinstate")
def reinstate(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    m = _get_member(member_id)
    request.get_json(silent=True)

    if m["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", 409, "member not suspended")

    loss_ts = m.get("_loss_timestamp")
    docs = [d for d in store.T["evidence_docs"].values() if d["case_id"] == m["case_id"]]
    restored = False
    for d in docs:
        if loss_ts is not None and d["created_at"] > loss_ts:
            restored = True
            break
    if not restored:
        raise err("ERR_REINSTATEMENT_EVIDENCE_REQUIRED", 422,
                  "restoration evidence required")

    m["status"] = "ACTIVE"
    recompute_member_matrix(m)
    touch(m)
    if m["household_id"]:
        recompute_household(store.T["households"][m["household_id"]])
    return success(200, ser_member(m), "object")


@bp.post("/membership/members/<member_id>/deceased")
def mark_deceased(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["BenefitsOfficer"])
    m = _get_member(member_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    optional_field(body, "date_of_death")
    beneficiary_id = optional_field(body, "beneficiary_member_id")

    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "member not active")

    # Determine beneficiary
    beneficiary = None
    if beneficiary_id is not None:
        beneficiary = store.T["members"].get(beneficiary_id)
        if beneficiary is None:
            raise err("ERR_INVALID_REFERENCE", 422, "beneficiary_member_id does not resolve")
    else:
        # surviving spouse member, else earliest-created surviving child member
        spouse = None
        child = None
        for x in store.T["members"].values():
            if x["id"] == m["id"]:
                continue
            if x["status"] == "DECEASED":
                continue
            if x["sponsor_member_id"] == m["id"]:
                if x["claimed_relationship"] in ("SPOUSE", "WIDOW_WIDOWER"):
                    if spouse is None or (x["created_at"], x["id"]) < (spouse["created_at"], spouse["id"]):
                        spouse = x
                elif x["claimed_relationship"] in ("CHILD", "STEPCHILD"):
                    if child is None or (x["created_at"], x["id"]) < (child["created_at"], child["id"]):
                        child = x
        beneficiary = spouse if spouse is not None else child

    m["status"] = "DECEASED"
    recompute_member_matrix(m)
    touch(m)
    if m["household_id"]:
        recompute_household(store.T["households"][m["household_id"]])

    if beneficiary is not None:
        row = new_row()
        row.update({
            "member_id": m["id"],
            "beneficiary_member_id": beneficiary["id"],
            "continuance_months": None,
            "continuance_amount_cents": None,
            "transfer_household_id": None,
            "resolution_note": None,
            "status": "OPEN",
        })
        store.insert_row("survivor_cases", row)

    return success(200, ser_member(m), "object")


@bp.post("/membership/members/<member_id>/link-household")
def link_household(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer"])
    auth.enforce_ownership(c, member_id)
    m = _get_member(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    household_id = require_field(body, "household_id")
    expected = require_field(body, "expected_member_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", 400, "invalid expected_member_version")

    hh = store.T["households"].get(household_id)
    if hh is None:
        raise err("ERR_NOT_FOUND", 404, "household not found")

    # OCC check
    if expected != m["version"]:
        raise err("ERR_STALE_VERSION", 412, "stale member version")

    old_hh_id = m["household_id"]
    m["household_id"] = household_id
    recompute_member_matrix(m)
    touch(m)  # increments version by 1
    if old_hh_id:
        recompute_household(store.T["households"][old_hh_id])
    recompute_household(hh)
    return success(200, ser_member(m), "object")


@bp.post("/membership/members/<member_id>/delink-household")
def delink_household(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer"])
    auth.enforce_ownership(c, member_id)
    m = _get_member(member_id)
    request.get_json(silent=True)

    old_hh_id = m["household_id"]
    m["household_id"] = None
    touch(m)
    if old_hh_id:
        recompute_household(store.T["households"][old_hh_id])
    return success(200, ser_member(m), "object")
