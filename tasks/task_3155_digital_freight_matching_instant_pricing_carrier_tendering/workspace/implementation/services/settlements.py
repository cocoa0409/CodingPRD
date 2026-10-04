"""Settlement arithmetic (PRD 2.9, 3.9; SCAFFOLD Table 3)."""

from decimal import Decimal

from constants import (
    QUICK_PAY_TIERS, d, round_half_up, utc, plus_days,
)
from db import clock_now, db, mint_id, touch
from errors import ApiError
from services.common import load_accessorial_total, refresh_carrier_score


def quick_pay_tier_rate(carrier_id, at_instant, exclude_settlement_id=None):
    """The tier key is a COUNT of the carrier's other paid settlements.

    PRD 3.9 counts the settlements "already in PAID status whose paid_at falls
    strictly before the payout instant" and excludes the one being paid. When
    the logical clock does not advance between two payouts every paid_at is
    equal, so the ordering the scaffold states (paid_at ASC, tie-broken by
    created_at ASC) is what distinguishes them; the count is therefore taken
    over settlements paid at or before the instant, minus the payer itself.
    """
    prior = 0
    rows = []
    for row in db.settlements.values():
        if row["carrier_id"] != carrier_id:
            continue
        if row["settlement_status"] != "PAID":
            continue
        if exclude_settlement_id is not None and row["id"] == exclude_settlement_id:
            continue
        if row["paid_at"] is not None and utc(row["paid_at"]) <= utc(at_instant):
            rows.append(row)
    rows.sort(key=lambda row: (row["paid_at"], row["created_at"]))
    prior = len(rows)
    for low, high, rate in QUICK_PAY_TIERS:
        if prior >= low and (high is None or prior <= high):
            return rate
    return QUICK_PAY_TIERS[-1][2]


def claims_deduction_for(load_id):
    total = 0
    for claim in db.claims.values():
        if claim["load_id"] == load_id and claim["status"] in ("APPROVED", "SETTLED"):
            total += claim["approved_amount_cents"]
    return total


def restrike(settlement, tier_rate=None):
    """Strike gross, then discount, then net — the pinned evaluation order."""
    load = db.loads.get(settlement["load_id"])
    booking = db.bookings.get(settlement["booking_id"])
    settlement["claims_deduction_cents"] = claims_deduction_for(settlement["load_id"])
    if load is not None:
        settlement["accessorial_cents"] = load_accessorial_total(load["id"])
    settlement["gross_payable_cents"] = (settlement["line_haul_cents"]
                                         + settlement["accessorial_cents"]
                                         - settlement["claims_deduction_cents"])
    if booking is not None and booking["quick_pay_elected"]:
        rate = tier_rate if tier_rate is not None else quick_pay_tier_rate(
            settlement["carrier_id"], clock_now())
        settlement["quick_pay_discount_cents"] = round_half_up(
            d(settlement["gross_payable_cents"]) * rate)
    else:
        settlement["quick_pay_discount_cents"] = 0
    settlement["net_payable_cents"] = (settlement["gross_payable_cents"]
                                       - settlement["quick_pay_discount_cents"])
    return settlement


def refresh_live_settlement_for_load(load_id):
    """Re-strike the load's ACCRUED or READY settlement after a cascade.

    A clawback leaves the row REVERSED when the deduction swallowed the whole
    settlement, but the load's deduction line must still track a later approval
    (PRD 3.8), so any settled row on the load is refreshed.
    """
    settlement = None
    for row in db.settlements.values():
        if row["load_id"] != load_id or row["reversal_of_settlement_id"] is not None:
            continue
        if row["settlement_status"] in ("ACCRUED", "READY", "REVERSED"):
            settlement = row
            break
    if settlement is None:
        return None
    restrike(settlement)
    touch(settlement)
    return settlement


def create_settlement_for_delivery(load, booking):
    now = clock_now()
    settlement = {
        "id": mint_id(),
        "carrier_id": booking["carrier_id"],
        "booking_id": booking["id"],
        "load_id": load["id"],
        "line_haul_cents": booking["agreed_rate_cents"],
        "accessorial_cents": load_accessorial_total(load["id"]),
        "claims_deduction_cents": 0,
        "gross_payable_cents": 0,
        "quick_pay_discount_cents": 0,
        "net_payable_cents": 0,
        "payout_due_at": None,
        "paid_at": None,
        "reversal_of_settlement_id": None,
        "settlement_status": "ACCRUED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.settlements[settlement["id"]] = settlement
    restrike(settlement)
    return settlement


def payout_due_at(load, settlement, shipper):
    """PRD 3.9 — delivery instant (or creation) plus the shipper's terms."""
    if load["status"] in ("DELIVERED", "INVOICED", "PAID") and load.get("actual_delivery_at"):
        basis = load["actual_delivery_at"]
    elif load["status"] in ("DELIVERED", "INVOICED", "PAID"):
        basis = load.get("delivered_at") or settlement["created_at"]
    else:
        basis = settlement["created_at"]
    return plus_days(basis, shipper["payment_terms_days"])


def apply_clawback(settlement, claim):
    """PRD 3.9 — the approved amount is withheld from the carrier's pay.

    The deduction line is the sum over the load's APPROVED and SETTLED claims,
    re-struck in the pinned order; the carrier's clawback count rises by one.
    """
    restrike(settlement)
    if settlement["net_payable_cents"] <= 0 and settlement["gross_payable_cents"] <= 0:
        settlement["settlement_status"] = "REVERSED"
    carrier = db.carriers.get(settlement["carrier_id"])
    if carrier is not None:
        carrier["claims_clawback_count"] = carrier.get("claims_clawback_count", 0) + 1
        refresh_carrier_score(carrier, bump=True)
    touch(settlement)
    return settlement


def reverse_settlement(settlement):
    """Void: negate every money line exactly into a compensating row."""
    now = clock_now()
    compensating = {
        "id": mint_id(),
        "carrier_id": settlement["carrier_id"],
        "booking_id": settlement["booking_id"],
        "load_id": settlement["load_id"],
        "line_haul_cents": -settlement["line_haul_cents"],
        "accessorial_cents": -settlement["accessorial_cents"],
        "claims_deduction_cents": -settlement["claims_deduction_cents"],
        "gross_payable_cents": -settlement["gross_payable_cents"],
        "quick_pay_discount_cents": -settlement["quick_pay_discount_cents"],
        "net_payable_cents": -settlement["net_payable_cents"],
        "payout_due_at": None,
        "paid_at": None,
        "reversal_of_settlement_id": settlement["id"],
        "settlement_status": "ACCRUED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    settlement["settlement_status"] = "REVERSED"
    touch(settlement)
    db.settlements[compensating["id"]] = compensating
    return compensating