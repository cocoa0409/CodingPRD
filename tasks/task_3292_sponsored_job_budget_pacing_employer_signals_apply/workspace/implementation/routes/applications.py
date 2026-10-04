"""Application endpoints: apply-flow start, completion, close, disposition."""

from flask import Blueprint

import auth
import validations as V
from db import iso, store
from models import application_view, apply_event_view, create, touch
from response import array, ok, page_meta, paginate
from services import calc, events
from routes.assessments import score_answers

bp = Blueprint("applications", __name__)

APPLICATION_STATUSES = ("STARTED", "COMPLETED", "RESPONDED", "CLOSED")
DISPOSITIONS = ("NONE", "REVIEWED", "INTERVIEW", "REJECTED", "HIRED")
RESPONDING = ("REVIEWED", "INTERVIEW", "REJECTED", "HIRED")


def application_employer_id(application):
    posting = store.job_postings.get(application["job_posting_id"])
    if posting is None:
        return None
    return posting["employer_id"]


def load_application(actor_id, role, application_id):
    application = V.get("application", application_id)
    if role == "Employer":
        auth.require_ownership(actor_id, role, "application", "Employer",
                               application_employer_id(application))
    elif role == "JobSeeker":
        auth.require_ownership(actor_id, role, "application", "JobSeeker",
                               application["job_seeker_id"])
    return application


def attached_assessment(posting_id):
    assessments = [
        assessment for assessment in store.assessments.values()
        if assessment["job_posting_id"] == posting_id
        and assessment["status"] == "PUBLISHED"
    ]
    if not assessments:
        return None
    assessments.sort(key=lambda row: (row["created_at"], row["id"]))
    return assessments[-1]


@bp.post("/applications")
def start_application():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("JobSeeker", "PlatformAdmin"))
    data = V.body()
    V.require_fields(data, ["job_posting_id", "job_seeker_id"])
    posting_id = V.require_string(data, "job_posting_id")
    seeker_id = V.require_string(data, "job_seeker_id")
    assessment_id = V.optional_string(data, "assessment_id")
    answers = data.get("assessment_answers")

    posting = V.get("job_posting", posting_id)
    seeker = V.get("job_seeker", seeker_id)
    if role == "JobSeeker":
        auth.require_ownership(actor_id, role, "application", "JobSeeker", seeker["id"])

    assessment = None
    if assessment_id is not None:
        assessment = V.get("assessment", assessment_id)
        if assessment["job_posting_id"] != posting["id"]:
            from errors import ERR_ASSESSMENT_NOT_FOUND, fail
            fail(ERR_ASSESSMENT_NOT_FOUND,
                 "That assessment is not attached to this posting.")

    score = None
    if assessment is not None:
        score = score_answers(assessment, answers)

    application = create(
        "applications",
        job_posting_id=posting["id"],
        job_seeker_id=seeker["id"],
        status="STARTED",
        started_at=iso(store.clock),
        completed_at=None,
        disposition="NONE",
        responded_at=None,
        assessment_id=assessment["id"] if assessment else None,
        assessment_score=score,
    )
    posting["apply_started_count"] = posting["apply_started_count"] + 1
    touch(posting)

    create(
        "apply_events",
        application_id=application["id"],
        kind="STARTED",
        source="HOSTED" if posting["apply_mode"] == "HOSTED" else "REDIRECT",
        occurred_at=iso(store.clock),
    )
    return ok(application_view(application), 201)


@bp.get("/applications")
def list_applications():
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "JobSeeker"))
    V.reject_unknown_query({"job_seeker_id", "job_posting_id", "status", "limit", "offset"})
    seeker_id = V.str_filter("job_seeker_id")
    posting_id = V.str_filter("job_posting_id")
    status = V.enum_filter("status", APPLICATION_STATUSES)
    limit, offset = V.pagination()
    if seeker_id is not None:
        V.get("job_seeker", seeker_id)
    if posting_id is not None:
        V.get("job_posting", posting_id)

    items = []
    for application in store.applications.values():
        if seeker_id is not None and application["job_seeker_id"] != seeker_id:
            continue
        if posting_id is not None and application["job_posting_id"] != posting_id:
            continue
        if status is not None and application["status"] != status:
            continue
        if role == "JobSeeker" and application["job_seeker_id"] != actor_id:
            continue
        if role == "Employer" and application_employer_id(application) != actor_id:
            continue
        items.append(application)

    items = V.sort_newest(items)
    total = len(items)
    return array([application_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))


@bp.get("/applications/<application_id>")
def get_application(application_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "JobSeeker"))
    application = load_application(actor_id, role, application_id)
    return ok(application_view(application))


@bp.post("/applications/<application_id>/complete")
def complete_application(application_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("JobSeeker", "PlatformAdmin"))
    data = V.body()
    application = load_application(actor_id, role, application_id)
    posting = store.job_postings[application["job_posting_id"]]

    from errors import (
        ERR_ASSESSMENT_SCORE_BELOW_THRESHOLD,
        ERR_INVALID_APPLICATION_STATE,
        ERR_INVALID_REQUEST,
        fail,
    )

    # Tier 4: only STARTED may complete.
    if application["status"] == "CLOSED":
        from errors import ERR_APPLICATION_ALREADY_TERMINAL
        fail(ERR_APPLICATION_ALREADY_TERMINAL, "The application is CLOSED.")
    if application["status"] != "STARTED":
        fail(ERR_INVALID_APPLICATION_STATE,
             "Only an application in STARTED can be completed.")

    # Tier 6: screening is owed only when the posting's newest PUBLISHED
    # assessment carries a pass_threshold above zero.
    assessment = attached_assessment(posting["id"])
    answers_supplied = "assessment_answers" in data and data["assessment_answers"] is not None
    if assessment is not None and assessment["pass_threshold"] > 0:
        if answers_supplied:
            application["assessment_score"] = score_answers(assessment, data["assessment_answers"])
        elif application["assessment_id"] is None:
            from errors import ERR_INVALID_REQUEST as _EIR
            fail(_EIR,
                 "assessment_answers are required to complete an application against a "
                 "posting that carries a scored assessment.")
        score = application["assessment_score"]
        if score is None or score < assessment["pass_threshold"]:
            fail(ERR_ASSESSMENT_SCORE_BELOW_THRESHOLD,
                 "The assessment score is below the assessment's pass_threshold.")
    elif assessment is not None and answers_supplied:
        if application["assessment_id"] is None:
            application["assessment_id"] = assessment["id"]
        application["assessment_score"] = score_answers(assessment, data["assessment_answers"])

    application["status"] = "COMPLETED"
    application["completed_at"] = iso(store.clock)
    touch(application)
    posting["apply_completed_count"] = posting["apply_completed_count"] + 1
    touch(posting)

    create(
        "apply_events",
        application_id=application["id"],
        kind="COMPLETED",
        occurred_at=iso(store.clock),
        source="HOSTED" if posting["apply_mode"] == "HOSTED" else "REDIRECT",
    )

    # A sponsored APPLICATION event is recorded; it bills only on a CPA campaign.
    events.record_completion_event(posting)
    return ok(application_view(application))


@bp.post("/applications/<application_id>/close")
def close_application(application_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer", "JobSeeker", "PlatformAdmin"))
    V.body()
    application = load_application(actor_id, role, application_id)

    from errors import ERR_APPLICATION_ALREADY_TERMINAL, ERR_INVALID_APPLICATION_STATE, fail

    if application["status"] == "CLOSED":
        fail(ERR_APPLICATION_ALREADY_TERMINAL, "The application is already CLOSED.")
    if application["status"] not in ("STARTED", "COMPLETED", "RESPONDED"):
        fail(ERR_INVALID_APPLICATION_STATE, "The application cannot be closed.")

    application["status"] = "CLOSED"
    touch(application)

    # A CLOSED application with no disposition counts against the employer signal.
    employer_id = application_employer_id(application)
    employer = store.employers.get(employer_id) if employer_id else None
    if employer is not None and employer["status"] == "ACTIVE":
        calc.recompute_employer_quality(employer)
        calc.recompute_employer_sponsored_pacing(employer["id"])
    return ok(application_view(application))


@bp.post("/applications/<application_id>/disposition")
def record_disposition(application_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("Employer",))
    data = V.body()
    V.require_fields(data, ["disposition"])
    disposition = V.require_string(data, "disposition")
    application = load_application(actor_id, role, application_id)

    from errors import (
        ERR_APPLICATION_ALREADY_TERMINAL,
        ERR_INVALID_APPLICATION_STATE,
        ERR_INVALID_REQUEST,
        fail,
    )

    # Tier 4: only COMPLETED (and RESPONDED, for a changed disposition) is eligible.
    if application["status"] == "CLOSED":
        fail(ERR_APPLICATION_ALREADY_TERMINAL, "The application is CLOSED.")
    if application["status"] not in ("COMPLETED", "RESPONDED"):
        fail(ERR_INVALID_APPLICATION_STATE,
             "Disposition requires a COMPLETED application.")

    # Tier 6/11: disposition member validity.
    if disposition not in RESPONDING:
        fail(ERR_INVALID_REQUEST,
             "disposition must be one of REVIEWED, INTERVIEW, REJECTED, HIRED.")

    application["disposition"] = disposition
    if application["responded_at"] is None:
        application["responded_at"] = iso(store.clock)
    if application["status"] == "COMPLETED":
        application["status"] = "RESPONDED"
    touch(application)

    # Quality recompute fires only while the employer is ACTIVE (PRD 3.6).
    employer_id = application_employer_id(application)
    employer = store.employers.get(employer_id) if employer_id else None
    if employer is not None and employer["status"] == "ACTIVE":
        calc.recompute_employer_quality(employer)
        touch(employer)
        calc.recompute_employer_sponsored_pacing(employer["id"])
    return ok(application_view(application))


@bp.get("/applications/<application_id>/apply-events")
def list_apply_events(application_id):
    actor_id, role = auth.actor()
    auth.require_role(actor_id, role, ("PlatformAdmin", "Employer", "JobSeeker"))
    application = load_application(actor_id, role, application_id)
    V.reject_unknown_query({"limit", "offset"})
    limit, offset = V.pagination()
    items = [
        event for event in store.apply_events.values()
        if event["application_id"] == application["id"]
    ]
    items = V.sort_newest(items)
    total = len(items)
    return array([apply_event_view(row) for row in paginate(items, limit, offset)], 200,
                 page_meta(limit, offset, total))