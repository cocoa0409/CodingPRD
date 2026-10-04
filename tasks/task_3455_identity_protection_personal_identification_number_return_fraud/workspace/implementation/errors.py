"""Error catalog: error_id -> (http_status, default message).

IDs and statuses are verbatim from the PRD error catalogue (§5).
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers must be present and non-empty.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation, or an ownership check failed.",
    "ERR_DUTY_SEGREGATION_VIOLATION": "Segregation of duties: this action is forbidden to the user who created or opened the resource.",
    "ERR_TAXPAYER_NOT_FOUND": "The named taxpayer does not exist.",
    "ERR_RETURN_NOT_FOUND": "The named tax return does not exist.",
    "ERR_REPORT_NOT_FOUND": "The named identity-theft report does not exist.",
    "ERR_CASE_NOT_FOUND": "The named identity-verification case does not exist.",
    "ERR_CONFLICT_NOT_FOUND": "The named dependent conflict does not exist.",
    "ERR_PREPARER_NOT_FOUND": "The named preparer does not exist.",
    "ERR_ALERT_NOT_FOUND": "The named fraud-scheme alert does not exist.",
    "ERR_OFFICE_NOT_FOUND": "The named service office does not exist.",
    "ERR_DISBURSEMENT_NOT_FOUND": "The named refund disbursement does not exist.",
    "ERR_CONFIG_NOT_FOUND": "The named filter model config does not exist.",
    "ERR_HOLD_NOT_FOUND": "The named filter hold does not exist.",
    "ERR_ADVOCATE_CASE_NOT_FOUND": "The named advocate case does not exist.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or violates a declared constraint.",
    "ERR_INVALID_STATE": "The entity's current state does not permit the requested transition.",
    "ERR_ALREADY_TERMINAL": "The entity is in a terminal state and accepts no further transitions.",
    "ERR_RETURN_NOT_HELD": "The named return is not in FILTER_HELD.",
    "ERR_CASE_ALREADY_OPEN": "A non-terminal verification case already exists for this return.",
    "ERR_CONFLICT_ALREADY_RESOLVED": "The dependent conflict is already RESOLVED.",
    "ERR_CONFIG_NOT_DRAFT": "Only a DRAFT filter model config can be activated.",
    "ERR_CONFIG_NOT_ACTIVE": "No filter model config is ACTIVE.",
    "ERR_DUPLICATE_TIN": "A taxpayer with this tin already exists.",
    "ERR_DUPLICATE_RETURN": "A non-terminal return already exists for this taxpayer and tax year.",
    "ERR_DEPENDENT_CONFLICT_OPEN": "An OPEN dependent conflict already exists for this dependent TIN and tax year.",
    "ERR_ACTIVE_REPORT_WINDOW": "The taxpayer has a SUBMITTED report whose review window contains this submission.",
    "ERR_APPOINTMENT_CAPACITY_EXCEEDED": "The appointment interval would breach the office's overlap capacity.",
    "ERR_PREPARER_SUSPENDED": "A SUSPENDED preparer cannot file returns.",
    "ERR_STALE_VERSION": "expected_taxpayer_version does not match the taxpayer's current version.",
    "ERR_IP_PIN_REQUIRED": "An ENROLLED filer must present ip_pin_submitted.",
    "ERR_IP_PIN_MISMATCH": "ip_pin_submitted does not equal the ACTIVE pin for the taxpayer and tax year.",
    "ERR_NOT_ENROLLED": "The taxpayer is not ENROLLED in the IP PIN program.",
    "ERR_THRESHOLD_ORDER_INVALID": "gray_zone_threshold must be strictly below hold_threshold.",
    "ERR_VERIFICATION_WINDOW_EXPIRED": "The document was submitted after the case's deadline_at.",
    "ERR_VERIFICATION_INCOMPLETE": "Releasing a held refund requires a VERIFIED linked verification case.",
    "ERR_CHANNEL_NOT_ALLOWED": "The requested channel is not permitted for this operation.",
    "ERR_DISBURSEMENT_AMOUNT_MISMATCH": "expected_amount_cents does not equal the computed disbursement total.",
    "ERR_HARDSHIP_NOT_EXPEDITABLE": "Expedite requires a linked return in FILTER_HELD.",
}

HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_DUTY_SEGREGATION_VIOLATION": 403,
    "ERR_TAXPAYER_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_CONFLICT_NOT_FOUND": 404,
    "ERR_PREPARER_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_OFFICE_NOT_FOUND": 404,
    "ERR_DISBURSEMENT_NOT_FOUND": 404,
    "ERR_CONFIG_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_ADVOCATE_CASE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_RETURN_NOT_HELD": 409,
    "ERR_CASE_ALREADY_OPEN": 409,
    "ERR_CONFLICT_ALREADY_RESOLVED": 409,
    "ERR_CONFIG_NOT_DRAFT": 409,
    "ERR_CONFIG_NOT_ACTIVE": 409,
    "ERR_DUPLICATE_TIN": 409,
    "ERR_DUPLICATE_RETURN": 409,
    "ERR_DEPENDENT_CONFLICT_OPEN": 409,
    "ERR_ACTIVE_REPORT_WINDOW": 409,
    "ERR_APPOINTMENT_CAPACITY_EXCEEDED": 409,
    "ERR_PREPARER_SUSPENDED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_IP_PIN_REQUIRED": 422,
    "ERR_IP_PIN_MISMATCH": 422,
    "ERR_NOT_ENROLLED": 422,
    "ERR_THRESHOLD_ORDER_INVALID": 422,
    "ERR_VERIFICATION_WINDOW_EXPIRED": 422,
    "ERR_VERIFICATION_INCOMPLETE": 422,
    "ERR_CHANNEL_NOT_ALLOWED": 422,
    "ERR_DISBURSEMENT_AMOUNT_MISMATCH": 422,
    "ERR_HARDSHIP_NOT_EXPEDITABLE": 409,
}


def err(error_id, message=None):
    """Raise an ApiError with the catalogued HTTP status for error_id."""
    raise ApiError(error_id, HTTP_STATUS[error_id], message)
