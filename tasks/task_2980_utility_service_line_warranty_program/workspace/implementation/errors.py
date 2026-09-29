"""The error catalogue (PRD section 5) and the exception it is raised through."""

ERROR_STATUS = {
    # --- authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- schema / pagination
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # --- existence
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_PREMISES_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    # --- optimistic concurrency
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_PREMISES_VERSION": 412,
    "ERR_STALE_ENROLLMENT_VERSION": 412,
    "ERR_STALE_PARTNER_VERSION": 412,
    "ERR_STALE_COMPLAINT_VERSION": 412,
    # --- state preconditions
    "ERR_INVALID_PARTNER_STATE": 409,
    "ERR_INVALID_CAMPAIGN_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_DISPATCH_STATE": 409,
    "ERR_INVALID_COMPLAINT_STATE": 409,
    "ERR_ENROLLMENT_TERMINAL": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    # --- cross-entity state gates
    "ERR_PARTNER_NOT_ACTIVE": 409,
    "ERR_NO_FILED_PRODUCT": 409,
    "ERR_PRODUCT_WITHDRAWN": 409,
    "ERR_CAMPAIGN_NOT_MAILED": 409,
    "ERR_MAILING_SUPPRESSED": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_CONTRACTOR_NOT_ACTIVE": 409,
    # --- business safety
    "ERR_CONTRACTOR_LICENSE_EXPIRED": 422,
    "ERR_PERMIT_REQUIRED": 422,
    # --- business referential
    "ERR_CONTRACTOR_NOT_CERTIFIED": 422,
    "ERR_INVALID_RECURRENCE_LINK": 422,
    "ERR_REMEDY_TARGET_MISSING": 422,
    "ERR_REMEDY_NOT_PERMITTED": 422,
    "ERR_BILL_INSERT_NOT_SUPPORTED": 422,
    "ERR_RESTORATION_SCOPE_NOT_COVERED": 422,
    "ERR_DENIAL_REASON_UNSUPPORTED": 422,
    # --- business temporal
    "ERR_DROP_WINDOW_CONFLICT": 422,
    "ERR_CONTRACTOR_WINDOW_CONFLICT": 422,
    "ERR_DROP_DATE_IN_FUTURE": 422,
    "ERR_WAITING_PERIOD_NOT_ELAPSED": 422,
    "ERR_APPEAL_WINDOW_EXPIRED": 422,
    "ERR_INSUFFICIENT_RENEWAL_NOTICE": 422,
    # --- business constraints
    "ERR_OWNERSHIP_NOT_ELIGIBLE": 422,
    "ERR_DUPLICATE_ACTIVE_ENROLLMENT": 422,
    "ERR_PRE_EXISTING_CONDITION": 422,
    "ERR_CANCELLATION_BLOCKED_APPEAL": 422,
    "ERR_CONTRACTOR_CAPACITY_EXCEEDED": 422,
    "ERR_NO_ELIGIBLE_CONTRACTOR": 422,
    "ERR_RATE_FILING_REQUIRED": 422,
    # --- fiscal
    "ERR_ANNUAL_CAP_EXHAUSTED": 422,
    "ERR_PER_OCCURRENCE_CAP_EXHAUSTED": 422,
    "ERR_REFUND_NOT_AVAILABLE": 422,
    "ERR_REVERSAL_EXCEEDS_BENEFIT": 422,
}


class ApiError(Exception):
    """Any refusal the API returns as an error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower().capitalize()


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
