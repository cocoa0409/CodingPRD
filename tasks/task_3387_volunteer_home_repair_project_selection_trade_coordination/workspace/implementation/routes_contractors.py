"""Licensed trade contractor registry and discipline (PRD 3.7)."""
from flask import Blueprint

from db import new_record
from helpers import (
    body, require_roles, ok_obj, get_or_404, req_str, req_int, opt_int,
    req_dt, raise_err, now_iso, CONTRACTOR_TRADES,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_CONTRACTOR_NOT_FOUND,
)
from logic import bump
from cascades import suspend_contractor, terminate_contractor
from serializers import ser_contractor

bp = Blueprint("contractors", __name__)

CONTRACTOR_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")


@bp.post("/rebuild/trade-contractors")
def create_contractor():
    require_roles("PlatformAdmin")
    b = body()
    trade = b.get("trade")
    if trade not in CONTRACTOR_TRADES:
        raise_err(E_INVALID_REQUEST, 400,
                  "trade must be one of " + ", ".join(CONTRACTOR_TRADES))
    max_jobs = opt_int(b, "max_concurrent_jobs", default=1, lo=1)
    rec = new_record("contractors", {
        "legal_name": req_str(b, "legal_name"),
        "trade": trade,
        "license_number": req_str(b, "license_number"),
        "license_expires_on": req_dt(b, "license_expires_on"),
        "insurance_expires_on": req_dt(b, "insurance_expires_on"),
        "max_concurrent_jobs": max_jobs,
        "status": "ACTIVE",
        "strike_count": 0,
    }, now_iso)
    return ok_obj(ser_contractor(rec), 201)


@bp.get("/rebuild/trade-contractors/<contractorId>")
def get_contractor(contractorId):
    require_roles("Any")
    rec = get_or_404("contractors", contractorId, E_CONTRACTOR_NOT_FOUND)
    return ok_obj(ser_contractor(rec))


@bp.patch("/rebuild/trade-contractors/<contractorId>")
def patch_contractor(contractorId):
    require_roles("PlatformAdmin")
    rec = get_or_404("contractors", contractorId, E_CONTRACTOR_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in CONTRACTOR_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(CONTRACTOR_STATUSES))
    if target == "SUSPENDED":
        if rec["status"] != "ACTIVE":
            raise_err(E_INVALID_STATE, 409,
                      "only an ACTIVE contractor can be suspended")
        suspend_contractor(rec)
    elif target == "ACTIVE":
        if rec["status"] != "SUSPENDED":
            raise_err(E_INVALID_STATE, 409,
                      "only a SUSPENDED contractor can be reinstated")
        rec["status"] = "ACTIVE"
        rec["strike_count"] = 0
        bump(rec)
    elif target == "TERMINATED":
        if rec["status"] not in ("ACTIVE", "SUSPENDED"):
            raise_err(E_INVALID_STATE, 409,
                      "only ACTIVE or SUSPENDED contractors can be "
                      "terminated")
        terminate_contractor(rec)
    return ok_obj(ser_contractor(rec))
