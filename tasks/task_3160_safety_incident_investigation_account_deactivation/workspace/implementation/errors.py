"""Error catalogue.

Every identifier below appears verbatim in the PRD error catalogue (§5) and in
the SCAFFOLD error table (§1.6); the HTTP statuses are the ones those tables pin.
"""


class ApiError(Exception):
    """Carries the PRD error identifier, HTTP status and message.

    The catalogue entries are ``(error_id, http_status)`` tuples, so call sites
    write ``ApiError(*ERR_X, message=...)``; the parameter names are chosen so the
    expanded status lands in ``http_status`` and never collides with ``message``.
    """

    def __init__(self, error_id="ERR_INVALID_STATE", http_status=None, *,
                 message=None, status=None):
        if http_status is None:
            http_status = status if status is not None else 409
        if message is None:
            message = error_id
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def raise_error(spec, message=None):
    error_id, status = spec
    raise ApiError(error_id, status, message=message or error_id)


# --- authentication / authorisation -----------------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)

# --- existence ---------------------------------------------------------------
ERR_RESOURCE_NOT_FOUND = ("ERR_RESOURCE_NOT_FOUND", 404)
ERR_INCIDENT_NOT_FOUND = ("ERR_INCIDENT_NOT_FOUND", 404)
ERR_TRIP_NOT_FOUND = ("ERR_TRIP_NOT_FOUND", 404)

# --- state -------------------------------------------------------------------
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_APPEAL_ALREADY_FILED = ("ERR_APPEAL_ALREADY_FILED", 409)
ERR_HOLD_BLOCKED_BY_APPEAL = ("ERR_HOLD_BLOCKED_BY_APPEAL", 409)

# --- business rules ----------------------------------------------------------
ERR_SEVERITY_BELOW_HOLD_FLOOR = ("ERR_SEVERITY_BELOW_HOLD_FLOOR", 422)
ERR_APPEAL_WINDOW_CLOSED = ("ERR_APPEAL_WINDOW_CLOSED", 422)
ERR_APPEAL_NOT_ELIGIBLE = ("ERR_APPEAL_NOT_ELIGIBLE", 422)
ERR_THROWN_ON_APPEAL = ("ERR_THROWN_ON_APPEAL", 422)
ERR_REGULATOR_REPORT_BLOCKED = ("ERR_REGULATOR_REPORT_BLOCKED", 409)
ERR_IN_FLIGHT_APPEAL = ("ERR_IN_FLIGHT_APPEAL", 409)
ERR_CLUSTER_BANNED = ("ERR_CLUSTER_BANNED", 422)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_TRIP_ACCOUNT_MISMATCH = ("ERR_TRIP_ACCOUNT_MISMATCH", 422)
ERR_CROSS_REGION_REFERENCE = ("ERR_CROSS_REGION_REFERENCE", 422)
ERR_REPORTER_ACCOUNT_MISMATCH = ("ERR_REPORTER_ACCOUNT_MISMATCH", 422)
ERR_ADVERSE_REASON_REQUIRED = ("ERR_ADVERSE_REASON_REQUIRED", 422)
ERR_MONTHLY_REPORT_CAP_REACHED = ("ERR_MONTHLY_REPORT_CAP_REACHED", 422)