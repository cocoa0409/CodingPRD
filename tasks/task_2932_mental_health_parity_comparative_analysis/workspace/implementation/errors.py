"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# Every error id in the PRD section 5 catalogue with its HTTP status.
ERROR_STATUS = {
    # --- authentication / authorization ---
    "ERR_MISSING_IDENTITY_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    # --- existence ---
    "ERR_ADMINISTRATOR_NOT_FOUND": 404,
    "ERR_PLAN_YEAR_NOT_FOUND": 404,
    "ERR_CLASSIFICATION_NOT_FOUND": 404,
    "ERR_NQTL_ITEM_NOT_FOUND": 404,
    "ERR_ANALYSIS_NOT_FOUND": 404,
    "ERR_VENDOR_REQUEST_NOT_FOUND": 404,
    "ERR_DATA_SUBMISSION_NOT_FOUND": 404,
    "ERR_CAP_NOT_FOUND": 404,
    "ERR_REGULATOR_REQUEST_NOT_FOUND": 404,
    # --- payload shape / field level ---
    "ERR_VALIDATION": 422,
    "ERR_NETWORK_TIER_MISMATCH": 422,
    "ERR_SUB_CLASSIFICATION_MISMATCH": 422,
    "ERR_MEASUREMENT_PERIOD_INVALID": 422,
    "ERR_DENIALS_EXCEED_CLAIMS": 422,
    "ERR_SUBMISSION_TYPE_NOT_REQUESTED": 422,
    "ERR_INSUFFICIENT_COMPARATIVE_ANALYSIS": 422,
    "ERR_EMPTY_TEST_POPULATION": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # --- referential coherence ---
    "ERR_CROSS_PLAN_YEAR_REFERENCE": 409,
    "ERR_ANALYSIS_ALREADY_SUPERSEDED": 409,
    # --- plan-year gating ---
    "ERR_PLAN_YEAR_CLOSED": 409,
    "ERR_PLAN_YEAR_NOT_OPEN": 409,
    # --- transition guards ---
    "ERR_ANALYSIS_NOT_DRAFT": 409,
    "ERR_ANALYSIS_NOT_SUBMITTED": 409,
    "ERR_ANALYSIS_NOT_INSUFFICIENT": 409,
    "ERR_ITEM_NOT_AWAITING_DETERMINATION": 409,
    "ERR_ITEM_NOT_IN_VIOLATION": 409,
    "ERR_CAP_NOT_DRAFT": 409,
    "ERR_CAP_NOT_APPROVED": 409,
    "ERR_REGULATOR_REQUEST_NOT_OPEN": 409,
    "ERR_REGULATOR_REQUEST_NOT_RESPONDED": 409,
    "ERR_ESCALATION_ALREADY_DECLARED": 409,
    "ERR_REQUEST_ALREADY_FULFILLED": 409,
    "ERR_PRODUCTION_WINDOW_CLOSED": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_PLAN_YEAR_VERSION": 412,
    "ERR_STALE_NQTL_ITEM_VERSION": 412,
    # --- safety / compliance ---
    "ERR_SELF_CERTIFICATION": 409,
    "ERR_APPROVER_IS_DETERMINER": 409,
    "ERR_IN_OPERATION_DATA_MISSING": 409,
    "ERR_ANALYSIS_NOT_CERTIFIED": 409,
    "ERR_STRINGENCY_CONTRADICTS_EVIDENCE": 409,
    "ERR_MH_BENEFITS_NOT_COVERED": 409,
    "ERR_DUPLICATE_NQTL_ITEM": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    # --- temporal ---
    "ERR_MEASUREMENT_PERIOD_OVERLAP": 409,
    "ERR_PRODUCTION_WINDOW_OVERLAP": 409,
    "ERR_NOT_YET_OVERDUE": 409,
    "ERR_RESPONSE_WINDOW_EXPIRED": 409,
    "ERR_NO_REQUESTED_ITEMS": 409,
    # --- fiscal ---
    "ERR_LIABILITY_CAP_EXCEEDED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_IDENTITY_HEADERS": "X-User-ID and X-User-Role headers are required and must be non-empty.",
    "ERR_UNKNOWN_ROLE": "X-User-Role must be one of PlanSponsor, Administrator, ComplianceOfficer, Regulator.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to invoke this operation.",
    "ERR_ADMINISTRATOR_NOT_FOUND": "No administrator exists with the supplied identifier.",
    "ERR_PLAN_YEAR_NOT_FOUND": "No plan year exists with the supplied identifier.",
    "ERR_CLASSIFICATION_NOT_FOUND": "No benefit classification exists with the supplied identifier.",
    "ERR_NQTL_ITEM_NOT_FOUND": "No NQTL item exists with the supplied identifier.",
    "ERR_ANALYSIS_NOT_FOUND": "No comparative analysis exists with the supplied identifier.",
    "ERR_VENDOR_REQUEST_NOT_FOUND": "No vendor data request exists with the supplied identifier.",
    "ERR_DATA_SUBMISSION_NOT_FOUND": "No data submission exists with the supplied identifier.",
    "ERR_CAP_NOT_FOUND": "No corrective action plan exists with the supplied identifier.",
    "ERR_REGULATOR_REQUEST_NOT_FOUND": "No regulator request exists with the supplied identifier.",
    "ERR_VALIDATION": "The request payload failed shape validation.",
    "ERR_NETWORK_TIER_MISMATCH": "network_tier does not agree with benefit_category.",
    "ERR_SUB_CLASSIFICATION_MISMATCH": "sub_classification does not agree with benefit_category.",
    "ERR_MEASUREMENT_PERIOD_INVALID": "measurement_period_end is earlier than measurement_period_start.",
    "ERR_DENIALS_EXCEED_CLAIMS": "Denial counts may not exceed the adjudicated claim counts.",
    "ERR_SUBMISSION_TYPE_NOT_REQUESTED": "submission_type was not requested by the owning vendor data request.",
    "ERR_INSUFFICIENT_COMPARATIVE_ANALYSIS": "The comparative analysis documentation is not minimally complete.",
    "ERR_EMPTY_TEST_POPULATION": "The substantially-all denominator is zero under the requested basis.",
    "ERR_CLOCK_NOT_MONOTONIC": "current_utc must be strictly later than the current logical clock value.",
    "ERR_CROSS_PLAN_YEAR_REFERENCE": "The foreign-key combination spans two plan years.",
    "ERR_ANALYSIS_ALREADY_SUPERSEDED": "The named analysis is no longer supersedable.",
    "ERR_PLAN_YEAR_CLOSED": "The owning plan year is CLOSED.",
    "ERR_PLAN_YEAR_NOT_OPEN": "The owning plan year is not OPEN.",
    "ERR_ANALYSIS_NOT_DRAFT": "The comparative analysis is not in DRAFT.",
    "ERR_ANALYSIS_NOT_SUBMITTED": "The comparative analysis is not in SUBMITTED.",
    "ERR_ANALYSIS_NOT_INSUFFICIENT": "The comparative analysis is not in INSUFFICIENT.",
    "ERR_ITEM_NOT_AWAITING_DETERMINATION": "The NQTL item is not in a state that admits this determination.",
    "ERR_ITEM_NOT_IN_VIOLATION": "The owning NQTL item is not in VIOLATION.",
    "ERR_CAP_NOT_DRAFT": "The corrective action plan is not in DRAFT.",
    "ERR_CAP_NOT_APPROVED": "The corrective action plan is not in APPROVED.",
    "ERR_REGULATOR_REQUEST_NOT_OPEN": "The regulator request is not awaiting a response.",
    "ERR_REGULATOR_REQUEST_NOT_RESPONDED": "The regulator request is not in RESPONDED.",
    "ERR_ESCALATION_ALREADY_DECLARED": "A breach has already been declared on this request.",
    "ERR_REQUEST_ALREADY_FULFILLED": "The vendor data request has already been fulfilled.",
    "ERR_PRODUCTION_WINDOW_CLOSED": "The production window is closed following a declared breach.",
    "ERR_STALE_PLAN_YEAR_VERSION": "expected_plan_year_version does not match the plan year's current version.",
    "ERR_STALE_NQTL_ITEM_VERSION": "expected_nqtl_item_version does not match the NQTL item's current version.",
    "ERR_SELF_CERTIFICATION": "The author of a comparative analysis may not review it.",
    "ERR_APPROVER_IS_DETERMINER": "The officer who determined the violation may not decide the remedy.",
    "ERR_IN_OPERATION_DATA_MISSING": "Certification requires a VALIDATED DENIAL_RATES submission for the classification.",
    "ERR_ANALYSIS_NOT_CERTIFIED": "The item's latest non-withdrawn comparative analysis is not CERTIFIED.",
    "ERR_STRINGENCY_CONTRADICTS_EVIDENCE": "The determination outcome contradicts the recomputed stringency evidence.",
    "ERR_MH_BENEFITS_NOT_COVERED": "The classification does not cover MH/SUD benefits.",
    "ERR_DUPLICATE_NQTL_ITEM": "A live NQTL item already exists for this plan year, classification and type.",
    "ERR_REVISION_LIMIT_REACHED": "The comparative analysis has exhausted its revision rounds.",
    "ERR_MEASUREMENT_PERIOD_OVERLAP": "The measurement period collides with an existing period.",
    "ERR_PRODUCTION_WINDOW_OVERLAP": "The production window collides with a live request's window.",
    "ERR_NOT_YET_OVERDUE": "The escalation is not yet ripe.",
    "ERR_RESPONSE_WINDOW_EXPIRED": "The regulator response window has expired.",
    "ERR_NO_REQUESTED_ITEMS": "The regulator's demand matches no inventoried NQTL item.",
    "ERR_LIABILITY_CAP_EXCEEDED": "Approval would push the plan year above its remediation liability cap.",
}
