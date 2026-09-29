"""Error catalogue (PRD section 5) and the exception type carrying it."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_PROJECT_MANAGER": 403,
    "ERR_NOT_PROJECT_CLIENT": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_APPROVAL_LEVEL_INSUFFICIENT": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_PHASE_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    "ERR_SUBCONTRACT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_WRITE_OFF_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_MULTIPLIER_NOT_FOUND": 404,
    # referential integrity (body FKs)
    "ERR_INVALID_REFERENCE": 422,
    # concurrency
    "ERR_STALE_PROJECT_VERSION": 412,
    # state
    "ERR_PROJECT_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_PROJECT_UNDER_BILLING_REVIEW": 409,
    # compliance / safety
    "ERR_OVERHEAD_RATE_NOT_CERTIFIED": 409,
    "ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING": 422,
    "ERR_EXPENSE_UNALLOWABLE": 422,
    # temporal
    "ERR_PERIOD_LOCKED": 422,
    "ERR_RATE_PERIOD_OVERLAP": 409,
    "ERR_MULTIPLIER_BACKDATED": 409,
    # work breakdown structure
    "ERR_PHASE_NOT_LEAF": 422,
    "ERR_WBS_CYCLE": 422,
    "ERR_WBS_CODE_DUPLICATE": 409,
    "ERR_WBS_FEE_ROLLUP_MISMATCH": 422,
    "ERR_PHASE_HAS_OPEN_CHARGES": 409,
    "ERR_CERTIFICATION_YEAR_DUPLICATE": 409,
    # rate resolution
    "ERR_NO_EFFECTIVE_LABOR_RATE": 422,
    "ERR_NO_EFFECTIVE_MULTIPLIER": 422,
    # consultant / pay-when-paid
    "ERR_PAY_WHEN_PAID_NOT_SATISFIED": 409,
    "ERR_CONSULTANT_BUDGET_OVERCOMMIT": 409,
    "ERR_SUBCONTRACT_COMMITMENT_EXCEEDED": 422,
    # invoicing / write-off fiscal checks
    "ERR_BILLING_EXCEEDS_EARNED": 422,
    "ERR_NOTHING_TO_INVOICE": 422,
    "ERR_BACKUP_DOCUMENTATION_MISSING": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_WRITE_OFF_AMOUNT_NOT_ALLOCATABLE": 422,
    "ERR_WRITE_OFF_AMOUNT_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
