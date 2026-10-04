"""Household member get/update/delete."""

from flask import Blueprint

from db import DB, CLOCK, touch
from errors import not_found, business, invalid_request, ERR_OPEN_SERVICE_CALLS
from middleware import require_auth
from response import ok_obj
from services.calculations import (
    NON_TERMINAL_CALL_STATES, household_proration_credit, tier_by_code,
)
from services.serialize import public
from services.validate import body_json, parse_iso_field

bp = Blueprint("household", __name__)

RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT", "OTHER"}


def _get_hm(memberId):
    h = DB.household_members.get(memberId)
    if h is None:
        raise not_found("household member not found")
    return h


@bp.get("/motor-club/household-members/<memberId>")
def get_household_member(memberId):
    require_auth({"MemberServicesRep", "Dispatcher"})
    return ok_obj(public(_get_hm(memberId)))


@bp.put("/motor-club/household-members/<memberId>")
def update_household_member(memberId):
    require_auth({"MemberServicesRep"})
    h = _get_hm(memberId)
    data = body_json()
    if "full_name" in data and data["full_name"] is not None:
        if not isinstance(data["full_name"], str) or not data["full_name"]:
            raise invalid_request("full_name must be a non-empty string")
        h["full_name"] = data["full_name"]
    if "relationship" in data and data["relationship"] is not None:
        if data["relationship"] not in RELATIONSHIPS:
            raise invalid_request("relationship must be SPOUSE, CHILD, PARENT or OTHER")
        h["relationship"] = data["relationship"]
    if "date_of_birth" in data and data["date_of_birth"] is not None:
        parse_iso_field(data["date_of_birth"], "date_of_birth")
        h["date_of_birth"] = data["date_of_birth"]
    touch(h)
    return ok_obj(public(h))


@bp.delete("/motor-club/household-members/<memberId>")
def remove_household_member(memberId):
    require_auth({"MemberServicesRep"})
    h = _get_hm(memberId)
    # non-terminal service-call guard
    for c in DB.service_calls.values():
        if c["requesting_member_id"] == h["id"] and c["status"] in NON_TERMINAL_CALL_STATES:
            raise business(ERR_OPEN_SERVICE_CALLS,
                           "household member has non-terminal service calls")
    if h["status"] == "ACTIVE":
        m = DB.memberships.get(h["membership_id"])
        if m is not None:
            tier = tier_by_code(m["tier_code"])
            if tier is not None:
                credit = household_proration_credit(m, tier, CLOCK.now())
                m["account_credit_cents"] += credit
                touch(m)
    h["status"] = "REMOVED"
    touch(h)
    return ok_obj(public(h))
