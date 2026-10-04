from flask import Blueprint, request

import auth
import store
from domain import (
    ser_household, ser_survivor, recompute_household,
    recompute_member_matrix,
)
from envelope import success
from errors import err
from helpers import new_row, touch, require_field
from paginate import list_response

bp = Blueprint("households", __name__)

SURVIVOR_DEDUCTIBLE_CENTS = 50000
SPOUSE_MONTHS = 3
CHILD_MONTHS = 2


def _get_household(household_id):
    h = store.T["households"].get(household_id)
    if h is None:
        raise err("ERR_NOT_FOUND", 404, "household not found")
    return h


def _get_survivor(case_id):
    s = store.T["survivor_cases"].get(case_id)
    if s is None:
        raise err("ERR_NOT_FOUND", 404, "survivor case not found")
    return s


def _get_member(member_id):
    m = store.T["members"].get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", 404, "member not found")
    return m


@bp.post("/membership/households")
def create_household():
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    name = require_field(body, "household_name")
    primary_id = require_field(body, "primary_member_id")

    primary = store.T["members"].get(primary_id)
    if primary is None:
        raise err("ERR_INVALID_REFERENCE", 422, "primary_member_id does not resolve")
    # Member role may only anchor a household on itself
    if c["role"] == "Member" and c["uid"] != primary_id:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")

    row = new_row()
    row.update({
        "household_name": name,
        "primary_member_id": primary_id,
        "aggregate_product_count": 0,
        "status": "ACTIVE",
    })
    store.insert_row("households", row)

    primary["household_id"] = row["id"]
    touch(primary)
    recompute_household(row)
    return success(201, ser_household(row), "object")


@bp.get("/membership/households")
def list_households():
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "PlatformAdmin"])
    rows = list(store.T["households"].values())
    status = request.args.get("status")
    primary = request.args.get("primary_member_id")
    if status:
        rows = [h for h in rows if h["status"] == status]
    if primary:
        rows = [h for h in rows if h["primary_member_id"] == primary]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_household(r) for r in rows], success)


@bp.get("/membership/households/<household_id>")
def get_household(household_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "PlatformAdmin"])
    return success(200, ser_household(_get_household(household_id)), "object")


@bp.post("/membership/households/<household_id>/dissolve")
def dissolve_household(household_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    h = _get_household(household_id)
    request.get_json(silent=True)

    if h["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409, "household not active")

    linked = [
        m for m in store.T["members"].values()
        if m["household_id"] == household_id and m["status"] in ("ACTIVE", "SUSPENDED")
    ]
    if linked:
        raise err("ERR_HOUSEHOLD_NOT_EMPTY", 422, "household not empty")

    h["status"] = "DISSOLVED"
    touch(h)
    return success(200, ser_household(h), "object")


# ---------------------------------------------------------------------------
# Survivor cases
# ---------------------------------------------------------------------------

@bp.get("/membership/members/<member_id>/survivor-cases")
def list_member_survivor_cases(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    rows = [s for s in store.T["survivor_cases"].values() if s["member_id"] == member_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_survivor(r) for r in rows], success)


@bp.get("/membership/survivor-cases")
def list_survivor_cases():
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    rows = list(store.T["survivor_cases"].values())
    member_id = request.args.get("member_id")
    ben = request.args.get("beneficiary_member_id")
    th = request.args.get("transfer_household_id")
    if member_id:
        rows = [s for s in rows if s["member_id"] == member_id]
    if ben:
        rows = [s for s in rows if s["beneficiary_member_id"] == ben]
    if th:
        rows = [s for s in rows if s["transfer_household_id"] == th]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_survivor(r) for r in rows], success)


@bp.get("/membership/survivor-cases/<case_id>")
def get_survivor_case(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "BenefitsOfficer", "PlatformAdmin"])
    return success(200, ser_survivor(_get_survivor(case_id)), "object")


@bp.post("/membership/survivor-cases/<case_id>/grant")
def grant_survivor_case(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["BenefitsOfficer"])
    sc = _get_survivor(case_id)
    request.get_json(silent=True)

    if sc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", 409, "survivor case not open")
    deceased = store.T["members"][sc["member_id"]]
    if deceased["status"] != "DECEASED":
        raise err("ERR_INVALID_STATE", 409, "deceased member not DECEASED")
    beneficiary = store.T["members"].get(sc["beneficiary_member_id"])
    if beneficiary is None:
        raise err("ERR_INVALID_REFERENCE", 422, "beneficiary does not resolve")
    if beneficiary["status"] != "ACTIVE":
        raise err("ERR_BENEFICIARY_NOT_ACTIVE", 422, "beneficiary not active")

    # survivor_continuance waterfall
    exposure = sum(
        e["exposure_cents"] for e in store.T["entitlements"].values()
        if e["member_id"] == deceased["id"] and e["status"] in ("OPEN", "GRANDFATHERED")
    )
    covered = max(0, exposure - SURVIVOR_DEDUCTIBLE_CENTS)
    spouse_line = beneficiary["claimed_relationship"] in ("SPOUSE", "WIDOW_WIDOWER")
    if spouse_line:
        rate_num, rate_den, months = 20, 100, SPOUSE_MONTHS
    else:
        rate_num, rate_den, months = 30, 100, CHILD_MONTHS
    amount = (covered * rate_num // rate_den) * months

    sc["continuance_months"] = months
    sc["continuance_amount_cents"] = amount

    # transfer cascade: grandfathered entitlements whose offering permits
    # beneficiary category re-key; others close with MEMBER_LOSS
    for e in store.T["entitlements"].values():
        if e["member_id"] != deceased["id"]:
            continue
        if e["status"] == "GRANDFATHERED":
            offering = store.T["product_offerings"].get(e["product_offering_id"])
            if (offering is not None
                    and beneficiary["eligibility_category"] in offering["allowed_categories"]):
                e["member_id"] = beneficiary["id"]
                touch(e)
                continue
        if e["status"] in ("OPEN", "GRANDFATHERED"):
            e["status"] = "CLOSED"
            e["closure_reason"] = "MEMBER_LOSS"
            touch(e)

    # household transfer
    old_ben_hh = beneficiary["household_id"]
    dec_hh = deceased["household_id"]
    if dec_hh is not None:
        beneficiary["household_id"] = dec_hh
        sc["transfer_household_id"] = dec_hh
        recompute_member_matrix(beneficiary)
        touch(beneficiary)
        if old_ben_hh and old_ben_hh != dec_hh:
            recompute_household(store.T["households"][old_ben_hh])
        recompute_household(store.T["households"][dec_hh])
    else:
        sc["transfer_household_id"] = None

    sc["status"] = "GRANTED"
    touch(sc)
    return success(200, ser_survivor(sc), "object")


@bp.post("/membership/survivor-cases/<case_id>/close")
def close_survivor_case(case_id):
    c = auth.ctx()
    auth.require_roles(c, ["BenefitsOfficer"])
    sc = _get_survivor(case_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    note = require_field(body, "resolution_note")

    if sc["status"] != "GRANTED":
        raise err("ERR_INVALID_STATE", 409, "survivor case not granted")

    sc["resolution_note"] = note
    sc["status"] = "CLOSED"
    touch(sc)
    return success(200, ser_survivor(sc), "object")
