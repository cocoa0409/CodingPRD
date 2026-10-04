"""Payout service: country thresholds, payment-method eligibility, the vetting
hold, and the three PayoutRequest transitions.

The country floor comparison is at-least, so an amount exactly equal to the
minimum is payable (calculation: payout_threshold_by_country).
"""

from apptime import now, shift
from config import (
    DEFAULT_ELIGIBLE_PAYMENT_METHODS,
    ELIGIBLE_PAYMENT_METHODS,
    HOLD_DAYS,
    PAYOUT_MIN_BR_CENTS,
    PAYOUT_MIN_IN_PH_CENTS,
    PAYOUT_MIN_US_CENTS,
)
from db import db, common_fields, touch
from errors import fail
from serializers import reserved_payout_cents, total_earned_cents


def minimum_payout_cents(country: str) -> int:
    if country == "US":
        return PAYOUT_MIN_US_CENTS
    if country in {"IN", "PH"}:
        return PAYOUT_MIN_IN_PH_CENTS
    if country == "BR":
        return PAYOUT_MIN_BR_CENTS
    return PAYOUT_MIN_IN_PH_CENTS


def eligible_methods(country: str) -> set:
    return ELIGIBLE_PAYMENT_METHODS.get(country, DEFAULT_ELIGIBLE_PAYMENT_METHODS)


def check_payout_version(payout: dict, expected) -> None:
    """OCC guard on payout release (PRD §2.7)."""
    if expected is None:
        fail("ERR_INVALID_REQUEST", "Field 'expected_payout_request_version' is required.")
    if int(expected) != payout["version"]:
        fail("ERR_STALE_VERSION")


def request_payout(worker_row: dict, payment_method: str, amount_cents: int) -> dict:
    """Mint a HELD_FOR_VETTING payout, reserving the funds immediately."""
    if amount_cents <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be a positive integer.")
    if amount_cents < minimum_payout_cents(worker_row["country"]):
        fail("ERR_PAYOUT_THRESHOLD_NOT_MET")
    if payment_method not in eligible_methods(worker_row["country"]):
        fail("ERR_PAYOUT_METHOD_INELIGIBLE")

    created_at = now()
    row = common_fields()
    row.update(
        {
            "worker_id": worker_row["id"],
            "payment_method": payment_method,
            "amount_cents": amount_cents,
            "hold_until_at": shift(created_at, days=HOLD_DAYS),
            "identity_verified_at": None,
            "status": "HELD_FOR_VETTING",
            "rejection_reason": None,
        }
    )
    db.payouts[row["id"]] = row
    touch(worker_row)
    return row


def verify_payout(payout: dict, worker_row: dict, expected_version) -> dict:
    """HELD_FOR_VETTING -> PAID for an identity-verified worker past the hold."""
    if payout["status"] != "HELD_FOR_VETTING":
        fail("ERR_INVALID_STATE")
    check_payout_version(payout, expected_version)
    if not worker_row.get("identity_verified"):
        fail("ERR_IDENTITY_NOT_VERIFIED")
    if now() < payout["hold_until_at"]:
        fail("ERR_VETTING_HOLD_ACTIVE")

    payout["identity_verified_at"] = now()
    payout["status"] = "PAID"
    touch(payout)
    touch(worker_row)
    return payout


def reject_payout(payout: dict, worker_row: dict, reason) -> dict:
    """HELD_FOR_VETTING -> REJECTED; the reserved funds are released."""
    if payout["status"] != "HELD_FOR_VETTING":
        fail("ERR_INVALID_STATE")
    payout["rejection_reason"] = None if reason is None else str(reason)
    payout["status"] = "REJECTED"
    touch(payout)
    # withdrawable_cents is derived as earned - reserved, so flipping the
    # status out of {PAID, HELD_FOR_VETTING} releases the amount immediately.
    touch(worker_row)
    return payout


def settle_due_payouts() -> None:
    """Sweep: held payouts past their hold, for identity-verified workers."""
    for payout in list(db.payouts.values()):
        if payout["status"] != "HELD_FOR_VETTING":
            continue
        if now() < payout["hold_until_at"]:
            continue
        worker_row = db.workers.get(payout["worker_id"])
        if worker_row is None or not worker_row.get("identity_verified"):
            continue
        payout["identity_verified_at"] = now()
        payout["status"] = "PAID"
        touch(payout)
        touch(worker_row)


def withdrawable(worker_row: dict) -> int:
    return total_earned_cents(worker_row["id"]) - reserved_payout_cents(worker_row["id"])