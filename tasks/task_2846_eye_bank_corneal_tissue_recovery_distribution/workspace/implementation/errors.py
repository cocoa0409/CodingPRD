"""Error catalogue and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_HTTP.get(error_id, 400)


ERROR_HTTP = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_UNKNOWN_ACTOR": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # existence
    "ERR_DONOR_NOT_FOUND": 404,
    "ERR_SEROLOGY_PANEL_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_RECOVERY_NOT_FOUND": 404,
    "ERR_TISSUE_NOT_FOUND": 404,
    "ERR_SURGEON_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # optimistic concurrency
    "ERR_STALE_TISSUE_VERSION": 412,
    "ERR_STALE_DONOR_VERSION": 412,
    # lifecycle / state
    "ERR_DONOR_STATE_INVALID": 409,
    "ERR_PANEL_STATE_INVALID": 409,
    "ERR_RECOVERY_STATE_INVALID": 409,
    "ERR_TISSUE_NOT_ELIGIBLE": 409,
    "ERR_TISSUE_CUSTODY_INVALID": 409,
    "ERR_REQUEST_STATE_INVALID": 409,
    "ERR_ALLOCATION_STATE_INVALID": 409,
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_INVESTIGATION_STATE_INVALID": 409,
    # business rules
    "ERR_CONSENT_SCOPE_VIOLATION": 422,
    "ERR_SEROLOGY_REACTIVE": 422,
    "ERR_SEROLOGY_PENDING": 422,
    "ERR_DONOR_UNDER_LOOKBACK": 422,
    "ERR_SCREENING_RISK_TOO_HIGH": 422,
    "ERR_DEATH_TIME_IN_FUTURE": 422,
    "ERR_PRESERVATION_WINDOW_EXCEEDED": 422,
    "ERR_TECHNICIAN_NOT_CERTIFIED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_EVALUATION_INCOMPLETE": 422,
    "ERR_SURGEON_NOT_CREDENTIALED": 422,
    "ERR_PROCEDURE_CLASSIFICATION_MISMATCH": 422,
    "ERR_ECD_BELOW_REQUEST_MINIMUM": 422,
    "ERR_DONOR_AGE_ABOVE_REQUEST_MAX": 422,
    "ERR_SURGERY_DATE_IN_PAST": 422,
    "ERR_TISSUE_EXPIRED": 422,
    "ERR_EXPIRY_BEFORE_SURGERY_DATE": 422,
    "ERR_NO_ELIGIBLE_TISSUE": 422,
    "ERR_NO_TEMPERATURE_BASELINE": 422,
    "ERR_READING_OUTSIDE_SHIPMENT_WINDOW": 422,
    "ERR_INVALID_REISSUE_SOURCE": 422,
    "ERR_SHIPMENT_INTEGRITY_FAILED": 422,
    "ERR_REPORT_TISSUE_NOT_IMPLANTED_BY_SURGEON": 422,
    "ERR_CLOCK_REWIND_FORBIDDEN": 422,
    # conflicts / uniqueness / capacity
    "ERR_TECHNICIAN_DISPATCH_OVERLAP": 409,
    "ERR_SURGEON_DAY_CAPACITY_EXCEEDED": 409,
    "ERR_REISSUE_LIMIT_REACHED": 409,
    "ERR_DUPLICATE_DONOR_CODE": 409,
    "ERR_DUPLICATE_SCREENING_ANSWER": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or malformed.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not perform this operation.",
    "ERR_UNKNOWN_ACTOR": "The acting identity does not resolve to a known actor.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity does not own this resource.",
    "ERR_INVALID_REQUEST": "The request payload failed schema validation.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range.",
    "ERR_STALE_TISSUE_VERSION": "The supplied tissue version does not match the stored version.",
    "ERR_STALE_DONOR_VERSION": "The supplied donor version does not match the stored version.",
}
