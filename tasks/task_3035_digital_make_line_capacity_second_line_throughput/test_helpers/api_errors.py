"""Error catalog for the Digital Makeline Capacity API.

Every error identifier the API contract declares, together with the HTTP status
each one must be returned with. Registering the mapping with the shared
validators lets ``validate_error`` cross-check the status automatically, so a
test only has to name the identifier it expects.
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """Declared error identifiers, grouped by the validation tier that emits them."""

    # Tier 1-2: credentials and role authorization.
    MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
    FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"

    # Tier 3: path-parameter and body-reference existence.
    STORE_NOT_FOUND = "ERR_STORE_NOT_FOUND"
    ORDER_NOT_FOUND = "ERR_ORDER_NOT_FOUND"
    MENU_ITEM_NOT_FOUND = "ERR_MENU_ITEM_NOT_FOUND"
    BATCH_NOT_FOUND = "ERR_BATCH_NOT_FOUND"
    DEPLOYMENT_NOT_FOUND = "ERR_DEPLOYMENT_NOT_FOUND"
    SUPPRESSION_EVENT_NOT_FOUND = "ERR_SUPPRESSION_EVENT_NOT_FOUND"
    CHANNEL_NOT_FOUND = "ERR_CHANNEL_NOT_FOUND"
    INGREDIENT_NOT_FOUND = "ERR_INGREDIENT_NOT_FOUND"

    # Schema and range validation.
    INVALID_REQUEST = "ERR_INVALID_REQUEST"

    # Version pinning.
    STALE_VERSION = "ERR_STALE_VERSION"

    # State legality.
    INVALID_STATE = "ERR_INVALID_STATE"
    ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"

    # Business rules.
    ACCURACY_UNVERIFIED = "ERR_ACCURACY_UNVERIFIED"
    ITEM_SUPPRESSED = "ERR_ITEM_SUPPRESSED"
    INSUFFICIENT_INGREDIENT = "ERR_INSUFFICIENT_INGREDIENT"
    LINE_CAPACITY_EXCEEDED = "ERR_LINE_CAPACITY_EXCEEDED"
    INVALID_DEPLOYMENT = "ERR_INVALID_DEPLOYMENT"
    SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    DAY_NOT_CLOSABLE = "ERR_DAY_NOT_CLOSABLE"
    MARKETPLACE_REFERENCE_INVALID = "ERR_MARKETPLACE_REFERENCE_INVALID"
    WASTE_EXCEEDS_BATCH = "ERR_WASTE_EXCEEDS_BATCH"
    MANUAL_SUPPRESSION_ONLY = "ERR_MANUAL_SUPPRESSION_ONLY"
    WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"

    # Named in the production-start precondition prose.
    DEPLOYMENT_MISSING = "ERR_DEPLOYMENT_MISSING"


# error_id -> HTTP status, exactly as the contract's error table declares it.
HTTP_STATUS_CODES: dict[str, int] = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_MENU_ITEM_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_SUPPRESSION_EVENT_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_INGREDIENT_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ACCURACY_UNVERIFIED": 409,
    "ERR_ITEM_SUPPRESSED": 409,
    "ERR_INSUFFICIENT_INGREDIENT": 409,
    "ERR_LINE_CAPACITY_EXCEEDED": 409,
    "ERR_INVALID_DEPLOYMENT": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DAY_NOT_CLOSABLE": 409,
    "ERR_MARKETPLACE_REFERENCE_INVALID": 422,
    "ERR_WASTE_EXCEEDS_BATCH": 422,
    "ERR_MANUAL_SUPPRESSION_ONLY": 409,
    "ERR_WINDOW_OVERLAP": 409,
    # The production-start precondition names this identifier but the catalogue
    # does not tabulate a status for it; assert the identifier only.
    "ERR_DEPLOYMENT_MISSING": 409,
}

# Hand the mapping to the shared validators once, at import time.
set_error_http_status_map(HTTP_STATUS_CODES)
