"""Derived (computed) values: the two conserved quantities, the aggregates the
PRD defines as live views over the ledger, and the eligibility assessment.

Nothing in here is stored.  Every value is recomputed from the primary records
on each read so that the invariants of PRD 2.10 hold by construction.
"""

import config
import timeutil
from money import floor_ratio
from store import ordered, store

# ------------------------------------------------------------------ navigation


def partner_of(record):
    return store.partners.get(record.get("partner_id"))


def product_of_enrollment(enrollment):
    return store.products.get(enrollment["product_id"])


def premises_of_enrollment(enrollment):
    return store.premises.get(enrollment["premises_id"])


def enrollment_of_claim(claim):
    return store.enrollments.get(claim["enrollment_id"])


def product_of_claim(claim):
    enrollment = enrollment_of_claim(claim)
    return product_of_enrollment(enrollment) if enrollment else None


def claim_of_dispatch(dispatch):
    return store.claims.get(dispatch["claim_id"])


def partner_of_enrollment(enrollment):
    product = product_of_enrollment(enrollment)
    return store.partners.get(product["partner_id"]) if product else None


def enrollments_of_premises(premises_id):
    return ordered(store.enrollments, lambda e: e["premises_id"] == premises_id)


def claims_of_enrollment(enrollment_id):
    return ordered(store.claims, lambda c: c["enrollment_id"] == enrollment_id)


def dispatches_of_claim(claim_id):
    return ordered(store.dispatches, lambda d: d["claim_id"] == claim_id)


def dispatches_of_enrollment(enrollment_id):
    out = []
    for claim in claims_of_enrollment(enrollment_id):
        out.extend(dispatches_of_claim(claim["id"]))
    return sorted(out, key=lambda d: (d["created_at"], d["_seq"]))


# ---------------------------------------------------------------- ledger views


def ledger_of_enrollment(enrollment_id):
    return ordered(store.ledger_entries, lambda r: r["enrollment_id"] == enrollment_id)


def annual_benefit_used_cents(enrollment):
    """Signed sum of benefit rows stamped with the policy's current cap year."""
    total = 0
    for row in ledger_of_enrollment(enrollment["id"]):
        if row["ledger_kind"] != "BENEFIT":
            continue
        if row["cap_year_start"] != enrollment["cap_year_start"]:
            continue
        total += row["amount_cents"]
    return total


def occurrence_used_cents(claim):
    """The same benefit sum, restricted to the claim's occurrence group."""
    enrollment = enrollment_of_claim(claim)
    if enrollment is None:
        return 0
    group = {c["id"] for c in occurrence_group(claim)}
    total = 0
    for row in ledger_of_enrollment(enrollment["id"]):
        if row["ledger_kind"] != "BENEFIT":
            continue
        if row["cap_year_start"] != enrollment["cap_year_start"]:
            continue
        if row["claim_id"] in group:
            total += row["amount_cents"]
    return total


def claim_benefit_paid_cents(claim):
    total = 0
    for row in store.ledger_entries.values():
        if row["claim_id"] == claim["id"] and row["ledger_kind"] == "BENEFIT":
            total += row["amount_cents"]
    return total


def occurrence_group(claim):
    root = claim.get("occurrence_root_claim_id") or claim["id"]
    return ordered(store.claims, lambda c: (c.get("occurrence_root_claim_id") or c["id"]) == root)


def annual_benefit_reserved_cents(enrollment):
    """Provisional estimates held by the policy's still-open dispatches."""
    total = 0
    for dispatch in dispatches_of_enrollment(enrollment["id"]):
        if dispatch["status"] in config.OPEN_DISPATCH_STATUSES:
            total += dispatch.get("estimated_benefit_cents") or 0
    return total


def premium_collected_cents(enrollment):
    total = 0
    for row in ledger_of_enrollment(enrollment["id"]):
        if row["ledger_kind"] == "CASH" and row["entry_type"] in config.CASH_INFLOW_ENTRY_TYPES:
            total += row["amount_cents"]
    return total


def premium_refunded_cents(enrollment):
    total = 0
    for row in ledger_of_enrollment(enrollment["id"]):
        if row["ledger_kind"] == "CASH" and row["entry_type"] in config.CASH_OUTFLOW_ENTRY_TYPES:
            total += row["amount_cents"]
    return abs(total)


# ------------------------------------------------------------ counters / holds


def contractor_open_dispatch_count(contractor):
    count = 0
    for dispatch in store.dispatches.values():
        if dispatch["contractor_id"] == contractor["id"] and dispatch["status"] in config.OPEN_DISPATCH_STATUSES:
            count += 1
    return count


def partner_enrolled_premises_count(partner):
    addresses = set()
    for enrollment in store.enrollments.values():
        if enrollment["coverage_status"] not in config.LIVE_COVERAGE_STATUSES:
            continue
        product = product_of_enrollment(enrollment)
        if product is None or product["partner_id"] != partner["id"]:
            continue
        addresses.add(enrollment["premises_id"])
    return len(addresses)


def premises_mail_count_current_year(premises):
    year = store.today().year
    count = 0
    for drop in premises.get("_mail_history", []):
        if drop["drop_date"].year == year:
            count += 1
    return count


def premises_has_retention_hold(premises):
    for enrollment in enrollments_of_premises(premises["id"]):
        if enrollment.get("retention_hold"):
            return True
    return False


def premises_suppression_reason(premises):
    """Standing suppression: the campaign-scoped reasons are not evaluated here."""
    partner = partner_of(premises)
    if premises.get("do_not_mail"):
        return "DNM_REQUEST"
    if premises.get("address_status") == "BAD":
        return "BAD_ADDRESS"
    if premises.get("regulator_hold"):
        return "REGULATOR_COMPLAINT_OPEN"
    if premises_has_retention_hold(premises):
        return "OPEN_APPEAL"
    if partner is not None and premises_mail_count_current_year(premises) >= partner["max_mailings_per_year"]:
        return "CONTACT_FREQUENCY_CAP"
    return "NONE"


def premises_regulator_hold_still_open(premises_id):
    """True when any complaint citing a policy at this address is still open."""
    for complaint in store.complaints.values():
        if complaint["status"] not in config.OPEN_COMPLAINT_STATUSES:
            continue
        enrollment_id = complaint.get("enrollment_id")
        if not enrollment_id:
            continue
        enrollment = store.enrollments.get(enrollment_id)
        if enrollment is not None and enrollment["premises_id"] == premises_id:
            return True
    return False


# ------------------------------------------------------- eligibility & pools


def eligibility_assessment(claim):
    """First failing check in the pinned order of PRD 3.5."""
    enrollment = enrollment_of_claim(claim)
    if enrollment is None:
        return "COVERAGE_INACTIVE"
    product = product_of_enrollment(enrollment)
    premises = premises_of_enrollment(enrollment)
    if enrollment["coverage_status"] in ("SUSPENDED_NONPAY", "CANCELLED", "LAPSED"):
        return "COVERAGE_INACTIVE"
    if product is not None and premises is not None:
        covered = config.COVERED_DEFECT_LOCATIONS.get(product["ownership_boundary"], [])
        if claim["defect_location"] not in covered:
            return "OWNERSHIP_INELIGIBLE"
        if product["required_owned_segment"] not in premises["owned_segments"]:
            return "OWNERSHIP_INELIGIBLE"
    if premises is not None and premises.get("known_defect_reported_at"):
        known = timeutil.parse_instant(premises["known_defect_reported_at"])
        enrolled = timeutil.parse_instant(enrollment["enrollment_date"])
        if known is not None and enrolled is not None and known < enrolled:
            return "PRE_EXISTING"
    reported = timeutil.parse_instant(claim["reported_at"])
    effective = timeutil.parse_instant(enrollment["coverage_effective_at"])
    if reported is not None and effective is not None and reported < effective:
        return "WAITING_PERIOD"
    if enrollment["cap_status"] == "ANNUAL_CAP_EXHAUSTED":
        return "CAP_EXHAUSTED"
    return "ELIGIBLE"


def annual_pool_cents(enrollment):
    product = product_of_enrollment(enrollment)
    return product["annual_cap_cents"] - annual_benefit_used_cents(enrollment)


def occurrence_pool_cents(claim):
    product = product_of_claim(claim)
    return product["per_occurrence_cap_cents"] - occurrence_used_cents(claim)


def benefit_pool_cents(claim):
    """The waterfall's ceiling: the lesser of the two remaining allowances."""
    enrollment = enrollment_of_claim(claim)
    return min(occurrence_pool_cents(claim), annual_pool_cents(enrollment))


def capacity_headroom_pct(contractor):
    maximum = contractor["max_open_dispatches"]
    open_count = contractor_open_dispatch_count(contractor)
    return floor_ratio(100 * (maximum - open_count), maximum)


def rate_score(contractor):
    return max(0, 100 - floor_ratio(contractor["hourly_rate_cents"], 200))
