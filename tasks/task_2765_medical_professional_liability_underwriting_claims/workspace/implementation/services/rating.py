"""Risk classification, credit/surcharge stacking, term rating and policy roll-ups.

PRD 3.2 (classification), 3.3 (credit and surcharge), 3.4 (rating ladder),
2.10 (premium ledger, compound policy status and the re-rating cascade).
"""
from decimal import Decimal

import constants as C
from store import db, sorted_records, touch
from val import ZERO, d, r2, r4


# --- collection helpers -----------------------------------------------------
def policies_of(insured_id):
    return sorted_records(
        [p for p in db.policies.values() if p["insured_id"] == insured_id]
    )


def terms_of(policy_id):
    return sorted_records(
        [t for t in db.policy_terms.values() if t["policy_id"] == policy_id]
    )


def tails_of(policy_id):
    return sorted_records(
        [t for t in db.tail_endorsements.values() if t["policy_id"] == policy_id]
    )


def enrollments_of(insured_id):
    return sorted_records(
        [e for e in db.enrollments.values() if e["insured_id"] == insured_id]
    )


def peer_cases_of(insured_id):
    return sorted_records(
        [c for c in db.peer_review_cases.values() if c["insured_id"] == insured_id]
    )


def claims_of(insured_id):
    return sorted_records(
        [c for c in db.claims.values() if c["insured_id"] == insured_id]
    )


def policy_of_term(term):
    return db.policies.get(term["policy_id"]) if term else None


def responding_term(claim):
    term_id = claim.get("policy_term_id")
    return db.policy_terms.get(term_id) if term_id else None


def responding_policy(claim):
    term = responding_term(claim)
    return policy_of_term(term) if term else None


# --- PRD 3.2: risk classification ------------------------------------------
def risk_band(score):
    if score < C.RISK_BAND_R2_MIN:
        return "R1"
    if score < C.RISK_BAND_R3_MIN:
        return "R2"
    if score < C.RISK_BAND_R4_MIN:
        return "R3"
    return "R4"


def classify(insured, variant):
    """Return (score, code, factor) under the requested rating variant."""
    specialty = db.specialty_classes.get(insured["specialty_class_id"])
    hazard = specialty["hazard_index"] if specialty else ZERO
    procedure = r4(Decimal(insured["high_severity_procedure_pct"]) / C.PROCEDURE_DIVISOR)
    raw_history = C.CLOSED_PAID_WEIGHT * Decimal(insured["closed_paid_claim_count"])
    if variant == "RENEWAL_PROSPECTIVE":
        raw_history += C.OPEN_CLAIM_WEIGHT * Decimal(insured["open_claim_count"])
    history = min(C.HISTORY_COMPONENT_CAP, raw_history)
    score = r2(
        C.W_SPECIALTY * Decimal(hazard)
        + C.W_PROCEDURE * procedure
        + C.W_HISTORY * history
    )
    code = risk_band(score)
    return score, code, C.RISK_CLASS_FACTOR[code]


def apply_classification(insured):
    """The insured always stores the UNDERWRITING_SNAPSHOT reading."""
    score, code, factor = classify(insured, "UNDERWRITING_SNAPSHOT")
    insured["risk_class_score"] = score
    insured["risk_class_code"] = code
    insured["risk_class_factor"] = factor
    touch(insured)


def recompute_claim_counters(insured):
    closed_paid = 0
    open_claims = 0
    for claim in claims_of(insured["id"]):
        if claim["claim_status"] in ("RESOLVED", "CLOSED") and claim["paid_indemnity"] > ZERO:
            closed_paid += 1
        if claim["claim_status"] in ("INTAKE", "INVESTIGATION", "LITIGATION") and claim[
            "coverage_status"
        ] != "DENIED":
            open_claims += 1
    insured["closed_paid_claim_count"] = closed_paid
    insured["open_claim_count"] = open_claims
    apply_classification(insured)


# --- PRD 3.3: stacked credit and surcharge position -------------------------
def stacked_credit(insured, as_of):
    """The capped credit percentage carried as of the given calendar date."""
    cutoff = d(as_of)
    winners = {}
    for enrollment in enrollments_of(insured["id"]):
        if enrollment["status"] != "COMPLETED" or not enrollment["completed_on"]:
            continue
        completed = d(enrollment["completed_on"])
        if completed > cutoff:
            continue
        if (cutoff - completed).days > C.CREDIT_LOOKBACK_DAYS:
            continue
        code = enrollment["program_code"]
        current = winners.get(code)
        if current is None or completed > d(current["completed_on"]):
            winners[code] = enrollment
    total = ZERO
    for code in winners:
        total += C.PROGRAM_CREDIT_PCT[code]
    total = r4(total)
    return min(C.MAX_STACKED_CREDIT_PCT, total)


def surcharge_position(insured, as_of):
    """The greatest surcharge from closed peer review cases inside the window."""
    cutoff = d(as_of)
    best = ZERO
    for case in peer_cases_of(insured["id"]):
        if case["status"] != "CLOSED" or not case["closed_on"]:
            continue
        closed = d(case["closed_on"])
        if closed > cutoff:
            continue
        if (cutoff - closed).days > C.SURCHARGE_LOOKBACK_DAYS:
            continue
        if case["surcharge_pct_assigned"] > best:
            best = case["surcharge_pct_assigned"]
    return r4(best)


def recompute_surcharge(insured):
    insured["surcharge_pct"] = surcharge_position(
        insured, db.logical_date().isoformat()
    )
    touch(insured)


# --- PRD 3.4: rating a term -------------------------------------------------
def administrative_fee(premium_net):
    if premium_net < C.ADMIN_FEE_TIER_1_MAX:
        return C.ADMIN_FEE_TIER_1
    if premium_net < C.ADMIN_FEE_TIER_2_MAX:
        return C.ADMIN_FEE_TIER_2
    return C.ADMIN_FEE_TIER_3


def rate_term(term):
    """Run the pinned four-stage ladder and the fee ladder over a DRAFT term."""
    policy = db.policies[term["policy_id"]]
    insured = db.insureds[policy["insured_id"]]
    specialty = db.specialty_classes[insured["specialty_class_id"]]

    if policy["coverage_form"] == "CLAIMS_MADE":
        step_year = min(
            C.MAX_STEP_YEAR, term["term_index"] + policy["prior_acts_step_credit"]
        )
        step_factor = C.STEP_FACTOR[step_year]
    else:
        step_year = C.MAX_STEP_YEAR
        step_factor = C.STEP_FACTOR[C.MAX_STEP_YEAR]

    increased_limits = C.INCREASED_LIMITS_FACTOR[r2(policy["limit_per_claim"])]
    venue_factor = C.VENUE_SEVERITY_FACTOR[insured["venue_code"]]
    score, code, factor = classify(insured, term["rating_variant"])

    stage_1 = r2(specialty["base_rate_per_million"] * increased_limits)
    stage_2 = r2(stage_1 * factor)
    stage_3 = r2(stage_2 * venue_factor)
    premium_manual = r2(stage_3 * step_factor)

    credit = stacked_credit(insured, term["effective_date"])
    surcharge = surcharge_position(insured, term["effective_date"])
    premium_net = r2(premium_manual * (Decimal("1") - credit + surcharge))

    admin_fee = administrative_fee(premium_net)
    guaranty = r2(C.GUARANTY_FUND_RATE * (premium_net + admin_fee))
    term_total = r2(premium_net + admin_fee + guaranty)

    term["claims_made_step_year"] = step_year
    term["step_factor"] = step_factor
    term["rated_risk_class_code"] = code
    term["rated_risk_class_factor"] = factor
    term["venue_severity_factor"] = venue_factor
    term["increased_limits_factor"] = increased_limits
    term["credit_pct_applied"] = credit
    term["surcharge_pct_applied"] = surcharge
    term["premium_manual"] = premium_manual
    term["premium_net"] = premium_net
    term["administrative_fee"] = admin_fee
    term["guaranty_fund_assessment"] = guaranty
    term["term_total"] = term_total
    term["rate_revision_index_used"] = specialty["rate_revision_index"]
    return term


# --- PRD 2.10: premium ledger and compound policy status --------------------
WRITTEN_STATUSES = ("ISSUED", "IN_FORCE", "EXPIRED", "CANCELLED_FLAT", "CANCELLED_PRO_RATA")


def recompute_policy_money(policy):
    quoted = ZERO
    written = ZERO
    for term in terms_of(policy["id"]):
        if term["status"] == "DRAFT":
            quoted += term["term_total"]
        if term["status"] in WRITTEN_STATUSES:
            written += term["premium_net"] - term["return_premium"]
    policy["quoted_premium_total"] = r2(quoted)
    policy["written_premium_net_total"] = r2(written)
    touch(policy)


def derive_current_term(policy):
    candidates = [
        t for t in terms_of(policy["id"]) if t["status"] in ("ISSUED", "IN_FORCE")
    ]
    if not candidates:
        policy["current_term_id"] = None
        return
    # candidates are already in creation order, so a strict > keeps the earliest
    # created term when two share the latest effective date.
    latest = None
    for term in candidates:
        if latest is None or d(term["effective_date"]) > d(latest["effective_date"]):
            latest = term
    policy["current_term_id"] = latest["id"]


def derive_policy_status(policy, driven_by=None):
    """Re-derive the compound policy status (PRD 3.4).

    A term cancellation says the policy's "`status` set to `CANCELLED` once no
    term on it remains in `DRAFT`, `ISSUED` or `IN_FORCE`", while a term expiry
    says the status "bubbles up to `EXPIRED` once every term on it has reached a
    terminal status and at least one of them is `EXPIRED`". Where a policy holds
    both an expired and a cancelled term, the transition that triggered the
    re-derivation is what the owning workflow section names, so ``driven_by``
    pins which of the two terminal readings wins.
    """
    terms = terms_of(policy["id"])
    statuses = [t["status"] for t in terms]
    cancelled = any(s in ("CANCELLED_FLAT", "CANCELLED_PRO_RATA") for s in statuses)
    if any(s in ("ISSUED", "IN_FORCE") for s in statuses):
        policy["status"] = "ACTIVE"
    elif "DRAFT" in statuses:
        if policy["status"] != "ACTIVE":
            policy["status"] = "QUOTED"
    elif cancelled and (driven_by == "CANCELLED" or "EXPIRED" not in statuses):
        policy["status"] = "CANCELLED"
    elif "EXPIRED" in statuses:
        policy["status"] = "EXPIRED"
    elif not terms:
        policy["status"] = "QUOTED"


def refresh_policy(policy, with_status=True):
    recompute_policy_money(policy)
    derive_current_term(policy)
    if with_status:
        derive_policy_status(policy)
    touch(policy)


# --- PRD 2.10: the re-rating cascade ---------------------------------------
def rerate_drafts(insured_id, variant=None):
    """Re-rate DRAFT terms on an insured's policies, optionally one variant only."""
    for policy in policies_of(insured_id):
        affected = False
        for term in terms_of(policy["id"]):
            if term["status"] != "DRAFT":
                continue
            if variant is not None and term["rating_variant"] != variant:
                continue
            rate_term(term)
            touch(term)
            affected = True
        if affected:
            recompute_policy_money(policy)


def rerate_specialty_class(specialty_class_id):
    for insured in db.insureds.values():
        if insured["specialty_class_id"] == specialty_class_id:
            rerate_drafts(insured["id"])
