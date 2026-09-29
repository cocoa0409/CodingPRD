"""Nine-step fill pricing, the waitlist, fill application, void and the
allocation cycle (PRD 3.8 - 3.10)."""

from decimal import Decimal

from store import db, find, insert, set_field
from util import ceil_units, cents, dec, parse_date

VOLUME_UNIT_ML = 100
BASE_FEE_CENTS_PER_100ML = 480
OUTPATIENT_HANDLING_CENTS = 350
DISCOUNT_TIER_1_ML = 2000
DISCOUNT_TIER_2_ML = 5000
TIER_0 = Decimal("0.00")
TIER_1 = Decimal("0.05")
TIER_2 = Decimal("0.12")
NICU_RESERVE_ML = 3000
MAX_LOTS_PER_PRESCRIPTION_PER_CYCLE = 3

OPEN_PRESCRIPTION_STATES = ("QUEUED", "PARTIALLY_FILLED")


# --- helpers ---------------------------------------------------------------
def program_of(prescription):
    if prescription.get("subsidy_program_id") is None:
        return None
    return find("programs", prescription["subsidy_program_id"])


def released_available_total():
    return sum(
        lot["available_ml"]
        for lot in db.rows("lots")
        if lot["release_status"] == "RELEASED"
    )


def refresh_program_status(program):
    if program is None:
        return
    if program["consumed_cents"] >= program["annual_cap_cents"]:
        set_field(program, "status", "EXHAUSTED")
    else:
        set_field(program, "status", "OPEN")


# --- step 1..9 pricing -----------------------------------------------------
def tier_rate(prior_ml):
    if prior_ml < DISCOUNT_TIER_1_ML:
        return TIER_0
    if prior_ml < DISCOUNT_TIER_2_ML:
        return TIER_1
    return TIER_2


def price_fill(prescription, program, volume_ml):
    """PRD 3.9 pricing; two independent round-half-up steps (5 and 7)."""
    units = ceil_units(volume_ml, VOLUME_UNIT_ML)                    # step 1
    prior_ml = prescription["cumulative_dispensed_ml"]               # step 2
    rate = tier_rate(prior_ml)
    base_cents = units * BASE_FEE_CENTS_PER_100ML                    # step 3
    handling_cents = (                                               # step 4
        OUTPATIENT_HANDLING_CENTS
        if prescription["patient_type"] == "OUTPATIENT" else 0
    )
    gross = cents(dec(base_cents + handling_cents) * (Decimal(1) - rate))  # step 5
    coverage = Decimal(0)                                            # step 6
    if program is not None and program["status"] == "OPEN":
        coverage = dec(program["coverage_pct"])
    uncapped = cents(dec(gross) * coverage)                          # step 7
    if program is None:
        subsidy = 0
    else:                                                            # step 8
        headroom = program["annual_cap_cents"] - program["consumed_cents"]
        subsidy = uncapped if uncapped < headroom else headroom
        if subsidy < 0:
            subsidy = 0
    payer_due = gross - subsidy                                      # step 9
    return {
        "tier_discount_pct": rate,
        "gross_fee_cents": gross,
        "uncapped_subsidy_cents": uncapped,
        "subsidy_cents": subsidy,
        "payer_due_cents": payer_due,
    }


# --- waitlist --------------------------------------------------------------
def _bucket_key(row):
    return (row["created_at"], -row["remaining_ml"], row["prescription_code"])


def renumber_tier(tier):
    rows = [
        p for p in db.rows("prescriptions")
        if p["priority_tier"] == tier and p["status"] in OPEN_PRESCRIPTION_STATES
    ]
    rows.sort(key=_bucket_key)
    position = 0
    for row in rows:
        position += 1
        set_field(row, "waitlist_position", position)


def renumber_all():
    for tier in (1, 2, 3):
        renumber_tier(tier)


# --- fill / void -----------------------------------------------------------
def apply_fill(prescription, lot, volume_ml, priced, user_id, cycle_sequence=None):
    dispense = insert("dispenses", {
        "prescription_id": prescription["id"],
        "lot_id": lot["id"],
        "volume_ml": volume_ml,
        "tier_discount_pct": priced["tier_discount_pct"],
        "gross_fee_cents": priced["gross_fee_cents"],
        "subsidy_cents": priced["subsidy_cents"],
        "payer_due_cents": priced["payer_due_cents"],
        "allocation_cycle_sequence": cycle_sequence,
        "dispensed_by_user_id": user_id,
        "status": "DISPENSED",
    })

    set_field(lot, "dispensed_ml", lot["dispensed_ml"] + volume_ml)
    set_field(lot, "available_ml", lot["total_volume_ml"] - lot["dispensed_ml"])
    if lot["release_status"] == "RELEASED" and lot["available_ml"] <= 0:
        set_field(lot, "release_status", "EXHAUSTED")

    program = program_of(prescription)
    if program is not None and priced["subsidy_cents"]:
        set_field(program, "consumed_cents",
                  program["consumed_cents"] + priced["subsidy_cents"])
        refresh_program_status(program)

    cumulative = prescription["cumulative_dispensed_ml"] + volume_ml
    set_field(prescription, "cumulative_dispensed_ml", cumulative)
    remaining = prescription["prescribed_ml"] - cumulative
    if remaining < 0:
        remaining = 0
    set_field(prescription, "remaining_ml", remaining)
    if remaining == 0:
        set_field(prescription, "status", "FILLED")
        set_field(prescription, "waitlist_position", None)
    else:
        set_field(prescription, "status", "PARTIALLY_FILLED")
    return dispense


def void_fill(dispense):
    prescription = find("prescriptions", dispense["prescription_id"])
    lot = find("lots", dispense["lot_id"])
    set_field(dispense, "status", "VOIDED")

    if lot is not None:
        set_field(lot, "dispensed_ml", lot["dispensed_ml"] - dispense["volume_ml"])
        if lot["dispensed_ml"] < 0:
            set_field(lot, "dispensed_ml", 0)
        set_field(lot, "available_ml", lot["total_volume_ml"] - lot["dispensed_ml"])
        if lot["release_status"] == "EXHAUSTED" and lot["available_ml"] > 0:
            expiry = parse_date(lot["expiration_date"])
            if expiry is not None and expiry >= db.clock_date():
                set_field(lot, "release_status", "RELEASED")

    if prescription is not None:
        program = program_of(prescription)
        if program is not None and dispense["subsidy_cents"]:
            set_field(program, "consumed_cents",
                      program["consumed_cents"] - dispense["subsidy_cents"])
            if program["consumed_cents"] < 0:
                set_field(program, "consumed_cents", 0)
            refresh_program_status(program)
        reopen_prescription(prescription, dispense["volume_ml"])
    return dispense


def reopen_prescription(prescription, volume_ml):
    """Give volume back to an order and return it to the queue."""
    cumulative = prescription["cumulative_dispensed_ml"] - volume_ml
    if cumulative < 0:
        cumulative = 0
    set_field(prescription, "cumulative_dispensed_ml", cumulative)
    remaining = prescription["prescribed_ml"] - cumulative
    if remaining < 0:
        remaining = 0
    set_field(prescription, "remaining_ml", remaining)
    if prescription["status"] in ("FILLED", "PARTIALLY_FILLED", "QUEUED"):
        if cumulative == 0:
            set_field(prescription, "status", "QUEUED")
        elif remaining > 0:
            set_field(prescription, "status", "PARTIALLY_FILLED")
        renumber_tier(prescription["priority_tier"])


# --- allocation cycle ------------------------------------------------------
def _eligible_lots(prescription, today):
    lots = []
    for lot in db.rows("lots"):
        if lot["release_status"] != "RELEASED":
            continue
        if lot["available_ml"] <= 0:
            continue
        expiry = parse_date(lot["expiration_date"])
        if expiry is None or expiry < today:
            continue
        if prescription["requires_preterm_milk"] and lot["milk_class"] != "PRETERM":
            continue
        lots.append(lot)
    lots.sort(key=lambda l: (l["expiration_date"], l["available_ml"], l["lot_code"]))
    return lots


def run_allocation_cycle(user_id):
    db.cycle_counter += 1
    sequence = db.cycle_counter
    today = db.clock_date()

    demand = [
        p for p in db.rows("prescriptions")
        if p["status"] in OPEN_PRESCRIPTION_STATES
        and parse_date(p["needed_by_date"]) is not None
        and parse_date(p["needed_by_date"]) >= today
    ]

    for tier in (1, 2, 3):
        bucket = [p for p in demand if p["priority_tier"] == tier]
        bucket.sort(key=_bucket_key)
        for prescription in bucket:
            lots_used = 0
            for lot in _eligible_lots(prescription, today):
                if prescription["remaining_ml"] <= 0:
                    break
                if lots_used >= MAX_LOTS_PER_PRESCRIPTION_PER_CYCLE:
                    break
                if prescription["status"] not in OPEN_PRESCRIPTION_STATES:
                    break
                available_to_bucket = lot["available_ml"]
                if tier == 3:
                    spare = released_available_total() - NICU_RESERVE_ML
                    if spare < 0:
                        spare = 0
                    if spare < available_to_bucket:
                        available_to_bucket = spare
                draw_ml = prescription["remaining_ml"]
                if available_to_bucket < draw_ml:
                    draw_ml = available_to_bucket
                if draw_ml <= 0:
                    continue
                program = program_of(prescription)
                priced = price_fill(prescription, program, draw_ml)
                # Each draw is a whole fill and carries its own audit increment
                # on the three ledgers it rewrites (PRD 3.10 -> 3.9), so the
                # per-request absorb rule is re-armed for exactly those rows.
                db.rearm(prescription, lot, program)
                apply_fill(prescription, lot, draw_ml, priced, user_id, sequence)
                lots_used += 1

    renumber_all()
    return sequence
