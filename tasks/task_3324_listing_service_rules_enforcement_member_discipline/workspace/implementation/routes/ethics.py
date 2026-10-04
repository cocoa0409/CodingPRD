"""Ethics case endpoints: file/list/get/screen/appeal/appeal-ruling + flat."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, require_member_actor
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_SCREENING_CONFLICT, ERR_SCREENING_OVERDUE,
                    ERR_APPEAL_WINDOW_CLOSED, ERR_APPEAL_CONFLICT,
                    ERR_CROSS_ASSOCIATION_REFERENCE)
from helpers import (body, mint_common, touch, now_iso_str, get_association,
                     get_ethics_case, page)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("ethics", __name__)

GRIEVANCE_REVIEW_DAYS = 45
APPEAL_WINDOW_DAYS = 20


def _filter_ethics(items):
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    resp = request.args.get("respondent_member_id")
    if resp is not None:
        items = [c for c in items if c["respondent_member_id"] == resp]
    comp = request.args.get("complainant_member_id")
    if comp is not None:
        items = [c for c in items if c["complainant_member_id"] == comp]
    return items


@bp.route("/mls/associations/<assoc_id>/ethics-cases", methods=["POST"])
def file_ethics_case(assoc_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("respondent_member_id", "article_code"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    respondent_id = data["respondent_member_id"]
    if respondent_id == user_id:
        raise_err(ERR_INVALID_REQUEST,
                  "respondent_member_id must differ from the complainant")
    complainant = store.members.get(user_id)
    respondent = store.members.get(respondent_id)
    if complainant is None or complainant["association_id"] != assoc_id \
       or respondent is None or respondent["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "Both parties must be members of the association")
    filed = now()
    case = {
        "association_id": assoc_id,
        "complainant_member_id": user_id,
        "respondent_member_id": respondent_id,
        "article_code": data["article_code"],
        "grievance_review_due_at": None,  # set below
        "screening_outcome": None,
        "filed_at": now_iso_str(),
        "status": "GRIEVANCE_SCREENING",  # FILED -> GRIEVANCE_SCREENING automatic
        "sanction_cents": 0,
    }
    mint_common(case)
    from db import _fmt_iso
    case["grievance_review_due_at"] = _fmt_iso(
        filed + timedelta(days=GRIEVANCE_REVIEW_DAYS))
    store.ethics_cases[case["id"]] = case
    return success_object(case, 201)


@bp.route("/mls/associations/<assoc_id>/ethics-cases", methods=["GET"])
def list_ethics_cases(assoc_id):
    require_roles("AssociationStaff", "GrievanceMember", "HearingPanelist", "Member")
    get_association(assoc_id)
    items = [c for c in store.ethics_cases.values()
             if c["association_id"] == assoc_id]
    items = _filter_ethics(items)
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/ethics-cases/<case_id>", methods=["GET"])
def get_ethics_case_route(assoc_id, case_id):
    require_roles("AssociationStaff", "GrievanceMember", "HearingPanelist", "Member")
    get_association(assoc_id)
    return success_object(get_ethics_case(case_id, assoc_id))


@bp.route("/mls/ethics-cases", methods=["GET"])
def flat_list_ethics_cases():
    require_roles("AssociationStaff", "GrievanceMember", "HearingPanelist", "Member")
    items = _filter_ethics(list(store.ethics_cases.values()))
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/ethics-cases/<case_id>", methods=["GET"])
def flat_get_ethics_case(case_id):
    require_roles("AssociationStaff", "GrievanceMember", "HearingPanelist", "Member")
    return success_object(get_ethics_case(case_id))


@bp.route("/mls/associations/<assoc_id>/ethics-cases/<case_id>/screen",
          methods=["POST"])
def screen_case(assoc_id, case_id):
    user_id, _ = require_roles("GrievanceMember")
    assoc = get_association(assoc_id)
    case = get_ethics_case(case_id, assoc_id)
    check_not_merged(assoc)
    if case["status"] != "GRIEVANCE_SCREENING":
        raise_err(ERR_INVALID_STATE,
                  "Only a case in GRIEVANCE_SCREENING may be screened")
    data = body()
    outcome = data.get("outcome")
    if outcome not in ("DISMISSED", "FORWARDED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be DISMISSED or FORWARDED")
    if user_id in (case["complainant_member_id"], case["respondent_member_id"]):
        raise_err(ERR_SCREENING_CONFLICT,
                  "Screener must be neither complainant nor respondent")
    if now() > _parse_iso(case["grievance_review_due_at"]):
        raise_err(ERR_SCREENING_OVERDUE,
                  "Screening attempted after grievance_review_due_at")
    case["screening_outcome"] = outcome
    case["status"] = "DISMISSED" if outcome == "DISMISSED" else "HEARING_SCHEDULED"
    touch(case)
    return success_object(case)


@bp.route("/mls/associations/<assoc_id>/ethics-cases/<case_id>/appeal",
          methods=["POST"])
def appeal_case(assoc_id, case_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    case = get_ethics_case(case_id, assoc_id)
    check_not_merged(assoc)
    if case["status"] != "DECIDED":
        raise_err(ERR_INVALID_STATE, "Only a DECIDED case may be appealed")
    require_member_actor(user_id, case["respondent_member_id"])
    # Appeal within 20 days of the linked panel's ruling instant.
    panel = None
    for p in store.hearing_panels.values():
        if p["case_type"] == "ETHICS" and p["case_id"] == case_id \
           and p["status"] == "DECIDED":
            panel = p
    if panel is None:
        raise_err(ERR_INVALID_STATE, "No decided panel found for this case")
    ruling_at = _parse_iso(panel["updated_at"])
    if now() > ruling_at + timedelta(days=APPEAL_WINDOW_DAYS):
        raise_err(ERR_APPEAL_WINDOW_CLOSED,
                  "Appeal filed after ruling + 20 days")
    case["status"] = "APPEALED"
    touch(case)
    return success_object(case)


@bp.route("/mls/associations/<assoc_id>/ethics-cases/<case_id>/appeal-ruling",
          methods=["POST"])
def appeal_ruling(assoc_id, case_id):
    user_id, _ = require_roles("GrievanceMember")
    assoc = get_association(assoc_id)
    case = get_ethics_case(case_id, assoc_id)
    check_not_merged(assoc)
    if case["status"] != "APPEALED":
        raise_err(ERR_INVALID_STATE, "Only an APPEALED case may be ruled on")
    conflict_ids = {case["complainant_member_id"], case["respondent_member_id"]}
    for p in store.hearing_panels.values():
        if p["case_type"] == "ETHICS" and p["case_id"] == case_id \
           and p["status"] == "DECIDED":
            conflict_ids.update(p.get("selected_member_ids") or [])
    if user_id in conflict_ids:
        raise_err(ERR_APPEAL_CONFLICT,
                  "Appeal ruling member must not be a party or original panelist")
    case["status"] = "FINAL"
    touch(case)
    return success_object(case)
