"""Channel configuration, content policy and the surcharge structure (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import calc
import validators as v
from auth import (ALL_ROLES, ROLE_COMPLIANCE_AUDITOR, ROLE_DISTRIBUTION_MANAGER,
                  ROLE_PLATFORM_ADMIN, ROLE_PRICING_ANALYST, authenticate)
from envelope import paginate, pagination, respond_list, respond_object
from errors import ApiError
from serializers import channel_out, surcharge_rule_out
from store import bump, common_fields, db, get_or_404, immutable_fields
from services import surcharge_rules_for

bp = Blueprint("channels", __name__)

CHANNEL_KINDS = ("DIRECT", "NDC_AGGREGATOR", "GDS_LEGACY")
CONTENT_TIERS = ("FULL", "STANDARD", "RESTRICTED")
ITEM_SCOPES = ("FARE", "ANCILLARY", "ALL")


@bp.post("/channels")
def create_channel():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = v.json_body()
    channel_code = v.req_string(body, "channel_code", 1, 32)
    channel_kind = v.req_enum(body, "channel_kind", CHANNEL_KINDS)
    content_tier = v.opt_enum(body, "content_tier", CONTENT_TIERS, "STANDARD")
    content_markup_pct = v.opt_decimal(body, "content_markup_pct",
                                       Decimal(0), Decimal("0.25"), 4, Decimal(0))
    incentive_multiplier = v.opt_decimal(body, "incentive_multiplier",
                                         Decimal("1.0"), Decimal("2.0"), 2,
                                         Decimal("1.0"))
    monthly_platform_fee_cents = v.opt_int(body, "monthly_platform_fee_cents", 0, None, 0)
    per_message_cost_cents = v.opt_int(body, "per_message_cost_cents", 0, None, 0)
    per_segment_fee_cents = v.opt_int(body, "per_segment_fee_cents", 0, None, 0)
    servicing_parity_change = v.opt_bool(body, "servicing_parity_change", True)
    servicing_parity_refund = v.opt_bool(body, "servicing_parity_refund", True)
    required_disclosure_codes = v.opt_str_array(body, "required_disclosure_codes", [])

    for existing in db.channels.values():
        if existing["channel_code"] == channel_code:
            raise ApiError("ERR_DUPLICATE_CHANNEL_CODE",
                           "channel_code is already registered.")

    channel = common_fields()
    channel.update({
        "channel_code": channel_code,
        "channel_kind": channel_kind,
        "content_tier": content_tier,
        "content_tier_rank": calc.content_tier_rank(content_tier),
        "content_markup_pct": content_markup_pct,
        "incentive_multiplier": incentive_multiplier,
        "monthly_platform_fee_cents": monthly_platform_fee_cents,
        "per_message_cost_cents": per_message_cost_cents,
        "per_segment_fee_cents": per_segment_fee_cents,
        "servicing_parity_change": servicing_parity_change,
        "servicing_parity_refund": servicing_parity_refund,
        "required_disclosure_codes": required_disclosure_codes,
        "booking_count": 0,
        "activity_cost_cents": 0,
        "cost_per_booking_flat_cents": 0,
        "cost_per_booking_activity_cents": 0,
    })
    db.channels[channel["id"]] = channel
    return respond_object(channel_out(channel), 201)


@bp.get("/channels/<channel_id>")
def read_channel(channel_id):
    authenticate(ALL_ROLES)
    channel = get_or_404(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")
    return respond_object(channel_out(channel))


@bp.patch("/channels/<channel_id>/content-policy")
def revise_content_policy(channel_id):
    authenticate([ROLE_DISTRIBUTION_MANAGER])
    body = v.json_body()
    content_tier = v.opt_enum(body, "content_tier", CONTENT_TIERS)
    servicing_parity_change = v.opt_bool(body, "servicing_parity_change")
    servicing_parity_refund = v.opt_bool(body, "servicing_parity_refund")
    required_disclosure_codes = v.opt_str_array(body, "required_disclosure_codes")
    channel = get_or_404(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")

    if content_tier is not None:
        channel["content_tier"] = content_tier
        channel["content_tier_rank"] = calc.content_tier_rank(content_tier)
    if servicing_parity_change is not None:
        channel["servicing_parity_change"] = servicing_parity_change
    if servicing_parity_refund is not None:
        channel["servicing_parity_refund"] = servicing_parity_refund
    if required_disclosure_codes is not None:
        channel["required_disclosure_codes"] = required_disclosure_codes
    # Deliberately does not reprice or withdraw any existing offer.
    bump(channel)
    return respond_object(channel_out(channel))


@bp.post("/channels/<channel_id>/surcharge-rules")
def add_surcharge_rule(channel_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    body = v.json_body()
    surcharge_code = v.req_string(body, "surcharge_code", 1, 32)
    item_scope = v.req_enum(body, "item_scope", ITEM_SCOPES)
    rate_pct = v.req_decimal(body, "rate_pct", Decimal(0), Decimal("0.5"), 4,
                             lo_exclusive=True)
    threshold_cents = v.opt_int(body, "threshold_cents", 0, None, 0)
    min_cents = v.opt_int(body, "min_cents", 0, None, 0)
    max_cents = v.req_int(body, "max_cents", 0, None)
    if max_cents < min_cents:
        raise ApiError("ERR_INVALID_REQUEST", "max_cents must be >= min_cents.")
    channel = get_or_404(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")

    rule = immutable_fields()
    rule.update({
        "channel_id": channel["id"],
        "surcharge_code": surcharge_code,
        "item_scope": item_scope,
        "rate_pct": rate_pct,
        "threshold_cents": threshold_cents,
        "min_cents": min_cents,
        "max_cents": max_cents,
    })
    db.surcharge_rules[rule["id"]] = rule
    bump(channel)
    return respond_object(surcharge_rule_out(rule), 201)


@bp.get("/channels/<channel_id>/surcharge-rules")
def list_surcharge_rules(channel_id):
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_PRICING_ANALYST,
                  ROLE_DISTRIBUTION_MANAGER, ROLE_COMPLIANCE_AUDITOR])
    limit, offset = pagination()
    channel = get_or_404(db.channels, channel_id, "ERR_CHANNEL_NOT_FOUND")
    rules = surcharge_rules_for(channel["id"])
    page, total = paginate(rules, limit, offset)
    return respond_list([surcharge_rule_out(r) for r in page], limit, offset, total)
