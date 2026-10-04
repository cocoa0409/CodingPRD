"""Error catalog for the Limited-Assortment Grocery API.

Every error identifier the contract declares, with the HTTP status it must be
returned with. Registering the mapping lets ``validate_error`` cross-check the
status automatically.
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """Declared error identifiers, grouped by the evaluation tier that emits them."""

    # Tier 1: authentication.
    UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    # Tier 2: authorization / ownership.
    FORBIDDEN = "ERR_FORBIDDEN"
    # Tier 3: request shape.
    VALIDATION = "ERR_VALIDATION"
    # Tier 4: existence.
    NOT_FOUND = "ERR_NOT_FOUND"
    # Tier 5: state admissibility.
    INVALID_STATE = "ERR_INVALID_STATE"
    TENDER_NOT_OPEN = "ERR_TENDER_NOT_OPEN"
    PANEL_INCOMPLETE = "ERR_PANEL_INCOMPLETE"
    SHIFT_NOT_OPEN = "ERR_SHIFT_NOT_OPEN"
    # Tier 6: blind-panel integrity.
    BLIND_VIOLATION = "ERR_BLIND_VIOLATION"
    # Tier 7: temporal and window rules.
    WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"
    SALE_WINDOW_CONFLICT = "ERR_SALE_WINDOW_CONFLICT"
    CLEARANCE_GAP_VIOLATION = "ERR_CLEARANCE_GAP_VIOLATION"
    CLAIM_WINDOW_EXPIRED = "ERR_CLAIM_WINDOW_EXPIRED"
    SALE_WINDOW_INACTIVE = "ERR_SALE_WINDOW_INACTIVE"
    # Tier 8: structural business constraints.
    SKU_CAP_EXCEEDED = "ERR_SKU_CAP_EXCEEDED"
    SKU_CAP_BELOW_CURRENT = "ERR_SKU_CAP_BELOW_CURRENT"
    DUPLICATE_SKU = "ERR_DUPLICATE_SKU"
    BARCODE_COUNT_INVALID = "ERR_BARCODE_COUNT_INVALID"
    SHELF_READY_REQUIRED = "ERR_SHELF_READY_REQUIRED"
    BID_DUPLICATE = "ERR_BID_DUPLICATE"
    DUAL_SOURCE_REQUIRED = "ERR_DUAL_SOURCE_REQUIRED"
    SUPPLIER_SUSPENDED = "ERR_SUPPLIER_SUSPENDED"
    ALLOCATION_INCOMPLETE = "ERR_ALLOCATION_INCOMPLETE"
    PRODUCT_NOT_ACTIVE = "ERR_PRODUCT_NOT_ACTIVE"
    FINDS_NO_REPLENISHMENT = "ERR_FINDS_NO_REPLENISHMENT"
    WINDOW_LIMIT_EXCEEDED = "ERR_WINDOW_LIMIT_EXCEEDED"
    CASHIER_ROLE_REQUIRED = "ERR_CASHIER_ROLE_REQUIRED"
    # Optimistic concurrency.
    STALE_VERSION = "ERR_STALE_VERSION"
    # Tier 9: fiscal rules, always last.
    BID_CEILING_EXCEEDED = "ERR_BID_CEILING_EXCEEDED"
    LABOR_BUDGET_EXCEEDED = "ERR_LABOR_BUDGET_EXCEEDED"
    COIN_BALANCE_NEGATIVE = "ERR_COIN_BALANCE_NEGATIVE"
    ALLOCATION_EXHAUSTED = "ERR_ALLOCATION_EXHAUSTED"


HTTP_STATUS_CODES = {
    ApiErrorId.UNAUTHENTICATED: 401,
    ApiErrorId.FORBIDDEN: 403,
    ApiErrorId.VALIDATION: 400,
    ApiErrorId.NOT_FOUND: 404,
    ApiErrorId.INVALID_STATE: 409,
    ApiErrorId.TENDER_NOT_OPEN: 409,
    ApiErrorId.PANEL_INCOMPLETE: 409,
    ApiErrorId.SHIFT_NOT_OPEN: 409,
    ApiErrorId.BLIND_VIOLATION: 422,
    ApiErrorId.WINDOW_OVERLAP: 409,
    ApiErrorId.SALE_WINDOW_CONFLICT: 409,
    ApiErrorId.CLEARANCE_GAP_VIOLATION: 409,
    ApiErrorId.CLAIM_WINDOW_EXPIRED: 422,
    ApiErrorId.SALE_WINDOW_INACTIVE: 409,
    ApiErrorId.SKU_CAP_EXCEEDED: 409,
    ApiErrorId.SKU_CAP_BELOW_CURRENT: 409,
    ApiErrorId.DUPLICATE_SKU: 409,
    ApiErrorId.BARCODE_COUNT_INVALID: 422,
    ApiErrorId.SHELF_READY_REQUIRED: 422,
    ApiErrorId.BID_DUPLICATE: 409,
    ApiErrorId.DUAL_SOURCE_REQUIRED: 409,
    ApiErrorId.SUPPLIER_SUSPENDED: 409,
    ApiErrorId.ALLOCATION_INCOMPLETE: 409,
    ApiErrorId.PRODUCT_NOT_ACTIVE: 409,
    ApiErrorId.FINDS_NO_REPLENISHMENT: 409,
    ApiErrorId.WINDOW_LIMIT_EXCEEDED: 409,
    ApiErrorId.CASHIER_ROLE_REQUIRED: 422,
    ApiErrorId.STALE_VERSION: 412,
    ApiErrorId.BID_CEILING_EXCEEDED: 422,
    ApiErrorId.LABOR_BUDGET_EXCEEDED: 422,
    ApiErrorId.COIN_BALANCE_NEGATIVE: 422,
    ApiErrorId.ALLOCATION_EXHAUSTED: 409,
}

# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})
