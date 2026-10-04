"""PermitApplication endpoints (PRD §3.3, §3.5, §3.7).

Covers create/list/get/PATCH plus the action endpoints submit, screening,
publish-notice, advance-to-decision, render-decision and withdraw, following
the validation pipeline order of PRD §2.8 (first failure wins).
"""

from decimal import Decimal

from flask import Blueprint

import calculations as calc
from cascades import compensation_cascade, issue_permit
from db import STORE, bump, get_clock, new_entity
from errors import api_err
from helpers import (get_body, opt_int, opt_str, parse_impacts, req_enum,
                     req_number, req_str, to_decimal)
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import application_out

bp = Blueprint("applications", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")
PATHWAYS = ("GENERAL", "INDIVIDUAL", "ATF_GENERAL", "ATF_INDIVIDUAL")
GENERAL_PERMIT_CODES = ("NWP-29", "NWP-39")
GENERAL_RESOURCE_TYPES = ("EMERGENT_MARSH", "STREAM")
WITHDRAWABLE_STATES = (
    "DRAFT", "SUBMITTED", "SCREENING", "RETURNED_TO_APPLICANT",
    "ALTERNATIVES_REVIEW", "PUBLIC_NOTICE_OPEN", "DECISION_PENDING",
    "SUSPENDED_PENDING_JD",
)
GP_IMPACT_LIMIT = Decimal("0.50")
CMR_THRESHOLD = Decimal("0.10")


def _get_app_or_404(app_id):
    app = STORE["applications"].get(app_id)
    if app is None:
        raise api_err("ERR_APPLICATION_NOT_FOUND",
                      "No PermitApplication with id %s" % app_id)
    return app


def _is_general(pathway):
    return pathway in ("GENERAL", "ATF_GENERAL")


def _is_atf(pathway):
    return pathway in ("ATF_GENERAL", "ATF_INDIVIDUAL")


def _check_body_fks(body):
    """Pipeline tier 5: every FK field present in the body must reference an
    existing entity. Returns (site, jd, case) with None for absent fields."""
    site = jd = case = None
    site_id = body.get("site_id")
    if site_id is not None and isinstance(site_id, str):
        site = STORE["sites"].get(site_id)
        if site is None:
            raise api_err("ERR_SITE_NOT_FOUND",
                          "No WatersSite with id %s" % site_id)
    jd_id = body.get("jd_id")
    if jd_id is not None and isinstance(jd_id, str):
        jd = STORE["jds"].get(jd_id)
        if jd is None:
            raise api_err("ERR_JD_NOT_FOUND",
                          "No JurisdictionalDetermination with id %s" % jd_id)
    case_id = body.get("enforcement_case_id")
    if case_id is not None and isinstance(case_id, str):
        case = STORE["cases"].get(case_id)
        if case is None:
            raise api_err("ERR_CASE_NOT_FOUND",
                          "No EnforcementCase with id %s" % case_id)
    return site, jd, case


def _check_general_permit_eligibility(general_permit_code, total_impact,
                                      impacts):
    """Priority 15: code in {NWP-29, NWP-39}, total impact <= 0.50 acres
    (exactly 0.50 eligible), every impact type in {EMERGENT_MARSH, STREAM}."""
    eligible = (
        general_permit_code in GENERAL_PERMIT_CODES
        and total_impact <= GP_IMPACT_LIMIT
        and all(line["resource_type"] in GENERAL_RESOURCE_TYPES
                for line in impacts)
    )
    if not eligible:
        raise api_err(
            "ERR_GENERAL_PERMIT_INELIGIBLE",
            "General-permit eligibility failed: code must be NWP-29 or "
            "NWP-39, total impact must be <= 0.50 acres, and impacts must "
            "be limited to EMERGENT_MARSH and STREAM")


def _check_atf_case_state(case):
    """Priority 21: linked case must be VIOLATION_CONFIRMED or
    RESOLUTION_PENDING."""
    if case is None or case["case_status"] not in (
            "VIOLATION_CONFIRMED", "RESOLUTION_PENDING"):
        raise api_err(
            "ERR_CASE_INVALID_STATE",
            "The linked enforcement case must be VIOLATION_CONFIRMED or "
            "RESOLUTION_PENDING")


def _derive(pathway, impacts):
    total = sum((line["impact_acres"] for line in impacts), Decimal("0"))
    is_atf = _is_atf(pathway)
    return total, is_atf, total > CMR_THRESHOLD


@bp.post("/wetland-permits/applications")
def create_application():
    user_id, role = require_roles(["Applicant"])
    body = get_body()
    # Tier 5: body FK existence (fields that are present).
    site, jd, case = _check_body_fks(body)
    # Tier 6: request shape.
    site_id = req_str(body, "site_id")
    jd_id = req_str(body, "jd_id")
    site = STORE["sites"][site_id]
    pathway = req_enum(body, "pathway", PATHWAYS)
    impacts = parse_impacts(body.get("impacts"), site["resource_types_present"])
    project_purpose = req_str(body, "project_purpose")
    estimated_cost = req_number(body, "estimated_cost_dollars",
                                minimum=Decimal("0"))
    is_atf = _is_atf(pathway)
    is_general = _is_general(pathway)
    if is_general:
        general_permit_code = req_str(body, "general_permit_code")
    else:
        general_permit_code = opt_str(body, "general_permit_code")
    if is_atf:
        enforcement_case_id = req_str(body, "enforcement_case_id")
        case = STORE["cases"].get(enforcement_case_id)
        if case is None:
            raise api_err("ERR_CASE_NOT_FOUND",
                          "No EnforcementCase with id %s"
                          % enforcement_case_id)
        # Tier 6: the case must name the same responsible applicant.
        if case["responsible_applicant_id"] != user_id:
            raise api_err(
                "ERR_INVALID_REQUEST",
                "enforcement_case_id must name a case whose "
                "responsible_applicant_id equals the creating applicant")
    else:
        enforcement_case_id = opt_str(body, "enforcement_case_id")
        if enforcement_case_id is not None:
            case = STORE["cases"].get(enforcement_case_id)
            if case is None:
                raise api_err("ERR_CASE_NOT_FOUND",
                              "No EnforcementCase with id %s"
                              % enforcement_case_id)
    total, is_atf, cmr = _derive(pathway, [
        {"resource_type": r, "impact_acres": a} for r, a in impacts])
    # Priority 15: general-permit eligibility is enforced at creation.
    if is_general:
        _check_general_permit_eligibility(general_permit_code, total, [
            {"resource_type": r} for r, _ in impacts])
    # Priority 21: ATF linkage integrity is enforced at creation.
    if is_atf:
        _check_atf_case_state(case)
    application = new_entity({
        "applicant_id": user_id,
        "site_id": site_id,
        "jd_id": jd_id,
        "pathway": pathway,
        "general_permit_code": general_permit_code,
        "impacts": [{"resource_type": r, "impact_acres": a}
                    for r, a in impacts],
        "total_impact_acres": total,
        "is_after_the_fact": is_atf,
        "enforcement_case_id": enforcement_case_id,
        "project_purpose": project_purpose,
        "estimated_cost_dollars": estimated_cost,
        "submitted_date": None,
        "screening_reviewer_id": None,
        "pir_score": None,
        "pir_outcome": None,
        "compensatory_mitigation_required": cmr,
        "notice_status": "NONE",
        "notice_published_date": None,
        "comment_period_days": None,
        "status": "DRAFT",
    })
    STORE["applications"][application["id"]] = application
    return success_obj(application_out(application), 201)


@bp.get("/wetland-permits/applications")
def list_applications():
    require_roles(list(ALL_ROLES))
    apps = apply_filters(STORE["applications"].values(), {
        "applicant_id": "applicant_id",
        "site_id": "site_id",
        "jd_id": "jd_id",
        "status": "status",
        "enforcement_case_id": "enforcement_case_id",
    })
    return list_response(apps, application_out)


@bp.get("/wetland-permits/applications/<id>")
def get_application(id):
    require_roles(list(ALL_ROLES))
    return success_obj(application_out(_get_app_or_404(id)))


@bp.patch("/wetland-permits/applications/<id>")
def patch_application(id):
    user_id, role = require_roles(["Applicant"])
    app = _get_app_or_404(id)
    check_ownership(user_id, role, app["applicant_id"])
    body = get_body()
    # Tier 5: provided FK fields must reference existing entities.
    site, jd, case = _check_body_fks(body)
    # Tier 6: shape — OCC field required, provided fields valid, merged
    # conditional fields satisfied.
    if "expected_application_version" not in body \
            or body.get("expected_application_version") is None:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field expected_application_version is required")
    expected = body["expected_application_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field expected_application_version must be an integer")

    new_site_id = body.get("site_id")
    if new_site_id is not None and not isinstance(new_site_id, str):
        raise api_err("ERR_INVALID_REQUEST", "Field site_id must be a string")
    new_jd_id = body.get("jd_id")
    if new_jd_id is not None and not isinstance(new_jd_id, str):
        raise api_err("ERR_INVALID_REQUEST", "Field jd_id must be a string")
    new_pathway = body.get("pathway")
    if new_pathway is not None and new_pathway not in PATHWAYS:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field pathway must be one of %s" % ", ".join(PATHWAYS))
    merged_site_id = new_site_id if new_site_id is not None else app["site_id"]
    merged_site = STORE["sites"][merged_site_id]
    if "impacts" in body and body.get("impacts") is not None:
        new_impacts = parse_impacts(body.get("impacts"),
                                    merged_site["resource_types_present"])
    else:
        new_impacts = None
    if "project_purpose" in body and body.get("project_purpose") is not None \
            and not isinstance(body["project_purpose"], str):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field project_purpose must be a string")
    if "estimated_cost_dollars" in body \
            and body.get("estimated_cost_dollars") is not None:
        new_cost = to_decimal(body["estimated_cost_dollars"],
                              "estimated_cost_dollars")
        if new_cost < 0:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field estimated_cost_dollars must be >= 0")
    merged_pathway = new_pathway if new_pathway is not None else app["pathway"]
    merged_code = body.get("general_permit_code", app["general_permit_code"])
    merged_case_id = body.get("enforcement_case_id",
                              app["enforcement_case_id"])
    if _is_general(merged_pathway) and merged_code is None:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field general_permit_code is required for general "
                      "permit pathways")
    if _is_atf(merged_pathway):
        if merged_case_id is None:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field enforcement_case_id is required for "
                          "after-the-fact pathways")
        merged_case = STORE["cases"].get(merged_case_id)
        if merged_case is None:
            raise api_err("ERR_CASE_NOT_FOUND",
                          "No EnforcementCase with id %s" % merged_case_id)
        if merged_case["responsible_applicant_id"] != user_id:
            raise api_err(
                "ERR_INVALID_REQUEST",
                "enforcement_case_id must name a case whose "
                "responsible_applicant_id equals the applicant")
    # Tier 7: state — editable while DRAFT or RETURNED_TO_APPLICANT.
    if app["status"] not in ("DRAFT", "RETURNED_TO_APPLICANT"):
        raise api_err("ERR_APPLICATION_INVALID_STATE",
                      "Applications may be edited only while DRAFT or "
                      "RETURNED_TO_APPLICANT")
    # Tier 8: optimistic concurrency.
    if expected != app["version"]:
        raise api_err("ERR_STALE_VERSION",
                      "expected_application_version does not match the "
                      "application's current version")
    # Apply the edit; status unchanged; computed fields recomputed.
    if new_site_id is not None:
        app["site_id"] = new_site_id
    if new_jd_id is not None:
        app["jd_id"] = new_jd_id
    if new_pathway is not None:
        app["pathway"] = new_pathway
    if new_impacts is not None:
        app["impacts"] = [{"resource_type": r, "impact_acres": a}
                          for r, a in new_impacts]
    if body.get("project_purpose") is not None:
        app["project_purpose"] = body["project_purpose"]
    if "estimated_cost_dollars" in body \
            and body.get("estimated_cost_dollars") is not None:
        app["estimated_cost_dollars"] = new_cost
    if "general_permit_code" in body:
        app["general_permit_code"] = body.get("general_permit_code")
    if "enforcement_case_id" in body:
        app["enforcement_case_id"] = body.get("enforcement_case_id")
    total, is_atf, cmr = _derive(app["pathway"], app["impacts"])
    app["total_impact_acres"] = total
    app["is_after_the_fact"] = is_atf
    app["compensatory_mitigation_required"] = cmr
    bump(app)
    return success_obj(application_out(app))


def _gp_impact_lines(app):
    return [{"resource_type": line["resource_type"]} for line in app["impacts"]]


@bp.post("/wetland-permits/applications/<id>/submit")
def submit_application(id):
    user_id, role = require_roles(["Applicant"])
    app = _get_app_or_404(id)
    check_ownership(user_id, role, app["applicant_id"])
    body = get_body()
    new_jd_id = body.get("new_jd_id")
    # Tier 5: new_jd_id, when present, must reference an existing JD.
    new_jd = None
    if new_jd_id is not None:
        if not isinstance(new_jd_id, str):
            raise api_err("ERR_INVALID_REQUEST",
                          "Field new_jd_id must be a string")
        new_jd = STORE["jds"].get(new_jd_id)
        if new_jd is None:
            raise api_err("ERR_JD_NOT_FOUND",
                          "No JurisdictionalDetermination with id %s"
                          % new_jd_id)
    # Tier 6: new_jd_id is a required conditional field when resubmitting
    # from SUSPENDED_PENDING_JD.
    if app["status"] == "SUSPENDED_PENDING_JD" and new_jd is None:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field new_jd_id is required when resubmitting from "
                      "SUSPENDED_PENDING_JD")
    # Tier 7: state — the application must be in a submittable state, and
    # the referenced JD must be ISSUED.
    if app["status"] not in ("DRAFT", "RETURNED_TO_APPLICANT",
                             "SUSPENDED_PENDING_JD"):
        raise api_err("ERR_APPLICATION_INVALID_STATE",
                      "Application cannot be submitted from status %s"
                      % app["status"])
    if app["status"] == "SUSPENDED_PENDING_JD":
        # The replacement JD must belong to the same site.
        if new_jd["site_id"] != app["site_id"]:
            raise api_err("ERR_JD_NOT_FOUND",
                          "new_jd_id does not reference a determination for "
                          "the application's site")
        ref_jd = new_jd
    else:
        ref_jd = STORE["jds"].get(app["jd_id"])
        if ref_jd is None:
            raise api_err("ERR_JD_NOT_FOUND",
                          "No JurisdictionalDetermination with id %s"
                          % app["jd_id"])
    if ref_jd["status"] != "ISSUED":
        raise api_err("ERR_JD_INVALID_STATE",
                      "The referenced determination is not ISSUED")
    # Priority 11: the referenced JD must be unexpired (expiry exactly at
    # the clock is still acceptable).
    clock = get_clock()
    if ref_jd["expiration_date"] is not None \
            and clock > ref_jd["expiration_date"]:
        raise api_err("ERR_JD_EXPIRED",
                      "The referenced determination has expired")
    # Priority 15: general-permit eligibility re-runs at submission.
    if _is_general(app["pathway"]):
        _check_general_permit_eligibility(
            app["general_permit_code"], app["total_impact_acres"],
            _gp_impact_lines(app))
    # Priority 18: the referenced JD must be JURISDICTIONAL.
    if ref_jd["determination"] != "JURISDICTIONAL":
        raise api_err("ERR_JD_NOT_JURISDICTIONAL",
                      "The referenced determination is NON_JURISDICTIONAL")
    # Priority 21: ATF linkage re-checked at submission.
    if app["is_after_the_fact"]:
        case = STORE["cases"].get(app["enforcement_case_id"])
        _check_atf_case_state(case)
    if app["status"] == "SUSPENDED_PENDING_JD":
        app["jd_id"] = new_jd["id"]
    app["submitted_date"] = clock
    app["status"] = "SUBMITTED"
    bump(app)
    return success_obj(application_out(app))


@bp.post("/wetland-permits/applications/<id>/screening")
def screening(id):
    user_id, role = require_roles(["Reviewer"])
    app = _get_app_or_404(id)
    body = get_body()
    action = req_enum(body, "action", ("BEGIN", "RETURN", "APPROVE"))
    opt_str(body, "return_reason")
    if action == "BEGIN":
        if app["status"] != "SUBMITTED":
            raise api_err("ERR_APPLICATION_INVALID_STATE",
                          "BEGIN requires status SUBMITTED")
        app["status"] = "SCREENING"
        app["screening_reviewer_id"] = user_id
    elif action == "RETURN":
        if app["status"] != "SCREENING":
            raise api_err("ERR_APPLICATION_INVALID_STATE",
                          "RETURN requires status SCREENING")
        app["status"] = "RETURNED_TO_APPLICANT"
    else:  # APPROVE
        if app["status"] != "SCREENING":
            raise api_err("ERR_APPLICATION_INVALID_STATE",
                          "APPROVE requires status SCREENING")
        if app["pathway"] in ("INDIVIDUAL", "ATF_INDIVIDUAL"):
            app["status"] = "ALTERNATIVES_REVIEW"
        else:
            # Streamlined general-permit path: skips alternatives review,
            # public notice, and the public interest review entirely.
            app["status"] = "DECISION_PENDING"
    bump(app)
    return success_obj(application_out(app))


@bp.post("/wetland-permits/applications/<id>/publish-notice")
def publish_notice(id):
    require_roles(["Reviewer"])
    app = _get_app_or_404(id)
    body = get_body()
    # Tier 6: comment_period_days must lie in 15..60 when supplied.
    comment_period_days = opt_int(body, "comment_period_days", default=None,
                                  minimum=15, maximum=60)
    # Tier 7: state.
    if app["status"] != "ALTERNATIVES_REVIEW":
        raise api_err("ERR_APPLICATION_INVALID_STATE",
                      "publish-notice requires status ALTERNATIVES_REVIEW")
    # Priority 19: the alternatives analysis must be ACCEPTED.
    accepted = any(aa["application_id"] == app["id"]
                   and aa["status"] == "ACCEPTED"
                   for aa in STORE["analyses"].values())
    if not accepted:
        raise api_err("ERR_AA_NOT_ACCEPTED",
                      "The alternatives analysis must be ACCEPTED before "
                      "the public notice is published")
    # Priority 24: at most one published notice per application.
    if app["notice_status"] != "NONE":
        raise api_err("ERR_NOTICE_ALREADY_PUBLISHED",
                      "The application's notice has already been published")
    app["status"] = "PUBLIC_NOTICE_OPEN"
    app["notice_status"] = "PUBLISHED"
    app["notice_published_date"] = get_clock()
    app["comment_period_days"] = comment_period_days if \
        comment_period_days is not None else 30
    bump(app)
    return success_obj(application_out(app))


@bp.post("/wetland-permits/applications/<id>/advance-to-decision")
def advance_to_decision(id):
    require_roles(["Reviewer"])
    app = _get_app_or_404(id)
    get_body()
    # Tier 7: state.
    if app["status"] != "PUBLIC_NOTICE_OPEN":
        raise api_err("ERR_APPLICATION_INVALID_STATE",
                      "advance-to-decision requires status PUBLIC_NOTICE_OPEN")
    # Priority 13: the comment period must have fully closed.
    if app["notice_status"] != "COMMENT_PERIOD_CLOSED":
        raise api_err("ERR_NOTICE_PERIOD_STILL_OPEN",
                      "The comment period has not fully elapsed")
    # Priority 20: no unresolved substantive objections.
    for comment in STORE["comments"].values():
        if comment["application_id"] == app["id"] \
                and comment["comment_type"] == "SUBSTANTIVE_OBJECTION" \
                and comment["status"] == "FILED":
            raise api_err("ERR_UNRESOLVED_AGENCY_OBJECTIONS",
                          "A substantive agency objection remains unresolved")
    score, outcome = calc.pir_score(app)
    app["pir_score"] = score
    app["pir_outcome"] = outcome
    app["status"] = "DECISION_PENDING"
    bump(app)
    return success_obj(application_out(app))


@bp.post("/wetland-permits/applications/<id>/render-decision")
def render_decision(id):
    user_id, role = require_roles(["DistrictEngineer"])
    app = _get_app_or_404(id)
    body = get_body()
    outcome = req_enum(body, "outcome", ("ISSUE", "DENY"))
    opt_str(body, "decision_rationale")
    # Tier 7: state.
    if app["status"] != "DECISION_PENDING":
        raise api_err("ERR_APPLICATION_INVALID_STATE",
                      "render-decision requires status DECISION_PENDING")
    # Priority 14: segregation of duties — the deciding engineer must not
    # be the reviewer who screened the application.
    if user_id == app["screening_reviewer_id"]:
        raise api_err("ERR_SEGREGATION_OF_DUTIES",
                      "The deciding engineer must differ from the screening "
                      "reviewer")
    if outcome == "ISSUE":
        # Priority 17: individual pathways need a favorable PIR.
        if app["pathway"] in ("INDIVIDUAL", "ATF_INDIVIDUAL") \
                and app["pir_outcome"] != "FAVORABLE":
            raise api_err("ERR_PUBLIC_INTEREST_UNFAVORABLE",
                          "The public interest review outcome is UNFAVORABLE")
        # Priority 21: ATF linkage at decision time.
        if app["is_after_the_fact"]:
            case = STORE["cases"].get(app["enforcement_case_id"])
            if case is None \
                    or case["resolution_track"] != "AFTER_THE_FACT_PERMIT" \
                    or case["atf_application_id"] != app["id"]:
                raise api_err("ERR_CASE_INVALID_STATE",
                              "The linked enforcement case must be on the "
                              "AFTER_THE_FACT_PERMIT track naming this "
                              "application")
        # Priority 30: secured mitigation when compensation is required.
        if app["compensatory_mitigation_required"]:
            secured = any(p["application_id"] == app["id"]
                          and p["status"] == "CREDITS_SECURED"
                          for p in STORE["plans"].values())
            if not secured:
                raise api_err("ERR_MITIGATION_NOT_SECURED",
                              "Compensatory mitigation is required but no "
                              "plan is CREDITS_SECURED")
        issue_permit(app)
        app["status"] = "ISSUED"
    else:
        compensation_cascade(app)
        app["status"] = "DENIED"
    bump(app)
    return success_obj(application_out(app))


@bp.post("/wetland-permits/applications/<id>/withdraw")
def withdraw_application(id):
    user_id, role = require_roles(["Applicant"])
    app = _get_app_or_404(id)
    check_ownership(user_id, role, app["applicant_id"])
    get_body()
    # Tier 7: withdraw is defined from every non-terminal pre-decision
    # state, including SUSPENDED_PENDING_JD.
    if app["status"] not in WITHDRAWABLE_STATES:
        raise api_err("ERR_APPLICATION_INVALID_STATE",
                      "Application cannot be withdrawn from status %s"
                      % app["status"])
    compensation_cascade(app)
    app["status"] = "WITHDRAWN"
    bump(app)
    return success_obj(application_out(app))
