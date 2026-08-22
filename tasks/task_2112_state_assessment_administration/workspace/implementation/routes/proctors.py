"""Proctor roster and test-security training (PRD 3.1)."""

from flask import Blueprint, request

import serialize
from db import create, db, now, ordered, touch
from derive import certification_status, one_decimal, quiz_passes
from errors import api_error
from middleware import (
    ALL_ROLES,
    SCHOOL_COORDINATOR,
    body_reference,
    endpoint,
    json_body,
    require_scope,
    resolve,
)
from response import object_response, paginate
from validators import identifier_field, number_field, string_field

bp = Blueprint("proctors", __name__)


@bp.post("/proctors")
@endpoint(SCHOOL_COORDINATOR)
def create_proctor(actor):
    # Check 4 — a proctor may only be added to the acting school's own roster.
    school_id = body_reference("school_id")
    if school_id is not None:
        require_scope(school_id == actor.user_id)

    body = json_body()
    school_id = identifier_field(body, "school_id")
    full_name = string_field(body, "full_name", min_length=1, max_length=120)
    email = string_field(body, "email", min_length=1)
    if email.count("@") != 1:
        raise api_error("ERR_INVALID_REQUEST", "email must contain exactly one at-sign.")

    resolve(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")

    proctor = create(
        db.proctors,
        {
            "school_id": school_id,
            "full_name": full_name,
            "email": email,
            "training_status": "NOT_TRAINED",
            "quiz_score_pct": None,
            "training_completed_at": None,
            "revoked_at": None,
            "strike_count": 0,
            "latest_affidavit_id": None,
        },
    )
    return object_response(serialize.proctor(proctor), 201)


@bp.get("/proctors/<proctor_id>")
@endpoint(*ALL_ROLES)
def read_proctor(actor, proctor_id):
    proctor = resolve(db.proctors, proctor_id, "ERR_PROCTOR_NOT_FOUND")
    return object_response(serialize.proctor(proctor))


@bp.get("/proctors")
@endpoint(*ALL_ROLES)
def list_proctors(actor):
    school_id = request.args.get("school_id")
    standing = request.args.get("certification_status")
    items = [
        proctor
        for proctor in db.proctors.values()
        if (school_id is None or proctor["school_id"] == school_id)
        and (standing is None or certification_status(proctor) == standing)
    ]
    return paginate(ordered(items), serialize.proctor)


@bp.post("/proctors/<proctor_id>/training-completions")
@endpoint(SCHOOL_COORDINATOR)
def record_training_completion(actor, proctor_id):
    proctor = resolve(db.proctors, proctor_id, "ERR_PROCTOR_NOT_FOUND")
    require_scope(proctor["school_id"] == actor.user_id)

    body = json_body()
    string_field(body, "module_version", min_length=1)
    quiz_score_pct = number_field(body, "quiz_score_pct", minimum=0.0, maximum=100.0)

    score = one_decimal(quiz_score_pct)
    proctor["quiz_score_pct"] = score
    if quiz_passes(quiz_score_pct):
        proctor["training_status"] = "PASSED"
        proctor["training_completed_at"] = now()
    else:
        proctor["training_status"] = "FAILED"
    touch(proctor)
    return object_response(serialize.proctor(proctor))
