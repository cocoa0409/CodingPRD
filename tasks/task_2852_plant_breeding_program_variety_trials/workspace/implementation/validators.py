"""Request-shape validation (PRD 2.7 step 3) and pagination (PRD 2.3)."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import bad_request

MISSING = object()

# ---- enumerations ----------------------------------------------------------
ROLES = ["PipelineDirector", "ProgramLead", "BreedingScientist", "TrialAgronomist",
         "DataAnalyst", "RegulatoryOfficer", "SupplyPlanner"]
CROP_CODES = ["MAIZE", "SOYBEAN", "WHEAT", "CANOLA"]
DISEASE_TRAITS = ["GLS", "NCLB", "SCLB", "RUST", "SDS", "PHYTOPHTHORA"]
QUALITY_SPECS = ["TEST_WEIGHT_MIN", "PROTEIN_MIN", "OIL_MIN", "MOISTURE_MAX"]
QUALITY_TRAITS = ["TEST_WEIGHT", "PROTEIN", "OIL", "MOISTURE"]
NURSERY_TYPES = ["WINTER", "SUMMER"]
ENVIRONMENT_CLASSES = ["HIGH_YIELD_IRRIGATED", "RAINFED_TEMPERATE", "DROUGHT_STRESS", "DISEASE_NURSERY"]
SERIES_STAGES = ["STAGE_1", "STAGE_2", "STAGE_3"]
PLOT_DESIGNS = ["RCBD", "AUGMENTED", "ALPHA_LATTICE"]
TRAIT_CODES = ["YIELD_KG_PLOT", "TEST_WEIGHT", "PROTEIN_PCT", "OIL_PCT", "MOISTURE_PCT", "DISEASE_SEVERITY"]
QC_STATUSES = ["ACCEPTED", "REJECTED"]
ANALYSIS_VARIANTS = ["UNBALANCED_INCLUSIVE", "BALANCED_CORE"]
DECISIONS = ["ADVANCE", "HOLD", "DISCARD"]
REVIEW_OUTCOMES = ["APPROVE", "REQUEST_CHANGES"]
PIPELINE_STAGES = ["NURSERY", "STAGE_1", "STAGE_2", "STAGE_3", "PRE_COMMERCIAL", "COMMERCIAL", "DISCARDED"]
STEWARDSHIP_STATUSES = ["NOT_REQUIRED", "PENDING", "APPROVED", "SUSPENDED"]

WINTER_MONTHS = {10, 11, 12, 1, 2}
SUMMER_MONTHS = {4, 5, 6, 7, 8}


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------
def json_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


# ---------------------------------------------------------------------------
# scalar readers
# ---------------------------------------------------------------------------
def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad_request("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad_request("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(body, name, default=None, min_len=None, max_len=None):
    if not _present(body, name):
        return default
    return req_str(body, name, min_len=min_len, max_len=max_len)


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def _to_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad_request("Field '%s' must be a number." % name)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad_request("Field '%s' must be a number." % name)


def req_num(body, name, gt=None, ge=None, le=None):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = _to_decimal(name, body[name])
    if gt is not None and not value > Decimal(str(gt)):
        bad_request("Field '%s' must be greater than %s." % (name, gt))
    if ge is not None and value < Decimal(str(ge)):
        bad_request("Field '%s' must be >= %s." % (name, ge))
    if le is not None and value > Decimal(str(le)):
        bad_request("Field '%s' must be <= %s." % (name, le))
    return value


def opt_num(body, name, default=None, gt=None, ge=None, le=None):
    if not _present(body, name):
        return default
    return req_num(body, name, gt=gt, ge=ge, le=le)


def req_bool(body, name):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_id(body, name):
    return req_str(body, name)


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or len(value) == 0:
        bad_request("Field '%s' must be a string identifier." % name)
    return value


# ---------------------------------------------------------------------------
# dates and instants (PRD 2.5)
# ---------------------------------------------------------------------------
def parse_date_only(name, value):
    if not isinstance(value, str) or len(value) != 10:
        bad_request("Field '%s' must be a date-only value in YYYY-MM-DD form." % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        bad_request("Field '%s' must be a date-only value in YYYY-MM-DD form." % name)


def req_date(body, name):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    return parse_date_only(name, body[name])


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return parse_date_only(name, body[name])


def req_instant(body, name):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        bad_request("Field '%s' must be an ISO 8601 UTC instant." % name)
    text = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    bad_request("Field '%s' must be an instant of the form YYYY-MM-DDTHH:MM:SSZ." % name)


# ---------------------------------------------------------------------------
# maps and arrays
# ---------------------------------------------------------------------------
def opt_score_map(body, name, allowed_keys, lo, hi):
    if not _present(body, name):
        return {}
    value = body[name]
    if not isinstance(value, dict):
        bad_request("Field '%s' must be an object." % name)
    out = {}
    for key, raw in value.items():
        if key not in allowed_keys:
            bad_request("Field '%s' contains unknown key '%s'." % (name, key))
        if isinstance(raw, bool) or not isinstance(raw, int):
            bad_request("Field '%s' values must be integers." % name)
        if raw < lo or raw > hi:
            bad_request("Field '%s' values must be between %d and %d." % (name, lo, hi))
        out[key] = raw
    return out


def opt_value_map(body, name, allowed_keys):
    if not _present(body, name):
        return {}
    value = body[name]
    if not isinstance(value, dict):
        bad_request("Field '%s' must be an object." % name)
    out = {}
    for key, raw in value.items():
        if key not in allowed_keys:
            bad_request("Field '%s' contains unknown key '%s'." % (name, key))
        out[key] = _to_decimal("%s.%s" % (name, key), raw)
    return out


def req_str_array(body, name, min_items=1):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % name)
    if len(value) < min_items:
        bad_request("Field '%s' must contain at least %d element(s)." % (name, min_items))
    for item in value:
        if not isinstance(item, str) or len(item) == 0:
            bad_request("Field '%s' must contain non-empty strings." % name)
    return list(value)


def opt_enum_array(body, name, allowed):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad_request("Field '%s' elements must be one of %s." % (name, ", ".join(allowed)))
    return list(value)


def req_market_allocations(body, name):
    if not _present(body, name):
        bad_request("Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, list) or len(value) == 0:
        bad_request("Field '%s' must be a non-empty array." % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            bad_request("Field '%s' elements must be objects." % name)
        code = item.get("market_code")
        if not isinstance(code, str) or len(code) == 0:
            bad_request("Each market allocation needs a non-empty market_code.")
        if "demand_kg" not in item or item["demand_kg"] is None:
            bad_request("Each market allocation needs a demand_kg greater than 0.")
        demand = _to_decimal("demand_kg", item["demand_kg"])
        if demand <= 0:
            bad_request("Each market allocation needs a demand_kg greater than 0.")
        out.append({"market_code": code, "demand_kg": demand})
    return out


# ---------------------------------------------------------------------------
# pagination + query filters
# ---------------------------------------------------------------------------
def _query_int(name, raw):
    text = raw.strip()
    if text == "":
        bad_request("Query parameter '%s' must be an integer." % name)
    try:
        return int(text)
    except ValueError:
        bad_request("Query parameter '%s' must be an integer." % name)


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        limit = _query_int("limit", args.get("limit"))
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        offset = _query_int("offset", args.get("offset"))
        if offset < 0:
            bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        bad_request("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_int(name):
    if name not in request.args:
        return None
    return _query_int(name, request.args.get(name))


def query_bool(name):
    if name not in request.args:
        return None
    value = request.args.get(name).strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be true or false." % name)


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
