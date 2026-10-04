"""Applicant registration, eligibility documents, verification (PRD 3.3)."""
from flask import Blueprint

from auth import get_auth, require_applicant_owner, require_roles
from calc import preference_state
from envelope import success_list, success_object
from errors import fail, not_found
from serializers import applicant_out, application_out, document_out
from store import DB, base_fields, now, touch
from validate import get_body, opt_str, parse_pagination, req_bool, req_enum, req_str

bp = Blueprint("applicants", __name__)

CLAIMS = ["NONE", "FIVE_POINT", "TEN_POINT_CP", "TEN_POINT_CPS"]
DOC_TYPES = ["DD214", "SF50", "VA_LETTER", "SCHEDULE_A_CERT", "MILITARY_SPOUSE_ORDERS"]


def get_applicant_or_404(applicant_id):
    row = DB.applicants.get(applicant_id)
    if row is None:
        not_found("applicant")
    return row


def recompute_preference(applicant):
    verified_types = {
        d["doc_type"]
        for d in DB.documents.values()
        if d["applicant_id"] == applicant["id"] and d["verified"]
    }
    verified, points = preference_state(applicant, verified_types)
    if applicant["preference_verified"] != verified or applicant["preference_points"] != points:
        applicant["preference_verified"] = verified
        applicant["preference_points"] = points
        touch(applicant)


@bp.route("/hiring/applicants", methods=["POST"])
def register_applicant():
    # Under the Applicant role the supplied X-User-ID is ignored; the new
    # record's id becomes that applicant's identity (PRD 2.1).
    _, role = get_auth()
    require_roles(role, ["Applicant", "HRSpecialist"])
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    is_citizen = req_bool(body, "is_us_citizen")
    is_fed = req_bool(body, "is_current_federal_employee")
    agency_code = opt_str(body, "agency_code")
    claim = req_enum(body, "veteran_preference_claim", CLAIMS)
    for a in DB.applicants.values():
        if a["email"] == email:
            fail("ERR_DUPLICATE_KEY", "email already registered")
    verified, points = preference_state({"veteran_preference_claim": claim}, set())
    row = base_fields()
    row.update({
        "full_name": full_name, "email": email,
        "is_us_citizen": is_citizen, "is_current_federal_employee": is_fed,
        "agency_code": agency_code, "veteran_preference_claim": claim,
        "preference_verified": verified, "preference_points": points,
    })
    DB.applicants[row["id"]] = row
    return success_object(applicant_out(row), 201)


@bp.route("/hiring/applicants/<applicant_id>", methods=["GET"])
def read_applicant(applicant_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant", "HRSpecialist", "OPMDelegate"])
    row = get_applicant_or_404(applicant_id)
    if role == "Applicant":
        require_applicant_owner(user_id, row["id"])
    return success_object(applicant_out(row))


@bp.route("/hiring/applicants/<applicant_id>/applications", methods=["GET"])
def list_applicant_applications(applicant_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant", "HRSpecialist"])
    row = get_applicant_or_404(applicant_id)
    if role == "Applicant":
        require_applicant_owner(user_id, row["id"])
    limit, offset = parse_pagination()
    items = [a for a in DB.applications.values() if a["applicant_id"] == row["id"]]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([application_out(a) for a in page], limit, offset, total)


@bp.route("/hiring/applicants/<applicant_id>/documents", methods=["POST"])
def upload_document(applicant_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant", "OPMDelegate"])
    body = get_body()
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    row = get_applicant_or_404(applicant_id)
    if role == "Applicant":
        require_applicant_owner(user_id, row["id"])
    doc = base_fields()
    doc.update({
        "applicant_id": row["id"], "doc_type": doc_type,
        "verified": False, "verified_by": None, "verified_at": None,
    })
    DB.documents[doc["id"]] = doc
    return success_object(document_out(doc), 201)


@bp.route("/hiring/applicants/<applicant_id>/documents", methods=["GET"])
def list_documents(applicant_id):
    user_id, role = get_auth()
    require_roles(role, ["Applicant", "HRSpecialist", "OPMDelegate"])
    row = get_applicant_or_404(applicant_id)
    if role == "Applicant":
        require_applicant_owner(user_id, row["id"])
    limit, offset = parse_pagination()
    items = [d for d in DB.documents.values() if d["applicant_id"] == row["id"]]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([document_out(d) for d in page], limit, offset, total)


@bp.route("/hiring/documents/<document_id>/verify", methods=["POST"])
def verify_document(document_id):
    user_id, role = get_auth()
    require_roles(role, ["OPMDelegate"])
    get_body()
    doc = DB.documents.get(document_id)
    if doc is None:
        not_found("document")
    doc["verified"] = True
    doc["verified_by"] = user_id
    doc["verified_at"] = now()
    touch(doc)
    applicant = DB.applicants.get(doc["applicant_id"])
    if applicant is not None:
        recompute_preference(applicant)
    return success_object(document_out(doc))
