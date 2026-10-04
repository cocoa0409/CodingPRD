"""CertificationBodyAdmin endpoints: logical clock, standards, jurisdictions."""
from flask import Blueprint

import clock
import db
from constants import RECIPROCITY_GROUPS, ROLE_ADMIN
from errors import ApiError, ERR_STANDARD_EDITION_OVERLAP
from middleware import require_roles
from response import success
from services import calc, sweep
from validation import (
    body, opt_datetime, opt_str_list, req_bool, req_datetime, req_enum,
    req_list, req_number, req_str,
)
import validation as v

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles(ROLE_ADMIN)
def set_clock(user_id, role):
    payload = body(required=True)
    target = req_datetime(payload, "to_iso8601")
    clock.set_now(target)
    sweep.run_sweep()
    return success({"current_utc": clock.iso(target)})


def _validate_protocols(raw):
    protocols = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "test_protocols entries must be objects")
        protocols.append({
            "protocol_code": v.req_str(entry, "protocol_code"),
            "name": v.req_str(entry, "name"),
            "mandatory": v.req_bool(entry, "mandatory"),
            "safety_critical": v.req_bool(entry, "safety_critical"),
            "pass_threshold": v.req_number(entry, "pass_threshold"),
            "base_fee_cents": v.req_int(entry, "base_fee_cents"),
        })
    return protocols


@bp.post("/standards")
@require_roles(ROLE_ADMIN)
def create_standard(user_id, role):
    payload = body(required=True)
    category_code = req_str(payload, "category_code")
    standard_code = req_str(payload, "standard_code")
    edition_label = req_str(payload, "edition_label")
    effective_from = req_datetime(payload, "effective_from")
    effective_to = opt_datetime(payload, "effective_to")
    construction_requirements = [
        s for s in req_list(payload, "construction_requirements")
    ]
    for slot in construction_requirements:
        if not isinstance(slot, str):
            raise ApiError("ERR_INVALID_REQUEST",
                           "construction_requirements must contain only strings")
    test_protocols = _validate_protocols(req_list(payload, "test_protocols"))

    # Temporal rule: half-open effectiveness windows of the same
    # (category_code, standard_code) must never overlap; adjacency is legal.
    for existing in db.standards.values():
        if (existing["category_code"] == category_code
                and existing["standard_code"] == standard_code
                and calc.windows_overlap(
                    effective_from, effective_to,
                    existing["effective_from"], existing["effective_to"])):
            raise ApiError(ERR_STANDARD_EDITION_OVERLAP,
                           "effectiveness window overlaps an existing edition")

    standard = db.new_entity(db.standards, {
        "category_code": category_code,
        "standard_code": standard_code,
        "edition_label": edition_label,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "construction_requirements": construction_requirements,
        "test_protocols": test_protocols,
        "status": calc.standard_status_window(effective_from, effective_to),
    })
    return success(standard, status=201)


@bp.post("/jurisdictions")
@require_roles(ROLE_ADMIN)
def create_jurisdiction(user_id, role):
    payload = body(required=True)
    jurisdiction = db.new_entity(db.jurisdictions, {
        "jurisdiction_code": req_str(payload, "jurisdiction_code"),
        "name": req_str(payload, "name"),
        "accepts_field_labels": req_bool(payload, "accepts_field_labels"),
        "accepts_reciprocity": req_bool(payload, "accepts_reciprocity"),
        "reciprocity_sources": opt_str_list(payload, "reciprocity_sources", default=[]),
        "reciprocity_group": req_enum(payload, "reciprocity_group", RECIPROCITY_GROUPS)
            if payload.get("reciprocity_group") is not None else "NONE",
    })
    return success(jurisdiction, status=201)
