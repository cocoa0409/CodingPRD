"""Calculation rules (PRD 2.7, 3.1, 3.2, 3.4, 3.8, 3.9).

Every number here is produced with Decimal arithmetic and round-half-up, and
every rounding step happens exactly where the PRD pins it.
"""

from decimal import Decimal

from core import (
    CATEGORY_PRIORITY, CONDITION_RANK, SOFT_RATIO_REJECT_THRESHOLD,
    WAREHOUSE_CAPACITY_CF, OCCUPYING_STOCK_STATUSES, clock, dec, round_half_up,
    ceil_units,
)
from db import (
    db, sorted_by_creation, lines_of_voucher, units_of_voucher,
    agency_of_voucher, client_of_voucher, referral_of_voucher, touch,
)

# --------------------------------------------------------------------------
# client_referral_priority_score  (PRD 3.2)
# --------------------------------------------------------------------------
URGENCY_WEIGHT = {"ROUTINE": 10, "PRIORITY": 25, "EMERGENCY": 40}
SIZE_POINT_PER_PERSON = 5
SIZE_POINT_CAP_PERSONS = 6
INFANT_POINTS = 15
TENURE_POINTS_PER_MONTH = 4
TENURE_POINTS_CAP = 20
REVISION_PENALTY_PER_ROUND = 6
INTAKE_STRIKE_WEIGHT = 8
WAITLIST_STRIKE_WEIGHT = 16


def priority_score(referral, client, tenure_days=0, strike_weight=INTAKE_STRIKE_WEIGHT):
    urgency_points = URGENCY_WEIGHT[referral["urgency"]]
    size_points = min(client["household_size"], SIZE_POINT_CAP_PERSONS) * SIZE_POINT_PER_PERSON
    infant_points = INFANT_POINTS if client["has_infant"] else 0
    tenure_points = min((tenure_days // 30) * TENURE_POINTS_PER_MONTH, TENURE_POINTS_CAP)
    revision_penalty = referral["revision_count"] * REVISION_PENALTY_PER_ROUND
    strike_penalty = client["no_show_strikes"] * strike_weight
    raw = dec(urgency_points + size_points + infant_points + tenure_points
              - revision_penalty - strike_penalty)
    if raw < 0:
        raw = Decimal("0")
    return round_half_up(raw, 1)


def intake_score(referral, client):
    """Intake variant: tenure is zero, strike weight is 8."""
    return priority_score(referral, client, tenure_days=0,
                          strike_weight=INTAKE_STRIKE_WEIGHT)


def whole_days_between(start, end):
    if start is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 86400)


def waitlist_score(referral, client, waiting_since):
    """Waitlist variant: tenure from waiting_since, strike weight is 16."""
    tenure_days = whole_days_between(waiting_since, clock.now())
    return priority_score(referral, client, tenure_days=tenure_days,
                          strike_weight=WAITLIST_STRIKE_WEIGHT)


# --------------------------------------------------------------------------
# voucher_delivery_fee  (PRD 3.9)
# --------------------------------------------------------------------------
BASE_FEE_CENTS = {"NORTH": 4000, "CENTRAL": 3000, "SOUTH": 5000}
PER_50CF_CENTS = 1200
CUBIC_FEET_PER_INCREMENT = 50
LIFT_SURCHARGE_CENTS = 1500
LIFT_CATEGORIES = ("BED", "SOFA")
FEE_CAP_CENTS = 9000
INFANT_SUBSIDY_BONUS = Decimal("0.10")
PROBATION_SUBSIDY_PENALTY = Decimal("0.20")


def _subsidy_percentage(client, agency):
    size = client["household_size"]
    if size <= 2:
        pct = Decimal("0.50")
    elif size <= 4:
        pct = Decimal("0.70")
    else:
        pct = Decimal("0.90")
    if client["has_infant"]:
        pct = min(pct + INFANT_SUBSIDY_BONUS, Decimal("1.00"))
    if agency["standing"] == "PROBATION":
        pct = max(pct - PROBATION_SUBSIDY_PENALTY, Decimal("0.00"))
    if agency["standing"] == "SUSPENDED":
        pct = Decimal("0.00")
    return pct


def compute_delivery_fee(voucher, service_county, stock_statuses):
    basis = units_of_voucher(voucher["id"], stock_statuses)
    total_cf = Decimal("0")
    categories = set()
    for unit in basis:
        total_cf += dec(unit["cubic_feet"])
        categories.add(unit["category"])

    base_cents = BASE_FEE_CENTS[service_county]
    bulk_cents = ceil_units(total_cf, CUBIC_FEET_PER_INCREMENT) * PER_50CF_CENTS
    lift_cents = LIFT_SURCHARGE_CENTS if categories.intersection(LIFT_CATEGORIES) else 0
    gross = min(base_cents + bulk_cents + lift_cents, FEE_CAP_CENTS)

    client = client_of_voucher(voucher)
    agency = agency_of_voucher(voucher)
    pct = _subsidy_percentage(client, agency)
    subsidy = int(round_half_up(dec(gross) * pct, 0))
    client_due = gross - subsidy
    return gross, subsidy, client_due


def write_fee(voucher, basis, service_county, stock_statuses):
    """Write the four money fields - but only while the billing axis is still
    PENDING (the billing freeze, PRD 3.9)."""
    if voucher["fee_status"] != "PENDING":
        return False
    gross, subsidy, client_due = compute_delivery_fee(voucher, service_county, stock_statuses)
    voucher["gross_fee_cents"] = gross
    voucher["subsidy_cents"] = subsidy
    voucher["client_due_cents"] = client_due
    voucher["fee_basis"] = basis
    return True


def write_provisional_fee(voucher):
    client = client_of_voucher(voucher)
    return write_fee(voucher, "PROVISIONAL", client["county"], ("RESERVED", "STAGED"))


def write_final_fee(voucher, run):
    return write_fee(voucher, "FINAL", run["county"], ("DELIVERED",))


def recompute_fill_ratio(voucher):
    lines = lines_of_voucher(voucher["id"])
    requested = sum(l["quantity_requested"] for l in lines)
    allocated = sum(l["quantity_allocated"] for l in lines)
    if requested == 0:
        return Decimal("0.000")
    return round_half_up(dec(allocated) / dec(requested), 3)


# --------------------------------------------------------------------------
# no_show_chargeback  (PRD 3.8)
# --------------------------------------------------------------------------
NO_SHOW_RATE = Decimal("0.45")
REFUSED_RATE = Decimal("0.25")
CATEGORY_BASE_CENTS = {
    "BED": 2500, "SOFA": 3000, "CRIB": 1500, "TABLE_SET": 1150,
    "DRESSER": 950, "KITCHEN_KIT": 650, "LINENS": 250,
}
CHARGEABLE_LINE_STATUSES = ("OPEN", "PARTIAL", "FILLED", "WAITLISTED")


def compute_chargeback(voucher, outcome):
    """Round each line to whole cents first, then sum the rounded charges."""
    rate = NO_SHOW_RATE if outcome == "NO_SHOW" else REFUSED_RATE
    total = 0
    for line in lines_of_voucher(voucher["id"]):
        if line["status"] not in CHARGEABLE_LINE_STATUSES:
            continue
        raw = dec(CATEGORY_BASE_CENTS[line["category"]]) * dec(line["quantity_allocated"]) * rate
        total += int(round_half_up(raw, 0))
    return total


# --------------------------------------------------------------------------
# agency_standing_recompute  (PRD 3.1)
# --------------------------------------------------------------------------
STANDING_WINDOW = 10
STANDING_MIN_SAMPLE = 2
TERMINAL_STOP_STATUSES = ("DELIVERED", "NO_SHOW", "REFUSED")


def recompute_agency_standing(agency):
    window = []
    for stop in db.delivery_stops.values():
        if stop["status"] not in TERMINAL_STOP_STATUSES:
            continue
        voucher = db.vouchers.get(stop["voucher_id"])
        if voucher is None:
            continue
        referral = referral_of_voucher(voucher)
        if referral is None or referral["agency_id"] != agency["id"]:
            continue
        window.append(stop)

    window.sort(key=lambda s: (s["created_at"], s["_seq"]), reverse=True)
    if len(window) > STANDING_WINDOW:
        boundary = window[STANDING_WINDOW - 1]["created_at"]
        kept = window[:STANDING_WINDOW]
        for stop in window[STANDING_WINDOW:]:
            if stop["created_at"] == boundary:
                kept.append(stop)
        window = kept

    terminal_count = len(window)
    no_show_count = len([s for s in window if s["status"] == "NO_SHOW"])
    if terminal_count < STANDING_MIN_SAMPLE:
        standing = "GOOD"
    elif no_show_count * 2 >= terminal_count:
        standing = "SUSPENDED"
    elif no_show_count * 4 >= terminal_count:
        standing = "PROBATION"
    else:
        standing = "GOOD"

    if agency["standing"] != standing:
        agency["standing"] = standing
        touch(agency)
        return True
    return False


# --------------------------------------------------------------------------
# donation_acceptance_triage  (PRD 3.4)
# --------------------------------------------------------------------------
def warehouse_occupancy_cf():
    total = Decimal("0")
    for unit in db.inventory_items.values():
        if unit["status"] in OCCUPYING_STOCK_STATUSES:
            total += dec(unit["cubic_feet"])
    return total


def run_triage(offer, items):
    """Apply the acceptance criteria; returns (declared_soft_ratio,
    accepted_count, rejected_count, bed_bug_risk_score)."""
    ordered = sorted_by_creation(items)
    total_items = len(ordered)

    # STEP 1 - pre-decision snapshot over all submitted pieces.
    soft_count = len([i for i in ordered if i["soft_surface"]])
    if total_items == 0:
        declared_soft_ratio = Decimal("0.000")
    else:
        declared_soft_ratio = round_half_up(dec(soft_count) / dec(total_items), 3)

    # STEP 2 - per-piece decision loop.
    headroom_cf = WAREHOUSE_CAPACITY_CF - warehouse_occupancy_cf()
    running_cf = Decimal("0")
    for item in ordered:
        cubic_feet = dec(item["cubic_feet"])
        if item["category"] == "CRIB" and item["declared_condition"] != "A":
            item["decision"] = "REJECTED"
            item["reject_reason"] = "RECALLED_CRIB"
        elif item["declared_condition"] == "D":
            item["decision"] = "REJECTED"
            item["reject_reason"] = "CONDITION_BELOW_MIN"
        elif item["soft_surface"] and declared_soft_ratio >= SOFT_RATIO_REJECT_THRESHOLD:
            item["decision"] = "REJECTED"
            item["reject_reason"] = "SOFT_SURFACE_RISK"
        elif running_cf + cubic_feet > headroom_cf:
            item["decision"] = "REJECTED"
            item["reject_reason"] = "CAPACITY"
        else:
            item["decision"] = "ACCEPTED"
            item["reject_reason"] = None
            running_cf = running_cf + cubic_feet
        touch(item)

    accepted = [i for i in ordered if i["decision"] == "ACCEPTED"]
    rejected = [i for i in ordered if i["decision"] == "REJECTED"]

    # STEP 3 - risk score, only once every decision is final.
    accepted_cf = sum((dec(i["cubic_feet"]) for i in accepted), Decimal("0"))
    accepted_soft_cf = sum((dec(i["cubic_feet"]) for i in accepted if i["soft_surface"]),
                           Decimal("0"))
    if accepted_cf == 0:
        risk = Decimal("0.0")
    else:
        risk = round_half_up(dec(100) * accepted_soft_cf / accepted_cf, 1)

    return declared_soft_ratio, len(accepted), len(rejected), risk


# --------------------------------------------------------------------------
# inventory_allocation_selector ranking helpers  (PRD 3.6)
# --------------------------------------------------------------------------
def line_processing_key(line):
    return (CATEGORY_PRIORITY[line["category"]], line["created_at"], line["_seq"])


def candidate_ranking_key(unit):
    return (-CONDITION_RANK[unit["condition"]], unit["available_since"],
            unit["created_at"], unit["_seq"])
