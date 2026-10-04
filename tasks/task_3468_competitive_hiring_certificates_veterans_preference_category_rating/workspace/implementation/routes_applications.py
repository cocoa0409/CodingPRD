"""Application submission, screening, and application-scoped lists
(PRD 3.4). Gates fire in the section 2.7 priority order."""
from flask import Blueprint

from auth import get_auth, require_applicant_owner, require_roles
from calc import category_for_score, qualification_determination, sme_technical_score
from envelope import success_list, success_object
from errors import fail, invalid_state, not_found
from serializers import (appeal_out, application_out, assessment_out,
                         entry_out)
from store import DB, base_fields, now, touch
from validate import get_body, parse_pagination, req_int, req_str

bp = Blueprint("applications", __name__)

# Non-COMPETITIVE authority -> required verified document type at apply time.
AUTHORITY_DOC = {
    "DIRECT_HIRE": None,
    "VEOA": "DD214",
    "SCHEDULE_A": "SCHEDULE_A_CERT",
    "NONCOMPETITIVE_SPOUSE": "MILITARY_SPOUSE_ORDERS",
}


def get_application_or_404(application_id):
    row = DB.applications.get(application_id)
    if row is None:
        not_found("application")
    return row


def _area_admits(ann, position, applicant):
    if not applicant["is_us_citizen"]:
        return False
    area = ann["area_of_consideration"]
    if area == "ALL_US_CITIZENS":
        return True
    if area == "STATUS_CANDIDATES":
        has_verified_preference = (
            applicant["preference_verified"] and applicant["veteran_preference_claim"] != "NONE"
        )
        return bool(applicant["is_current_federal_employee"] or has_verified_preference)
    # AGENCY_ONLY
    return applicant.get("agency_code") is not None and applicant["agency_code"] == position["org_code"]


def _authority_docs_satisfied(ann, applicant):
    required = AUTHORITY_DOC.get(ann["hiring_authority"])
    if required is None:
        return True
    return any(
        d["applicant_id"] == applicant["id"] and d["doc_type"] == required and d["verified"]
        for d in DB.documents.values()
    )


@bp.route("/hiring/announcements/<announcement_id>/applications", methods=["POST"])
def submit_application(announcement_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant"])
    body = get_body()
    applicant_id = req_str(body, "applicant_id")
    exp_months = req_int(body, "claimed_experience_months", 0)
    edu_months = req_int(body, "claimed_education_months", 0)
    sr_k = req_int(body, "self_rating_knowledge", 1, 5)
    sr_s = req_int(body, "self_rating_skill", 1, 5)
    sr_a = req_int(body, "self_rating_ability", 1, 5)
    ann = DB.announcements.get(announcement_id)
    if ann is None:
        not_found("announcement")
    applicant = DB.applicants.get(applicant_id)
    if applicant is None:
        not_found("applicant")
    require_applicant_owner(user_id, applicant["id"])
    # Priority 5: announcement must be OPEN.
    if ann["status"] != "OPEN":
        fail("ERR_ANNOUNCEMENT_NOT_OPEN", "announcement is not OPEN")
    # Priority 7: one application per applicant per announcement.
    for a in DB.applications.values():
        if a["announcement_id"] == ann["id"] and a["applicant_id"] == applicant["id"]:
            fail("ERR_DUPLICATE_APPLICATION", "applicant already applied to this announcement")
    # Priority 8: half-open period [open_at, close_at).
    clock = now()
    if not (ann["open_at"] <= clock < ann["close_at"]):
        fail("ERR_OUTSIDE_OPEN_PERIOD", "logical clock is outside the open period")
    # Priority 9: area of consideration, then authority eligibility docs.
    position = DB.positions[ann["position_id"]]
    if not _area_admits(ann, position, applicant):
        fail("ERR_OUTSIDE_AREA_OF_CONSIDERATION",
             "applicant fails the area of consideration")
    if not _authority_docs_satisfied(ann, applicant):
        fail("ERR_ELIGIBILITY_DOC_REQUIRED",
             "verified eligibility document required for this hiring authority")
    provisional = sme_technical_score(sr_k, sr_s, sr_a)
    row = base_fields()
    row.update({
        "announcement_id": ann["id"], "applicant_id": applicant["id"],
        "submitted_at": clock,
        "claimed_experience_months": exp_months,
        "claimed_education_months": edu_months,
        "self_rating_knowledge": sr_k, "self_rating_skill": sr_s,
        "self_rating_ability": sr_a,
        "provisional_score": provisional,
        "provisional_category": category_for_score(provisional, ann["bq_cut"], ann["wq_cut"]),
        "required_experience_months": None,
        "creditable_experience_months": None,
        "technical_score": None, "quality_category": None,
        "notified_at": clock,
        "status": "RECEIVED",
    })
    DB.applications[row["id"]] = row
    return success_object(application_out(row), 201)


@bp.route("/hiring/applications/<application_id>", methods=["GET"])
def read_application(application_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant", "HRSpecialist", "SelectingOfficial", "SME"])
    row = get_application_or_404(application_id)
    if role == "Applicant":
        require_applicant_owner(user_id, row["applicant_id"])
    return success_object(application_out(row))


@bp.route("/hiring/applications/<application_id>/screen", methods=["POST"])
def screen_application(application_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    get_body()
    row = get_application_or_404(application_id)
    if row["status"] != "RECEIVED":
        fail("ERR_APPLICATION_WRONG_STATE", "application is not RECEIVED")
    ann = DB.announcements[row["announcement_id"]]
    if ann["status"] not in ("OPEN", "CLOSED", "CERT_ISSUED"):
        invalid_state("announcement state does not allow screening")
    position = DB.positions[ann["position_id"]]
    series = DB.series[position["series_id"]]
    required, creditable, qualified = qualification_determination(row, position, series)
    row["required_experience_months"] = required
    row["creditable_experience_months"] = creditable
    row["status"] = "QUALIFIED" if qualified else "INELIGIBLE"
    row["notified_at"] = now()
    touch(row)
    return success_object(application_out(row))


@bp.route("/hiring/applications/<application_id>/assessments", methods=["GET"])
def list_application_assessments(application_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SME"])
    row = get_application_or_404(application_id)
    limit, offset = parse_pagination()
    items = [a for a in DB.assessments.values() if a["application_id"] == row["id"]]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([assessment_out(a) for a in page], limit, offset, total)


@bp.route("/hiring/applications/<application_id>/appeals", methods=["GET"])
def list_application_appeals(application_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant", "HRSpecialist"])
    row = get_application_or_404(application_id)
    if role == "Applicant":
        require_applicant_owner(user_id, row["applicant_id"])
    limit, offset = parse_pagination()
    items = [a for a in DB.appeals.values() if a["application_id"] == row["id"]]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([appeal_out(a) for a in page], limit, offset, total)


@bp.route("/hiring/applications/<application_id>/certificate-entries", methods=["GET"])
def list_application_entries(application_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "SelectingOfficial"])
    row = get_application_or_404(application_id)
    limit, offset = parse_pagination()
    items = [e for e in DB.entries.values() if e["application_id"] == row["id"]]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([entry_out(e) for e in page], limit, offset, total)
