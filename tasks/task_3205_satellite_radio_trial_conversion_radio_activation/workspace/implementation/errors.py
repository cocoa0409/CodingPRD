"""Error classes with scaffold error IDs and HTTP statuses."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="missing or unknown role header, or missing identity for entity-backed role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="role not permitted for endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg="path id does not resolve"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def reference_not_found(msg="body FK reference does not resolve"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def invalid_request(msg="invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg="transition not declared from current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def forbidden_owner(msg="customer-scoped action by non-owner"):
    return ApiError("ERR_FORBIDDEN_OWNER", 403, msg)


def duplicate(msg="uniqueness violation"):
    return ApiError("ERR_DUPLICATE", 409, msg)


def radio_ineligible(msg="radio not eligible for trial"):
    return ApiError("ERR_RADIO_INELIGIBLE", 422, msg)


def hardware_incompatible(msg="plan tier requires newer radio hardware generation"):
    return ApiError("ERR_HARDWARE_INCOMPATIBLE", 422, msg)


def campaign_window(msg="campaign window violation"):
    return ApiError("ERR_CAMPAIGN_WINDOW", 422, msg)


def campaign_overlap(msg="phase-window occupied by another ACTIVE/PAUSED campaign"):
    return ApiError("ERR_CAMPAIGN_OVERLAP", 409, msg)


def offer_sequence_violation(msg="step_up_rank sequencing violated"):
    return ApiError("ERR_OFFER_SEQUENCE_VIOLATION", 422, msg)


def offer_ineligible(msg="offer eligibility failed or per-customer cap reached"):
    return ApiError("ERR_OFFER_INELIGIBLE", 422, msg)


def save_cap_reached(msg="third save-offer accept in the same term"):
    return ApiError("ERR_SAVE_CAP_REACHED", 422, msg)


def renewal_disclosure_required(msg="regulatory disclosure missing/late"):
    return ApiError("ERR_RENEWAL_DISCLOSURE_REQUIRED", 422, msg)


def signal_exhausted_block(msg="suspend/immediate-cancel blocked by EXHAUSTED signal"):
    return ApiError("ERR_SIGNAL_EXHAUSTED_BLOCK", 409, msg)


def stale_version(msg="expected version mismatch"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def dealer_not_enrolled(msg="dealer not enrolled in used program"):
    return ApiError("ERR_DEALER_NOT_ENROLLED", 422, msg)


def trial_plan_required(msg="endpoint requires plan.is_trial == true"):
    return ApiError("ERR_TRIAL_PLAN_REQUIRED", 422, msg)


def paid_plan_required(msg="endpoint requires plan.is_trial == false"):
    return ApiError("ERR_PAID_PLAN_REQUIRED", 422, msg)
