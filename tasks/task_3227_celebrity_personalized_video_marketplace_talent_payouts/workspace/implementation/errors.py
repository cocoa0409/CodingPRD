"""Error types, response envelope helpers, and pagination."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog (id -> http status)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CONTENT_POLICY_FLAGGED": 422,
    "ERR_VIDEO_NOT_CLEARED": 409,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_ACCEPTANCE_WINDOW_CLOSED": 409,
    "ERR_DELIVERY_DEADLINE_PASSED": 409,
    "ERR_BUYER_WINDOW_CLOSED": 409,
    "ERR_INVALID_LICENSE_WINDOW": 422,
    "ERR_LICENSE_WINDOW_OVERLAP": 409,
    "ERR_TALENT_NOT_BOOKABLE": 409,
    "ERR_BUSINESS_ACCOUNT_REQUIRED": 403,
    "ERR_LICENSE_TYPE_INCOMPATIBLE": 422,
    "ERR_RERECORD_LIMIT_REACHED": 409,
    "ERR_DISPUTE_ALREADY_EXISTS": 409,
    "ERR_DUPLICATE_UNIQUE_FIELD": 409,
    "ERR_RATE_OUT_OF_BOUNDS": 422,
    "ERR_PAUSE_RATE_LIMIT": 429,
    "ERR_PAYOUT_BELOW_MINIMUM": 422,
    "ERR_TAX_DOC_MISSING": 422,
    "ERR_PENDING_BALANCE_INSUFFICIENT": 422,
}


def err(error_id, message):
    return ApiError(error_id, message, ERR[error_id])


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def parse_pagination(args):
    """Parse limit/offset from query args, enforcing bounds."""
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (ties broken by id) then page."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + len(page) < total
    return page, total, has_more
