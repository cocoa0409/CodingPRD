"""Error catalogue and the single API exception type.

Every identifier and HTTP status here is transcribed from PRD section 5 /
SCAFFOLD section 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)


# --- auth -------------------------------------------------------------------
ERR_MISSING_USER_ID = "ERR_MISSING_USER_ID"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"

# --- existence --------------------------------------------------------------
ERR_LANDOWNER_NOT_FOUND = "ERR_LANDOWNER_NOT_FOUND"
ERR_PARCEL_NOT_FOUND = "ERR_PARCEL_NOT_FOUND"
ERR_SETBACK_RULE_NOT_FOUND = "ERR_SETBACK_RULE_NOT_FOUND"
ERR_NEIGHBOR_CONSENT_NOT_FOUND = "ERR_NEIGHBOR_CONSENT_NOT_FOUND"
ERR_TITLE_CURATIVE_ITEM_NOT_FOUND = "ERR_TITLE_CURATIVE_ITEM_NOT_FOUND"
ERR_OPTION_AGREEMENT_NOT_FOUND = "ERR_OPTION_AGREEMENT_NOT_FOUND"
ERR_CORRIDOR_NOT_FOUND = "ERR_CORRIDOR_NOT_FOUND"
ERR_CROSSING_AGREEMENT_NOT_FOUND = "ERR_CROSSING_AGREEMENT_NOT_FOUND"
ERR_SITE_ACCESS_BOOKING_NOT_FOUND = "ERR_SITE_ACCESS_BOOKING_NOT_FOUND"
ERR_LEASE_AGREEMENT_NOT_FOUND = "ERR_LEASE_AGREEMENT_NOT_FOUND"
ERR_RENT_INVOICE_NOT_FOUND = "ERR_RENT_INVOICE_NOT_FOUND"

# --- request shape ----------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATION_RANGE = "ERR_INVALID_STATION_RANGE"
ERR_INVALID_WINDOW_RANGE = "ERR_INVALID_WINDOW_RANGE"

# --- concurrency & state ----------------------------------------------------
ERR_STALE_PARCEL_VERSION = "ERR_STALE_PARCEL_VERSION"
ERR_STALE_LEASE_VERSION = "ERR_STALE_LEASE_VERSION"
ERR_CONSENT_EXPIRED = "ERR_CONSENT_EXPIRED"
ERR_OPTION_EXPIRED = "ERR_OPTION_EXPIRED"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_RECORDED = "ERR_ALREADY_RECORDED"

# --- safety / title compliance ---------------------------------------------
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_TITLE_CURATIVE_BLOCKING = "ERR_TITLE_CURATIVE_BLOCKING"
ERR_CURATIVE_BLOCKED_PREDECESSOR = "ERR_CURATIVE_BLOCKED_PREDECESSOR"
ERR_SECURITY_NOT_POSTED = "ERR_SECURITY_NOT_POSTED"
ERR_W9_MISSING = "ERR_W9_MISSING"

# --- deal structure ---------------------------------------------------------
ERR_PARCEL_APN_DUPLICATE = "ERR_PARCEL_APN_DUPLICATE"
ERR_PROHIBITED_ZONING = "ERR_PROHIBITED_ZONING"
ERR_PARCEL_NOT_QUALIFIED = "ERR_PARCEL_NOT_QUALIFIED"
ERR_EXTENSION_LIMIT_REACHED = "ERR_EXTENSION_LIMIT_REACHED"
ERR_NEGOTIATION_ROUND_LIMIT = "ERR_NEGOTIATION_ROUND_LIMIT"
ERR_WAIVER_LIMIT_REACHED = "ERR_WAIVER_LIMIT_REACHED"
ERR_CORRIDOR_NOT_PERMITTED = "ERR_CORRIDOR_NOT_PERMITTED"
ERR_DUPLICATE_INVOICE_PERIOD = "ERR_DUPLICATE_INVOICE_PERIOD"

# --- temporal ---------------------------------------------------------------
ERR_CORRIDOR_STATION_CONFLICT = "ERR_CORRIDOR_STATION_CONFLICT"
ERR_CREW_CAPACITY_EXCEEDED = "ERR_CREW_CAPACITY_EXCEEDED"
ERR_WINDOW_IN_PAST = "ERR_WINDOW_IN_PAST"

# --- fiscal -----------------------------------------------------------------
ERR_LANDOWNER_PAYMENT_HOLD = "ERR_LANDOWNER_PAYMENT_HOLD"
ERR_SECURITY_OVERPOSTED = "ERR_SECURITY_OVERPOSTED"
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"


HTTP_STATUS = {
    ERR_MISSING_USER_ID: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_LANDOWNER_NOT_FOUND: 404,
    ERR_PARCEL_NOT_FOUND: 404,
    ERR_SETBACK_RULE_NOT_FOUND: 404,
    ERR_NEIGHBOR_CONSENT_NOT_FOUND: 404,
    ERR_TITLE_CURATIVE_ITEM_NOT_FOUND: 404,
    ERR_OPTION_AGREEMENT_NOT_FOUND: 404,
    ERR_CORRIDOR_NOT_FOUND: 404,
    ERR_CROSSING_AGREEMENT_NOT_FOUND: 404,
    ERR_SITE_ACCESS_BOOKING_NOT_FOUND: 404,
    ERR_LEASE_AGREEMENT_NOT_FOUND: 404,
    ERR_RENT_INVOICE_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_STATION_RANGE: 422,
    ERR_INVALID_WINDOW_RANGE: 422,
    ERR_STALE_PARCEL_VERSION: 412,
    ERR_STALE_LEASE_VERSION: 412,
    ERR_CONSENT_EXPIRED: 422,
    ERR_OPTION_EXPIRED: 422,
    ERR_INVALID_STATE: 409,
    ERR_ALREADY_RECORDED: 409,
    ERR_SEGREGATION_OF_DUTIES: 422,
    ERR_TITLE_CURATIVE_BLOCKING: 422,
    ERR_CURATIVE_BLOCKED_PREDECESSOR: 422,
    ERR_SECURITY_NOT_POSTED: 422,
    ERR_W9_MISSING: 422,
    ERR_PARCEL_APN_DUPLICATE: 409,
    ERR_PROHIBITED_ZONING: 422,
    ERR_PARCEL_NOT_QUALIFIED: 422,
    ERR_EXTENSION_LIMIT_REACHED: 422,
    ERR_NEGOTIATION_ROUND_LIMIT: 422,
    ERR_WAIVER_LIMIT_REACHED: 422,
    ERR_CORRIDOR_NOT_PERMITTED: 422,
    ERR_DUPLICATE_INVOICE_PERIOD: 409,
    ERR_CORRIDOR_STATION_CONFLICT: 409,
    ERR_CREW_CAPACITY_EXCEEDED: 409,
    ERR_WINDOW_IN_PAST: 422,
    ERR_LANDOWNER_PAYMENT_HOLD: 422,
    ERR_SECURITY_OVERPOSTED: 422,
    ERR_PAYMENT_AMOUNT_MISMATCH: 422,
}

ERROR_MESSAGES = {
    ERR_MISSING_USER_ID: "X-User-ID and X-User-Role headers are required and must be non-empty.",
    ERR_UNAUTHORIZED: "The acting role is not authorised for this operation.",
    ERR_LANDOWNER_NOT_FOUND: "No landowner exists with the supplied identifier.",
    ERR_PARCEL_NOT_FOUND: "No parcel exists with the supplied identifier.",
    ERR_SETBACK_RULE_NOT_FOUND: "No setback rule exists with the supplied identifier.",
    ERR_NEIGHBOR_CONSENT_NOT_FOUND: "No neighbor consent exists with the supplied identifier.",
    ERR_TITLE_CURATIVE_ITEM_NOT_FOUND: "No title curative item exists with the supplied identifier.",
    ERR_OPTION_AGREEMENT_NOT_FOUND: "No option agreement exists with the supplied identifier.",
    ERR_CORRIDOR_NOT_FOUND: "No corridor exists with the supplied identifier.",
    ERR_CROSSING_AGREEMENT_NOT_FOUND: "No crossing agreement exists with the supplied identifier.",
    ERR_SITE_ACCESS_BOOKING_NOT_FOUND: "No site-access booking exists with the supplied identifier.",
    ERR_LEASE_AGREEMENT_NOT_FOUND: "No lease agreement exists with the supplied identifier.",
    ERR_RENT_INVOICE_NOT_FOUND: "No rent invoice exists with the supplied identifier.",
    ERR_INVALID_REQUEST: "The request is not valid.",
    ERR_INVALID_STATION_RANGE: "The station range is not valid for this corridor.",
    ERR_INVALID_WINDOW_RANGE: "The half-open window is empty or inverted.",
    ERR_STALE_PARCEL_VERSION: "expected_parcel_version does not match the parcel's current version.",
    ERR_STALE_LEASE_VERSION: "expected_lease_agreement_version does not match the lease's current version.",
    ERR_CONSENT_EXPIRED: "The neighbor consent request has lapsed.",
    ERR_OPTION_EXPIRED: "The option agreement's term has run out.",
    ERR_INVALID_STATE: "The current state does not admit the requested transition.",
    ERR_ALREADY_RECORDED: "The memorandum of lease has already been recorded.",
    ERR_SEGREGATION_OF_DUTIES: "Segregation of duties forbids the acting user from performing this action.",
    ERR_TITLE_CURATIVE_BLOCKING: "An open blocking title curative item gates this action.",
    ERR_CURATIVE_BLOCKED_PREDECESSOR: "The curative item is still blocked by its predecessor.",
    ERR_SECURITY_NOT_POSTED: "The decommissioning security is not fully posted.",
    ERR_W9_MISSING: "The landowner has no W-9 on file.",
    ERR_PARCEL_APN_DUPLICATE: "A parcel with this apn and county_fips pair already exists.",
    ERR_PROHIBITED_ZONING: "The zoning code is prohibited.",
    ERR_PARCEL_NOT_QUALIFIED: "The underlying parcel is not qualified.",
    ERR_EXTENSION_LIMIT_REACHED: "Every purchased extension has already been used.",
    ERR_NEGOTIATION_ROUND_LIMIT: "The negotiation round limit has been reached.",
    ERR_WAIVER_LIMIT_REACHED: "The blocking-waiver limit for this parcel has been reached.",
    ERR_CORRIDOR_NOT_PERMITTED: "The corridor has not been permitted.",
    ERR_DUPLICATE_INVOICE_PERIOD: "An invoice already occupies this lease period.",
    ERR_CORRIDOR_STATION_CONFLICT: "The proposed crossing conflicts with an existing crossing.",
    ERR_CREW_CAPACITY_EXCEEDED: "Aggregate crew capacity on the parcel would be exceeded.",
    ERR_WINDOW_IN_PAST: "The access window starts before the current logical clock.",
    ERR_LANDOWNER_PAYMENT_HOLD: "The landowner is under a payment hold.",
    ERR_SECURITY_OVERPOSTED: "The posting would exceed the required decommissioning security.",
    ERR_PAYMENT_AMOUNT_MISMATCH: "paid_amount_cents must equal the invoice's gross_rent_cents exactly.",
}


def fail(error_id, message=None):
    """Raise the catalogued error, taking the HTTP status from the catalogue."""
    raise ApiError(error_id, HTTP_STATUS[error_id], message)


def bad_request(message=None):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)
