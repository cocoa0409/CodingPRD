"""ResourceCandidate routes."""

from flask import Blueprint, request

from calculations import FUEL_TYPES, RESOURCE_TYPES
from db import store
from errors import (
    ERR_CANDIDATE_NOT_FOUND, ERR_DUPLICATE_CANDIDATE_NAME,
    ERR_INVALID_REQUEST, raise_error,
)
from helpers import (
    body, get_int, get_num, get_str, paginate, parse_pagination,
    require_enum, require_fields, stamp_new,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import candidate_view, commitment_view, position_view

bp = Blueprint("candidates", __name__)

CANDIDATE_READ_ROLES = ("UtilityPlanner", "Commissioner", "Intervener", "PlatformAdmin")


def get_candidate_or_404(candidate_id: str) -> dict:
    c = store.candidates.get(candidate_id)
    if c is None:
        raise_error(ERR_CANDIDATE_NOT_FOUND, f"Candidate {candidate_id} not found")
    return c


@bp.route("/candidates", methods=["POST"])
@require_roles("UtilityPlanner")
def create_candidate(user_id, role):
    payload = body()
    require_fields(payload, "candidate_name", "resource_type", "nameplate_mw",
                   "online_year", "capex_usd_per_kw", "fixed_om_usd_per_kw_year",
                   "fuel_type", "build_lead_years")
    name = get_str(payload, "candidate_name")
    rtype = require_enum(payload, "resource_type", RESOURCE_TYPES)
    nameplate = get_num(payload, "nameplate_mw")
    if nameplate <= 0:
        raise_error(ERR_INVALID_REQUEST, "nameplate_mw must be > 0")
    online_year = get_int(payload, "online_year")
    if online_year < 2026:
        raise_error(ERR_INVALID_REQUEST, "online_year must be >= 2026")
    capex = get_num(payload, "capex_usd_per_kw")
    if capex <= 0:
        raise_error(ERR_INVALID_REQUEST, "capex_usd_per_kw must be > 0")
    fixed_om = get_num(payload, "fixed_om_usd_per_kw_year")
    if fixed_om < 0:
        raise_error(ERR_INVALID_REQUEST, "fixed_om_usd_per_kw_year must be >= 0")
    fuel_type = require_enum(payload, "fuel_type", FUEL_TYPES)
    if rtype in ("STORAGE", "DEMAND_RESPONSE") and fuel_type != "NONE":
        raise_error(ERR_INVALID_REQUEST,
                    "STORAGE and DEMAND_RESPONSE candidates must use fuel_type NONE")
    build_lead = get_int(payload, "build_lead_years")
    if build_lead < 1:
        raise_error(ERR_INVALID_REQUEST, "build_lead_years must be >= 1")
    for c in store.candidates.values():
        if c["candidate_name"] == name:
            raise_error(ERR_DUPLICATE_CANDIDATE_NAME,
                        "candidate_name already registered")
    store.candidate_seq += 1
    c = stamp_new({
        "candidate_name": name,
        "resource_type": rtype,
        "nameplate_mw": nameplate,
        "online_year": online_year,
        "capex_usd_per_kw": capex,
        "fixed_om_usd_per_kw_year": fixed_om,
        "fuel_type": fuel_type,
        "build_lead_years": build_lead,
        "global_sequence_index": store.candidate_seq,
    })
    store.candidates[c["id"]] = c
    return success_object(candidate_view(c), 201)


@bp.route("/candidates", methods=["GET"])
@require_roles(*CANDIDATE_READ_ROLES)
def list_candidates(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.candidates.values())
    if "resource_type" in request.args:
        items = [c for c in items if c["resource_type"] == request.args["resource_type"]]
    page, total = paginate(items, limit, offset)
    return success_list([candidate_view(c) for c in page], limit, offset, total)


@bp.route("/candidates/<candidateId>", methods=["GET"])
@require_roles(*CANDIDATE_READ_ROLES)
def get_candidate(user_id, role, candidateId):
    c = get_candidate_or_404(candidateId)
    return success_object(candidate_view(c), 200)


@bp.route("/candidates/<candidateId>/positions", methods=["GET"])
@require_roles(*CANDIDATE_READ_ROLES)
def list_candidate_positions(user_id, role, candidateId):
    c = get_candidate_or_404(candidateId)
    limit, offset = parse_pagination()
    items = [p for p in store.positions.values() if p["candidate_id"] == c["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([position_view(p) for p in page], limit, offset, total)


@bp.route("/candidates/<candidateId>/procurement-commitments", methods=["GET"])
@require_roles("UtilityPlanner", "Commissioner", "PlatformAdmin")
def list_candidate_commitments(user_id, role, candidateId):
    c = get_candidate_or_404(candidateId)
    limit, offset = parse_pagination()
    args = request.args
    items = [cm for cm in store.commitments.values() if cm["candidate_id"] == c["id"]]
    if "status" in args:
        items = [cm for cm in items if cm["status"] == args["status"]]
    if "plan_id" in args:
        items = [cm for cm in items if cm["plan_id"] == args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([commitment_view(cm) for cm in page], limit, offset, total)
