"""Specialty societies and stakeholder applicants."""

from flask import Blueprint

import auth
import parsers as P
import resolvers as R
import store
from response import object_response
from routes.common import guard, list_response, one

bp = Blueprint("societies", __name__)

STAFF = (auth.EDITORIAL_STAFF,)
SOCIETY_READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR, auth.COMMITTEE_REVIEWER)
APPLICANT_READERS = (auth.EDITORIAL_STAFF, auth.LICENSING_OFFICER)
SOCIETY_APPLICANT_READERS = (auth.EDITORIAL_STAFF, auth.EDITORIAL_PANEL_CHAIR)


@bp.post("/specialty-societies")
@guard(STAFF)
def create_society(actor):
    data = P.body()
    society = store.create(store.societies, {
        "name": P.text(data.get("name")),
        "specialty_code": P.text(data.get("specialty_code")),
        "voting_seat_count": P.integer(data.get("voting_seat_count"), 0),
        "gpci_work": P.number(data.get("gpci_work"), "1.0000"),
        "gpci_pe": P.number(data.get("gpci_pe"), "1.0000"),
        "gpci_mp": P.number(data.get("gpci_mp"), "1.0000"),
        # Derived; initialized to 0 when the society is registered.
        "cea_credit_balance": 0.0,
        "status": P.text(data.get("status"), "ACTIVE"),
    })
    return object_response(one(society), 201)


@bp.get("/specialty-societies")
@guard(SOCIETY_READERS)
def list_societies(actor):
    return list_response(store.sorted_rows(store.societies))


@bp.get("/specialty-societies/<society_id>")
@guard(SOCIETY_READERS)
def read_society(actor, society_id):
    return object_response(one(R.society(society_id)))


@bp.post("/specialty-societies/<society_id>/seat-assignments")
@guard(STAFF)
def seat_assignment(actor, society_id):
    society = R.society(society_id)
    data = P.body()
    society["voting_seat_count"] = P.integer(
        data.get("voting_seat_count"), society.get("voting_seat_count", 0)
    )
    store.bump(society)
    return object_response(one(society))


@bp.post("/applicants")
@guard(STAFF)
def create_applicant(actor):
    data = P.body()
    society_id = P.text_or_none(data.get("society_id"))
    if society_id is not None:
        R.fk(store.societies, society_id, "SpecialtySociety")
    applicant = store.create(store.applicants, {
        "name": P.text(data.get("name")),
        "applicant_type": P.text(data.get("applicant_type")),
        "society_id": society_id,
        "is_entity_member": P.boolean(data.get("is_entity_member"), False),
        "dues_paid_current": P.boolean(data.get("dues_paid_current"), False),
        "contact_email": P.text(data.get("contact_email")),
        "status": P.text(data.get("status"), "ACTIVE"),
    })
    return object_response(one(applicant), 201)


@bp.get("/applicants")
@guard(APPLICANT_READERS)
def list_applicants(actor):
    return list_response(store.sorted_rows(store.applicants))


@bp.get("/applicants/<applicant_id>")
@guard(APPLICANT_READERS)
def read_applicant(actor, applicant_id):
    return object_response(one(R.applicant(applicant_id)))


@bp.get("/specialty-societies/<society_id>/applicants")
@guard(SOCIETY_APPLICANT_READERS)
def list_society_applicants(actor, society_id):
    society = R.society(society_id)
    rows = [a for a in store.sorted_rows(store.applicants)
            if a.get("society_id") == society["id"]]
    return list_response(rows)