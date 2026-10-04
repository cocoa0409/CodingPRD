"""Domain error types and identifiers."""


class ApiError(Exception):
    """Exception carrying error_id, HTTP status, and a human message."""

    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error identifiers from PRD §5 / SCAFFOLD §1.6
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_DUPLICATE_KEY = "ERR_DUPLICATE_KEY"                # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_LICENSE_INACTIVE = "ERR_LICENSE_INACTIVE"          # 409
ERR_INVALID_FUNDING_SOURCE = "ERR_INVALID_FUNDING_SOURCE"  # 422
ERR_LOW_CONFIDENCE = "ERR_LOW_CONFIDENCE"              # 422
ERR_CADENCE_VIOLATION = "ERR_CADENCE_VIOLATION"        # 422
ERR_OFFER_EXPIRED = "ERR_OFFER_EXPIRED"                # 422
ERR_QUOTA_EXCEEDED = "ERR_QUOTA_EXCEEDED"              # 422
ERR_USE_NOT_PERMITTED = "ERR_USE_NOT_PERMITTED"        # 403
ERR_REGION_ARCHIVED = "ERR_REGION_ARCHIVED"            # 422
ERR_INVALID_INPUT = "ERR_INVALID_INPUT"                # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_DUPLICATE_DISPUTE = "ERR_DUPLICATE_DISPUTE"        # 409
ERR_SHIFT_IN_PAST = "ERR_SHIFT_IN_PAST"                # 422
ERR_EDITION_HAS_OPEN_OFFERS = "ERR_EDITION_HAS_OPEN_OFFERS"  # 422
ERR_INSUFFICIENT_DATA = "ERR_INSUFFICIENT_DATA"        # 422
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"      # 403


def unauthenticated(msg: str = "Authentication required") -> ApiError:
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg: str = "Role not permitted") -> ApiError:
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg: str = "Resource not found") -> ApiError:
    return ApiError(ERR_NOT_FOUND, 404, msg)


def duplicate_key(msg: str = "Duplicate idempotency key") -> ApiError:
    return ApiError(ERR_DUPLICATE_KEY, 409, msg)


def invalid_state(msg: str = "Invalid state") -> ApiError:
    return ApiError(ERR_INVALID_STATE, 409, msg)


def license_inactive(msg: str = "License agreement not ACTIVE") -> ApiError:
    return ApiError(ERR_LICENSE_INACTIVE, 409, msg)


def invalid_funding_source(msg: str = "Funding dealer must be a DEALER source") -> ApiError:
    return ApiError(ERR_INVALID_FUNDING_SOURCE, 422, msg)


def low_confidence(msg: str = "Series confidence below publish gate") -> ApiError:
    return ApiError(ERR_LOW_CONFIDENCE, 422, msg)


def cadence_violation(msg: str = "Weekly cadence violated") -> ApiError:
    return ApiError(ERR_CADENCE_VIOLATION, 422, msg)


def offer_expired(msg: str = "Offer expired") -> ApiError:
    return ApiError(ERR_OFFER_EXPIRED, 422, msg)


def quota_exceeded(msg: str = "License monthly event quota exceeded") -> ApiError:
    return ApiError(ERR_QUOTA_EXCEEDED, 422, msg)


def use_not_permitted(msg: str = "Use not permitted by agreement") -> ApiError:
    return ApiError(ERR_USE_NOT_PERMITTED, 403, msg)


def region_archived(msg: str = "Region is archived") -> ApiError:
    return ApiError(ERR_REGION_ARCHIVED, 422, msg)


def invalid_input(msg: str = "Invalid input") -> ApiError:
    return ApiError(ERR_INVALID_INPUT, 400, msg)


def stale_version(msg: str = "Stale expected_version") -> ApiError:
    return ApiError(ERR_STALE_VERSION, 412, msg)


def duplicate_dispute(msg: str = "An OPEN dispute already exists for this offer") -> ApiError:
    return ApiError(ERR_DUPLICATE_DISPUTE, 409, msg)


def shift_in_past(msg: str = "Shift effective_at is in the past") -> ApiError:
    return ApiError(ERR_SHIFT_IN_PAST, 422, msg)


def edition_has_open_offers(msg: str = "Edition has non-terminal cash offers") -> ApiError:
    return ApiError(ERR_EDITION_HAS_OPEN_OFFERS, 422, msg)


def insufficient_data(msg: str = "Insufficient trailing data") -> ApiError:
    return ApiError(ERR_INSUFFICIENT_DATA, 422, msg)
