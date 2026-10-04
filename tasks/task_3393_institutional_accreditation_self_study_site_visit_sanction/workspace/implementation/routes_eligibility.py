"""Eligibility applications: draft, list, file/re-file, adjudicate (PRD §3.2)."""
from flask import Blueprint

import constants as C
from auth import authenticate, require_liaison_owns, require_role
from db import STORE, add_years, fmt_dt
from errors import (ERR_ELIGIBILITY_APPLICATION_NOT_FOUND,
                    ERR_INSTITUTION_NOT_FOUND, ERR_INVALID_STATE, raise_err)
from helpers import (fetch_or_404, get_body, new_entity, opt_string, paginate,
                     req_enum, req_string, touch)
from response import success_list, success_object

bp = Blueprint("eligibility", __name__)

ALL_ROLES = ["CommissionAdmin", "CommissionStaff", "InstitutionLiaison", "PeerReviewer"]


@bp.post("/accreditation/institutions/<inst_id>/eligibility-applications")
def create_application(inst_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    require_liaison_owns(actor, inst_id)
    inst = fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    body = get_body()
    pathway = req_enum(body, "pathway", C.PATHWAYS)
    statement = req_string(body, "statement_of_intent")
    if inst["accreditation_status"] != "PROSPECTIVE":
        raise_err(ERR_INVALID_STATE, "Eligibility drafting requires a PROSPECTIVE institution")
    app = new_entity({
        "institution_id": inst_id,
        "pathway": pathway,
        "statement_of_intent": statement,
        "status": "DRAFT",
        "filed_at": None,
        "adjudicated_at": None,
        "adjudication_notes": None,
    })
    STORE.eligibility_applications[app["id"]] = app
    return success_object(_ser(app), code=201)


def _ser(app):
    from helpers import serialize
    return serialize(app)


@bp.get("/accreditation/institutions/<inst_id>/eligibility-applications")
def list_applications(inst_id):
    actor = authenticate()
    if actor.role == "InstitutionLiaison":
        require_liaison_owns(actor, inst_id)
    fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    items = [a for a in STORE.eligibility_applications.values() if a["institution_id"] == inst_id]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.post("/accreditation/eligibility-applications/<app_id>/file")
def file_application(app_id):
    actor = authenticate()
    require_role(actor, ["InstitutionLiaison"])
    app = fetch_or_404(STORE.eligibility_applications, app_id, ERR_ELIGIBILITY_APPLICATION_NOT_FOUND)
    require_liaison_owns(actor, app["institution_id"])
    if app["status"] not in ("DRAFT", "DEFICIENT"):
        raise_err(ERR_INVALID_STATE, "Only a DRAFT or DEFICIENT application can be filed")
    app["status"] = "FILED"
    app["filed_at"] = STORE.now_iso()
    touch(app)
    return success_object(_ser(app))


@bp.post("/accreditation/eligibility-applications/<app_id>/adjudicate")
def adjudicate_application(app_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    app = fetch_or_404(STORE.eligibility_applications, app_id, ERR_ELIGIBILITY_APPLICATION_NOT_FOUND)
    body = get_body()
    decision = req_enum(body, "decision", C.ADJUDICATION_DECISIONS)
    notes = opt_string(body, "adjudication_notes")
    if app["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "Only a FILED application can be adjudicated")
    inst = STORE.institutions.get(app["institution_id"])
    if decision == "APPROVE":
        if inst["accreditation_status"] != "PROSPECTIVE":
            raise_err(ERR_INVALID_STATE, "Approval requires a PROSPECTIVE institution")
        app["status"] = "APPROVED"
        now = STORE.now()
        inst["accreditation_status"] = "CANDIDATE"
        inst["candidacy_pathway"] = app["pathway"]
        inst["candidacy_started_at"] = STORE.now_iso()
        expires = add_years(now, C.CANDIDACY_YEARS[app["pathway"]])
        inst["_candidacy_expires_dt"] = expires
        inst["candidacy_expires_at"] = fmt_dt(expires)
        touch(inst)
    elif decision == "DENY":
        app["status"] = "DENIED"
    else:  # REQUEST_COMPLETION
        app["status"] = "DEFICIENT"
    app["adjudicated_at"] = STORE.now_iso()
    app["adjudication_notes"] = notes
    touch(app)
    return success_object(_ser(app))
