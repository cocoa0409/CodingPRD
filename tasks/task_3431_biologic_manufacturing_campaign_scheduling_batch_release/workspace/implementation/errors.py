"""Error catalog and ApiError exception.

Every error_id from the PRD section 5 catalogue (52 entries) with its HTTP
status code. ApiError carries the id/status/message; app.py renders it into
the standard error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_CATALOG[error_id]
        self.message = message or error_id
        super().__init__(self.message)


ERROR_CATALOG = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    # Existence
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_TRAIN_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_SEED_STAGE_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_DEVIATION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_MATERIAL_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_COMPARABILITY_STUDY_NOT_FOUND": 404,
    # Input validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_SPEC_BOUNDS": 400,
    "ERR_UNSUPPORTED_ACTION": 400,
    # Concurrency
    "ERR_STALE_BATCH_VERSION": 412,
    # State machine guards
    "ERR_INVALID_CAMPAIGN_STATE": 409,
    "ERR_INVALID_BATCH_STATE": 409,
    "ERR_TEST_NOT_RECORDED": 409,
    "ERR_DEVIATION_NOT_OPEN": 409,
    "ERR_INVALID_SHIPMENT_STATE": 409,
    "ERR_INVALID_STUDY_STATE": 409,
    "ERR_INVALID_INSPECTION_STATE": 409,
    "ERR_INVALID_SEED_STAGE_STATE": 409,
    # Safety / compliance
    "ERR_FOUR_EYES_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SITE_RELEASE_FROZEN": 409,
    "ERR_INSUFFICIENT_REMAINING_SHELF_LIFE": 409,
    "ERR_SINGLE_SOURCE_MATERIAL_BLOCKED": 409,
    # Referential
    "ERR_COMPARABILITY_NOT_ESTABLISHED": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_BATCH_ALREADY_EXISTS": 409,
    "ERR_SUPERSEDE_TARGET_NOT_INVALIDATED": 409,
    "ERR_STUDY_DATA_MISSING": 409,
    # Temporal
    "ERR_TRAIN_WINDOW_CONFLICT": 409,
    "ERR_CAMPAIGN_START_TOO_EARLY": 409,
    "ERR_SEED_TRANSFER_WINDOW_EXPIRED": 409,
    "ERR_SEED_INOCULATION_WINDOW_EXPIRED": 409,
    "ERR_BATCH_EXPIRED": 409,
    # Constraint
    "ERR_TRAIN_PRODUCT_INCOMPATIBLE": 409,
    "ERR_MARKET_SCOPE_VIOLATION": 422,
    "ERR_TEST_PHASE_MISMATCH": 409,
    "ERR_UNRESOLVED_TESTS": 409,
    "ERR_NO_SEED_STAGES_DEFINED": 409,
    "ERR_SEED_STAGES_INCOMPLETE": 409,
    "ERR_SEED_STAGE_ORDER_VIOLATION": 409,
    "ERR_MATERIAL_SHORTAGE": 409,
    "ERR_SHIPMENT_QUANTITY_EXCEEDS_AVAILABLE": 409,
    # Fiscal / capacity
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_COLD_STORAGE_CAPACITY_EXCEEDED": 409,
}


def err(error_id, message=None):
    """Raise an ApiError for the given catalog id."""
    raise ApiError(error_id, message)
