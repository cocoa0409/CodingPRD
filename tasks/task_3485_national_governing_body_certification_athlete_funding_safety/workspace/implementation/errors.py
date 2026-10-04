"""Error catalog (PRD section 5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs (exact strings from PRD section 5 / SCAFFOLD errors table).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_SCORE_OUT_OF_RANGE = "ERR_SCORE_OUT_OF_RANGE"    # 422
ERR_CYCLE_WINDOW_INVALID = "ERR_CYCLE_WINDOW_INVALID"    # 422
ERR_CYCLE_WINDOW_OVERLAP = "ERR_CYCLE_WINDOW_OVERLAP"    # 409
ERR_AGREEMENT_WINDOW_OVERLAP = "ERR_AGREEMENT_WINDOW_OVERLAP"  # 409
ERR_DEAL_EXCLUSIVITY_OVERLAP = "ERR_DEAL_EXCLUSIVITY_OVERLAP"  # 409
ERR_PUBLISH_LEAD_TIME = "ERR_PUBLISH_LEAD_TIME"      # 422
ERR_REGISTRATION_CLOSED = "ERR_REGISTRATION_CLOSED"  # 422
ERR_APPEAL_WINDOW_EXPIRED = "ERR_APPEAL_WINDOW_EXPIRED"  # 422
ERR_TRIALS_NOT_OPEN = "ERR_TRIALS_NOT_OPEN"          # 409
ERR_SCREENING_NOT_CLEARED = "ERR_SCREENING_NOT_CLEARED"  # 422
ERR_TRAINING_EXPIRED = "ERR_TRAINING_EXPIRED"        # 422
ERR_ATHLETE_NOT_ELIGIBLE = "ERR_ATHLETE_NOT_ELIGIBLE"    # 409
ERR_DUPLICATE_ENTRY = "ERR_DUPLICATE_ENTRY"          # 409
ERR_RESULTS_NOT_FINAL = "ERR_RESULTS_NOT_FINAL"      # 409
ERR_PENDING_APPEALS = "ERR_PENDING_APPEALS"          # 409
ERR_PENDING_SLOT_DECISIONS = "ERR_PENDING_SLOT_DECISIONS"  # 409
ERR_DEAL_CONSENT_REQUIRED = "ERR_DEAL_CONSENT_REQUIRED"  # 409
ERR_INSURANCE_NOT_ELIGIBLE = "ERR_INSURANCE_NOT_ELIGIBLE"  # 422
ERR_FUNDING_BUDGET_EXCEEDED = "ERR_FUNDING_BUDGET_EXCEEDED"  # 422
ERR_INTERNAL = "ERR_INTERNAL"                        # 500 (uncaught guard only)


def unauthenticated(msg="missing or unknown X-User-ID / X-User-Role headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="caller role is not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="requested transition is not defined from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="resource is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)


def stale_version(msg="expected version does not match the resource's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def segregation(msg="segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def score_range(msg="score or placing outside its declared range"):
    return ApiError(ERR_SCORE_OUT_OF_RANGE, 422, msg)
