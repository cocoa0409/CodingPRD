"""Error catalog (PRD §5 / SCAFFOLD §1.6): every error_id with its HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


CATALOG = {
    # Authentication & authorization
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_FORBIDDEN_RESOURCE_ACCESS": 403,
    # Not found (path or body references)
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_SHIPPER_NOT_FOUND": 404,
    "ERR_TARIFF_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_PROCEEDING_NOT_FOUND": 404,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVOICE_MISSING_REQUIRED_ELEMENT": 400,
    "ERR_INVALID_INVOICE_DATES": 400,
    "ERR_REDUCED_AMOUNT_NOT_LOWER": 400,
    "ERR_JUSTIFICATION_REQUIRED": 400,
    # Concurrency
    "ERR_STALE_VERSION": 412,
    # State preconditions
    "ERR_CARRIER_NOT_ACTIVE": 409,
    "ERR_TARIFF_NOT_IN_DRAFT": 409,
    "ERR_TARIFF_NOT_PUBLISHED": 409,
    "ERR_CONTRACT_NOT_EFFECTIVE": 409,
    "ERR_LICENSE_NOT_ACTIVE": 409,
    "ERR_INVOICE_NOT_DISPUTABLE": 409,
    "ERR_INVOICE_NOT_PAYABLE": 409,
    "ERR_DISPUTE_NOT_PENDING": 409,
    "ERR_COMPLAINT_NOT_DOCKETED": 409,
    "ERR_COMPLAINT_NOT_ADJUDICATING": 409,
    "ERR_APPEAL_NOT_ALLOWED": 409,
    "ERR_PROCEEDING_NOT_NOTICE_ISSUED": 409,
    "ERR_AGREEMENT_NOT_AWAITING_REVIEW": 409,
    "ERR_INVOICE_NOT_ACTIONABLE": 409,
    # Temporal windows
    "ERR_EFFECTIVE_DATE_NOTICE_SHORT": 422,
    "ERR_PUBLISH_WINDOW_NOT_REACHED": 422,
    "ERR_LATE_SERVICE_CONTRACT_FILING": 422,
    "ERR_LATE_INVOICE_ISSUANCE": 422,
    "ERR_COMPLAINT_FILING_WINDOW_EXPIRED": 422,
    "ERR_APPEAL_WINDOW_EXPIRED": 422,
    "ERR_WAITING_PERIOD_NOT_ELAPSED": 422,
    # Referential consistency
    "ERR_TARIFF_CARRIER_MISMATCH": 422,
    "ERR_BILLED_PARTY_NOT_CONTRACT_PARTY": 422,
    "ERR_NOT_INVOICE_PARTY": 422,
    "ERR_RESPONDENT_NOT_INVOICE_CARRIER": 422,
    "ERR_LICENSE_TYPE_MISMATCH": 422,
    "ERR_INVALID_AGREEMENT_MEMBERSHIP": 422,
    "ERR_MEMBER_SET_MISMATCH": 422,
    # Constraint / uniqueness / capacity
    "ERR_EMPTY_SUBJECT_SET": 422,
    "ERR_OMBUDS_ROUND_LIMIT_EXCEEDED": 409,
    "ERR_MONITORING_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_CONGESTION_REPORT": 409,
    "ERR_DUPLICATE_BOND_REF": 409,
    "ERR_PORT_CAPACITY_EXCEEDED": 409,
    # Fiscal
    "ERR_BOND_COVERAGE_EXCEEDED": 402,
    "ERR_BOND_REVERSAL_EXCEEDED": 402,
    # Regulatory safeguards
    "ERR_ADJUDICATOR_CONFLICT": 403,
    "ERR_COMPETITIVE_CONCERN_UNRESOLVED": 409,
}

# Module-level constants so raise sites reference one definition.
for _eid in CATALOG:
    globals()[_eid] = _eid


def fail(error_id, message):
    if error_id not in CATALOG:
        raise AssertionError("unknown error_id: %s" % error_id)
    raise ApiError(error_id, CATALOG[error_id], message)
