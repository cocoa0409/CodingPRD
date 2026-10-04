"""Claims compensation (PRD §3.8)."""

from decimal import Decimal

import db
import middleware
from errors import ApiError, ERR_INVALID_STATE, ERR_POLICY_NOT_FOUND
from money import dec, round_cents
from services import calculations as calc
from services import factories, recompute

TERMINAL = ("DENIED", "CANCELLED")


def create(payload):
    policy_id = payload.get("policy_id")
    policy = db.policy_rows().get(policy_id)
    if policy is None:
        raise ApiError(ERR_POLICY_NOT_FOUND)
    claim = factories.create_claim(payload)
    return claim


def list_claims(request, role=None, user_id=None):
    rows = list(db.claim_rows().values())
    if role == "AgencyPrincipal":
        owned = {p["id"] for p in db.policy_rows().values()
                 if p["owner_agency_id"] == user_id}
        rows = [c for c in rows if c["policy_id"] in owned]
    rows = middleware.filter_by(rows, {
        "policy_id": request.args.get("policy_id"),
        "status": request.args.get("status"),
    })
    rows.sort(key=lambda c: c["created_at"])
    return rows


def settle(claim):
    if claim["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)

    policy = db.policy_rows().get(claim["policy_id"])
    if policy is None:
        raise ApiError(ERR_POLICY_NOT_FOUND)

    claim["policy_paid_cents"] = calc.claim_paid_cents(
        claim["claim_amount_cents"], policy["annual_premium_cents"])
    claim["status"] = "PAID"
    recompute.touch(claim)

    recompute.cascade_from_claim(claim["id"], bump_policy=True, bump_agency=True)
    return claim


def deny(claim):
    if claim["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE)

    claim["policy_paid_cents"] = Decimal(0)
    claim["status"] = "DENIED"
    recompute.touch(claim)

    policy = db.policy_rows().get(claim["policy_id"])
    if policy is not None:
        agency_id = policy["owner_agency_id"]
        recompute.recompute_policy(policy["id"])
        recompute.recompute_agency(agency_id)
        for agreement in recompute.agreements_for(agency_id):
            recompute.recompute_termination_value(agreement, bump=True)
    return claim


def resolve(claim):
    """PAID -> OPEN plus a resolution chargeback against the released ledger."""
    if claim["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] != "PAID":
        raise ApiError(ERR_INVALID_STATE)

    policy = db.policy_rows().get(claim["policy_id"])
    if policy is None:
        raise ApiError(ERR_POLICY_NOT_FOUND)

    chargeback = dec(claim["policy_paid_cents"])
    updated = dec(policy["sub_producer_released_commission_cents"]) - chargeback
    if updated < 0:
        updated = Decimal(0)
    policy["sub_producer_released_commission_cents"] = round_cents(updated)

    claim["policy_paid_cents"] = Decimal(0)
    claim["status"] = "OPEN"
    recompute.touch(claim)

    agency_id = policy["owner_agency_id"]
    recompute.recompute_policy(policy["id"])
    recompute.recompute_agency(agency_id)
    for agreement in recompute.agreements_for(agency_id):
        recompute.recompute_termination_value(agreement, bump=True)
    return claim