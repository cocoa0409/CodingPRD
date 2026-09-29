"""Error catalogue for the Motor Vehicle Dealer Board API.

Every error identifier and its HTTP status is taken verbatim from PRD section 5.
"""


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a declared error."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message if message is not None else _default_message(error_id)
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)
        super().__init__(self.message)


ERROR_HTTP = {
    # --- authentication / authorisation / ownership -----------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request validity -------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    # --- existence --------------------------------------------------------
    "ERR_MANUFACTURER_NOT_FOUND": 404,
    "ERR_HEARING_ROOM_NOT_FOUND": 404,
    "ERR_DEALER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_SALESPERSON_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_PROTEST_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    # --- optimistic concurrency ------------------------------------------
    "ERR_STALE_FILING_VERSION": 412,
    "ERR_STALE_ROOM_VERSION": 412,
    # --- state gates ------------------------------------------------------
    "ERR_INVALID_APPLICATION_STATE": 409,
    "ERR_INVALID_SALESPERSON_STATE": 409,
    "ERR_INVALID_FILING_STATE": 409,
    "ERR_INVALID_PROTEST_STATE": 409,
    "ERR_INVALID_DISPUTE_STATE": 409,
    "ERR_INVALID_COMPLAINT_STATE": 409,
    # --- party standing ---------------------------------------------------
    "ERR_MANUFACTURER_REGISTRATION_LAPSED": 422,
    "ERR_APPLICATION_HAS_DEFICIENCIES": 422,
    "ERR_SPONSOR_NOT_LICENSED": 422,
    "ERR_UNDISCLOSED_DISCIPLINE": 422,
    "ERR_SALESPERSON_DISCIPLINE_BAR": 422,
    "ERR_DEALER_LICENSE_NOT_ACTIVE": 422,
    # --- referential integrity -------------------------------------------
    "ERR_LINE_MAKE_MISMATCH": 422,
    "ERR_FILING_FIELDS_INCONSISTENT": 422,
    "ERR_NOT_INCUMBENT_DEALER": 422,
    "ERR_OUTSIDE_RELEVANT_MARKET": 422,
    "ERR_STUDY_PARTY_MISMATCH": 422,
    "ERR_SALESPERSON_DEALER_MISMATCH": 422,
    # --- temporal ---------------------------------------------------------
    "ERR_NOTICE_PERIOD_TOO_SHORT": 422,
    "ERR_PROTEST_WINDOW_CLOSED": 422,
    "ERR_PROTEST_WINDOW_OPEN": 422,
    "ERR_EFFECTIVE_DATE_NOT_REACHED": 422,
    "ERR_HEARING_OUTSIDE_WINDOW": 422,
    "ERR_HEARING_NOT_REACHED": 422,
    "ERR_EVIDENCE_DEADLINE_PASSED": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_RESPONSE_WINDOW_CLOSED": 422,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 422,
    "ERR_RENEWAL_GRACE_EXPIRED": 422,
    "ERR_TERM_NOT_CONTIGUOUS": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # --- capacity / uniqueness / blocking --------------------------------
    "ERR_HEARING_ROOM_CONFLICT": 409,
    "ERR_ROOM_DAY_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_PROTEST": 409,
    "ERR_DUPLICATE_EXHIBIT_LABEL": 409,
    "ERR_AMENDMENT_LIMIT_REACHED": 409,
    "ERR_RESUBMISSION_LIMIT_REACHED": 409,
    "ERR_ACTIVE_PROTEST_BLOCKS_FINALIZE": 409,
    "ERR_APPEAL_PENDING": 409,
    "ERR_DUPLICATE_LINE_MAKE": 409,
    "ERR_DUPLICATE_ROOM_CODE": 409,
    "ERR_OPEN_APPLICATION_EXISTS": 409,
    "ERR_OPEN_DISPUTE_EXISTS": 409,
    # --- fiscal / evidentiary --------------------------------------------
    "ERR_INSUFFICIENT_RO_SAMPLE": 422,
    "ERR_RATE_NOT_ABOVE_POSTED": 422,
    "ERR_LOSS_REQUIRED_FOR_SANCTION": 422,
    "ERR_SANCTION_TYPE_NOT_ALLOWED": 422,
    "ERR_RESTITUTION_OVERPAYMENT": 422,
    "ERR_NO_PROBATIVE_STUDY": 422,
    "ERR_GOOD_CAUSE_NOT_ESTABLISHED": 422,
}


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize() if words else error_id


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
