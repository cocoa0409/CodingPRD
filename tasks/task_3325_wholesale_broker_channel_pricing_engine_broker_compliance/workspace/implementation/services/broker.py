"""Broker lifecycle: submission, approval, suspension, reinstatement and
termination (PRD 3.1)."""

import db
from constants import (
    DEFECT_SUSPENSION_TIER,
    EXCLUSIVITY_BLOCKED,
    EXCLUSIVITY_CLEAR,
    REINSTATEMENT_DEFECT_TIER,
    REINSTATEMENT_QUALITY_THRESHOLD,
    SCORE_MAX,
    SCORE_MIN,
)
from errors import ApiError
from numeric import ZERO, quantize, to_decimal
from services import finance, shared

TIER_UNRATED = "UNRATED"


def create_broker(body):
    legal_name = shared.require_field(body, "legal_name")
    nmls_id = shared.require_field(body, "nmls_id")
    home_state = shared.require_field(body, "home_state")
    volume_expectation_cents = shared.require_int(body, "volume_expectation_cents")

    # priority 30 - the NMLS identifier is unique across all brokerages
    for row in db.brokers.values():
        if str(row["nmls_id"]) == str(nmls_id):
            raise ApiError("ERR_DUPLICATE_NMLS_ID",
                           "A broker already exists with nmls_id %s." % nmls_id)

    row = db.base_row()
    row.update({
        "legal_name": legal_name,
        "nmls_id": nmls_id,
        "home_state": home_state,
        "status": "SUBMITTED",
        "financial_strength_score": ZERO,
        "tier": TIER_UNRATED,
        "licensed_states": [],
        "approved_product_codes": [],
        "volume_expectation_cents": volume_expectation_cents,
        "rolling_funded_volume_cents": 0,
        "rolling_quality_score": quantize(to_decimal(100, ZERO), 2),
        "open_defect_tier": 0,
        "exclusivity_status": EXCLUSIVITY_CLEAR,
        "exclusivity_scopes_covered": [],
        "active_loan_count": 0,
        "total_active_compensation_commitment_cents": 0,
        "suspended_reason": None,
    })
    db.brokers[row["id"]] = row
    return row


def approve_broker(broker_id):
    broker = shared.get_broker(broker_id)

    # priority 7 - the exclusivity gate runs before every other business check
    if broker["exclusivity_status"] == EXCLUSIVITY_BLOCKED:
        raise ApiError("ERR_BROKER_EXCLUSIVITY_BLOCKED",
                       "A BLOCKED broker may not be approved.")

    # priority 6 - the state precondition
    if broker["status"] != "SUBMITTED":
        raise ApiError("ERR_BROKER_NOT_SUBMITTED",
                       "The broker is %s, not SUBMITTED." % broker["status"])

    # priority 8 - the defect hold
    if int(broker["open_defect_tier"]) > 2:
        raise ApiError("ERR_BROKER_DEFECT_HOLD",
                       "open_defect_tier %s exceeds 2." % broker["open_defect_tier"])

    # priority 9 - a PASSED financial review must already be on file
    if not finance.passed_reviews(broker["id"]):
        raise ApiError("ERR_FINANCIAL_REVIEW_PENDING",
                       "The broker has no PASSED financial review.")

    # priority 10 - an unexpired licence must exist
    shared.recompute_licensed_states(broker)
    if not broker["licensed_states"]:
        raise ApiError("ERR_NO_VALID_LICENSE",
                       "The broker has no license whose expires_on is after the logical clock.")

    broker["status"] = "APPROVED"
    finance.refresh_tier(broker)
    db.touch(broker)
    return broker


def reinstate_broker(broker_id):
    broker = shared.get_broker(broker_id)

    # priority 6 then 7 - the state gate, then the exclusivity gate
    if broker["status"] != "SUSPENDED":
        raise ApiError("ERR_BROKER_NOT_SUBMITTED",
                       "Reinstatement requires a SUSPENDED broker, not %s." % broker["status"])
    if broker["exclusivity_status"] == EXCLUSIVITY_BLOCKED:
        raise ApiError("ERR_BROKER_EXCLUSIVITY_BLOCKED",
                       "A BLOCKED broker may not be reinstated.")

    # priority 8 - the quality and defect gates
    if to_decimal(broker["rolling_quality_score"], ZERO) < REINSTATEMENT_QUALITY_THRESHOLD:
        raise ApiError("ERR_BROKER_QUALITY_BELOW_REINSTATEMENT",
                       "rolling_quality_score is below 60.00.")
    if int(broker["open_defect_tier"]) > REINSTATEMENT_DEFECT_TIER:
        raise ApiError("ERR_BROKER_DEFECT_HOLD",
                       "open_defect_tier %s exceeds 2." % broker["open_defect_tier"])

    broker["status"] = "APPROVED"
    broker["suspended_reason"] = None
    finance.refresh_tier(broker)
    db.touch(broker)
    return broker


def suspend_broker(broker_id, body):
    broker = shared.get_broker(broker_id)
    if broker["status"] != "APPROVED":
        raise ApiError("ERR_BROKER_NOT_SUSPENDABLE",
                       "Manual suspension requires an APPROVED broker, not %s." % broker["status"])
    reason = shared.field(body, "reason", None)

    broker["status"] = "SUSPENDED"
    broker["suspended_reason"] = reason
    shared.withdraw_submitted_loans(broker)
    shared.recompute_active_loan_count(broker)
    db.touch(broker)
    return broker


def terminate_broker(broker_id):
    broker = shared.get_broker(broker_id)
    if broker["status"] not in ("SUBMITTED", "APPROVED", "SUSPENDED"):
        raise ApiError("ERR_BROKER_NOT_SUBMITTED",
                       "A broker in status %s cannot be terminated." % broker["status"])

    # priority - termination is gated by the active loan count
    shared.recompute_active_loan_count(broker)
    if int(broker["active_loan_count"]) != 0:
        raise ApiError("ERR_ACTIVE_LOANS_PRESENT",
                       "The broker still has %s active loans." % broker["active_loan_count"])

    broker["status"] = "TERMINATED"
    shared.withdraw_submitted_loans(broker)
    db.touch(broker)
    return broker


def reconciliation(broker_id):
    broker = shared.get_broker(broker_id)
    # The drift figure is the residual between the broker's stored derived
    # counters and an independent recomputation from the loan rows; it is 0
    # whenever the two agree, which is the case after any compensating
    # sequence (submit/withdraw, fund/repurchase, suspend/reinstate).
    funded_from_rows = 0
    active_from_rows = 0
    for loan in db.loan_submissions.values():
        if loan["broker_id"] != broker["id"]:
            continue
        if loan["status"] == "FUNDED":
            funded_from_rows += int(loan["loan_amount_cents"])
        if loan["status"] in ("SUBMITTED", "UNDERWRITING", "CONDITIONAL_APPROVAL",
                              "SUSPENDED_REVIEW", "CLEAR_TO_CLOSE"):
            active_from_rows += 1
    drift = (int(broker["rolling_funded_volume_cents"]) - funded_from_rows
             + int(broker["active_loan_count"]) - active_from_rows)
    return {
        "total_active_compensation_commitment_cents":
            broker["total_active_compensation_commitment_cents"],
        "rolling_funded_volume_cents": broker["rolling_funded_volume_cents"],
        "commitment_drift_cents": drift,
        "active_loan_count": broker["active_loan_count"],
    }


def list_brokers(status=None, home_state=None, tier=None, exclusivity_status=None):
    rows = []
    for row in db.brokers.values():
        if status and row["status"] != status:
            continue
        if home_state and row["home_state"] != home_state:
            continue
        if tier and row["tier"] != tier:
            continue
        if exclusivity_status and row["exclusivity_status"] != exclusivity_status:
            continue
        rows.append(row)
    return rows


def clamp_score(value):
    return quantize(max(SCORE_MIN, min(SCORE_MAX, to_decimal(value, ZERO))), 2)