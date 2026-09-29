"""Vessel jobs: opening, cancellation, weld-map release, examination plan."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import calc, derive

bp = Blueprint("jobs", __name__)

VESSEL_TYPES = ("PRESSURE_VESSEL", "HEAT_EXCHANGER")
DESIGN_CODES = ("DIV1", "DIV2")

REQUIRED_COMPONENTS = {
    "PRESSURE_VESSEL": ["SHELL", "HEAD"],
    "HEAT_EXCHANGER": ["SHELL", "HEAD", "TUBESHEET"],
}
REQUIRED_TEST_SIDES = {
    "PRESSURE_VESSEL": ["SHELL_SIDE"],
    "HEAT_EXCHANGER": ["SHELL_SIDE", "TUBE_SIDE"],
}


@bp.post("/vessel-jobs")
@guard(["ShopAdmin"])
def create_job(ctx):
    body = validation.body()
    certificate_id = validation.string_field(body, "certificate_id")
    job_number = validation.string_field(body, "job_number")
    customer_name = validation.string_field(body, "customer_name")
    vessel_type = validation.enum_field(body, "vessel_type", VESSEL_TYPES)
    design_code = validation.enum_field(body, "design_code", DESIGN_CODES)
    mawp_psi = validation.decimal_field(body, "mawp_psi", exclusive_min=0, maximum=5000)
    design_temp_f = validation.decimal_field(body, "design_temp_f", exclusive_min=-60,
                                             maximum=1000)
    mdmt_f = validation.decimal_field(body, "mdmt_f", minimum=-155)
    inside_radius_in = validation.decimal_field(body, "inside_radius_in", exclusive_min=0)
    stress_ratio = validation.decimal_field(body, "stress_ratio", required=False, scale=2,
                                            minimum="0.50", maximum="1.00",
                                            default=Decimal("1.00"))
    pneumatic_justification = validation.string_field(body, "pneumatic_justification",
                                                      required=False, allow_blank=True)
    if mdmt_f >= design_temp_f:
        fail("ERR_INVALID_REQUEST", "Field 'mdmt_f' must be strictly less than 'design_temp_f'.")

    certificate = db.get("certificates", certificate_id)
    if certificate is None:
        fail("ERR_CERTIFICATE_NOT_FOUND", "No such certificate: %s." % certificate_id)
    if derive.certificate_expired(certificate):
        fail("ERR_CERTIFICATE_EXPIRED", "The governing certificate has passed its expires_on.")

    for job in db.all_of("jobs"):
        if job["job_number"] == job_number:
            fail("ERR_DUPLICATE_JOB_NUMBER", "Job number '%s' already exists." % job_number)

    record = db.insert("jobs", {
        "certificate_id": certificate_id,
        "job_number": job_number,
        "customer_name": customer_name,
        "vessel_type": vessel_type,
        "design_code": design_code,
        "mawp_psi": mawp_psi,
        "design_temp_f": design_temp_f,
        "mdmt_f": mdmt_f,
        "inside_radius_in": inside_radius_in,
        "stress_ratio": stress_ratio,
        "pneumatic_justification": pneumatic_justification,
        "status": "DRAFT",
        "required_components": list(REQUIRED_COMPONENTS[vessel_type]),
        "required_test_sides": list(REQUIRED_TEST_SIDES[vessel_type]),
        "governing_joint_efficiency": None,
        "nonconformance_open_count": 0,
        "weld_completion_pct": Decimal("0.00"),
        "design_release_at": None,
    })
    return common.created("jobs", record)


@bp.get("/vessel-jobs/<job_id>")
@guard(ALL_ROLES)
def get_job(ctx, job_id):
    return common.one("jobs", common.must_exist("jobs", job_id))


@bp.get("/vessel-jobs")
@guard(ALL_ROLES)
def list_jobs(ctx):
    return common.listing("jobs", ["certificate_id", "status", "vessel_type"])


@bp.post("/vessel-jobs/<job_id>/cancel")
@guard(["ShopAdmin"])
def cancel_job(ctx, job_id):
    body = validation.body()
    validation.string_field(body, "cancel_reason")

    job = common.must_exist("jobs", job_id)
    if job["status"] in ("STAMPED", "CANCELLED"):
        fail("ERR_INVALID_JOB_STATE", "A %s job cannot be cancelled." % job["status"])

    for sheet in derive.job_calculations(job_id):
        if sheet["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
            db.mutate(sheet, {"status": "SUPERSEDED"})

    heats_touched = []
    for part in derive.job_parts(job_id):
        if part["status"] == "ISSUED":
            db.mutate(part, {"status": "SCRAPPED", "scrap_reason": "JOB_CANCELLED"})
            if part["heat_id"] not in heats_touched:
                heats_touched.append(part["heat_id"])
    for heat_id in heats_touched:
        heat = db.get("heats", heat_id)
        if heat is not None:
            derive.sync_heat_ledger(heat)

    for batch in derive.job_batches(job_id):
        if batch["status"] in ("SCHEDULED", "IN_PROGRESS"):
            db.mutate(batch, {"status": "ABORTED"})
            for weld in derive.batch_welds(batch["id"]):
                db.mutate(weld, {"pwht_batch_id": None, "pwht_status": "PENDING"})

    for report in derive.job_nonconformances(job_id):
        if report["disposition"] in derive.OPEN_DISPOSITIONS:
            db.mutate(report, {"disposition": "CLOSED", "closed_at": db.now_iso()})

    for report in derive.job_reports(job_id):
        if report["status"] in ("ASSEMBLING", "READY_FOR_AI", "AI_SIGNED", "STAMP_HOLD"):
            db.mutate(report, {"status": "VOIDED"})

    derive.recompute_job(job, {"status": "CANCELLED"})
    return common.one("jobs", job)


@bp.post("/vessel-jobs/<job_id>/weld-map-release")
@guard(["WeldingEngineer"])
def release_weld_map(ctx, job_id):
    job = common.must_exist("jobs", job_id)
    if job["status"] != "FAB_PLANNING":
        fail("ERR_INVALID_JOB_STATE",
             "The weld map is released out of FAB_PLANNING, not %s." % job["status"])

    welds = derive.job_welds(job_id)
    if not welds:
        fail("ERR_EMPTY_WELD_MAP", "The job carries no planned joint.")

    for part in derive.job_parts(job_id):
        if part["status"] == "ISSUED" and not derive.part_traceability(part):
            fail("ERR_TRACEABILITY_INCOMPLETE",
                 "Part '%s' does not trace to accepted material." % part["part_mark"])

    for weld in welds:
        if weld["fab_status"] != "PLANNED":
            continue
        for key in ("part_a_id", "part_b_id"):
            part = db.get("parts", weld.get(key))
            if part is not None and part["status"] == "SCRAPPED":
                fail("ERR_PART_SCRAPPED",
                     "Joint '%s' references a scrapped piece." % weld["weld_number"])

    if derive.governing_joint_efficiency(job_id) == Decimal("1.00"):
        for weld in welds:
            if weld["joint_category"] == "A" and weld["joint_type"] != "BUTT":
                fail("ERR_JOINT_TYPE_NOT_PERMITTED",
                     "A full-efficiency design admits only BUTT joints on Category A seams.")

    for weld in welds:
        procedure = db.get("wps", weld["wps_id"])
        if procedure is None:
            continue
        if not (procedure["thickness_min_in"] <= weld["thickness_in"] <= procedure["thickness_max_in"]):
            fail("ERR_THICKNESS_OUTSIDE_WPS_RANGE",
                 "Joint '%s' lies outside its procedure's qualified window." % weld["weld_number"])

    for weld in welds:
        if weld.get("required_volumetric_pct") is None:
            fail("ERR_NDE_INCOMPLETE",
                 "Joint '%s' carries no resolved volumetric requirement." % weld["weld_number"])

    derive.recompute_job(job, {"status": "FABRICATION"})
    return common.one("jobs", job)


@bp.post("/vessel-jobs/<job_id>/nde-plan")
@guard(["QCInspector"])
def run_nde_plan(ctx, job_id):
    job = common.must_exist("jobs", job_id)
    if job["status"] not in ("FABRICATION", "NDE_HOLD"):
        fail("ERR_INVALID_JOB_STATE",
             "The examination plan runs while the job is FABRICATION or NDE_HOLD.")

    candidates = [w for w in derive.job_welds(job_id)
                  if w["fab_status"] == "WELDED" and w["nde_status"] == "NOT_PLANNED"]
    candidates.sort(key=lambda w: (w["weld_number"], w["created_at"], w["_seq"]))

    created = []
    selected_ids = set()

    for category in ("A", "B", "C", "D"):
        group = [w for w in candidates if w["joint_category"] == category]
        if not group:
            continue
        chosen = set()
        for requirement in sorted({w["required_volumetric_pct"] for w in group}, reverse=True):
            subgroup = [w for w in group if w["required_volumetric_pct"] == requirement]
            take = calc.selection_count(len(subgroup), requirement)
            for weld in subgroup[:take]:
                chosen.add(weld["id"])
        for weld in group:
            if weld["id"] not in chosen:
                continue
            created.append(_make_exam(weld, weld["volumetric_method"],
                                      weld["required_volumetric_pct"]))
            selected_ids.add(weld["id"])

    for weld in candidates:
        if weld["required_surface_method"] is None:
            continue
        created.append(_make_exam(weld, weld["required_surface_method"], 100))
        selected_ids.add(weld["id"])

    for weld in candidates:
        if weld["id"] in selected_ids:
            db.mutate(weld, {"nde_status": "PLANNED"})

    payload = [db.public(exam) for exam in created]
    return response.make({"meta": {"api_request_id": db.request_id(),
                                   "api_request_timestamp": db.now_iso()},
                          "response_type": "array",
                          "data": payload}, 201)


def _make_exam(weld, method, required_coverage_pct):
    return db.insert("exams", {
        "weld_id": weld["id"],
        "method": method,
        "exam_class": calc.EXAM_CLASS[method],
        "required_coverage_pct": required_coverage_pct,
        "examined_coverage_pct": None,
        "indications_count": None,
        "result": "PENDING",
        "examiner_personnel_id": None,
        "exam_date": None,
    })
