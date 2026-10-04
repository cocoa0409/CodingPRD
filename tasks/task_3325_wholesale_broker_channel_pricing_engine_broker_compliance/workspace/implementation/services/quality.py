"""Post-funding quality control, defect remediation and repurchase
(PRD 3.9)."""

import db
from constants import (
    DEFECT_WEIGHTS,
    LOAN_QC_REVIEWABLE_STATUSES,
    ORIGINATION_FEE_SHARE,
    REPURCHASE_POINTS_THRESHOLD,
    REPURCHASE_WINDOW_DAYS,
    SCORE_MAX,
    SCORE_MIN,
    SEVERITY_MULTIPLIERS,
    TIER_MULTIPLIERS,
)
from errors import ApiError
from numeric import ZERO, clamp, quantize, round_half_up, round_int, to_decimal
from services import shared

DEFECT_TYPES = list(DEFECT_WEIGHTS.keys())
SEVERITIES = list(SEVERITY_MULTIPLIERS.keys())


# ---------------------------------------------------------------------------
# weighted_defect_points / defect_multiplier (PRD 3.9)
# ---------------------------------------------------------------------------
def weighted_defect_points(defect_type, severity):
    base = DEFECT_WEIGHTS.get(defect_type, ZERO)
    multiplier = SEVERITY_MULTIPLIERS.get(severity, ZERO)
    return round_half_up(base * multiplier, 2)


def defect_multiplier(open_defect_tier):
    tier = int(open_defect_tier)
    if tier <= 0:
        return TIER_MULTIPLIERS[0]
    if tier >= 4:
        return TIER_MULTIPLIERS[4]
    return TIER_MULTIPLIERS[tier]


def count_open_defects(broker_id):
    """Open findings across every loan of the broker."""
    loan_ids = {loan["id"] for loan in db.loan_submissions.values()
                if loan["broker_id"] == broker_id}
    count = 0
    for review in db.quality_control_reviews.values():
        if review["loan_submission_id"] in loan_ids and review["remediation_status"] == "OPEN":
            count += 1
    return count


def open_findings_for_loan(loan_id):
    return [row for row in db.quality_control_reviews.values()
            if row["loan_submission_id"] == loan_id and row["remediation_status"] == "OPEN"]


def _debit_score(broker, points):
    multiplier = defect_multiplier(broker["open_defect_tier"])
    current = to_decimal(broker["rolling_quality_score"], ZERO)
    broker["rolling_quality_score"] = round_half_up(
        max(ZERO, current - (points * multiplier)), 2)
    if broker["rolling_quality_score"] > SCORE_MAX:
        broker["rolling_quality_score"] = SCORE_MAX


def _credit_score(broker, points):
    multiplier = defect_multiplier(broker["open_defect_tier"])
    current = to_decimal(broker["rolling_quality_score"], ZERO)
    broker["rolling_quality_score"] = round_half_up(
        min(SCORE_MAX, current + (points * multiplier)), 2)
    if broker["rolling_quality_score"] < SCORE_MIN:
        broker["rolling_quality_score"] = SCORE_MIN


def _dec_tier(broker):
    broker["open_defect_tier"] = max(0, int(broker["open_defect_tier"]) - 1)


def _clear_loan_flag_if_no_open(loan):
    if not open_findings_for_loan(loan["id"]):
        loan["defect_remediation_open"] = False
        db.touch(loan)


# ---------------------------------------------------------------------------
# Creation (PRD 3.9)
# ---------------------------------------------------------------------------
def create_quality_control_review(caller, body):
    loan = shared.get_loan(shared.require_field(body, "loan_submission_id"))
    broker = shared.get_broker(loan["broker_id"])

    defect_type = shared.require_enum(body, "defect_type", DEFECT_TYPES)
    severity = shared.require_enum(body, "severity", SEVERITIES)
    remediation_status = shared.require_enum(
        body, "remediation_status", ["NONE", "OPEN", "REMEDIATED"])

    # priority 24 - one review per loan submission
    for row in db.quality_control_reviews.values():
        if row["loan_submission_id"] == loan["id"]:
            raise ApiError("ERR_QC_REVIEW_EXISTS",
                           "A quality control review already exists for this loan.")

    # priority 29 - the supplied enum members must be well formed. A defect review
    # may legitimately arrive already in progress (PRD 3.9 renders the OPEN branch
    # in full: it raises the tier and gates closing), so OPEN is accepted here.
    if defect_type == "NON_DEFECT" and remediation_status != "NONE":
        raise ApiError("ERR_INVALID_REQUEST",
                       "A NON_DEFECT review carries remediation_status NONE.")

    # priority 32 - segregation of duties
    if is_loan_underwriter(loan["id"], caller.user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                       "The QC reviewer must not be the loan's underwriter.")

    # the review must land on a loan that reached the funded part of its life
    if loan["status"] not in LOAN_QC_REVIEWABLE_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "A loan in status %s cannot be quality reviewed." % loan["status"])

    points = weighted_defect_points(defect_type, severity)

    row = db.base_row()
    row.update({
        "loan_submission_id": loan["id"],
        "broker_id": broker["id"],
        "reviewer_id": caller.user_id,
        "defect_type": defect_type,
        "severity": severity,
        "weighted_defect_points": points,
        "repurchase_required": False,
        "repurchase_due_at": None,
        "reviewed_at": db.now_iso(),
    })

    if defect_type == "NON_DEFECT":
        row["outcome"] = "CLEAR"
        row["remediation_status"] = "NONE"
        row["weighted_defect_points"] = ZERO
        db.quality_control_reviews[row["id"]] = row
        db.touch(broker)
        return row

    row["outcome"] = "DEFECT"
    row["remediation_status"] = remediation_status
    if severity == "CRITICAL" and points >= REPURCHASE_POINTS_THRESHOLD:
        row["repurchase_required"] = True
        row["repurchase_due_at"] = shared.current_repurchase_deadline()
    db.quality_control_reviews[row["id"]] = row

    # cascade hop 1 -> 2: debit the rolling quality score at the tier of the moment
    _debit_score(broker, points)

    # cascade hop 1 -> 2 (guarded): an OPEN finding raises the tier, and once the
    # tier is at least 1 the loan's remediation flag is set (PRD 3.9).
    if remediation_status == "OPEN":
        broker["open_defect_tier"] = int(broker["open_defect_tier"]) + 1
        if int(broker["open_defect_tier"]) >= 1:
            loan["defect_remediation_open"] = True
            db.touch(loan)

    # an already-REMEDIATED defect is a mint correction: its points land now
    if remediation_status == "REMEDIATED":
        loan["defect_remediation_open"] = True
        db.touch(loan)

    # cascade hop 2 -> 3 (independent branch): a CLEAR_TO_CLOSE loan is pushed back
    if loan["status"] == "CLEAR_TO_CLOSE":
        loan["status"] = "SUSPENDED_REVIEW"
        db.touch(loan)

    shared.recompute_active_loan_count(broker)
    shared.recompute_compensation_commitment(broker)
    db.touch(broker)
    shared.evaluate_suspension(broker)
    return row


def is_loan_underwriter(loan_id, user_id):
    rows = [row for row in db.underwriting_decisions.values()
            if row["loan_submission_id"] == loan_id and row["is_final"]]
    if not rows:
        return False
    rows.sort(key=lambda row: (row["decided_at"], row["created_at"], row["id"]))
    return rows[-1]["underwriter_id"] == user_id


# ---------------------------------------------------------------------------
# Resolution (PRD 3.9)
# ---------------------------------------------------------------------------
def resolve_quality_control_review(caller, review_id, body):
    review = shared.get_quality_review(review_id)
    broker = shared.get_broker(review["broker_id"])
    loan = db.loan_submissions.get(review["loan_submission_id"])

    resolution_type = shared.require_enum(body, "resolution_type", ["REMEDIATED", "VOIDED"])
    note = shared.field(body, "resolution_note", None)

    if resolution_type == "REMEDIATED":
        return _resolve_remediated(review, broker, loan, note)
    return _resolve_voided(review, broker, loan, note)


def _resolve_remediated(review, broker, loan, note):
    current = review["remediation_status"]

    if current == "OPEN":
        review["remediation_status"] = "REMEDIATED"
        db.touch(review)
        _dec_tier(broker)
        if loan is not None:
            _clear_loan_flag_if_no_open(loan)
        db.touch(broker)
        return review

    if current == "REMEDIATED" and review["outcome"] == "DEFECT":
        # dating-only mint correction: the status holds, the points land now
        _debit_score(broker, review["weighted_defect_points"])
        if loan is not None:
            loan["defect_remediation_open"] = True
            db.touch(loan)
        db.touch(broker)
        shared.evaluate_suspension(broker)
        return review

    raise ApiError("ERR_INVALID_REQUEST",
                   "A REMEDIATED resolution cannot be applied to a finding in state %s."
                   % current)


def _resolve_voided(review, broker, loan, note):
    current = review["remediation_status"]
    outcome = review["outcome"]

    if outcome == "CLEAR":
        if current != "NONE":
            raise ApiError("ERR_INVALID_REQUEST",
                           "A VOIDED resolution on a CLEAR review requires remediation_status NONE.")
        review["remediation_status"] = "VOIDED"
        db.touch(review)
        _credit_score(broker, review["weighted_defect_points"])
        db.touch(broker)
        return review

    if current not in ("OPEN", "REMEDIATED"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "A VOIDED resolution cannot be applied twice (state %s)." % current)

    review["remediation_status"] = "VOIDED"
    db.touch(review)
    _credit_score(broker, review["weighted_defect_points"])
    if current == "OPEN":
        _dec_tier(broker)
        if loan is not None:
            _clear_loan_flag_if_no_open(loan)
    db.touch(broker)
    shared.evaluate_suspension(broker)
    return review


# ---------------------------------------------------------------------------
# Repurchase (PRD 3.9)
# ---------------------------------------------------------------------------
def repurchase(review_id):
    review = shared.get_quality_review(review_id)
    loan = shared.get_loan(review["loan_submission_id"])
    broker = shared.get_broker(loan["broker_id"])

    if review["outcome"] != "DEFECT" or not review["repurchase_required"]:
        raise ApiError("ERR_REPURCHASE_NOT_REQUIRED",
                       "The review is not a repurchase-required critical defect.")

    due = db.parse_instant(review.get("repurchase_due_at"))
    if due is None or db.clock.now > due:
        raise ApiError("ERR_REPURCHASE_WINDOW_EXPIRED",
                       "The repurchase window has lapsed.")

    if loan["status"] == "REPURCHASED":
        raise ApiError("ERR_LOAN_ALREADY_REPURCHASED",
                       "The loan already carries a repurchase.")
    if loan["status"] != "FUNDED":
        raise ApiError("ERR_LOAN_ALREADY_REPURCHASED",
                       "A loan in status %s cannot be repurchased." % loan["status"])

    contribution = to_decimal(loan["loan_amount_cents"], ZERO)
    pool = to_decimal(shared.funded_volume_before_repurchase(broker, loan), ZERO)
    denominator = pool + contribution
    if denominator == ZERO:
        volume_share_reversal = ZERO
    else:
        volume_share_reversal = (pool * contribution) / denominator
    fee_reversal = contribution * ORIGINATION_FEE_SHARE
    exposure = round_int(volume_share_reversal + fee_reversal)

    loan["repurchase_exposure_cents"] = exposure
    loan["status"] = "REPURCHASED"
    db.touch(loan)

    # the funded-volume credit is reversed: the loan is no longer FUNDED
    shared.recompute_compensation_commitment(broker)
    shared.recompute_rolling_funded_volume(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return loan


def quantize_score(value):
    return quantize(clamp(to_decimal(value, ZERO), SCORE_MIN, SCORE_MAX), 2)