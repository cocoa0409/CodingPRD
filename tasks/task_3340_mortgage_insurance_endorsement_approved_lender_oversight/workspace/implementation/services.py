"""Cross-entity business logic: net worth rule, cascades, sweeps, waterfalls."""
from store import db, bump, logical_date, logical_now
from util import parse_date, parse_dt, add_months_dt, rhu

# --- net worth (SCAFFOLD calculations.required_net_worth) -------------------
SMALL_LENDER_FLOOR_CENTS = 50000000
STANDARD_FLOOR_CENTS = 100000000
SMALL_LENDER_VOLUME_CAP_CENTS = 5000000000


def recompute_net_worth(lender):
    """Recompute net_worth_variant and required_net_worth_cents in place.

    This is a computed-field reconciliation: it does NOT bump the lender's
    version (version increments only where the workflow says so).
    """
    if (lender["institution_type"] == "MORTGAGEE_NONSUPERVISED"
            and lender["endorsed_volume_cents"] < SMALL_LENDER_VOLUME_CAP_CENTS):
        lender["net_worth_variant"] = "SMALL_LENDER"
        lender["required_net_worth_cents"] = SMALL_LENDER_FLOOR_CENTS
    else:
        lender["net_worth_variant"] = "STANDARD"
        lender["required_net_worth_cents"] = max(
            STANDARD_FLOOR_CENTS, rhu(lender["endorsed_volume_cents"], 100))


# --- finders -----------------------------------------------------------------
def cases_of_lender(lender_id):
    return [c for c in db.cases.values() if c["lender_id"] == lender_id]


def filings_of_lender(lender_id):
    return [f for f in db.filings.values() if f["lender_id"] == lender_id]


def appraisals_of_case(case_id):
    return [a for a in db.appraisals.values() if a["loan_case_id"] == case_id]


def escrows_of_case(case_id):
    return [e for e in db.escrows.values() if e["loan_case_id"] == case_id]


def mip_entries_of_case(case_id):
    return [e for e in db.mip_entries.values() if e["loan_case_id"] == case_id]


def reviews_of_case(case_id):
    return [r for r in db.reviews.values() if r["loan_case_id"] == case_id]


def defects_of_review(review_id):
    return [d for d in db.defects.values() if d["review_id"] == review_id]


def agreements_of_case(case_id):
    return [a for a in db.agreements.values() if a["loan_case_id"] == case_id]


def actions_of_case(case_id):
    return [a for a in db.actions.values() if a["loan_case_id"] == case_id]


def claims_of_case(case_id):
    return [c for c in db.claims.values() if c["loan_case_id"] == case_id]


# --- mip retained (compensating invariant) ------------------------------------
def recompute_mip_retained(case):
    """mip_retained_cents = sum(amount_cents over entries with status != CANCELLED).

    REFUND rows carry negative amounts and reduce the total through the same
    summation. Computed-field reconciliation: no version bump on the case.
    """
    case["mip_retained_cents"] = sum(
        e["amount_cents"] for e in mip_entries_of_case(case["id"])
        if e["status"] != "CANCELLED")


# --- clock sweeps (POST /_clock/set_current_utc side effects) -----------------
def sweep_clock():
    d = logical_date()
    for a in db.appraisals.values():
        if a["status"] == "ACCEPTED" and parse_date(a["expiry_date"]) <= d:
            a["status"] = "EXPIRED"
            bump(a)
    for e in db.escrows.values():
        if e["status"] == "OPEN" and parse_date(e["end_date"]) < d:
            e["status"] = "EXPIRED"
            bump(e)


# --- cascade B: lender suspension / reinstatement -----------------------------
def cascade_suspend(lender):
    """Hop 1: UNDERWRITE_SUBMITTED cases -> BLOCKED.
    Hop 2 (caused by hop 1): their OPEN escrows -> FROZEN(SUSPENSION)."""
    for case in cases_of_lender(lender["id"]):
        if case["status"] == "UNDERWRITE_SUBMITTED":
            case["status"] = "BLOCKED"
            bump(case)
            for esc in escrows_of_case(case["id"]):
                if esc["status"] == "OPEN":
                    esc["status"] = "FROZEN"
                    esc["freeze_origin"] = "SUSPENSION"
                    bump(esc)


def cascade_reinstate(lender):
    """Unblock: BLOCKED cases -> UNDERWRITE_SUBMITTED; their escrows frozen by
    SUSPENSION -> OPEN (origin cleared)."""
    for case in cases_of_lender(lender["id"]):
        if case["status"] == "BLOCKED":
            case["status"] = "UNDERWRITE_SUBMITTED"
            bump(case)
            for esc in escrows_of_case(case["id"]):
                if esc["status"] == "FROZEN" and esc["freeze_origin"] == "SUSPENSION":
                    esc["status"] = "OPEN"
                    esc["freeze_origin"] = None
                    bump(esc)


# --- cascade A: TIER_1 defect confirmed ---------------------------------------
def cascade_impairment(case):
    """Hop 2: case endorsement_integrity -> IMPAIRED.
    Hop 3: every OPEN escrow of the case -> FROZEN(IMPAIRMENT)."""
    case["endorsement_integrity"] = "IMPAIRED"
    bump(case)
    for esc in escrows_of_case(case["id"]):
        if esc["status"] == "OPEN":
            esc["status"] = "FROZEN"
            esc["freeze_origin"] = "IMPAIRMENT"
            bump(esc)


def restore_integrity(case):
    """Review close with no unremediated CONFIRMED TIER_1: SOUND + unfreeze
    IMPAIRMENT-frozen escrows."""
    if case["endorsement_integrity"] == "IMPAIRED":
        case["endorsement_integrity"] = "SOUND"
        bump(case)
    for esc in escrows_of_case(case["id"]):
        if esc["status"] == "FROZEN" and esc["freeze_origin"] == "IMPAIRMENT":
            esc["status"] = "OPEN"
            esc["freeze_origin"] = None
            bump(esc)


# --- loss mitigation waterfall -------------------------------------------------
TIER_OF = {
    "REPAYMENT_PLAN": 1,
    "SPECIAL_FORBEARANCE": 2,
    "LOAN_MODIFICATION": 3,
    "PARTIAL_CLAIM": 4,
    "PRE_FORECLOSURE_SALE": 5,
    "DEED_IN_LIEU": 6,
}


def waterfall_exhausted(case_id):
    """Every tier 1..6 holds an action with status INFEASIBLE or FAILED."""
    acts = actions_of_case(case_id)
    for tier in range(1, 7):
        if not any(a["tier"] == tier and a["status"] in ("INFEASIBLE", "FAILED")
                   for a in acts):
            return False
    return True
