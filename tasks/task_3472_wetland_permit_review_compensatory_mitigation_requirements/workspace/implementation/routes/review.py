"""AlternativesAnalysis and AgencyComment endpoints (PRD §3.4, §3.5)."""

from flask import Blueprint

from db import STORE, bump, get_clock, new_entity
from errors import api_err
from helpers import (get_body, opt_bool, opt_enum, opt_int, opt_str,
                     req_bool, req_enum, req_int, req_str, req_str_list)
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import aa_out, comment_out

bp = Blueprint("review", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")
LEDPA_CONCLUSIONS = ("PROPOSED_IS_LEDPA", "ALTERNATIVE_IS_LEDPA",
                     "UNDETERMINED")
AA_VERDICTS = ("ACCEPT", "REQUEST_REVISION", "REJECT")
AGENCIES = ("EPA", "FWS", "NMFS", "STATE_WATER_QUALITY", "TRIBAL_AUTHORITY")
COMMENT_TYPES = ("ADVISORY", "SUBSTANTIVE_OBJECTION", "CONCURRENCE")


def _get_aa_or_404(aa_id):
    aa = STORE["analyses"].get(aa_id)
    if aa is None:
        raise api_err("ERR_AA_NOT_FOUND",
                      "No AlternativesAnalysis with id %s" % aa_id)
    return aa


@bp.post("/wetland-permits/alternatives-analyses")
def create_aa():
    user_id, role = require_roles(["Applicant"])
    body = get_body()
    # Tier 5: body FK existence (also needed for the ownership check).
    application_id = req_str(body, "application_id")
    app = STORE["applications"].get(application_id)
    if app is None:
        raise api_err("ERR_APPLICATION_NOT_FOUND",
                      "No PermitApplication with id %s" % application_id)
    # Tier 4: ownership via the parent application.
    check_ownership(user_id, role, app["applicant_id"])
    # Tier 6: shape.
    avoidance_demonstrated = req_bool(body, "avoidance_demonstrated")
    avoidance_narrative = req_str(body, "avoidance_narrative")
    minimization_steps = req_str_list(body, "minimization_steps")
    ledpa_conclusion = req_enum(body, "ledpa_conclusion", LEDPA_CONCLUSIONS)
    offsite = req_int(body, "offsite_alternatives_considered", minimum=0)
    # Tier 7: the application must be in ALTERNATIVES_REVIEW.
    if app["status"] != "ALTERNATIVES_REVIEW":
        raise api_err("ERR_AA_INVALID_STATE",
                      "An alternatives analysis requires the application in "
                      "ALTERNATIVES_REVIEW")
    # Priority 24: at most one analysis per application.
    for existing in STORE["analyses"].values():
        if existing["application_id"] == app["id"]:
            raise api_err("ERR_AA_ALREADY_EXISTS",
                          "The application already has an alternatives "
                          "analysis")
    aa = new_entity({
        "application_id": app["id"],
        "avoidance_demonstrated": avoidance_demonstrated,
        "avoidance_narrative": avoidance_narrative,
        "minimization_steps": minimization_steps,
        "ledpa_conclusion": ledpa_conclusion,
        "offsite_alternatives_considered": offsite,
        "revision_count": 0,
        "status": "SUBMITTED",
    })
    STORE["analyses"][aa["id"]] = aa
    return success_obj(aa_out(aa), 201)


@bp.get("/wetland-permits/alternatives-analyses")
def list_aas():
    require_roles(list(ALL_ROLES))
    items = apply_filters(STORE["analyses"].values(), {
        "application_id": "application_id",
        "status": "status",
    })
    return list_response(items, aa_out)


@bp.get("/wetland-permits/alternatives-analyses/<id>")
def get_aa(id):
    require_roles(list(ALL_ROLES))
    return success_obj(aa_out(_get_aa_or_404(id)))


@bp.patch("/wetland-permits/alternatives-analyses/<id>")
def patch_aa(id):
    user_id, role = require_roles(["Applicant"])
    aa = _get_aa_or_404(id)
    app = STORE["applications"].get(aa["application_id"])
    # Tier 4: ownership via the parent application.
    check_ownership(user_id, role,
                    app["applicant_id"] if app else None)
    body = get_body()
    # Tier 6: validate provided fields.
    if "avoidance_demonstrated" in body \
            and body.get("avoidance_demonstrated") is not None:
        req_bool(body, "avoidance_demonstrated")
    if "avoidance_narrative" in body \
            and body.get("avoidance_narrative") is not None:
        req_str(body, "avoidance_narrative")
    if "minimization_steps" in body \
            and body.get("minimization_steps") is not None:
        req_str_list(body, "minimization_steps")
    if "ledpa_conclusion" in body \
            and body.get("ledpa_conclusion") is not None:
        opt_enum(body, "ledpa_conclusion", LEDPA_CONCLUSIONS)
    if "offsite_alternatives_considered" in body \
            and body.get("offsite_alternatives_considered") is not None:
        opt_int(body, "offsite_alternatives_considered", minimum=0)
    # Tier 7: revisable only from REVISION_REQUESTED.
    if aa["status"] != "REVISION_REQUESTED":
        raise api_err("ERR_AA_INVALID_STATE",
                      "Only a REVISION_REQUESTED analysis can be revised")
    if "avoidance_demonstrated" in body \
            and body.get("avoidance_demonstrated") is not None:
        aa["avoidance_demonstrated"] = body["avoidance_demonstrated"]
    if "avoidance_narrative" in body \
            and body.get("avoidance_narrative") is not None:
        aa["avoidance_narrative"] = body["avoidance_narrative"]
    if "minimization_steps" in body \
            and body.get("minimization_steps") is not None:
        aa["minimization_steps"] = body["minimization_steps"]
    if "ledpa_conclusion" in body \
            and body.get("ledpa_conclusion") is not None:
        aa["ledpa_conclusion"] = body["ledpa_conclusion"]
    if "offsite_alternatives_considered" in body \
            and body.get("offsite_alternatives_considered") is not None:
        aa["offsite_alternatives_considered"] = \
            body["offsite_alternatives_considered"]
    aa["status"] = "SUBMITTED"
    aa["revision_count"] += 1
    bump(aa)
    return success_obj(aa_out(aa))


@bp.post("/wetland-permits/alternatives-analyses/<id>/review")
def review_aa(id):
    require_roles(["Reviewer"])
    aa = _get_aa_or_404(id)
    body = get_body()
    verdict = req_enum(body, "verdict", AA_VERDICTS)
    opt_str(body, "revision_notes")
    # Tier 7: state.
    if aa["status"] != "SUBMITTED":
        raise api_err("ERR_AA_INVALID_STATE",
                      "Only a SUBMITTED analysis can be reviewed")
    if verdict == "ACCEPT":
        # Priority 16: the LEDPA gate — demonstrated avoidance, at least
        # two minimization steps, and a PROPOSED_IS_LEDPA conclusion.
        if not (aa["avoidance_demonstrated"] is True
                and len(aa["minimization_steps"]) >= 2
                and aa["ledpa_conclusion"] == "PROPOSED_IS_LEDPA"):
            raise api_err("ERR_LEDPA_NOT_DEMONSTRATED",
                          "Acceptance requires demonstrated avoidance, at "
                          "least two minimization steps, and a "
                          "PROPOSED_IS_LEDPA conclusion")
        aa["status"] = "ACCEPTED"
    elif verdict == "REQUEST_REVISION":
        aa["status"] = "REVISION_REQUESTED"
    else:  # REJECT
        aa["status"] = "REJECTED"
    bump(aa)
    return success_obj(aa_out(aa))


# ---------------------------------------------------------------------------
# Agency comments
# ---------------------------------------------------------------------------

@bp.post("/wetland-permits/agency-comments")
def create_comment():
    require_roles(["AgencyReviewer"])
    body = get_body()
    # Tier 5: body FK existence.
    application_id = req_str(body, "application_id")
    app = STORE["applications"].get(application_id)
    if app is None:
        raise api_err("ERR_APPLICATION_NOT_FOUND",
                      "No PermitApplication with id %s" % application_id)
    # Tier 6: shape.
    agency = req_enum(body, "agency", AGENCIES)
    comment_type = req_enum(body, "comment_type", COMMENT_TYPES)
    comment_text = req_str(body, "comment_text")
    # Priority 12: comments are fileable only while the notice is PUBLISHED.
    if app["notice_status"] != "PUBLISHED":
        raise api_err("ERR_COMMENT_PERIOD_CLOSED",
                      "Agency comments may be filed only while the notice "
                      "is PUBLISHED")
    comment = new_entity({
        "application_id": app["id"],
        "agency": agency,
        "comment_type": comment_type,
        "comment_text": comment_text,
        "filed_date": get_clock(),
        "resolution_text": None,
        "status": "FILED",
    })
    STORE["comments"][comment["id"]] = comment
    return success_obj(comment_out(comment), 201)


@bp.get("/wetland-permits/agency-comments")
def list_comments():
    require_roles(list(ALL_ROLES))
    items = apply_filters(STORE["comments"].values(), {
        "application_id": "application_id",
        "comment_type": "comment_type",
        "status": "status",
        "agency": "agency",
    })
    return list_response(items, comment_out)


@bp.get("/wetland-permits/agency-comments/<id>")
def get_comment(id):
    require_roles(list(ALL_ROLES))
    comment = STORE["comments"].get(id)
    if comment is None:
        raise api_err("ERR_COMMENT_NOT_FOUND",
                      "No AgencyComment with id %s" % id)
    return success_obj(comment_out(comment))


@bp.post("/wetland-permits/agency-comments/<id>/resolve")
def resolve_comment(id):
    require_roles(["Reviewer"])
    comment = STORE["comments"].get(id)
    if comment is None:
        raise api_err("ERR_COMMENT_NOT_FOUND",
                      "No AgencyComment with id %s" % id)
    body = get_body()
    resolution_text = req_str(body, "resolution_text")
    # Tier 7: state. The error catalog defines no comment-specific state
    # error, so a wrong-state resolve surfaces as ERR_INVALID_REQUEST
    # (INTERPRETATION — flagged in the generation report).
    if comment["status"] != "FILED":
        raise api_err("ERR_INVALID_REQUEST",
                      "Only a FILED comment can be resolved")
    comment["status"] = "RESOLVED"
    comment["resolution_text"] = resolution_text
    bump(comment)
    return success_obj(comment_out(comment))
