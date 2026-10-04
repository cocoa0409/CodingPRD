"""API error type. error_id / http_status come from the scaffold catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# -- 400 / 401 / 403 ---------------------------------------------------------
def invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def unauthenticated(msg="Missing or unknown X-User-Role, or missing X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized_role(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def not_resource_owner(msg="Caller does not own the target resource"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


# -- 404 ---------------------------------------------------------------------
def office_not_found():
    return ApiError("ERR_STATE_OFFICE_NOT_FOUND", 404, "No StateOffice with that id")


def investigation_not_found():
    return ApiError("ERR_INVESTIGATION_NOT_FOUND", 404, "No Investigation with that id")


def participation_not_found():
    return ApiError("ERR_PARTICIPATION_NOT_FOUND", 404, "No Participation with that id")


def response_not_found():
    return ApiError("ERR_RESPONSE_NOT_FOUND", 404, "No ConsolidatedResponse with that id")


def settlement_not_found():
    return ApiError("ERR_SETTLEMENT_NOT_FOUND", 404, "No Settlement with that id")


def line_not_found():
    return ApiError("ERR_ALLOCATION_LINE_NOT_FOUND", 404, "No AllocationLine with that id")


def disbursement_not_found():
    return ApiError("ERR_DISBURSEMENT_NOT_FOUND", 404, "No Disbursement with that id")


def claimant_not_found():
    return ApiError("ERR_CLAIMANT_NOT_FOUND", 404, "No Claimant with that id")


def period_not_found():
    return ApiError("ERR_MONITORING_PERIOD_NOT_FOUND", 404, "No MonitoringPeriod with that id")


# -- 409 / 412 / 422 (raised ad hoc at call sites) ---------------------------
def invalid_phase(msg="Investigation phase forbids the operation"):
    return ApiError("ERR_INVALID_PHASE", 409, msg)


def invalid_state(msg="Resource state forbids the trigger"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
