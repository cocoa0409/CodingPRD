"""Error classes and error ID constants from the scaffold §1.6 catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized(msg="Role not permitted for the endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def err_forbidden(msg="Entity-scoped caller attempted to act on another entity's resource"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_sod(msg="Segregation of duties conflict"):
    return ApiError("ERR_SOD_CONFLICT", msg, 403)


def err_not_found(msg="Referenced id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Missing required field, wrong type, or invalid enum value"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Target resource is in a state from which the requested transition is undefined"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_entity_restricted(msg="Entity compliance_status is RESTRICTED"):
    return ApiError("ERR_ENTITY_RESTRICTED", msg, 409)


def err_standard_not_applicable(msg="Referenced standard is not in the entity's applicable_standards set"):
    return ApiError("ERR_STANDARD_NOT_APPLICABLE", msg, 422)


def err_invalid_interval(msg="Interval end not after start, or milestone due_date not in the future"):
    return ApiError("ERR_INVALID_INTERVAL", msg, 422)


def err_engagement_not_yet_open(msg="Engagement start attempted before period_start"):
    return ApiError("ERR_ENGAGEMENT_NOT_YET_OPEN", msg, 409)


def err_engagement_not_in_progress(msg="Evidence submitted to an engagement not in IN_PROGRESS"):
    return ApiError("ERR_ENGAGEMENT_NOT_IN_PROGRESS", msg, 409)


def err_evidence_not_reviewable(msg="Evidence accept/reject attempted while engagement is not IN_PROGRESS"):
    return ApiError("ERR_EVIDENCE_NOT_REVIEWABLE", msg, 409)


def err_cip_evidence_required(msg="ACCESS_LOG evidence missing a valid ACTIVE BES cyber asset reference"):
    return ApiError("ERR_CIP_EVIDENCE_REQUIRED", msg, 422)


def err_violation_source_invalid(msg="Violation source references are missing, mismatched, or not in the required terminal state"):
    return ApiError("ERR_VIOLATION_SOURCE_INVALID", msg, 422)


def err_violation_state(msg="Violation not in a state that permits the requested action"):
    return ApiError("ERR_VIOLATION_STATE", msg, 409)


def err_mitigation_plan_exists(msg="A mitigation plan already exists for this violation"):
    return ApiError("ERR_MITIGATION_PLAN_EXISTS", msg, 409)


def err_plan_state(msg="Mitigation plan not in a state that permits the requested action"):
    return ApiError("ERR_PLAN_STATE", msg, 409)


def err_milestones_incomplete(msg="complete-mitigation attempted with PENDING or MISSED milestones remaining"):
    return ApiError("ERR_MILESTONES_INCOMPLETE", msg, 409)


def err_self_log_not_enrolled(msg="Entity is not enrolled in the self-logging program"):
    return ApiError("ERR_SELF_LOG_NOT_ENROLLED", msg, 422)


def err_empty_review_period(msg="start-review attempted on a review period with zero entries"):
    return ApiError("ERR_EMPTY_REVIEW_PERIOD", msg, 422)


def err_entries_unreviewed(msg="close attempted while entries remain in LOGGED status"):
    return ApiError("ERR_ENTRIES_UNREVIEWED", msg, 409)


def err_active_access_grants(msg="CIP asset decommission attempted with ACTIVE access grants"):
    return ApiError("ERR_ACTIVE_ACCESS_GRANTS", msg, 409)


def err_asset_decommissioned(msg="Access grant attempted on a DECOMMISSIONED asset"):
    return ApiError("ERR_ASSET_DECOMMISSIONED", msg, 409)


def err_appeal_window_expired(msg="Appeal or federal-review request filed after its window closed"):
    return ApiError("ERR_APPEAL_WINDOW_EXPIRED", msg, 422)


def err_duplicate_active_appeal(msg="An appeal is already active for this violation"):
    return ApiError("ERR_DUPLICATE_ACTIVE_APPEAL", msg, 409)


def err_penalty_not_confirmed(msg="settle/waive attempted on a penalty not in CONFIRMED status"):
    return ApiError("ERR_PENALTY_NOT_CONFIRMED", msg, 409)


def err_penalty_already_resolved(msg="confirm attempted on a penalty not in ASSESSED status"):
    return ApiError("ERR_PENALTY_ALREADY_RESOLVED", msg, 409)


def err_stale_version(msg="expected_violation_version does not match the current Violation.version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)
