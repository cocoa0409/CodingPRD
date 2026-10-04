"""Error catalog (SCAFFOLD section 1.6 / PRD section 5) and the exception type.

The two tables below transcribe the scaffold's error_id -> http mapping and
provide a human-readable message for each identifier.
"""


class ApiError(Exception):
    """A refusal carrying an error_id, an HTTP status and a message."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    # auth + ownership
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RECEIVING_FRANCHISEE": 403,
    "ERR_NOT_PERFORMING_FRANCHISEE": 403,
    "ERR_NOT_REFERRAL_PARTY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_AUDITOR_REQUIRED": 400,
    "ERR_APPROVER_REQUIRED": 400,
    "ERR_INVALID_PERIOD": 400,
    # existence
    "ERR_BRAND_NOT_FOUND": 404,
    "ERR_FRANCHISEE_NOT_FOUND": 404,
    "ERR_TERRITORY_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_LEAD_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_VERIFICATION_AUDIT_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_TRANSFER_APPLICATION_NOT_FOUND": 404,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_REFERRAL_DISPUTED": 409,
    "ERR_STALE_VERSION": 412,
    # trade qualification
    "ERR_CERTIFICATION_TOO_LOW": 422,
    "ERR_ACCOUNT_BRAND_NOT_CONTRACTED": 422,
    "ERR_SHARED_SERVICES_REQUIRED": 422,
    # cross-entity linkage
    "ERR_AGREEMENT_REQUIRED_FOR_AWARD": 409,
    "ERR_AGREEMENT_TERRITORY_NOT_AWARDED": 409,
    "ERR_OPEN_REMEDIATION": 409,
    "ERR_STANDARDS_DEFAULTED": 409,
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_REMEDIATION_FAILED": 422,
    # uniqueness / set / threshold
    "ERR_TERRITORY_POSTAL_OVERLAP": 409,
    "ERR_DUPLICATE_BRAND_CODE": 409,
    "ERR_DUPLICATE_TERRITORY_CODE": 409,
    "ERR_DUPLICATE_AGREEMENT_NUMBER": 409,
    "ERR_DUPLICATE_REFERRAL_CODE": 409,
    "ERR_TERRITORY_ALREADY_AGREED": 409,
    "ERR_LEAD_BRAND_MISMATCH": 409,
    "ERR_TARGET_TERRITORY_INVALID": 409,
    "ERR_TRANSFER_ALREADY_PENDING": 409,
    "ERR_EXPANSION_THRESHOLD_NOT_MET": 409,
    "ERR_LEAD_POOL_EMPTY": 409,
    # temporal windows
    "ERR_SLA_WINDOW_EXCEEDS_PROGRAM": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 409,
    "ERR_AUDIT_CYCLE_EXCEEDED": 409,
    "ERR_REMEDIATION_WINDOW_CLOSED": 409,
    "ERR_HOLD_WINDOW_ACTIVE": 409,
    "ERR_REFERRAL_EXPIRED": 409,
    "ERR_REOPEN_WINDOW_CLOSED": 409,
    "ERR_REMEDIATION_NOT_OVERDUE": 409,
    "ERR_AGREEMENT_NOT_EXPIRABLE": 422,
    "ERR_SLA_NOT_BREACHED": 422,
    # fiscal
    "ERR_HOUSEHOLD_CAP_EXCEEDED": 422,
    "ERR_STATEMENT_PERIOD_OVERLAP": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and X-User-Role must name a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this operation.",
    "ERR_NOT_RECEIVING_FRANCHISEE": "The acting franchisee is not the receiving party of this referral or lead allocation.",
    "ERR_NOT_PERFORMING_FRANCHISEE": "The acting franchisee does not own the performing agreement.",
    "ERR_NOT_REFERRAL_PARTY": "The acting franchisee is neither the originating nor the receiving party of this referral.",
    "ERR_SEGREGATION_OF_DUTIES": "The second operator of this two-step control must differ from the first.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_AUDITOR_REQUIRED": "Conducting an audit requires a non-empty auditor_operator_id.",
    "ERR_APPROVER_REQUIRED": "Approving a transfer application requires a non-empty approval_operator_id.",
    "ERR_INVALID_PERIOD": "The statement period end must be strictly after its start.",
    "ERR_BRAND_NOT_FOUND": "The referenced brand does not exist.",
    "ERR_FRANCHISEE_NOT_FOUND": "The referenced franchisee does not exist.",
    "ERR_TERRITORY_NOT_FOUND": "The referenced territory does not exist.",
    "ERR_AGREEMENT_NOT_FOUND": "The referenced franchise agreement does not exist.",
    "ERR_REFERRAL_NOT_FOUND": "The referenced referral does not exist.",
    "ERR_LEAD_NOT_FOUND": "The referenced lead does not exist.",
    "ERR_ACCOUNT_NOT_FOUND": "The referenced national account does not exist.",
    "ERR_WORK_ORDER_NOT_FOUND": "The referenced work order does not exist.",
    "ERR_AUDIT_NOT_FOUND": "The referenced brand standards audit does not exist.",
    "ERR_VERIFICATION_AUDIT_NOT_FOUND": "verification_audit_id names no audit for the same agreement.",
    "ERR_STATEMENT_NOT_FOUND": "The referenced royalty statement does not exist.",
    "ERR_TRANSFER_APPLICATION_NOT_FOUND": "The referenced transfer application does not exist.",
    "ERR_INVALID_STATE": "The target resource is not in a state from which this transition is declared.",
    "ERR_ALREADY_TERMINAL": "The target resource has already reached a terminal state.",
    "ERR_REFERRAL_DISPUTED": "The referral still carries an open dispute and may not be settled.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the resource's current version.",
    "ERR_CERTIFICATION_TOO_LOW": "The performing agreement's certification level ranks below the brand minimum.",
    "ERR_ACCOUNT_BRAND_NOT_CONTRACTED": "The performing brand is not a member of the program's contracted brands.",
    "ERR_SHARED_SERVICES_REQUIRED": "The receiving franchisee is not enrolled in shared services.",
    "ERR_AGREEMENT_REQUIRED_FOR_AWARD": "No matching franchise agreement exists for this territory.",
    "ERR_AGREEMENT_TERRITORY_NOT_AWARDED": "The bound territory has not been awarded.",
    "ERR_OPEN_REMEDIATION": "The agreement carries an open remediation.",
    "ERR_STANDARDS_DEFAULTED": "The agreement's standards status is DEFAULT.",
    "ERR_ACCOUNT_SUSPENDED": "The national account is not ACTIVE.",
    "ERR_REMEDIATION_FAILED": "The re-verification audit scored below the passing threshold.",
    "ERR_TERRITORY_POSTAL_OVERLAP": "A postal code would belong to two non-reclaimed territories of the same brand.",
    "ERR_DUPLICATE_BRAND_CODE": "brand_code is already taken.",
    "ERR_DUPLICATE_TERRITORY_CODE": "territory_code is already taken.",
    "ERR_DUPLICATE_AGREEMENT_NUMBER": "agreement_number is already taken.",
    "ERR_DUPLICATE_REFERRAL_CODE": "referral_code is already taken.",
    "ERR_TERRITORY_ALREADY_AGREED": "Another agreement for this territory is already live.",
    "ERR_LEAD_BRAND_MISMATCH": "The receiving agreement's brand does not match the lead's brand.",
    "ERR_TARGET_TERRITORY_INVALID": "A reallocation target id is not a valid placeholder territory.",
    "ERR_TRANSFER_ALREADY_PENDING": "Another transfer application for this agreement is still open.",
    "ERR_EXPANSION_THRESHOLD_NOT_MET": "household_count is below the expansion-rights threshold.",
    "ERR_LEAD_POOL_EMPTY": "No eligible agreement is available to receive this lead.",
    "ERR_SLA_WINDOW_EXCEEDS_PROGRAM": "The work order's service level window exceeds the program's.",
    "ERR_RENEWAL_WINDOW_CLOSED": "The agreement is not yet inside its renewal window.",
    "ERR_AUDIT_CYCLE_EXCEEDED": "The audit was conducted at or after the agreement's audit due instant.",
    "ERR_REMEDIATION_WINDOW_CLOSED": "The verification audit was conducted after the remediation due instant.",
    "ERR_HOLD_WINDOW_ACTIVE": "The allocation hold window has not yet elapsed.",
    "ERR_REFERRAL_EXPIRED": "The referral's expiry instant has been reached.",
    "ERR_REOPEN_WINDOW_CLOSED": "The 24-hour reopen window has closed.",
    "ERR_REMEDIATION_NOT_OVERDUE": "The remediation due instant has not been reached.",
    "ERR_AGREEMENT_NOT_EXPIRABLE": "The logical clock is strictly before the agreement's expiry instant.",
    "ERR_SLA_NOT_BREACHED": "The logical clock is strictly before the work order's SLA due instant.",
    "ERR_HOUSEHOLD_CAP_EXCEEDED": "The award would push the franchisee past the 250000 protected household cap.",
    "ERR_STATEMENT_PERIOD_OVERLAP": "The period overlaps a non-voided statement for the same agreement.",
}