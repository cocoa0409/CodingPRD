"""Business logic: calculations, cascades, serializers, shared validators."""
import uuid
from datetime import datetime, date, timezone, timedelta

from flask import g

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NO_ELIGIBLE_TIER,
    ERR_PRIVACY_HOLD_BLOCKS_ACCESS,
)
from store import store

# --- Calculation constants (scaffold §1.3) ---
FPL_TABLE = {
    1: 1506000, 2: 2044200, 3: 2582400, 4: 3120600,
    5: 3658800, 6: 4197000, 7: 4735200, 8: 5273400,
}
FPL_INCREMENT = 538200
SELF_DECLARE_MAX_DISCOUNT_PCT = 80
RAPID_REINSERTION_WINDOW = timedelta(days=30)
RAPID_LOT_EXPIRY_GRACE_DAYS = 7


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def logical_now():
    return store.clock.now()


def logical_now_iso():
    return iso_format(logical_now())


def iso_format(dt):
    """ISO 8601 UTC with three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(value, field):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 timestamp string", 400)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 timestamp", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO date string", 400)
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is not a valid ISO date", 400)


def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object", 400)
    return body


def req_field(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, f"missing required field: {field}", 400)
    return body[field]


def req_str(body, field):
    v = req_field(body, field)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a non-empty string", 400)
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = req_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}", 400)
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be <= {maximum}", 400)
    return v


def req_bool(body, field):
    v = req_field(body, field)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a boolean", 400)
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a boolean", 400)
    return body[field]


def req_enum(body, field, allowed):
    v = req_field(body, field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}", 400)
    return v


def pagination_params():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be a non-negative integer", 400)
    return limit, offset


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e["_created_seq"],))


def page(items):
    """Apply default sort (created_at ascending) and pagination."""
    limit, offset = pagination_params()
    ordered = sorted_by_created(items)
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Entity base
# ---------------------------------------------------------------------------

_seq_counter = [0]


def base_entity():
    _seq_counter[0] += 1
    now = logical_now_iso()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_created_seq": _seq_counter[0],
    }


def touch(entity):
    entity["updated_at"] = logical_now_iso()
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Derived state: is_minor, license status
# ---------------------------------------------------------------------------

def _add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return d.replace(year=d.year + years, day=28)


def is_minor_at(dob, ref_date):
    """True when ref_date - dob < 18 years (i.e. 18th birthday still in future)."""
    return _add_years(dob, 18) > ref_date


def patient_is_minor(patient, ref=None):
    ref = ref or logical_now().date()
    return is_minor_at(parse_date(patient["date_of_birth"], "date_of_birth"), ref)


def license_derived_status(lic):
    """EXPIRED once the logical clock reaches valid_until (exclusive end)."""
    if logical_now() >= parse_ts(lic["valid_until"], "valid_until"):
        return "EXPIRED"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# Privacy hold gate (validation priority 4.5)
# ---------------------------------------------------------------------------

def check_privacy_hold(patient_id):
    """Block callers not whitelisted through an ACTIVE covering hold."""
    now = logical_now()
    covering = []
    for h in store.privacy_holds.values():
        if h["patient_id"] != patient_id or h["status"] != "ACTIVE":
            continue
        if h["scope"] not in ("RECORD_VIEW", "ALL"):
            continue
        if parse_ts(h["hold_start"], "hold_start") <= now < parse_ts(h["hold_end"], "hold_end"):
            covering.append(h)
    if not covering:
        return
    user_id = getattr(g, "user_id", None)
    for h in covering:
        if user_id in (h.get("authorized_staff_ids") or []):
            return
    raise ApiError(
        ERR_PRIVACY_HOLD_BLOCKS_ACCESS,
        "Caller not authorized through an ACTIVE privacy hold covering now",
        403,
    )


def patient_id_for_encounter(encounter):
    return encounter["patient_id"]


def patient_id_for_claim(claim):
    enc = store.encounters.get(claim["encounter_id"])
    return enc["patient_id"] if enc else None


def patient_id_for_reservation(res):
    enc = store.encounters.get(res["encounter_id"])
    return enc["patient_id"] if enc else None


def patient_id_for_referral(ref):
    enc = store.encounters.get(ref["encounter_id"])
    return enc["patient_id"] if enc else None


def patient_id_for_assessment(assessment):
    return assessment["patient_id"]


# ---------------------------------------------------------------------------
# Calculations (scaffold §1.3)
# ---------------------------------------------------------------------------

def fpl_base_for(household_size):
    if household_size <= 8:
        return FPL_TABLE[household_size]
    return FPL_TABLE[8] + (household_size - 8) * FPL_INCREMENT


def compute_fpl_pct(household_size, annual_income_cents):
    base = fpl_base_for(household_size)
    # floor(annual_income_cents * 100 / base); inputs non-negative => // is floor
    return (annual_income_cents * 100) // base


def assign_tier(affiliate_id, fpl_pct, income_basis):
    candidates = [
        t for t in store.fee_tiers.values()
        if t["affiliate_id"] == affiliate_id
        and t["fpl_pct_min_inclusive"] <= fpl_pct < t["fpl_pct_max_exclusive"]
    ]
    if income_basis == "SELF_DECLARED":
        candidates = [
            t for t in candidates
            if not t["requires_documentation"]
            and t["discount_pct"] <= SELF_DECLARE_MAX_DISCOUNT_PCT
        ]
    if not candidates:
        raise ApiError(
            ERR_NO_ELIGIBLE_TIER,
            "No FeeScheduleTier band matches fpl_pct under the income_basis variant filter",
            422,
        )
    candidates.sort(
        key=lambda t: (-t["discount_pct"], t["fpl_pct_min_inclusive"], t["_created_seq"])
    )
    return candidates[0]


def sliding_fee_charge(full_fee_cents, tier):
    discount = (full_fee_cents * tier["discount_pct"]) // 100  # floor discount first
    charge = full_fee_cents - discount
    return max(charge, tier["nominal_copay_cents"])


def find_catalog_entry(affiliate_id, service_code):
    for e in store.catalog_entries.values():
        if e["affiliate_id"] == affiliate_id and e["service_code"] == service_code:
            return e
    return None


def compute_patient_charge(encounter, assessment):
    entry = find_catalog_entry(encounter["affiliate_id"], encounter["service_code"])
    if entry is None:
        return encounter.get("patient_charge_cents", 0)
    tier = None
    for t in store.fee_tiers.values():
        if t["affiliate_id"] == encounter["affiliate_id"] and t["tier_code"] == assessment["assigned_tier_code"]:
            tier = t
            break
    if tier is None:
        return encounter.get("patient_charge_cents", 0)
    return sliding_fee_charge(entry["full_fee_cents"], tier)


# ---------------------------------------------------------------------------
# Serializers (strip internal keys, refresh derived fields)
# ---------------------------------------------------------------------------

def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_affiliate(a):
    return _public(a)


def serialize_catalog_entry(e):
    return _public(e)


def serialize_tier(t):
    return _public(t)


def serialize_patient(p):
    out = _public(p)
    out["is_minor"] = patient_is_minor(p)
    p["is_minor"] = out["is_minor"]
    return out


def serialize_assessment(a):
    return _public(a)


def serialize_provider(p):
    return _public(p)


def serialize_license(lic):
    out = _public(lic)
    out["status"] = license_derived_status(lic)
    lic["status"] = out["status"]
    return out


def serialize_encounter(e):
    return _public(e)


def serialize_claim(c):
    return _public(c)


def serialize_lot(l):
    return _public(l)


def serialize_reservation(r):
    return _public(r)


def serialize_referral(r):
    return _public(r)


def serialize_grant_report(r):
    return _public(r)


def serialize_privacy_hold(h):
    return _public(h)
