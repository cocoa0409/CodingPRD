"""Peer reviewer registry: register, directory, read, PATCH + re-screen (§3.5)."""
from flask import Blueprint, request

import constants as C
from auth import authenticate, require_role
from db import STORE
from errors import ERR_REVIEWER_NOT_FOUND, ERR_VALIDATION, raise_err
from helpers import (fetch_or_404, get_body, new_entity, opt_bool, opt_int,
                     opt_list, opt_number, opt_string, paginate, req_enum_list,
                     req_number, req_string, req_string_list, serialize, touch)
from response import success_list, success_object

bp = Blueprint("reviewers", __name__)


def _round_rating(value):
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@bp.post("/accreditation/reviewers")
def create_reviewer():
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    body = get_body()
    full_name = req_string(body, "full_name")
    specialty = req_enum_list(body, "specialty_criteria", C.CRITERION_CODES)
    quality = _round_rating(req_number(body, "quality_rating", minimum=0, maximum=5))
    affiliation = None
    if "affiliation_institution_id" in body and body["affiliation_institution_id"] is not None:
        affiliation = req_string(body, "affiliation_institution_id")
    declared = []
    if "declared_conflict_institution_ids" in body and body["declared_conflict_institution_ids"] is not None:
        declared = req_string_list(body, "declared_conflict_institution_ids")
    prior = opt_int(body, "prior_chair_count", minimum=0)
    active = opt_bool(body, "is_active")
    reviewer = new_entity({
        "full_name": full_name,
        "affiliation_institution_id": affiliation,
        "specialty_criteria": list(specialty),
        "declared_conflict_institution_ids": list(declared),
        "quality_rating": quality,
        "prior_chair_count": prior if prior is not None else 0,
        "is_active": active if active is not None else True,
    })
    STORE.reviewers[reviewer["id"]] = reviewer
    return success_object(_ser_reviewer(reviewer), code=201)


def _ser_reviewer(reviewer):
    from helpers import reviewer_assignment_count
    data = serialize(reviewer)
    data["current_assignment_count"] = reviewer_assignment_count(reviewer["id"])
    return data


@bp.get("/accreditation/reviewers")
def list_reviewers():
    authenticate()
    items = list(STORE.reviewers.values())
    affiliation = request.args.get("affiliation_institution_id")
    if affiliation is not None:
        items = [r for r in items if r["affiliation_institution_id"] == affiliation]
    specialty = request.args.get("specialty")
    if specialty is not None:
        items = [r for r in items if specialty in r["specialty_criteria"]]
    active = request.args.get("is_active")
    if active is not None:
        lowered = active.lower()
        if lowered not in ("true", "false"):
            raise_err(ERR_VALIDATION, "is_active must be 'true' or 'false'")
        flag = lowered == "true"
        items = [r for r in items if r["is_active"] == flag]
    from helpers import parse_pagination
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = [_ser_reviewer(r) for r in ordered[offset:offset + limit]]
    return success_list(page, total, limit, offset)


@bp.get("/accreditation/reviewers/<reviewer_id>")
def get_reviewer(reviewer_id):
    authenticate()
    reviewer = fetch_or_404(STORE.reviewers, reviewer_id, ERR_REVIEWER_NOT_FOUND)
    return success_object(_ser_reviewer(reviewer))


@bp.get("/accreditation/reviewers/<reviewer_id>/assignments")
def list_reviewer_assignments(reviewer_id):
    authenticate()
    fetch_or_404(STORE.reviewers, reviewer_id, ERR_REVIEWER_NOT_FOUND)
    items = [a for a in STORE.team_assignments.values() if a["reviewer_id"] == reviewer_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.patch("/accreditation/reviewers/<reviewer_id>")
def patch_reviewer(reviewer_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    reviewer = fetch_or_404(STORE.reviewers, reviewer_id, ERR_REVIEWER_NOT_FOUND)
    body = get_body()
    if "affiliation_institution_id" in body:
        value = body["affiliation_institution_id"]
        if value is not None and not isinstance(value, str):
            raise_err(ERR_VALIDATION, "affiliation_institution_id must be a string or null")
        reviewer["affiliation_institution_id"] = value
    if "specialty_criteria" in body and body["specialty_criteria"] is not None:
        reviewer["specialty_criteria"] = list(req_enum_list(body, "specialty_criteria", C.CRITERION_CODES))
    if "declared_conflict_institution_ids" in body and body["declared_conflict_institution_ids"] is not None:
        reviewer["declared_conflict_institution_ids"] = list(req_string_list(body, "declared_conflict_institution_ids"))
    if "quality_rating" in body and body["quality_rating"] is not None:
        reviewer["quality_rating"] = _round_rating(req_number(body, "quality_rating", minimum=0, maximum=5))
    prior = opt_int(body, "prior_chair_count", minimum=0)
    if prior is not None:
        reviewer["prior_chair_count"] = prior
    active = opt_bool(body, "is_active")
    if active is not None:
        reviewer["is_active"] = active
    touch(reviewer)
    # Continuous conflict screening (§2.10/§3.5): re-screen ACTIVE assignments.
    for a in STORE.team_assignments.values():
        if a["reviewer_id"] != reviewer_id or a["status"] != "ACTIVE":
            continue
        team = STORE.review_teams.get(a["review_team_id"])
        if team is None or team["status"] == "DISBANDED":
            continue
        cycle = STORE.review_cycles.get(team["review_cycle_id"])
        if cycle is None:
            continue
        inst_id = cycle["institution_id"]
        conflicted = (reviewer["affiliation_institution_id"] is not None
                      and reviewer["affiliation_institution_id"] == inst_id) \
            or inst_id in (reviewer["declared_conflict_institution_ids"] or [])
        if conflicted and a["conflict_status"] == "CLEARED":
            a["conflict_status"] = "CONFLICTED"
            touch(a)
    return success_object(_ser_reviewer(reviewer))
