"""Error classes and the error-id catalogue (PRD section 5 / SCAFFOLD errors)."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_HOME_SITE_NOT_AVAILABLE": 409,
    "ERR_ABA_DISCLOSURE_MISSING": 403,
    "ERR_ABA_DISCLOSURE_CURE_EXPIRED": 409,
    "ERR_STEERING_PROHIBITED": 403,
    "ERR_QUALIFICATION_SCORE_BELOW_FLOOR": 422,
    "ERR_DTI_CEILING_EXCEEDED": 422,
    "ERR_COMMUNITY_SUSPENDED": 403,
    "ERR_APPLICATION_DRIFT_EXCLUDED": 409,
    "ERR_COMMITMENT_WINDOW_CLOSED": 409,
    "ERR_ADVERTISED_RATE_EXPIRED": 409,
    "ERR_RATE_LOCK_EXPIRED": 409,
    "ERR_RELOCK_LIMIT_REACHED": 409,
    "ERR_COMMITMENT_WINDOW_OVERLAP": 409,
    "ERR_LOCK_WINDOW_OVERLAP": 409,
    "ERR_FORWARD_COMMITMENT_EXHAUSTED": 409,
    "ERR_NO_QUALIFIED_APPLICATION": 409,
    "ERR_INCENTIVE_BUDGET_EXHAUSTED": 422,
    "ERR_BUYDOWN_EXCEEDS_ALLOCATION": 422,
    "ERR_DEPOSIT_SUM_MISMATCH": 422,
    "ERR_FORFEITURE_STATUTE_UNDETERMINED": 409,
    "ERR_FORFEITURE_NOT_PROPOSED": 409,
    "ERR_DUPLICATE_ACTIVE_LOCK": 409,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 400,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        super().__init__(self.message)

    def to_dict(self):
        return {"error_id": self.error_id, "message": self.message}


def fail(error_id, message=None, http_status=None):
    raise ApiError(error_id, message, http_status)