"""Error catalogue: every error_id from PRD §5 with its HTTP status."""
from __future__ import annotations

ERROR_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CLINICIAN_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_PAYER_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_NOTE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_CONTINUITY_PLAN_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_CASELOAD_FULL": 409,
    "ERR_CLINICIAN_SLOT_CONFLICT": 409,
    "ERR_PATIENT_DOUBLE_BOOKED": 409,
    "ERR_BATCH_NOT_LOCKABLE": 409,
    "ERR_BATCH_NOT_PAYABLE": 409,
    "ERR_WRITE_OFF_NOT_ALLOWED": 409,
    "ERR_PAYER_SUSPENDED": 409,
    "ERR_CONTINUITY_DEADLINE_PASSED": 409,
    "ERR_DUPLICATE_RATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CLINICIAN_NOT_BILLABLE": 422,
    "ERR_SERVICE_NOT_ENROLLED": 422,
    "ERR_OUTSIDE_ENROLLMENT_WINDOW": 422,
    "ERR_TIMELY_FILING_EXPIRED": 422,
    "ERR_RESUBMISSION_LIMIT_REACHED": 422,
    "ERR_DOCUMENTATION_MISSING": 422,
    "ERR_DURATION_MISMATCH": 422,
    "ERR_NOTE_SUPERSEDED": 422,
    "ERR_BENEFIT_UNVERIFIED": 422,
    "ERR_NO_ELIGIBLE_CLINICIAN": 422,
    "ERR_MATCH_TIE_UNRESOLVABLE": 422,
    "ERR_ENROLLMENT_WINDOW_INVALID": 422,
}

MESSAGES = {
    "ERR_INVALID_REQUEST": "The request is structurally malformed.",
    "ERR_UNAUTHENTICATED": "X-User-Role or X-User-ID header missing, empty or undeclared.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted on this endpoint.",
    "ERR_CLINICIAN_NOT_FOUND": "No clinician exists with the given id.",
    "ERR_LICENSE_NOT_FOUND": "No license exists with the given id for the given clinician.",
    "ERR_PAYER_NOT_FOUND": "No payer exists with the given id.",
    "ERR_ENROLLMENT_NOT_FOUND": "No payer enrollment exists with the given id.",
    "ERR_PATIENT_NOT_FOUND": "No patient exists with the given id.",
    "ERR_SESSION_NOT_FOUND": "No session exists with the given id.",
    "ERR_NOTE_NOT_FOUND": "No session note exists with the given id for the given session.",
    "ERR_CLAIM_NOT_FOUND": "No claim exists with the given id.",
    "ERR_BATCH_NOT_FOUND": "No payout batch exists with the given id.",
    "ERR_CONTINUITY_PLAN_NOT_FOUND": "No continuity plan exists with the given id.",
    "ERR_INVALID_STATE": "The resource is not in a state from which the transition is declared.",
    "ERR_ALREADY_TERMINAL": "The resource is in a terminal state and admits no further transition.",
    "ERR_CASELOAD_FULL": "The clinician's caseload target would be reached or passed.",
    "ERR_CLINICIAN_SLOT_CONFLICT": "The interval is unavailable or overlaps another session on the clinician.",
    "ERR_PATIENT_DOUBLE_BOOKED": "The interval overlaps another non-terminal session on the patient.",
    "ERR_BATCH_NOT_LOCKABLE": "The batch cannot be locked in its current period, status or line composition.",
    "ERR_BATCH_NOT_PAYABLE": "The batch cannot be paid in its current status or line composition.",
    "ERR_WRITE_OFF_NOT_ALLOWED": "The claim is still within its recovery window and has resubmissions left.",
    "ERR_PAYER_SUSPENDED": "The operation requires an ACTIVE payer.",
    "ERR_CONTINUITY_DEADLINE_PASSED": "The continuity plan's reassignment deadline has passed.",
    "ERR_DUPLICATE_RATE": "A rate row with the same key combination already exists.",
    "ERR_STALE_VERSION": "The supplied version does not match the resource's current version.",
    "ERR_CLINICIAN_NOT_BILLABLE": "The clinician's billing posture is GATED or FROZEN.",
    "ERR_SERVICE_NOT_ENROLLED": "The payer, CPT code or enrollment does not cover this service date.",
    "ERR_OUTSIDE_ENROLLMENT_WINDOW": "The service date falls outside the covering enrollment's window.",
    "ERR_TIMELY_FILING_EXPIRED": "The claim's recovery deadline has been reached.",
    "ERR_RESUBMISSION_LIMIT_REACHED": "The claim has already used both resubmissions.",
    "ERR_DOCUMENTATION_MISSING": "The session carries no signed note.",
    "ERR_DURATION_MISMATCH": "A note's duration does not equal the session's scheduled length.",
    "ERR_NOTE_SUPERSEDED": "The newest note for the session is not SIGNED.",
    "ERR_BENEFIT_UNVERIFIED": "The patient's benefit status is not VERIFIED.",
    "ERR_NO_ELIGIBLE_CLINICIAN": "No clinician satisfied the match eligibility conditions.",
    "ERR_MATCH_TIE_UNRESOLVABLE": "Two candidates remained tied on every ranking key.",
    "ERR_ENROLLMENT_WINDOW_INVALID": "effective_to is at or before effective_from.",
}


class ApiError(Exception):
    def __init__(self, error_id: str, status: int | None = None, message: str | None = None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status if status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or MESSAGES.get(error_id, error_id)


def fail(error_id: str, message: str | None = None) -> ApiError:
    return ApiError(error_id, message=message)