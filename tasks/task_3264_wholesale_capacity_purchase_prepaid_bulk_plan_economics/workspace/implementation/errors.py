"""Error catalogue and the ApiError exception type.

Every error id here is read verbatim from SCAFFOLD.yaml Table 7 / PRD section 5.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SUBSCRIBER_NOT_FOUND": 404,
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_ACTIVATION_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_SIM_INVENTORY_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TERM_ALREADY_TERMINAL": 409,
    "ERR_ACTIVATION_ALREADY_TERMINAL": 409,
    "ERR_PORT_ALREADY_TERMINAL": 409,
    "ERR_CYCLE_ALREADY_ROLLED": 409,
    "ERR_AGREEMENT_SUSPENDED": 409,
    "ERR_AGREEMENT_CLOSED": 409,
    "ERR_PLAN_RETIRED": 409,
    "ERR_INSUFFICIENT_AGREEMENT_CAPACITY": 409,
    "ERR_DUPLICATE_ACTIVE_TERM": 409,
    "ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE": 422,
    "ERR_PARTNER_SUSPENDED": 422,
    "ERR_NO_ACTIVATABLE_SIM_MEDIA": 422,
    "ERR_SIM_INVENTORY_DEPLETED": 409,
    "ERR_SUBSCRIBER_NOT_ACTIVE": 409,
    "ERR_TERM_NOT_ACTIVE": 409,
    "ERR_MSISDN_ALREADY_IN_FLIGHT": 409,
    "ERR_MSISDN_MISMATCH": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PLAN_TERM": 422,
    "ERR_INVALID_ADDON_WINDOW": 422,
    "ERR_SELF_SERVICE_TOO_EARLY": 409,
    "ERR_SUPPORT_BUDGET_EXCEEDED": 402,
    "ERR_SLA_NOT_DUE": 409,
    "ERR_RETAIL_CHANNEL_MISMATCH": 422,
    "ERR_PORT_IN_FLIGHT": 409,
    "ERR_TERM_ALREADY_STARTED": 409,
    "ERR_ADDON_WINDOW_OVERLAP": 409,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    """Carries an error id, a human message and the catalogue HTTP status."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").capitalize()
        super().__init__(self.message)