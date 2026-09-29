"""Examination interpretation, nonconformance reports and the repair loop."""

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from routes.welding import covering_nonconformance
from services import calc, derive

bp = Blueprint("exams", __name__)

REPAIR_LIMIT = 2


def chain_repair_generation(parent):
    """The generation the repair chain hanging off `parent` has reached.

    A repair joint keeps `repair_of_weld_id` pointing at the report's original
    joint, so the chain's depth lives in the generations of the joints already
    raised against it rather than in the original's own counter. PRD §3.7 counts
    the cycle `OPEN -> REPAIR -> OPEN` "once per generation, until
    `repair_generation` reaches the limit of 2", which is that depth.
    """
    reached = parent["repair_generation"]
    for weld in db.all_of("welds"):
        if weld["repair_of_weld_id"] == parent["id"]:
            reached = max(reached, weld["repair_generation"])
    return reached


def raise_nonconformance(job, weld, source):
    """Mint a nonconformance report; the caller recomputes the job afterwards."""
    sequence = len(derive.job_nonconformances(job["id"])) + 1
    severity = "MAJOR"
    if source == "NDE_REJECT":
        severity = "MAJOR" if weld["joint_category"] in ("A", "B") else "MINOR"
    return db.insert("nonconformances", {
        "job_id": job["id"],
        "weld_id": None if weld is None else weld["id"],
        "ncr_number": "NCR-%s-%03d" % (job["job_number"], sequence),
        "source": source,
        "severity": severity,
        "disposition": "OPEN",
        "disposition_notes": None,
        "ai_concurrence_personnel_id": None,
        "closed_at": None,
    })


# ---------------------------------------------------------------------------
# Examinations (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.get("/nde-exams/<exam_id>")
@guard(ALL_ROLES)
def get_exam(ctx, exam_id):
    return common.one("exams", common.must_exist("exams", exam_id))


@bp.get("/nde-exams")
@guard(ALL_ROLES)
def list_exams(ctx):
    return common.listing("exams", ["weld_id", "examiner_personnel_id", "method",
                                    "exam_class", "result"])


@bp.post("/nde-exams/<exam_id>/result")
@guard(["QCInspector"])
def record_result(ctx, exam_id):
    body = validation.body()
    result = validation.enum_field(body, "result", ("ACCEPT", "REJECT"))
    coverage = validation.decimal_field(body, "examined_coverage_pct", scale=2,
                                        minimum=0, maximum=100)
    indications = validation.int_field(body, "indications_count", minimum=0)
    exam_date = validation.date_field(body, "exam_date")
    if result == "REJECT" and indications < 1:
        fail("ERR_INVALID_REQUEST",
             "A REJECT needs at least one reportable indication.")

    exam = common.must_exist("exams", exam_id)
    if exam["result"] != "PENDING":
        fail("ERR_INVALID_EXAM_STATE", "This examination has already been interpreted.")
    weld = db.get("welds", exam["weld_id"])
    if weld["fab_status"] != "WELDED":
        fail("ERR_INVALID_EXAM_STATE", "The joint has not been welded yet.")
    if weld["welded_at"] is not None:
        if exam_date < calc.parse_date(weld["welded_at"][:10]):
            fail("ERR_INVALID_EXAM_STATE",
                 "The examination predates the deposition of the joint.")

    db.mutate(exam, {"result": result, "examined_coverage_pct": coverage,
                     "indications_count": indications,
                     "exam_date": db.iso_date(exam_date),
                     "examiner_personnel_id": ctx.user_id})
    job = db.get("jobs", weld["job_id"])

    if result == "ACCEPT":
        _cascade_accept(job, weld)
    else:
        _cascade_reject(job, weld)
    return common.one("exams", exam)


def _cascade_accept(job, weld):
    exams = derive.weld_exams(weld["id"])
    if all(e["result"] == "ACCEPT" for e in exams) and weld["nde_status"] == "PLANNED":
        db.mutate(weld, {"nde_status": "ACCEPTED"})
        # PRD 3.6: a parent joint is satisfied through its accepted repair.
        parent_id = weld["repair_of_weld_id"]
        if parent_id is not None and weld["fab_status"] == "WELDED":
            parent = db.get("welds", parent_id)
            if parent is not None and parent["nde_status"] == "REJECTED":
                db.mutate(parent, {"nde_status": "ACCEPTED"})
        derive.recompute_job(job)
        derive.sync_job_reports(job)


def _cascade_reject(job, weld):
    if weld["nde_status"] == "PLANNED":
        db.mutate(weld, {"nde_status": "REJECTED"})
    raise_nonconformance(job, weld, "NDE_REJECT")
    covering = covering_nonconformance(weld)
    if covering is not None and covering["disposition"] == "REPAIR":
        db.mutate(covering, {"disposition": "OPEN"})
    changes = {"status": "NDE_HOLD"} if job["status"] == "FABRICATION" else {}
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)


# ---------------------------------------------------------------------------
# Nonconformance reports (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.get("/nonconformances/<nonconformance_id>")
@guard(ALL_ROLES)
def get_nonconformance(ctx, nonconformance_id):
    return common.one("nonconformances",
                      common.must_exist("nonconformances", nonconformance_id))


@bp.get("/nonconformances")
@guard(ALL_ROLES)
def list_nonconformances(ctx):
    return common.listing("nonconformances", [
        "job_id", "weld_id", "ai_concurrence_personnel_id", "source", "severity",
        "disposition",
    ])


@bp.post("/nonconformances/<nonconformance_id>/disposition")
@guard(["QCInspector", "AuthorizedInspector"])
def disposition(ctx, nonconformance_id):
    body = validation.body()
    decision = validation.enum_field(body, "disposition", ("REPAIR", "USE_AS_IS"))
    notes = validation.string_field(body, "disposition_notes")

    ncr = common.must_exist("nonconformances", nonconformance_id)
    if ncr["disposition"] != "OPEN":
        fail("ERR_INVALID_NONCONFORMANCE_STATE",
             "Only an OPEN report may be dispositioned.")
    job = db.get("jobs", ncr["job_id"])
    if job["status"] != "NDE_HOLD":
        fail("ERR_INVALID_JOB_STATE", "Disposition needs the job in NDE_HOLD.")

    changes = {"disposition": decision, "disposition_notes": notes}
    if decision == "USE_AS_IS":
        if ctx.role != "AuthorizedInspector":
            fail("ERR_AI_CONCURRENCE_REQUIRED",
                 "A use-as-is disposition is the Authorized Inspector's call.")
        changes["ai_concurrence_personnel_id"] = ctx.user_id
    else:
        weld = db.get("welds", ncr["weld_id"])
        if weld is not None and chain_repair_generation(weld) >= REPAIR_LIMIT:
            fail("ERR_REPAIR_LIMIT_EXCEEDED",
                 "Joint %s has already been repaired twice." % weld["weld_number"])

    db.mutate(ncr, changes)
    derive.recompute_job(job)
    derive.sync_job_reports(job)
    return common.one("nonconformances", ncr)


@bp.post("/nonconformances/<nonconformance_id>/repair-welds")
@guard(["WeldingEngineer"])
def create_repair_weld(ctx, nonconformance_id):
    body = validation.body()
    weld_number = validation.string_field(body, "weld_number")
    wps_id = validation.string_field(body, "wps_id")

    ncr = common.must_exist("nonconformances", nonconformance_id)
    procedure = db.get("wps", wps_id)
    if procedure is None:
        fail("ERR_WPS_NOT_FOUND", "No procedure carries id %s." % wps_id)
    if ncr["disposition"] != "REPAIR":
        fail("ERR_INVALID_NONCONFORMANCE_STATE",
             "A repair joint needs the report dispositioned REPAIR.")
    job = db.get("jobs", ncr["job_id"])
    if job["status"] != "NDE_HOLD":
        fail("ERR_INVALID_JOB_STATE", "Repair welding needs the job in NDE_HOLD.")
    parent = db.get("welds", ncr["weld_id"])
    if parent is None:
        fail("ERR_INVALID_NONCONFORMANCE_STATE",
             "This report names no joint to repair.")
    if procedure["status"] != "QUALIFIED":
        fail("ERR_WPS_NOT_QUALIFIED",
             "Procedure %s is not QUALIFIED." % procedure["wps_number"])
    thickness = parent["thickness_in"]
    if (thickness < procedure["thickness_min_in"]
            or thickness > procedure["thickness_max_in"]):
        fail("ERR_THICKNESS_OUTSIDE_WPS_RANGE",
             "%s in falls outside the qualified window of %s."
             % (thickness, procedure["wps_number"]))
    for other in derive.job_welds(job["id"]):
        if other["weld_number"] == weld_number:
            fail("ERR_DUPLICATE_WELD_NUMBER",
                 "Joint %s is already on this weld map." % weld_number)
    reached = chain_repair_generation(parent)
    if reached >= REPAIR_LIMIT:
        fail("ERR_REPAIR_LIMIT_EXCEEDED",
             "Joint %s has already been repaired twice." % parent["weld_number"])

    record = db.insert("welds", {
        "job_id": job["id"],
        "weld_number": weld_number,
        "joint_category": parent["joint_category"],
        "joint_type": parent["joint_type"],
        "thickness_in": thickness,
        "wps_id": wps_id,
        "part_a_id": parent["part_a_id"],
        "part_b_id": parent["part_b_id"],
        "welder_qualification_id": None,
        "repair_of_weld_id": parent["id"],
        "repair_generation": reached + 1,
        "pwht_batch_id": None,
        "welded_at": None,
        "fab_status": "PLANNED",
        "nde_status": "NOT_PLANNED",
        "pwht_status": "PENDING" if procedure["pwht_required"] else "NOT_REQUIRED",
        "required_volumetric_pct": 0,
        "volumetric_method": None,
        "required_surface_method": None,
    })
    coverage, method, surface = derive.resolve_weld_examination(record, job)
    record["required_volumetric_pct"] = coverage
    record["volumetric_method"] = method
    record["required_surface_method"] = surface

    derive.recompute_job(job)
    derive.sync_job_reports(job)
    return common.created("welds", record)


@bp.post("/nonconformances/<nonconformance_id>/close")
@guard(["QCInspector"])
def close_nonconformance(ctx, nonconformance_id):
    ncr = common.must_exist("nonconformances", nonconformance_id)
    if ncr["disposition"] not in ("REPAIR", "USE_AS_IS"):
        fail("ERR_INVALID_NONCONFORMANCE_STATE",
             "Only a dispositioned report may be closed.")

    if ncr["disposition"] == "REPAIR":
        satisfied = False
        if ncr["weld_id"] is not None:
            for repair in derive.children("welds", "repair_of_weld_id", ncr["weld_id"]):
                if (repair["fab_status"] == "WELDED"
                        and repair["nde_status"] == "ACCEPTED"):
                    satisfied = True
        if not satisfied:
            fail("ERR_INVALID_NONCONFORMANCE_STATE",
                 "The repair joint has not been welded and accepted.")
    elif ncr["ai_concurrence_personnel_id"] is None:
        fail("ERR_AI_CONCURRENCE_REQUIRED",
             "The Authorized Inspector's concurrence is not on file.")

    db.mutate(ncr, {"disposition": "CLOSED", "closed_at": db.now_iso()})
    job = db.get("jobs", ncr["job_id"])
    changes = {}
    if (job["status"] == "NDE_HOLD"
            and derive.nonconformance_open_count(job["id"]) == 0):
        changes["status"] = "FABRICATION"
    derive.recompute_job(job, changes)
    derive.sync_job_reports(job)
    return common.one("nonconformances", ncr)
