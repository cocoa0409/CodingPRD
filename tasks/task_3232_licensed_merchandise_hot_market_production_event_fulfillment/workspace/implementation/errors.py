"""Error catalog: error identifiers, HTTP statuses and the API exception type.

Every error_id and HTTP status below is taken verbatim from the task's error
catalog (PRD section 5 / SCAFFOLD section 1.6).
"""


class ApiError(Exception):
    """Raised by any layer; the app converts it into the standard error envelope."""

    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message


# --- Request shape & auth -------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"              # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_LICENSOR_MISMATCH = "ERR_LICENSOR_MISMATCH"        # 403

# --- Existence ------------------------------------------------------------
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_LICENSOR_NOT_FOUND = "ERR_LICENSOR_NOT_FOUND"      # 404
ERR_DESIGN_NOT_FOUND = "ERR_DESIGN_NOT_FOUND"          # 404
ERR_PRODUCTION_ORDER_NOT_FOUND = "ERR_PRODUCTION_ORDER_NOT_FOUND"  # 404
ERR_FULFILLMENT_ORDER_NOT_FOUND = "ERR_FULFILLMENT_ORDER_NOT_FOUND"  # 404

# --- State & concurrency --------------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_ALREADY_COMMITTED = "ERR_ALREADY_COMMITTED"        # 409

# --- Licensing & design approval -----------------------------------------
ERR_DESIGN_NOT_APPROVED = "ERR_DESIGN_NOT_APPROVED"    # 422
ERR_LICENSOR_PROJECT_NOT_FOUND = "ERR_LICENSOR_PROJECT_NOT_FOUND"  # 422
ERR_PRINT_TYPECAST_MISMATCH = "ERR_PRINT_TYPECAST_MISMATCH"  # 422
ERR_PRINT_QUANTITY_EXCEEDED = "ERR_PRINT_QUANTITY_EXCEEDED"  # 422

# --- Hot market & capacity ------------------------------------------------
ERR_UNBALANCED_ALLOCATION = "ERR_UNBALANCED_ALLOCATION"  # 422
ERR_RUSH_COMMITMENT_BREACH = "ERR_RUSH_COMMITMENT_BREACH"  # 422
ERR_EVENT_WINDOW_CLOSED = "ERR_EVENT_WINDOW_CLOSED"    # 409
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"        # 409
ERR_INVENTORY_INSUFFICIENT = "ERR_INVENTORY_INSUFFICIENT"  # 409
ERR_PRODUCTION_ALREADY_COMMITTED = "ERR_PRODUCTION_ALREADY_COMMITTED"  # 409
ERR_PICK_REMARK_REUSED = "ERR_PICK_REMARK_REUSED"      # 409
ERR_LOT_EXHAUSTED = "ERR_LOT_EXHAUSTED"                # 409

# --- Royalty ledger -------------------------------------------------------
ERR_NO_ACCRUED_ROYALTY = "ERR_NO_ACCRUED_ROYALTY"      # 422
ERR_GUARANTEE_FLOOR_BREACH = "ERR_GUARANTEE_FLOOR_BREACH"  # 422
ERR_SETTLEMENT_NOOP = "ERR_SETTLEMENT_NOOP"            # 422

# --- Counterfeit enforcement ---------------------------------------------
ERR_COUNTERFEIT_OVERCOUNT = "ERR_COUNTERFEIT_OVERCOUNT"  # 422
ERR_LISTING_UNVERIFIED = "ERR_LISTING_UNVERIFIED"      # 422


HTTP_STATUS = {
    ERR_INVALID_REQUEST: 400,
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_LICENSOR_MISMATCH: 403,
    ERR_NOT_FOUND: 404,
    ERR_LICENSOR_NOT_FOUND: 404,
    ERR_DESIGN_NOT_FOUND: 404,
    ERR_PRODUCTION_ORDER_NOT_FOUND: 404,
    ERR_FULFILLMENT_ORDER_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_STALE_VERSION: 412,
    ERR_ALREADY_COMMITTED: 409,
    ERR_DESIGN_NOT_APPROVED: 422,
    ERR_LICENSOR_PROJECT_NOT_FOUND: 422,
    ERR_PRINT_TYPECAST_MISMATCH: 422,
    ERR_PRINT_QUANTITY_EXCEEDED: 422,
    ERR_UNBALANCED_ALLOCATION: 422,
    ERR_RUSH_COMMITMENT_BREACH: 422,
    ERR_EVENT_WINDOW_CLOSED: 409,
    ERR_CAPACITY_EXCEEDED: 409,
    ERR_INVENTORY_INSUFFICIENT: 409,
    ERR_PRODUCTION_ALREADY_COMMITTED: 409,
    ERR_PICK_REMARK_REUSED: 409,
    ERR_LOT_EXHAUSTED: 409,
    ERR_NO_ACCRUED_ROYALTY: 422,
    ERR_GUARANTEE_FLOOR_BREACH: 422,
    ERR_SETTLEMENT_NOOP: 422,
    ERR_COUNTERFEIT_OVERCOUNT: 422,
    ERR_LISTING_UNVERIFIED: 422,
}


def fail(error_id, message=None):
    """Raise the API error for `error_id` with its catalogued HTTP status."""
    status = HTTP_STATUS.get(error_id, 400)
    raise ApiError(status, error_id, message or error_id)