"""Error catalogue, custom exception and time helpers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- Error id -> HTTP status, exactly as declared in the scaffold error catalog. ---
ERROR_STATUS = {
    "ERR_INVALID_USER_CONTEXT": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_BUYER_SUSPENDED": 403,
    "ERR_JURISDICTION_NOT_ENACTED": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_DELAY_DAYS": 400,
    "ERR_INVALID_APPOINTMENT_WINDOW": 400,
    "ERR_ENTITLEMENT_VERSION_NOT_NEWER": 400,
    "ERR_CONFIG_LOCK_DEADLINE_PASSED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_APPRAISAL_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_ENTITLEMENT_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_CENTER_NOT_FOUND": 404,
    "ERR_CONFIGURATION_NOT_FOUND": 404,
    "ERR_OPTION_NOT_FOUND": 404,
    "ERR_ESTIMATE_NOT_FOUND": 404,
    "ERR_NOTE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ORDER_NOT_OWNED": 403,
    "ERR_BUYER_NOT_ACTIVE": 403,
    "ERR_ORDER_NOT_CONFIG_LOCKED": 409,
    "ERR_ORDER_NOT_ALLOCATED": 409,
    "ERR_ORDER_NOT_IN_TRANSIT": 409,
    "ERR_ORDER_NOT_AT_CENTER": 409,
    "ERR_ORDER_NOT_DELIVERY_SCHEDULED": 409,
    "ERR_ORDER_NOT_APPRAISABLE": 409,
    "ERR_ORDER_NOT_FINANCEABLE": 409,
    "ERR_APPOINTMENT_NOT_BOOKED": 409,
    "ERR_APPOINTMENT_NOT_CONFIRMED": 409,
    "ERR_APPOINTMENT_NOT_AT_RISK": 409,
    "ERR_APPOINTMENT_ALREADY_TERMINAL": 409,
    "ERR_INSPECTION_INCOMPLETE": 409,
    "ERR_APPRAISAL_NOT_DRAFT": 409,
    "ERR_APPLICATION_NOT_SUBMITTED": 409,
    "ERR_FINANCING_NOT_FUNDED": 409,
    "ERR_BATCH_NOT_SCHEDULED": 409,
    "ERR_BATCH_NOT_DELAYED": 409,
    "ERR_BATCH_NOT_DELAYABLE": 409,
    "ERR_BATCH_NOT_IN_PRODUCTION": 409,
    "ERR_OUT_OF_STATE_DELIVERY_REQUIRED": 403,
    "ERR_GALLERY_HANDOVER_FORBIDDEN": 403,
    "ERR_DELIVERY_SLOT_CONFLICT": 409,
    "ERR_SERVICE_SLOT_CONFLICT": 409,
    "ERR_VAN_SCHEDULE_CONFLICT": 409,
    "ERR_GALLERY_SERIALIZATION_GAP": 409,
    "ERR_APPRAISAL_EXPIRES_BEFORE_DELIVERY": 409,
    "ERR_HOME_DELIVERY_OUT_OF_RANGE": 403,
    "ERR_ORDER_FEE_UNPAID": 402,
    "ERR_TRADE_IN_NOT_RESOLVED": 409,
    "ERR_TRADE_IN_TRANSFER_UNSETTLED": 409,
    "ERR_APPRAISAL_OFFER_EXPIRED": 409,
    "ERR_FINANCE_EXCEEDS_VEHICLE_VALUE": 402,
    "ERR_BUYER_NOT_VERIFIED": 403,
    "ERR_NO_ELIGIBLE_UNIT": 409,
    "ERR_ORDER_DELIVERY_NOT_READY": 409,
    "ERR_NO_ESTIMATE_CHANGE": 409,
    "ERR_ESTIMATE_WINDOW_EXPIRED": 409,
    "ERR_MOBILE_SERVICE_FORBIDDEN": 403,
    "ERR_PARTS_NOT_REQUIRED": 409,
    "ERR_TRIAGE_NO_SERVICE_REQUIRED": 409,
    "ERR_PARTS_NOT_PRE_SHIPPED": 409,
    "ERR_CENTER_NOT_FOUND_FOR_KIND": 409,
}

MESSAGES = {
    "ERR_INVALID_USER_CONTEXT": "X-User-Role header missing or not one of the eight declared roles.",
    "ERR_INSUFFICIENT_PERMISSIONS": "The acting role is not permitted to perform this operation.",
    "ERR_BUYER_SUSPENDED": "The acting Buyer account is SUSPENDED.",
    "ERR_JURISDICTION_NOT_ENACTED": "The governing StateJurisdiction is not ENACTED.",
    "ERR_INVALID_REQUEST": "Request body is malformed, a required field is absent, or a supplied value has the wrong type.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_INVALID_STATE": "The target resource is not in the state the requested transition requires.",
    "ERR_ALREADY_TERMINAL": "The target resource is already in a terminal state.",
    "ERR_ORDER_NOT_OWNED": "The acting Buyer does not own the target order.",
    "ERR_ORDER_FEE_UNPAID": "No ORDER_FEE_PAYMENT ledger entry covering the order fee exists.",
    "ERR_CONFIG_LOCK_DEADLINE_PASSED": "The configuration lock deadline has passed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.status = status or ERROR_STATUS.get(error_id, 400)
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Timestamps: ISO 8601 UTC with three fractional digits.
# --------------------------------------------------------------------------

def fmt(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def parse_dt(value, field="datetime"):
    if value is None:
        fail("ERR_INVALID_REQUEST", f"{field} is required.")
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            fail("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 instant.")
    else:
        fail("ERR_INVALID_REQUEST", f"{field} has the wrong type.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(delta):
    """Whole days of a timedelta, rounded DOWN (toward negative infinity)."""
    return delta.days


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))