"""Applicant companies and manufacturing facilities (PRD 3.1)."""
from flask import Blueprint

from auth import ALL_ROLES, auth, require_role
from envelope import sort_default, success_list, success_object
from errors import fail
from serialize import applicant, facility
from state import STORE, create_entity, get
from validate import body, req_str

bp = Blueprint("companies", __name__)


@bp.post("/generic-drug-review/applicant-companies")
def create_applicant():
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    b = body()
    legal_name = req_str(b, "legal_name")
    contact_email = req_str(b, "contact_email")
    headquarters_country = req_str(b, "headquarters_country")
    ent = create_entity("applicants", {
        "legal_name": legal_name,
        "contact_email": contact_email,
        "headquarters_country": headquarters_country,
    })
    return success_object(applicant(ent), 201)


@bp.get("/generic-drug-review/applicant-companies/<applicant_id>")
def get_applicant(applicant_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    ent = get("applicants", applicant_id)
    if ent is None:
        fail("ERR_APPLICANT_NOT_FOUND", "Applicant company id does not exist")
    return success_object(applicant(ent))


@bp.get("/generic-drug-review/applicant-companies/<applicant_id>/manufacturing-facilities")
def list_applicant_facilities(applicant_id):
    _uid, role = auth()
    require_role(role, ALL_ROLES)
    if get("applicants", applicant_id) is None:
        fail("ERR_APPLICANT_NOT_FOUND", "Applicant company id does not exist")
    items = [f for f in STORE["facilities"].values()
             if f["applicant_id"] == applicant_id]
    return success_list([facility(f) for f in sort_default(items)])


@bp.post("/generic-drug-review/manufacturing-facilities")
def create_facility():
    uid, role = auth()
    require_role(role, ["ApplicantSponsor"])
    b = body()
    # Priority 3 ownership, then priority 4 existence of the body reference,
    # then priority 5 shape. Checks skip gracefully when the field is absent
    # or mistyped; the shape pass then reports it.
    aid = b.get("applicant_id")
    if isinstance(aid, str):
        if aid != uid:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "applicant_id must equal the acting ApplicantSponsor's X-User-ID")
        if get("applicants", aid) is None:
            fail("ERR_APPLICANT_NOT_FOUND", "Applicant company id does not exist")
    aid = req_str(b, "applicant_id")
    facility_name = req_str(b, "facility_name")
    fei_number = req_str(b, "fei_number")
    country_code = req_str(b, "country_code")
    ent = create_entity("facilities", {
        "applicant_id": aid,
        "facility_name": facility_name,
        "fei_number": fei_number,
        "country_code": country_code,
        "is_foreign": country_code != "US",
    })
    return success_object(facility(ent), 201)
