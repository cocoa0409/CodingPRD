"""Error catalogue and the single API exception type (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> HTTP status, transcribed from PRD §5.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_TARIFF_RULE_SET_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_RAIL_CAR_NOT_FOUND": 404,
    "ERR_PLACEMENT_CYCLE_NOT_FOUND": 404,
    "ERR_DEMURRAGE_CHARGE_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_BUNCHING_CLAIM_NOT_FOUND": 404,
    "ERR_DEMURRAGE_DISPUTE_NOT_FOUND": 404,
    "ERR_AVERAGE_AGREEMENT_NOT_FOUND": 404,
    "ERR_REGULATORY_COMPLAINT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_MOVEMENT_STATE": 409,
    "ERR_INVOICE_NOT_DISPUTABLE": 409,
    "ERR_INVOICE_INVALID_STATE": 409,
    "ERR_DISPUTE_INVALID_STATE": 409,
    "ERR_CHARGE_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_COMPLAINT_INVALID_STATE": 409,
    "ERR_TARIFF_INVALID_STATE": 409,
    "ERR_INVOICE_VERSION_STALE": 412,
    "ERR_RAIL_CAR_VERSION_STALE": 412,
    "ERR_FACILITY_EMBARGOED": 409,
    "ERR_FACILITY_NOT_OPEN": 409,
    "ERR_TARIFF_WITHDRAWN": 422,
    "ERR_TARIFF_NOT_PUBLISHED": 422,
    "ERR_TARIFF_SCOPE_MISMATCH": 422,
    "ERR_DISPUTE_SCOPE_MISMATCH": 422,
    "ERR_CHARGE_INVOICE_MISMATCH": 422,
    "ERR_SUPERSEDE_TARGET_INVALID": 422,
    "ERR_CAR_CYCLE_OVERLAP": 409,
    "ERR_FACILITY_SPOT_UNAVAILABLE": 409,
    "ERR_FACILITY_SWITCH_BUFFER": 409,
    "ERR_REFUSAL_LIMIT": 409,
    "ERR_INFO_REQUEST_LIMIT": 409,
    "ERR_APPEAL_LIMIT": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_NON_CHRONOLOGICAL_EVENT": 422,
    "ERR_INVALID_CLUSTER_WINDOW": 422,
    "ERR_CLUSTER_WINDOW_OVERLAP": 409,
    "ERR_DUPLICATE_AGREEMENT_MONTH": 409,
    "ERR_CUSTOMER_CREDIT_HOLD": 402,
    "ERR_INVOICE_NO_CHARGES": 422,
    "ERR_DISPUTE_NO_EVIDENCE": 422,
    "ERR_CLAIM_EXCEEDS_CHARGE": 422,
    "ERR_ALLOWANCE_PCT_MISMATCH": 422,
    "ERR_BUNCHING_CLAIM_NOT_GRANTED": 422,
    "ERR_APPEAL_NOT_EXHAUSTED": 422,
    "ERR_ORDERED_CREDIT_EXCEEDS_CLAIM": 422,
    "ERR_CLAIM_NO_DELIVERIES": 422,
    "ERR_NO_PENDING_NOTIFICATION": 422,
    "ERR_NOTIFICATION_NOT_SENT": 422,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_ROLE_FORBIDDEN": "The acting role is not authorized for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting consignee does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The first-level adjudicator may not act on the appeal round.",
    "ERR_INVALID_REQUEST": "The request body failed schema validation.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer >= 0.",
}


def fail(error_id, message=None):
    """Raise the catalogued error with its fixed HTTP status."""
    raise ApiError(error_id, ERROR_STATUS[error_id], message)
