"""Error catalog — all 29 error IDs from SCAFFOLD.yaml §1.6 / PRD §5, each with
its pinned HTTP status. Every ERR_* referenced in code is defined exactly once
here; raising an undefined id is a programming error and surfaces loudly."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SUBSTANCE_PROHIBITED": 422,
    "ERR_DISCLOSURE_INSUFFICIENT": 422,
    "ERR_DUPLICATE_CLEARANCE": 409,
    "ERR_AUDIT_SCORE_INSUFFICIENT": 409,
    "ERR_CONVERTER_NOT_AUTHORIZED": 409,
    "ERR_AUTHORIZATION_WINDOW_OVERLAP": 409,
    "ERR_AUTHORIZATION_CAPABILITY_MISMATCH": 422,
    "ERR_AGREEMENT_WINDOW_OVERLAP": 409,
    "ERR_AGREEMENT_NOT_EFFECTIVE": 409,
    "ERR_CHANNEL_FLOOR_VIOLATION": 422,
    "ERR_BUYER_AMBIGUOUS": 422,
    "ERR_CLEARANCE_NOT_CLEARED": 409,
    "ERR_LTB_WINDOW_CLOSED": 409,
    "ERR_LTB_POOL_EXHAUSTED": 409,
    "ERR_ORDER_COMPLIANCE_BLOCKED": 409,
    "ERR_BENCH_CAPACITY_EXCEEDED": 409,
    "ERR_RETEST_LIMIT_EXCEEDED": 409,
    "ERR_ACCRUAL_NOT_FINALIZED": 409,
    "ERR_REBATE_BUDGET_EXCEEDED": 422,
    "ERR_PHASEOUT_SUCCESSOR_REQUIRED": 409,
    "ERR_QUALIFICATION_GATE_UNMET": 409,
}


def api_err(error_id, message):
    if error_id not in ERROR_CATALOG:
        raise KeyError("undefined error id: %s" % error_id)
    return ApiError(error_id, ERROR_CATALOG[error_id], message)


def invalid_request(message):
    return api_err("ERR_INVALID_REQUEST", message)


def not_found(message="Resource not found"):
    return api_err("ERR_NOT_FOUND", message)


def invalid_state(message):
    return api_err("ERR_INVALID_STATE", message)


def stale_version(message="expected version does not match current version"):
    return api_err("ERR_STALE_VERSION", message)
