"""Territory endpoints -- the allocation ladder (PRD 2.6, 3.2, 3.3).

POST /franchise/territories, GET /franchise/territories[/{id}]
POST /franchise/territories/{id}/offer|award|request-expansion|withdraw-expansion|reallocate|reclaim
"""
from flask import Blueprint

import cascades
import derived
from auth import guard
from config import AGREEMENT_LIVE, HOUSEHOLD_CAP
from errors import ApiError
from fetch import get_agreement, get_franchisee, get_territory, paged
from response import created, ok
from store import common_fields, db, touch
from validate import (
    body,
    opt_bool,
    opt_id,
    opt_id_list,
    reject_unknown,
    req_int,
    req_id,
    req_str,
    req_str_list,
)

bp = Blueprint("territories", __name__)

CREATE_INPUT = [
    "territory_code", "brand_id", "household_count", "postal_codes",
    "expansion_right_households", "protected", "franchisee_id", "parent_territory_id",
]


def _started_territory(name):
    territory = get_territory(name)
    if territory.get("status") == "RECLAIMED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    return territory


def _require_status(territory, allowed):
    if territory.get("status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _require_postal_clear(territory):
    if derived.postal_overlap(territory.get("brand_id"),
                              territory.get("postal_codes"),
                              exclude_id=territory["id"]):
        raise ApiError("ERR_TERRITORY_POSTAL_OVERLAP")


@bp.post("/franchise/territories")
def create_territory():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    territory_code = req_str(b, "territory_code")
    if any(t.get("territory_code") == territory_code for t in db.territories.values()):
        raise ApiError("ERR_DUPLICATE_TERRITORY_CODE")

    brand_id = req_id(b, "brand_id")
    if db.brands.get(brand_id) is None:
        raise ApiError("ERR_BRAND_NOT_FOUND")
    household_count = req_int(b, "household_count", minimum=1)
    # An empty postal set is accepted: the reallocation carve-out requires
    # placeholder rows in DEFINED status whose postal_codes is still empty, and
    # this create endpoint is the only way those placeholders come into being.
    postal_codes = req_str_list(b, "postal_codes", min_items=0)
    expansion_right = req_int(b, "expansion_right_households", minimum=0)
    protected = opt_bool(b, "protected", default=True)

    # Body foreign keys resolve in the order the input list declares them.
    franchisee_id = opt_id(b, "franchisee_id")
    if franchisee_id is not None and db.franchisees.get(franchisee_id) is None:
        raise ApiError("ERR_FRANCHISEE_NOT_FOUND")
    parent_territory_id = opt_id(b, "parent_territory_id")
    if parent_territory_id is not None and db.territories.get(parent_territory_id) is None:
        raise ApiError("ERR_TERRITORY_NOT_FOUND")

    if derived.postal_overlap(brand_id, postal_codes):
        raise ApiError("ERR_TERRITORY_POSTAL_OVERLAP")

    record = common_fields()
    record.update({
        "_kind": "Territory",
        "territory_code": territory_code,
        "brand_id": brand_id,
        "franchisee_id": franchisee_id,
        "parent_territory_id": parent_territory_id,
        "source_of_reallocation_id": None,
        "household_count": household_count,
        "postal_codes": list(postal_codes),
        "protected": protected,
        "expansion_right_households": expansion_right,
        "allocated_households": 0,
        "status": "DEFINED",
    })
    db.territories[record["id"]] = record
    return created(record)


@bp.get("/franchise/territories/<territory_id>")
def read_territory(territory_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return ok(get_territory(territory_id))


@bp.get("/franchise/territories")
def list_territories():
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return paged(
        db.territories,
        "brand_id", "franchisee_id", "parent_territory_id",
        "source_of_reallocation_id", "status", "postal_code",
    )


@bp.post("/franchise/territories/<territory_id>/offer")
def offer_territory(territory_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["franchisee_id"])
    franchisee_id = req_id(b, "franchisee_id")
    territory = _started_territory(territory_id)
    # Existence precedes the state rung.
    get_franchisee(franchisee_id)
    _require_status(territory, ["DEFINED"])
    territory["franchisee_id"] = franchisee_id
    _require_postal_clear(territory)
    territory["status"] = "OFFERED"
    touch(territory)
    return ok(territory)


@bp.post("/franchise/territories/<territory_id>/award")
def award_territory(territory_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["expected_territory_version"])
    expected_version = req_int(b, "expected_territory_version", minimum=0)
    territory = _started_territory(territory_id)
    _require_status(territory, ["OFFERED"])
    if expected_version != territory.get("version"):
        raise ApiError("ERR_STALE_VERSION")
    if territory.get("franchisee_id") is None:
        raise ApiError("ERR_AGREEMENT_REQUIRED_FOR_AWARD")

    # Cross-entity linkage (rung 8): a matching agreement must already exist.
    match = [
        a for a in db.agreements.values()
        if a.get("franchisee_id") == territory.get("franchisee_id")
        and a.get("brand_id") == territory.get("brand_id")
        and a.get("territory_id") == territory["id"]
        and a.get("lifecycle_status") in ("OFFERED", "ACTIVE")
    ]
    if not match:
        raise ApiError("ERR_AGREEMENT_REQUIRED_FOR_AWARD")

    # Set constraint (rung 9), then the cap (rung 11).
    _require_postal_clear(territory)
    if derived.award_would_exceed_cap(territory.get("franchisee_id"), territory):
        raise ApiError("ERR_HOUSEHOLD_CAP_EXCEEDED")

    territory["status"] = "AWARDED"
    territory["allocated_households"] = int(territory.get("household_count") or 0)
    touch(territory)
    franchisee = db.franchisees.get(territory.get("franchisee_id"))
    cascades.recompute_franchisee(franchisee)
    return ok(territory)


@bp.post("/franchise/territories/<territory_id>/request-expansion")
def request_expansion(territory_id):
    uid, role = guard(["FranchiseeOperator"])
    territory = _started_territory(territory_id)
    if role == "FranchiseeOperator" and uid != territory.get("franchisee_id"):
        raise ApiError("ERR_UNAUTHORIZED")
    _require_status(territory, ["ACTIVE"])
    if not territory.get("protected"):
        raise ApiError("ERR_EXPANSION_THRESHOLD_NOT_MET")
    if int(territory.get("expansion_right_households") or 0) <= 0:
        raise ApiError("ERR_EXPANSION_THRESHOLD_NOT_MET")
    # The comparison is inclusive: exactly at the threshold qualifies.
    if int(territory.get("household_count") or 0) < int(territory.get("expansion_right_households") or 0):
        raise ApiError("ERR_EXPANSION_THRESHOLD_NOT_MET")
    territory["status"] = "EXPANSION_REQUESTED"
    touch(territory)
    franchisee = db.franchisees.get(territory.get("franchisee_id"))
    cascades.recompute_franchisee(franchisee)
    return ok(territory)


@bp.post("/franchise/territories/<territory_id>/withdraw-expansion")
def withdraw_expansion(territory_id):
    uid, role = guard(["FranchiseeOperator"])
    territory = _started_territory(territory_id)
    if role == "FranchiseeOperator" and uid != territory.get("franchisee_id"):
        raise ApiError("ERR_UNAUTHORIZED")
    _require_status(territory, ["EXPANSION_REQUESTED"])
    territory["status"] = "ACTIVE"
    touch(territory)
    franchisee = db.franchisees.get(territory.get("franchisee_id"))
    cascades.recompute_franchisee(franchisee)
    return ok(territory)


@bp.post("/franchise/territories/<territory_id>/reallocate")
def reallocate_territory(territory_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["target_territory_ids"])
    target_ids = req_str_list(b, "target_territory_ids", min_items=1)
    territory = _started_territory(territory_id)
    _require_status(territory, ["EXPANSION_REQUESTED"])
    if not territory.get("postal_codes"):
        raise ApiError("ERR_TARGET_TERRITORY_INVALID")
    if len(target_ids) > len(territory.get("postal_codes") or []):
        raise ApiError("ERR_TARGET_TERRITORY_INVALID")

    targets = []
    for target_id in target_ids:
        target = db.territories.get(target_id)
        if target is None:
            raise ApiError("ERR_TARGET_TERRITORY_INVALID")
        if target.get("brand_id") != territory.get("brand_id"):
            raise ApiError("ERR_TARGET_TERRITORY_INVALID")
        if target.get("status") != "DEFINED":
            raise ApiError("ERR_TARGET_TERRITORY_INVALID")
        if target.get("postal_codes"):
            raise ApiError("ERR_TARGET_TERRITORY_INVALID")
        targets.append(target)

    # Deterministic division: ascending territory_code order, each gets >= 1 code.
    targets.sort(key=lambda t: t.get("territory_code") or "")
    codes = sorted(territory.get("postal_codes") or [])
    per = len(codes) // len(targets)
    remainder = len(codes) % len(targets)
    cursor = 0
    for index, target in enumerate(targets):
        take = per + (1 if index < remainder else 0)
        chunk = codes[cursor:cursor + take]
        cursor += take
        target["postal_codes"] = chunk
        target["parent_territory_id"] = territory["id"]
        target["source_of_reallocation_id"] = territory["id"]
        derived.refresh_territory(target)
        touch(target)

    territory["postal_codes"] = []
    territory["status"] = "PENDING_REALLOCATION"
    touch(territory)
    return created({"reallocated_territory_ids": [t["id"] for t in targets]})


@bp.post("/franchise/territories/<territory_id>/reclaim")
def reclaim_territory(territory_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    territory = _started_territory(territory_id)
    _require_status(territory, ["PENDING_REALLOCATION"])
    prior_holder = territory.get("franchisee_id")
    territory["franchisee_id"] = None
    territory["status"] = "RECLAIMED"
    territory["allocated_households"] = 0
    touch(territory)

    for child in derived.children_of_territory(territory["id"]):
        child["franchisee_id"] = None
        child["status"] = "RECLAIMED"
        child["allocated_households"] = 0
        touch(child)

    if prior_holder:
        cascades.recompute_franchisee(db.franchisees.get(prior_holder))
    return ok(territory)