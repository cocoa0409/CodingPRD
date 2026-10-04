"""Hearing panel endpoints: convene/list/get/hold-hearing/rule + flat read."""

from flask import Blueprint, request

import calcs
import services
from auth import require_roles
from db import store, now
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_FORBIDDEN, ERR_PANEL_SOLE_ACTOR,
                    ERR_CREDIT_CAP_EXCEEDED, ERR_FACTOR_SCORE_INVALID,
                    ERR_CROSS_ASSOCIATION_REFERENCE)
from helpers import (body, mint_common, touch, now_iso_str, get_association,
                     get_panel, get_citation, get_ethics_case,
                     get_arbitration_case, page)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("panels", __name__)

CASE_TYPES = ("CITATION", "ETHICS", "ARBITRATION")
# Expected source states of the linked case at convene time.
CONVENE_CASE_STATES = {
    "CITATION": "HEARING_PENDING",
    "ETHICS": "HEARING_SCHEDULED",
    "ARBITRATION": "ARBITRATION_SCHEDULED",
}


@bp.route("/mls/associations/<assoc_id>/hearing-panels", methods=["POST"])
def convene_panel(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("case_type", "case_id"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    case_type = data["case_type"]
    if case_type not in CASE_TYPES:
        raise_err(ERR_INVALID_REQUEST, "case_type must be one of %s"
                  % ", ".join(CASE_TYPES))
    if case_type == "CITATION":
        case = store.citations.get(data["case_id"])
    elif case_type == "ETHICS":
        case = store.ethics_cases.get(data["case_id"])
    else:
        case = store.arbitration_cases.get(data["case_id"])
    if case is None or case["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "case_id must resolve under case_type within the association")
    if case["status"] != CONVENE_CASE_STATES[case_type]:
        raise_err(ERR_INVALID_STATE,
                  "Case is not in a state that can be convened (%s required)"
                  % CONVENE_CASE_STATES[case_type])
    calcs.refresh_exclusions_for_association(assoc_id)
    selected = calcs.select_panel_members(assoc_id, case_type, case)
    panel = {
        "association_id": assoc_id,
        "case_type": case_type,
        "case_id": case["id"],
        "selected_member_ids": selected,
        "convene_at": now_iso_str(),
        "decision": None,
        "status": "CONVENED",
        "_hold_actor": None,  # internal: panelist who held the hearing
    }
    mint_common(panel)
    store.hearing_panels[panel["id"]] = panel
    return success_object(panel, 201)


@bp.route("/mls/associations/<assoc_id>/hearing-panels", methods=["GET"])
def list_panels(assoc_id):
    require_roles("AssociationStaff", "HearingPanelist", "GrievanceMember")
    get_association(assoc_id)
    items = [p for p in store.hearing_panels.values()
             if p["association_id"] == assoc_id]
    case_type = request.args.get("case_type")
    if case_type is not None:
        items = [p for p in items if p["case_type"] == case_type]
    case_id = request.args.get("case_id")
    if case_id is not None:
        items = [p for p in items if p["case_id"] == case_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items, limit, offset, total = page(items)
    return success_list([_public(p) for p in items], limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/hearing-panels/<panel_id>",
          methods=["GET"])
def get_panel_route(assoc_id, panel_id):
    require_roles("AssociationStaff", "HearingPanelist", "GrievanceMember")
    get_association(assoc_id)
    return success_object(_public(get_panel(panel_id, assoc_id)))


@bp.route("/mls/hearing-panels/<panel_id>", methods=["GET"])
def flat_get_panel(panel_id):
    require_roles("AssociationStaff", "HearingPanelist", "GrievanceMember")
    return success_object(_public(get_panel(panel_id)))


def _public(panel):
    """Strip internal bookkeeping fields from the panel representation."""
    return {k: v for k, v in panel.items() if not k.startswith("_")}


@bp.route("/mls/associations/<assoc_id>/hearing-panels/<panel_id>/hold-hearing",
          methods=["POST"])
def hold_hearing(assoc_id, panel_id):
    user_id, _ = require_roles("HearingPanelist")
    assoc = get_association(assoc_id)
    panel = get_panel(panel_id, assoc_id)
    check_not_merged(assoc)
    if panel["status"] != "CONVENED":
        raise_err(ERR_INVALID_STATE, "Only a CONVENED panel may hold a hearing")
    if user_id not in panel["selected_member_ids"]:
        raise_err(ERR_FORBIDDEN,
                  "Only a seated panelist may hold the hearing")
    data = body()
    if panel["case_type"] == "ARBITRATION":
        factor_scores = data.get("factor_scores")
        if not isinstance(factor_scores, dict):
            raise_err(ERR_FACTOR_SCORE_INVALID,
                      "Arbitration hold-hearing requires factor_scores")
        for key in calcs.FACTOR_KEYS:
            if key not in factor_scores:
                raise_err(ERR_FACTOR_SCORE_INVALID,
                          "Missing factor key %s" % key)
            v = factor_scores[key]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 10:
                raise_err(ERR_FACTOR_SCORE_INVALID,
                          "Factor %s must be an integer 0..10" % key)
        case = store.arbitration_cases[panel["case_id"]]
        case["procuring_cause_factor_scores"] = {
            k: int(factor_scores[k]) for k in calcs.FACTOR_KEYS}
        touch(case)

    panel["status"] = "HEARING_HELD"
    panel["_hold_actor"] = user_id
    touch(panel)

    # Advance the linked case: ethics/arbitration -> HEARD; citation stays.
    if panel["case_type"] == "ETHICS":
        case = store.ethics_cases[panel["case_id"]]
        if case["status"] == "HEARING_SCHEDULED":
            case["status"] = "HEARD"
            touch(case)
    elif panel["case_type"] == "ARBITRATION":
        case = store.arbitration_cases[panel["case_id"]]
        if case["status"] == "ARBITRATION_SCHEDULED":
            case["status"] = "HEARD"
            touch(case)
    return success_object(_public(panel))


@bp.route("/mls/associations/<assoc_id>/hearing-panels/<panel_id>/rule",
          methods=["POST"])
def rule_panel(assoc_id, panel_id):
    user_id, _ = require_roles("HearingPanelist")
    assoc = get_association(assoc_id)
    panel = get_panel(panel_id, assoc_id)
    check_not_merged(assoc)
    if panel["status"] != "HEARING_HELD":
        raise_err(ERR_INVALID_STATE, "Only a HEARING_HELD panel may rule")
    if user_id not in panel["selected_member_ids"]:
        raise_err(ERR_FORBIDDEN, "Only a seated panelist may rule")
    if panel.get("_hold_actor") == user_id:
        raise_err(ERR_PANEL_SOLE_ACTOR,
                  "The panelist who held the hearing must not rule")
    data = body()
    decision = data.get("decision")
    if decision not in ("UPHOLD", "OVERTURN"):
        raise_err(ERR_INVALID_REQUEST, "decision must be UPHOLD or OVERTURN")

    # CITATION uphold branch runs the credit-cap check BEFORE any state
    # change; on overflow the ruling is rejected and nothing changes.
    citation = None
    cited_member = None
    if panel["case_type"] == "CITATION":
        citation = store.citations[panel["case_id"]]
        cited_member = store.members[citation["member_id"]]
        if decision == "UPHOLD":
            calcs.recompute_strikes(cited_member)
            if cited_member["strikes_12m"] < calcs.ESCALATION_THRESHOLD:
                if cited_member["sanction_credit_balance_cents"] \
                   + citation["fine_amount_cents"] \
                   > assoc["sanction_credit_cap_cents"]:
                    raise_err(ERR_CREDIT_CAP_EXCEEDED,
                              "Crediting the fine would exceed the association cap")

    panel["decision"] = decision
    panel["status"] = "DECIDED"
    touch(panel)

    if panel["case_type"] == "CITATION":
        _rule_citation(assoc, citation, cited_member, decision)
    elif panel["case_type"] == "ETHICS":
        _rule_ethics(assoc, panel, decision)
    else:
        _rule_arbitration(panel, decision)
    return success_object(_public(panel))


def _rule_citation(assoc, citation, member, decision):
    if decision == "OVERTURN":
        citation["status"] = "WAIVED"
        touch(citation)
        services.listing_unflag_chain(citation)
        return
    # UPHOLD: branch on live strikes_12m at ruling time.
    calcs.recompute_strikes(member)
    if member["strikes_12m"] >= calcs.ESCALATION_THRESHOLD:
        citation["status"] = "ESCALATED"
        touch(citation)
        services.listing_unflag_chain(citation)
        return
    citation["status"] = "PAID"
    touch(citation)
    services.credit_member_for_paid_citation(member, citation)


def _rule_ethics(assoc, panel, decision):
    case = store.ethics_cases[panel["case_id"]]
    if decision == "UPHOLD":
        respondent = store.members[case["respondent_member_id"]]
        case["sanction_cents"] = calcs.ethics_sanction_amount(
            respondent["strikes_12m"])
        # Sanction is fine-only: never credits. Recompute strikes (sanction
        # itself adds no strike); if respondent reaches >= 3, suspend.
        calcs.recompute_strikes(respondent)
        touch(respondent)
        if respondent["strikes_12m"] >= calcs.ESCALATION_THRESHOLD:
            services.suspend_member(respondent)
    case["status"] = "DECIDED"
    touch(case)


def _rule_arbitration(panel, decision):
    case = store.arbitration_cases[panel["case_id"]]
    if decision == "UPHOLD":
        case["award_amount_cents"] = calcs.procuring_cause_award(
            case["claim_amount_cents"], case["procuring_cause_factor_scores"])
    else:
        case["award_amount_cents"] = 0
    case["status"] = "AWARDED"
    touch(case)
