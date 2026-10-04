"""Error catalogue for the esign envelope workflow API.

error_id values and HTTP statuses are taken verbatim from SCAFFOLD.yaml §1.6
and PRD.md §5. The response envelope field names (error_id/message under
data, response_type "error") come from response_envelope.error.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- auth ---------------------------------------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_SOD_VIOLATION = ("ERR_SOD_VIOLATION", 403)

# --- existence ----------------------------------------------------------
ERR_ENVELOPE_NOT_FOUND = ("ERR_ENVELOPE_NOT_FOUND", 404)
ERR_RECIPIENT_NOT_FOUND = ("ERR_RECIPIENT_NOT_FOUND", 404)
ERR_DOCUMENT_NOT_FOUND = ("ERR_DOCUMENT_NOT_FOUND", 404)
ERR_ACCOUNT_NOT_FOUND = ("ERR_ACCOUNT_NOT_FOUND", 404)
ERR_TEMPLATE_NOT_FOUND = ("ERR_TEMPLATE_NOT_FOUND", 404)
ERR_RETENTION_POLICY_NOT_FOUND = ("ERR_RETENTION_POLICY_NOT_FOUND", 404)

# --- state --------------------------------------------------------------
ERR_ENVELOPE_TERMINAL = ("ERR_ENVELOPE_TERMINAL", 409)
ERR_INVALID_ENVELOPE_STATE = ("ERR_INVALID_ENVELOPE_STATE", 409)
ERR_RECIPIENT_TERMINAL = ("ERR_RECIPIENT_TERMINAL", 409)
ERR_SESSION_CLOSED = ("ERR_SESSION_CLOSED", 409)
ERR_LEGAL_HOLD_FROZEN = ("ERR_LEGAL_HOLD_FROZEN", 409)
ERR_ENVELOPE_EXPIRED = ("ERR_ENVELOPE_EXPIRED", 409)
ERR_RETENTION_NOT_EXPIRED = ("ERR_RETENTION_NOT_EXPIRED", 409)
ERR_DUPLICATE_RECIPIENT = ("ERR_DUPLICATE_RECIPIENT", 409)
ERR_DUPLICATE_TEMPLATE_NAME = ("ERR_DUPLICATE_TEMPLATE_NAME", 409)
ERR_REMINDER_COOLDOWN = ("ERR_REMINDER_COOLDOWN", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)

# --- assurance / consent ------------------------------------------------
ERR_AUTH_REQUIRED = ("ERR_AUTH_REQUIRED", 422)
ERR_AUTH_LEVEL_TOO_LOW = ("ERR_AUTH_LEVEL_TOO_LOW", 422)
ERR_AUTH_MAX_ATTEMPTS = ("ERR_AUTH_MAX_ATTEMPTS", 422)
ERR_INVALID_ACCESS_CODE = ("ERR_INVALID_ACCESS_CODE", 401)
ERR_CONSENT_REQUIRED = ("ERR_CONSENT_REQUIRED", 422)

# --- structural ---------------------------------------------------------
ERR_ROUTING_NOT_RELEASED = ("ERR_ROUTING_NOT_RELEASED", 422)
ERR_ROUTING_ORDER_GAP = ("ERR_ROUTING_ORDER_GAP", 422)
ERR_FIELD_REQUIRED = ("ERR_FIELD_REQUIRED", 422)
ERR_RECIPIENT_ENVELOPE_MISMATCH = ("ERR_RECIPIENT_ENVELOPE_MISMATCH", 422)
ERR_DOCUMENT_ENVELOPE_MISMATCH = ("ERR_DOCUMENT_ENVELOPE_MISMATCH", 422)
ERR_TEMPLATE_NOT_PUBLISHED = ("ERR_TEMPLATE_NOT_PUBLISHED", 422)
ERR_BULK_ROW_INVALID = ("ERR_BULK_ROW_INVALID", 422)
ERR_INSUFFICIENT_CREDIT = ("ERR_INSUFFICIENT_CREDIT", 402)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)


def fail(spec, message):
    """Raise an ApiError from a (error_id, http_status) tuple."""
    raise ApiError(spec[0], message, spec[1])