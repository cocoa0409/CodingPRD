"""Business logic: calculations and workflows per PRD section 3."""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_FLOOR

from db import store
from errors import invalid_request
from helpers import new_resource, now_iso, touch


def rhu(value):
    """Round half up to nearest integer; accepts int/float/Decimal."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Computed partner fields
# ---------------------------------------------------------------------------

def partner_originated_this_month_count(partner):
    now = store.clock
    count = 0
    for loan in store.loans.values():
        if loan.get("holder_partner_id") != partner["id"]:
            continue
        if loan.get("allocation_channel") not in ("PARTNER_RETAINED", "REFERRAL_RETAINED"):
            continue
        funded = loan.get("_funded_at")
        if funded and funded[:7] == f"{now.year:04d}-{now.month:02d}":
            count += 1
    return count


def partner_funded_balance_cents(partner):
    total = 0
    for loan in store.loans.values():
        if loan.get("holder_partner_id") != partner["id"]:
            continue
        if loan.get("status") in ("CURRENT", "DELINQUENT", "CHARGED_OFF"):
            total += loan.get("principal_cents", 0)
    return total


# ---------------------------------------------------------------------------
# Scoring / DTI / affordability
# ---------------------------------------------------------------------------

def compute_risk_score(model, applicant):
    score = 0.0
    for v in model.get("variables") or []:
        name = v.get("name")
        weight = float(v.get("weight", 0))
        vmin = v.get("min")
        vmax = v.get("max")
        x = applicant.get(name, 0)
        try:
            x = float(x)
        except (TypeError, ValueError):
            x = 0.0
        if vmin is not None and x < vmin:
            contribution = 0.0
        elif vmax is not None and x > vmax:
            contribution = weight * 100.0
        elif vmax == vmin:
            contribution = weight * 100.0
        else:
            contribution = weight * 100.0 * (x - vmin) / (vmax - vmin)
        if isinstance(name, str) and name.startswith("bank_account"):
            contribution *= 0.9
        score += contribution
    score = rhu(score)
    floor = model.get("score_floor")
    ceiling = model.get("score_ceiling")
    if floor is not None:
        score = max(floor, score)
    if ceiling is not None:
        score = min(ceiling, score)
    return score


def compute_dti(applicant):
    monthly_income = applicant.get("annual_income_cents", 0) // 12
    if monthly_income <= 0:
        return 100.0
    val = Decimal("100") * Decimal(applicant.get("monthly_debt_payments_cents", 0)) / Decimal(monthly_income)
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_approved_amount(app):
    applicant = store.applicants.get(app["applicant_id"], {})
    monthly_income = applicant.get("annual_income_cents", 0) // 12
    verifs = [v for v in store.verifications.values() if v.get("application_id") == app["id"]]
    manual_used = any(v.get("status") == "MANUAL_PASSED" for v in verifs)
    ratio = Decimal("0.32") if manual_used else Decimal("0.40")
    capacity = int((Decimal(monthly_income) * ratio).to_integral_value(rounding=ROUND_FLOOR))
    capacity = max(0, capacity - applicant.get("monthly_debt_payments_cents", 0))
    max_supportable = capacity * 30
    return min(app.get("requested_amount_cents", 0), max_supportable)


# ---------------------------------------------------------------------------
# Disparate impact (exact rationals via Fraction)
# ---------------------------------------------------------------------------

def compute_disparate_impact(model_id):
    from fractions import Fraction

    cohort = [
        a for a in store.applications.values()
        if a.get("model_version_id") == model_id and a.get("status") in ("APPROVED", "DECLINED")
    ]

    def rate(group_levels):
        members = [
            a for a in cohort
            if store.applicants.get(a.get("applicant_id"), {}).get("education_level") in group_levels
        ]
        if not members:
            return Fraction(1, 1)
        approved = sum(1 for a in members if a["status"] == "APPROVED")
        return Fraction(approved, len(members))

    rate_a = rate({"BACHELOR", "MASTER", "DOCTORATE"})
    rate_b = rate({"HIGH_SCHOOL", "ASSOCIATE"})
    if rate_a == 0 and rate_b == 0:
        ratio = Fraction(1, 1)
    else:
        ratio = min(rate_a, rate_b) / max(rate_a, rate_b)
    passed = ratio >= Fraction(4, 5)
    return {
        "approval_rate_group_a": float(rate_a),
        "approval_rate_group_b": float(rate_b),
        "disparate_impact_ratio": float(ratio),
        "outcome": "PASSED" if passed else "FAILED",
    }


# ---------------------------------------------------------------------------
# Servicing events / loan helpers
# ---------------------------------------------------------------------------

def add_event(loan, event_type, amount_cents, note=None):
    ev = new_resource(common=False)
    ev.update({
        "loan_id": loan["id"],
        "event_type": event_type,
        "amount_cents": amount_cents,
        "occurred_at": now_iso(),
        "resulting_loan_status": loan["status"],
        "note": note,
    })
    store.servicing_events[ev["id"]] = ev
    return ev


def recompute_scheduled_interest(loan):
    monthly_rate = float(loan["apr"]) / 12.0 / 100.0
    loan["scheduled_interest_cents"] = rhu(loan["outstanding_principal_cents"] * monthly_rate)


def create_loan(app, holder_id, channel, apr):
    principal = app["approved_amount_cents"]
    monthly_rate = float(apr) / 12.0 / 100.0
    n = 36
    if monthly_rate == 0:
        payment = rhu(principal / n)
    else:
        payment = rhu(principal * monthly_rate / (1 - (1 + monthly_rate) ** (-n)))
    loan = new_resource()
    loan.update({
        "application_id": app["id"],
        "holder_partner_id": holder_id,
        "allocation_channel": channel,
        "principal_cents": principal,
        "apr": apr,
        "term_months": n,
        "monthly_payment_cents": payment,
        "late_fee_accrued_cents": 0,
        "outstanding_principal_cents": principal,
        "days_delinquent": 0,
        "status": "FUNDED",
        "_funded_at": now_iso(),
        # Per-period interest due at funding (PRD 3.10): outstanding principal
        # at the start of the period times the monthly rate, rounded half up.
        "_interest_per_period_cents": rhu(principal * monthly_rate),
    })
    store.loans[loan["id"]] = loan
    recompute_scheduled_interest(loan)
    if store.clock.day == 1:
        loan["status"] = "CURRENT"
        add_event(loan, "DELINQUENCY_ADVANCED", 0)
        touch(loan)
    return loan


def late_fee(loan):
    return min(rhu(0.05 * loan["monthly_payment_cents"]), 1500)


# ---------------------------------------------------------------------------
# Allocation waterfall
# ---------------------------------------------------------------------------

def retained_reject_reasons(app, partner, applicant):
    box = store.credit_boxes.get(partner.get("active_credit_box_id") or "")
    if box is None or box.get("status") != "ACTIVE":
        return None, ["NO_ACTIVE_CREDIT_BOX"]
    reasons = []
    if applicant.get("state_code") not in (box.get("allowed_states") or []):
        reasons.append("STATE_NOT_ALLOWED")
    score = app.get("risk_score")
    if score is not None:
        if score < box.get("min_score", 0):
            reasons.append("SCORE_BELOW_BOX")
        if score > box.get("max_score", 0):
            reasons.append("SCORE_ABOVE_BOX")
    amount = app.get("approved_amount_cents")
    if amount is not None:
        if amount < box.get("min_loan_cents", 0):
            reasons.append("AMOUNT_BELOW_BOX")
        if amount > box.get("max_loan_cents", 0):
            reasons.append("AMOUNT_ABOVE_BOX")
    if not reasons and partner_originated_this_month_count(partner) >= box.get("monthly_volume_cap_count", 0):
        reasons.append("VOLUME_CAP_REACHED")
    return box, reasons


def buyer_reject_reasons(app, partner, applicant):
    box = store.credit_boxes.get(partner.get("active_credit_box_id") or "")
    if box is None or box.get("status") != "ACTIVE":
        return None, ["NO_ACTIVE_CREDIT_BOX"]
    reasons = []
    if applicant.get("state_code") not in (box.get("allowed_states") or []):
        reasons.append("STATE_NOT_ALLOWED")
    score = app.get("risk_score")
    if score is not None:
        if score < box.get("min_score", 0):
            reasons.append("SCORE_BELOW_BOX")
        if score > box.get("max_score", 0):
            reasons.append("SCORE_ABOVE_BOX")
    amount = app.get("approved_amount_cents")
    if amount is not None:
        if amount < box.get("min_loan_cents", 0):
            reasons.append("AMOUNT_BELOW_BOX")
        if amount > box.get("max_loan_cents", 0):
            reasons.append("AMOUNT_ABOVE_BOX")
    return box, reasons


def run_allocation(app):
    applicant = store.applicants.get(app["applicant_id"], {})
    candidate_ids = []
    reason_codes = []
    chosen = None
    chosen_channel = None
    chosen_box = None

    def consider_partner(partner, channel):
        nonlocal chosen, chosen_channel, chosen_box
        candidate_ids.append(partner["id"])
        if partner.get("status") != "ACTIVE":
            reason_codes.append("PARTNER_INACTIVE")
            return False
        if channel == "WHOLE_LOAN_SALE":
            box, reasons = buyer_reject_reasons(app, partner, applicant)
        else:
            box, reasons = retained_reject_reasons(app, partner, applicant)
        if reasons:
            reason_codes.extend(reasons)
            return False
        chosen, chosen_channel, chosen_box = partner["id"], channel, box
        return True

    def consider_pool(pool):
        nonlocal chosen, chosen_channel, chosen_box
        candidate_ids.append(pool["trust_partner_id"])
        principal = app.get("approved_amount_cents") or 0
        if principal > pool.get("max_single_loan_cents", 0):
            reason_codes.append("POOL_SINGLE_LOAN_EXCEEDED")
            return False
        if pool.get("allocated_principal_cents", 0) + principal > pool.get("target_principal_cents", 0):
            reason_codes.append("POOL_CAPACITY_EXCEEDED")
            return False
        chosen, chosen_channel = pool["trust_partner_id"], "SECURITIZATION"
        chosen_box = None
        pool["allocated_principal_cents"] += principal
        touch(pool)
        return True

    def created_key(r):
        return (r.get("created_at", ""), r.get("_seq", 0))

    # Step 1: referral
    if app.get("channel") == "PARTNER_REFERRAL":
        ref = store.partners.get(app.get("referral_partner_id") or "")
        if ref is not None:
            consider_partner(ref, "REFERRAL_RETAINED")

    # Step 2: retained banks / credit unions. Partners of the right type are
    # evaluated in creation order regardless of status so a non-ACTIVE partner
    # is recorded as rejected with PARTNER_INACTIVE rather than skipped
    # silently (PRD 3.9: "each rejection ... is recorded"; PRD 3.3: suspension
    # excludes the partner's credit box from eligibility).
    if chosen is None:
        banks = sorted(
            [p for p in store.partners.values()
             if p.get("partner_type") in ("BANK", "CREDIT_UNION")],
            key=created_key,
        )
        for p in banks:
            if consider_partner(p, "PARTNER_RETAINED"):
                break

    # Step 3: whole-loan buyers
    if chosen is None:
        buyers = sorted(
            [p for p in store.partners.values()
             if p.get("partner_type") == "LOAN_BUYER" and p.get("status") == "ACTIVE"],
            key=created_key,
        )
        for p in buyers:
            if consider_partner(p, "WHOLE_LOAN_SALE"):
                break

    # Step 4: securitization pools
    if chosen is None:
        pools = sorted(
            [p for p in store.securitization_pools.values()
             if p.get("status") == "OPEN"
             and store.partners.get(p.get("trust_partner_id"), {}).get("status") == "ACTIVE"],
            key=created_key,
        )
        for pool in pools:
            if consider_pool(pool):
                break

    # Decide
    decision = new_resource(common=False)
    decision.update({
        "application_id": app["id"],
        "candidate_partner_ids": candidate_ids,
        "decided_at": now_iso(),
    })

    if chosen is not None:
        decision["chosen_partner_id"] = chosen
        decision["channel"] = chosen_channel
        decision["reason_codes"] = reason_codes
        apr = chosen_box["annual_percentage_rate"] if chosen_box else 0
        create_loan(app, chosen, chosen_channel, apr)
        app["status"] = "APPROVED"
    else:
        decision["chosen_partner_id"] = None
        decision["channel"] = "UNALLOCATED"
        if (app.get("approved_amount_cents") or 0) <= 0:
            reason_codes.append("AFFORDABILITY_ZERO")
        decision["reason_codes"] = reason_codes
        app["status"] = "DECLINED"

    store.allocation_decisions[decision["id"]] = decision
    touch(app)
    return decision
