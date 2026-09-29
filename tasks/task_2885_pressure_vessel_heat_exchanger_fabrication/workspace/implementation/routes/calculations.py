"""Design calculation sheets: dual-variant wall sizing and independent review."""

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import calc, derive

bp = Blueprint("calculations", __name__)

COMPONENTS = ("SHELL", "HEAD", "TUBESHEET", "NOZZLE")
RT_EXTENTS = ("FULL", "SPOT", "NONE")


def _design_inputs(body):
    return (
        validation.enum_field(body, "rt_extent_declared", RT_EXTENTS),
        validation.decimal_field(body, "allowable_stress_psi", exclusive_min=0,
                                 maximum=30000),
        validation.decimal_field(body, "corrosion_allowance_in", scale=4, minimum=0,
                                 maximum="0.5000"),
        validation.decimal_field(body, "thickness_nominal_in", scale=4, exclusive_min=0),
    )


def _resolve(sheet, job):
    efficiency = calc.joint_efficiency(sheet["rt_extent_declared"])
    circumferential, longitudinal, required, governing = calc.wall_thickness(
        job["mawp_psi"], job["inside_radius_in"], sheet["allowable_stress_psi"],
        efficiency, sheet["corrosion_allowance_in"])
    return {
        "joint_efficiency": efficiency,
        "thickness_circumferential_in": circumferential,
        "thickness_longitudinal_in": longitudinal,
        "thickness_required_in": required,
        "governing_variant": governing,
    }


@bp.post("/vessel-jobs/<job_id>/design-calculations")
@guard(["DesignEngineer"])
def create_calculation(ctx, job_id):
    body = validation.body()
    expected_job_version = validation.int_field(body, "expected_job_version")
    component = validation.enum_field(body, "component", COMPONENTS)
    rt_extent, allowable_stress, corrosion_allowance, thickness_nominal = _design_inputs(body)

    job = common.must_exist("jobs", job_id)
    if expected_job_version != job["version"]:
        fail("ERR_STALE_JOB_VERSION",
             "The job has moved on since version %s." % expected_job_version)
    if job["status"] in ("STAMPED", "CANCELLED"):
        fail("ERR_INVALID_JOB_STATE",
             "A %s job admits no further design work." % job["status"])

    siblings = [s for s in derive.job_calculations(job_id) if s["component"] == component]
    revision = max([s["revision"] for s in siblings], default=0) + 1

    superseded = False
    for sheet in siblings:
        if sheet["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            db.mutate(sheet, {"status": "SUPERSEDED"})
            superseded = True

    record = db.insert("calculations", {
        "job_id": job_id,
        "component": component,
        "revision": revision,
        "rt_extent_declared": rt_extent,
        "joint_efficiency": None,
        "allowable_stress_psi": allowable_stress,
        "corrosion_allowance_in": corrosion_allowance,
        "thickness_nominal_in": thickness_nominal,
        "thickness_circumferential_in": None,
        "thickness_longitudinal_in": None,
        "thickness_required_in": None,
        "governing_variant": None,
        "status": "DRAFT",
        "prepared_by_personnel_id": ctx.user_id,
        "reviewed_by_personnel_id": None,
        "reject_reason": None,
    })
    record.update(_resolve(record, job))

    changes = {}
    if superseded and job["status"] == "DESIGN_REVIEW":
        changes["status"] = "DRAFT"
    elif superseded and job["status"] == "FAB_PLANNING":
        changes["status"] = "DRAFT"
        changes["design_release_at"] = None
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.created("calculations", record)


@bp.get("/design-calculations/<calculation_id>")
@guard(ALL_ROLES)
def get_calculation(ctx, calculation_id):
    return common.one("calculations", common.must_exist("calculations", calculation_id))


@bp.get("/design-calculations")
@guard(ALL_ROLES)
def list_calculations(ctx):
    return common.listing("calculations", ["job_id", "prepared_by_personnel_id",
                                           "reviewed_by_personnel_id", "component",
                                           "status"])


@bp.post("/design-calculations/<calculation_id>/submit")
@guard(["DesignEngineer"])
def submit_calculation(ctx, calculation_id):
    sheet = common.must_exist("calculations", calculation_id)
    if sheet["status"] != "DRAFT":
        fail("ERR_INVALID_CALCULATION_STATE", "Only a DRAFT sheet may be submitted.")
    job = db.get("jobs", sheet["job_id"])
    if job["status"] not in ("DRAFT", "DESIGN_REVIEW"):
        fail("ERR_INVALID_JOB_STATE",
             "Submission needs the job in DRAFT or DESIGN_REVIEW.")
    if sheet["thickness_nominal_in"] < sheet["thickness_required_in"]:
        fail("ERR_INSUFFICIENT_WALL_THICKNESS",
             "The nominal wall is thinner than the code demands.")

    db.mutate(sheet, {"status": "SUBMITTED"})
    changes = {"status": "DESIGN_REVIEW"} if job["status"] == "DRAFT" else {}
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.one("calculations", sheet)


@bp.post("/design-calculations/<calculation_id>/approve")
@guard(["DesignEngineer"])
def approve_calculation(ctx, calculation_id):
    sheet = common.must_exist("calculations", calculation_id)
    if sheet["status"] != "SUBMITTED":
        fail("ERR_INVALID_CALCULATION_STATE", "Only a SUBMITTED sheet may be approved.")
    if ctx.user_id == sheet["prepared_by_personnel_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer must differ from the preparer of the sheet.")

    db.mutate(sheet, {"status": "APPROVED", "reviewed_by_personnel_id": ctx.user_id})
    job = db.get("jobs", sheet["job_id"])

    changes = {}
    if job["status"] == "DESIGN_REVIEW" and _all_components_approved(job):
        changes["status"] = "FAB_PLANNING"
        changes["design_release_at"] = db.now_iso()
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.one("calculations", sheet)


def _all_components_approved(job):
    sheets = derive.job_calculations(job["id"])
    for component in job["required_components"]:
        approved = [s for s in sheets
                    if s["component"] == component and s["status"] == "APPROVED"]
        if len(approved) != 1:
            return False
    return True


@bp.post("/design-calculations/<calculation_id>/reject")
@guard(["DesignEngineer"])
def reject_calculation(ctx, calculation_id):
    body = validation.body()
    reject_reason = validation.string_field(body, "reject_reason")

    sheet = common.must_exist("calculations", calculation_id)
    if sheet["status"] != "SUBMITTED":
        fail("ERR_INVALID_CALCULATION_STATE", "Only a SUBMITTED sheet may be rejected.")
    if ctx.user_id == sheet["prepared_by_personnel_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The reviewer must differ from the preparer of the sheet.")

    db.mutate(sheet, {"status": "REJECTED", "reviewed_by_personnel_id": ctx.user_id,
                      "reject_reason": reject_reason})
    job = db.get("jobs", sheet["job_id"])
    changes = {"status": "DRAFT"} if job["status"] == "DESIGN_REVIEW" else {}
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.one("calculations", sheet)


@bp.post("/design-calculations/<calculation_id>/revise")
@guard(["DesignEngineer"])
def revise_calculation(ctx, calculation_id):
    body = validation.body()
    rt_extent, allowable_stress, corrosion_allowance, thickness_nominal = _design_inputs(body)

    sheet = common.must_exist("calculations", calculation_id)
    if sheet["status"] != "REJECTED":
        fail("ERR_INVALID_CALCULATION_STATE", "Only a REJECTED sheet may be revised.")
    job = db.get("jobs", sheet["job_id"])
    if job["status"] != "DRAFT":
        fail("ERR_INVALID_JOB_STATE", "Revision needs the job in DRAFT.")

    changes = {
        "status": "DRAFT",
        "revision": sheet["revision"] + 1,
        "rt_extent_declared": rt_extent,
        "allowable_stress_psi": allowable_stress,
        "corrosion_allowance_in": corrosion_allowance,
        "thickness_nominal_in": thickness_nominal,
        "reviewed_by_personnel_id": None,
        "reject_reason": None,
    }
    probe = dict(sheet)
    probe.update(changes)
    changes.update(_resolve(probe, job))
    db.mutate(sheet, changes)
    return common.one("calculations", sheet)
