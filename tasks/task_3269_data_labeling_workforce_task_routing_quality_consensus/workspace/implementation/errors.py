"""Error catalogue for the Data Labeling Ops API (PRD section 5).

Every validation ladder rung in PRD section 2.11 raises ApiError with one of the
error ids below. The id string and the HTTP status are the contract; the message
is human-readable only.
"""


class ApiError(Exception):
    """An error that maps onto the standard error envelope of PRD section 2.2."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# --- Rank 1: request well-formedness and identity -------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"

# --- Rank 2: role admissibility -------------------------------------------
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"

# --- Rank 3: existence, resolved left to right ----------------------------
ERR_PROGRAM_NOT_FOUND = "ERR_PROGRAM_NOT_FOUND"
ERR_SPEC_UNIT_NOT_FOUND = "ERR_SPEC_UNIT_NOT_FOUND"
ERR_ITEM_NOT_FOUND = "ERR_ITEM_NOT_FOUND"
ERR_COMMIT_NOT_FOUND = "ERR_COMMIT_NOT_FOUND"
ERR_GOLD_AUDIT_NOT_FOUND = "ERR_GOLD_AUDIT_NOT_FOUND"
ERR_WORKER_NOT_FOUND = "ERR_WORKER_NOT_FOUND"
ERR_QUALIFICATION_NOT_FOUND = "ERR_QUALIFICATION_NOT_FOUND"
ERR_APPEAL_CASE_NOT_FOUND = "ERR_APPEAL_CASE_NOT_FOUND"

# --- Rank 4: optimistic concurrency ---------------------------------------
ERR_STALE_VERSION = "ERR_STALE_VERSION"

# --- Rank 5: state admissibility ------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_INSTRUCTION_NOT_PUBLISHED = "ERR_INSTRUCTION_NOT_PUBLISHED"

# --- Rank 6: safety band ---------------------------------------------------
ERR_PROGRAM_OPERATIONALLY_RESTRICTED = "ERR_PROGRAM_OPERATIONALLY_RESTRICTED"
ERR_WORKER_RESTRICTED = "ERR_WORKER_RESTRICTED"
ERR_FIELD_SCHEMA_MISMATCH = "ERR_FIELD_SCHEMA_MISMATCH"
ERR_EDGE_CASE_GUIDANCE_CONFLICT = "ERR_EDGE_CASE_GUIDANCE_CONFLICT"

# --- Rank 7: referential integrity ----------------------------------------
ERR_UNIT_CODE_DUPLICATE = "ERR_UNIT_CODE_DUPLICATE"
ERR_SPEC_UNIT_CYCLE = "ERR_SPEC_UNIT_CYCLE"
ERR_INSTRUCTION_REVISION_MISMATCH = "ERR_INSTRUCTION_REVISION_MISMATCH"

# --- Rank 8: temporal band -------------------------------------------------
ERR_COMMIT_WINDOW_CLOSED = "ERR_COMMIT_WINDOW_CLOSED"
ERR_REQUIRED_UNITS_GAP = "ERR_REQUIRED_UNITS_GAP"
ERR_COVERAGE_WINDOW_OVERLAP = "ERR_COVERAGE_WINDOW_OVERLAP"
ERR_WORKER_LANE_CONFLICT = "ERR_WORKER_LANE_CONFLICT"
ERR_REWORK_WINDOW_EXPIRED = "ERR_REWORK_WINDOW_EXPIRED"

# --- Rank 9: remaining business constraints -------------------------------
ERR_NO_ELIGIBLE_WORKER = "ERR_NO_ELIGIBLE_WORKER"
ERR_GOLD_ROTATION_ACTIVE = "ERR_GOLD_ROTATION_ACTIVE"
ERR_PANEL_ALREADY_DISPATCHED = "ERR_PANEL_ALREADY_DISPATCHED"
ERR_QUORUM_NOT_REACHED = "ERR_QUORUM_NOT_REACHED"
ERR_REWORK_ROUND_LIMIT = "ERR_REWORK_ROUND_LIMIT"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_QUALIFICATION_SCORE_BELOW_TIER = "ERR_QUALIFICATION_SCORE_BELOW_TIER"
ERR_CAPACITY_INFEASIBLE = "ERR_CAPACITY_INFEASIBLE"

# --- Rank 10: fiscal band ---------------------------------------------------
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"
ERR_CURRENCY_MISMATCH = "ERR_CURRENCY_MISMATCH"
ERR_INSUFFICIENT_RECEIVABLE = "ERR_INSUFFICIENT_RECEIVABLE"


# Status codes, verbatim from PRD section 5.
STATUS_BY_ERROR = {
    ERR_INVALID_REQUEST: 400,
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_PROGRAM_NOT_FOUND: 404,
    ERR_SPEC_UNIT_NOT_FOUND: 404,
    ERR_ITEM_NOT_FOUND: 404,
    ERR_COMMIT_NOT_FOUND: 404,
    ERR_GOLD_AUDIT_NOT_FOUND: 404,
    ERR_WORKER_NOT_FOUND: 404,
    ERR_QUALIFICATION_NOT_FOUND: 404,
    ERR_APPEAL_CASE_NOT_FOUND: 404,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_ALREADY_TERMINAL: 409,
    ERR_INSTRUCTION_NOT_PUBLISHED: 409,
    ERR_PROGRAM_OPERATIONALLY_RESTRICTED: 409,
    ERR_WORKER_RESTRICTED: 403,
    ERR_FIELD_SCHEMA_MISMATCH: 400,
    ERR_EDGE_CASE_GUIDANCE_CONFLICT: 409,
    ERR_UNIT_CODE_DUPLICATE: 409,
    ERR_SPEC_UNIT_CYCLE: 409,
    ERR_INSTRUCTION_REVISION_MISMATCH: 409,
    ERR_COMMIT_WINDOW_CLOSED: 409,
    ERR_REQUIRED_UNITS_GAP: 409,
    ERR_COVERAGE_WINDOW_OVERLAP: 409,
    ERR_WORKER_LANE_CONFLICT: 409,
    ERR_REWORK_WINDOW_EXPIRED: 409,
    ERR_NO_ELIGIBLE_WORKER: 422,
    ERR_GOLD_ROTATION_ACTIVE: 409,
    ERR_PANEL_ALREADY_DISPATCHED: 409,
    ERR_QUORUM_NOT_REACHED: 409,
    ERR_REWORK_ROUND_LIMIT: 409,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_QUALIFICATION_SCORE_BELOW_TIER: 422,
    ERR_CAPACITY_INFEASIBLE: 409,
    ERR_PAYMENT_AMOUNT_MISMATCH: 422,
    ERR_CURRENCY_MISMATCH: 409,
    ERR_INSUFFICIENT_RECEIVABLE: 422,
}

MESSAGES = {
    ERR_INVALID_REQUEST: "A required input field is absent or carries a value of the wrong type.",
    ERR_UNAUTHENTICATED: "The X-User-ID and X-User-Role headers must both be present and non-empty.",
    ERR_UNAUTHORIZED: "The acting role is not admitted by this endpoint.",
    ERR_PROGRAM_NOT_FOUND: "The engagement named in the path does not exist.",
    ERR_SPEC_UNIT_NOT_FOUND: "The spec unit named in the path does not exist.",
    ERR_ITEM_NOT_FOUND: "The labeling piece named in the path does not exist.",
    ERR_COMMIT_NOT_FOUND: "The assignment named in the path does not exist.",
    ERR_GOLD_AUDIT_NOT_FOUND: "The gold audit named in the path does not exist or does not target the named item.",
    ERR_WORKER_NOT_FOUND: "The worker named in the path does not exist.",
    ERR_QUALIFICATION_NOT_FOUND: "The qualification named in the path does not exist.",
    ERR_APPEAL_CASE_NOT_FOUND: "The appeal case named in the path does not exist.",
    ERR_STALE_VERSION: "The supplied expected version does not equal the entity's current version.",
    ERR_INVALID_STATE: "The target resource is in a state that does not admit this operation.",
    ERR_ALREADY_TERMINAL: "The assignment is no longer DISPATCHED.",
    ERR_INSTRUCTION_NOT_PUBLISHED: "The unit instruction document has not reached PUBLISHED.",
    ERR_PROGRAM_OPERATIONALLY_RESTRICTED: "The engagement carries an unresolved MAJOR or CATASTROPHIC confidentiality incident.",
    ERR_WORKER_RESTRICTED: "The acting worker has an open confidentiality incident.",
    ERR_FIELD_SCHEMA_MISMATCH: "The committed payload key set does not equal the spec unit field_schema key set.",
    ERR_EDGE_CASE_GUIDANCE_CONFLICT: "Published edge case guidance contradicts a positive enumerated edge case count.",
    ERR_UNIT_CODE_DUPLICATE: "The unit_code, item_key or worker handle is already used in its scope.",
    ERR_SPEC_UNIT_CYCLE: "The declared parent unit would close a cycle in the decomposition graph.",
    ERR_INSTRUCTION_REVISION_MISMATCH: "The instruction revision differs from the unit's pinned frozen_revision.",
    ERR_COMMIT_WINDOW_CLOSED: "The logical clock has reached or passed the assignment commit_deadline_at.",
    ERR_REQUIRED_UNITS_GAP: "The piece would publish a zero detection gap.",
    ERR_COVERAGE_WINDOW_OVERLAP: "The coverage window overlaps the blackout window by a positive length.",
    ERR_WORKER_LANE_CONFLICT: "A selected worker already holds a touching or overlapping dispatched assignment.",
    ERR_REWORK_WINDOW_EXPIRED: "The rework window has lapsed.",
    ERR_NO_ELIGIBLE_WORKER: "The selector produced an empty eligible candidate set.",
    ERR_GOLD_ROTATION_ACTIVE: "The piece has already taken three gold audits this week epoch.",
    ERR_PANEL_ALREADY_DISPATCHED: "The committed production assignment count has reached panel_size.",
    ERR_QUORUM_NOT_REACHED: "Fewer than commitment_quorum non-abstaining commits exist.",
    ERR_REWORK_ROUND_LIMIT: "The piece has exhausted its rework round limit.",
    ERR_SEGREGATION_OF_DUTIES: "The acting reviewer holds a commit on the disputed piece.",
    ERR_QUALIFICATION_SCORE_BELOW_TIER: "The qualification score is below the declared tier minimum.",
    ERR_CAPACITY_INFEASIBLE: "The plan is infeasible under the requested accuracy variant.",
    ERR_PAYMENT_AMOUNT_MISMATCH: "The asserted payout amount differs from the computed capped amount.",
    ERR_CURRENCY_MISMATCH: "The currency differs from the worker payout_currency.",
    ERR_INSUFFICIENT_RECEIVABLE: "The operation would drive worker_receivable_cents strictly negative.",
}


def fail(error_id, message=None):
    """Raise the catalogue error, deriving the HTTP status from PRD section 5."""
    raise ApiError(
        error_id,
        STATUS_BY_ERROR[error_id],
        message or MESSAGES.get(error_id, error_id),
    )