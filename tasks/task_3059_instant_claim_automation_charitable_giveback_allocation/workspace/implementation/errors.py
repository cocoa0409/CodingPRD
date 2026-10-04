"""Error classes and helpers."""


class APIError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_invalid_request(msg="Malformed request body"):
    return APIError("ERR_INVALID_REQUEST", msg, 400)


def err_unauthenticated(msg="X-User-Role header missing or not a declared role"):
    return APIError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted or ownership check failed"):
    return APIError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource not found"):
    return APIError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg="Resource not in a legal from-state"):
    return APIError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="Stale version"):
    return APIError("ERR_STALE_VERSION", msg, 412)


def err_filing_not_submitted(msg="Filing not in SUBMITTED"):
    return APIError("ERR_FILING_NOT_SUBMITTED", msg, 409)


def err_rate_filing_not_approved(msg="Referenced filing not APPROVED"):
    return APIError("ERR_RATE_FILING_NOT_APPROVED", msg, 422)


def err_flat_fee_violates_filing(msg="Fee violates filing cap"):
    return APIError("ERR_FLAT_FEE_VIOLATES_FILING", msg, 422)


def err_fee_config_already_active(msg="Another ACTIVE FeeConfig exists for state"):
    return APIError("ERR_FEE_CONFIG_ALREADY_ACTIVE", msg, 409)


def err_fee_config_not_found(msg="No ACTIVE FeeConfig for state"):
    return APIError("ERR_FEE_CONFIG_NOT_FOUND", msg, 422)


def err_treaty_in_use(msg="Treaty attached to a cohort"):
    return APIError("ERR_TREATY_IN_USE", msg, 409)


def err_cohort_not_open(msg="No OPEN cohort for bind year"):
    return APIError("ERR_COHORT_NOT_OPEN", msg, 422)


def err_cohort_closed(msg="Cohort not OPEN"):
    return APIError("ERR_COHORT_CLOSED", msg, 409)


def err_cohort_not_closed(msg="Cohort not CLOSED"):
    return APIError("ERR_COHORT_NOT_CLOSED", msg, 409)


def err_quote_expired(msg="Quote expired"):
    return APIError("ERR_QUOTE_EXPIRED", msg, 422)


def err_policyholder_debarred(msg="Policyholder debarred"):
    return APIError("ERR_POLICYHOLDER_DEBARRED", msg, 422)


def err_application_auto_decline_required(msg="Behavioral signals >= hard threshold"):
    return APIError("ERR_APPLICATION_AUTO_DECLINE_REQUIRED", msg, 422)


def err_policy_not_active(msg="Policy not ACTIVE"):
    return APIError("ERR_POLICY_NOT_ACTIVE", msg, 409)


def err_premium_already_paid(msg="No premium outstanding"):
    return APIError("ERR_PREMIUM_ALREADY_PAID", msg, 422)


def err_appeal_window_closed(msg="Appeal window closed"):
    return APIError("ERR_APPEAL_WINDOW_CLOSED", msg, 422)


def err_appeal_limit_reached(msg="Appeal limit reached"):
    return APIError("ERR_APPEAL_LIMIT_REACHED", msg, 409)


def err_segregation_of_duties(msg="Reviewer must differ from original denier"):
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 422)


def err_cause_not_active(msg="Cause not ACTIVE"):
    return APIError("ERR_CAUSE_NOT_ACTIVE", msg, 422)


def err_lapse_grace_not_elapsed(msg="Lapse grace period not elapsed"):
    return APIError("ERR_LAPSE_GRACE_NOT_ELAPSED", msg, 409)
