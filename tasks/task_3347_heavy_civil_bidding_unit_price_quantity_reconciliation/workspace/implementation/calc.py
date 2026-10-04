"""Every derived figure in the system (scaffold section 1.3, PRD section 3)."""

import math
from decimal import Decimal

import db
from util import dec, f2, round_2dp, round_cents

# ---------------------------------------------------------------------------
# Populations
# ---------------------------------------------------------------------------

OPEN_PHASE_STATUSES = ("DRAFT", "APPROVED", "PAYABLE")
FINAL_PHASE_STATUSES = ("APPROVED",)


def project_items(project):
    return [i for i in db.BID_ITEMS.values() if i["project_id"] == project["id"]]


def included_items(project):
    """Items whose item_status is not DRAFT (unbalanced score, variance counts)."""
    return [i for i in project_items(project) if i["item_status"] != "DRAFT"]


# PRD 3.2: "The population of included pay items is every item on the project
# whose `item_status` is not `DRAFT`."
BID_POPULATION_STATUSES = ("PRICED", "SUBMITTED", "AWARDED", "ACTIVE", "CLOSED")


def bid_population(project):
    """The items currently in the bid — the population of the bid extension."""
    return [i for i in project_items(project) if i["item_status"] in BID_POPULATION_STATUSES]


def project_quotes(project):
    return [q for q in db.QUOTES.values() if q["project_id"] == project["id"]]


def item_measurements(item):
    return [m for m in db.MEASUREMENTS.values() if m["bid_item_id"] == item["id"]]


def project_measurements(project):
    rows = []
    for item in project_items(project):
        rows.extend(item_measurements(item))
    return rows


def latest_reconciliation(project):
    rows = [r for r in db.RECONCILIATIONS.values() if r["project_id"] == project["id"]]
    rows.sort(key=lambda r: r["_seq"])
    return rows[-1] if rows else None


def non_closed_reconciliation(project):
    rows = [r for r in db.RECONCILIATIONS.values()
            if r["project_id"] == project["id"] and r["reconciliation_status"] != "CLOSED"]
    rows.sort(key=lambda r: r["_seq"])
    return rows[-1] if rows else None


def awarded_value_cents(project):
    """The contract value captured at award, before any reconciliation settlement."""
    return project.get("_awarded_value_cents", 0)


def settled_contract_value_cents(project):
    reconciliation = latest_reconciliation(project)
    net = reconciliation["net_adjustment_cents"] if reconciliation is not None else 0
    return awarded_value_cents(project) + net


def ledger_phase(project):
    """OPEN phase counts every non-VOIDED row; FINALIZED phase counts APPROVED only."""
    reconciliation = latest_reconciliation(project)
    if reconciliation is not None and reconciliation["reconciliation_status"] in ("FINALIZED", "CLOSED"):
        return FINAL_PHASE_STATUSES
    return OPEN_PHASE_STATUSES


def counted_measurements(item, statuses=None):
    if statuses is None:
        project = db.PROJECTS.get(item["project_id"])
        statuses = ledger_phase(project) if project else OPEN_PHASE_STATUSES
    rows = [m for m in item_measurements(item) if m["measurement_status"] in statuses]
    rows.sort(key=lambda m: (m["measured_at"], m["created_at"], m["_seq"]))
    return rows


def payable_measurements(project):
    return [m for m in project_measurements(project)
            if m["measurement_status"] in ("APPROVED", "PAYABLE")]


# ---------------------------------------------------------------------------
# project_bid_extension
# ---------------------------------------------------------------------------

def item_extended_cents(item):
    return round_cents(dec(item["bid_unit_price_cents"]) * dec(item["estimated_quantity"]))


def items_subtotal_cents(project):
    return sum(item_extended_cents(i) for i in bid_population(project))


def subcontract_subtotal_cents(project):
    return sum(q["quoted_amount_cents"] for q in project_quotes(project)
               if q["quote_status"] in ("CARRIED", "SELECTED"))


def total_bid_cents(project):
    return items_subtotal_cents(project) + subcontract_subtotal_cents(project)


# ---------------------------------------------------------------------------
# bid_unbalanced_unit_price_extension
# ---------------------------------------------------------------------------

def band_multiplier(ratio):
    if ratio < Decimal("0.80"):
        return Decimal("1.00")
    if ratio < Decimal("1.20"):
        return Decimal("1.00")
    if ratio < Decimal("2.00"):
        return Decimal("1.005")
    return Decimal("1.015")


def unbalanced_bid_score(project):
    total = 0
    for item in included_items(project):
        balanced = item["balanced_unit_price_cents"]
        if balanced is None or balanced <= 0:
            continue
        ratio = dec(item["bid_unit_price_cents"]) / dec(balanced)
        contribution = dec(item["estimated_quantity"]) * dec(balanced) * band_multiplier(ratio)
        total += round_cents(contribution)
    return total


# ---------------------------------------------------------------------------
# quantity_variance_adjustment
# ---------------------------------------------------------------------------

def item_ledger(item, statuses=None):
    """Return (measured_quantity, variance_pct, renegotiation_required)."""
    measured = sum(dec(m["measured_quantity"]) for m in counted_measurements(item, statuses))
    estimated = dec(item["estimated_quantity"])
    variance = round_2dp((measured - estimated) / estimated * Decimal(100))
    overrun = dec(item["overrun_threshold_pct"])
    underrun = dec(item["underrun_threshold_pct"])
    renegotiation = variance > overrun or variance < (-underrun)
    return measured, variance, renegotiation


def recalc_item(item, stamp=True):
    measured, variance, renegotiation = item_ledger(item)
    item["measured_quantity"] = float(measured)
    item["variance_pct"] = f2(variance)
    item["renegotiation_required"] = bool(renegotiation)
    if stamp:
        db.touch(item)
    return item


def variance_counts(project):
    overrun = 0
    underrun = 0
    for item in included_items(project):
        _, variance, _ = item_ledger(item)
        if variance > dec(item["overrun_threshold_pct"]):
            overrun += 1
        if variance < (-dec(item["underrun_threshold_pct"])):
            underrun += 1
    return overrun, underrun


def net_adjustment_cents(project):
    total = 0
    for item in project_items(project):
        _, variance, renegotiation = item_ledger(item)
        if not renegotiation:
            continue
        economic_variance = round_cents(variance)
        points = min(max(economic_variance, 0), 300)
        total += points * 200
    return total


def has_final_renegotiated_rate(item):
    for determination in db.DETERMINATIONS.values():
        if (determination["determination_status"] == "FINAL"
                and determination["determination_type"] == "QUANTITY_ADJUSTMENT"
                and determination.get("target_bid_item_id") == item["id"]):
            return True
    return False


def applied_rate_cents(item):
    """The renegotiated rate when a FINAL QUANTITY_ADJUSTMENT covers the item."""
    rate = None
    for determination in db.DETERMINATIONS.values():
        if (determination["determination_status"] == "FINAL"
                and determination["determination_type"] == "QUANTITY_ADJUSTMENT"
                and determination.get("target_bid_item_id") == item["id"]):
            rate = determination["determined_unit_rate_cents"]
    if rate is None:
        return item["bid_unit_price_cents"]
    return rate


def payable_amount_cents(measurement, rate):
    return round_cents(dec(measurement["measured_quantity"]) * dec(rate))


# ---------------------------------------------------------------------------
# retention_settlement / absolute_retention_reconciliation
# ---------------------------------------------------------------------------

ANNUAL_PACE_CENTS = 4000000000
MONTHLY_PACE_CENTS = 333333333


def gross_payable_cents(project):
    return sum(m["payable_amount_cents"] for m in payable_measurements(project))


def retention_held_cents(project):
    gross = dec(gross_payable_cents(project))
    return round_cents(gross * dec(project["retention_rate_pct"]) / Decimal(100))


def pace_basis_retention_cents(project):
    gross = gross_payable_cents(project)
    if gross >= MONTHLY_PACE_CENTS:
        return 0
    return round_cents(dec(MONTHLY_PACE_CENTS) * dec(project["retention_rate_pct"]) / Decimal(100))


def retention_released_cents(reconciliation):
    if reconciliation is None:
        return 0
    if reconciliation["reconciliation_status"] != "CLOSED":
        return 0
    return reconciliation["retention_held_cents"]


# ---------------------------------------------------------------------------
# performance_bond_requirement
# ---------------------------------------------------------------------------

def statutory_pct(size_cents):
    if size_cents <= 1000000:
        return Decimal("0.50")
    if size_cents <= 5000000:
        return Decimal("0.75")
    if size_cents <= 10000000:
        return Decimal("1.00")
    return Decimal("1.25")


def required_bond_cents(bond, project):
    size = project["contract_value_cents"]
    if bond["bond_type"] == "PERFORMANCE":
        return round_cents(dec(size) * statutory_pct(size))
    if bond["bond_type"] == "PAYMENT":
        return round_cents(dec(size) * Decimal("1.00"))
    return round_cents(dec(project["total_bid_cents"]) * Decimal("0.10"))


# ---------------------------------------------------------------------------
# surety_exposure_capacity
# ---------------------------------------------------------------------------

def surety_consumed_cents(surety):
    consumed = sum(b["capacity_consumed_cents"] for b in db.BONDS.values()
                   if b["surety_id"] == surety["id"])
    consumed += sum(c["committed_amount_cents"] for c in db.COMMITMENTS.values()
                    if c["surety_id"] == surety["id"]
                    and c["commitment_status"] in ("RESERVED", "ACTIVE"))
    return consumed


def surety_available_cents(surety):
    return max(0, surety["aggregate_capacity_cents"] - surety_consumed_cents(surety))


def recalc_surety(surety, stamp=True):
    consumed = surety_consumed_cents(surety)
    surety["capacity_consumed_cents"] = consumed
    surety["available_capacity_cents"] = max(0, surety["aggregate_capacity_cents"] - consumed)
    surety["unavailable_capacity_cents"] = consumed
    if stamp:
        db.touch(surety)
    return surety


# ---------------------------------------------------------------------------
# dbe_participation_credit
# ---------------------------------------------------------------------------

def dbe_participation_pct(project):
    numerator = 0
    denominator = 0
    for quote in project_quotes(project):
        if quote["quote_status"] in ("CARRIED", "SELECTED"):
            denominator += quote["quoted_amount_cents"]
            if quote["unicap_registered"]:
                numerator += quote["quoted_amount_cents"]
    if denominator == 0:
        return 0.0
    return f2(dec(numerator) / dec(denominator) * Decimal(100))


def quote_dbe_credit_cents(quote):
    if quote["quote_status"] in ("CARRIED", "SELECTED") and quote["unicap_registered"]:
        return quote["quoted_amount_cents"]
    return 0


# ---------------------------------------------------------------------------
# notice_period_elapsed
# ---------------------------------------------------------------------------

NOTICE_LIMIT_DAYS = 30


def notice_days_elapsed(condition):
    delta = db.clock() - condition["reported_at"]
    return int(math.floor(delta.total_seconds() / 86400))


# ---------------------------------------------------------------------------
# crew_productivity_unit_cost
# ---------------------------------------------------------------------------

def crew_rate_cents(crew_day_labor_cents, crew_day_equipment_cents, daily_productivity_units):
    crew_day = dec(crew_day_labor_cents) + dec(crew_day_equipment_cents)
    return round_cents(crew_day / dec(daily_productivity_units))


# ---------------------------------------------------------------------------
# lien claim (payment-bond exposure to unpaid progress measurements)
# ---------------------------------------------------------------------------

def lien_claim_amount_cents(bond, project):
    if bond["bond_type"] != "PAYMENT":
        return 0
    return sum(m["payable_amount_cents"] for m in project_measurements(project)
               if m["measurement_status"] == "APPROVED")


# ---------------------------------------------------------------------------
# Roll-up writers
# ---------------------------------------------------------------------------

def refresh_project_bid(project, stamp=False):
    project["total_bid_cents"] = total_bid_cents(project)
    project["unbalanced_bid_score"] = float(unbalanced_bid_score(project))
    project["dbe_participation_pct"] = dbe_participation_pct(project)
    if stamp:
        db.touch(project)
    return project


def refresh_project_retention(project):
    reconciliation = non_closed_reconciliation(project)
    held = retention_held_cents(project)
    if reconciliation is not None:
        reconciliation["retention_held_cents"] = held
        reconciliation["pace_basis_retention_cents"] = pace_basis_retention_cents(project)
        reconciliation["final_contract_value_cents"] = (
            awarded_value_cents(project) + reconciliation["net_adjustment_cents"]
        )
        project["retention_balance_cents"] = held - reconciliation["retention_released_cents"]
    else:
        project["retention_balance_cents"] = held
    return held


def refresh_reconciliation(project):
    """Recompute the quantity variance roll-up and the retention settlement."""
    reconciliation = non_closed_reconciliation(project)
    if reconciliation is None:
        return None
    overrun, underrun = variance_counts(project)
    reconciliation["overrun_item_count"] = overrun
    reconciliation["underrun_item_count"] = underrun
    reconciliation["net_adjustment_cents"] = net_adjustment_cents(project)
    reconciliation["final_contract_value_cents"] = (
        awarded_value_cents(project) + reconciliation["net_adjustment_cents"]
    )
    reconciliation["retention_held_cents"] = retention_held_cents(project)
    reconciliation["pace_basis_retention_cents"] = pace_basis_retention_cents(project)
    reconciliation["retention_released_cents"] = retention_released_cents(reconciliation)
    project["retention_balance_cents"] = (
        reconciliation["retention_held_cents"] - reconciliation["retention_released_cents"]
    )
    return reconciliation
