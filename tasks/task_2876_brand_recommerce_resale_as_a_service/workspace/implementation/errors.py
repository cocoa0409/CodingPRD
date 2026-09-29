"""Error catalogue for the Brand Recommerce & Resale platform.

Every identifier and HTTP status below is taken verbatim from PRD.md section 5
(Error Code Catalogue).
"""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_OVERRIDE_ROLE_REQUIRED": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_GRADE_POLICY_NOT_FOUND": 404,
    "ERR_CREDIT_POLICY_NOT_FOUND": 404,
    "ERR_STORE_LOCATION_NOT_FOUND": 404,
    "ERR_REFURB_BAY_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_TRADE_IN_NOT_FOUND": 404,
    "ERR_CREDIT_GRANT_NOT_FOUND": 404,
    "ERR_RESALE_UNIT_NOT_FOUND": 404,
    "ERR_REFURB_ORDER_NOT_FOUND": 404,
    "ERR_MARKDOWN_CAMPAIGN_NOT_FOUND": 404,
    "ERR_RESALE_ORDER_NOT_FOUND": 404,
    "ERR_DIVERSION_REPORT_NOT_FOUND": 404,
    "ERR_TRADE_IN_NOT_RECEIVABLE": 409,
    "ERR_TRADE_IN_NOT_AUTHENTICATABLE": 409,
    "ERR_TRADE_IN_NOT_APPEALABLE": 409,
    "ERR_TRADE_IN_NOT_DISPOSITIONABLE": 409,
    "ERR_INTAKE_WINDOW_EXPIRED": 409,
    "ERR_APPEAL_LIMIT_EXCEEDED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_COUNTERFEIT_NOT_ACCEPTABLE": 409,
    "ERR_CUSTOMER_SUSPENDED": 409,
    "ERR_STORE_LOCATION_CLOSED": 409,
    "ERR_BAY_OUT_OF_SERVICE": 409,
    "ERR_CHANNEL_NOT_ACTIVE": 409,
    "ERR_GRADE_POLICY_MISSING": 409,
    "ERR_CREDIT_POLICY_MISSING": 409,
    "ERR_UNIT_NOT_SCHEDULABLE": 409,
    "ERR_BAY_STORE_MISMATCH": 409,
    "ERR_BAY_WINDOW_CONFLICT": 409,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_REFURB_ORDER_NOT_STARTABLE": 409,
    "ERR_REFURB_ORDER_NOT_LOGGABLE": 409,
    "ERR_REFURB_ORDER_NOT_QC_SUBMITTABLE": 409,
    "ERR_REFURB_ORDER_NOT_QC_DECIDABLE": 409,
    "ERR_REWORK_LIMIT_EXCEEDED": 409,
    "ERR_REFURB_NOT_VIABLE": 409,
    "ERR_UNIT_NOT_READY_FOR_LISTING": 409,
    "ERR_ASSORTMENT_NOT_PERMITTED": 409,
    "ERR_MARGIN_FLOOR_ABOVE_CHANNEL_CEILING": 409,
    "ERR_CAMPAIGN_CATEGORY_OVERLAP": 409,
    "ERR_CAMPAIGN_CAPACITY_EXCEEDED": 409,
    "ERR_CAMPAIGN_NOT_RUNNABLE": 409,
    "ERR_UNIT_NOT_LISTED": 409,
    "ERR_STALE_CUSTOMER_VERSION": 412,
    "ERR_CREDIT_NOT_REDEEMABLE_HERE": 409,
    "ERR_REDEMPTION_CAP_EXCEEDED": 422,
    "ERR_INSUFFICIENT_CREDIT": 422,
    "ERR_MIN_CASH_REMAINDER": 422,
    "ERR_ORDER_NOT_FULFILLABLE": 409,
    "ERR_ORDER_NOT_RETURN_REQUESTABLE": 409,
    "ERR_RETURN_WINDOW_CLOSED": 409,
    "ERR_WARRANTY_EXPIRED": 409,
    "ERR_ORDER_RETURN_NOT_SETTLEABLE": 409,
    "ERR_NO_REPLACEMENT_UNIT": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_REPORT_ALREADY_PUBLISHED": 409,
    # Fallbacks that never appear in the catalogue but keep the envelope shape
    # for framework-level rejections (unknown route, unsupported method).
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-ID header is missing, empty or whitespace-only.",
    "ERR_ROLE_NOT_PERMITTED": "The X-User-Role is not permitted on this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting customer does not own the addressed resource.",
    "ERR_OVERRIDE_ROLE_REQUIRED": "Only a ProgramAdmin may supply a viability override reason.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_INVALID_TIME_WINDOW": "The supplied time window is invalid.",
}


class ApiError(Exception):
    """A rejection carrying one catalogue error identifier."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


NOT_FOUND_FOR = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "grade_policies": "ERR_GRADE_POLICY_NOT_FOUND",
    "credit_policies": "ERR_CREDIT_POLICY_NOT_FOUND",
    "store_locations": "ERR_STORE_LOCATION_NOT_FOUND",
    "refurb_bays": "ERR_REFURB_BAY_NOT_FOUND",
    "channels": "ERR_CHANNEL_NOT_FOUND",
    "trade_ins": "ERR_TRADE_IN_NOT_FOUND",
    "credit_grants": "ERR_CREDIT_GRANT_NOT_FOUND",
    "resale_units": "ERR_RESALE_UNIT_NOT_FOUND",
    "refurb_orders": "ERR_REFURB_ORDER_NOT_FOUND",
    "markdown_campaigns": "ERR_MARKDOWN_CAMPAIGN_NOT_FOUND",
    "resale_orders": "ERR_RESALE_ORDER_NOT_FOUND",
    "diversion_reports": "ERR_DIVERSION_REPORT_NOT_FOUND",
}
