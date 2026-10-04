"""Teacher onboarding and teacher lifecycle endpoints."""

from flask import Blueprint, request

from core import auth, clock, constants as C, envelope, store
from core.errors import fail
from services import calc, cascades, views

from .common import api, resolve

bp = Blueprint("onboarding", __name__)

NON_TERMINAL = (
    "DRAFT",
    "SCREENING_PENDING",
    "SCREENING_FAILED",
    "SCREENING_PASSED",
    "SAMPLE_PENDING",
    "SAMPLE_REJECTED",
    "SAMPLE_APPROVED",
)


# ---------------------------------------------------------------------------
# TeacherApplication
# ---------------------------------------------------------------------------
@bp.post("/outschool/teacher-applications")
@api(["TeacherApplicant", "PlatformAdmin"])
def create_application(role, user_id):
    data = auth.body()
    minutes = data.get("teaching_sample_minutes")
    if minutes is not None and not auth.is_blank(minutes):
        if not isinstance(minutes, int) or isinstance(minutes, bool):
            fail("ERR_INVALID_ENUM_VALUE", "teaching_sample_minutes must be an integer")
        if minutes < C.SAMPLE_MIN_MINUTES:
            fail("ERR_SAMPLE_TOO_SHORT", "A teaching sample must be at least 5 minutes long")
    auth.require_fields(data, ["applicant_user_id", "applicant_email", "display_name"])
    app = store.make_record(
        "applications",
        applicant_user_id=data["applicant_user_id"],
        applicant_email=data["applicant_email"],
        display_name=data["display_name"],
        status="DRAFT",
        screening_outcome=None,
        screening_completed_period_index=None,
        teaching_sample_url=data.get("teaching_sample_url"),
        teaching_sample_minutes=minutes,
        reviewed_by_user_id=None,
        reviewer_bound_period_index=None,
        decision=None,
        decision_reason_code=None,
        revision_count=0,
    )
    return envelope.Result(201, views.application_out(app))


@bp.get("/outschool/teacher-applications/<application_id>")
@api(["TeacherApplicant", "TeacherReviewer", "PlatformAdmin"])
def get_application(role, user_id, application_id):
    app = resolve("applications", application_id, "TeacherApplication")
    return envelope.Result(200, views.application_out(app))


@bp.post("/outschool/teacher-applications/<application_id>/submit")
@api(["TeacherApplicant", "PlatformAdmin"])
def submit_application(role, user_id, application_id):
    app = resolve("applications", application_id, "TeacherApplication")
    if app["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT application may be submitted")
    data = auth.body()
    minutes = data.get("teaching_sample_minutes")
    if not auth.is_blank(minutes):
        if not isinstance(minutes, int) or isinstance(minutes, bool):
            fail("ERR_INVALID_ENUM_VALUE", "teaching_sample_minutes must be an integer")
        if minutes < C.SAMPLE_MIN_MINUTES:
            fail("ERR_SAMPLE_TOO_SHORT", "A teaching sample must be at least 5 minutes long")
    auth.require_fields(
        data, ["teaching_sample_url", "teaching_sample_minutes"]
    )
    for name in ("applicant_user_id", "applicant_email", "display_name"):
        if auth.is_blank(app.get(name)):
            fail("ERR_MISSING_REQUIRED_FIELD", "Field %r is required" % (name,))
    app["teaching_sample_url"] = data["teaching_sample_url"]
    app["teaching_sample_minutes"] = minutes
    outcome = C.SCREENING_OUTCOME_BY_APPLICATION.get(
        app["applicant_email"], C.SCREENING_OUTCOME_BY_APPLICATION["default"]
    )
    app["screening_outcome"] = outcome
    app["screening_completed_period_index"] = clock.period()
    app["reviewed_by_user_id"] = None
    app["reviewer_bound_period_index"] = None
    app["decision"] = None
    app["revision_count"] = 0
    app["status"] = "SCREENING_PASSED" if outcome == "PASS" else "SCREENING_FAILED"
    store.touch(app)
    return envelope.Result(200, views.application_out(app))


@bp.post("/outschool/teacher-applications/<application_id>/submit-sample")
@api(["TeacherApplicant", "PlatformAdmin"])
def submit_sample(role, user_id, application_id):
    app = resolve("applications", application_id, "TeacherApplication")
    if app["screening_outcome"] == "FAIL":
        fail("ERR_SCREENING_FAILED", "The background screening did not clear")
    if app["status"] not in ("SCREENING_PASSED", "SAMPLE_REJECTED"):
        fail("ERR_INVALID_STATE", "A sample may only be submitted from SCREENING_PASSED or SAMPLE_REJECTED")
    data = auth.body()
    minutes = data.get("teaching_sample_minutes")
    if not auth.is_blank(minutes):
        if not isinstance(minutes, int) or isinstance(minutes, bool):
            fail("ERR_INVALID_ENUM_VALUE", "teaching_sample_minutes must be an integer")
        if minutes < C.SAMPLE_MIN_MINUTES:
            fail("ERR_SAMPLE_TOO_SHORT", "A teaching sample must be at least 5 minutes long")
    if calc.screening_is_stale(app):
        fail("ERR_SCREENING_STALE", "The background screening is older than 365 periods")
    if app["revision_count"] >= C.APPLICATION_MAX_REVISIONS:
        fail("ERR_REVISION_LIMIT_REACHED", "The revision budget is exhausted")
    auth.require_fields(data, ["teaching_sample_url", "teaching_sample_minutes"])
    app["teaching_sample_url"] = data["teaching_sample_url"]
    app["teaching_sample_minutes"] = minutes
    app["status"] = "SAMPLE_PENDING"
    app["reviewed_by_user_id"] = None
    app["reviewer_bound_period_index"] = None
    app["decision"] = None
    store.touch(app)
    return envelope.Result(200, views.application_out(app))


@bp.post("/outschool/teacher-applications/<application_id>/review")
@api(["TeacherReviewer", "PlatformAdmin"])
def review_application(role, user_id, application_id):
    app = resolve("applications", application_id, "TeacherApplication")
    data = auth.body()
    if data.get("stage") is not None and data.get("stage") not in ("SCREENING", "SAMPLE"):
        fail("ERR_INVALID_ENUM_VALUE", "stage must be SCREENING or SAMPLE")
    if data.get("verdict") is not None and data.get("verdict") not in ("PASS", "FAIL"):
        fail("ERR_INVALID_ENUM_VALUE", "verdict must be PASS or FAIL")
    stage = data.get("stage")
    verdict = data.get("verdict")

    screening_reject = (
        stage == "SCREENING" and verdict == "FAIL" and app["status"] == "SCREENING_FAILED"
    )
    sample_review = stage == "SAMPLE" and app["status"] == "SAMPLE_PENDING"
    budget_reject = (
        verdict == "FAIL"
        and app["status"] in NON_TERMINAL
        and app["revision_count"] + 1 >= C.APPLICATION_MAX_REVISIONS
    )
    if not (screening_reject or sample_review or budget_reject):
        fail("ERR_INVALID_STATE", "No review transition is declared from status %s" % (app["status"],))

    if user_id == app["applicant_user_id"]:
        fail("ERR_REVIEWER_CONFLICT", "A reviewer may not decide their own application")
    if app["reviewed_by_user_id"] is not None and app["reviewed_by_user_id"] == user_id:
        fail("ERR_REVIEWER_CONFLICT", "This reviewer is already bound to the application")
    auth.require_fields(data, ["stage", "verdict"])

    app["reviewed_by_user_id"] = user_id
    app["reviewer_bound_period_index"] = clock.period()

    if stage == "SAMPLE" and verdict == "PASS":
        app["status"] = "SAMPLE_APPROVED"
        app["decision"] = "APPROVE"
    else:
        app["decision"] = "REJECT"
        if stage == "SAMPLE":
            app["decision_reason_code"] = "SAMPLE_QUALITY"
        elif stage == "SCREENING":
            app["decision_reason_code"] = "POLICY_VIOLATION"
        app["revision_count"] += 1
        if app["revision_count"] >= C.APPLICATION_MAX_REVISIONS:
            app["status"] = "REJECTED"
        else:
            app["status"] = "SAMPLE_REJECTED"
    store.touch(app)
    return envelope.Result(200, views.application_out(app))


@bp.post("/outschool/teacher-applications/<application_id>/approve")
@api(["TeacherReviewer", "PlatformAdmin"])
def approve_application(role, user_id, application_id):
    app = resolve("applications", application_id, "TeacherApplication")
    if app["status"] == "SAMPLE_APPROVED":
        if user_id == app["applicant_user_id"]:
            fail("ERR_REVIEWER_CONFLICT", "A reviewer may not approve their own application")
        if app["reviewed_by_user_id"] != user_id:
            fail("ERR_REVIEWER_CONFLICT", "Only the bound reviewer may give final approval")
        if calc.screening_is_stale(app):
            fail("ERR_SCREENING_STALE", "The background screening is older than 365 periods")
        if app["revision_count"] >= C.APPLICATION_MAX_REVISIONS:
            fail("ERR_REVISION_LIMIT_REACHED", "The revision budget is exhausted")
    else:
        if user_id == app["applicant_user_id"]:
            fail("ERR_REVIEWER_CONFLICT", "A reviewer may not approve their own application")
        fail("ERR_APPLICATION_NOT_APPROVED", "Final approval requires status SAMPLE_APPROVED")
    app["status"] = "APPROVED"
    store.touch(app)
    teacher = store.make_record(
        "teachers",
        application_id=app["id"],
        display_name=app["display_name"],
        status="PENDING_SETUP",
        screening_validity_period_index=(
            (app["screening_completed_period_index"] or 0) + C.SCREENING_VALIDITY_PERIODS
        ),
        suspension_reason=None,
        suspension_trigger=None,
        peak_actionable_risk_score=0,
    )
    return envelope.Result(201, views.teacher_out(teacher))


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------
@bp.get("/outschool/teachers/<teacher_id>")
@api(["Teacher", "TeacherReviewer", "PlatformAdmin"])
def get_teacher(role, user_id, teacher_id):
    teacher = resolve("teachers", teacher_id, "Teacher")
    return envelope.Result(200, views.teacher_out(teacher))


@bp.get("/outschool/teachers")
@api(["TeacherReviewer", "PlatformAdmin"])
def list_teachers(role, user_id):
    items = store.by_created(store.all_of("teachers"))
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    if application_id:
        items = [t for t in items if t["application_id"] == application_id]
    if status:
        items = [t for t in items if t["status"] == status]
    return envelope.paged([views.teacher_out(t) for t in items], request.args)


@bp.post("/outschool/teachers/<teacher_id>/activate")
@api(["PlatformAdmin"])
def activate_teacher(role, user_id, teacher_id):
    teacher = resolve("teachers", teacher_id, "Teacher")
    if teacher["status"] != "PENDING_SETUP":
        fail("ERR_INVALID_STATE", "Only a PENDING_SETUP teacher may be activated")
    if views.teacher_out(teacher)["payout_tax_document_status"] != "ON_FILE":
        fail("ERR_TAX_DOC_MISSING", "The teacher's tax document is not on file")
    teacher["status"] = "ACTIVE"
    teacher["suspension_reason"] = None
    teacher["suspension_trigger"] = None
    store.touch(teacher)
    return envelope.Result(200, views.teacher_out(teacher))


@bp.post("/outschool/teachers/<teacher_id>/suspend")
@api(["PlatformAdmin"])
def suspend_teacher(role, user_id, teacher_id):
    teacher = resolve("teachers", teacher_id, "Teacher")
    if teacher["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE teacher may be suspended")
    data = auth.body()
    auth.require_fields(data, ["reason"])
    teacher["status"] = "SUSPENDED"
    teacher["suspension_reason"] = data["reason"]
    teacher["suspension_trigger"] = "MANUAL"
    store.touch(teacher)
    cascades.suspension_cascade(teacher)
    return envelope.Result(200, views.teacher_out(teacher))


@bp.post("/outschool/teachers/<teacher_id>/reinstate")
@api(["PlatformAdmin"])
def reinstate_teacher(role, user_id, teacher_id):
    teacher = resolve("teachers", teacher_id, "Teacher")
    if teacher["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Only a SUSPENDED teacher may be reinstated")
    if views.teacher_out(teacher)["payout_tax_document_status"] != "ON_FILE":
        fail("ERR_TAX_DOC_MISSING", "The teacher's tax document is not on file")
    if teacher["peak_actionable_risk_score"] >= C.RISK_SUSPENSION_THRESHOLD:
        fail("ERR_INVALID_STATE", "Peak risk is still at or above the suspension threshold")
    teacher["status"] = "ACTIVE"
    teacher["suspension_reason"] = None
    teacher["suspension_trigger"] = None
    store.touch(teacher)
    return envelope.Result(200, views.teacher_out(teacher))


@bp.post("/outschool/teachers/<teacher_id>/terminate")
@api(["PlatformAdmin"])
def terminate_teacher(role, user_id, teacher_id):
    teacher = resolve("teachers", teacher_id, "Teacher")
    if teacher["status"] not in ("PENDING_SETUP", "ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE", "This teacher may not be terminated")
    for listing in store.all_of("listings"):
        if listing["teacher_id"] != teacher["id"]:
            continue
        if views.listing_out(listing)["section_count"] > 0:
            fail("ERR_INVALID_STATE", "A listing of this teacher still has live sections")
    teacher["status"] = "TERMINATED"
    store.touch(teacher)
    for listing in store.all_of("listings"):
        if listing["teacher_id"] != teacher["id"]:
            continue
        listing["lifecycle_state"] = "ARCHIVED"
        store.touch(listing)
        cascades.archive_listing_sections(listing)
    return envelope.Result(200, views.teacher_out(teacher))
