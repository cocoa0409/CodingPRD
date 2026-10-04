"""Error catalog (PRD section 5 / scaffold errors table).

Every error_id the API can return, with its HTTP status. ApiError carries
error_id + message + http_status through to the envelope error handler.
"""

ERROR_STATUS = {
    # auth / identity (families 1-3)
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FACTORY_OWNERSHIP_MISMATCH": 403,
    "ERR_BUYER_REF_MISMATCH": 403,
    "ERR_SELF_ATTESTATION_FORBIDDEN": 403,
    # existence (family 4)
    "ERR_FACTORY_NOT_FOUND": 404,
    "ERR_MODEL_NOT_FOUND": 404,
    "ERR_COMPONENT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_DOC_NOT_FOUND": 404,
    "ERR_WORKER_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    # request schema / simple semantics (family 5)
    "ERR_INVALID_REQUEST": 400,
    "ERR_DOC_LINK_AMBIGUOUS": 400,
    "ERR_CLOCK_REGRESSION": 400,
    # state (family 6)
    "ERR_INVALID_STATE": 409,
    "ERR_FACTORY_NOT_ACTIVE": 409,
    "ERR_MODEL_NOT_ACTIVE": 409,
    "ERR_REPORT_NOT_CERTIFIED": 409,
    "ERR_REPORT_NOT_ACTIVE": 409,
    "ERR_RUN_NOT_COMPLETED": 409,
    "ERR_RUN_NOT_READY": 409,
    "ERR_ALLOCATION_NOT_LOCKED": 409,
    "ERR_WORKER_NOT_ACTIVE": 409,
    # regulatory / compliance (family 7)
    "ERR_CONTENT_THRESHOLD_NOT_MET": 422,
    "ERR_BERRY_CONTENT_NOT_PROVEN": 422,
    "ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY": 422,
    "ERR_POLICY_FORBIDS_IMPORT": 422,
    "ERR_POLICY_FORBIDS_DOMESTIC": 422,
    "ERR_POLICY_NOT_DOMESTIC_ONLY": 422,
    "ERR_FACTORY_NOT_CLEARED": 422,
    "ERR_CUSTOM_REQUIRES_DOMESTIC": 422,
    # temporal (family 8)
    "ERR_LINE_WINDOW_CONFLICT": 409,
    "ERR_GOV_CONTRACT_WINDOW_CONFLICT": 409,
    "ERR_EVIDENCE_STALE": 422,
    # structural (family 9)
    "ERR_MATERIAL_SHORTAGE": 409,
    "ERR_DOMESTIC_MATERIAL_SHORTAGE": 409,
    "ERR_WORKFORCE_SHORTFALL": 422,
    "ERR_STYLE_CODE_EXISTS": 409,
    "ERR_CONTRACT_NUMBER_EXISTS": 409,
    "ERR_CLAIM_ALREADY_EXISTS": 409,
    "ERR_ALLOCATION_ALREADY_EXISTS": 409,
    "ERR_ENROLLMENT_ALREADY_OPEN": 409,
    "ERR_REPORT_MODEL_MISMATCH": 422,
    "ERR_MODEL_MISMATCH": 422,
    "ERR_NOT_A_CUSTOM_RUN": 422,
    "ERR_MODEL_HAS_OPEN_RUNS": 409,
    "ERR_MODEL_HAS_PUBLISHED_CLAIMS": 409,
    # referential evidence (family 10)
    "ERR_REQUIRED_EVIDENCE_MISSING": 422,
    # fiscal / pool arithmetic (family 11)
    "ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY": 422,
    "ERR_CAPACITY_WEEK_EXCEEDED": 422,
    "ERR_RUN_ORDER_CAPACITY_EXCEEDED": 422,
    "ERR_SHIFT_EXCEEDS_SOURCE": 422,
    "ERR_SHIFT_BELOW_CONSUMED": 422,
    "ERR_WEEK_RUNS_OPEN": 409,
    # optimistic concurrency (family 12)
    "ERR_STALE_RUN_VERSION": 412,
    "ERR_STALE_ALLOCATION_VERSION": 412,
    # framework-level fallbacks (not in the PRD catalogue; unreachable via
    # declared endpoints, used for unknown paths / methods / crashes)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        if http_status is not None:
            self.http_status = http_status
        else:
            self.http_status = ERROR_STATUS[error_id]
