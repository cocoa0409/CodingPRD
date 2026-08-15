"""Error classes and error ID constants for the fraud ops API."""


class ApiError(Exception):
    """Exception carrying error_id, message, and http_status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error IDs (from scaffold §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"
ERR_THRESHOLD_ORDER_INVALID = "ERR_THRESHOLD_ORDER_INVALID"
ERR_ACCOUNT_NOT_ACTIVE = "ERR_ACCOUNT_NOT_ACTIVE"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CHARGEBACK_INVALID_STATE = "ERR_CHARGEBACK_INVALID_STATE"
ERR_NO_ACTIVE_RULESET = "ERR_NO_ACTIVE_RULESET"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_CARD_COMPROMISED = "ERR_CARD_COMPROMISED"
ERR_DECISION_EXPOSURE_REQUIRES_MANAGER = "ERR_DECISION_EXPOSURE_REQUIRES_MANAGER"
ERR_REOPEN_LIMIT_EXCEEDED = "ERR_REOPEN_LIMIT_EXCEEDED"
ERR_TRAVEL_NOTICE_OVERLAP = "ERR_TRAVEL_NOTICE_OVERLAP"
ERR_CONTACT_TOO_SOON = "ERR_CONTACT_TOO_SOON"
ERR_FINALIZE_WINDOW_EXPIRED = "ERR_FINALIZE_WINDOW_EXPIRED"
ERR_DUPLICATE_EVENT = "ERR_DUPLICATE_EVENT"
ERR_CHARGEBACK_EXISTS = "ERR_CHARGEBACK_EXISTS"
ERR_TXN_NOT_DISPUTABLE = "ERR_TXN_NOT_DISPUTABLE"
ERR_TXN_ALREADY_IN_LOSS = "ERR_TXN_ALREADY_IN_LOSS"
ERR_LOSS_TXN_NOT_CONFIRMED = "ERR_LOSS_TXN_NOT_CONFIRMED"
ERR_CONTACT_REQUIRED = "ERR_CONTACT_REQUIRED"
ERR_CHARGEBACK_PENDING = "ERR_CHARGEBACK_PENDING"
ERR_DUPLICATE_CREDIT = "ERR_DUPLICATE_CREDIT"
ERR_FINAL_AMOUNT_TOLERANCE = "ERR_FINAL_AMOUNT_TOLERANCE"
ERR_RECOVERY_EXCEEDS_OUTSTANDING = "ERR_RECOVERY_EXCEEDS_OUTSTANDING"
ERR_RING_THRESHOLD_NOT_MET = "ERR_RING_THRESHOLD_NOT_MET"


def err_unauthenticated(msg="Missing or unknown X-User-Role or missing X-User-ID"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def err_forbidden_role(msg="Role not permitted on this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, msg, 403)


def err_not_resource_owner(msg="Cardholder does not own the target resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def err_invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def err_invalid_window(msg="Window start must be strictly before window end"):
    return ApiError(ERR_INVALID_WINDOW, msg, 422)


def err_threshold_order_invalid(msg="review_threshold must be strictly less than decline_threshold"):
    return ApiError(ERR_THRESHOLD_ORDER_INVALID, msg, 422)


def err_account_not_active(msg="Account is not ACTIVE"):
    return ApiError(ERR_ACCOUNT_NOT_ACTIVE, msg, 409)


def err_invalid_state(msg="Invalid state for this operation"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def err_chargeback_invalid_state(msg="Chargeback transition invalid from current status"):
    return ApiError(ERR_CHARGEBACK_INVALID_STATE, msg, 409)


def err_no_active_ruleset(msg="No ACTIVE ruleset covers the card's scope"):
    return ApiError(ERR_NO_ACTIVE_RULESET, msg, 409)


def err_stale_version(msg="expected_ruleset_version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def err_segregation_of_duties(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, msg, 403)


def err_card_compromised(msg="Card is COMPROMISED with no DECLINED ReissueDecision"):
    return ApiError(ERR_CARD_COMPROMISED, msg, 409)


def err_decision_exposure_requires_manager(msg="High-exposure decline requires FraudOpsManager"):
    return ApiError(ERR_DECISION_EXPOSURE_REQUIRES_MANAGER, msg, 403)


def err_reopen_limit_exceeded(msg="Alert reopen limit exceeded"):
    return ApiError(ERR_REOPEN_LIMIT_EXCEEDED, msg, 409)


def err_travel_notice_overlap(msg="Travel notice overlaps an existing ACTIVE notice"):
    return ApiError(ERR_TRAVEL_NOTICE_OVERLAP, msg, 409)


def err_contact_too_soon(msg="Contact created within 60 minutes of the account's most recent contact"):
    return ApiError(ERR_CONTACT_TOO_SOON, msg, 409)


def err_finalize_window_expired(msg="Loss finalize attempted after booked_at + 30 days"):
    return ApiError(ERR_FINALIZE_WINDOW_EXPIRED, msg, 409)


def err_duplicate_event(msg="event_reference already registered"):
    return ApiError(ERR_DUPLICATE_EVENT, msg, 409)


def err_chargeback_exists(msg="A non-terminal chargeback already exists for the transaction"):
    return ApiError(ERR_CHARGEBACK_EXISTS, msg, 409)


def err_txn_not_disputable(msg="Transaction decision is not APPROVE"):
    return ApiError(ERR_TXN_NOT_DISPUTABLE, msg, 409)


def err_txn_already_in_loss(msg="Transaction already covered by a non-terminal loss"):
    return ApiError(ERR_TXN_ALREADY_IN_LOSS, msg, 409)


def err_loss_txn_not_confirmed(msg="Loss transaction is not CONFIRMED_FRAUD or does not belong to the account"):
    return ApiError(ERR_LOSS_TXN_NOT_CONFIRMED, msg, 422)


def err_contact_required(msg="Alert resolution requires a matching COMPLETED contact"):
    return ApiError(ERR_CONTACT_REQUIRED, msg, 409)


def err_chargeback_pending(msg="A covered transaction has a pending chargeback"):
    return ApiError(ERR_CHARGEBACK_PENDING, msg, 409)


def err_duplicate_credit(msg="Duplicate-credit cap exceeded"):
    return ApiError(ERR_DUPLICATE_CREDIT, msg, 422)


def err_final_amount_tolerance(msg="Final amount outside tolerance"):
    return ApiError(ERR_FINAL_AMOUNT_TOLERANCE, msg, 422)


def err_recovery_exceeds_outstanding(msg="Claimed/paid amount exceeds loss outstanding"):
    return ApiError(ERR_RECOVERY_EXCEEDS_OUTSTANDING, msg, 422)


def err_ring_threshold_not_met(msg="Fewer than 3 qualifying accounts"):
    return ApiError(ERR_RING_THRESHOLD_NOT_MET, msg, 409)
