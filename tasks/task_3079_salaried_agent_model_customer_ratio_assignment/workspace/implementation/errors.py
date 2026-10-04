"""Error catalogue and the ApiError exception carrying (error_id, http_status)."""


class ApiError(Exception):
    def __init__(self, error_id, message="", http_status=400):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or CATALOG.get(error_id, ("", ""))[1]
        self.http_status = http_status or CATALOG.get(error_id, (500, ""))[0]


# error_id -> (http_status, default message)
CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or malformed X-User-Role / X-User-ID headers."),
    "ERR_FORBIDDEN": (403, "The caller's role does not permit the operation, or the caller does not own the referenced resource."),
    "ERR_REGION_NOT_FOUND": (404, "No region matches the supplied identifier."),
    "ERR_AGENT_NOT_FOUND": (404, "No agent matches the supplied identifier."),
    "ERR_CLIENT_NOT_FOUND": (404, "No client matches the supplied identifier."),
    "ERR_TRANSACTION_NOT_FOUND": (404, "No transaction matches the supplied identifier."),
    "ERR_LISTING_NOT_FOUND": (404, "No listing agreement matches the supplied identifier."),
    "ERR_TOUR_NOT_FOUND": (404, "No tour matches the supplied identifier."),
    "ERR_SURVEY_NOT_FOUND": (404, "No survey matches the supplied identifier."),
    "ERR_REFERRAL_NOT_FOUND": (404, "No referral matches the supplied identifier."),
    "ERR_INVALID_REQUEST": (400, "A required input is absent, an enum value is outside its declared set, or a score/rating is outside 1..5."),
    "ERR_INVALID_STATE": (409, "The target resource is not in a state from which the requested operation is declared."),
    "ERR_GEOGRAPHY_MISMATCH": (409, "The agent's home_zip is not a member of the region's service_area_codes."),
    "ERR_CLIENT_EMAIL_DUPLICATE": (409, "A client with the same email already exists."),
    "ERR_LISTING_CLIENT_MISMATCH": (409, "The listing agreement's client has need_kind BUY rather than SELL."),
    "ERR_NO_ELIGIBLE_AGENT": (409, "The assignment selector found no eligible agent; the client stays UNASSIGNED with an explanatory reason code."),
    "ERR_AGENT_NOT_ELIGIBLE": (409, "No candidate agent satisfies the selector's eligibility requirement."),
    "ERR_REGION_CAPACITY_EXCEEDED": (409, "The region's partner pool is full: Region.open_referral_count is already at or above Region.capacity."),
    "ERR_TRANSACTION_ALREADY_OPEN": (409, "The client already has a transaction whose coordination_status is UNASSIGNED, ASSIGNED or REVIEW."),
    "ERR_ASSOCIATE_AGENT_REQUIRED": (409, "The lead agent's UniServicedTourCount has reached the block threshold and no associate agent was staffed on the tour."),
    "ERR_TOUR_SCHEDULE_CONFLICT": (409, "The lead agent or the client already has a tour whose block window overlaps the requested window."),
    "ERR_ACCESS_WINDOW_NOT_OPEN": (409, "The tour was confirmed before its access-code release instant."),
    "ERR_LIST_PRICE_OUT_OF_BAND": (409, "list_price_cents is below the minimum or above the maximum supported by the region's listing programme."),
    "ERR_LIST_FEE_RATE_EXCEEDED": (409, "list_fee_rate_pct exceeds the flat listing fee ceiling, which is below the traditional brokerage rate."),
    "ERR_REFERRAL_FEE_EXCEEDED": (409, "referral_fee_bps exceeds the partner referral fee ceiling."),
    "ERR_CONTRACT_PRICE_MISSING": (409, "A transaction was closed without a contract price recorded."),
    "ERR_NO_CONTRACT_PRICE": (409, "A referral fee computation was requested before any contract price exists for the referred client."),
    "ERR_ENROLMENT_NOT_CONFIRMED": (409, "The region requires benefit enrolment and the request did not acknowledge it."),
    "ERR_STALE_VERSION": (412, "expected_region_version or expected_agent_version does not match the resource's current version."),
}


def raise_error(error_id, message=None):
    status, default = CATALOG.get(error_id, (500, "Unexpected error."))
    raise ApiError(error_id, message or default, status)