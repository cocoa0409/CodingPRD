"""Arbitration case endpoints: file/list/get/mediation-outcome + flat routes."""

from datetime import timedelta

from flask import Blueprint, request

import calcs
import services
from auth import require_roles
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_ARBITRATION_WINDOW_CLOSED,
                    ERR_CROSS_ASSOCIATION_REFERENCE)
from helpers import (body, mint_common, touch, now_iso_str, get_association,
                     get_arbitration_case, page)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("arbitration", __name__)

ARBITRATION_WINDOW_DAYS = 180


def _filter_arb(items):
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    resp = request.args.get("respondent_member_id")
    if resp is not None:
        items = [c for c in items if c["respondent_member_id"] == resp]
    comp = request.args.get("complainant_member_id")
    if comp is not None:
        items = [c for c in items if c["complainant_member_id"] == comp]
    listing_id = request.args.get("listing_id")
    if listing_id is not None:
        items = [c for c in items if c["listing_id"] == listing_id]
    return items


@bp.route("/mls/associations/<assoc_id>/arbitration-cases", methods=["POST"])
def file_arbitration_case(assoc_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("respondent_member_id", "listing_id", "claim_amount_cents"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    respondent_id = data["respondent_member_id"]
    if respondent_id == user_id:
        raise_err(ERR_INVALID_REQUEST,
                  "respondent_member_id must differ from the complainant")
    claim = data["claim_amount_cents"]
    if isinstance(claim, bool) or not isinstance(claim, int) or claim <= 0:
        raise_err(ERR_INVALID_REQUEST, "claim_amount_cents must be an integer > 0")
    complainant = store.members.get(user_id)
    respondent = store.members.get(respondent_id)
    if complainant is None or complainant["association_id"] != assoc_id \
       or respondent is None or respondent["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "Both parties must be members of the association")
    listing = store.listings.get(data["listing_id"])
    if listing is None:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "listing_id does not reference an existing listing")
    office = store.offices.get(listing["office_id"])
    if office is None or office["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "listing_id references a listing of another association")
    if listing["status"] != "SOLD":
        raise_err(ERR_INVALID_STATE,
                  "Arbitration requires the listing to be SOLD")
    # Filing window: closing date + 180 days. The closing date is the
    # business_effective_at of the PENDING -> SOLD status change (falling back
    # to the change's recorded_at).
    closing = None
    for sc in store.status_changes.values():
        if sc["listing_id"] == listing["id"] and sc["to_status"] == "SOLD":
            closing = _parse_iso(sc.get("business_effective_at")
                                 or sc["recorded_at"])
    if closing is None:
        closing = _parse_iso(listing.get("status_changed_at")
                             or listing["created_at"])
    if now() > closing + timedelta(days=ARBITRATION_WINDOW_DAYS):
        raise_err(ERR_ARBITRATION_WINDOW_CLOSED,
                  "Arbitration filed after listing closing + 180 days")
    case = {
        "association_id": assoc_id,
        "complainant_member_id": user_id,
        "respondent_member_id": respondent_id,
        "listing_id": listing["id"],
        "claim_amount_cents": claim,
        "filed_at": now_iso_str(),
        "status": "MEDIATION_OFFERED",  # FILED -> MEDIATION_OFFERED automatic
        "award_amount_cents": 0,
        "procuring_cause_factor_scores": {},
    }
    mint_common(case)
    store.arbitration_cases[case["id"]] = case
    # Exclusion lists change when a new arbitration case names parties.
    calcs.refresh_exclusions_for_association(assoc_id)
    return success_object(case, 201)


@bp.route("/mls/associations/<assoc_id>/arbitration-cases", methods=["GET"])
def list_arbitration_cases(assoc_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    get_association(assoc_id)
    items = [c for c in store.arbitration_cases.values()
             if c["association_id"] == assoc_id]
    items = _filter_arb(items)
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/arbitration-cases/<case_id>",
          methods=["GET"])
def get_arbitration_case_route(assoc_id, case_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    get_association(assoc_id)
    return success_object(get_arbitration_case(case_id, assoc_id))


@bp.route("/mls/arbitration-cases", methods=["GET"])
def flat_list_arbitration_cases():
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    items = _filter_arb(list(store.arbitration_cases.values()))
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/arbitration-cases/<case_id>", methods=["GET"])
def flat_get_arbitration_case(case_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    return success_object(get_arbitration_case(case_id))


@bp.route("/mls/associations/<assoc_id>/arbitration-cases/<case_id>/mediation-outcome",
          methods=["POST"])
def mediation_outcome(assoc_id, case_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    case = get_arbitration_case(case_id, assoc_id)
    check_not_merged(assoc)
    if case["status"] != "MEDIATION_OFFERED":
        raise_err(ERR_INVALID_STATE,
                  "Only a case in MEDIATION_OFFERED may record a mediation outcome")
    data = body()
    outcome = data.get("outcome")
    if outcome not in ("SETTLED", "DECLINED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be SETTLED or DECLINED")
    case["status"] = "MEDIATED" if outcome == "SETTLED" else "ARBITRATION_SCHEDULED"
    touch(case)
    return success_object(case)
