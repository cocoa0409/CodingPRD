"""Error classes and error ID constants (PRD §5 error catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error IDs (exact strings from the PRD §5 catalogue)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"              # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                          # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                          # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"      # 422
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                  # 412
ERR_UNIQUENESS_VIOLATION = "ERR_UNIQUENESS_VIOLATION"    # 409
ERR_TEMPORAL_OVERLAP = "ERR_TEMPORAL_OVERLAP"            # 422
ERR_SNAPSHOT_INVALID = "ERR_SNAPSHOT_INVALID"            # 422
ERR_NO_ELIGIBLE_CATEGORY = "ERR_NO_ELIGIBLE_CATEGORY"    # 422
ERR_CONFLICT_OF_INTEREST = "ERR_CONFLICT_OF_INTEREST"    # 422
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"                  # 422
ERR_QUORUM_NOT_MET = "ERR_QUORUM_NOT_MET"                # 422
ERR_SEAT_LIMIT_REACHED = "ERR_SEAT_LIMIT_REACHED"        # 422
ERR_LICENSE_TIER_INSUFFICIENT = "ERR_LICENSE_TIER_INSUFFICIENT"  # 422
ERR_DISPUTE_NOT_ISSUER = "ERR_DISPUTE_NOT_ISSUER"        # 422
ERR_RATING_KIND_MISMATCH = "ERR_RATING_KIND_MISMATCH"    # 409
ERR_METHODOLOGY_NOT_EFFECTIVE = "ERR_METHODOLOGY_NOT_EFFECTIVE"  # 409
ERR_SUPPRESSED_RATING = "ERR_SUPPRESSED_RATING"          # 409
ERR_OPEN_DISPUTES_REMAIN = "ERR_OPEN_DISPUTES_REMAIN"    # 409
ERR_ARREARS_OUTSTANDING = "ERR_ARREARS_OUTSTANDING"      # 409
ERR_SEATS_STILL_ACTIVE = "ERR_SEATS_STILL_ACTIVE"        # 409
ERR_INDEX_NOT_LICENSABLE = "ERR_INDEX_NOT_LICENSABLE"    # 409
ERR_AUDIT_OUTCOME_INVALID = "ERR_AUDIT_OUTCOME_INVALID"  # 422
ERR_VALIDATION = "ERR_VALIDATION"                        # 400
ERR_FUTURE_EFFECTIVE_DATE = "ERR_FUTURE_EFFECTIVE_DATE"  # 422


def unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Request-body FK references a non-existent entity"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 422, msg)


def invalid_state(msg="Transition not legal from the resource's current state"):
    return ApiError(ERR_INVALID_STATE_TRANSITION, 409, msg)


def stale_version(msg="Stale expected version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def uniqueness(msg="Unique constraint violated"):
    return ApiError(ERR_UNIQUENESS_VIOLATION, 409, msg)


def temporal_overlap(msg="Effectiveness window overlaps or is misordered"):
    return ApiError(ERR_TEMPORAL_OVERLAP, 422, msg)


def snapshot_invalid(msg="Holdings snapshot integrity violation"):
    return ApiError(ERR_SNAPSHOT_INVALID, 422, msg)


def no_eligible_category(msg="No active category satisfies min_weight_bp for the latest snapshot"):
    return ApiError(ERR_NO_ELIGIBLE_CATEGORY, 422, msg)


def conflict_of_interest(msg="Open commercial-rating conflict blocks this operation"):
    return ApiError(ERR_CONFLICT_OF_INTEREST, 422, msg)


def sod_violation(msg="Segregation-of-duties violation"):
    return ApiError(ERR_SOD_VIOLATION, 422, msg)


def seat_limit(msg="Seat quota reached or agreement/licensee not ACTIVE"):
    return ApiError(ERR_SEAT_LIMIT_REACHED, 422, msg)


def license_tier_insufficient(msg="Requires an ACTIVE agreement with tier DERIVED_WORKS"):
    return ApiError(ERR_LICENSE_TIER_INSUFFICIENT, 422, msg)


def dispute_not_issuer(msg="Dispute raiser is not the fund's issuer or corrected_value missing"):
    return ApiError(ERR_DISPUTE_NOT_ISSUER, 422, msg)


def rating_kind_mismatch(msg="Rating kind does not support this operation"):
    return ApiError(ERR_RATING_KIND_MISMATCH, 409, msg)


def methodology_not_effective(msg="Methodology is not in EFFECTIVE status"):
    return ApiError(ERR_METHODOLOGY_NOT_EFFECTIVE, 409, msg)


def suppressed_rating(msg="Rating is suppressed and cannot be published"):
    return ApiError(ERR_SUPPRESSED_RATING, 409, msg)


def open_disputes_remain(msg="Operation blocked while open disputes remain"):
    return ApiError(ERR_OPEN_DISPUTES_REMAIN, 409, msg)


def arrears_outstanding(msg="Licensee has outstanding arrears"):
    return ApiError(ERR_ARREARS_OUTSTANDING, 409, msg)


def seats_still_active(msg="Agreement termination requires seats_in_use == 0"):
    return ApiError(ERR_SEATS_STILL_ACTIVE, 409, msg)


def index_not_licensable(msg="Index launch preconditions unmet"):
    return ApiError(ERR_INDEX_NOT_LICENSABLE, 409, msg)


def audit_outcome_invalid(msg="Closing an audit with PENALTY requires unlicensed_uses_found > 0"):
    return ApiError(ERR_AUDIT_OUTCOME_INVALID, 422, msg)


def validation(msg="Malformed request"):
    return ApiError(ERR_VALIDATION, 400, msg)


def future_effective_date(msg="Effective date is in the future relative to the logical clock"):
    return ApiError(ERR_FUTURE_EFFECTIVE_DATE, 422, msg)
