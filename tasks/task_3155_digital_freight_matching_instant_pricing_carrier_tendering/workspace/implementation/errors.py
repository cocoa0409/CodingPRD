"""Error catalogue for the Digital Freight Matching API.

Every identifier below appears verbatim in PRD.md section 5 (and in
SCAFFOLD.yaml Table 6) together with its HTTP status code.
"""

# error_id -> (http_status, human readable message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers missing or role not recognised."),
    "ERR_UNAUTHORIZED": (403, "The acting role may not perform this operation."),
    "ERR_INVALID_REQUEST": (400, "The request is malformed or carries an unacceptable value."),
    "ERR_WINDOW_ORDER": (400, "window_end must be strictly after window_start."),
    "ERR_DUPLICATE_MC_NUMBER": (400, "mc_number is already registered on another carrier."),
    "ERR_LOAD_NOT_FOUND": (404, "load_id does not resolve."),
    "ERR_CARRIER_NOT_FOUND": (404, "carrier_id does not resolve."),
    "ERR_SHIPPER_NOT_FOUND": (404, "shipper_id does not resolve."),
    "ERR_FACILITY_NOT_FOUND": (404, "facility_id does not resolve."),
    "ERR_EQUIPMENT_NOT_FOUND": (404, "equipment_id does not resolve."),
    "ERR_QUOTE_NOT_FOUND": (404, "rate_quote_id does not resolve."),
    "ERR_BOOKING_NOT_FOUND": (404, "booking_id does not resolve."),
    "ERR_APPOINTMENT_NOT_FOUND": (404, "appointment_id does not resolve."),
    "ERR_DETENTION_NOT_FOUND": (404, "detention_id does not resolve."),
    "ERR_CLAIM_NOT_FOUND": (404, "claim_id does not resolve."),
    "ERR_SETTLEMENT_NOT_FOUND": (404, "settlement_id does not resolve."),
    "ERR_CONTRACT_NOT_FOUND": (404, "lane_contract_id does not resolve."),
    "ERR_INVALID_STATE": (409, "The resource is not in a state from which the requested transition is declared."),
    "ERR_ALREADY_TERMINAL": (409, "The resource has already reached a terminal state."),
    "ERR_QUOTE_EXPIRED": (409, "The logical clock has reached the quote's acceptance_deadline."),
    "ERR_QUOTE_NOT_VIEWABLE": (409, "The quote's load is no longer POSTED."),
    "ERR_CARRIER_NOT_VERIFIED": (409, "carrier.status is not VERIFIED."),
    "ERR_AUTHORITY_REVOKED": (409, "Operating authority is REVOKED."),
    "ERR_INSURANCE_EXPIRED": (409, "insurance_expires_at is at or before the logical clock."),
    "ERR_SAFETY_SCORE_TOO_LOW": (409, "safety_score exceeds 80.0."),
    "ERR_CARRIER_BLOCKED": (409, "The carrier appears in the shipper's blocked_carrier_ids."),
    "ERR_CARRIER_NOT_COMPLIANT": (409, "The carrier is not VERIFIED, so the claim cannot be settled."),
    "ERR_INSURANCE_LIMIT_BELOW_MINIMUM": (409, "insurance_liability_limit_cents is below 75,000,000 cents."),
    "ERR_CARGO_COVERAGE_BELOW_MINIMUM": (409, "cargo_coverage_limit_cents is below 100,000,000 cents."),
    "ERR_NO_EQUIPMENT_ON_FILE": (409, "No AVAILABLE equipment unit exists for this carrier."),
    "ERR_APPOINTMENT_OVERLAP": (409, "No dock position survives the 120-minute buffered dock window comparison."),
    "ERR_EQUIPMENT_WINDOW_CONFLICT": (409, "The requested window overlaps a non-terminal booking on the same unit."),
    "ERR_TRACKING_SEQUENCE_OUT_OF_ORDER": (409, "sequence is not one greater than the load's existing ping count."),
    "ERR_TRACKING_SEQUENCE_GAP": (409, "status_rank skips a step beyond the greatest rank observed plus one."),
    "ERR_SETTLEMENT_NOT_DUE": (409, "A TERMS payout was attempted strictly before payout_due_at."),
    "ERR_SETTLEMENT_ALREADY_PAID": (409, "The settlement has already been paid."),
    "ERR_DOCK_CAPACITY_EXCEEDED": (409, "docks_committed_today has reached dock_capacity."),
    "ERR_LOAD_CREDIT_EXHAUSTED": (409, "load_credits_committed has reached load_credit_limit."),
    "ERR_REPOST_LIMIT_REACHED": (409, "repost_count has already reached 3."),
    "ERR_CLAIM_REVIEW_ROUNDS_EXHAUSTED": (409, "The claim has exhausted its three review rounds."),
    "ERR_CLAIM_ALREADY_REVIEWED": (409, "The claim already has a review round behind it."),
    "ERR_CLAIM_NOT_REVIEWED": (409, "No review round has been recorded for this claim."),
    "ERR_ESCALATION_THRESHOLD_NOT_MET": (409, "provisional_liability_cents is not strictly greater than 2,500,000."),
    "ERR_EQUIPMENT_UNAVAILABLE": (409, "The chosen unit is IN_SHOP or its equipment_type differs from the load's."),
    "ERR_EQUIPMENT_CARRIER_MISMATCH": (409, "The chosen unit belongs to a different carrier."),
    "ERR_QUOTE_LOAD_MISMATCH": (409, "The quote belongs to a different load."),
    "ERR_SHIPPER_CREDIT_EXHAUSTED": (409, "credit_available_cents is below the locked price being accepted."),
    "ERR_CARRIER_RISK_BLOCKED": (409, "operational_risk_score is below 40.0."),
    "ERR_CONTRACT_NOT_ACTIVE": (409, "The referenced lane contract is not ACTIVE or its term does not cover now."),
    "ERR_OPEN_CLAIMS_BLOCK_SETTLEMENT": (409, "The load carries a claim in FILED, UNDER_REVIEW or INFO_REQUESTED."),
    "ERR_NO_APPROVED_CLAIM": (409, "No APPROVED claim exists on the booking or load."),
    "ERR_CLAIM_BEFORE_DELIVERY": (409, "The load has not reached DELIVERED."),
    "ERR_WAIVE_REASON_REQUIRED": (409, "reason_code must be FACILITY_FAULT, FORCE_MAJEURE or GOODWILL."),
    "ERR_RESCHEDULE_ONLY_EARLIER": (409, "An appointment can only be pulled earlier."),
    "ERR_STALE_VERSION": (412, "The expected version does not match the parent's current version."),
}


class ApiError(Exception):
    """Carries the error_id / message / http status of a refused request."""

    def __init__(self, error_id, message=None, http_status=None):
        if error_id not in ERRORS:
            raise KeyError("unknown error id: %s" % error_id)
        default_status, default_message = ERRORS[error_id]
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = http_status or default_status
        super().__init__(self.error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)