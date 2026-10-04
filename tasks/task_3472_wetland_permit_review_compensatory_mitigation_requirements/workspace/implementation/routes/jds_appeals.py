"""JurisdictionalDetermination and Appeal endpoints (PRD §3.1, §3.2)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
from cascades import reverse_jd_cascade
from db import STORE, bump, get_clock, new_entity
from errors import api_err
from helpers import get_body, req_enum, req_str
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import appeal_out, jd_out

bp = Blueprint("jds_appeals", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")
JD_TYPES = ("PRELIMINARY", "APPROVED")
DETERMINATIONS = ("JURISDICTIONAL", "NON_JURISDICTIONAL")


def _get_jd_or_404(jd_id):
    jd = STORE["jds"].get(jd_id)
    if jd is None:
        raise api_err("ERR_JD_NOT_FOUND",
                      "No JurisdictionalDetermination with id %s" % jd_id)
    return jd


@bp.post("/wetland-permits/jurisdictional-determinations")
def create_jd():
    require_roles(["Reviewer"])
    body = get_body()
    # Tier 5: body FK existence.
    site_id = req_str(body, "site_id")
    if site_id not in STORE["sites"]:
        raise api_err("ERR_SITE_NOT_FOUND", "No WatersSite with id %s" % site_id)
    # Tier 6: shape.
    jd_type = req_enum(body, "jd_type", JD_TYPES)
    determination = req_enum(body, "determination", DETERMINATIONS)
    rationale = req_str(body, "rationale")
    jd = new_entity({
        "site_id": site_id,
        "jd_type": jd_type,
        "determination": determination,
        "rationale": rationale,
        "issued_date": None,
        "expiration_date": None,
        "status": "DRAFT",
    })
    STORE["jds"][jd["id"]] = jd
    return success_obj(jd_out(jd), 201)


@bp.get("/wetland-permits/jurisdictional-determinations")
def list_jds():
    require_roles(list(ALL_ROLES))
    jds = apply_filters(STORE["jds"].values(), {
        "site_id": "site_id",
        "jd_type": "jd_type",
        "status": "status",
    })
    return list_response(jds, jd_out)


@bp.get("/wetland-permits/jurisdictional-determinations/<id>")
def get_jd(id):
    require_roles(list(ALL_ROLES))
    return success_obj(jd_out(_get_jd_or_404(id)))


@bp.post("/wetland-permits/jurisdictional-determinations/<id>/issue")
def issue_jd(id):
    require_roles(["DistrictEngineer"])
    jd = _get_jd_or_404(id)
    # Tier 7: state.
    if jd["status"] != "DRAFT":
        raise api_err("ERR_JD_INVALID_STATE",
                      "Only a DRAFT determination can be issued")
    # Priority 22: one live determination per site — no other JD of the same
    # site may be ISSUED with expiration_date >= current clock.
    clock = get_clock()
    for other in STORE["jds"].values():
        if other["id"] == jd["id"] or other["site_id"] != jd["site_id"]:
            continue
        if other["status"] == "ISSUED" and other["expiration_date"] is not None \
                and other["expiration_date"] >= clock:
            raise api_err(
                "ERR_ACTIVE_JD_EXISTS",
                "Another determination for this site is ISSUED and unexpired")
    jd["status"] = "ISSUED"
    jd["issued_date"] = clock
    jd["expiration_date"] = clock + timedelta(days=calc.JD_VALIDITY_DAYS)
    bump(jd)
    return success_obj(jd_out(jd))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

@bp.post("/wetland-permits/appeals")
def create_appeal():
    user_id, role = require_roles(["Applicant"])
    body = get_body()
    # Tier 5: body FK existence (needed before ownership can be evaluated).
    jd_id = req_str(body, "jd_id")
    jd = STORE["jds"].get(jd_id)
    if jd is None:
        raise api_err("ERR_JD_NOT_FOUND",
                      "No JurisdictionalDetermination with id %s" % jd_id)
    # Tier 4: ownership — the caller must own the site's applicant record.
    site = STORE["sites"].get(jd["site_id"])
    check_ownership(user_id, role,
                    site["applicant_id"] if site else None)
    # Tier 6: shape.
    grounds_text = req_str(body, "grounds_text")
    # Tier 7: state — the determination must be ISSUED.
    if jd["status"] != "ISSUED":
        raise api_err("ERR_JD_INVALID_STATE",
                      "Only an ISSUED determination can be appealed")
    # Priority 9: only APPROVED determinations carry appeal rights.
    if jd["jd_type"] != "APPROVED":
        raise api_err("ERR_JD_NOT_APPEALABLE",
                      "Only APPROVED determinations carry appeal rights")
    # Priority 10: appeal window — at most 60 days after issuance; exactly
    # 60 days is allowed.
    clock = get_clock()
    if clock - jd["issued_date"] > timedelta(days=calc.APPEAL_WINDOW_DAYS):
        raise api_err("ERR_APPEAL_WINDOW_CLOSED",
                      "The 60-day appeal window has closed")
    # Priority 23: at most one appeal per determination.
    for existing in STORE["appeals"].values():
        if existing["jd_id"] == jd["id"]:
            raise api_err("ERR_APPEAL_ALREADY_FILED",
                          "An appeal already exists for this determination")
    appeal = new_entity({
        "jd_id": jd["id"],
        "appellant_applicant_id": user_id,
        "grounds_text": grounds_text,
        "filed_date": clock,
        "decided_date": None,
        "decision_rationale": None,
        "status": "FILED",
    })
    STORE["appeals"][appeal["id"]] = appeal
    return success_obj(appeal_out(appeal), 201)


@bp.get("/wetland-permits/appeals")
def list_appeals():
    require_roles(list(ALL_ROLES))
    appeals = apply_filters(STORE["appeals"].values(), {
        "jd_id": "jd_id",
        "appellant_applicant_id": "appellant_applicant_id",
        "status": "status",
    })
    return list_response(appeals, appeal_out)


@bp.get("/wetland-permits/appeals/<id>")
def get_appeal(id):
    require_roles(list(ALL_ROLES))
    appeal = STORE["appeals"].get(id)
    if appeal is None:
        raise api_err("ERR_APPEAL_NOT_FOUND", "No Appeal with id %s" % id)
    return success_obj(appeal_out(appeal))


@bp.post("/wetland-permits/appeals/<id>/decide")
def decide_appeal(id):
    require_roles(["DistrictEngineer"])
    appeal = STORE["appeals"].get(id)
    if appeal is None:
        raise api_err("ERR_APPEAL_NOT_FOUND", "No Appeal with id %s" % id)
    body = get_body()
    # Tier 6: shape.
    outcome = req_enum(body, "outcome", ("SUSTAINED", "DENIED"))
    decision_rationale = req_str(body, "decision_rationale")
    # Tier 7: state.
    if appeal["status"] != "FILED":
        raise api_err("ERR_APPEAL_INVALID_STATE",
                      "Only a FILED appeal can be decided")
    appeal["status"] = outcome
    appeal["decided_date"] = get_clock()
    appeal["decision_rationale"] = decision_rationale
    bump(appeal)
    if outcome == "SUSTAINED":
        jd = STORE["jds"].get(appeal["jd_id"])
        if jd is not None and jd["status"] == "ISSUED":
            reverse_jd_cascade(jd)
    return success_obj(appeal_out(appeal))
