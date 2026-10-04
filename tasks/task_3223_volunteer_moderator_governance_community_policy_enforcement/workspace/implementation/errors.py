"""Error catalogue (§1.6 of the scaffold / §5 of the PRD).

Every error_id below is transcribed verbatim from the error table; the HTTP
status attached to each is the one the catalogue declares.
"""


class ApiError(Exception):
    """An error that carries a catalogue error_id, a message and an HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_COMMUNITY_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_COMMUNITY_NAME": 409,
    "ERR_DUPLICATE_RULE_CODE": 409,
    "ERR_RULE_CONFLICT": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_CROSS_POWER_QUORUM_NOT_MET": 409,
    "ERR_PRIVATE_PROTEST_FORBIDDEN": 409,
    "ERR_TOP_MODERATOR_REMOVAL_FORBIDDEN": 409,
    "ERR_FINAL_MODERATOR_REMOVAL": 409,
    "ERR_INACTIVITY_REMOVAL_NOT_JUSTIFIED": 409,
    "ERR_PENDING_HANDOVER": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_PRECEDENT_EXPIRED": 409,
    "ERR_NO_NEW_EVIDENCE": 422,
    "ERR_ACTIVE_SANCTION_CONFLICT": 409,
    "ERR_REINSTATEMENT_CONDITIONS_UNMET": 409,
    "ERR_BRIGADE_EVIDENCE_INCOMPLETE": 409,
    "ERR_BRIGADE_SEVERITY_TOO_LOW": 409,
    "ERR_COOLING_OFF_ACTIVE": 409,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_SANCTION_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PAGINATION_INVALID": 400,
    "ERR_PROTEST_NOT_FOUND": 404,
    "ERR_ACCOUNT_WIDE_CONFLICT": 409,
    "ERR_ARCHIVED_COMMUNITY": 409,
}


def fail(error_id, message=None):
    """Raise the catalogue error `error_id` with the catalogue HTTP status."""
    raise ApiError(error_id, message or error_id, _HTTP[error_id])


def status_for(error_id):
    return _HTTP.get(error_id, 500)