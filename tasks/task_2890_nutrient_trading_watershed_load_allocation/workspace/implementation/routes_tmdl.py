"""TMDL assessments, source assessments and allocation runs."""
from flask import Blueprint

from auth import ALL_ROLES, require
from calc import (
    included_sources,
    rescind_run,
    rows_where,
    run_allocation,
    set_program_status,
)
from common import collection_response, filtered, one, resolve, touched
from errors import ApiError
from store import (
    ZERO2,
    db,
    new_row,
    now_iso,
    parse_date,
    q2,
    q4,
    touch,
)
from validation import enum_arg, int_arg, spec, str_arg, validate_body

bp = Blueprint("tmdl", __name__)

ASSESSMENT_STATUSES = ("DRAFT", "PUBLIC_COMMENT", "REVISION", "APPROVED", "WITHDRAWN", "SUPERSEDED")
SOURCE_TYPES = ("POINT", "NONPOINT")
SOURCE_STATUSES = ("INVENTORIED", "ADJUSTED", "EXCLUDED")
RUN_METHODS = ("PRO_RATA_BY_EXISTING_LOAD", "CONTROLLABILITY_WEIGHTED")
RUN_STATUSES = ("ACTIVE", "SUPERSEDED", "RESCINDED")

ASSESSMENT_TRANSITIONS = {
    ("DRAFT", "PUBLIC_COMMENT"),
    ("PUBLIC_COMMENT", "REVISION"),
    ("REVISION", "PUBLIC_COMMENT"),
    ("PUBLIC_COMMENT", "APPROVED"),
    ("DRAFT", "WITHDRAWN"),
    ("PUBLIC_COMMENT", "WITHDRAWN"),
    ("REVISION", "WITHDRAWN"),
}


# --------------------------------------------------------------------------
# assessments
# --------------------------------------------------------------------------
@bp.route("/tmdl-assessments", methods=["POST"])
def create_assessment():
    require("TmdlAnalyst")
    body = validate_body(
        [
            spec("watershed_id", "id"),
            spec("assessment_code", "string"),
            spec("loading_capacity_lbs_yr", "number", minimum=0, min_exclusive=True, dp=2),
            spec("margin_of_safety_pct", "number", minimum=0, maximum="0.5", dp=4),
            spec("background_load_lbs_yr", "number", minimum=0, dp=2),
            spec("period_start_date", "date"),
            spec("period_end_date", "date"),
        ]
    )
    if parse_date(body["period_end_date"]) <= parse_date(body["period_start_date"]):
        raise ApiError("ERR_INVALID_REQUEST", "period_end_date must fall strictly after period_start_date.")

    watershed = resolve(db.watersheds, "watershed_id", body["watershed_id"])
    for existing in db.tmdl_assessments.values():
        if existing["watershed_id"] == watershed["id"] and existing["assessment_code"] == body["assessment_code"]:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = new_row(
        "TmdlAssessment",
        watershed_id=watershed["id"],
        assessment_code=body["assessment_code"],
        loading_capacity_lbs_yr=q2(body["loading_capacity_lbs_yr"]),
        margin_of_safety_pct=q4(body["margin_of_safety_pct"]),
        background_load_lbs_yr=q2(body["background_load_lbs_yr"]),
        period_start_date=body["period_start_date"],
        period_end_date=body["period_end_date"],
        status="DRAFT",
        revision_round=0,
        allocation_variant=None,
        effective_background_lbs_yr=None,
        margin_of_safety_lbs_yr=ZERO2,
        allocable_load_lbs_yr=ZERO2,
        wla_total_lbs_yr=ZERO2,
        la_total_lbs_yr=ZERO2,
        reserve_allocation_lbs_yr=ZERO2,
        approved_at=None,
    )
    db.tmdl_assessments[row["id"]] = row
    return one(row, 201)


@bp.route("/tmdl-assessments/<tmdl_assessment_id>", methods=["GET"])
def get_assessment(tmdl_assessment_id):
    require(*ALL_ROLES)
    return one(resolve(db.tmdl_assessments, "tmdl_assessment_id", tmdl_assessment_id))


@bp.route("/tmdl-assessments", methods=["GET"])
def list_assessments():
    require(*ALL_ROLES)
    filters = {
        "watershed_id": str_arg("watershed_id"),
        "status": enum_arg("status", ASSESSMENT_STATUSES),
    }
    return collection_response(filtered(db.tmdl_assessments, filters))


@bp.route("/tmdl-assessments/<tmdl_assessment_id>/status", methods=["POST"])
def assessment_status(tmdl_assessment_id):
    require("TmdlAnalyst", "ProgramAdministrator")
    assessment = resolve(db.tmdl_assessments, "tmdl_assessment_id", tmdl_assessment_id)
    body = validate_body(
        [
            spec("target_status", "enum", enum=ASSESSMENT_STATUSES),
            spec("reason", "string", required=False),
        ]
    )
    target = body["target_status"]
    current = assessment["status"]
    if (current, target) not in ASSESSMENT_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE")
    if current == "DRAFT" and target == "PUBLIC_COMMENT":
        if not included_sources(assessment["id"]):
            raise ApiError("ERR_INVALID_STATE")

    if target == "APPROVED":
        active = rows_where(db.allocation_runs, tmdl_assessment_id=assessment["id"], status="ACTIVE")
        if not active:
            raise ApiError("ERR_WLA_NOT_ALLOCATED")

    assessment["status"] = target
    if current == "PUBLIC_COMMENT" and target == "REVISION":
        assessment["revision_round"] = assessment["revision_round"] + 1
    if target == "APPROVED":
        assessment["approved_at"] = now_iso()
    touch(assessment, touched())

    if target == "APPROVED":
        for other in rows_where(db.tmdl_assessments, watershed_id=assessment["watershed_id"], status="APPROVED"):
            if other["id"] == assessment["id"]:
                continue
            other["status"] = "SUPERSEDED"
            touch(other, touched())
        watershed = db.watersheds.get(assessment["watershed_id"])
        if watershed is not None and watershed["program_status"] == "PROVISIONAL":
            set_program_status(watershed, "ACTIVE", touched())
    return one(assessment)


# --------------------------------------------------------------------------
# source assessments
# --------------------------------------------------------------------------
@bp.route("/source-assessments", methods=["POST"])
def create_source_assessment():
    require("TmdlAnalyst")
    body = validate_body(
        [
            spec("tmdl_assessment_id", "id"),
            spec("reach_id", "id"),
            spec("source_name", "string"),
            spec("source_type", "enum", enum=SOURCE_TYPES),
            spec("existing_load_lbs_yr", "number", minimum=0, dp=2),
            spec("controllability_index", "number", minimum=0, maximum=1, dp=4),
            spec("status", "enum", enum=SOURCE_STATUSES, required=False, default="INVENTORIED"),
        ]
    )
    assessment = resolve(db.tmdl_assessments, "tmdl_assessment_id", body["tmdl_assessment_id"])
    reach = resolve(db.reaches, "reach_id", body["reach_id"])
    if reach["watershed_id"] != assessment["watershed_id"]:
        raise ApiError("ERR_WATERSHED_MISMATCH")

    row = new_row(
        "SourceAssessment",
        tmdl_assessment_id=assessment["id"],
        reach_id=reach["id"],
        source_name=body["source_name"],
        source_type=body["source_type"],
        existing_load_lbs_yr=q2(body["existing_load_lbs_yr"]),
        controllability_index=q4(body["controllability_index"]),
        status=body["status"],
        allocated_load_lbs_yr=None,
        allocation_run_id=None,
    )
    db.source_assessments[row["id"]] = row
    return one(row, 201)


@bp.route("/source-assessments/<source_assessment_id>", methods=["GET"])
def get_source_assessment(source_assessment_id):
    require("ProgramAdministrator", "TmdlAnalyst", "PermitWriter", "Permittee", "RegistryAdministrator")
    return one(resolve(db.source_assessments, "source_assessment_id", source_assessment_id))


@bp.route("/source-assessments", methods=["GET"])
def list_source_assessments():
    require("ProgramAdministrator", "TmdlAnalyst", "PermitWriter", "Permittee", "RegistryAdministrator")
    filters = {
        "tmdl_assessment_id": str_arg("tmdl_assessment_id"),
        "reach_id": str_arg("reach_id"),
        "allocation_run_id": str_arg("allocation_run_id"),
        "source_type": enum_arg("source_type", SOURCE_TYPES),
        "status": enum_arg("status", SOURCE_STATUSES),
    }
    return collection_response(filtered(db.source_assessments, filters))


# --------------------------------------------------------------------------
# allocation runs
# --------------------------------------------------------------------------
@bp.route("/tmdl-assessments/<tmdl_assessment_id>/allocation-runs", methods=["POST"])
def create_allocation_run(tmdl_assessment_id):
    require("TmdlAnalyst")
    assessment = resolve(db.tmdl_assessments, "tmdl_assessment_id", tmdl_assessment_id)
    body = validate_body(
        [
            spec("run_label", "string"),
            spec("method", "enum", enum=RUN_METHODS),
            spec("expected_tmdl_assessment_version", "int"),
        ]
    )
    if body["expected_tmdl_assessment_version"] != assessment["version"]:
        raise ApiError("ERR_STALE_TMDL_VERSION")
    if not included_sources(assessment["id"]):
        raise ApiError("ERR_NO_INCLUDED_SOURCES")

    run = run_allocation(assessment, body["run_label"], body["method"], touched())
    return one(run, 201)


@bp.route("/allocation-runs/<allocation_run_id>/rescind", methods=["POST"])
def rescind_allocation_run(allocation_run_id):
    require("TmdlAnalyst", "ProgramAdministrator")
    run = resolve(db.allocation_runs, "allocation_run_id", allocation_run_id)
    validate_body([spec("reason", "string")])
    if run["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    source_ids = set(s["id"] for s in rows_where(db.source_assessments, allocation_run_id=run["id"]))
    for permit in db.permits.values():
        if permit["source_assessment_id"] in source_ids and permit["limit_status"] in ("INTERIM", "FINAL"):
            raise ApiError("ERR_ALLOCATION_RUN_IN_USE")

    rescind_run(run, touched())
    return one(run)


@bp.route("/allocation-runs/<allocation_run_id>", methods=["GET"])
def get_allocation_run(allocation_run_id):
    require("ProgramAdministrator", "TmdlAnalyst", "PermitWriter", "Permittee", "RegistryAdministrator")
    return one(resolve(db.allocation_runs, "allocation_run_id", allocation_run_id))


@bp.route("/allocation-runs", methods=["GET"])
def list_allocation_runs():
    require("ProgramAdministrator", "TmdlAnalyst", "PermitWriter", "Permittee", "RegistryAdministrator")
    filters = {
        "tmdl_assessment_id": str_arg("tmdl_assessment_id"),
        "status": enum_arg("status", RUN_STATUSES),
        "method": enum_arg("method", RUN_METHODS),
    }
    return collection_response(filtered(db.allocation_runs, filters))
