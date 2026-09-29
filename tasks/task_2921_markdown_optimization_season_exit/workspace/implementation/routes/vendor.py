"""Vendor allowance negotiation and claim recognition (PRD 3.8)."""

from flask import Blueprint

from common import r2
from db import db, new_row, touch
from errors import ApiError
from middleware import (ROLE_CONTROLLER, ROLE_MERCHANDISE_DIRECTOR,
                        ROLE_PRICING_ANALYST, ROLE_VENDOR_REP, body, endpoint)
from response import created, ok
from serializers import agreement_json, claim_json
from services import calc, lookup
from services.lifecycle import claims_of_agreement, recompute_plan

bp = Blueprint("vendor", __name__)


@endpoint(bp, "/allowance-agreements", ["POST"], (ROLE_PRICING_ANALYST,))
def create_agreement(user_id, role):
    from validation import req_enum, req_int, req_num, req_str
    payload = body()
    season_id = req_str(payload, "season_id")
    vendor_code = req_str(payload, "vendor_code", min_len=1, max_len=64)
    scope = req_enum(payload, "item_category_scope", calc.CATEGORIES)
    share_pct = req_num(payload, "current_share_pct",
                        minimum="0.01", maximum="100.00")
    cap_cents = req_int(payload, "current_cap_cents", minimum=1)

    season = lookup.season(season_id)
    lookup.gate_not_closed(season)

    agreement = new_row(
        season_id=season["id"],
        vendor_code=vendor_code,
        item_category_scope=scope,
        current_share_pct=r2(share_pct),
        current_cap_cents=cap_cents,
        agreed_share_pct=None,
        funding_cap_cents=None,
        remaining_cap_cents=None,
        recognized_total_cents=0,
        round_index=1,
        last_offer_by_role=ROLE_PRICING_ANALYST,
        last_offer_by_user_id=user_id,
        status="PROPOSED",
    )
    db.insert("agreements", agreement)
    return created(agreement_json(agreement))


@endpoint(bp, "/allowance-agreements/<agreement_id>/counter", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_VENDOR_REP))
def counter_agreement(user_id, role, agreement_id):
    from validation import req_int, req_num
    payload = body()
    share_pct = req_num(payload, "share_pct", minimum="0.01", maximum="100.00")
    cap_cents = req_int(payload, "cap_cents", minimum=1)
    agreement = lookup.agreement(agreement_id)

    if role == ROLE_VENDOR_REP:
        if agreement["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE",
                           "A VendorRep counters an agreement in PROPOSED.")
        next_status = "COUNTERED"
    else:
        if agreement["status"] != "COUNTERED":
            raise ApiError("ERR_INVALID_STATE",
                           "A PricingAnalyst counters an agreement in "
                           "COUNTERED.")
        next_status = "PROPOSED"

    lookup.gate_not_closed(lookup.season(agreement["season_id"]))

    if agreement["round_index"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
                       "The negotiation has exhausted its rounds.")

    agreement["current_share_pct"] = r2(share_pct)
    agreement["current_cap_cents"] = cap_cents
    agreement["round_index"] = agreement["round_index"] + 1
    agreement["last_offer_by_role"] = role
    agreement["last_offer_by_user_id"] = user_id
    agreement["status"] = next_status
    touch(agreement)
    return ok(agreement_json(agreement))


@endpoint(bp, "/allowance-agreements/<agreement_id>/accept", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_VENDOR_REP))
def accept_agreement(user_id, role, agreement_id):
    agreement = lookup.agreement(agreement_id)
    if agreement["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PROPOSED or COUNTERED agreement may be "
                       "accepted.")
    lookup.gate_not_closed(lookup.season(agreement["season_id"]))
    if role == agreement["last_offer_by_role"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "A party may never accept its own offer.")

    agreement["status"] = "AGREED"
    agreement["agreed_share_pct"] = agreement["current_share_pct"]
    agreement["funding_cap_cents"] = agreement["current_cap_cents"]
    agreement["remaining_cap_cents"] = agreement["current_cap_cents"]
    agreement["recognized_total_cents"] = 0
    touch(agreement)
    return ok(agreement_json(agreement))


def _check_claim_eligibility(agreement, plan, item):
    """Rule 13, in the PRD's own order."""
    if plan["plan_type"] != "PERMANENT":
        raise ApiError("ERR_PROMO_NOT_CLAIMABLE",
                       "Promotional markdowns are not vendor claimable.")
    if plan["status"] not in ("EXECUTING", "COMPLETED"):
        raise ApiError("ERR_PLAN_NOT_CLAIMABLE",
                       "The plan must be EXECUTING or COMPLETED to be "
                       "claimed against.")
    if item["vendor_code"] != agreement["vendor_code"] or \
            item["category"] != agreement["item_category_scope"]:
        raise ApiError("ERR_ALLOWANCE_SCOPE_MISMATCH",
                       "The plan's item falls outside the agreement's scope.")


def _refresh_agreement_totals(agreement):
    total = sum(c["recognized_cents"] for c in claims_of_agreement(agreement)
                if c["status"] == "RECOGNIZED")
    agreement["recognized_total_cents"] = total
    if agreement["funding_cap_cents"] is not None:
        agreement["remaining_cap_cents"] = \
            agreement["funding_cap_cents"] - total
    return total


@endpoint(bp, "/vendor-claims", ["POST"],
          (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR))
def create_claim(user_id, role):
    from validation import req_int, req_str
    payload = body()
    agreement_id = req_str(payload, "allowance_agreement_id")
    plan_id = req_str(payload, "markdown_plan_id")
    claimed_cents = req_int(payload, "claimed_cents", minimum=1)

    agreement = lookup.agreement(agreement_id)
    plan = lookup.plan(plan_id)
    item = lookup.item(plan["item_id"])
    lookup.gate_active(lookup.season(plan["season_id"]))
    _check_claim_eligibility(agreement, plan, item)

    claim = new_row(
        allowance_agreement_id=agreement["id"],
        markdown_plan_id=plan["id"],
        claimed_cents=claimed_cents,
        recognized_cents=0,
        recognized_by_user_id=None,
        rejection_reason=None,
        status="SUBMITTED",
    )
    db.insert("claims", claim)
    return created(claim_json(claim))


@endpoint(bp, "/vendor-claims/<claim_id>/recognize", ["POST"],
          (ROLE_CONTROLLER,))
def recognize_claim(user_id, role, claim_id):
    claim = lookup.claim(claim_id)
    agreement = lookup.agreement(claim["allowance_agreement_id"])
    plan = lookup.plan(claim["markdown_plan_id"])
    item = lookup.item(plan["item_id"])

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a SUBMITTED claim may be recognized.")
    if agreement["status"] != "AGREED":
        raise ApiError("ERR_INVALID_STATE",
                       "The agreement must be AGREED to recognize funding.")
    lookup.gate_not_closed(lookup.season(plan["season_id"]))
    _check_claim_eligibility(agreement, plan, item)

    gross = plan["gross_markdown_cents"]
    eligible_total = calc.eligible_funding_total(agreement["agreed_share_pct"],
                                                gross)
    headroom = eligible_total - plan["vendor_funded_cents"]
    recognized = min(claim["claimed_cents"], headroom,
                     agreement["remaining_cap_cents"])
    if recognized < 1:
        raise ApiError("ERR_ALLOWANCE_CAP_EXHAUSTED",
                       "No headroom remains for this claim.")

    # hop 1: the claim
    claim["recognized_cents"] = recognized
    claim["status"] = "RECOGNIZED"
    claim["recognized_by_user_id"] = user_id
    touch(claim)

    # hops 2 and 3: agreement totals and its funding status
    _refresh_agreement_totals(agreement)
    if agreement["remaining_cap_cents"] == 0 and agreement["status"] == "AGREED":
        agreement["status"] = "FUNDED"
    touch(agreement)

    # hops 4 and 5: sibling claims and their plans
    if agreement["remaining_cap_cents"] == 0:
        for sibling in claims_of_agreement(agreement):
            if sibling["id"] == claim["id"] or sibling["status"] != "SUBMITTED":
                continue
            sibling["status"] = "REJECTED"
            sibling["rejection_reason"] = "CAP_EXHAUSTED"
            sibling["recognized_cents"] = 0
            touch(sibling)
            sibling_plan = db.get("plans", sibling["markdown_plan_id"])
            if sibling_plan is not None and sibling_plan["id"] != plan["id"]:
                recompute_plan(sibling_plan)

    recompute_plan(plan, force=True)
    return ok(claim_json(claim))


@endpoint(bp, "/vendor-claims/<claim_id>/reverse", ["POST"], (ROLE_CONTROLLER,))
def reverse_claim(user_id, role, claim_id):
    from validation import req_str
    payload = body()
    req_str(payload, "reversal_reason", min_len=1, max_len=1024)
    claim = lookup.claim(claim_id)
    agreement = lookup.agreement(claim["allowance_agreement_id"])
    plan = lookup.plan(claim["markdown_plan_id"])

    if claim["status"] != "RECOGNIZED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a RECOGNIZED claim may be reversed.")
    if agreement["status"] not in ("AGREED", "FUNDED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The agreement must be AGREED or FUNDED to reverse.")
    lookup.gate_not_closed(lookup.season(plan["season_id"]))

    claim["status"] = "REVERSED"
    claim["recognized_cents"] = 0
    touch(claim)

    _refresh_agreement_totals(agreement)
    if agreement["status"] == "FUNDED":
        agreement["status"] = "AGREED"
    touch(agreement)

    recompute_plan(plan, force=True)
    return ok(claim_json(claim))
