"""Error catalogue (PRD section 5) and the exception used to raise them."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


HTTP_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_DEPARTMENT_SCOPE_VIOLATION": 403,
    # existence
    "ERR_DEPARTMENT_NOT_FOUND": 404,
    "ERR_BAKE_DAY_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_INGREDIENT_NOT_FOUND": 404,
    "ERR_OVEN_NOT_FOUND": 404,
    "ERR_PRODUCTION_RUN_NOT_FOUND": 404,
    "ERR_PICKUP_SLOT_NOT_FOUND": 404,
    "ERR_CAKE_ORDER_NOT_FOUND": 404,
    "ERR_INGREDIENT_ORDER_NOT_FOUND": 404,
    "ERR_WASTE_RECORD_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # optimistic concurrency
    "ERR_STALE_BAKE_DAY_VERSION": 412,
    "ERR_STALE_DEPARTMENT_VERSION": 412,
    # state
    "ERR_BAKE_DAY_CLOSED": 409,
    "ERR_BAKE_DAY_PLAN_LOCKED": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_PROOF_REQUIRED": 409,
    "ERR_PROOF_NOT_REQUIRED": 409,
    "ERR_RUN_NOT_COMPLETED": 409,
    "ERR_WASTE_RECORD_ALREADY_VOIDED": 409,
    "ERR_INVALID_CAKE_ORDER_STATE": 409,
    "ERR_INVALID_INGREDIENT_ORDER_STATE": 409,
    "ERR_OVEN_UNAVAILABLE": 409,
    "ERR_PICKUP_SLOT_CLOSED": 409,
    # safety
    "ERR_ALLERGEN_SEGREGATION_VIOLATION": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PRODUCT_EXPIRED": 422,
    # temporal
    "ERR_MARKDOWN_WINDOW_NOT_OPEN": 422,
    "ERR_DECORATION_LEAD_TIME_MISSED": 422,
    "ERR_OVEN_SHIFT_WINDOW_VIOLATION": 422,
    "ERR_OVEN_SLOT_CONFLICT": 409,
    "ERR_PICKUP_SLOT_OVERLAP": 409,
    # constraint
    "ERR_DECK_INDEX_OUT_OF_RANGE": 422,
    "ERR_DUPLICATE_FORECAST_LINE": 409,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_REVISION_LIMIT_REACHED": 422,
    "ERR_PICKUP_SLOT_CAPACITY_EXCEEDED": 422,
    "ERR_WASTE_EXCEEDS_ON_SHELF": 422,
    "ERR_EMPTY_PRODUCTION_PLAN": 422,
    # referential
    "ERR_INGREDIENT_NOT_IN_DEPARTMENT": 422,
    "ERR_NOT_CUSTOM_CAKE_BASE": 422,
    "ERR_OVEN_METHOD_MISMATCH": 422,
    # fiscal / capacity
    "ERR_MARKDOWN_AUTHORIZATION_REQUIRED": 403,
    "ERR_OVEN_RACK_CAPACITY_EXCEEDED": 422,
    "ERR_LABOR_BUDGET_EXCEEDED": 422,
    "ERR_SHELF_LIFE_OVERSTOCK": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_DEPARTMENT_SCOPE_VIOLATION": "The acting department manager does not own the target resource.",
    "ERR_DEPARTMENT_NOT_FOUND": "No bakery department matches the supplied identifier.",
    "ERR_BAKE_DAY_NOT_FOUND": "No bake day matches the supplied identifier.",
    "ERR_PRODUCT_NOT_FOUND": "No product matches the supplied identifier.",
    "ERR_INGREDIENT_NOT_FOUND": "No ingredient matches the supplied identifier.",
    "ERR_OVEN_NOT_FOUND": "No oven matches the supplied identifier.",
    "ERR_PRODUCTION_RUN_NOT_FOUND": "No production run matches the supplied identifier.",
    "ERR_PICKUP_SLOT_NOT_FOUND": "No pickup slot matches the supplied identifier.",
    "ERR_CAKE_ORDER_NOT_FOUND": "No custom cake order matches the supplied identifier.",
    "ERR_INGREDIENT_ORDER_NOT_FOUND": "No ingredient order matches the supplied identifier.",
    "ERR_WASTE_RECORD_NOT_FOUND": "No waste record matches the supplied identifier.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_STALE_BAKE_DAY_VERSION": "expected_bake_day_version does not match the bake day's current version.",
    "ERR_STALE_DEPARTMENT_VERSION": "expected_department_version does not match the department's current version.",
    "ERR_BAKE_DAY_CLOSED": "The bake day is closed.",
    "ERR_BAKE_DAY_PLAN_LOCKED": "The bake day's plan is locked.",
    "ERR_INVALID_RUN_STATE": "The requested transition is not permitted from the current state.",
    "ERR_PROOF_REQUIRED": "The run must pass through proofing before it may be baked.",
    "ERR_PROOF_NOT_REQUIRED": "This product does not require a proof stage.",
    "ERR_RUN_NOT_COMPLETED": "The production run has not been completed.",
    "ERR_WASTE_RECORD_ALREADY_VOIDED": "The waste record has already been voided.",
    "ERR_INVALID_CAKE_ORDER_STATE": "The requested transition is not permitted from the order's current status.",
    "ERR_INVALID_INGREDIENT_ORDER_STATE": "The requested transition is not permitted from the order's current status.",
    "ERR_OVEN_UNAVAILABLE": "The oven is not available.",
    "ERR_PICKUP_SLOT_CLOSED": "The pickup slot is closed.",
    "ERR_ALLERGEN_SEGREGATION_VIOLATION": "Allergen segregation forbids this pairing.",
    "ERR_SEGREGATION_OF_DUTIES": "The operator who executed the run may not attest its waste.",
    "ERR_PRODUCT_EXPIRED": "The product has already expired.",
    "ERR_MARKDOWN_WINDOW_NOT_OPEN": "The markdown window has not opened yet.",
    "ERR_DECORATION_LEAD_TIME_MISSED": "The decoration lead time has been missed.",
    "ERR_OVEN_SHIFT_WINDOW_VIOLATION": "The run does not fit inside the day's oven shift window.",
    "ERR_OVEN_SLOT_CONFLICT": "The buffered bake interval collides with another run on this deck.",
    "ERR_PICKUP_SLOT_OVERLAP": "The pickup window overlaps an existing window on this bake day.",
    "ERR_DECK_INDEX_OUT_OF_RANGE": "deck_index is outside the oven's deck range.",
    "ERR_DUPLICATE_FORECAST_LINE": "A forecast line already exists for this product and daypart.",
    "ERR_DUPLICATE_SKU": "The value already exists inside the department.",
    "ERR_REVISION_LIMIT_REACHED": "The order has already used its two revisions.",
    "ERR_PICKUP_SLOT_CAPACITY_EXCEEDED": "The pickup slot's decorator capacity would be exceeded.",
    "ERR_WASTE_EXCEEDS_ON_SHELF": "The attested waste exceeds the run's remaining shelf units.",
    "ERR_EMPTY_PRODUCTION_PLAN": "The production plan is empty.",
    "ERR_INGREDIENT_NOT_IN_DEPARTMENT": "The referenced resource belongs to a different department or bake day.",
    "ERR_NOT_CUSTOM_CAKE_BASE": "The referenced product is not flagged as a custom cake base.",
    "ERR_OVEN_METHOD_MISMATCH": "Oven assignment does not match the product's production method.",
    "ERR_MARKDOWN_AUTHORIZATION_REQUIRED": "Markdown on this bake day is restricted to a department manager.",
    "ERR_OVEN_RACK_CAPACITY_EXCEEDED": "rack_count exceeds the oven's per-deck rack capacity.",
    "ERR_LABOR_BUDGET_EXCEEDED": "The run would push the day's planned labor past its budget.",
    "ERR_SHELF_LIFE_OVERSTOCK": "The rounded order quantity exceeds the ingredient's shelf-life cap.",
}
