"""Distributor and lead assignment routes."""
from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_CONTRACTOR_SUSPENDED,
    ERR_TIER_REQUIREMENT_NOT_MET, ERR_TERRITORY_OVERLAP, ERR_LEAD_POOL_EMPTY,
    ERR_OWNERSHIP_MISMATCH, not_found,
)
from middleware import require_roles
from response import success, list_response
from services.helpers import (
    body_json, require_fields, require_string, require_string_list,
    require_enum, require_nonneg_int, parse_date, stamp_common, touch,
    parse_pagination,
)
from services.calculations import TIER_RANK
from services.cascades import lazy_expire_certifications

bp = Blueprint("distribution", __name__)

TIERS = ("BRONZE", "SILVER", "GOLD")


@bp.post("/program/distributors")
def create_distributor():
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["name", "territory_codes", "lead_pool_total"])
    name = require_string(data, "name")
    territory_codes = require_string_list(data, "territory_codes")
    total = require_nonneg_int(data, "lead_pool_total")
    with db.lock:
        d = stamp_common({
            "name": name,
            "territory_codes": list(territory_codes),
            "lead_pool_total": total,
            "lead_pool_available": total,
        })
        db.distributors[d["id"]] = d
    return success(d, status=201)


def _get_distributor(did):
    d = db.distributors.get(did)
    if d is None:
        raise not_found("Distributor")
    return d


@bp.get("/program/distributors/<did>")
def get_distributor(did):
    require_roles("ProgramAdmin", "Distributor")
    with db.lock:
        d = _get_distributor(did)
    return success(d)


@bp.post("/program/lead-assignments")
def create_lead_assignment():
    user_id, role = require_roles("Distributor")
    data = body_json()
    require_fields(data, ["distributor_id", "contractor_id", "territory_code",
                          "required_tier", "start_date", "end_date"])
    distributor_id = require_string(data, "distributor_id")
    contractor_id = require_string(data, "contractor_id")
    territory_code = require_string(data, "territory_code")
    required_tier = require_enum(data, "required_tier", TIERS)
    start_date = require_string(data, "start_date")
    start_d = parse_date(start_date)
    end_date = require_string(data, "end_date")
    end_d = parse_date(end_date)
    if end_d <= start_d:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be after start_date")
    with db.lock:
        if distributor_id != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                           "Distributor may only assign from own pool")
        d = _get_distributor(distributor_id)
        contractor = db.contractors.get(contractor_id)
        if contractor is None:
            raise not_found("Contractor")
        if contractor["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACTOR_SUSPENDED, 409, "Contractor is not ACTIVE")
        # tier + territory eligibility
        lazy_expire_certifications(db)
        tier_ok = any(
            c["contractor_id"] == contractor["id"]
            and c["status"] == "ACTIVE"
            and TIER_RANK[c["tier"]] >= TIER_RANK[required_tier]
            for c in db.certifications.values()
        )
        territory_ok = (territory_code in d["territory_codes"]
                        and territory_code in contractor["territory_codes"])
        if not (territory_ok and tier_ok):
            raise ApiError(ERR_TIER_REQUIREMENT_NOT_MET, 422,
                           "Territory or tier requirement not met")
        # half-open overlap against existing ASSIGNED of same distributor + territory
        for la in db.lead_assignments.values():
            if la["distributor_id"] != d["id"]:
                continue
            if la["territory_code"] != territory_code:
                continue
            if la["status"] != "ASSIGNED":
                continue
            from datetime import date
            o_start = date.fromisoformat(la["start_date"])
            o_end = date.fromisoformat(la["end_date"])
            if start_d < o_end and o_start < end_d:
                raise ApiError(ERR_TERRITORY_OVERLAP, 409,
                               "Territory window overlaps an existing assignment")
        if d["lead_pool_available"] <= 0:
            raise ApiError(ERR_LEAD_POOL_EMPTY, 422, "Lead pool is empty")
        la = stamp_common({
            "distributor_id": distributor_id,
            "contractor_id": contractor_id,
            "territory_code": territory_code,
            "required_tier": required_tier,
            "start_date": start_date,
            "end_date": end_date,
            "status": "ASSIGNED",
        })
        db.lead_assignments[la["id"]] = la
        d["lead_pool_available"] = d["lead_pool_total"] - sum(
            1 for x in db.lead_assignments.values()
            if x["distributor_id"] == d["id"] and x["status"] == "ASSIGNED"
        )
    return success(la, status=201)


def _get_assignment(aid):
    la = db.lead_assignments.get(aid)
    if la is None:
        raise not_found("LeadAssignment")
    return la


@bp.post("/program/lead-assignments/<aid>/return")
def return_lead(aid):
    user_id, role = require_roles("Distributor")
    with db.lock:
        la = _get_assignment(aid)
        if la["distributor_id"] != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                           "Distributor may only return own assignments")
        if la["status"] != "ASSIGNED":
            raise ApiError(ERR_INVALID_STATE, 409, "Lead assignment is not ASSIGNED")
        la["status"] = "RETURNED"
        touch(la)
        d = db.distributors.get(la["distributor_id"])
        if d is not None:
            d["lead_pool_available"] = d["lead_pool_total"] - sum(
                1 for x in db.lead_assignments.values()
                if x["distributor_id"] == d["id"] and x["status"] == "ASSIGNED"
            )
    return success(la)


@bp.get("/program/lead-assignments")
def list_lead_assignments():
    require_roles("ProgramAdmin", "Distributor")
    limit, offset = parse_pagination()
    distributor_id = request.args.get("distributor_id")
    contractor_id = request.args.get("contractor_id")
    status = request.args.get("status")
    if status is not None and status not in ("ASSIGNED", "RETURNED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid status filter")
    with db.lock:
        rows = list(db.lead_assignments.values())
        if distributor_id is not None:
            rows = [r for r in rows if r["distributor_id"] == distributor_id]
        if contractor_id is not None:
            rows = [r for r in rows if r["contractor_id"] == contractor_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        rows.sort(key=lambda x: x["created_at"])
        total = len(rows)
        page = rows[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.get("/program/lead-assignments/<aid>")
def get_lead_assignment(aid):
    require_roles("ProgramAdmin", "Distributor")
    with db.lock:
        la = _get_assignment(aid)
    return success(la)
