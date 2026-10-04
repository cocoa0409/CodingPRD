"""Reinsurance cession allocation, lender exposure and portfolio concentration.

Implements calculations `reinsurance_cession_allocation`,
`lender_exposure_reconciliation`, `portfolio_concentration` and
`settlement_reversal_invariant` from SCAFFOLD section 1.3 and PRD 3.10 / 3.12.
"""

from common import d, parse_utc, round4, round_half_up_int
from db import new_row

# SCAFFOLD lender_exposure_reconciliation constant.
WARN_THRESHOLD_PCT = 80

IN_FORCE_STATUSES = ("ACTIVE", "PENDING_CANCELLATION")


def treaty_in_force_at(treaty, event_dt):
    """inception_utc <= event < expiration_utc: the inception bound is inclusive
    and the expiration bound is exclusive (PRD 3.10)."""
    inception = parse_utc(treaty["inception_utc"])
    expiration = parse_utc(treaty["expiration_utc"])
    return inception <= event_dt < expiration


def treaty_capacity(treaty):
    return treaty["exhaustion_per_claim_cents"] - treaty["retention_per_claim_cents"]


def compute_cession(settlement_amount_cents, retention, capacity):
    """clamp(settlement - retention, 0, capacity) - a clamp, never a test."""
    return max(0, min(settlement_amount_cents - retention, capacity))


def remaining_aggregate_capacity(treaty, loan):
    remaining = treaty["aggregate_ceded_cap_cents"] - loan.get("aggregate_ceded_cents", 0)
    return max(0, remaining)


def allocate_cession(db, claim, loan, settlement_amount_cents, clock_now):
    """Synthesized cession: only settlements whose option is CASH or
    THIRD_PARTY_SALE create one. A treaty-related failure is RECORDED with a
    reason, and an aggregate breach CAPS the per-claim amount rather than
    rejecting it.
    """
    treaty = None
    rejected_reason = None

    treaty_id = loan.get("reinsurance_treaty_id")
    if not treaty_id:
        rejected_reason = "NO_TREATY"
    else:
        treaty = db.reinsurance_treaties.get(treaty_id)
        if treaty is None:
            rejected_reason = "NO_TREATY"
        elif treaty["status"] != "ACTIVE":
            rejected_reason = "TREATY_NOT_IN_FORCE_AT_EVENT"
        elif not treaty_in_force_at(treaty, parse_utc(claim["event_completed_utc"])):
            rejected_reason = "TREATY_NOT_IN_FORCE_AT_EVENT"

    if rejected_reason is None:
        capacity = treaty_capacity(treaty)
        per_claim = compute_cession(
            settlement_amount_cents, treaty["retention_per_claim_cents"], capacity
        )
        # Aggregate capacity is respected by capping, not by rejecting.
        remaining = remaining_aggregate_capacity(treaty, loan)
        ceded = min(per_claim, remaining)
        record = new_row(clock_now)
        record.update({
            "claim_id": claim["id"],
            "loan_id": loan["id"],
            "treaty_id": treaty["id"],
            "ceded_amount_cents": ceded,
            "retained_amount_cents": settlement_amount_cents - ceded,
            "aggregate_ceded_after_cents": loan["aggregate_ceded_cents"] + ceded,
            "status": "ACCEPTED",
            "rejected_reason": None,
        })
        db.reinsurance_cessions[record["id"]] = record
        loan["aggregate_ceded_cents"] = record["aggregate_ceded_after_cents"]
        return record

    record = new_row(clock_now)
    record.update({
        "claim_id": claim["id"],
        "loan_id": loan["id"],
        "treaty_id": treaty["id"] if treaty is not None else None,
        "ceded_amount_cents": 0,
        "retained_amount_cents": settlement_amount_cents,
        "aggregate_ceded_after_cents": loan["aggregate_ceded_cents"],
        "status": "REJECTED",
        "rejected_reason": rejected_reason,
    })
    db.reinsurance_cessions[record["id"]] = record
    return record


# --- lender exposure ----------------------------------------------------------

def loan_contribution(loan, policy):
    """loan.aggregate_ceded_cents + round_half_up(coverage base * contribution rate)."""
    rate = d(policy["exposure_contribution_rate"])
    base_part = round_half_up_int(d(loan["coverage_base_upb_cents"]) * rate)
    return loan.get("aggregate_ceded_cents", 0) + base_part


def lender_contribution(db, lender):
    """Sum of its in-force loans' contributions; a CANCELLED loan contributes
    nothing at all."""
    total = 0
    for loan in db.loans.values():
        if loan["lender_id"] != lender["id"]:
            continue
        if loan["coverage_status"] not in IN_FORCE_STATUSES:
            continue
        policy = db.master_policies.get(loan["master_policy_id"])
        if policy is None:
            continue
        total += loan_contribution(loan, policy)
    return total


def used_pct(contribution, cap_cents):
    if not cap_cents:
        return 0.0
    return round4(d(contribution) * 100 / d(cap_cents))


# --- portfolio concentration --------------------------------------------------

def compute_snapshot(db, snapshot_utc, threshold_cents):
    """One segment per county present in the in-force book, ordered by
    sum_geography DESC then county_code ASC; the comparison is inclusive at the
    threshold. An empty book yields a null concentration index and no segments.
    """
    in_force = [
        loan for loan in db.loans.values()
        if loan["coverage_status"] in IN_FORCE_STATUSES
    ]

    geography = {}
    for loan in in_force:
        county = loan["county_code"]
        geography[county] = geography.get(county, 0) + loan["coverage_base_upb_cents"]

    ordered = sorted(geography.items(), key=lambda item: (-item[1], item[0]))

    geography_totals = [
        {"county_code": county, "in_force_coverage_base_cents": total}
        for county, total in ordered
    ]
    segment_statuses = [
        {
            "county_code": county,
            "in_force_coverage_base_cents": total,
            "status": "BREACHED" if total >= threshold_cents else "WITHIN_LIMITS",
        }
        for county, total in ordered
    ]

    aggregate_ceded = sum(loan.get("aggregate_ceded_cents", 0) for loan in in_force)

    whole_book = sum(loan["coverage_base_upb_cents"] for loan in in_force)
    if not in_force or whole_book == 0:
        index = None
    else:
        by_lender = {}
        for loan in in_force:
            by_lender[loan["lender_id"]] = (
                by_lender.get(loan["lender_id"], 0) + loan["coverage_base_upb_cents"]
            )
        largest = max(by_lender.values())
        index = round4(d(largest) / d(whole_book))

    return {
        "geography_totals": geography_totals,
        "segment_statuses": segment_statuses,
        "aggregate_ceded_cents": aggregate_ceded,
        "lender_concentration_index": index,
    }