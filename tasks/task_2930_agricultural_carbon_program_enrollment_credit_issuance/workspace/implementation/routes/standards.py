"""Published methodologies (PracticeStandard)."""

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from routes.fields import PRACTICE_CODES
from services import common, serialize

bp = Blueprint("standards", __name__)

FILTERS = {
    "practice_code": ("practice_code", "str"),
    "status": ("status", "str"),
    "standard_version": ("standard_version", "int"),
    "version": ("standard_version", "int"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER, mw.ROLE_REGISTRY_OFFICER)


@bp.route("/practice-standards", methods=["POST"])
def create_standard():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    body = v.json_body()
    practice_code = v.v_enum(body, "practice_code", PRACTICE_CODES)
    standard_version = v.v_int(body, "standard_version", minimum=1)
    lookback = v.v_int(body, "additionality_lookback_years", minimum=3, maximum=10)
    max_prior = v.v_dec(body, "max_prior_adoption_pct", 2, minimum=0, maximum=100)
    min_documented = v.v_int(body, "min_documented_years", minimum=1)
    min_adoption = v.v_int(body, "min_adoption_years", minimum=1)
    uncertainty_base = v.v_dec(body, "uncertainty_base_pct", 2, minimum=0, maximum=100)
    sequestration = v.v_dec(body, "sequestration_rate_per_acre", 4, minimum=0, exclusive_min=True)
    modeled_rate = v.v_dec(body, "modeled_baseline_rate_per_acre", 4, minimum=0, exclusive_min=True)
    buffer_base = v.v_dec(body, "buffer_base_pct", 2, minimum=0, maximum=25)
    telemetry_required = v.v_bool(body, "telemetry_required", required=False, default=False)
    effective_from = v.v_date(body, "effective_from")

    for other in db.practice_standards.values():
        if other["practice_code"] == practice_code and other["standard_version"] == standard_version:
            common.fail("ERR_DUPLICATE_STANDARD_VERSION")

    row = db.common_fields()
    row.update({
        "practice_code": practice_code,
        "standard_version": standard_version,
        "additionality_lookback_years": lookback,
        "max_prior_adoption_pct": max_prior,
        "min_documented_years": min_documented,
        "min_adoption_years": min_adoption,
        "uncertainty_base_pct": uncertainty_base,
        "sequestration_rate_per_acre": sequestration,
        "modeled_baseline_rate_per_acre": modeled_rate,
        "buffer_base_pct": buffer_base,
        "telemetry_required": telemetry_required,
        "effective_from": effective_from,
        "status": "ACTIVE",
        "revision_note": None,
    })
    db.practice_standards[row["id"]] = row
    return resp.object_response(serialize.practice_standard(row), 201)


@bp.route("/practice-standards", methods=["GET"])
def list_standards():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.practice_standards.values(), FILTERS)
    return resp.paginate(rows, serialize.practice_standard)


@bp.route("/practice-standards/<practice_standard_id>", methods=["GET"])
def read_standard(practice_standard_id):
    mw.authorize(*READ_ROLES)
    row = common.get_practice_standard(practice_standard_id)
    return resp.object_response(serialize.practice_standard(row))


@bp.route("/practice-standards/<practice_standard_id>/retire", methods=["POST"])
def retire_standard(practice_standard_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    row = common.get_practice_standard(practice_standard_id)
    v.json_body()
    if row["status"] != "ACTIVE":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE standard may be retired.")
    row["status"] = "RETIRED"
    db.touch(row)
    return resp.object_response(serialize.practice_standard(row))


@bp.route("/practice-standards/<practice_standard_id>/revise", methods=["POST"])
def revise_standard(practice_standard_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    row = common.get_practice_standard(practice_standard_id)
    body = v.json_body()
    revision_note = v.v_str(body, "revision_note")
    if row["status"] != "ACTIVE":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE standard may be revised.")
    row["standard_version"] = row["standard_version"] + 1
    row["revision_note"] = revision_note
    db.touch(row)
    return resp.object_response(serialize.practice_standard(row))
