"""Shared primitives: response envelope, errors, decimal/datetime helpers.

Every structural name here is taken from PRD.md section 2.2 / 2.3 / 2.4 and
SCAFFOLD.yaml section 1.0 (response_envelope).
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import jsonify

getcontext().prec = 60

UTC = timezone.utc

# --------------------------------------------------------------------------
# Decimal helpers.  Money / tonnage / acreage -> 2dp; water depth -> 3dp.
# Every rounding in this specification is half-up (PRD 2.7).
# --------------------------------------------------------------------------

Q2 = Decimal("0.01")
Q3 = Decimal("0.001")
ZERO = Decimal("0")


def D(value):
    """Coerce an inbound JSON number (int/float/str/Decimal) to Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    return D(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r3(value):
    return D(value).quantize(Q3, rounding=ROUND_HALF_UP)


def dec_out(value):
    """Render a Decimal for the JSON body."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_last_wall = [None]


def wall_now():
    """Strictly increasing wall-clock instant, millisecond resolution.

    created_at / updated_at are real-time stamps: they are NOT the logical
    clock (PRD 2.4 enumerates exactly which fields read the logical clock).
    Strict monotonicity keeps `created_at ASC` list ordering and the
    governing-estimate / auto-cancel tie-breaks deterministic.
    """
    raw = datetime.now(UTC)
    now = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
    prev = _last_wall[0]
    if prev is not None and now <= prev:
        now = prev + timedelta(milliseconds=1)
    _last_wall[0] = now
    return now


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """Format a server-stamped instant.

    Whole seconds when the instant has no sub-second component (PRD 3.6
    states the clearance instants are expressed to whole seconds), otherwise
    three fractional digits.
    """
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ms(dt)


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        return None
    raw = value.strip()
    if raw[-1] in ("Z", "z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def is_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role must both be present and name a declared role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to call this endpoint.",
    "ERR_VINEYARD_OWNERSHIP_REQUIRED": "The acting ClientOwner does not own the target ranch.",
    "ERR_CREW_OWNERSHIP_REQUIRED": "The acting CrewSupervisor does not own the referenced crew.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_VINEYARD_NOT_FOUND": "No Vineyard with the given id.",
    "ERR_BLOCK_NOT_FOUND": "No Block with the given id.",
    "ERR_CONTRACT_NOT_FOUND": "No CustomFarmingContract with the given id.",
    "ERR_PLAN_NOT_FOUND": "No FarmingPlan with the given id.",
    "ERR_CREW_NOT_FOUND": "No LaborCrew with the given id.",
    "ERR_WORK_ORDER_NOT_FOUND": "No WorkOrder with the given id.",
    "ERR_SPRAY_NOT_FOUND": "No SprayRecord with the given id.",
    "ERR_IRRIGATION_EVENT_NOT_FOUND": "No IrrigationEvent with the given id.",
    "ERR_DELIVERY_WINDOW_NOT_FOUND": "No WineryDeliveryWindow with the given id.",
    "ERR_HARVEST_LOAD_NOT_FOUND": "No HarvestLoad with the given id.",
    "ERR_PEST_OBSERVATION_NOT_FOUND": "No PestObservation with the given id.",
    "ERR_STALE_BLOCK_VERSION": "expected_block_version does not match the current Block version.",
    "ERR_STALE_DELIVERY_WINDOW_VERSION": "expected_delivery_window_version does not match the current window version.",
    "ERR_CONTRACT_NOT_DRAFT": "The contract is not DRAFT.",
    "ERR_CONTRACT_NOT_ACTIVE": "The contract is not ACTIVE.",
    "ERR_PLAN_NOT_DRAFT": "The farming plan is not DRAFT.",
    "ERR_PLAN_NOT_SUBMITTED": "The farming plan is not SUBMITTED.",
    "ERR_REVISION_LIMIT_REACHED": "The plan revision limit has been reached.",
    "ERR_PLAN_NOT_APPROVED": "The cited farming plan is not APPROVED.",
    "ERR_BLOCK_REMOVED": "The block has been REMOVED.",
    "ERR_WORK_ORDER_NOT_SCHEDULED": "The work order is not SCHEDULED.",
    "ERR_WORK_ORDER_NOT_IN_PROGRESS": "The work order is not IN_PROGRESS.",
    "ERR_WORK_ORDER_TERMINAL": "The work order is already COMPLETED or CANCELLED.",
    "ERR_PAYROLL_STATE_INVALID": "The payroll action is not valid for the current payroll status.",
    "ERR_SPRAY_NOT_RECOMMENDED": "The spray record is not RECOMMENDED.",
    "ERR_SPRAY_NOT_APPLIED": "The spray record is not APPLIED.",
    "ERR_IRRIGATION_NOT_SCHEDULED": "The irrigation event is not SCHEDULED.",
    "ERR_LOAD_NOT_PLANNED": "The harvest load is not PLANNED.",
    "ERR_LOAD_NOT_IN_TRANSIT": "The harvest load is not IN_TRANSIT.",
    "ERR_CREW_INACTIVE": "The referenced crew is INACTIVE.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this step.",
    "ERR_CREW_NOT_PEST_CERTIFIED": "An uncertified crew may not be booked inside an open re-entry interval.",
    "ERR_REENTRY_INTERVAL_ACTIVE": "The block's re-entry interval is still active.",
    "ERR_PREHARVEST_INTERVAL_ACTIVE": "The block's pre-harvest interval is still active.",
    "ERR_ACTION_THRESHOLD_NOT_MET": "The cited observation does not exceed the pest action threshold.",
    "ERR_CREW_SCHEDULE_CONFLICT": "The crew is already booked over this interval.",
    "ERR_DELIVERY_ETA_OUTSIDE_WINDOW": "delivery_eta falls outside the delivery window.",
    "ERR_DUPLICATE_PLAN_FOR_BLOCK_YEAR": "A farming plan already exists for this block and crop year.",
    "ERR_DUPLICATE_BLOCK_CODE": "A block with this block_code already exists on this ranch.",
    "ERR_PLAN_BLOCK_MISMATCH": "The cited farming plan belongs to a different block.",
    "ERR_VINEYARD_MISMATCH": "The referenced rows belong to different ranches.",
    "ERR_BLOCK_ALREADY_ENROLLED": "The block is already enrolled under a contract.",
    "ERR_NO_ENROLLED_BLOCKS": "The contract has no enrolled blocks.",
    "ERR_BLOCK_NOT_ENROLLED": "The block is not enrolled under any contract.",
    "ERR_NO_YIELD_ESTIMATE": "The block has no yield estimate on file.",
    "ERR_CREW_TASK_MISMATCH": "The crew is not capable of the requested task.",
    "ERR_PLAN_BUDGET_EXCEEDED": "The plan budget would be exceeded.",
    "ERR_WINDOW_CAPACITY_EXCEEDED": "The delivery window capacity would be exceeded.",
    "ERR_HARVEST_EXCEEDS_ESTIMATE": "The block harvest tolerance would be exceeded.",
}


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ms(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status
