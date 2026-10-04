"""Claim assembly, the policy administration fee, and the write-off menu.

The billed amount is assembled from three lines and rounded ONCE at the end over
the exact component sum — not per component. The administration-fee line is a
policy figure picked by a pinned three-key sort over the practice's history, so
it is only exceptionally the treatment's own fee.
"""

from decimal import Decimal

import db
from services import pricing
from utils import half_up

WRITE_OFF_W1_PCT = Decimal("0.10")
WRITE_OFF_W2_PCT = Decimal("0.25")
POLICY_FEE_PERCENTILE = Decimal("0.41")

# A practice's write-off headroom cap: at or below it the claim carries the
# narrower W1 headroom, above it only W2 may be used.
DEFAULT_WRITE_OFF_CAP_CENTS = 0

TIER_W1 = "W1"
TIER_W2 = "W2"


def practice_treatments_for_product(practice_id, drug_product_id):
    return [
        t
        for t in db.where("treatments", practice_id=practice_id, drug_product_id=drug_product_id)
        if t["status"] == "ADMINISTERED"
    ]


def policy_admin_fee_cents(practice_id, drug_product_id):
    """Sorted by administered_at ASC, then admin_fee_cents ASC, then created_at
    ASC; the pick is the ordinal given by rounding 0.41 * count half up."""
    rows = practice_treatments_for_product(practice_id, drug_product_id)
    if not rows:
        return 0
    rows.sort(
        key=lambda t: (
            t.get("administered_at") or "",
            int(t.get("admin_fee_cents") or 0),
            t.get("created_at") or "",
            t.get("_seq", 0),
        )
    )
    index = half_up(POLICY_FEE_PERCENTILE * Decimal(len(rows)))
    if index >= len(rows):
        index = len(rows) - 1
    if index < 0:
        index = 0
    return int(rows[index].get("admin_fee_cents") or 0)


def settlement_order(practice_id):
    """The pinned three-key sort defining claim-settlement order."""
    rows = [
        t
        for t in db.where("treatments", practice_id=practice_id)
        if t["status"] in ("ADMINISTERED", "BILLED")
    ]
    rows.sort(
        key=lambda t: (
            t.get("administered_at") or "",
            int(t.get("admin_fee_cents") or 0),
            t.get("created_at") or "",
            t.get("_seq", 0),
        )
    )
    return rows


def assign_settlement_priority(practice):
    for index, treatment in enumerate(settlement_order(practice["id"]), start=1):
        treatment["settlement_priority"] = index


def write_off_cap(practice):
    return int(practice.get("write_off_cap_cents", DEFAULT_WRITE_OFF_CAP_CENTS) or 0)


def resolve_write_off_tier(practice, requested=None):
    """W2 is the only tier reachable while the practice's unsettled balance sits
    above its own cap."""
    above_cap = int(practice.get("unsettled_balance_cents") or 0) > write_off_cap(practice)
    if requested is not None:
        if requested not in (TIER_W1, TIER_W2):
            from errors import ApiError

            raise ApiError("ERR_INVALID_REQUEST", "write_off_tier must be W1 or W2")
        if requested == TIER_W1 and above_cap:
            from errors import ApiError

            raise ApiError("ERR_INVALID_REQUEST", "only W2 may be used above the write-off cap")
        return requested
    return TIER_W2 if above_cap else TIER_W1


def write_off_cents(billed_amount_cents, tier):
    pct = WRITE_OFF_W1_PCT if tier == TIER_W1 else WRITE_OFF_W2_PCT
    return half_up(Decimal(billed_amount_cents) * pct)


def compute_billed_amount(treatment, claim):
    """line_1 patient units + line_2 wastage + line_3 admin fee, summed exactly
    and rounded once at the end."""
    rate = pricing.draw_unit_cost_cents(
        treatment["practice_id"], treatment["drug_product_id"]
    )
    dose_count = int(treatment.get("dose_count") or 1)
    administered = int(treatment.get("administered_units") or 0)
    wastage_units = int(treatment.get("wastage_units") or 0)
    policy_fee = policy_admin_fee_cents(treatment["practice_id"], treatment["drug_product_id"])
    disclosure = bool(claim.get("post_settlement_disclosure"))

    line_1 = half_up(Decimal(rate) * Decimal(dose_count) * Decimal(administered))
    line_2 = half_up(Decimal(rate) * Decimal(wastage_units))
    line_3 = 0 if disclosure else policy_fee
    total = half_up(Decimal(line_1) + Decimal(line_2) + Decimal(line_3))
    return {
        "rate": rate,
        "line_1": line_1,
        "line_2": line_2,
        "line_3": line_3,
        "policy_admin_fee_cents": policy_fee,
        "billed_amount_cents": total,
    }


def refreshed_policy_fee(claim, treatment):
    fee = policy_admin_fee_cents(treatment["practice_id"], treatment["drug_product_id"])
    claim["policy_admin_fee_cents"] = fee
    return fee


def refresh_claim_fields(treatment, claim):
    """Recompute the claim's computed lines. billed_amount_cents is only
    pinned (frozen) at submission; before that it tracks the assembly."""
    treatment["policy_admin_fee_cents"] = policy_admin_fee_cents(
        treatment["practice_id"], treatment["drug_product_id"]
    )
    claim["policy_admin_fee_cents"] = treatment["policy_admin_fee_cents"]
    if claim["status"] == "DRAFT":
        assembly = compute_billed_amount(treatment, claim)
        claim["billed_amount_cents"] = assembly["billed_amount_cents"]
        claim["billed_admin_fee_cents"] = assembly["line_3"]
        claim["written_off_admin_fee_cents"] = (
            assembly["policy_admin_fee_cents"] if claim.get("post_settlement_disclosure") else 0
        )
    else:
        claim["billed_admin_fee_cents"] = 0 if claim.get("post_settlement_disclosure") else claim.get(
            "policy_admin_fee_cents", 0
        )
        claim["written_off_admin_fee_cents"] = (
            claim.get("policy_admin_fee_cents", 0) if claim.get("post_settlement_disclosure") else 0
        )