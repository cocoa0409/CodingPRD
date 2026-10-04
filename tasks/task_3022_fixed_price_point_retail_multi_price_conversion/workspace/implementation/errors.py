"""Error identifiers and the transport exception, per SCAFFOLD §1.6 / PRD §5."""

# --- auth -------------------------------------------------------------------
ERR_MISSING_USER_CONTEXT = "ERR_MISSING_USER_CONTEXT"
ERR_INSUFFICIENT_ROLE = "ERR_INSUFFICIENT_ROLE"

# --- not found --------------------------------------------------------------
ERR_ITEM_NOT_FOUND = "ERR_ITEM_NOT_FOUND"
ERR_CONTAINER_NOT_FOUND = "ERR_CONTAINER_NOT_FOUND"
ERR_STORE_NOT_FOUND = "ERR_STORE_NOT_FOUND"
ERR_VENDOR_NOT_FOUND = "ERR_VENDOR_NOT_FOUND"
ERR_PRICE_POINT_NOT_FOUND = "ERR_PRICE_POINT_NOT_FOUND"
ERR_SEASON_WINDOW_NOT_FOUND = "ERR_SEASON_WINDOW_NOT_FOUND"
ERR_AISLE_RESET_NOT_FOUND = "ERR_AISLE_RESET_NOT_FOUND"
ERR_ALLOCATION_LINE_NOT_FOUND = "ERR_ALLOCATION_LINE_NOT_FOUND"
ERR_CONVERSION_PROJECT_NOT_FOUND = "ERR_CONVERSION_PROJECT_NOT_FOUND"
ERR_AUDIT_NOT_FOUND = "ERR_AUDIT_NOT_FOUND"
ERR_PACK_PROGRAM_NOT_FOUND = "ERR_PACK_PROGRAM_NOT_FOUND"

# --- request shape ----------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_DUPLICATE_SKU = "ERR_DUPLICATE_SKU"

# --- price point ------------------------------------------------------------
ERR_PRICE_POINT_MISMATCH = "ERR_PRICE_POINT_MISMATCH"
ERR_PRICE_POINT_NOT_ACTIVE = "ERR_PRICE_POINT_NOT_ACTIVE"
ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION = "ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION"

# --- item lifecycle ---------------------------------------------------------
ERR_ITEM_NOT_DENOMINATED = "ERR_ITEM_NOT_DENOMINATED"
ERR_ITEM_NOT_PRICE_ASSIGNED = "ERR_ITEM_NOT_PRICE_ASSIGNED"
ERR_ITEM_NOT_COST_PENDING = "ERR_ITEM_NOT_COST_PENDING"
ERR_ITEM_NOT_IN_DELETE_REVIEW = "ERR_ITEM_NOT_IN_DELETE_REVIEW"
ERR_ITEM_NOT_COST_CLEARED = "ERR_ITEM_NOT_COST_CLEARED"
ERR_COST_EXCEEDS_PRICE_POINT = "ERR_COST_EXCEEDS_PRICE_POINT"

# --- container / freight ----------------------------------------------------
ERR_CONTAINER_NOT_BOOKED = "ERR_CONTAINER_NOT_BOOKED"
ERR_CONTAINER_NOT_IN_TRANSIT = "ERR_CONTAINER_NOT_IN_TRANSIT"
ERR_CONTAINER_NOT_AT_PORT = "ERR_CONTAINER_NOT_AT_PORT"
ERR_CONTAINER_NOT_RECEIVED = "ERR_CONTAINER_NOT_RECEIVED"
ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD = "ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD"
ERR_CUSTOMS_NOT_CLEARED = "ERR_CUSTOMS_NOT_CLEARED"
ERR_CONTAINER_VENDOR_MISMATCH = "ERR_CONTAINER_VENDOR_MISMATCH"

# --- allocation -------------------------------------------------------------
ERR_ALLOCATION_LINE_NOT_ALLOCATED = "ERR_ALLOCATION_LINE_NOT_ALLOCATED"
ERR_RELEASE_EXCEEDS_ALLOCATION = "ERR_RELEASE_EXCEEDS_ALLOCATION"

# --- store conversion -------------------------------------------------------
ERR_STORE_NOT_SINGLE_PRICE = "ERR_STORE_NOT_SINGLE_PRICE"
ERR_STORE_NOT_MULTI_PRICE = "ERR_STORE_NOT_MULTI_PRICE"
ERR_STORE_NOT_CONVERTING = "ERR_STORE_NOT_CONVERTING"
ERR_STORE_ALREADY_CONVERTING = "ERR_STORE_ALREADY_CONVERTING"
ERR_CONVERSION_NOT_DRAFT = "ERR_CONVERSION_NOT_DRAFT"
ERR_CONVERSION_NOT_IN_PROGRESS = "ERR_CONVERSION_NOT_IN_PROGRESS"
ERR_CONVERSION_PREREQUISITES_UNMET = "ERR_CONVERSION_PREREQUISITES_UNMET"
ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT = "ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT"

# --- reset calendar ---------------------------------------------------------
ERR_SEASON_WINDOW_NOT_DRAFT = "ERR_SEASON_WINDOW_NOT_DRAFT"
ERR_SEASON_WINDOW_NOT_SCHEDULED = "ERR_SEASON_WINDOW_NOT_SCHEDULED"
ERR_SEASON_WINDOW_NOT_OPEN = "ERR_SEASON_WINDOW_NOT_OPEN"
ERR_INVALID_SEASON_WINDOW = "ERR_INVALID_SEASON_WINDOW"
ERR_AISLE_RESET_NOT_PLANNED = "ERR_AISLE_RESET_NOT_PLANNED"
ERR_AISLE_RESET_NOT_EXECUTING = "ERR_AISLE_RESET_NOT_EXECUTING"
ERR_AISLE_RESET_OVERLAP = "ERR_AISLE_RESET_OVERLAP"
ERR_RESET_OUTSIDE_CALENDAR = "ERR_RESET_OUTSIDE_CALENDAR"
ERR_STORE_DAY_CAPACITY_EXCEEDED = "ERR_STORE_DAY_CAPACITY_EXCEEDED"
ERR_NO_ELIGIBLE_ITEMS = "ERR_NO_ELIGIBLE_ITEMS"

# --- price integrity --------------------------------------------------------
ERR_AUDIT_ALREADY_RESOLVED = "ERR_AUDIT_ALREADY_RESOLVED"
ERR_MIXED_PRICE_POINT_OPEN_VIOLATION = "ERR_MIXED_PRICE_POINT_OPEN_VIOLATION"

# --- vendor pack development ------------------------------------------------
ERR_PACK_COST_TARGET_MISSED = "ERR_PACK_COST_TARGET_MISSED"

# --- concurrency ------------------------------------------------------------
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_AISLE_COVERAGE_SHORTFALL = "ERR_AISLE_COVERAGE_SHORTFALL"

# --- fallbacks --------------------------------------------------------------
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_METHOD_NOT_ALLOWED = "ERR_METHOD_NOT_ALLOWED"

STATUS_BY_ERROR = {
    ERR_MISSING_USER_CONTEXT: 401,
    ERR_INSUFFICIENT_ROLE: 403,
    ERR_ITEM_NOT_FOUND: 404,
    ERR_CONTAINER_NOT_FOUND: 404,
    ERR_STORE_NOT_FOUND: 404,
    ERR_VENDOR_NOT_FOUND: 404,
    ERR_PRICE_POINT_NOT_FOUND: 404,
    ERR_SEASON_WINDOW_NOT_FOUND: 404,
    ERR_AISLE_RESET_NOT_FOUND: 404,
    ERR_ALLOCATION_LINE_NOT_FOUND: 404,
    ERR_CONVERSION_PROJECT_NOT_FOUND: 404,
    ERR_AUDIT_NOT_FOUND: 404,
    ERR_PACK_PROGRAM_NOT_FOUND: 404,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_SEASON_WINDOW: 400,
    ERR_DUPLICATE_SKU: 409,
    ERR_PRICE_POINT_MISMATCH: 422,
    ERR_PRICE_POINT_NOT_ACTIVE: 409,
    ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION: 409,
    ERR_ITEM_NOT_DENOMINATED: 409,
    ERR_ITEM_NOT_PRICE_ASSIGNED: 409,
    ERR_ITEM_NOT_COST_PENDING: 409,
    ERR_ITEM_NOT_IN_DELETE_REVIEW: 409,
    ERR_ITEM_NOT_COST_CLEARED: 422,
    ERR_COST_EXCEEDS_PRICE_POINT: 422,
    ERR_CONTAINER_NOT_BOOKED: 409,
    ERR_CONTAINER_NOT_IN_TRANSIT: 409,
    ERR_CONTAINER_NOT_AT_PORT: 409,
    ERR_CONTAINER_NOT_RECEIVED: 409,
    ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD: 409,
    ERR_CUSTOMS_NOT_CLEARED: 409,
    ERR_CONTAINER_VENDOR_MISMATCH: 409,
    ERR_ALLOCATION_LINE_NOT_ALLOCATED: 409,
    ERR_RELEASE_EXCEEDS_ALLOCATION: 422,
    ERR_STORE_NOT_SINGLE_PRICE: 409,
    ERR_STORE_NOT_MULTI_PRICE: 409,
    ERR_STORE_NOT_CONVERTING: 409,
    ERR_STORE_ALREADY_CONVERTING: 409,
    ERR_CONVERSION_NOT_DRAFT: 409,
    ERR_CONVERSION_NOT_IN_PROGRESS: 409,
    ERR_CONVERSION_PREREQUISITES_UNMET: 409,
    ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT: 409,
    ERR_SEASON_WINDOW_NOT_DRAFT: 409,
    ERR_SEASON_WINDOW_NOT_SCHEDULED: 409,
    ERR_SEASON_WINDOW_NOT_OPEN: 409,
    ERR_AISLE_RESET_NOT_PLANNED: 409,
    ERR_AISLE_RESET_NOT_EXECUTING: 409,
    ERR_AISLE_RESET_OVERLAP: 409,
    ERR_RESET_OUTSIDE_CALENDAR: 409,
    ERR_STORE_DAY_CAPACITY_EXCEEDED: 422,
    ERR_NO_ELIGIBLE_ITEMS: 422,
    ERR_AUDIT_ALREADY_RESOLVED: 409,
    ERR_MIXED_PRICE_POINT_OPEN_VIOLATION: 422,
    ERR_PACK_COST_TARGET_MISSED: 422,
    ERR_STALE_VERSION: 412,
    ERR_AISLE_COVERAGE_SHORTFALL: 422,
    ERR_METHOD_NOT_ALLOWED: 405,
}

DEFAULT_MESSAGES = {
    ERR_MISSING_USER_CONTEXT: "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role.",
    ERR_INSUFFICIENT_ROLE: "The acting role is not permitted to call this endpoint.",
    ERR_INVALID_REQUEST: "The request body violates a declared shape constraint.",
    ERR_DUPLICATE_SKU: "A unique key supplied on creation is already held by another row.",
    ERR_PRICE_POINT_MISMATCH: "Item.unit_retail_cents does not equal the assigned PricePoint.shelf_price_cents.",
    ERR_PRICE_POINT_NOT_ACTIVE: "The referenced PricePoint is not ACTIVE and may not be issued.",
    ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION: "The AisleReset price point differs from the converting store's conversion price point.",
    ERR_ITEM_NOT_DENOMINATED: "The Item is not in DENOMINATED.",
    ERR_ITEM_NOT_PRICE_ASSIGNED: "The Item is not in PRICE_ASSIGNED.",
    ERR_ITEM_NOT_COST_PENDING: "The Item is not in COST_PENDING.",
    ERR_ITEM_NOT_IN_DELETE_REVIEW: "The Item is not in DELETE_REVIEW.",
    ERR_ITEM_NOT_COST_CLEARED: "The Item's net contribution is negative and it is not cured by an ACTIVE exclusive pack.",
    ERR_COST_EXCEEDS_PRICE_POINT: "The landed cost drives the net contribution below zero; the loss is reported against an ACTIVE exclusive pack.",
    ERR_CONTAINER_NOT_BOOKED: "The Container is not in BOOKED.",
    ERR_CONTAINER_NOT_IN_TRANSIT: "The Container is not in IN_TRANSIT.",
    ERR_CONTAINER_NOT_AT_PORT: "The Container is not in AT_PORT.",
    ERR_CONTAINER_NOT_RECEIVED: "The Container is not in RECEIVED.",
    ERR_CONTAINER_NOT_ON_CUSTOMS_HOLD: "The Container is not in CUSTOMS_HOLD.",
    ERR_CUSTOMS_NOT_CLEARED: "The Container has not been cleared by customs.",
    ERR_CONTAINER_VENDOR_MISMATCH: "The Container's vendor differs from the Item's sourcing vendor.",
    ERR_ALLOCATION_LINE_NOT_ALLOCATED: "The AllocationLine is not in ALLOCATED.",
    ERR_RELEASE_EXCEEDS_ALLOCATION: "release_units exceeds the AllocationLine's remaining_units.",
    ERR_STORE_NOT_SINGLE_PRICE: "The Store is not in SINGLE_PRICE.",
    ERR_STORE_NOT_MULTI_PRICE: "The Store is not in MULTI_PRICE.",
    ERR_STORE_NOT_CONVERTING: "The Store is not in CONVERTING or REVERTING.",
    ERR_STORE_ALREADY_CONVERTING: "The Store already has a conversion price point set.",
    ERR_CONVERSION_NOT_DRAFT: "The ConversionProject is not in DRAFT.",
    ERR_CONVERSION_NOT_IN_PROGRESS: "The ConversionProject is not in IN_PROGRESS.",
    ERR_CONVERSION_PREREQUISITES_UNMET: "A required conversion artefact has not been filed.",
    ERR_ITEM_NOT_AT_SOURCE_PRICE_POINT: "An item in the batch does not sit at the batch's source price point.",
    ERR_SEASON_WINDOW_NOT_DRAFT: "The SeasonWindow is not in DRAFT.",
    ERR_SEASON_WINDOW_NOT_SCHEDULED: "The SeasonWindow is not in SCHEDULED.",
    ERR_SEASON_WINDOW_NOT_OPEN: "The SeasonWindow is not OPEN.",
    ERR_INVALID_SEASON_WINDOW: "closes_on must be strictly after opens_on.",
    ERR_AISLE_RESET_NOT_PLANNED: "The AisleReset is not in PLANNED.",
    ERR_AISLE_RESET_NOT_EXECUTING: "The AisleReset is not in EXECUTING.",
    ERR_AISLE_RESET_OVERLAP: "The AisleReset interval overlaps a non-terminal reset on the same aisle of the same store.",
    ERR_RESET_OUTSIDE_CALENDAR: "The AisleReset interval is not fully contained in its SeasonWindow.",
    ERR_STORE_DAY_CAPACITY_EXCEEDED: "The store-day aggregate shelf commitment exceeds the store's shelf facing capacity.",
    ERR_NO_ELIGIBLE_ITEMS: "No ACTIVE Item carries the reset's price point.",
    ERR_AUDIT_ALREADY_RESOLVED: "The price integrity audit is already RESOLVED.",
    ERR_MIXED_PRICE_POINT_OPEN_VIOLATION: "The store already carries an OPEN violation under a different price point.",
    ERR_PACK_COST_TARGET_MISSED: "quoted_landed_cost_cents exceeds the target landed cost ceiling.",
    ERR_STALE_VERSION: "expected_store_version does not equal the store's current version.",
    ERR_AISLE_COVERAGE_SHORTFALL: "coverage_delta_pct is below -0.50.",
    ERR_NOT_FOUND: "The requested path does not resolve.",
    ERR_METHOD_NOT_ALLOWED: "The HTTP method is not allowed on this path.",
}
for _eid in (
    ERR_ITEM_NOT_FOUND,
    ERR_CONTAINER_NOT_FOUND,
    ERR_STORE_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
    ERR_PRICE_POINT_NOT_FOUND,
    ERR_SEASON_WINDOW_NOT_FOUND,
    ERR_AISLE_RESET_NOT_FOUND,
    ERR_ALLOCATION_LINE_NOT_FOUND,
    ERR_CONVERSION_PROJECT_NOT_FOUND,
    ERR_AUDIT_NOT_FOUND,
    ERR_PACK_PROGRAM_NOT_FOUND,
):
    DEFAULT_MESSAGES[_eid] = "No resource exists for the supplied id."


class ApiError(Exception):
    """Carries the scaffold-declared error_id, message and HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or STATUS_BY_ERROR.get(error_id, 400)


def fail(error_id, message=None, http_status=None):
    raise ApiError(error_id, message, http_status)