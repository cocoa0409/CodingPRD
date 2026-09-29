"""Baseline proposal, approval and rejection (section 3.4)."""

from decimal import Decimal

from flask import Blueprint, g

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, serialize

bp = Blueprint("baselines", __name__)

METHODS = ("HISTORICAL_DATA", "MODELED")

FILTERS = {
    "enrollment_id": ("enrollment_id", "str"),
    "status": ("status", "str"),
    "method": ("method", "str"),
}

READ_ROLES = (mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER)


@bp.route("/enrollments/<enrollment_id>/baselines", methods=["POST"])
def propose_baseline(enrollment_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    enrollment = common.get_enrollment(enrollment_id)
    body = v.json_body()
    method = v.v_enum(body, "method", METHODS)
    expected_version = v.v_int(body, "expected_enrollment_version")

    if expected_version != enrollment["version"]:
        common.fail("ERR_STALE_ENROLLMENT_VERSION")

    field = db.fields[enrollment["field_id"]]
    standard = db.practice_standards[enrollment["practice_standard_id"]]
    rows = calc.baseline_qualifying_rows(
        db.sorted_rows(db.practice_history),
        field["id"],
        enrollment["practice_code"],
        enrollment["start_crop_year"],
        standard["additionality_lookback_years"],
    )
    if len(set(r["crop_year"] for r in rows)) == 0:
        common.fail("ERR_INSUFFICIENT_PRACTICE_HISTORY")

    for other in db.sorted_rows(db.baselines):
        if (
            other["enrollment_id"] == enrollment["id"]
            and other["status"] == "PROPOSED"
            and other["method"] == method
        ):
            common.fail("ERR_DUPLICATE_BASELINE")

    figures = calc.baseline_figures(method, rows, field, standard)

    for other in db.sorted_rows(db.baselines):
        if other["enrollment_id"] == enrollment["id"] and other["status"] == "PROPOSED":
            other["status"] = "SUPERSEDED"
            db.touch(other)

    row = db.common_fields()
    row.update({
        "enrollment_id": enrollment["id"],
        "method": method,
        "qualifying_years": figures["qualifying_years"],
        "historical_mean_rate": figures["historical_mean_rate"],
        "baseline_emissions_t": figures["baseline_emissions_t"],
        "uncertainty_pct": figures["uncertainty_pct"],
        "status": "PROPOSED",
        "approved_by_admin_id": None,
        "rejection_note": None,
    })
    db.baselines[row["id"]] = row
    db.touch(enrollment)
    return resp.object_response(serialize.baseline(row), 201)


@bp.route("/baselines", methods=["GET"])
def list_baselines():
    mw.authorize(*READ_ROLES)
    rows = common.apply_filters(db.baselines.values(), FILTERS)
    return resp.paginate(rows, serialize.baseline)


@bp.route("/baselines/<baseline_id>", methods=["GET"])
def read_baseline(baseline_id):
    mw.authorize(*READ_ROLES)
    row = common.get_baseline(baseline_id)
    enrollment = db.enrollments.get(row["enrollment_id"])
    if enrollment is not None:
        mw.require_grower_owner(enrollment["grower_id"])
    return resp.object_response(serialize.baseline(row))


@bp.route("/baselines/<baseline_id>/approve", methods=["POST"])
def approve_baseline(baseline_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    baseline = common.get_baseline(baseline_id)
    v.json_body()
    enrollment = db.enrollments[baseline["enrollment_id"]]
    if baseline["status"] != "PROPOSED" or enrollment["status"] != "ACCEPTED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "A PROPOSED baseline on an ACCEPTED enrollment is required.",
        )
    if enrollment["screening_decision_admin_id"] is not None and (
        g.user_id == enrollment["screening_decision_admin_id"]
    ):
        common.fail("ERR_SEGREGATION_OF_DUTIES")

    baseline["status"] = "APPROVED"
    baseline["approved_by_admin_id"] = g.user_id
    db.touch(baseline)

    enrollment["status"] = "ACTIVE"
    enrollment["permanence_status"] = "IN_COMPLIANCE"
    enrollment["baseline_approval_admin_id"] = g.user_id
    db.touch(enrollment)

    field = db.fields.get(enrollment["field_id"])
    if field is not None and field["status"] == "MAPPED":
        field["status"] = "ENROLLED"
        db.touch(field)
        grower = db.growers.get(field["grower_id"])
        if grower is not None:
            grower["total_enrolled_acres"] = Decimal(grower["total_enrolled_acres"]) + Decimal(
                field["mapped_acres"]
            )
            db.touch(grower)

    return resp.object_response(serialize.baseline(baseline))


@bp.route("/baselines/<baseline_id>/reject", methods=["POST"])
def reject_baseline(baseline_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    baseline = common.get_baseline(baseline_id)
    body = v.json_body()
    rejection_note = v.v_str(body, "rejection_note")
    if baseline["status"] != "PROPOSED":
        common.fail(
            "ERR_INVALID_STATE_TRANSITION", "Only a PROPOSED baseline may be rejected."
        )
    baseline["status"] = "REJECTED"
    baseline["rejection_note"] = rejection_note
    db.touch(baseline)
    return resp.object_response(serialize.baseline(baseline))
