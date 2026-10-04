"""Error identifiers and the ApiError exception (PRD section 5 catalogue)."""


class ApiError(Exception):
    """Carries the scaffold error id, HTTP status and human message."""

    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message if message else error_id
        super().__init__("%s (%s)" % (error_id, self.http_status))


# Full error catalogue: id -> HTTP status (PRD section 5 / scaffold Table 6).
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHORIZED": 403,
    "ERR_REGION_NOT_FOUND": 404,
    "ERR_OPERATION_NOT_FOUND": 404,
    "ERR_SHELTER_SITE_NOT_FOUND": 404,
    "ERR_SHELTER_OPERATION_NOT_FOUND": 404,
    "ERR_VOLUNTEER_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_FUND_POOL_NOT_FOUND": 404,
    "ERR_BLOOD_DRIVE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CARD_ALREADY_ISSUED": 409,
    "ERR_SHELTER_RESTRICTED": 409,
    "ERR_VOLUNTEER_NOT_CREDENTIALED": 409,
    "ERR_SITE_NOT_APPROVED": 409,
    "ERR_INSPECTION_STALE": 409,
    "ERR_FUNCTIONAL_NEEDS_UNSUPPORTED": 409,
    "ERR_SOD_VIOLATION": 403,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_BED_OCCUPANCY_CONFLICT": 409,
    "ERR_BLOOD_DRIVE_WINDOW_OVERLAP": 409,
    "ERR_DUPLICATE_INCIDENT_CODE": 409,
    "ERR_DUPLICATE_FUND_CODE": 409,
    "ERR_ROTATION_TOO_LONG": 422,
    "ERR_ANNUAL_ROTATION_CAP": 422,
    "ERR_MAX_SHIFTS_EXCEEDED": 409,
    "ERR_AGENCY_NOT_AUTHORIZED": 409,
    "ERR_REGION_MISMATCH": 409,
    "ERR_DEPLOYMENT_SHELTER_MISMATCH": 409,
    "ERR_DUPLICATION_BLOCKED": 409,
    "ERR_ASSISTANCE_BELOW_MINIMUM": 409,
    "ERR_INSUFFICIENT_FUNDS": 409,
    "ERR_POOL_RESTRICTION_MISMATCH": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_NO_BED_AVAILABLE": 409,
    "ERR_NO_ELIGIBLE_VOLUNTEER": 409,
    "ERR_COLLECTION_TARGET_EXCEEDED": 409,
}


def fail(error_id, message=None):
    raise ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
