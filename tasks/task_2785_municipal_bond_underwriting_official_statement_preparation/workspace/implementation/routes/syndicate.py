"""Syndicate seats: MSRB Rule G-23 and the liability pot (PRD 3.5)."""
from decimal import Decimal

from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate, require_deal_ownership
from services import calc
from validation import dec, parse_body, query_value, spec

bp = Blueprint("syndicate", __name__)

MEMBER_ROLES = ["SENIOR_MANAGER", "CO_MANAGER", "SELLING_GROUP"]
PCT_WHOLE = Decimal("100.0000")

MEMBER_SPECS = [
    spec("firm_id", "string"),
    spec("member_role", "enum", values=MEMBER_ROLES),
    spec("liability_pct", "number", exclusive_minimum=0, maximum=100, max_decimals=4),
    spec("takedown_share_pct", "number", exclusive_minimum=0, maximum=100, max_decimals=4),
    spec("priority_rank", "integer", minimum=1, maximum=40),
]


@bp.route("/bond-offerings/deals/<deal_id>/syndicate-members", methods=["POST"])
def create_member(deal_id):
    actor = authenticate(["Underwriter", "MunicipalAdvisor"])
    deal = lookup.get_deal(deal_id)
    body = parse_body(MEMBER_SPECS)
    # tier 7: the firm being seated must exist
    firm = lookup.get_firm(body["firm_id"])
    # tier 8: actor ownership, with the unseated-underwriter carve-out
    require_deal_ownership(actor, deal, adding_firm_id=body["firm_id"])
    # tier 12: MSRB conduct
    if deal["municipal_advisor_firm_id"] == firm["id"]:
        raise ApiError("ERR_MA_UNDERWRITER_CONFLICT")
    if firm["is_suspended"]:
        raise ApiError("ERR_FIRM_SUSPENDED")
    # tier 15: the three uniqueness guards
    existing_members = lookup.members_of_deal(deal_id)
    for member in existing_members:
        if member["firm_id"] == firm["id"] and member["status"] != "RESIGNED":
            raise ApiError("ERR_DUPLICATE_SYNDICATE_MEMBER")
    if body["member_role"] == "SENIOR_MANAGER":
        for member in existing_members:
            if member["member_role"] == "SENIOR_MANAGER":
                raise ApiError("ERR_DUPLICATE_SYNDICATE_MEMBER")
    for member in existing_members:
        if member["status"] == "ACTIVE" and member["priority_rank"] == body["priority_rank"]:
            raise ApiError("ERR_DUPLICATE_SYNDICATE_MEMBER")
    # tier 16: neither running total may exceed the whole
    active = [member for member in existing_members if member["status"] == "ACTIVE"]
    liability_pct = dec(body["liability_pct"])
    takedown_share_pct = dec(body["takedown_share_pct"])
    liability_sum = sum((dec(member["liability_pct"]) for member in active), liability_pct)
    if liability_sum > PCT_WHOLE:
        raise ApiError("ERR_LIABILITY_PCT_SUM_INVALID")
    takedown_sum = sum(
        (dec(member["takedown_share_pct"]) for member in active), takedown_share_pct
    )
    if takedown_sum > PCT_WHOLE:
        raise ApiError("ERR_LIABILITY_PCT_SUM_INVALID")
    row = db.new_row(
        deal_id=deal_id,
        firm_id=firm["id"],
        member_role=body["member_role"],
        liability_pct=liability_pct,
        takedown_share_pct=takedown_share_pct,
        priority_rank=body["priority_rank"],
        status="ACTIVE",
        liability_par_usd=Decimal(0),
        takedown_credit_usd=Decimal(0),
    )
    # liability_par_usd is known as soon as the structure has been submitted.
    row["liability_par_usd"] = calc.liability_par(row, deal)
    db.db.members[row["id"]] = row
    return response.created(serializers.member(row))


@bp.route("/bond-offerings/deals/<deal_id>/syndicate-members", methods=["GET"])
def list_deal_members(deal_id):
    authenticate(ALL_ROLES)
    lookup.get_deal(deal_id)
    rows = lookup.members_of_deal(deal_id)
    member_role = query_value("member_role")
    if member_role is not None:
        rows = [row for row in rows if row["member_role"] == member_role]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.member)
