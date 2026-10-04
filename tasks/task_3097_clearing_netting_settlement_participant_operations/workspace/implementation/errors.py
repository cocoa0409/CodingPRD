"""Error catalogue and the exception type that carries an API error.

Error ids and HTTP statuses are taken verbatim from SCAFFOLD.yaml section 1.6
and PRD section 5.
"""


class ApiError(Exception):
    """An error the API surfaces using the standard error envelope."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- auth -------------------------------------------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)

# --- existence --------------------------------------------------------------
ERR_RESOURCE_NOT_FOUND = ("ERR_RESOURCE_NOT_FOUND", 404)
ERR_PARTICIPANT_NOT_FOUND = ("ERR_PARTICIPANT_NOT_FOUND", 404)
ERR_SECURITY_NOT_FOUND = ("ERR_SECURITY_NOT_FOUND", 404)
ERR_WINDOW_NOT_FOUND = ("ERR_WINDOW_NOT_FOUND", 404)

# --- state / business safety ------------------------------------------------
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_PARTICIPANT_NOT_ACTIVE = ("ERR_PARTICIPANT_NOT_ACTIVE", 409)
ERR_FINANCIAL_STANDARD_NOT_MET = ("ERR_FINANCIAL_STANDARD_NOT_MET", 409)
ERR_SEGREGATED_CUSTODY_REQUIRED = ("ERR_SEGREGATED_CUSTODY_REQUIRED", 409)
ERR_SELF_TRADE_FORBIDDEN = ("ERR_SELF_TRADE_FORBIDDEN", 409)
ERR_NOT_MATCHED = ("ERR_NOT_MATCHED", 409)
ERR_SHORT_POSITION_ADJUSTMENT = ("ERR_SHORT_POSITION_ADJUSTMENT", 409)
ERR_TRADE_ENTRY_DEADLINE_PASSED = ("ERR_TRADE_ENTRY_DEADLINE_PASSED", 409)
ERR_AFFIRMATION_DEADLINE_PASSED = ("ERR_AFFIRMATION_DEADLINE_PASSED", 409)
ERR_ACTION_NOT_EFFECTIVE = ("ERR_ACTION_NOT_EFFECTIVE", 409)
ERR_WINDOW_ALREADY_NETTED = ("ERR_WINDOW_ALREADY_NETTED", 409)
ERR_WINDOW_HAS_ACTIVE_FAILS = ("ERR_WINDOW_HAS_ACTIVE_FAILS", 409)
ERR_EMPTY_NET_POSITION_SET = ("ERR_EMPTY_NET_POSITION_SET", 409)
ERR_OBLIGATION_UNDERFUNDED = ("ERR_OBLIGATION_UNDERFUNDED", 409)
ERR_FUNDING_EXCEEDS_OBLIGATION = ("ERR_FUNDING_EXCEEDS_OBLIGATION", 409)
ERR_INSUFFICIENT_DEPOSIT = ("ERR_INSUFFICIENT_DEPOSIT", 409)
ERR_DEPOSIT_RELEASE_INVALID = ("ERR_DEPOSIT_RELEASE_INVALID", 409)
ERR_FUND_ALREADY_RECOMPUTED = ("ERR_FUND_ALREADY_RECOMPUTED", 409)
ERR_CLEARING_FUND_DEFICIT = ("ERR_CLEARING_FUND_DEFICIT", 409)
ERR_NO_ALLOCATABLE_DEFICIT = ("ERR_NO_ALLOCATABLE_DEFICIT", 409)
ERR_PROCEEDING_NOT_LIQUIDATING = ("ERR_PROCEEDING_NOT_LIQUIDATING", 409)
ERR_DISPUTE_RESOLUTION_NOT_OWNER = ("ERR_DISPUTE_RESOLUTION_NOT_OWNER", 403)
ERR_NOT_ALL_PARTICIPANTS_ACTIVE = ("ERR_NOT_ALL_PARTICIPANTS_ACTIVE", 409)

# --- request-shape / concurrency --------------------------------------------
ERR_AFFIRMATION_DEADLINE_ORDER = ("ERR_AFFIRMATION_DEADLINE_ORDER", 422)
ERR_INVALID_AMOUNT = ("ERR_INVALID_AMOUNT", 422)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_IMMUTABLE_FIELD = ("ERR_IMMUTABLE_FIELD", 422)
ERR_WINDOW_DEADLINE_REGRESSION = ("ERR_WINDOW_DEADLINE_REGRESSION", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)

MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-Role header is missing or does not name a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted for this operation.",
    "ERR_RESOURCE_NOT_FOUND": "The resource named in the path does not exist.",
    "ERR_PARTICIPANT_NOT_FOUND": "The referenced participant does not exist.",
    "ERR_SECURITY_NOT_FOUND": "The referenced security does not exist.",
    "ERR_WINDOW_NOT_FOUND": "No open settlement window exists for the trade's security and settlement date.",
    "ERR_INVALID_STATE": "The target resource is not in the state the requested operation requires.",
    "ERR_PARTICIPANT_NOT_ACTIVE": "The participant is not in an ACTIVE membership standing.",
    "ERR_FINANCIAL_STANDARD_NOT_MET": "The participant's financial standard status is FAIL.",
    "ERR_SEGREGATED_CUSTODY_REQUIRED": "The participant holds no SEGREGATED custody account.",
    "ERR_SELF_TRADE_FORBIDDEN": "A participant may not trade with itself.",
    "ERR_NOT_MATCHED": "The trade's match status is not MATCHED.",
    "ERR_SHORT_POSITION_ADJUSTMENT": "The corporate action would service a short quantity under a rule that forbids it.",
    "ERR_TRADE_ENTRY_DEADLINE_PASSED": "The trade date is at or after the settlement window's trade entry deadline.",
    "ERR_AFFIRMATION_DEADLINE_PASSED": "The logical clock is at or after the window's affirmation deadline.",
    "ERR_AFFIRMATION_DEADLINE_ORDER": "affirmation_deadline must be strictly after trade_entry_deadline.",
    "ERR_ACTION_NOT_EFFECTIVE": "The corporate action's effective date is after the settlement date of a window it would service.",
    "ERR_WINDOW_ALREADY_NETTED": "The settlement window is no longer OPEN.",
    "ERR_WINDOW_HAS_ACTIVE_FAILS": "The window has a FAILED net position owned by an ACTIVE participant.",
    "ERR_EMPTY_NET_POSITION_SET": "The window has no net position rows.",
    "ERR_OBLIGATION_UNDERFUNDED": "A net position has not been funded to its settlement obligation.",
    "ERR_FUNDING_EXCEEDS_OBLIGATION": "The funding posting would push funded_amount_cents above settlement_obligation_cents.",
    "ERR_INVALID_AMOUNT": "The supplied monetary amount is zero or violates its sign rule.",
    "ERR_INSUFFICIENT_DEPOSIT": "The posted deposit balance is below the participant's outstanding obligations.",
    "ERR_DEPOSIT_RELEASE_INVALID": "The release lacks a reason code or would drive the posted balance below zero.",
    "ERR_FUND_ALREADY_RECOMPUTED": "The clearing fund was already recomputed with no intervening new net position.",
    "ERR_CLEARING_FUND_DEFICIT": "The candidate component balances cannot cover the loss allocation.",
    "ERR_NO_ALLOCATABLE_DEFICIT": "The default proceeding carries no positive deficit to allocate.",
    "ERR_PROCEEDING_NOT_LIQUIDATING": "The default proceeding is not in the state this operation requires.",
    "ERR_DISPUTE_RESOLUTION_NOT_OWNER": "The dispute resolution must be requested against the lower participant id of the pair.",
    "ERR_STALE_VERSION": "The supplied version does not equal the parent entity's current version.",
    "ERR_IMMUTABLE_FIELD": "The update supplies a field that is immutable after creation.",
    "ERR_WINDOW_DEADLINE_REGRESSION": "The timeline update would regress the window's deadlines.",
    "ERR_INVALID_REQUEST": "A required input field is missing, mistyped, or an unknown field was supplied.",
    "ERR_NOT_ALL_PARTICIPANTS_ACTIVE": "No participant with membership_status == ACTIVE remains.",
    "ERR_INVALID_STATE_AUTO_CLOSE": "Automatic window close condition.",
}


def api_error(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple."""
    error_id, status = spec
    return ApiError(error_id, message or MESSAGES.get(error_id, error_id), status)