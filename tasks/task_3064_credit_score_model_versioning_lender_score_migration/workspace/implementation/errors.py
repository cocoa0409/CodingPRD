"""Error catalogue (§1.6 / PRD §5) and the ApiError exception type."""

from decimal import Decimal

# --- error id -> http status, read verbatim from the scaffold error catalog ---
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_LICENSE_NOT_OWNED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_BUREAU_NOT_FOUND": 404,
    "ERR_SCORE_MODEL_NOT_FOUND": 404,
    "ERR_SCORE_VARIANT_NOT_FOUND": 404,
    "ERR_CONSUMER_NOT_FOUND": 404,
    "ERR_ARCHIVE_SAMPLE_NOT_FOUND": 404,
    "ERR_VALIDATION_STUDY_NOT_FOUND": 404,
    "ERR_REFERENCE_SET_NOT_FOUND": 404,
    "ERR_SCORE_RESULT_NOT_FOUND": 404,
    "ERR_REASON_CODE_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_MODEL_DOCUMENTATION_NOT_FOUND": 404,
    "ERR_MIGRATION_EVENT_NOT_FOUND": 404,
    "ERR_DISCOVERY_REQUEST_NOT_FOUND": 404,
    "ERR_FEE_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_DISCOVERY_TAG_UNKNOWN": 404,
    "ERR_INVALID_STATE_MACHINE_EDGE": 409,
    "ERR_MODEL_SUPERSEDED": 409,
    "ERR_MODEL_RETIRED": 409,
    "ERR_MODEL_DEPRECATED": 409,
    "ERR_LICENSE_SUSPENDED": 409,
    "ERR_LICENSE_VARIANT_MISMATCH": 409,
    "ERR_LICENSE_WINDOW_CONFLICT": 409,
    "ERR_SAMPLE_WINDOW_OVERLAP": 409,
    "ERR_SAMPLE_MODEL_MISMATCH": 409,
    "ERR_SAMPLE_TOO_SMALL": 409,
    "ERR_SAMPLE_KIND_MISMATCH": 409,
    "ERR_REFERENCE_SET_CONSUMER_MISMATCH": 409,
    "ERR_REASON_CODE_VARIANT_MISMATCH": 409,
    "ERR_REASON_CODE_ARCHIVED": 409,
    "ERR_REASON_CODE_ACTIVE": 409,
    "ERR_REASON_CODE_REUSE_LIMIT": 409,
    "ERR_REASON_CODE_MISSING": 409,
    "ERR_REASON_CODE_VIOLATION": 409,
    "ERR_COMPOSITE_CODE_DUPLICATE": 409,
    "ERR_DUPLICATE_BUREAU_CODE": 409,
    "ERR_DUPLICATE_CONSUMER_REF": 409,
    "ERR_DUPLICATE_VERSION_LABEL": 409,
    "ERR_DUPLICATE_VARIANT_INDUSTRY": 409,
    "ERR_DUPLICATE_CODE_LABEL": 409,
    "ERR_DUPLICATE_DISCOVERY_TAG": 409,
    "ERR_ENTITLEMENT_WITHIN_LIMIT": 409,
    "ERR_NO_RELEASED_VARIANT": 409,
    "ERR_MODEL_DOC_REQUIRED": 409,
    "ERR_LICENSE_DOC_MISSING": 409,
    "ERR_DEPRECATION_BLOCKED": 409,
    "ERR_RETIREMENT_BLOCKED": 409,
    "ERR_STUDY_ALREADY_FINALIZED": 409,
    "ERR_STUDY_NOT_FINALIZED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_STALE_VERSION": 412,
}

MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role or X-User-ID header missing, or X-User-Role names an undeclared role.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted on this endpoint, or X-User-ID does not match the entity backing the role.",
    "ERR_LICENSE_NOT_OWNED": "The posting names a licence that is not the acting ScoreConsumer's own X-User-ID.",
    "ERR_INVALID_REQUEST": "The request is malformed: unknown field, wrong type, or a magnitude bound was violated.",
    "ERR_DISCOVERY_TAG_UNKNOWN": "No ScoreDiscoveryRequest is registered under the supplied discovery tag.",
    "ERR_INVALID_STATE_MACHINE_EDGE": "The target does not occupy the state named by the transition's from clause.",
    "ERR_MODEL_SUPERSEDED": "The model version has been superseded.",
    "ERR_MODEL_RETIRED": "The model version has been retired.",
    "ERR_MODEL_DEPRECATED": "No new licence may be created on a variant of a deprecated model version.",
    "ERR_LICENSE_SUSPENDED": "Posting under a licence that is not ACTIVE is refused.",
    "ERR_LICENSE_VARIANT_MISMATCH": "The named licence does not cover the posting's score variant.",
    "ERR_LICENSE_WINDOW_CONFLICT": "The licence term overlaps an existing term for the same lender and variant.",
    "ERR_SAMPLE_WINDOW_OVERLAP": "The archive sample window overlaps an existing sample on the same model version.",
    "ERR_SAMPLE_MODEL_MISMATCH": "The named sample does not belong to the study's score model version.",
    "ERR_SAMPLE_TOO_SMALL": "The sample's record_count is below the model's min_input_count.",
    "ERR_SAMPLE_KIND_MISMATCH": "A CROSS_BUREAU study requires a VALIDATION-kind sample.",
    "ERR_REFERENCE_SET_CONSUMER_MISMATCH": "The named reference set belongs to a different consumer.",
    "ERR_REASON_CODE_VARIANT_MISMATCH": "The reason code does not belong to the variant or model family it must map.",
    "ERR_REASON_CODE_ARCHIVED": "An archived reason code may not be relied upon here.",
    "ERR_REASON_CODE_ACTIVE": "The bound reason code is still ACTIVE and may not be reconciled against.",
    "ERR_REASON_CODE_REUSE_LIMIT": "The reason code's bind_count has already reached 2.",
    "ERR_REASON_CODE_MISSING": "A PROTECTED_CLASS study requires an ACTIVE reason code on the model.",
    "ERR_REASON_CODE_VIOLATION": "A required composite reason code does not appear on any non-voided posting.",
    "ERR_COMPOSITE_CODE_DUPLICATE": "The composite code already exists on the variant.",
    "ERR_ENTITLEMENT_WITHIN_LIMIT": "The licence is still within its entitlement and may not be suspended.",
    "ERR_NO_RELEASED_VARIANT": "The model version carries no RELEASED variant.",
    "ERR_MODEL_DOC_REQUIRED": "A FILED or SUPPLEMENTED MODEL_RISK_REPORT is required.",
    "ERR_LICENSE_DOC_MISSING": "A FILED or SUPPLEMENTED document carrying the licensed version label is required.",
    "ERR_DEPRECATION_BLOCKED": "An ACTIVE licence sits on a variant of this model version.",
    "ERR_RETIREMENT_BLOCKED": "A reference set on this model version sits outside RECONCILED.",
    "ERR_STUDY_ALREADY_FINALIZED": "The study has already been acknowledged.",
    "ERR_STUDY_NOT_FINALIZED": "The study has not been acknowledged and cannot be compensated.",
    "ERR_SEGREGATION_OF_DUTIES": "The acknowledging officer must differ from the analyst who performed the study.",
    "ERR_STALE_VERSION": "The supplied expected version does not equal the parent record's current version.",
}

for _eid in ERROR_STATUS:
    MESSAGES.setdefault(_eid, "The requested operation could not be completed.")


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or MESSAGES.get(error_id, "The requested operation could not be completed.")
        super().__init__(f"{self.error_id}: {self.message}")


def invalid_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)


def not_found_msg(entity):
    return f"No {entity} carries the requested id."


def as_int(value):
    """Coerce a JSON value to int, rejecting bools and non-integral floats."""
    if isinstance(value, bool):
        raise invalid_request("Expected an integer.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            raise invalid_request("Expected an integer.")
        return int(value)
    raise invalid_request("Expected an integer.")


def as_number(value):
    """Coerce a JSON value to Decimal, rejecting bools and non-numeric types."""
    if isinstance(value, bool):
        raise invalid_request("Expected a number.")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        return value
    raise invalid_request("Expected a number.")