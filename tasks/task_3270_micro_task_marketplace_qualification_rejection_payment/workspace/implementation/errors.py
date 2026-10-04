"""Error catalogue and exception type.

Every refusable condition in the platform carries one of these ids from
SCAFFOLD.yaml §1.6 together with its pinned HTTP status.
"""


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the global handler."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status

    def body(self) -> dict:
        return {"error_id": self.error_id, "message": self.message}


# --- id -> (http status, default message) ---------------------------------
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or unknown X-User-Role / X-User-ID header."),
    "ERR_FORBIDDEN": (403, "Acting role not permitted for this endpoint, or acting principal is not the resource owner."),
    "ERR_NOT_FOUND": (404, "A path-segment id does not resolve to a row of its collection."),
    "ERR_INVALID_REQUEST": (400, "Malformed body, missing required field, or a field outside its declared enum/type."),
    "ERR_INVALID_STATE": (409, "Target resource is not in a state from which the requested transition is declared."),
    "ERR_REQUESTER_NOT_ACTIVE": (409, "Acting requester status is SUSPENDED or PENDING_REVIEW; publication and lifecycle writes are closed."),
    "ERR_REQUESTER_TASK_BLOCKED": (409, "Requester task_abuse_flag is TRUE, so new HIT publication is refused."),
    "ERR_WORKER_SUSPENDED": (409, "Acting worker status is SUSPENDED."),
    "ERR_QUALIFICATION_REQUIRED": (409, "Worker does not hold a live WorkerQualification for every required qualification id."),
    "ERR_EXAM_NOT_AVAILABLE": (409, "The qualification type's exam_available is FALSE."),
    "ERR_QUALIFICATION_EXAM_ATTEMPTS_EXCEEDED": (409, "The worker's scored attempt count for the exam has reached max_attempts."),
    "ERR_QUALIFICATION_EXAM_COOLDOWN_ACTIVE": (409, "Fewer than retake_cooldown_days have elapsed since the worker's last scored attempt."),
    "ERR_CONCURRENCY_LIMIT_EXCEEDED": (409, "Worker is at the concurrency cap and no ACCEPTED assignment is available to expire."),
    "ERR_HIT_MAX_ASSIGNMENTS_REACHED": (409, "The task pool has already reached max_assignments."),
    "ERR_REWARD_INVALID": (400, "reward_cents is not a positive integer, or a pool/time-limit field is not positive."),
    "ERR_ASSIGNMENT_EXPIRED": (409, "The assignment's time limit has elapsed; the write-path guard expires it and refuses the operation."),
    "ERR_ASSIGNMENT_NOT_EXPIRED": (409, "The sweep was called on a HIT with no ACCEPTED assignment whose time limit has elapsed."),
    "ERR_REVIEW_TOO_EARLY": (409, "Approval attempted before elapsed time reaches half of assignment_duration_minutes."),
    "ERR_REJECTION_REASON_REQUIRED": (400, "A rejection was submitted with an empty or missing reason."),
    "ERR_DISPUTE_WINDOW_CLOSED": (409, "More than DISPUTE_WINDOW_HOURS have elapsed since the rejection."),
    "ERR_DISPUTE_ALREADY_USED": (409, "The assignment has already used its single dispute."),
    "ERR_REQUESTER_REVIEW_NOT_TRIGGERED": (409, "The rolling rejection rate over the window is below ABUSE_FLAG_THRESHOLD_PCT."),
    "ERR_STALE_VERSION": (412, "expected_*_version does not match the parent row's current version."),
    "ERR_INSUFFICIENT_FUNDS": (402, "requester.prepaid_balance_cents is below hit.funds_required_cents at publication."),
    "ERR_BONUS_BUDGET_EXCEEDED": (409, "The bonus would push hit.spent_bonus_cents above hit.bonus_budget_cents."),
    "ERR_PAYOUT_THRESHOLD_NOT_MET": (409, "Requested amount is below the worker country's minimum payout threshold."),
    "ERR_PAYOUT_METHOD_INELIGIBLE": (409, "payment_method is not in the worker country's eligible method set."),
    "ERR_IDENTITY_NOT_VERIFIED": (409, "Payout release attempted while the worker's identity has not been recorded as VERIFIED."),
    "ERR_VETTING_HOLD_ACTIVE": (409, "Payout release attempted before payout.hold_until_at."),
    "ERR_ALREADY_COMPLETED_HIT": (409, "The worker already worked this task; a replacement slot is refused."),
}


def fail(error_id: str, message: str = None) -> None:
    """Raise the catalogued error, keeping the scaffold's pinned HTTP status."""
    status, default_message = ERROR_CATALOG[error_id]
    raise ApiError(error_id, message or default_message, status)