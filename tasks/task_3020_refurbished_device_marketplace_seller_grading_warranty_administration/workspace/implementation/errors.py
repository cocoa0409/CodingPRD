"""Error catalog.

Error ids and HTTP statuses are copied verbatim from the PRD's error catalogue
(§5) and the scaffold's `errors` table.  Nothing here invents a code.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


DEFAULT_MESSAGES = {
    "ERR_INVALID_REQUEST": "The request body is missing a required field or carries an out-of-range value.",
    "ERR_UNAUTHENTICATED": "Credentials are required for this endpoint.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not perform this operation.",
    "ERR_SOD_VIOLATION": "The acting operator is barred by the segregation-of-duties matrix.",
    "ERR_RESOURCE_NOT_FOUND": "The requested resource does not exist.",
    "ERR_REFERENCED_ENTITY_NOT_FOUND": "A referenced entity does not exist.",
    "ERR_RESERVATION_NOT_FOUND": "No warranty reservation services this listing.",
    "ERR_DIAGNOSTIC_EVIDENCE_REQUIRED": "A diagnostic evidence digest of exactly 64 lowercase hex characters is required.",
    "ERR_DEVICE_BLOCKLISTED": "The device IMEI appears on a blocklist.",
    "ERR_BATTERY_BELOW_FLOOR": "The battery health is below the applicable floor.",
    "ERR_INSPECTION_BATTERY_UNINSURABLE": "The measured battery health is below the insurable threshold.",
    "ERR_PART_PROVENANCE_UNDOCUMENTED": "The declared part provenance requires a provenance document digest.",
    "ERR_COUNTERFEIT_PRICE_SIGNAL": "The list price is far enough below the model catalogue floor to signal a counterfeit.",
    "ERR_MODEL_NOT_ELIGIBLE": "The model code is not eligible for listing on this marketplace.",
    "ERR_SELLER_NOT_APPROVED": "The seller is not approved to hold or submit listings.",
    "ERR_ROUTED_SELLER_IMMUTABLE": "The routed seller binding may not be reassigned.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition exists.",
    "ERR_CLAIM_TERMINAL": "The claim is terminal and admits no further mutation.",
    "ERR_CLAIM_ALREADY_UPHELD": "The claim has already been upheld and awaits return routing.",
    "ERR_OBLIGATION_EXCEEDS_CAP": "The resolution obligation exceeds the cap for the selected resolution type.",
    "ERR_HUMAN_REVIEW_REQUIRED": "The seller has reached the minimum suspension-trigger threshold and needs human review.",
    "ERR_TRIGGER_CEILING_REACHED": "The seller has reached the suspension-trigger ceiling.",
    "ERR_STALE_VERSION": "The supplied version does not match the current version of the parent resource.",
    "ERR_VERIFICATION_ALREADY_DISCLOSED": "The listing already carries a disclosed mystery-shop verification.",
    "ERR_AUDIT_ALREADY_SCHEDULED": "The seller already has an audit record in progress.",
    "ERR_SELLER_ALREADY_BLOCKLISTED": "The seller is already blocklisted.",
    "ERR_SECTION_BLOCKED_BY_OPEN_CLAIM": "The section cannot close while a claim routed to the seller is approved and unresolved.",
    "ERR_SECTION_TOO_YOUNG": "The section is fewer than 90 calendar days old.",
    "ERR_REVISION_LIMIT_REACHED": "The submission has already used its one free revision round.",
    "ERR_ACCEPTANCE_WINDOW_CLOSED": "The acceptance window has lapsed.",
    "ERR_IMEI_ALREADY_LISTED": "A non-withdrawn listing for this seller already carries this IMEI.",
    "ERR_GRADING_DEFINITION_NOT_ACTIVE": "The grading definition bound at submission is no longer active.",
    "ERR_WITHDRAW_BLOCKED_BY_OPEN_CLAIM": "The listing carries an open claim or a repairing reservation.",
}

# (error_id, http_status)
REGISTRY = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_DIAGNOSTIC_EVIDENCE_REQUIRED": 422,
    "ERR_DEVICE_BLOCKLISTED": 422,
    "ERR_BATTERY_BELOW_FLOOR": 422,
    "ERR_INSPECTION_BATTERY_UNINSURABLE": 422,
    "ERR_PART_PROVENANCE_UNDOCUMENTED": 422,
    "ERR_COUNTERFEIT_PRICE_SIGNAL": 422,
    "ERR_MODEL_NOT_ELIGIBLE": 422,
    "ERR_SELLER_NOT_APPROVED": 422,
    "ERR_ROUTED_SELLER_IMMUTABLE": 422,
    "ERR_OBLIGATION_EXCEEDS_CAP": 422,
    "ERR_HUMAN_REVIEW_REQUIRED": 422,
    "ERR_TRIGGER_CEILING_REACHED": 422,
    "ERR_IMEI_ALREADY_LISTED": 422,
    "ERR_RETURN_SLOT_COLLISION": 409,
    "ERR_VERIFICATION_OVERLAP": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_CLAIM_TERMINAL": 409,
    "ERR_CLAIM_ALREADY_UPHELD": 409,
    "ERR_VERIFICATION_ALREADY_DISCLOSED": 409,
    "ERR_AUDIT_ALREADY_SCHEDULED": 409,
    "ERR_SELLER_ALREADY_BLOCKLISTED": 409,
    "ERR_SECTION_BLOCKED_BY_OPEN_CLAIM": 409,
    "ERR_SECTION_TOO_YOUNG": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_ACCEPTANCE_WINDOW_CLOSED": 409,
    "ERR_GRADING_DEFINITION_NOT_ACTIVE": 409,
    "ERR_WITHDRAW_BLOCKED_BY_OPEN_CLAIM": 409,
    "ERR_STALE_VERSION": 412,
}


def fail(error_id, message=None):
    return ApiError(error_id, REGISTRY[error_id], message)