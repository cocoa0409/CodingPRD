"""Agency incentive agreements and the negotiation cycle (PRD 3.3)."""
from decimal import Decimal

from flask import Blueprint

import calc
import validators as v
from auth import (ALL_ROLES, ROLE_AGENCY, ROLE_COMPLIANCE_AUDITOR,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_PLATFORM_ADMIN, authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from routing import resolve_owned
from serializers import agreement_out
from store import bump, common_fields, db, sort_key

bp = Blueprint("agreements", __name__)

AGREEMENT_STATES = ("PROPOSED", "COUNTERED", "SIGNED", "SUSPENDED",
                    "WITHDRAWN", "SUPERSEDED")
NEGOTIATION_ACTIONS = ("COUNTER", "PROPOSE", "ACCEPT", "WITHDRAW")
SUPERSEDABLE = ("PROPOSED", "COUNTERED", "SIGNED")


@bp.post("/agency-agreements")
def open_agreement():
    actor = authenticate([ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    partner_id = v.req_string(body, "partner_id", 1, None)
    channel_id = v.req_string(body, "channel_id", 1, None)
    proposed_incentive_pct = v.req_decimal(body, "proposed_incentive_pct",
                                          Decimal(0), Decimal("0.15"), 4,
                                          lo_exclusive=True)
    incentive_cap_cents = v.req_int(body, "incentive_cap_cents", 1, None)
    target_net_revenue_cents = v.req_int(body, "target_net_revenue_cents", 1, None)
    expected_partner_version = v.req_int(body, "expected_partner_version", 1, None)

    partner = db.partners.get(partner_id)
    if partner is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND", "partner_id does not resolve.")
    channel = db.channels.get(channel_id)
    if channel is None:
        raise ApiError("ERR_CHANNEL_NOT_FOUND", "channel_id does not resolve.")

    if expected_partner_version != partner["version"]:
        raise ApiError("ERR_STALE_PARTNER_VERSION",
                       "expected_partner_version does not match the partner.")
    if partner["partner_type"] != "TRAVEL_AGENCY":
        raise ApiError("ERR_PARTNER_TYPE_NOT_ELIGIBLE",
                       "Only a TRAVEL_AGENCY may hold an incentive agreement.")

    # Opening an agreement supersedes the pair's live agreements.
    for existing in sorted(db.agreements.values(), key=sort_key):
        if (existing["partner_id"] == partner["id"]
                and existing["channel_id"] == channel["id"]
                and existing["status"] in SUPERSEDABLE):
            existing["status"] = "SUPERSEDED"
            bump(existing)

    agreement = common_fields()
    agreement.update({
        "partner_id": partner["id"],
        "channel_id": channel["id"],
        "proposed_incentive_pct": proposed_incentive_pct,
        "agreed_incentive_pct": None,
        "incentive_cap_cents": incentive_cap_cents,
        "target_net_revenue_cents": target_net_revenue_cents,
        "cumulative_net_revenue_cents": 0,
        "incentive_accrued_cents": 0,
        "incentive_tier": "TIER_1",
        "tier_downgrade_count": 0,
        "negotiation_round": 0,
        "proposed_by_user_id": actor.user_id,
        "signed_by_user_id": None,
        "status": "PROPOSED",
    })
    db.agreements[agreement["id"]] = agreement
    bump(partner)
    return respond_object(agreement_out(agreement), 201)


@bp.get("/agency-agreements/<agreement_id>")
def read_agreement(agreement_id):
    actor = authenticate(ALL_ROLES)
    pending, agreement = resolve_owned(db.agreements, agreement_id,
                                       "ERR_AGREEMENT_NOT_FOUND", actor)
    pending.raise_if_missing()
    return respond_object(agreement_out(agreement))


@bp.get("/agency-agreements")
def list_agreements():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_COMPLIANCE_AUDITOR, ROLE_AGENCY])
    limit, offset = pagination()
    partner_id = v.query_string("partner_id")
    channel_id = v.query_string("channel_id")
    status = v.query_enum("status", AGREEMENT_STATES)

    rows = []
    for agreement in db.agreements.values():
        if partner_id is not None and agreement["partner_id"] != partner_id:
            continue
        if channel_id is not None and agreement["channel_id"] != channel_id:
            continue
        if status is not None and agreement["status"] != status:
            continue
        rows.append(agreement)
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return respond_list([agreement_out(a) for a in page], limit, offset, total)


@bp.post("/agency-agreements/<agreement_id>/negotiation-rounds")
def record_negotiation_round(agreement_id):
    actor = authenticate([ROLE_DISTRIBUTION_MANAGER, ROLE_AGENCY])
    pending, agreement = resolve_owned(db.agreements, agreement_id,
                                       "ERR_AGREEMENT_NOT_FOUND", actor)
    body = v.json_body()
    action = v.req_enum(body, "action", NEGOTIATION_ACTIONS)
    proposed_incentive_pct = v.opt_decimal(body, "proposed_incentive_pct",
                                           Decimal(0), Decimal("0.15"), 4, None,
                                           lo_exclusive=True)
    v.opt_string(body, "note", 0, 2000)
    pending.raise_if_missing()

    # The counter is the agency's move; every other action is the airline's.
    if action == "COUNTER" and actor.role != ROLE_AGENCY:
        raise ApiError("ERR_UNAUTHORIZED", "Only the Agency may counter.")
    if action != "COUNTER" and actor.role != ROLE_DISTRIBUTION_MANAGER:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only a DistributionManager may perform %s." % action)

    status = agreement["status"]
    legal = {
        "COUNTER": ("PROPOSED",),
        "PROPOSE": ("COUNTERED",),
        "ACCEPT": ("PROPOSED",),
        "WITHDRAW": ("PROPOSED", "COUNTERED"),
    }[action]
    if status not in legal:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s is not legal from %s." % (action, status))

    if action == "ACCEPT" and actor.user_id == agreement["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The proposer may not accept its own proposal.")

    if action == "COUNTER" and agreement["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT",
                       "The agreement has exhausted its counter rounds.")
    if action == "PROPOSE" and agreement["negotiation_round"] > calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT",
                       "The agreement has exhausted its negotiation rounds.")

    if action == "COUNTER":
        agreement["negotiation_round"] = agreement["negotiation_round"] + 1
        agreement["status"] = "COUNTERED"
        if proposed_incentive_pct is not None:
            agreement["proposed_incentive_pct"] = proposed_incentive_pct
    elif action == "PROPOSE":
        agreement["status"] = "PROPOSED"
        agreement["proposed_by_user_id"] = actor.user_id
        if proposed_incentive_pct is not None:
            agreement["proposed_incentive_pct"] = proposed_incentive_pct
    elif action == "ACCEPT":
        agreement["status"] = "SIGNED"
        agreement["agreed_incentive_pct"] = agreement["proposed_incentive_pct"]
        agreement["signed_by_user_id"] = actor.user_id
    else:
        agreement["status"] = "WITHDRAWN"
    bump(agreement)
    return respond_object(agreement_out(agreement))
