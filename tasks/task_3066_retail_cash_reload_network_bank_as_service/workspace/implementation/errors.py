"""Error catalogue for the Retail Cash Reload Network API.

Every error_id and its HTTP status is read verbatim from the scaffold's
error catalogue / the PRD's error code catalogue.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- 401 / 403 ---------------------------------------------------------------
def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def unauthorized(msg="The acting role may not perform this operation."):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def segregation_of_duties(msg="The confirming principal raised or worked this alert."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def retailer_not_party(msg="The acting retailer is not party to the disputed load."):
    return ApiError("ERR_RETAILER_NOT_PARTY", msg, 403)


# --- 404 ---------------------------------------------------------------------
def entity_not_found(msg="A resource identifier in the path does not resolve."):
    return ApiError("ERR_ENTITY_NOT_FOUND", msg, 404)


def referenced_not_found(msg="A body reference does not resolve to a stored row."):
    return ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND", msg, 404)


# --- 400 ---------------------------------------------------------------------
def invalid_request(msg="The request payload is invalid."):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


# --- 409 ---------------------------------------------------------------------
def invalid_state(msg="The resource's current state does not permit this operation."):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def already_terminal(msg="The resource is already in a terminal state."):
    return ApiError("ERR_ALREADY_TERMINAL", msg, 409)


def program_frozen(msg="The parent program's compliance posture is FROZEN."):
    return ApiError("ERR_PROGRAM_FROZEN", msg, 409)


def program_restricted(msg="The parent program's compliance posture is RESTRICTED."):
    return ApiError("ERR_PROGRAM_RESTRICTED", msg, 409)


def posture_transition_blocked(msg="The requested posture move is not eligible at the current posture score."):
    return ApiError("ERR_PROGRAM_POSTURE_TRANSITION_BLOCKED", msg, 409)


def agreement_not_active(msg="The retailer agreement is not ACTIVE."):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", msg, 409)


def account_frozen(msg="The card account's compliance hold dimension is FROZEN."):
    return ApiError("ERR_ACCOUNT_FROZEN", msg, 409)


def aml_alert_pending(msg="A live AML alert references this card account."):
    return ApiError("ERR_AML_ALERT_PENDING", msg, 409)


def location_not_open(msg="The reload location is not OPEN."):
    return ApiError("ERR_LOCATION_NOT_OPEN", msg, 409)


def contract_version_locked(msg="The cited contract version is locked."):
    return ApiError("ERR_CONTRACT_VERSION_LOCKED", msg, 409)


def dispute_response_window_closed(msg="The retailer response deadline has passed."):
    return ApiError("ERR_DISPUTE_RESPONSE_WINDOW_CLOSED", msg, 409)


def settlement_not_settled(msg="The batch is not SETTLED."):
    return ApiError("ERR_SETTLEMENT_NOT_SETTLED", msg, 409)


def settlement_period_overlap(msg="The period overlaps an open batch of the same agreement."):
    return ApiError("ERR_SETTLEMENT_PERIOD_OVERLAP", msg, 409)


def load_outside_settlement_period(msg="The load's funded_at falls outside the batch period."):
    return ApiError("ERR_LOAD_OUTSIDE_SETTLEMENT_PERIOD", msg, 409)


def load_not_reversed(msg="The load is not REVERSED."):
    return ApiError("ERR_LOAD_NOT_REVERSED", msg, 409)


def float_window_overlap(msg="The float window overlaps a non-cancelled window of this location."):
    return ApiError("ERR_FLOAT_WINDOW_OVERLAP", msg, 409)


# --- 412 ---------------------------------------------------------------------
def stale_version(msg="The supplied expected version does not match the current version."):
    return ApiError("ERR_STALE_VERSION", msg, 412)


# --- 422 ---------------------------------------------------------------------
def per_transaction_limit_exceeded(msg="The principal exceeds the effective per-transaction limit."):
    return ApiError("ERR_PER_TRANSACTION_LIMIT_EXCEEDED", msg, 422)


def daily_location_limit_exceeded(msg="The load would push the location past its daily limit."):
    return ApiError("ERR_DAILY_LOCATION_LIMIT_EXCEEDED", msg, 422)


def minimum_load_amount(msg="The principal is below the platform minimum load."):
    return ApiError("ERR_MINIMUM_LOAD_AMOUNT", msg, 422)


def velocity_limit_exceeded(msg="The load would push the account window past a velocity limit."):
    return ApiError("ERR_VELOCITY_LIMIT_EXCEEDED", msg, 422)


def structuring_suspected(msg="The account does not satisfy the structuring predicate."):
    return ApiError("ERR_STRUCTURING_SUSPECTED", msg, 422)


def structuring_band(msg="The structuring band is closed while the account is flagged."):
    return ApiError("ERR_STRUCTURING_BAND", msg, 422)


def brand_onboarding_incomplete(msg="The brand's onboarding checklist is incomplete."):
    return ApiError("ERR_BRAND_ONBOARDING_INCOMPLETE", msg, 422)


def loss_allocation_mismatch(msg="The three allocation shares do not sum to the total loss."):
    return ApiError("ERR_LOSS_ALLOCATION_MISMATCH", msg, 422)


def settlement_empty_period(msg="No FUNDED load falls inside the batch period."):
    return ApiError("ERR_SETTLEMENT_EMPTY_PERIOD", msg, 422)


def float_cap_exceeded(msg="The float position would exceed the float cap."):
    return ApiError("ERR_FLOAT_CAP_EXCEEDED", msg, 422)