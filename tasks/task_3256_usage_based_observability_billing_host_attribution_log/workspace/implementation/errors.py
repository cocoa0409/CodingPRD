"""Error taxonomy: ApiError carries error_id, message, and HTTP status."""

from flask import jsonify


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def invalid_request(msg="Request payload schema violation"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource id does not resolve"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Entity in a state that does not admit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def period_closed(msg="Mutation attempted against a CLOSED or SETTLED BillingPeriod"):
    return ApiError("ERR_PERIOD_CLOSED", 409, msg)


def stale_version(msg="expected_*_version does not match the parent's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def account_delinquent(msg="BillingAccount.standing != GOOD; blocks new commitments"):
    return ApiError("ERR_ACCOUNT_DELINQUENT", 409, msg)


def commitment_window_overlap(msg="Commitment window overlaps another commitment for same account+meter"):
    return ApiError("ERR_COMMITMENT_WINDOW_OVERLAP", 409, msg)


def tier_window_overlap(msg="RetentionTier effective window overlaps another tier's window"):
    return ApiError("ERR_TIER_WINDOW_OVERLAP", 409, msg)


def plan_limit(msg="Plan tier cap on ACTIVE monitors reached"):
    return ApiError("ERR_PLAN_LIMIT", 409, msg)


def tag_policy_violation(msg="TagPolicy with enforcement BLOCK rejects the UsageRecord"):
    return ApiError("ERR_TAG_POLICY_VIOLATION", 422, msg)


def duplicate_host_hour(msg="HostHourRecord for (period, hour_bucket_utc) already exists"):
    return ApiError("ERR_DUPLICATE_HOST_HOUR", 409, msg)


def no_active_commitment(msg="Reindex requires an ACTIVE Commitment covering meter=LOG_INDEX"):
    return ApiError("ERR_NO_ACTIVE_COMMITMENT", 409, msg)


def open_incidents_block_close(msg="BillingPeriod close attempted while CardinalityIncidents are still OPEN"):
    return ApiError("ERR_OPEN_INCIDENTS_BLOCK_CLOSE", 409, msg)
