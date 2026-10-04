"""Error classes and error ID constants (from SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                      # 403
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                    # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                    # 409
ERR_COMMISSARY_INVALID_STATE = "ERR_COMMISSARY_INVALID_STATE"      # 409
ERR_STORE_INVALID_STATE = "ERR_STORE_INVALID_STATE"                # 409
ERR_SURGE_ALREADY_ACTIVE = "ERR_SURGE_ALREADY_ACTIVE"              # 409
ERR_SURGE_NOT_ACTIVE = "ERR_SURGE_NOT_ACTIVE"                      # 409
ERR_SUPPLIER_INVALID_STATE = "ERR_SUPPLIER_INVALID_STATE"          # 409
ERR_AUDIT_ALREADY_RECORDED = "ERR_AUDIT_ALREADY_RECORDED"          # 409
ERR_ROUTE_INVALID_STATE = "ERR_ROUTE_INVALID_STATE"                # 409
ERR_BATCH_INVALID_STATE = "ERR_BATCH_INVALID_STATE"                # 409
ERR_DELIVERY_INVALID_STATE = "ERR_DELIVERY_INVALID_STATE"          # 409
ERR_RUN_INVALID_STATE = "ERR_RUN_INVALID_STATE"                    # 409
ERR_ORDER_INVALID_STATE = "ERR_ORDER_INVALID_STATE"                # 409
ERR_POSTING_INVALID_STATE = "ERR_POSTING_INVALID_STATE"            # 409
ERR_APPLICATION_INVALID_STATE = "ERR_APPLICATION_INVALID_STATE"    # 409
ERR_SHIFT_INVALID_STATE = "ERR_SHIFT_INVALID_STATE"                # 409
ERR_COLD_CHAIN_VIOLATION = "ERR_COLD_CHAIN_VIOLATION"              # 422
ERR_SUPPLIER_AUDIT_STALE = "ERR_SUPPLIER_AUDIT_STALE"              # 422
ERR_SUPPLIER_NOT_APPROVED = "ERR_SUPPLIER_NOT_APPROVED"            # 422
ERR_RADIUS_LIMIT_EXCEEDED = "ERR_RADIUS_LIMIT_EXCEEDED"            # 422
ERR_DELIVERY_FREQUENCY_VIOLATION = "ERR_DELIVERY_FREQUENCY_VIOLATION"  # 422
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"                            # 422
ERR_ROUTE_WINDOW_CONFLICT = "ERR_ROUTE_WINDOW_CONFLICT"            # 422
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"                    # 422
ERR_COOLER_CAPACITY_EXCEEDED = "ERR_COOLER_CAPACITY_EXCEEDED"      # 422
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"          # 422
ERR_PROMOTION_INELIGIBLE = "ERR_PROMOTION_INELIGIBLE"              # 422
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"                            # 422
ERR_POSTURE_BLOCKS = "ERR_POSTURE_BLOCKS"                          # 422
ERR_TRUCK_INACTIVE = "ERR_TRUCK_INACTIVE"                          # 422
ERR_OPEN_BATCHES_EXIST = "ERR_OPEN_BATCHES_EXIST"                  # 409
ERR_STORES_STILL_OPEN = "ERR_STORES_STILL_OPEN"                    # 409
ERR_BATCHES_NOT_DELIVERED = "ERR_BATCHES_NOT_DELIVERED"            # 409
ERR_OPEN_SHIFTS_EXIST = "ERR_OPEN_SHIFTS_EXIST"                    # 409
ERR_RUN_NOT_COMPLETED = "ERR_RUN_NOT_COMPLETED"                    # 422


def unauthenticated(msg="Authentication required"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, msg, 403)


def forbidden(msg="Identity/ownership check failed"):
    return ApiError(ERR_FORBIDDEN_ROLE, msg, 403)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def linkage(msg="Cross-entity linkage check failed"):
    """Tier-12 linkage failures surface ERR_INVALID_REQUEST; the suite's error
    catalog maps ERR_INVALID_REQUEST to HTTP 400."""
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def conflict(error_id, msg):
    return ApiError(error_id, msg, 409)


def unprocessable(error_id, msg):
    return ApiError(error_id, msg, 422)
