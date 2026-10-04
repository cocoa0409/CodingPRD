from flask import Blueprint

from db import store, new_entity, touch, parse_date
from errors import ApiError, bad_request, not_found, invalid_state
from middleware import (auth, body, need, need_str, need_int, need_date,
                        need_enum, forbid_role)
from response import ok
from serialize import application_json
import services as svc

bp = Blueprint("applications", __name__)

EDUCATION_LEVELS = {"LESS_THAN_HS", "HS_DIPLOMA", "GED", "SOME_COLLEGE",
                    "ASSOCIATES", "BACHELORS_PLUS"}
CITIZENSHIP = {"US_CITIZEN", "US_NATIONAL", "PERMANENT_RESIDENT", "OTHER"}
REJECTION_REASONS = {"BACKGROUND_CHECK_FAILED", "APPLICANT_WITHDREW",
                     "OFFER_DECLINED"}
TRIGGERS = {"SCREEN", "INTERVIEWED", "OFFERED", "ACCEPTED", "DECLINED",
            "REJECTED", "WITHDRAWN", "ENROLLED"}


def _age_on(dob, on):
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


@bp.route("/corps/applications", methods=["POST"])
def create_application():
    auth(["Applicant"])
    data = body()
    site_id = need_str(data, "site_id")
    full_name = need_str(data, "full_name")
    dob = need_date(data, "date_of_birth")
    education = need_enum(data, "education_level", EDUCATION_LEVELS)
    citizenship = need_enum(data, "citizenship_status", CITIZENSHIP)
    terms = need_int(data, "prior_service_terms")
    if terms < 0:
        bad_request("prior_service_terms must be >= 0")
    awards = need_int(data, "prior_full_awards_received")
    if awards < 0:
        bad_request("prior_full_awards_received must be >= 0")
    site = store.sites.get(site_id)
    if site is None:
        not_found("Site not found")
    # Hard eligibility gates run at creation, in fixed order: age, education, service.
    age = _age_on(parse_date(dob), parse_date(site["service_year_start"]))
    if age < 17 or age > 25:
        raise ApiError("ERR_AGE_INELIGIBLE", 422,
                       "Applicant age at service_year_start must be 17..25")
    if education == "LESS_THAN_HS":
        raise ApiError("ERR_EDUCATION_INELIGIBLE", 422,
                       "education_level LESS_THAN_HS is ineligible")
    if citizenship == "OTHER" or terms >= 4 or awards >= 2:
        raise ApiError("ERR_SERVICE_INELIGIBLE", 422,
                       "Service eligibility requirements not met")
    a = new_entity({
        "site_id": site_id,
        "full_name": full_name,
        "date_of_birth": dob,
        "education_level": education,
        "citizenship_status": citizenship,
        "prior_service_terms": terms,
        "prior_full_awards_received": awards,
        "status": "SUBMITTED",
        "rejection_reason": None,
        "enrolled_member_id": None,
    })
    store.applications[a["id"]] = a
    return ok(application_json(a), 201)


@bp.route("/corps/applications/<app_id>/state", methods=["POST"])
def application_state(app_id):
    uid, role = auth(["ProgramManager", "Applicant"])
    data = body()
    to_status = need(data, "to_status")
    if to_status not in TRIGGERS:
        bad_request("to_status must be one of %s" % sorted(TRIGGERS))
    rejection_reason = data.get("rejection_reason")
    if rejection_reason is not None and rejection_reason not in REJECTION_REASONS:
        bad_request("rejection_reason must be one of %s" % sorted(REJECTION_REASONS))
    a = store.applications.get(app_id)
    if a is None:
        not_found("Application not found")
    cur = a["status"]

    # Role gating per transition (endpoint admits both roles).
    if to_status in ("SCREEN", "INTERVIEWED", "OFFERED", "REJECTED", "ENROLLED"):
        if role != "ProgramManager":
            forbid_role("Only a ProgramManager may perform this transition")
    elif to_status in ("ACCEPTED", "DECLINED"):
        if role != "Applicant":
            forbid_role("Only the Applicant may answer an offer")
    # WITHDRAWN: either role.

    if to_status == "SCREEN":
        if cur != "SUBMITTED":
            invalid_state("SCREEN is only valid from SUBMITTED")
        # Soft screening always succeeds (200); the branch is chosen by the
        # optional rejection_reason in the request.
        if rejection_reason == "BACKGROUND_CHECK_FAILED":
            a["status"] = "REJECTED"
            a["rejection_reason"] = "BACKGROUND_CHECK_FAILED"
        else:
            a["status"] = "SCREENED_ELIGIBLE"
    elif to_status == "INTERVIEWED":
        if cur != "SCREENED_ELIGIBLE":
            invalid_state("INTERVIEWED is only valid from SCREENED_ELIGIBLE")
        a["status"] = "INTERVIEWED"
    elif to_status == "OFFERED":
        if cur != "INTERVIEWED":
            invalid_state("OFFERED is only valid from INTERVIEWED")
        a["status"] = "OFFERED"
    elif to_status == "REJECTED":
        if cur != "INTERVIEWED":
            invalid_state("REJECTED is only valid from INTERVIEWED")
        if rejection_reason is None:
            bad_request("rejection_reason is required for REJECTED")
        a["status"] = "REJECTED"
        a["rejection_reason"] = rejection_reason
    elif to_status == "ACCEPTED":
        if cur != "OFFERED":
            invalid_state("ACCEPTED is only valid from OFFERED")
        a["status"] = "ACCEPTED"
    elif to_status == "DECLINED":
        if cur != "OFFERED":
            invalid_state("DECLINED is only valid from OFFERED")
        a["status"] = "DECLINED"
        a["rejection_reason"] = "OFFER_DECLINED"
    elif to_status == "WITHDRAWN":
        if cur not in ("SUBMITTED", "SCREENED_ELIGIBLE", "INTERVIEWED",
                       "OFFERED", "ACCEPTED"):
            invalid_state("WITHDRAWN is not valid from %s" % cur)
        a["status"] = "WITHDRAWN"
        a["rejection_reason"] = "APPLICANT_WITHDREW"
    elif to_status == "ENROLLED":
        if cur != "ACCEPTED":
            invalid_state("ENROLLED is only valid from ACCEPTED")
        site = store.sites.get(a["site_id"])
        if site is None or site["status"] != "ACTIVE":
            invalid_state("Site is not ACTIVE")
        member = new_entity({
            "site_id": a["site_id"],
            "full_name": a["full_name"],
            "service_status": "ENROLLED",
            "stipend_status": "NOT_STARTED",
            "award_status": "NOT_EARNED",
            "award_amount_cents": None,
            "exit_type": None,
            "exit_date": None,
        })
        store.members[member["id"]] = member
        a["status"] = "ENROLLED"
        a["enrolled_member_id"] = member["id"]
    touch(a)
    return ok(application_json(a), 200)
