from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, dec, fail, fmt_date, get_date, get_enum, get_str, now_date, ok,
                  pagination, paginate, q_enum, q_str, rh, sorted_rows)

bp = Blueprint("submissions", __name__)

TYPES = ("ACQUISITION", "DISPOSITION", "BIRTH", "TRANSFER")
STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")


@bp.post("/studbook-submissions")
@auth("Registrar")
def create_submission():
    b = body()
    program_id = get_str(b, "species_program_id", required=True)
    institution_id = get_str(b, "institution_id", required=True)
    agreement_id = get_str(b, "transfer_agreement_id")
    submission_type = get_enum(b, "submission_type", TYPES, required=True)
    period_end, period_end_raw = get_date(b, "reporting_period_end", required=True)

    db.get_program(program_id)
    db.get_institution(institution_id)
    if agreement_id is not None:
        db.get_agreement(agreement_id)

    if actor() != institution_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    for other in db.submissions.values():
        if other["species_program_id"] != program_id:
            continue
        if other["institution_id"] != institution_id:
            continue
        if other["submission_type"] != submission_type:
            continue
        if services.as_date(other["reporting_period_end"]) != period_end:
            continue
        if other["status"] in ("SUBMITTED", "ACCEPTED"):
            fail("ERR_DUPLICATE_STUDBOOK_SUBMISSION")

    submitted_on = now_date()
    days_late, base, multiplier, surcharge, total = calc.lateness(period_end, submitted_on)

    submission = db.insert(db.submissions, {
        "species_program_id": program_id,
        "institution_id": institution_id,
        "transfer_agreement_id": agreement_id,
        "submission_type": submission_type,
        "reporting_period_end": period_end_raw,
        "submitted_on": fmt_date(submitted_on),
        "days_late": days_late,
        "base_points": base,
        "surcharge_multiplier": multiplier,
        "surcharge_points": surcharge,
        "total_compliance_points": total,
        "status": "SUBMITTED",
        "review_note": None,
    })
    return ok(services.submission_out(submission), 201)


@bp.post("/studbook-submissions/<submission_id>/review")
@auth("ProgramCoordinator")
def review_submission(submission_id):
    b = body()
    outcome = get_enum(b, "outcome", ("ACCEPT", "REJECT"), required=True)
    review_note = get_str(b, "review_note")

    submission = db.get_submission(submission_id)
    if actor() != submission["species_program_id"]:
        fail("ERR_ACTOR_SCOPE_VIOLATION")

    if submission["status"] != "SUBMITTED":
        fail("ERR_SUBMISSION_ALREADY_REVIEWED")

    submission["status"] = "ACCEPTED" if outcome == "ACCEPT" else "REJECTED"
    submission["review_note"] = review_note
    db.touch(submission)

    institution = db.institutions.get(submission["institution_id"])
    if institution is not None:
        balance = rh(dec(institution["compliance_points_balance"])
                     + dec(submission["total_compliance_points"]), 2)
        institution["compliance_points_balance"] = balance
        if institution["accreditation_status"] == "ACCREDITED" \
                and balance >= calc.ACCREDITATION_REVIEW_POINTS:
            institution["accreditation_status"] = "PROVISIONAL"
        db.touch(institution)
    return ok(services.submission_out(submission))


@bp.get("/studbook-submissions/<submission_id>")
@auth()
def read_submission(submission_id):
    return ok(services.submission_out(db.get_submission(submission_id)))


@bp.get("/studbook-submissions")
@auth()
def list_submissions():
    limit, offset = pagination()
    filters = {
        "species_program_id": q_str("species_program_id"),
        "institution_id": q_str("institution_id"),
        "transfer_agreement_id": q_str("transfer_agreement_id"),
        "submission_type": q_enum("submission_type", TYPES),
        "status": q_enum("status", STATUSES),
    }
    rows = list(db.submissions.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.submission_out)
