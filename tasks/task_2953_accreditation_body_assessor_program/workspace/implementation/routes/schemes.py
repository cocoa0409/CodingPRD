"""Accreditation programme rule development (PRD section 3.1)."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
import store
from auth import SCHEME_MANAGER, endpoint
from envelope import created, single
from errors import ApiError
from validators import (body, bool_field, decimal_field, enum_field, int_field,
                        string_field)

bp = Blueprint("schemes", __name__)

STANDARD_REFS = ("ISO_IEC_17025", "ISO_IEC_17020", "ISO_IEC_17021_1", "ISO_IEC_17065")
SCHEME_STATUSES = ("DRAFT", "UNDER_REVIEW", "PUBLISHED", "WITHDRAWN")
SCHEME_TRANSITIONS = {
    ("DRAFT", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "DRAFT"),
    ("UNDER_REVIEW", "PUBLISHED"),
    ("PUBLISHED", "UNDER_REVIEW"),
    ("PUBLISHED", "WITHDRAWN"),
}


@bp.post("/accreditation/schemes")
@endpoint([SCHEME_MANAGER])
def create_scheme(user_id, role):
    payload = body()
    program_code = string_field(payload, "program_code", 3, 32)
    name = string_field(payload, "name", 1, 160)
    standard_ref = enum_field(payload, "standard_ref", STANDARD_REFS)
    multiplier = decimal_field(payload, "complexity_multiplier", "1.0000", "2.0000", 4,
                               required=False, default=Decimal("1.0000"))
    witness_min_count = int_field(payload, "witness_min_count", 0, 10,
                                  required=False, default=1)
    points_required = decimal_field(payload, "qualification_points_required", "0", "100", 2,
                                    required=False, default=Decimal("60.00"))
    surveillance_interval_days = int_field(payload, "surveillance_interval_days", 30, 1095,
                                           required=False, default=365)
    reassessment_interval_days = int_field(payload, "reassessment_interval_days", 365, 2190,
                                           required=False, default=1460)
    critical_days = int_field(payload, "critical_nc_close_days", 1, 365,
                              required=False, default=30)
    major_days = int_field(payload, "major_nc_close_days", 1, 365, required=False, default=60)
    minor_days = int_field(payload, "minor_nc_close_days", 1, 365, required=False, default=90)
    unannounced_authority = bool_field(payload, "unannounced_authority",
                                       required=False, default=False)
    remote_assessment_allowed = bool_field(payload, "remote_assessment_allowed",
                                           required=False, default=True)

    for existing in store.rows("schemes"):
        if existing["program_code"] == program_code:
            raise ApiError("ERR_INVALID_REQUEST", "program_code must be unique")

    scheme = store.insert("schemes", {
        "program_code": program_code,
        "name": name,
        "standard_ref": standard_ref,
        "status": "DRAFT",
        "rule_revision": 1,
        "complexity_multiplier": calc.to_number(multiplier),
        "witness_min_count": witness_min_count,
        "qualification_points_required": calc.to_number(points_required),
        "surveillance_interval_days": surveillance_interval_days,
        "reassessment_interval_days": reassessment_interval_days,
        "critical_nc_close_days": critical_days,
        "major_nc_close_days": major_days,
        "minor_nc_close_days": minor_days,
        "unannounced_authority": unannounced_authority,
        "remote_assessment_allowed": remote_assessment_allowed,
        "revision_note": None,
        "published_at": None,
        "_complexity_multiplier": multiplier,
        "_points_required": points_required,
    })
    return created(store.public(scheme))


@bp.post("/accreditation/schemes/<scheme_id>/status")
@endpoint([SCHEME_MANAGER])
def change_scheme_status(user_id, role, scheme_id):
    payload = body()
    to_status = enum_field(payload, "to_status", SCHEME_STATUSES)
    revision_note = string_field(payload, "revision_note", 1, 500,
                                 required=(to_status == "DRAFT"))

    scheme = domain.find("schemes", scheme_id)
    if (scheme["status"], to_status) not in SCHEME_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "a %s programme cannot move to %s" % (scheme["status"], to_status))

    if to_status == "DRAFT":
        scheme["revision_note"] = revision_note
    elif to_status == "PUBLISHED":
        if scheme["published_at"] is not None:
            scheme["rule_revision"] = scheme["rule_revision"] + 1
        scheme["published_at"] = store.now_iso()
    scheme["status"] = to_status
    store.touch(scheme)
    return single(store.public(scheme))
