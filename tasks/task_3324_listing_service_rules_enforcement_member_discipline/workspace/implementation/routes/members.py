"""Member endpoints: register/list/get/terminate/credit-adjustments."""

from datetime import timedelta

from flask import Blueprint, request

import calcs
import services
from auth import require_roles
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
                    ERR_ASSOCIATION_MERGED, ERR_INVALID_STATE,
                    ERR_CREDIT_CAP_EXCEEDED)
from helpers import (body, mint_common, touch, get_association, get_member, page)
from response import success_object, success_list

bp = Blueprint("members", __name__)

TERMINATE_MIN_SUSPENDED_DAYS = 90


def check_not_merged(assoc):
    if assoc["consolidation_state"] == "MERGED":
        raise_err(ERR_ASSOCIATION_MERGED,
                  "Association is MERGED; mutations are rejected")


@bp.route("/mls/associations/<assoc_id>/members", methods=["POST"])
def create_member(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("member_nr", "full_name"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    for m in store.members.values():
        if m["association_id"] == assoc_id and m["member_nr"] == data["member_nr"]:
            raise_err(ERR_DUPLICATE_RESOURCE,
                      "member_nr '%s' already exists in this association"
                      % data["member_nr"])
    member = {
        "association_id": assoc_id,
        "member_nr": data["member_nr"],
        "full_name": data["full_name"],
        "membership_state": "ACTIVE",
        "mls_access_state": "ENABLED",
        "sanction_credit_balance_cents": 0,
        "strikes_12m": 0,
        "hearing_panel_exclusions": [],
    }
    mint_common(member)
    store.members[member["id"]] = member
    calcs.refresh_exclusions_for_association(assoc_id)
    return success_object(member, 201)


@bp.route("/mls/associations/<assoc_id>/members", methods=["GET"])
def list_members(assoc_id):
    require_roles("AssociationStaff", "GrievanceMember", "HearingPanelist", "Member")
    get_association(assoc_id)
    items = [m for m in store.members.values() if m["association_id"] == assoc_id]
    state = request.args.get("membership_state")
    if state is not None:
        items = [m for m in items if m["membership_state"] == state]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/members/<member_id>", methods=["GET"])
def get_member_route(assoc_id, member_id):
    require_roles("AssociationStaff", "Member", "GrievanceMember", "HearingPanelist")
    get_association(assoc_id)
    return success_object(get_member(member_id, assoc_id))


@bp.route("/mls/associations/<assoc_id>/members/<member_id>/terminate",
          methods=["POST"])
def terminate_member_route(assoc_id, member_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    member = get_member(member_id, assoc_id)
    check_not_merged(assoc)
    if member["membership_state"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE,
                  "Only a SUSPENDED member may be terminated")
    # >= 90 consecutive days measured from the grace_end_date of the dues
    # period whose lapse triggered the suspension.
    susp = store.suspensions.get(member_id)
    if susp is not None and susp.get("trigger_grace_end_date") is not None:
        start = susp["trigger_grace_end_date"]
    elif susp is not None:
        start = susp["suspended_at"]
    else:
        # Fallback: member suspended before tracking existed
        start = _parse_iso(member["updated_at"])
    if now() - start < timedelta(days=TERMINATE_MIN_SUSPENDED_DAYS):
        raise_err(ERR_INVALID_STATE,
                  "Member has not been SUSPENDED for >= 90 days")
    services.terminate_member(member)
    return success_object(member)


@bp.route("/mls/associations/<assoc_id>/members/<member_id>/credit-adjustments",
          methods=["POST"])
def credit_adjustment(assoc_id, member_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    member = get_member(member_id, assoc_id)
    check_not_merged(assoc)
    data = body()
    if data.get("amount_cents") is None or data.get("note") is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field(s) 'amount_cents', 'note'")
    amount = data["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer >= 0")
    if not isinstance(data["note"], str) or not data["note"]:
        raise_err(ERR_INVALID_REQUEST, "note must be a non-empty string")
    new_balance = member["sanction_credit_balance_cents"] + amount
    if new_balance > assoc["sanction_credit_cap_cents"]:
        raise_err(ERR_CREDIT_CAP_EXCEEDED,
                  "Credit adjustment would exceed the association cap")
    member["sanction_credit_balance_cents"] = new_balance
    touch(member)
    return success_object(member, 201)
