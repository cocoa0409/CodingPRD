"""The manufacturer's data report: scoring, signature and the nameplate."""

from decimal import Decimal

from flask import Blueprint

import db
import validation
from errors import fail
from middleware import ALL_ROLES, guard
from routes import common
from services import derive

bp = Blueprint("reports", __name__)

FORM_TYPES = ("U-1A", "U-1", "U-2A")


@bp.post("/vessel-jobs/<job_id>/data-report")
@guard(["QCInspector", "AuthorizedInspector"])
def create_report(ctx, job_id):
    body = validation.body()
    expected_job_version = validation.int_field(body, "expected_job_version")
    form_type = validation.enum_field(body, "form_type", FORM_TYPES)

    job = common.must_exist("jobs", job_id)
    if expected_job_version != job["version"]:
        fail("ERR_STALE_JOB_VERSION",
             "The job has moved on since version %s." % expected_job_version)
    if job["status"] in ("STAMPED", "CANCELLED"):
        fail("ERR_INVALID_JOB_STATE",
             "A %s job admits no data package." % job["status"])
    if derive.nonconformance_open_count(job_id) > 0:
        fail("ERR_OPEN_NONCONFORMANCE",
             "The job still carries an open nonconformance.")
    for part in derive.job_parts(job_id):
        if not derive.part_traceability(part):
            fail("ERR_TRACEABILITY_INCOMPLETE",
                 "Piece %s has no complete mill test report." % part["part_mark"])

    sequence = len(derive.job_reports(job_id)) + 1
    record = db.insert("reports", {
        "job_id": job_id,
        "form_type": form_type,
        "mdr_number": "MDR-%s-%02d" % (job["job_number"], sequence),
        "section_scores": {},
        "completeness_score": Decimal("0.00"),
        "missing_items": [],
        "assembled_by_personnel_id": ctx.user_id,
        "ai_personnel_id": None,
        "ai_signed_at": None,
        "nameplate_serial": None,
        "nameplate_stamped_at": None,
        "status": "ASSEMBLING",
    })
    for prior in derive.job_reports(job_id):
        if prior["id"] == record["id"]:
            continue
        if prior["status"] in ("ASSEMBLING", "READY_FOR_AI"):
            db.mutate(prior, {"status": "VOIDED"})

    section_scores, completeness, missing_items = derive.report_derived(record)
    record["section_scores"] = section_scores
    record["completeness_score"] = completeness
    record["missing_items"] = missing_items

    # PRD 3.9: assembly always advances the job's version counter.
    if not derive.recompute_job(job):
        db.touch(job)
    return common.created("reports", record)


@bp.get("/data-reports/<report_id>")
@guard(ALL_ROLES)
def get_report(ctx, report_id):
    return common.one("reports", common.must_exist("reports", report_id))


@bp.get("/data-reports")
@guard(ALL_ROLES)
def list_reports(ctx):
    return common.listing("reports", ["job_id", "assembled_by_personnel_id",
                                      "ai_personnel_id", "form_type", "status"])


@bp.post("/data-reports/<report_id>/submit-to-ai")
@guard(["QCInspector", "AuthorizedInspector"])
def submit_report(ctx, report_id):
    report = common.must_exist("reports", report_id)
    if report["status"] != "ASSEMBLING":
        fail("ERR_INVALID_REPORT_STATE", "Only an ASSEMBLING package may be submitted.")
    job = db.get("jobs", report["job_id"])
    if job["status"] != "DATA_PACKAGE":
        fail("ERR_INVALID_JOB_STATE", "Submission needs the job in DATA_PACKAGE.")
    if derive.nonconformance_open_count(job["id"]) > 0:
        fail("ERR_OPEN_NONCONFORMANCE",
             "The job still carries an open nonconformance.")
    section_scores, completeness, missing_items = derive.report_derived(report)
    if completeness != Decimal("100.00"):
        fail("ERR_DATA_PACKAGE_INCOMPLETE",
             "The data package scores %s of 100.00." % completeness)

    db.mutate(report, {"status": "READY_FOR_AI", "section_scores": section_scores,
                       "completeness_score": completeness,
                       "missing_items": missing_items})
    return common.one("reports", report)


@bp.post("/data-reports/<report_id>/ai-sign")
@guard(["AuthorizedInspector"])
def sign_report(ctx, report_id):
    report = common.must_exist("reports", report_id)
    if report["status"] != "READY_FOR_AI":
        fail("ERR_INVALID_REPORT_STATE", "Only a READY_FOR_AI package may be signed.")
    if ctx.user_id == report["assembled_by_personnel_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The Inspector who assembled the package may not sign it.")
    job = db.get("jobs", report["job_id"])
    certificate = db.get("certificates", job["certificate_id"])
    if derive.certificate_expired(certificate):
        fail("ERR_CERTIFICATE_EXPIRED",
             "The Certificate of Authorization has expired.")
    if not derive.certificate_authorized(certificate):
        fail("ERR_STAMPING_NOT_AUTHORIZED",
             "The certificate no longer confers stamping authority.")

    db.mutate(report, {"status": "AI_SIGNED", "ai_personnel_id": ctx.user_id,
                       "ai_signed_at": db.now_iso()})
    return common.one("reports", report)


@bp.post("/data-reports/<report_id>/stamp-nameplate")
@guard(["ShopAdmin"])
def stamp_nameplate(ctx, report_id):
    body = validation.body()
    nameplate_serial = validation.string_field(body, "nameplate_serial")

    report = common.must_exist("reports", report_id)
    if report["status"] != "AI_SIGNED":
        fail("ERR_INVALID_REPORT_STATE",
             "Only an AI_SIGNED package may be stamped.")
    job = db.get("jobs", report["job_id"])
    certificate = db.get("certificates", job["certificate_id"])
    if derive.certificate_expired(certificate):
        fail("ERR_CERTIFICATE_EXPIRED",
             "The Certificate of Authorization has expired.")
    if not derive.certificate_authorized(certificate):
        fail("ERR_STAMPING_NOT_AUTHORIZED",
             "The certificate no longer confers stamping authority.")
    for other in db.all_of("reports"):
        if other["id"] != report_id and other["nameplate_serial"] == nameplate_serial:
            fail("ERR_DUPLICATE_NAMEPLATE_SERIAL",
                 "Nameplate serial %s is already recorded." % nameplate_serial)

    db.mutate(report, {"status": "STAMPED", "nameplate_serial": nameplate_serial,
                       "nameplate_stamped_at": db.now_iso()})
    changes = {"status": "STAMPED"} if job["status"] == "DATA_PACKAGE" else {}
    derive.recompute_job(job, changes)
    return common.one("reports", report)
