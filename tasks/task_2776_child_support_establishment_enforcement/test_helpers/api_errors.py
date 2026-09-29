"""
Error identifier catalogue for the Child Support Enforcement API.

Mirrors the error code catalogue of the PRD one-for-one: every declared
``error_id`` string together with the HTTP status code the PRD binds it to.
Registering the mapping with the framework at import time lets
``validate_error`` cross-check the HTTP status automatically whenever a test
names an expected error id.
"""

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    """Every machine-readable ``error_id`` the API is allowed to answer with."""

    # ---- Authentication and identity -------------------------------------
    MISSING_AUTH_HEADERS = "ERR_MISSING_AUTH_HEADERS"
    INVALID_ROLE = "ERR_INVALID_ROLE"
    UNAUTHORIZED = "ERR_UNAUTHORIZED"
    NOT_CASE_PARTY = "ERR_NOT_CASE_PARTY"
    NOT_IWO_EMPLOYER = "ERR_NOT_IWO_EMPLOYER"
    SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

    # ---- Path-variable and body foreign-key resolution -------------------
    CASE_NOT_FOUND = "ERR_CASE_NOT_FOUND"
    PARTICIPANT_NOT_FOUND = "ERR_PARTICIPANT_NOT_FOUND"
    ORDER_NOT_FOUND = "ERR_ORDER_NOT_FOUND"
    PATERNITY_ACTION_NOT_FOUND = "ERR_PATERNITY_ACTION_NOT_FOUND"
    EMPLOYER_NOT_FOUND = "ERR_EMPLOYER_NOT_FOUND"
    IWO_NOT_FOUND = "ERR_IWO_NOT_FOUND"
    CHARGE_NOT_FOUND = "ERR_CHARGE_NOT_FOUND"
    PAYMENT_NOT_FOUND = "ERR_PAYMENT_NOT_FOUND"
    REVIEW_NOT_FOUND = "ERR_REVIEW_NOT_FOUND"
    ENFORCEMENT_ACTION_NOT_FOUND = "ERR_ENFORCEMENT_ACTION_NOT_FOUND"
    REFERRAL_NOT_FOUND = "ERR_REFERRAL_NOT_FOUND"
    OFFER_NOT_FOUND = "ERR_OFFER_NOT_FOUND"
    REFERENCED_ENTITY_NOT_FOUND = "ERR_REFERENCED_ENTITY_NOT_FOUND"

    # ---- Payload schema --------------------------------------------------
    VALIDATION = "ERR_VALIDATION"

    # ---- Optimistic concurrency -----------------------------------------
    STALE_ORDER_VERSION = "ERR_STALE_ORDER_VERSION"
    STALE_CASE_VERSION = "ERR_STALE_CASE_VERSION"

    # ---- State preconditions --------------------------------------------
    INVALID_CASE_STATUS = "ERR_INVALID_CASE_STATUS"
    INVALID_ORDER_STATUS = "ERR_INVALID_ORDER_STATUS"
    INVALID_PATERNITY_STATUS = "ERR_INVALID_PATERNITY_STATUS"
    INVALID_IWO_STATUS = "ERR_INVALID_IWO_STATUS"
    INVALID_REVIEW_STATUS = "ERR_INVALID_REVIEW_STATUS"
    INVALID_ACTION_STATUS = "ERR_INVALID_ACTION_STATUS"
    INVALID_REFERRAL_STATUS = "ERR_INVALID_REFERRAL_STATUS"
    INVALID_OFFER_STATUS = "ERR_INVALID_OFFER_STATUS"

    # ---- Safety and compliance ------------------------------------------
    GOOD_CAUSE_BARS_DISCLOSURE = "ERR_GOOD_CAUSE_BARS_DISCLOSURE"
    PATERNITY_NOT_ESTABLISHED = "ERR_PATERNITY_NOT_ESTABLISHED"

    # ---- Referential -----------------------------------------------------
    PARTY_ROLE_MISMATCH = "ERR_PARTY_ROLE_MISMATCH"
    TANF_FLAG_MISMATCH = "ERR_TANF_FLAG_MISMATCH"
    NCP_NOT_LOCATED = "ERR_NCP_NOT_LOCATED"
    NO_CONTROLLING_ORDER_JURISDICTION = "ERR_NO_CONTROLLING_ORDER_JURISDICTION"

    # ---- Temporal --------------------------------------------------------
    RESCISSION_WINDOW_CLOSED = "ERR_RESCISSION_WINDOW_CLOSED"
    COLLECTION_APPOINTMENT_NOT_REACHED = "ERR_COLLECTION_APPOINTMENT_NOT_REACHED"
    CONTEST_WINDOW_OPEN = "ERR_CONTEST_WINDOW_OPEN"
    CONTEST_WINDOW_CLOSED = "ERR_CONTEST_WINDOW_CLOSED"
    ORDER_INTERVAL_OVERLAP = "ERR_ORDER_INTERVAL_OVERLAP"
    CHARGE_PERIOD_OVERLAP = "ERR_CHARGE_PERIOD_OVERLAP"
    REVIEW_NOT_YET_ELIGIBLE = "ERR_REVIEW_NOT_YET_ELIGIBLE"
    MODIFICATION_EFFECTIVE_DATE_NOT_LATER = "ERR_MODIFICATION_EFFECTIVE_DATE_NOT_LATER"
    REMITTANCE_NOT_YET_DUE = "ERR_REMITTANCE_NOT_YET_DUE"
    INSTALLMENT_NOT_YET_LATE = "ERR_INSTALLMENT_NOT_YET_LATE"

    # ---- Counting and uniqueness ----------------------------------------
    LOCATE_ATTEMPTS_EXHAUSTED = "ERR_LOCATE_ATTEMPTS_EXHAUSTED"
    RESCISSION_LIMIT = "ERR_RESCISSION_LIMIT"
    SPECIMEN_REJECTION_LIMIT = "ERR_SPECIMEN_REJECTION_LIMIT"
    DEVIATION_REJECTION_LIMIT = "ERR_DEVIATION_REJECTION_LIMIT"
    INFO_REQUEST_LIMIT = "ERR_INFO_REQUEST_LIMIT"
    DUPLICATE_PATERNITY_ACTION = "ERR_DUPLICATE_PATERNITY_ACTION"
    DEVIATION_BELOW_MIN_PCT = "ERR_DEVIATION_BELOW_MIN_PCT"
    ACTIVE_OFFER_EXISTS = "ERR_ACTIVE_OFFER_EXISTS"
    OFFER_SUPERSEDED = "ERR_OFFER_SUPERSEDED"
    ENFORCEMENT_STAYED = "ERR_ENFORCEMENT_STAYED"
    ASSIGNED_ARREARS_NOT_COMPROMISABLE = "ERR_ASSIGNED_ARREARS_NOT_COMPROMISABLE"
    COMPROMISE_RISK_TOO_HIGH = "ERR_COMPROMISE_RISK_TOO_HIGH"

    # ---- Fiscal ----------------------------------------------------------
    AGGREGATE_WITHHOLDING_EXCEEDS_CAP = "ERR_AGGREGATE_WITHHOLDING_EXCEEDS_CAP"
    WITHHOLDING_CAP_EXHAUSTED = "ERR_WITHHOLDING_CAP_EXHAUSTED"
    ARREARS_BELOW_ENFORCEMENT_THRESHOLD = "ERR_ARREARS_BELOW_ENFORCEMENT_THRESHOLD"
    ARREARS_BELOW_COMPROMISE_MINIMUM = "ERR_ARREARS_BELOW_COMPROMISE_MINIMUM"
    ARREARS_OUTSTANDING = "ERR_ARREARS_OUTSTANDING"
    CHARGE_PARTIALLY_PAID = "ERR_CHARGE_PARTIALLY_PAID"
    IWO_DEFAULTED = "ERR_IWO_DEFAULTED"
    PAYMENT_BELOW_INSTALLMENT = "ERR_PAYMENT_BELOW_INSTALLMENT"
    OFFER_SNAPSHOT_STALE = "ERR_OFFER_SNAPSHOT_STALE"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


# ---------------------------------------------------------------------------
# error_id -> HTTP status, exactly as the PRD's error catalogue declares it.
# ---------------------------------------------------------------------------

HTTP_STATUS_CODES = {
    # 401
    ApiErrorId.MISSING_AUTH_HEADERS.value: 401,
    ApiErrorId.INVALID_ROLE.value: 401,
    # 403
    ApiErrorId.UNAUTHORIZED.value: 403,
    ApiErrorId.NOT_CASE_PARTY.value: 403,
    ApiErrorId.NOT_IWO_EMPLOYER.value: 403,
    ApiErrorId.SEGREGATION_OF_DUTIES.value: 403,
    # 404
    ApiErrorId.CASE_NOT_FOUND.value: 404,
    ApiErrorId.PARTICIPANT_NOT_FOUND.value: 404,
    ApiErrorId.ORDER_NOT_FOUND.value: 404,
    ApiErrorId.PATERNITY_ACTION_NOT_FOUND.value: 404,
    ApiErrorId.EMPLOYER_NOT_FOUND.value: 404,
    ApiErrorId.IWO_NOT_FOUND.value: 404,
    ApiErrorId.CHARGE_NOT_FOUND.value: 404,
    ApiErrorId.PAYMENT_NOT_FOUND.value: 404,
    ApiErrorId.REVIEW_NOT_FOUND.value: 404,
    ApiErrorId.ENFORCEMENT_ACTION_NOT_FOUND.value: 404,
    ApiErrorId.REFERRAL_NOT_FOUND.value: 404,
    ApiErrorId.OFFER_NOT_FOUND.value: 404,
    ApiErrorId.REFERENCED_ENTITY_NOT_FOUND.value: 404,
    # 422
    ApiErrorId.VALIDATION.value: 422,
    ApiErrorId.PARTY_ROLE_MISMATCH.value: 422,
    ApiErrorId.TANF_FLAG_MISMATCH.value: 422,
    ApiErrorId.MODIFICATION_EFFECTIVE_DATE_NOT_LATER.value: 422,
    ApiErrorId.DEVIATION_BELOW_MIN_PCT.value: 422,
    ApiErrorId.PAYMENT_BELOW_INSTALLMENT.value: 422,
    # 412
    ApiErrorId.STALE_ORDER_VERSION.value: 412,
    ApiErrorId.STALE_CASE_VERSION.value: 412,
    # 409 - state preconditions
    ApiErrorId.INVALID_CASE_STATUS.value: 409,
    ApiErrorId.INVALID_ORDER_STATUS.value: 409,
    ApiErrorId.INVALID_PATERNITY_STATUS.value: 409,
    ApiErrorId.INVALID_IWO_STATUS.value: 409,
    ApiErrorId.INVALID_REVIEW_STATUS.value: 409,
    ApiErrorId.INVALID_ACTION_STATUS.value: 409,
    ApiErrorId.INVALID_REFERRAL_STATUS.value: 409,
    ApiErrorId.INVALID_OFFER_STATUS.value: 409,
    # 409 - safety and compliance
    ApiErrorId.GOOD_CAUSE_BARS_DISCLOSURE.value: 409,
    ApiErrorId.PATERNITY_NOT_ESTABLISHED.value: 409,
    # 409 - referential
    ApiErrorId.NCP_NOT_LOCATED.value: 409,
    ApiErrorId.NO_CONTROLLING_ORDER_JURISDICTION.value: 409,
    # 409 - temporal
    ApiErrorId.RESCISSION_WINDOW_CLOSED.value: 409,
    ApiErrorId.COLLECTION_APPOINTMENT_NOT_REACHED.value: 409,
    ApiErrorId.CONTEST_WINDOW_OPEN.value: 409,
    ApiErrorId.CONTEST_WINDOW_CLOSED.value: 409,
    ApiErrorId.ORDER_INTERVAL_OVERLAP.value: 409,
    ApiErrorId.CHARGE_PERIOD_OVERLAP.value: 409,
    ApiErrorId.REVIEW_NOT_YET_ELIGIBLE.value: 409,
    ApiErrorId.REMITTANCE_NOT_YET_DUE.value: 409,
    ApiErrorId.INSTALLMENT_NOT_YET_LATE.value: 409,
    # 409 - counting and uniqueness
    ApiErrorId.LOCATE_ATTEMPTS_EXHAUSTED.value: 409,
    ApiErrorId.RESCISSION_LIMIT.value: 409,
    ApiErrorId.SPECIMEN_REJECTION_LIMIT.value: 409,
    ApiErrorId.DEVIATION_REJECTION_LIMIT.value: 409,
    ApiErrorId.INFO_REQUEST_LIMIT.value: 409,
    ApiErrorId.DUPLICATE_PATERNITY_ACTION.value: 409,
    ApiErrorId.ACTIVE_OFFER_EXISTS.value: 409,
    ApiErrorId.OFFER_SUPERSEDED.value: 409,
    ApiErrorId.ENFORCEMENT_STAYED.value: 409,
    ApiErrorId.ASSIGNED_ARREARS_NOT_COMPROMISABLE.value: 409,
    ApiErrorId.COMPROMISE_RISK_TOO_HIGH.value: 409,
    # 409 - fiscal
    ApiErrorId.AGGREGATE_WITHHOLDING_EXCEEDS_CAP.value: 409,
    ApiErrorId.WITHHOLDING_CAP_EXHAUSTED.value: 409,
    ApiErrorId.ARREARS_BELOW_ENFORCEMENT_THRESHOLD.value: 409,
    ApiErrorId.ARREARS_BELOW_COMPROMISE_MINIMUM.value: 409,
    ApiErrorId.ARREARS_OUTSTANDING.value: 409,
    ApiErrorId.CHARGE_PARTIALLY_PAID.value: 409,
    ApiErrorId.IWO_DEFAULTED.value: 409,
    ApiErrorId.OFFER_SNAPSHOT_STALE.value: 409,
}

# Register with the framework so validate_error() cross-checks HTTP statuses.
set_error_http_status_map(HTTP_STATUS_CODES)
