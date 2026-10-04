class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or unrecognized X-User-Role or X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)

def err_unauthorized_role(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", msg, 403)

def err_not_found(msg="Resource not found"):
    return ApiError("ERR_RESOURCE_NOT_FOUND", msg, 404)

def err_validation(msg="Validation failed"):
    return ApiError("ERR_VALIDATION", msg, 400)

def err_invalid_state(msg="Invalid state for requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)

def err_already_terminal(msg="Entity is in a terminal state"):
    return ApiError("ERR_ALREADY_TERMINAL", msg, 409)

def err_stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)

def err_agreement_not_active(msg="Agreement is not ACTIVE"):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", msg, 409)

def err_agreement_already_active(msg="Agreement is not in DRAFT"):
    return ApiError("ERR_AGREEMENT_ALREADY_ACTIVE", msg, 409)

def err_territory_has_active(msg="Territory already has an ACTIVE agreement"):
    return ApiError("ERR_TERRITORY_HAS_ACTIVE_AGREEMENT", msg, 409)

def err_line_obligation(msg="Mandatory product line obligations unmet"):
    return ApiError("ERR_LINE_OBLIGATION_UNMET", msg, 422)

def err_min_order(msg="quantity_gallons below minimum order quantity"):
    return ApiError("ERR_MIN_ORDER_QUANTITY", msg, 422)

def err_zero_quantity(msg="Quantity must be greater than zero"):
    return ApiError("ERR_ZERO_QUANTITY", msg, 400)

def err_index_duplicate(msg="Index already exists for brand and quarter"):
    return ApiError("ERR_INDEX_QUARTER_DUPLICATE", msg, 409)

def err_cpo_finalized(msg="CPO pricing already FINALIZED"):
    return ApiError("ERR_CPO_ALREADY_FINALIZED", msg, 409)

def err_price_band(msg="Local price deviates from NCA price by more than 5%"):
    return ApiError("ERR_PRICE_DEVIATION_EXCEEDS_BAND", msg, 422)

def err_nca_not_published(msg="NCA is not PUBLISHED"):
    return ApiError("ERR_NCA_NOT_PUBLISHED", msg, 409)

def err_nca_overlap(msg="Overlapping PUBLISHED NCA window"):
    return ApiError("ERR_NCA_WINDOW_OVERLAP", msg, 409)

def err_window_overlap(msg="Service window overlaps another window for the same technician"):
    return ApiError("ERR_SERVICE_WINDOW_OVERLAP", msg, 409)

def err_placement_overlap(msg="Placement interval overlaps another placement"):
    return ApiError("ERR_EQUIPMENT_PLACEMENT_OVERLAP", msg, 409)

def err_equipment_not_in_warehouse(msg="Equipment is not IN_WAREHOUSE"):
    return ApiError("ERR_EQUIPMENT_NOT_IN_WAREHOUSE", msg, 409)

def err_service_budget(msg="Service budget exceeded"):
    return ApiError("ERR_SERVICE_BUDGET_EXCEEDED", msg, 422)

def err_customer_disputed(msg="Customer is DISPUTED"):
    return ApiError("ERR_CUSTOMER_DISPUTED", msg, 409)

def err_order_not_delivered(msg="DSD order not DELIVERED"):
    return ApiError("ERR_DSD_ORDER_NOT_DELIVERED", msg, 409)

def err_transfer_disputed(msg="A customer of the territory's agreement is DISPUTED"):
    return ApiError("ERR_TRANSFER_CUSTOMERS_DISPUTED", msg, 409)

def err_commitment_window_open(msg="Commitment window still open"):
    return ApiError("ERR_COMMITMENT_WINDOW_OPEN", msg, 409)

def err_launch_product_inactive(msg="Product line is not ACTIVE"):
    return ApiError("ERR_LAUNCH_PRODUCT_INACTIVE", msg, 409)

def err_fund_insufficient(msg="Insufficient marketing fund balance"):
    return ApiError("ERR_FUND_INSUFFICIENT_BALANCE", msg, 422)

def err_clawback_exceeds(msg="Clawback exceeds referenced accrual amount"):
    return ApiError("ERR_CLAWBACK_EXCEEDS_ACCRUAL", msg, 422)

def err_maintenance_overdue(msg="Fountain maintenance is overdue"):
    return ApiError("ERR_FOUNTAIN_MAINTENANCE_OVERDUE", msg, 409)

def err_referential(msg="Cross-reference integrity violation"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", msg, 422)
