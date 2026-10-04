"""Appeal filing and adjudication (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint

from auth import get_auth, require_applicant_owner, require_roles
from calc import APPEAL_WINDOW_DAYS, qualification_determination
from cascade import eval_certificate
from envelope import success_object
from errors import fail, invalid_request, not_found
from serializers import appeal_out
from store import DB, base_fields, now, touch
from validate import get_body, opt_int, opt_str, req_enum

bp = Blueprint("appeals", __name__)

GROUNDS = ["QUALIFICATION", "RATING", "PREFERENCE"]


def _on_active_certificate(application_id):
    app_row = DB.applications[application_id]
    ann = DB.announcements[app_row["announcement_id"]]
    for c in DB.certificates.values():
        if c["announcement_id"] == ann["id"]:
            eval_certificate(c)
    for e in DB.entries.values():
        if e["application_id"] != application_id:
            continue
        cert = DB.certificates[e["certificate_id"]]
        if cert["status"] == "ACTIVE":
            return True
    return False


@bp.route("/hiring/applications/<application_id>/appeals", methods=["POST"])
def file_appeal(application_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant"])
    body = get_body()
    grounds = req_enum(body, "grounds", GROUNDS)
    if grounds == "QUALIFICATION":
        if "corrected_experience_months" not in body or body["corrected_experience_months"] is None:
            invalid_request("corrected_experience_months is required for QUALIFICATION appeals")
        corrected = opt_int(body, "corrected_experience_months", 0)
    else:
        corrected = opt_int(body, "corrected_experience_months", 0)
    app_row = DB.applications.get(application_id)
    if app_row is None:
        not_found("application")
    require_applicant_owner(user_id, app_row["applicant_id"])
    # Priority 5: appealable posture.
    if app_row["status"] not in ("INELIGIBLE", "RATED"):
        fail("ERR_APPEAL_NOT_ALLOWED_STATE",
             "application is not in an appealable state")
    if grounds == "RATING" and _on_active_certificate(application_id):
        fail("ERR_APPEAL_NOT_ALLOWED_STATE",
             "application is referenced by an ACTIVE certificate")
    # Priority 7: grounds must match posture.
    if grounds == "QUALIFICATION" and app_row["status"] != "INELIGIBLE":
        fail("ERR_APPEAL_GROUND_MISMATCH", "QUALIFICATION appeals require INELIGIBLE")
    if grounds == "RATING" and app_row["status"] != "RATED":
        fail("ERR_APPEAL_GROUND_MISMATCH", "RATING appeals require RATED")
    # Priority 8: filing must land strictly before the deadline.
    clock = now()
    deadline = app_row["notified_at"] + timedelta(days=APPEAL_WINDOW_DAYS)
    if not clock < deadline:
        fail("ERR_APPEAL_WINDOW_EXPIRED", "appeal window has closed")
    row = base_fields()
    row.update({
        "application_id": app_row["id"], "grounds": grounds,
        "corrected_experience_months": corrected,
        "filed_at": clock, "deadline_at": deadline,
        "adjudication_note": None, "status": "FILED",
    })
    DB.appeals[row["id"]] = row
    return success_object(appeal_out(row), 201)


@bp.route("/hiring/appeals/<appeal_id>/adjudicate", methods=["POST"])
def adjudicate_appeal(appeal_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["SUSTAINED", "DENIED"])
    note = opt_str(body, "adjudication_note")
    row = DB.appeals.get(appeal_id)
    if row is None:
        not_found("appeal")
    if row["status"] != "FILED":
        fail("ERR_APPEAL_NOT_ALLOWED_STATE", "appeal is not FILED")
    row["status"] = outcome
    row["adjudication_note"] = note
    touch(row)
    if outcome != "SUSTAINED":
        return success_object(appeal_out(row))
    app_row = DB.applications[row["application_id"]]
    if row["grounds"] in ("QUALIFICATION", "PREFERENCE"):
        if app_row["status"] == "INELIGIBLE":
            if row["corrected_experience_months"] is not None:
                app_row["claimed_experience_months"] = row["corrected_experience_months"]
            ann = DB.announcements[app_row["announcement_id"]]
            position = DB.positions[ann["position_id"]]
            series = DB.series[position["series_id"]]
            required, creditable, qualified = qualification_determination(app_row, position, series)
            app_row["required_experience_months"] = required
            app_row["creditable_experience_months"] = creditable
            if qualified:
                app_row["status"] = "QUALIFIED"
            app_row["notified_at"] = now()
            touch(app_row)
        elif app_row["status"] == "RATED":
            # PREFERENCE sustained from RATED: refresh the determination and
            # the notification anchor; the rating itself stands.
            ann = DB.announcements[app_row["announcement_id"]]
            position = DB.positions[ann["position_id"]]
            series = DB.series[position["series_id"]]
            if row["corrected_experience_months"] is not None:
                app_row["claimed_experience_months"] = row["corrected_experience_months"]
            required, creditable, _ = qualification_determination(app_row, position, series)
            app_row["required_experience_months"] = required
            app_row["creditable_experience_months"] = creditable
            app_row["notified_at"] = now()
            touch(app_row)
    else:  # RATING
        if app_row["status"] == "RATED":
            for a in DB.assessments.values():
                if a["application_id"] == app_row["id"] and a["status"] == "ACCEPTED":
                    a["status"] = "RETURNED"
                    a["return_reason"] = "APPEAL_SUSTAINED"
                    touch(a)
            app_row["technical_score"] = None
            app_row["quality_category"] = None
            app_row["status"] = "QUALIFIED"
            app_row["notified_at"] = now()
            touch(app_row)
    return success_object(appeal_out(row))
