"""Courier reimbursement arithmetic and the donor ledger (PRD 3.4)."""

from decimal import Decimal

from store import db, set_field
from util import cents, dec

ZONE_BASE_CENTS = {"Z1": 1200, "Z2": 1850, "Z3": 2600}
CONTAINER_HANDLING_CENTS = 275
DRY_ICE_MULTIPLIER = Decimal("1.15")
EXCURSION_PENALTY_PER_MINUTE = Decimal("0.02")
EXCURSION_PENALTY_CAP = Decimal("0.60")
QUARANTINE_CREDIT_FACTOR = Decimal("0.5")

REJECT_TEMP_CELSIUS = Decimal("4.0")
REJECT_EXCURSION_MINUTES = 120
QUARANTINE_TEMP_CELSIUS = Decimal("-8.0")
QUARANTINE_EXCURSION_MINUTES = 30

CREDITED_SHIPMENT_STATES = ("ACCEPTED", "QUARANTINED", "CLOSED")


def excursion_penalty_rate(excursion_minutes):
    if excursion_minutes is None:
        return Decimal(0)
    rate = EXCURSION_PENALTY_PER_MINUTE * dec(excursion_minutes)
    return EXCURSION_PENALTY_CAP if rate > EXCURSION_PENALTY_CAP else rate


def reimbursement_cents(shipment, excursion_minutes=None):
    """One shared skeleton; per-container rounding BEFORE the multiply."""
    base = dec(ZONE_BASE_CENTS[shipment["zone_code"]])
    share = base / dec(shipment["container_count"])
    if shipment["uses_dry_ice"]:
        share = share * DRY_ICE_MULTIPLIER
    rate = excursion_penalty_rate(excursion_minutes)
    per_container_raw = (share + dec(CONTAINER_HANDLING_CENTS)) * (Decimal(1) - rate)
    per_container = cents(per_container_raw)
    return per_container * shipment["container_count"]


def receipt_disposition(arrival_max_temp_celsius, excursion_minutes):
    temp = dec(arrival_max_temp_celsius)
    if temp > REJECT_TEMP_CELSIUS or excursion_minutes > REJECT_EXCURSION_MINUTES:
        return "REJECTED"
    if temp > QUARANTINE_TEMP_CELSIUS or excursion_minutes > QUARANTINE_EXCURSION_MINUTES:
        return "QUARANTINED"
    return "ACCEPTED"


def credited_for(status, final_cents):
    if status == "ACCEPTED":
        return final_cents
    if status == "QUARANTINED":
        return cents(dec(final_cents) * QUARANTINE_CREDIT_FACTOR)
    return 0


def refresh_reimbursement_balance(donor):
    """The ledger is by definition the sum of credited amounts on her coolers."""
    total = 0
    for shipment in db.rows("shipments"):
        if shipment["donor_id"] != donor["id"]:
            continue
        if shipment["status"] not in CREDITED_SHIPMENT_STATES:
            continue
        total += shipment["credited_reimbursement_cents"] or 0
    set_field(donor, "reimbursement_balance_cents", total)
