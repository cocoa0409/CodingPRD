"""Error catalog and the ApiError exception type.

Every error_id / http status pair is taken verbatim from SCAFFOLD.yaml §1.6 and
PRD.md §5.
"""

from decimal import Decimal, ROUND_HALF_UP


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- request shape ---------------------------------------------------------
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_BATCH_SIZE_INVALID = ("ERR_BATCH_SIZE_INVALID", 400)

# --- auth ------------------------------------------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_SOD_VIOLATION = ("ERR_SOD_VIOLATION", 403)
ERR_UNVERIFIED_TRAINER = ("ERR_UNVERIFIED_TRAINER", 403)

# --- existence -------------------------------------------------------------
ERR_EHR_IMPLEMENTATION_NOT_FOUND = ("ERR_EHR_IMPLEMENTATION_NOT_FOUND", 404)
ERR_FACILITY_NOT_FOUND = ("ERR_FACILITY_NOT_FOUND", 404)
ERR_STAFF_NOT_FOUND = ("ERR_STAFF_NOT_FOUND", 404)
ERR_DEPARTMENT_NOT_FOUND = ("ERR_DEPARTMENT_NOT_FOUND", 404)
ERR_BUILD_ITEM_NOT_FOUND = ("ERR_BUILD_ITEM_NOT_FOUND", 404)
ERR_TEST_SCENARIO_NOT_FOUND = ("ERR_TEST_SCENARIO_NOT_FOUND", 404)
ERR_DEFECT_NOT_FOUND = ("ERR_DEFECT_NOT_FOUND", 404)
ERR_CHANNEL_NOT_FOUND = ("ERR_CHANNEL_NOT_FOUND", 404)
ERR_TICKET_NOT_FOUND = ("ERR_TICKET_NOT_FOUND", 404)
ERR_CONVERSION_BATCH_NOT_FOUND = ("ERR_CONVERSION_BATCH_NOT_FOUND", 404)
ERR_PATIENT_ORDER_NOT_FOUND = ("ERR_PATIENT_ORDER_NOT_FOUND", 404)

# --- state -----------------------------------------------------------------
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_ALREADY_TERMINAL = ("ERR_ALREADY_TERMINAL", 409)
ERR_POSTURE_BLOCKS_OPERATION = ("ERR_POSTURE_BLOCKS_OPERATION", 409)
ERR_EPOCH_MISMATCH = ("ERR_EPOCH_MISMATCH", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)

# --- safety / constraints --------------------------------------------------
ERR_ORDER_NOT_RECONCILED = ("ERR_ORDER_NOT_RECONCILED", 422)
ERR_PROCEDURE_CREDENTIAL_MISSING = ("ERR_PROCEDURE_CREDENTIAL_MISSING", 422)
ERR_CUSTOMIZATION_LIMIT_EXCEEDED = ("ERR_CUSTOMIZATION_LIMIT_EXCEEDED", 422)
ERR_DEFECT_BLOCKS_DEPARTMENT = ("ERR_DEFECT_BLOCKS_DEPARTMENT", 422)
ERR_CHANNEL_NOT_VALIDATED = ("ERR_CHANNEL_NOT_VALIDATED", 422)
ERR_GO_LIVE_BLOCKED = ("ERR_GO_LIVE_BLOCKED", 422)
ERR_DEFECT_SEVERITY_NOT_DEFERRABLE = ("ERR_DEFECT_SEVERITY_NOT_DEFERRABLE", 422)
ERR_TRAINER_OBSERVATION_INSUFFICIENT = ("ERR_TRAINER_OBSERVATION_INSUFFICIENT", 422)
ERR_CLAIM_RESPONSE_INVALID = ("ERR_CLAIM_RESPONSE_INVALID", 422)
ERR_PRIMARY_FACILITY_MISMATCH = ("ERR_PRIMARY_FACILITY_MISMATCH", 422)
ERR_BALANCE_VARIANCE_EXCEEDED = ("ERR_BALANCE_VARIANCE_EXCEEDED", 422)
ERR_INTERFACE_MESSAGE_INVALID = ("ERR_INTERFACE_MESSAGE_INVALID", 422)
ERR_INTERFACE_LATENCY_EXCEEDED = ("ERR_INTERFACE_LATENCY_EXCEEDED", 422)
ERR_TRAINING_HOURS_INSUFFICIENT = ("ERR_TRAINING_HOURS_INSUFFICIENT", 422)
ERR_PROFICIENCY_GATE_CLOSED = ("ERR_PROFICIENCY_GATE_CLOSED", 422)

# --- temporal --------------------------------------------------------------
ERR_TEMPORAL_OVERLAP = ("ERR_TEMPORAL_OVERLAP", 409)
ERR_PRECEDING_STEP_INCOMPLETE = ("ERR_PRECEDING_STEP_INCOMPLETE", 409)
ERR_RETEST_COOLDOWN_ACTIVE = ("ERR_RETEST_COOLDOWN_ACTIVE", 409)
ERR_GO_LIVE_AFTER_TARGET = ("ERR_GO_LIVE_AFTER_TARGET", 422)

# --- capacity --------------------------------------------------------------
ERR_RELEASE_CAPACITY_EXCEEDED = ("ERR_RELEASE_CAPACITY_EXCEEDED", 409)
ERR_SHIFT_OVERLAP = ("ERR_SHIFT_OVERLAP", 409)


def fail(spec, message):
    """Raise an ApiError from an (error_id, http_status) tuple."""
    raise ApiError(spec[0], message, spec[1])


def q2(value):
    """Round half-up to 2 decimal places, returning a Decimal."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q0(value):
    """Round half-up to 0 decimal places, returning a Decimal."""
    return Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal/None for JSON output as a float (2 dp values) or int."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def whole(value):
    """Render a whole-minute Decimal as an int."""
    if value is None:
        return None
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))