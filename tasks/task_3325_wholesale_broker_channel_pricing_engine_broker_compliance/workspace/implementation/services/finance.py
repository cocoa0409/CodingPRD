"""Financial review scoring, the tier ladder, product eligibility and
compensation plans (PRD 3.2, 3.3, 3.6)."""

import db
from constants import (
    ATTAINMENT_MEETS_RATIO,
    ATTAINMENT_NEAR_RATIO,
    BAND_BELOW,
    BAND_MEETS,
    BAND_NEAR,
    BAND_SCORES,
    ELECTION_BORROWER_PAID,
    ELECTION_LENDER_PAID,
    ELECTION_UNDECIDED,
    ELECTION_VALUES,
    EXPERIENCE_TARGET_YEARS,
    LEVERAGE_CAP_RATIO,
    LIQUIDITY_TARGET_CENTS,
    NET_WORTH_FLOOR_CENTS,
    NET_WORTH_TARGET_CENTS,
    PLAN_CODES,
    PRODUCT_CODES,
    SCORE_MAX,
    SCORE_MIN,
    TIER_1,
    TIER_1_MIN_SCORE,
    TIER_2,
    TIER_2_MIN_SCORE,
    TIER_3,
    TIER_3_MIN_SCORE,
    TIER_UNRATED,
)
from errors import ApiError
from numeric import ONE, ZERO, clamp, quantize, round_half_up, to_decimal
from services import shared


# ---------------------------------------------------------------------------
# broker_financial_strength_score (PRD 3.2)
# ---------------------------------------------------------------------------
def compute_financial_strength_score(review, broker):
    net_worth = to_decimal(review["net_worth_cents"], ZERO)
    liquidity = to_decimal(review["liquidity_cents"], ZERO)
    liabilities = to_decimal(review["total_liabilities_cents"], ZERO)
    years = to_decimal(review["years_in_business"], ZERO)

    net_worth_component = min(ONE, net_worth / to_decimal(NET_WORTH_TARGET_CENTS)) * 40
    liquidity_component = min(ONE, liquidity / to_decimal(LIQUIDITY_TARGET_CENTS)) * 30
    denominator = max(ONE, net_worth * LEVERAGE_CAP_RATIO)
    leverage_component = max(ZERO, ONE - (liabilities / denominator)) * 20
    experience_component = min(ONE, years / to_decimal(EXPERIENCE_TARGET_YEARS)) * 10

    raw = net_worth_component + liquidity_component + leverage_component + experience_component
    return round_half_up(clamp(raw, SCORE_MIN, SCORE_MAX), 2)


def compute_attainment_band(review, broker):
    expectation = to_decimal(broker.get("volume_expectation_cents"), ZERO)
    if expectation is None or expectation <= ZERO:
        return BAND_BELOW
    ratio = to_decimal(review["prior_year_funded_volume_cents"], ZERO) / expectation
    if ratio >= ATTAINMENT_MEETS_RATIO:
        return BAND_MEETS
    if ratio >= ATTAINMENT_NEAR_RATIO:
        return BAND_NEAR
    return BAND_BELOW


def attainment_band_score(band):
    return BAND_SCORES.get(band, 0)


# ---------------------------------------------------------------------------
# broker_tier (PRD 3.2)
# ---------------------------------------------------------------------------
def passed_reviews(broker_id):
    rows = [row for row in db.financial_reviews.values()
            if row["broker_id"] == broker_id and row["status"] == "PASSED"]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return rows


def current_passed_review(broker_id):
    rows = passed_reviews(broker_id)
    for row in rows:
        if row.get("is_current"):
            return row
    return rows[-1] if rows else None


def compute_tier(broker):
    """Banded on financial_strength_score, then volume-capped, then UNRATED
    whenever no PASSED review is on file."""
    if not passed_reviews(broker["id"]):
        return TIER_UNRATED
    score = quantize(to_decimal(broker["financial_strength_score"], ZERO), 2)
    if score >= TIER_1_MIN_SCORE:
        tier = TIER_1
    elif score >= TIER_2_MIN_SCORE:
        tier = TIER_2
    elif score >= TIER_3_MIN_SCORE:
        tier = TIER_3
    else:
        tier = TIER_UNRATED

    current = current_passed_review(broker["id"])
    if tier == TIER_1 and current is not None:
        if current.get("attainment_band") != BAND_MEETS:
            tier = TIER_2
    return tier


def refresh_tier(broker):
    broker["tier"] = compute_tier(broker)
    return broker["tier"]


# ---------------------------------------------------------------------------
# FinancialReview CRUD
# ---------------------------------------------------------------------------
def create_financial_review(body):
    broker_id = shared.require_field(body, "broker_id")
    broker = shared.get_broker(broker_id)

    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "net_worth_cents": shared.require_int(body, "net_worth_cents"),
        "liquidity_cents": shared.require_int(body, "liquidity_cents"),
        "total_liabilities_cents": shared.require_int(body, "total_liabilities_cents"),
        "years_in_business": shared.require_int(body, "years_in_business"),
        "prior_year_funded_volume_cents": shared.require_int(body, "prior_year_funded_volume_cents"),
        "audit_attested": shared.optional_bool(body, "audit_attested", False),
        "status": "PENDING",
        "is_current": False,
    })
    row["computed_financial_strength_score"] = compute_financial_strength_score(row, broker)
    row["attainment_band"] = compute_attainment_band(row, broker)
    db.financial_reviews[row["id"]] = row
    return row


def decide_financial_review(review_id, body):
    review = shared.get_financial_review(review_id)
    outcome = shared.require_enum(body, "outcome", ["PASSED", "FAILED"])
    broker = shared.get_broker(review["broker_id"])

    if review["status"] != "PENDING":
        raise ApiError("ERR_REVIEW_ALREADY_DECIDED",
                       "The financial review is already %s." % review["status"])

    if outcome == "PASSED":
        if not review["audit_attested"]:
            raise ApiError("ERR_FINANCIAL_REVIEW_PENDING",
                           "An unattested financial review can never pass.")
        if int(review["net_worth_cents"]) < NET_WORTH_FLOOR_CENTS:
            raise ApiError("ERR_NET_WORTH_BELOW_MINIMUM",
                           "net_worth_cents is below the NET_WORTH_FLOOR_CENTS minimum.")
        review["status"] = "PASSED"
        for other in passed_reviews(broker["id"]):
            if other["id"] != review["id"] and other.get("is_current"):
                other["is_current"] = False
                db.touch(other)
        review["is_current"] = True
        db.touch(review)
        broker["financial_strength_score"] = review["computed_financial_strength_score"]
        refresh_tier(broker)
        db.touch(broker)
        shared.evaluate_suspension(broker)
        return review

    review["status"] = "FAILED"
    review["is_current"] = False
    db.touch(review)
    db.touch(broker)
    return review


# ---------------------------------------------------------------------------
# ProductEligibility
# ---------------------------------------------------------------------------
def create_product_eligibility(body):
    broker_id = shared.require_field(body, "broker_id")
    broker = shared.get_broker(broker_id)
    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "product_code": shared.require_enum(body, "product_code", PRODUCT_CODES),
        "max_ltv": shared.require_decimal(body, "max_ltv"),
        "min_fico": shared.require_int(body, "min_fico"),
        "max_loan_amount_cents": shared.require_int(body, "max_loan_amount_cents"),
        "status": "PENDING",
        "approved_at": None,
    })
    db.product_eligibilities[row["id"]] = row
    return row


def decide_product_eligibility(eligibility_id, body):
    eligibility = shared.get_eligibility(eligibility_id)
    outcome = shared.require_enum(body, "outcome", ["APPROVED", "REVOKED"])
    broker = shared.get_broker(eligibility["broker_id"])

    # Priority 4: the broker version guard runs before the state preconditions.
    expected = body.get("expected_broker_version") if isinstance(body, dict) else None
    if "expected_broker_version" not in (body or {}):
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_broker_version is required on this endpoint.")
    if expected is None or int(expected) != int(broker["version"]):
        raise ApiError("ERR_STALE_VERSION",
                       "expected_broker_version %r no longer matches the broker version %s."
                       % (expected, broker["version"]))

    # Priority 27: the row must still be undecided.
    if eligibility["status"] != "PENDING":
        raise ApiError("ERR_ELIGIBILITY_ALREADY_DECIDED",
                       "The product eligibility is already %s." % eligibility["status"])

    # Priority 7: approvals are frozen while the broker is BLOCKED.
    if outcome == "APPROVED" and broker["exclusivity_status"] == "BLOCKED":
        raise ApiError("ERR_BROKER_EXCLUSIVITY_BLOCKED",
                       "A BLOCKED broker may not have a product eligibility approved.")

    if outcome == "APPROVED":
        eligibility["status"] = "APPROVED"
        eligibility["approved_at"] = db.now_iso()
    else:
        eligibility["status"] = "REVOKED"
        eligibility["approved_at"] = None
    db.touch(eligibility)
    shared.recompute_approved_product_codes(broker)
    db.touch(broker)
    return eligibility


# ---------------------------------------------------------------------------
# CompensationPlan
# ---------------------------------------------------------------------------
def create_compensation_plan(body):
    broker_id = shared.require_field(body, "broker_id")
    broker = shared.get_broker(broker_id)
    plan_code = shared.require_enum(body, "plan_code", PLAN_CODES)
    for existing in db.compensation_plans.values():
        if existing["broker_id"] == broker["id"] and existing["plan_code"] == plan_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "plan_code %s already exists for this broker." % plan_code)
    default_election = shared.require_enum(
        body, "default_election", [ELECTION_LENDER_PAID, ELECTION_BORROWER_PAID])
    row = db.base_row()
    row.update({
        "broker_id": broker["id"],
        "plan_code": plan_code,
        "default_election": default_election,
        "lender_paid_amount_cents": shared.require_int(body, "lender_paid_amount_cents"),
        "borrower_paid_amount_cents": shared.require_int(body, "borrower_paid_amount_cents"),
        "is_active": shared.optional_bool(body, "is_active", True),
    })
    db.compensation_plans[row["id"]] = row
    return row


def active_plans_for(broker_id):
    return [row for row in db.compensation_plans.values()
            if row["broker_id"] == broker_id and row["is_active"]]


def update_compensation_plan(plan_id, body):
    plan = shared.get_plan(plan_id)
    if "is_active" not in (body or {}):
        raise ApiError("ERR_INVALID_REQUEST", "is_active is required on this endpoint.")
    target = shared.require_bool(body, "is_active")

    if plan["is_active"] == target:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "The plan is already %s." % ("active" if target else "inactive"),
        )

    if target is False:
        others = [row for row in active_plans_for(plan["broker_id"]) if row["id"] != plan["id"]]
        if not others:
            raise ApiError("ERR_LAST_ACTIVE_COMPENSATION_PLAN",
                           "Deactivation would leave the broker with no ACTIVE plan.")

    plan["is_active"] = target
    if "default_election" in (body or {}) and body["default_election"] is not None:
        plan["default_election"] = shared.require_enum(
            body, "default_election", [ELECTION_LENDER_PAID, ELECTION_BORROWER_PAID])
    if "lender_paid_amount_cents" in (body or {}) and body["lender_paid_amount_cents"] is not None:
        plan["lender_paid_amount_cents"] = shared.require_int(body, "lender_paid_amount_cents")
    if "borrower_paid_amount_cents" in (body or {}) and body["borrower_paid_amount_cents"] is not None:
        plan["borrower_paid_amount_cents"] = shared.require_int(body, "borrower_paid_amount_cents")
    db.touch(plan)
    return plan


def election_values():
    return ELECTION_VALUES


def undecided_value():
    return ELECTION_UNDECIDED