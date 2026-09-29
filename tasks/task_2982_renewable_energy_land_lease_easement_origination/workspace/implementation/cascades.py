"""The four named recompute procedures of PRD section 2.8, plus the derived
counters they lean on.

Order between the four is fixed: acreage, then screening, then qualification,
then landowner posture. Every procedure refreshes updated_at and increments
version by 1 on each row it touches.
"""

import calc
from store import db, ordered, touch
from util import D, r2

D0 = D("0.00")


# --------------------------------------------------------------- selectors
def parcel_consents(parcel_id):
    return ordered([c for c in db.consents.values() if c["parcel_id"] == parcel_id])


def parcel_items(parcel_id):
    return ordered([i for i in db.curative_items.values()
                    if i["parcel_id"] == parcel_id])


def applicable_rules(county_fips):
    return ordered([r for r in db.setback_rules.values()
                    if r["jurisdiction_code"] == county_fips])


def agreement_payments(option_agreement_id):
    rows = [p for p in db.payments.values()
            if p["option_agreement_id"] == option_agreement_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["sequence_no"]))


def landowner_agreements(landowner_id):
    return ordered([a for a in db.options.values()
                    if a["landowner_id"] == landowner_id])


def landowner_parcels(landowner_id):
    return ordered([p for p in db.parcels.values()
                    if p["landowner_id"] == landowner_id])


def landowner_leases(landowner_id):
    return ordered([l for l in db.leases.values()
                    if l["landowner_id"] == landowner_id])


def lease_invoices(lease_id):
    return ordered([i for i in db.invoices.values()
                    if i["lease_agreement_id"] == lease_id])


def corridor_crossings(corridor_id):
    return ordered([c for c in db.crossings.values()
                    if c["corridor_id"] == corridor_id])


def parcel_bookings(parcel_id):
    return ordered([b for b in db.bookings.values()
                    if b["parcel_id"] == parcel_id])


# ------------------------------------------------- 1. acreage re-derivation
def recompute_parcel_acreage(parcel, bump=True):
    gross = D(parcel["gross_acres"])
    parcel["slope_excluded_acres"] = calc.slope_excluded(gross, parcel["slope_pct"])

    raw = D0
    for rule in applicable_rules(parcel["county_fips"]):
        raw = raw + calc.rule_term(gross, rule["encumbrance_rate_per_acre"])
    parcel["raw_setback_acres"] = r2(raw)

    released = D0
    for consent in parcel_consents(parcel["id"]):
        rule = db.setback_rules.get(consent["setback_rule_id"])
        if consent["status"] == "GRANTED" and rule is not None \
                and rule["consent_waivable"]:
            term = calc.consent_term(gross, rule["encumbrance_rate_per_acre"])
        else:
            term = D0
        if D(consent["released_acres"]) != term:
            consent["released_acres"] = term
            touch(consent)
        released = released + term
    parcel["consent_released_acres"] = r2(released)

    parcel["setback_encumbered_acres"] = calc.floor_acres(raw - released)
    parcel["buildable_acres"] = calc.floor_acres(
        gross - D(parcel["slope_excluded_acres"])
        - D(parcel["setback_encumbered_acres"])
    )
    if bump:
        touch(parcel)
    return parcel


# --------------------------------------------- 2. screening re-computation
def recompute_parcel_screening(parcel, bump=True):
    score = calc.screening_score(
        parcel["interconnection_distance_km"],
        parcel["resource_capacity_factor"],
        parcel["slope_pct"],
        parcel["title_condition_grade"],
        parcel["blocking_curative_open_count"],
        parcel["screen_mode"],
    )
    parcel["screening_score"] = score
    parcel["screening_tier"] = calc.screening_tier(score)
    if bump:
        touch(parcel)
    return parcel


# ------------------------------------------ curative counters on the parcel
def recount_curative_counters(parcel):
    """Folded into the enclosing step: never bumps the version by itself."""
    blocking_open = 0
    waived_blocking = 0
    cost = 0
    for item in parcel_items(parcel["id"]):
        if item["severity"] == "BLOCKING":
            if item["status"] in ("BLOCKED", "OPEN"):
                blocking_open += 1
            elif item["status"] == "WAIVED":
                waived_blocking += 1
        if item["status"] == "CLEARED":
            cost += int(item["curative_cost_cents"])
    parcel["blocking_curative_open_count"] = blocking_open
    parcel["waived_blocking_count"] = waived_blocking
    parcel["curative_cost_cents"] = cost
    return parcel


# ------------------------------------- 3. qualification re-evaluation gate
def reevaluate_parcel_qualification(parcel, bump=True):
    """Returns True when the parcel's status actually moved."""
    status = parcel["status"]
    if status in ("DISQUALIFIED", "OPTIONED", "LEASED"):
        return False
    buildable = D(parcel["buildable_acres"])
    tier = parcel["screening_tier"]
    blocking = int(parcel["blocking_curative_open_count"])
    if status == "SCREENING":
        if buildable >= calc.MIN_BUILDABLE_ACRES \
                and tier in ("PRIORITY", "STANDARD") and blocking == 0:
            parcel["status"] = "QUALIFIED"
            if bump:
                touch(parcel)
            return True
        return False
    if status == "QUALIFIED":
        if buildable < calc.MIN_BUILDABLE_ACRES \
                or tier in ("DEFERRED", "REJECTED") or blocking > 0:
            parcel["status"] = "SCREENING"
            if bump:
                touch(parcel)
            return True
    return False


# ------------------------------------ 4. landowner posture synchronisation
def landowner_posture(landowner_id):
    for lease in landowner_leases(landowner_id):
        if lease["recording_status"] == "RECORDED":
            return "UNDER_LEASE"
    for agreement in landowner_agreements(landowner_id):
        if agreement["status"] in ("EXECUTED", "EXERCISED"):
            return "UNDER_OPTION"
    for parcel in landowner_parcels(landowner_id):
        if parcel["status"] in ("QUALIFIED", "OPTIONED", "LEASED"):
            return "ENGAGED"
    return "PROSPECT"


def sync_landowner_posture(landowner, also_changed=False, bump=True):
    """Never touches total_paid_cents (PRD section 2.8)."""
    if landowner is None:
        return False
    posture = landowner_posture(landowner["id"])
    changed = posture != landowner["status"]
    landowner["status"] = posture
    if (changed or also_changed) and bump:
        touch(landowner)
    return changed


# ------------------------------------------------------- the whole chain
def run_parcel_chain(parcel, bump=True, sync_owner=True):
    recompute_parcel_acreage(parcel, bump=bump)
    recompute_parcel_screening(parcel, bump=bump)
    reevaluate_parcel_qualification(parcel, bump=bump)
    if sync_owner:
        sync_landowner_posture(db.landowners.get(parcel["landowner_id"]), bump=bump)
    return parcel


# ------------------------------------------------------- option-fee ledger
def recompute_agreement_total(agreement):
    total = 0
    for row in agreement_payments(agreement["id"]):
        if row["ledger_direction"] == "DEBIT_DEVELOPER":
            total += int(row["amount_cents"])
        else:
            total -= int(row["amount_cents"])
    agreement["total_option_paid_cents"] = total
    return total


def recompute_landowner_total(landowner):
    if landowner is None:
        return False
    total = 0
    for agreement in landowner_agreements(landowner["id"]):
        total += int(agreement["total_option_paid_cents"])
    changed = total != int(landowner["total_paid_cents"])
    landowner["total_paid_cents"] = total
    return changed


def next_sequence_no(option_agreement_id):
    rows = agreement_payments(option_agreement_id)
    if not rows:
        return 1
    return max(int(r["sequence_no"]) for r in rows) + 1


# ------------------------------------------------------- other recomputes
def recount_granted_crossings(corridor):
    corridor["granted_crossing_count"] = len(
        [c for c in corridor_crossings(corridor["id"]) if c["status"] == "GRANTED"]
    )
    return corridor


def recompute_last_paid_invoice_year(lease):
    years = [int(i["period_year"]) for i in lease_invoices(lease["id"])
             if i["status"] == "PAID"]
    lease["last_paid_invoice_year"] = max(years) if years else 0
    return lease["last_paid_invoice_year"]
