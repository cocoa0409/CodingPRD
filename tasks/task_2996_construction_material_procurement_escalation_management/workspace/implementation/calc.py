"""The seven calculation rules (SCAFFOLD 1.3 / PRD 3.x)."""

from decimal import Decimal

from store import store
from util import (
    D,
    add_days,
    full_months_between,
    month_key,
    q2,
    q4,
    whole_days_between,
)

# --- release_for_fabrication_schedule ------------------------------------
LONG_LEAD_THRESHOLD_DAYS = 90
RFF_CRITICAL_FLOAT_DAYS = 0
RFF_AT_RISK_FLOAT_DAYS = 14

# --- supplier_exposure_score --------------------------------------------
TARIFF_WEIGHT = Decimal("1.6")
TARIFF_COMPONENT_CAP = Decimal("40")
EVENT_WEIGHT = Decimal("20")
EVENT_COMPONENT_CAP = Decimal("40")
NON_DOMESTIC_PENALTY = Decimal("20")
EXPOSURE_HIGH_THRESHOLD = Decimal("60")
EXPOSURE_ELEVATED_THRESHOLD = Decimal("30")

# --- buyout_variance -----------------------------------------------------
MAX_BUYOUT_OVERRUN_PCT = Decimal("15")

# --- storage_carrying_cost ----------------------------------------------
INSURANCE_RATE_PCT = Decimal("0.0175")
HANDLING_BUFFER_DAYS = 3

# --- substantiated_escalation_amount -------------------------------------
SMALL_CLAIM_FEE_PCT = Decimal("5.0")
MID_CLAIM_FEE_PCT = Decimal("3.5")
LARGE_CLAIM_FEE_PCT = Decimal("2.0")
TIER_1_CEILING = Decimal("10000")
TIER_2_CEILING = Decimal("50000")

# --- documentation_completeness -----------------------------------------
MANDATORY_DOC_TYPES = ("BAILMENT_AGREEMENT", "INSURANCE_CERTIFICATE", "LIEN_WAIVER")

MAX_NEGOTIATION_ROUNDS = 3
MAX_SUBSTITUTION_ROUNDS = 2


# =========================================================================
# release_for_fabrication_schedule
# =========================================================================
def package_lead_time_days(pkg):
    return (
        int(pkg["submittal_review_days"])
        + int(pkg["fabrication_duration_days"])
        + int(pkg["delivery_transit_days"])
    )


def package_is_long_lead(pkg):
    return (
        int(pkg["fabrication_duration_days"]) + int(pkg["delivery_transit_days"])
    ) >= LONG_LEAD_THRESHOLD_DAYS


def package_release_date(pkg):
    return add_days(pkg["required_onsite_date"], -package_lead_time_days(pkg))


def package_float_days(pkg):
    return whole_days_between(store.clock, package_release_date(pkg))


def package_risk_band(float_days):
    if float_days <= RFF_CRITICAL_FLOAT_DAYS:
        return "CRITICAL"
    if float_days <= RFF_AT_RISK_FLOAT_DAYS:
        return "AT_RISK"
    return "ON_TRACK"


def package_open_quote_count(package_id):
    return sum(
        1
        for q in store.quotes.values()
        if q["material_package_id"] == package_id and q["status"] == "OPEN"
    )


# =========================================================================
# supplier_exposure_score
# =========================================================================
def supplier_events_in_scope(supplier_id, forward):
    events = [
        e
        for e in store.disruptions.values()
        if e["supplier_id"] == supplier_id and e["status"] == "OPEN"
    ]
    if forward:
        return events
    return [e for e in events if e["effective_date"] <= store.clock]


def supplier_exposure(supplier, forward=False):
    """Returns (score Decimal, band str, in_scope_open_event_count int)."""
    events = supplier_events_in_scope(supplier["id"], forward)
    effective_tariff = D(supplier["declared_tariff_rate_pct"])
    for event in events:
        if event["event_type"] == "TARIFF_IMPOSED":
            rate = event.get("tariff_rate_pct")
            rate = D(0) if rate is None else D(rate)
            if rate > effective_tariff:
                effective_tariff = rate
    tariff_component = min(TARIFF_COMPONENT_CAP, TARIFF_WEIGHT * effective_tariff)
    event_component = min(EVENT_COMPONENT_CAP, EVENT_WEIGHT * Decimal(len(events)))
    geo_component = Decimal("0") if supplier["country_of_origin"] == "US" else NON_DOMESTIC_PENALTY
    score = q2(tariff_component + event_component + geo_component)
    if score >= EXPOSURE_HIGH_THRESHOLD:
        band = "HIGH"
    elif score >= EXPOSURE_ELEVATED_THRESHOLD:
        band = "ELEVATED"
    else:
        band = "LOW"
    return score, band, len(events)


# =========================================================================
# buyout_variance / the project money ledger
# =========================================================================
def project_packages(project_id):
    return [p for p in store.packages.values() if p["project_id"] == project_id]


def project_commitments(project_id):
    package_ids = set(p["id"] for p in project_packages(project_id))
    return [
        c for c in store.commitments.values() if c["material_package_id"] in package_ids
    ]


def project_rollups(project):
    packages = project_packages(project["id"])
    commitments = project_commitments(project["id"])
    live = [c for c in commitments if c["commitment_status"] in ("COMMITTED", "CLOSED")]

    estimated_total_cost = q2(sum((p["estimated_cost"] for p in packages), Decimal("0")))
    committed_total_cost = q2(
        sum((c["committed_base_cost"] + c["escalation_accrued"] for c in live), Decimal("0"))
    )
    bought_out_estimate = q2(
        sum(
            (p["estimated_cost"] for p in packages if p["status"] in ("BOUGHT_OUT", "CLOSED")),
            Decimal("0"),
        )
    )
    escalation_committed = q2(sum((c["escalation_accrued"] for c in live), Decimal("0")))
    live_ids = set(c["id"] for c in commitments)
    recovered = q2(
        sum(
            (
                co["substantiated_amount"]
                for co in store.change_orders.values()
                if co["purchase_commitment_id"] in live_ids
                and co["status"] == "OWNER_APPROVED"
            ),
            Decimal("0"),
        )
    )
    return {
        "estimated_total_cost": estimated_total_cost,
        "committed_total_cost": committed_total_cost,
        "buyout_variance": q2(estimated_total_cost - committed_total_cost),
        "bought_out_variance": q2(bought_out_estimate - committed_total_cost),
        "escalation_contingency_committed": escalation_committed,
        "escalation_contingency_remaining": q2(
            project["escalation_contingency_budget"] - escalation_committed
        ),
        "change_order_recovered_amount": recovered,
    }


# =========================================================================
# escalation_adjustment
# =========================================================================
def readings_for(index_code):
    return [r for r in store.index_readings.values() if r["index_code"] == index_code]


def reading_lookback(index_code, period):
    """The reading with the greatest period <= the supplied period."""
    candidates = [r for r in readings_for(index_code) if r["period"] <= period]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["period"])


def reading_exact(index_code, period):
    for reading in readings_for(index_code):
        if reading["period"] == period:
            return reading
    return None


def escalation_amount(committed_base_cost, agreement, current_index_value):
    """The four chained operations with exactly one intermediate rounding."""
    base = D(agreement["baseline_index_value"])
    index_delta_pct = q4((D(current_index_value) - base) / base * Decimal("100"))
    eligible = index_delta_pct - D(agreement["deadband_pct"])
    if eligible < 0:
        eligible = Decimal("0")
    capped = min(eligible, D(agreement["cap_pct"]))
    shared = capped * (Decimal("1") - D(agreement["contractor_share_pct"]) / Decimal("100"))
    return q2(D(committed_base_cost) * shared / Decimal("100"))


# =========================================================================
# storage_carrying_cost
# =========================================================================
def carrying_cost(arrangement):
    if arrangement["status"] == "DRAFT":
        return q2(0)
    as_of = arrangement["carrying_cost_frozen_at"] or store.clock
    months = full_months_between(arrangement["stored_from"], as_of)
    if months <= 0:
        return q2(0)
    stored_value = D(arrangement["stored_value"])
    monthly_storage = q2(stored_value * D(arrangement["monthly_storage_rate_pct"]) / Decimal("100"))
    monthly_insurance = q2(stored_value * INSURANCE_RATE_PCT / Decimal("100"))
    per_month = monthly_storage + monthly_insurance
    return q2(per_month * Decimal(months))


# =========================================================================
# documentation_completeness
# =========================================================================
def arrangement_documents(arrangement_id):
    return [
        d for d in store.documents.values() if d["storage_arrangement_id"] == arrangement_id
    ]


def document_qualifies(doc, arrangement):
    if doc["revoked"]:
        return False
    if not doc["verified"]:
        return False
    if not (doc["effective_date"] <= store.clock < doc["expires_at"]):
        return False
    if doc["doc_type"] == "INSURANCE_CERTIFICATE":
        if D(doc["coverage_amount"]) < D(arrangement["stored_value"]):
            return False
    return True


def documentation_completeness(arrangement):
    """Returns (verified_doc_type_count, documentation_status)."""
    types = set()
    for doc in arrangement_documents(arrangement["id"]):
        if doc["doc_type"] in MANDATORY_DOC_TYPES and document_qualifies(doc, arrangement):
            types.add(doc["doc_type"])
    count = len(types)
    return count, ("COMPLETE" if count == len(MANDATORY_DOC_TYPES) else "INCOMPLETE")


# =========================================================================
# substantiated_escalation_amount
# =========================================================================
def substantiation(gross_documented_amount, claimed_amount):
    """Returns (admin_fee_pct, admin_fee_amount, substantiated_amount)."""
    gross = D(gross_documented_amount)
    if gross < TIER_1_CEILING:
        rate = SMALL_CLAIM_FEE_PCT
    elif gross < TIER_2_CEILING:
        rate = MID_CLAIM_FEE_PCT
    else:
        rate = LARGE_CLAIM_FEE_PCT
    fee = q2(gross * rate / Decimal("100"))
    running_total = gross + fee
    substantiated = q2(min(running_total, D(claimed_amount)))
    return rate, fee, substantiated
