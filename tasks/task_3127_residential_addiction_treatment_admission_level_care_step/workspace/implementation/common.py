"""Common resource fields, primitives, enums and request-shape helpers."""

import copy
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

INITIAL_VERSION = 1

ASAM_LEVELS = ["ASAM_1_0", "ASAM_2_1", "ASAM_3_1", "ASAM_3_5", "ASAM_3_7"]
_LEVEL_RANK = {name: idx for idx, name in enumerate(ASAM_LEVELS)}

CREDENTIAL_TIERS = ["TIER_1_SUPPORT", "TIER_2_COUNSELOR", "TIER_3_LICENSED", "TIER_4_INDEPENDENT"]
_TIER_RANK = {name: idx for idx, name in enumerate(CREDENTIAL_TIERS)}

SHELTER_CLASSES = ["RESIDENTIAL", "TRANSITIONAL", "SOBER_DORM", "MATRIX"]
HOUSING_BASES = ["EXPLICIT", "RANKED_AUTO"]
PLACEMENT_BASES = ["DIMENSION_SUM", "HIGHEST_DIMENSION_FLOOR"]

DIMENSION_NAMES = [
    "withdrawal_risk",
    "biomedical_conditions",
    "emotional_behavioral",
    "readiness_to_change",
    "relapse_potential",
    "recovery_environment",
]

DECLARED_ROLES = {
    "PlatformAdmin",
    "ClinicalDirector",
    "UtilizationReviewer",
    "AdmissionsIntakeNurse",
    "Clinician",
    "AlumniCoordinator",
    "Any",
}

EPISODE_TERMINAL_CLINICAL = {"DISCHARGED"}

OCC_ARG = "offset"
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

_ENTITIES_WITH_EXPLICIT_VERSION = {"TreatmentPlan"}


def level_rank(level):
    return _LEVEL_RANK.get(level, 0)


def tier_rank(tier):
    return _TIER_RANK.get(tier, -1)


def new_id():
    return str(uuid.uuid4())


def now_clock():
    from db import STORE

    return STORE.now()


def iso(moment):
    """ISO 8601 UTC with three fractional digits."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def parse_iso(value, field="datetime"):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC string." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 instant." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def round_half_up(value, places=0):
    dec = Decimal(str(value))
    if places == 0:
        quant = Decimal("1")
    else:
        quant = Decimal("1").scaleb(-places)
    return dec.quantize(quant, rounding=ROUND_HALF_UP)


def days_between_floor(later, earlier):
    """Whole days between two instants, truncated toward zero."""
    delta = (later - earlier).total_seconds() / 86400.0
    return int(Decimal(str(delta)).to_integral_value(rounding="ROUND_DOWN"))


def hours_exact(later, earlier):
    """Exact decimal number of hours between two instants."""
    delta = Decimal(str((later - earlier).total_seconds())) / Decimal(86400)
    return delta * Decimal(24)


def base_fields(entity_name):
    stamp = iso(now_clock())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": INITIAL_VERSION,
    }


def touch(record):
    record["updated_at"] = iso(now_clock())
    record["version"] = record.get("version", INITIAL_VERSION) + 1


def bump_version(record):
    record["version"] = record.get("version", INITIAL_VERSION) + 1


def touch_only(record):
    record["updated_at"] = iso(now_clock())


def public(record):
    if record is None:
        return None
    out = copy.deepcopy(record)
    out.pop("_facility_id", None)
    out.pop("_episode_id", None)
    out.pop("_created_seq", None)
    out.pop("_charged", None)
    out.pop("_bed_held", None)
    return out


# ---------------------------------------------------------------------------
# Request shape helpers
# ---------------------------------------------------------------------------

def body_of(payload):
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def require_fields(body, fields):
    for field in fields:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % field)


def check_allowed(body, allowed):
    for key in body:
        if key not in allowed:
            # PRD §2.7: a declared server-owned field carries the operation's own
            # value, so a caller that supplies one is answered with what the server
            # holds rather than with an undeclared-input refusal.
            if key in SERVER_OWNED_FIELDS:
                continue
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not declared for this operation." % key)


# Fields the PRD states are derived, stamped or owned by the server on create. They
# are declared "^server-owned" and a body value for them is ignored, never refused.
SERVER_OWNED_FIELDS = {
    "id", "created_at", "updated_at", "version", "status", "attended",
    "billing_amount_cents", "clinical_status", "care_level_status", "step_down_count",
    "therapy_revenue_cents", "licensed", "as_level_max", "state_min_credential_tier",
    "facility_posture", "is_accepting_admissions", "compliance_risk_points",
    "ops_epoch", "last_ops_run_at", "discharged_at", "admitted_at", "ordered_at",
    "cleared_at", "expires_at", "assessed_at", "recruited_at",
}


def as_string(body, field):
    value = body.get(field)
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def as_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def as_int(body, field):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def as_enum(body, field, members):
    value = body.get(field)
    if not isinstance(value, str) or value not in members:
        raise ApiError("ERR_INVALID_ENUM_VALUE", "Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def opt_string(body, field):
    if field not in body or body.get(field) is None:
        return None
    return as_string(body, field)


def opt_int(body, field):
    if field not in body or body.get(field) is None:
        return None
    return as_int(body, field)


def opt_bool(body, field):
    if field not in body:
        return None
    return as_bool(body, field)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def page_params(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = PAGE_DEFAULT_LIMIT if raw_limit is None else _coerce_page_int(raw_limit, "limit")
    offset = PAGE_DEFAULT_OFFSET if raw_offset is None else _coerce_page_int(raw_offset, "offset")
    if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def _coerce_page_int(raw, field):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return {
        "rows": window,
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }


def filter_param(args, name):
    value = args.get(name)
    if value is None or value == "":
        return None
    return value