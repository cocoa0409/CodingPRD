"""Error class + error id catalog."""
from db import DB, fmt_iso
import uuid


class APIError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ITEM_NOT_ACTIVE": 409,
    "ERR_SAFETY_HOLD": 409,
    "ERR_CONTAINER_QUARANTINE_BLOCK": 409,
    "ERR_PO_HAS_SHIPPED_CONTAINERS": 409,
    "ERR_PO_ACTUAL_COSTS_REQUIRED": 422,
    "ERR_OVER_ALLOCATION": 409,
    "ERR_CONTAINER_NOT_ALLOCATABLE": 409,
    "ERR_STORE_DOCK_CAPACITY_EXCEEDED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_MARGIN_FLOOR_VIOLATION": 422,
    "ERR_EMPTY_SALE": 422,
    "ERR_ITEM_NOT_IN_STORE_ASSORTMENT": 422,
    "ERR_COUPON_NOT_ACTIVE": 409,
    "ERR_COUPON_EXHAUSTED": 409,
    "ERR_COUPON_OUTSIDE_WINDOW": 422,
    "ERR_COUPON_MEMBERS_ONLY": 422,
    "ERR_COUPON_CUSTOMER_LIMIT_REACHED": 422,
    "ERR_COUPON_MIN_BASKET_NOT_MET": 422,
    "ERR_COUPON_BUDGET_EXCEEDED": 402,
    "ERR_COUPON_ALREADY_APPLIED": 409,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_RETURN_WINDOW_EXPIRED": 422,
    "ERR_RETURN_QUANTITY_EXCEEDED": 422,
    "ERR_RENEWAL_WINDOW_CLOSED": 422,
    "ERR_MEMBERSHIP_EXISTS": 409,
    "ERR_CLAIM_APPEAL_EXHAUSTED": 409,
    "ERR_CLAIM_FINAL": 409,
    "ERR_SETTLEMENT_EXCEEDS_CLAIM": 422,
}


def raise_err(error_id, message=None):
    status = ERR[error_id]
    raise APIError(error_id, message or error_id, status)


def new_request_id():
    return "req_" + uuid.uuid4().hex[:22]


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": fmt_iso(DB.now()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
