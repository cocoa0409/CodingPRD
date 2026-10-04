"""Benefit-check estimation — the dual-variant benefit_cost_estimate (§3.9)."""

from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError, ERR_CONSENT_REQUIRED, ERR_PARTICIPANT_NOT_FOUND

PRIOR_AUTH_PLAN_SHARE_CAP = Decimal("0.50")

CONSENT_SCOPES_FOR_BENEFIT = ("BENEFIT_CHECK", "BOTH")
PREFERRED = "PREFERRED"
NON_PREFERRED = "NON_PREFERRED"
PRIOR_AUTH_REQUIRED = "PRIOR_AUTH_REQUIRED"
NOT_COVERED = "NOT_COVERED"
UNKNOWN = "UNKNOWN"


def round_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _payer(payer_id):
    payer = db.get("participants", payer_id)
    if payer is None:
        raise ApiError(ERR_PARTICIPANT_NOT_FOUND)
    return payer


def active_benefit_consent(patient_id):
    return db.find_one(
        "consents",
        lambda c: c["patient_id"] == patient_id
        and c["status"] == "ACTIVE"
        and c["scope"] in CONSENT_SCOPES_FOR_BENEFIT,
    )


def resolve_formulary_and_coverage(check, payer):
    """Resolve eligibility and formulary against the payer's plan and the order.

    The plan itself carries no per-drug formulary file, so the only eligible
    benefit plan a check can resolve against is a PAYER participant's plan,
    which settles at the plan's customary non-preferred tier. A check written
    against anything else resolves neither column.
    """
    if payer.get("participant_type") == "PAYER":
        return NON_PREFERRED, "ACTIVE"
    return UNKNOWN, UNKNOWN


def compute(check, payer, variant, formulary_status, coverage_status):
    """The pinned seven-step evaluation order, shared by both variants."""
    consent = active_benefit_consent(check["patient_id"])
    if consent is None:
        raise ApiError(ERR_CONSENT_REQUIRED)

    benchmark = check["benchmark_price_cents"]
    # STEP 0 — the snapshot is captured on the edge out of PENDING, never re-read
    deductible_met = check["deductible_met_snapshot_cents"]

    # Pinned exception — an INACTIVE coverage pins the estimate, no arithmetic
    if coverage_status == "INACTIVE":
        return {
            "formulary_status": NOT_COVERED,
            "estimated_patient_pay_cents": benchmark,
            "estimated_plan_pay_cents": 0,
            "credit_cents": 0,
        }

    # STEP 1 — effective benchmark
    if formulary_status == PREFERRED:
        effective = round_cents(
            Decimal(benchmark) * (Decimal("1") - Decimal(str(payer["formulary_preferred_pct"])))
        )
    else:
        effective = benchmark

    # STEP 2 — the patient's cost share
    patient_cost_share = payer["plan_copay_cents"] + round_cents(
        Decimal(str(payer["plan_coinsurance_pct"])) * Decimal(effective)
    )

    # STEP 3 — the brand fee
    if formulary_status in (NON_PREFERRED, PRIOR_AUTH_REQUIRED):
        brand_fee = payer["plan_brand_fee_cents"]
    else:
        brand_fee = 0

    # STEP 4 — deductible remaining
    deductible_remaining = max(0, payer["plan_deductible_cents"] - deductible_met)

    # STEP 5 — the variant-dependent deductible-credit basis
    if variant == "FINAL":
        credit = min(deductible_remaining, patient_cost_share + brand_fee)
        patient_pay = patient_cost_share + brand_fee
        plan_pay = max(0, effective - patient_cost_share)
    else:
        credit = min(deductible_remaining, patient_cost_share)
        patient_pay = patient_cost_share
        plan_pay = max(0, effective - patient_cost_share) + brand_fee

    # STEP 6 — the prior-authorization plan-share cap
    if formulary_status == PRIOR_AUTH_REQUIRED:
        plan_pay = min(plan_pay, round_cents(PRIOR_AUTH_PLAN_SHARE_CAP * Decimal(effective)))

    # STEP 7 — the shared benefit cap
    if plan_pay > payer["plan_benefit_cap_cents"]:
        removed = plan_pay - payer["plan_benefit_cap_cents"]
        plan_pay = payer["plan_benefit_cap_cents"]
        patient_pay += removed

    return {
        "formulary_status": formulary_status,
        "estimated_patient_pay_cents": patient_pay,
        "estimated_plan_pay_cents": plan_pay,
        "credit_cents": credit,
    }


def evaluate(check, variant):
    payer = _payer(check["payer_id"])
    formulary, coverage = resolve_formulary_and_coverage(check, payer)
    result = compute(check, payer, variant, formulary, coverage)
    check["formulary_status"] = result["formulary_status"]
    check["coverage_status"] = coverage
    check["pricing_variant"] = variant
    check["check_status"] = "COMPLETE"
    check["estimated_patient_pay_cents"] = result["estimated_patient_pay_cents"]
    check["estimated_plan_pay_cents"] = result["estimated_plan_pay_cents"]
    db.touch(check)
    if variant == "FINAL":
        advance = min(result["credit_cents"],
                      max(0, payer["plan_deductible_cents"] - payer["plan_deductible_met_cents"]))
        if advance:
            payer["plan_deductible_met_cents"] += advance
            db.touch(payer)
    return check