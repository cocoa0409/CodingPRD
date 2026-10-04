"""Error catalog for the membership-overnight-parking API.

Every error identifier in PRD section 5 / SCAFFOLD section 1.6 carries a fixed
HTTP status.  `ApiError` is the single exception type raised by the service
layer; the Flask error handler turns it into the standard error envelope.
"""

HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_HOST_NOT_ACCEPTING_STAYS": 409,
    "ERR_ORDINANCE_CONSTRAINT": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_REQUEST_LEAD_TIME": 422,
    "ERR_STAY_WINDOW_PASSED": 422,
    "ERR_VEHICLE_OCCUPANCY_OVERLAP": 409,
    "ERR_SITE_APPROACH_BLOCKED": 409,
    "ERR_HOST_CAPACITY_FULL": 409,
    "ERR_DUPLICATE_SITE_LABEL": 409,
    "ERR_MEMBER_EMAIL_DUPLICATE": 409,
    "ERR_VEHICLE_LENGTH_EXCEEDS_SITE": 422,
    "ERR_SITE_ELECTRIC_INCOMPATIBLE": 422,
    "ERR_VEHICLE_NOT_SELF_CONTAINED": 422,
    "ERR_MEMBER_NOT_ELIGIBLE": 403,
    "ERR_REVIEW_NOT_ELIGIBLE": 403,
    "ERR_DISPOSITION_NAME_COLLISION": 409,
    "ERR_WINDOW_CAPACITY_BELOW_RESERVED": 422,
    "ERR_WINDOW_EVICTS_CONFIRMED_STAY": 422,
    "ERR_BALANCE_DUE": 402,
    "ERR_STALE_HOST_VERSION": 412,
    "ERR_STALE_REQUEST_VERSION": 412,
    "ERR_STALE_WINDOW_VERSION": 412,
    "ERR_WINDOW_NOT_ACTIVE": 409,
    "ERR_PATRONIZATION_CODE_INVALID": 422,
    "ERR_REVIEW_ALREADY_WITHDRAWN": 409,
    "ERR_INCIDENT_NOT_OPEN": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-Role or X-User-ID header is missing or names an unrecognized role.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted for this operation.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_HOST_NOT_ACCEPTING_STAYS": "The host is not accepting stay requests.",
    "ERR_ORDINANCE_CONSTRAINT": "The local ordinance profile for this host is violated.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this operation.",
    "ERR_REQUEST_LEAD_TIME": "The stay request is inside the 48-hour lead-time guard.",
    "ERR_STAY_WINDOW_PASSED": "The stay's occupancy window has already passed.",
    "ERR_VEHICLE_OCCUPANCY_OVERLAP": "The vehicle already has an overlapping stay.",
    "ERR_SITE_APPROACH_BLOCKED": "The assigned site's approach is blocked by a circulating stay.",
    "ERR_HOST_CAPACITY_FULL": "The host has no free sites for this request.",
    "ERR_DUPLICATE_SITE_LABEL": "A parking site with this label already exists on the host.",
    "ERR_MEMBER_EMAIL_DUPLICATE": "This email address is already registered.",
    "ERR_VEHICLE_LENGTH_EXCEEDS_SITE": "The assigned site is shorter than the vehicle.",
    "ERR_SITE_ELECTRIC_INCOMPATIBLE": "The assigned site's electric pedestal is less capable than requested.",
    "ERR_VEHICLE_NOT_SELF_CONTAINED": "The host requires a self-contained rig with an inspection record.",
    "ERR_MEMBER_NOT_ELIGIBLE": "The member's subscription or removal status blocks this operation.",
    "ERR_REVIEW_NOT_ELIGIBLE": "No completed stay between this member and host authorizes a review.",
    "ERR_DISPOSITION_NAME_COLLISION": "The supplied display name collides with another member's name.",
    "ERR_WINDOW_CAPACITY_BELOW_RESERVED": "The window capacity override is below its reserved sites.",
    "ERR_WINDOW_EVICTS_CONFIRMED_STAY": "The amended window ceiling would evict a confirmed stay.",
    "ERR_BALANCE_DUE": "Outstanding dues or cancellation fees block a new stay request.",
    "ERR_STALE_HOST_VERSION": "expected_host_version does not match the host's current version.",
    "ERR_STALE_REQUEST_VERSION": "expected_request_version does not match the stay's current version.",
    "ERR_STALE_WINDOW_VERSION": "expected_window_version does not match the window's current version.",
    "ERR_WINDOW_NOT_ACTIVE": "The window is not ACTIVE and cannot be amended.",
    "ERR_PATRONIZATION_CODE_INVALID": "The verification code does not match the minted code.",
    "ERR_REVIEW_ALREADY_WITHDRAWN": "The review has already been withdrawn.",
    "ERR_INCIDENT_NOT_OPEN": "The incident is not OPEN and cannot be ruled on.",
}


class ApiError(Exception):
    """An API failure carrying an error_id and its declared HTTP status."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "The request could not be completed."
        )
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)