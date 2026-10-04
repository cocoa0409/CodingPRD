"""Error catalog for the field-kitchen-activation API.

Every error identifier and HTTP status below is taken verbatim from PRD section 5
(Error Code Catalogue) / SCAFFOLD `errors`.
"""

ERROR_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_FIELD_KITCHEN_NOT_FOUND": 404,
    "ERR_PARTNER_KITCHEN_NOT_FOUND": 404,
    "ERR_MEAL_ORDER_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_RUN_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_STOP_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ENTITY_TERMINAL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PARTNER_KITCHEN_NOT_CONTRACTED": 409,
    "ERR_INCIDENT_NOT_ACTIVE": 409,
    "ERR_ORIGIN_KITCHEN_NOT_OPERATIONAL": 409,
    "ERR_RUN_NOT_DELIVERING": 409,
    "ERR_SUPPLIER_NOT_APPROVED": 409,
    "ERR_COOLDOWN_ACTIVE": 409,
    "ERR_BANK_NOT_VERIFIED": 409,
    "ERR_VETTING_SCORE_TOO_LOW": 409,
    "ERR_FOOD_SAFETY_SCORE_TOO_LOW": 422,
    "ERR_KITCHEN_UTILITY_MISSING": 422,
    "ERR_SITE_ACCESS_BLOCKED": 422,
    "ERR_DIETARY_REQUIREMENT_UNMET": 422,
    "ERR_DRIVER_SAFETY_TRAINING_REQUIRED": 422,
    "ERR_KITCHEN_WINDOW_CONFLICT": 409,
    "ERR_KITCHEN_DAILY_RUN_CAP": 409,
    "ERR_RUN_LOAD_EXCEEDS_CAPACITY": 409,
    "ERR_DUPLICATE_STOP_SEQUENCE": 409,
    "ERR_DUPLICATE_STOP_SITE": 409,
    "ERR_FUNDING_CEILING_EXCEEDED": 422,
    "ERR_DISBURSEMENT_EXCEEDS_COMMITMENT": 422,
    "ERR_CROSS_INCIDENT_REFERENCE": 422,
    "ERR_ASSESSMENT_BEFORE_ACTIVATION": 422,
}

ERROR_MESSAGES = {
    "ERR_INVALID_REQUEST": "The request body is malformed or carries a value outside its declared range.",
    "ERR_MISSING_AUTH_HEADER": "The X-User-Role and X-User-ID headers are both required.",
    "ERR_UNAUTHORIZED_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the addressed resource.",
    "ERR_INCIDENT_NOT_FOUND": "The addressed incident does not exist.",
    "ERR_FIELD_KITCHEN_NOT_FOUND": "The addressed field kitchen does not exist.",
    "ERR_PARTNER_KITCHEN_NOT_FOUND": "The addressed partner kitchen does not exist.",
    "ERR_MEAL_ORDER_NOT_FOUND": "The addressed meal order does not exist.",
    "ERR_DISTRIBUTION_RUN_NOT_FOUND": "The addressed distribution run does not exist.",
    "ERR_DISTRIBUTION_STOP_NOT_FOUND": "The addressed distribution stop does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "The addressed resource does not exist.",
    "ERR_REFERENCED_ENTITY_NOT_FOUND": "A foreign-key identifier in the request body does not resolve.",
    "ERR_INVALID_STATE": "The entity is not in a state from which the requested transition is declared.",
    "ERR_ENTITY_TERMINAL": "The entity is in a terminal state and no transition is permitted.",
    "ERR_STALE_VERSION": "The expected parent version does not match the current version.",
    "ERR_PARTNER_KITCHEN_NOT_CONTRACTED": "The partner kitchen is not in contract_status CONTRACTED.",
    "ERR_INCIDENT_NOT_ACTIVE": "The parent incident is not in status ACTIVE.",
    "ERR_ORIGIN_KITCHEN_NOT_OPERATIONAL": "The origin field kitchen is not in site_status OPERATIONAL.",
    "ERR_RUN_NOT_DELIVERING": "The parent distribution run is not in status DELIVERING.",
    "ERR_SUPPLIER_NOT_APPROVED": "The producer is SUSPENDED and cannot take new sourcing orders.",
    "ERR_COOLDOWN_ACTIVE": "The partner kitchen is still inside its cooldown window.",
    "ERR_BANK_NOT_VERIFIED": "The partner kitchen's payout account is not verified.",
    "ERR_VETTING_SCORE_TOO_LOW": "The partner kitchen's vetting score is below 60.",
    "ERR_FOOD_SAFETY_SCORE_TOO_LOW": "The field kitchen's food safety score is below 70.",
    "ERR_KITCHEN_UTILITY_MISSING": "The field kitchen has no power source or no water source.",
    "ERR_SITE_ACCESS_BLOCKED": "The receiving site or assessed catchment is BLOCKED.",
    "ERR_DIETARY_REQUIREMENT_UNMET": "The batch's dietary tags do not cover the incident's dietary requirements.",
    "ERR_DRIVER_SAFETY_TRAINING_REQUIRED": "The volunteer driver has not completed the safety briefing.",
    "ERR_KITCHEN_WINDOW_CONFLICT": "The production window collides with another batch or a post-rejection buffer.",
    "ERR_KITCHEN_DAILY_RUN_CAP": "The origin field kitchen already has 3 runs bucketed to this UTC day.",
    "ERR_RUN_LOAD_EXCEEDS_CAPACITY": "The pending planned meals exceed the run's loaded meals.",
    "ERR_DUPLICATE_STOP_SEQUENCE": "Another stop of this run already uses this stop_sequence.",
    "ERR_DUPLICATE_STOP_SITE": "Another stop of this run already serves this distribution site.",
    "ERR_FUNDING_CEILING_EXCEEDED": "The new commitment would push spend above the incident's funding ceiling.",
    "ERR_DISBURSEMENT_EXCEEDS_COMMITMENT": "The disbursement would exceed the commitment's face value.",
    "ERR_CROSS_INCIDENT_REFERENCE": "A referenced entity belongs to a different activation.",
    "ERR_ASSESSMENT_BEFORE_ACTIVATION": "assessed_at is earlier than the parent incident's created_at.",
}


class ApiError(Exception):
    """Carries the error identifier, HTTP status and human message."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
