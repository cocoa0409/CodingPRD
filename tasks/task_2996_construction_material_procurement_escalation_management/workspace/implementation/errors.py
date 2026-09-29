"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6)."""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SUPPLIER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # shape
    "ERR_INVALID_REQUEST": 422,
    # existence
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    # concurrency
    "ERR_STALE_PROJECT_VERSION": 412,
    # state
    "ERR_QUOTE_NOT_OPEN": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_INVALID_POSTURE_TRANSITION": 409,
    "ERR_STORAGE_STEP_REQUIRED": 409,
    "ERR_CLOCK_REWIND": 422,
    "ERR_SUPPLIER_NOT_ACTIVE": 409,
    "ERR_ESCALATION_NOT_EXECUTED": 409,
    "ERR_AGREEMENT_NOT_ATTACHABLE": 409,
    "ERR_AGREEMENT_QUOTE_MISMATCH": 422,
    "ERR_INDEX_CODE_MISMATCH": 422,
    "ERR_INDEX_READING_MISSING": 409,
    "ERR_STORAGE_NOT_DOCUMENTED": 409,
    # safety / compliance
    "ERR_INSURANCE_COVERAGE_INSUFFICIENT": 422,
    "ERR_SUPPLIER_EXPOSURE_TOO_HIGH": 409,
    "ERR_SUBSTITUTE_SUPPLIER_EXPOSED": 409,
    # temporal / constraint
    "ERR_STORAGE_WINDOW_INVALID": 422,
    "ERR_PRICE_HOLD_OVERLAP": 409,
    "ERR_WAREHOUSE_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_PO_NUMBER": 409,
    "ERR_DUPLICATE_SCOPE_CODE": 409,
    "ERR_DUPLICATE_INDEX_READING": 409,
    "ERR_PACKAGE_ALREADY_COMMITTED": 409,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 409,
    "ERR_COUNTER_NOT_RESPONSIVE": 422,
    "ERR_ENGINEER_CONDITIONS_REQUIRED": 422,
    # fiscal
    "ERR_BUYOUT_OVERRUN_EXCEEDED": 422,
    "ERR_CONTINGENCY_EXCEEDED": 409,
    "ERR_STORED_VALUE_EXCEEDS_COMMITMENT": 422,
    "ERR_CLAIM_NOT_SUBSTANTIATED": 409,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role must be present and name a declared role.",
    "ERR_UNAUTHORIZED": "The declared role is not authorized for this endpoint.",
    "ERR_SUPPLIER_SCOPE_VIOLATION": "A SupplierRep may only act for its own supplier.",
    "ERR_SEGREGATION_OF_DUTIES": "The preparer of a change order may not submit it.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_PROJECT_NOT_FOUND": "The referenced project does not exist.",
    "ERR_PACKAGE_NOT_FOUND": "The referenced material package does not exist.",
    "ERR_SUPPLIER_NOT_FOUND": "The referenced supplier does not exist.",
    "ERR_QUOTE_NOT_FOUND": "The referenced quote does not exist.",
    "ERR_AGREEMENT_NOT_FOUND": "The referenced escalation agreement does not exist.",
    "ERR_COMMITMENT_NOT_FOUND": "The referenced purchase commitment does not exist.",
    "ERR_RECORD_NOT_FOUND": "The referenced record does not exist.",
    "ERR_STALE_PROJECT_VERSION": "expected_project_version does not match the project's current version.",
    "ERR_QUOTE_NOT_OPEN": "The quote is not OPEN.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not declared from the current state.",
    "ERR_INVALID_POSTURE_TRANSITION": "to_posture is not a declared edge from the current delivery posture.",
    "ERR_STORAGE_STEP_REQUIRED": "An early-buyout commitment may not skip off-site storage.",
    "ERR_CLOCK_REWIND": "The logical clock may not be rewound.",
    "ERR_SUPPLIER_NOT_ACTIVE": "The quote's supplier is not ACTIVE.",
    "ERR_ESCALATION_NOT_EXECUTED": "The attached escalation agreement is not EXECUTED.",
    "ERR_AGREEMENT_NOT_ATTACHABLE": "The escalation agreement may not be attached in its current status.",
    "ERR_AGREEMENT_QUOTE_MISMATCH": "The escalation agreement belongs to a different quote.",
    "ERR_INDEX_CODE_MISMATCH": "index_code does not match the package's commodity_index_code.",
    "ERR_INDEX_READING_MISSING": "No published index reading exists for the required index and period.",
    "ERR_STORAGE_NOT_DOCUMENTED": "No ACTIVE, fully documented storage arrangement is available.",
    "ERR_INSURANCE_COVERAGE_INSUFFICIENT": "coverage_amount is below the arrangement's stored_value.",
    "ERR_SUPPLIER_EXPOSURE_TOO_HIGH": "The supplier's snapshot exposure band is HIGH.",
    "ERR_SUBSTITUTE_SUPPLIER_EXPOSED": "The proposed supplier's forward exposure band is HIGH.",
    "ERR_STORAGE_WINDOW_INVALID": "The storage occupancy window is invalid.",
    "ERR_PRICE_HOLD_OVERLAP": "The price-hold interval overlaps a live quote for the same package and supplier.",
    "ERR_WAREHOUSE_WINDOW_CONFLICT": "The buffered occupancy interval collides with another arrangement in the same warehouse.",
    "ERR_DUPLICATE_PO_NUMBER": "po_number already exists.",
    "ERR_DUPLICATE_SCOPE_CODE": "scope_code already exists on that project.",
    "ERR_DUPLICATE_INDEX_READING": "(index_code, period) already published.",
    "ERR_PACKAGE_ALREADY_COMMITTED": "The package already carries a PENDING or COMMITTED commitment.",
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": "The negotiation rounds are exhausted.",
    "ERR_COUNTER_NOT_RESPONSIVE": "The counter moves no term in the supplier's favour.",
    "ERR_ENGINEER_CONDITIONS_REQUIRED": "engineer_conditions is required for APPROVED_AS_NOTED.",
    "ERR_BUYOUT_OVERRUN_EXCEEDED": "base_price exceeds the permitted buyout overrun over the package estimate.",
    "ERR_CONTINGENCY_EXCEEDED": "The provisional escalation exceeds the project's remaining escalation contingency.",
    "ERR_STORED_VALUE_EXCEEDS_COMMITMENT": "stored_value exceeds the commitment's committed_base_cost.",
    "ERR_CLAIM_NOT_SUBSTANTIATED": "The commitment's escalation is not FINAL and greater than zero.",
}


class ApiError(Exception):
    """Domain error carrying a PRD error_id and its declared HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)
