"""In-memory data store, logical clock, response envelope and auth helpers.

Storage is deliberately in-memory only: plain dicts keyed by id. Nothing is
seeded, preloaded or hardcoded here -- the store starts empty on every boot and
every entity is constructed by a client through the declared API surface.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from errors import ApiError, ERROR_STATUS
from errors import as_int, as_number

# =============================================================================
# In-memory tables (all empty at boot)
# =============================================================================
DB = {
    "bureaus": {},
    "score_models": {},
    "score_variants": {},
    "consumers": {},
    "archive_samples": {},
    "validation_studies": {},
    "reference_sets": {},
    "score_results": {},
    "reason_codes": {},
    "licenses": {},
    "fee_ledger_entries": {},
    "model_documentation": {},
    "migration_events": {},
    "score_discovery_requests": {},
}

# Insertion-ordered id logs, used for deterministic ordering of same-timestamp
# rows (created_at ties break by order of creation).
ORDER = {name: [] for name in DB}

# Logical clock -- fixed default, never falls back to wall-clock time.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
CLOCK = {"now": None}

DISCOVERY_SWEEP_HOURS = 720

ROLES = [
    "BureauAdministrator",
    "ModelDeveloper",
    "ValidationAnalyst",
    "ComplianceOfficer",
    "FairLendingOfficer",
    "ReasonCodeAdministrator",
    "ScoreConsumer",
]


def reset():
    for name, table in DB.items():
        table.clear()
        ORDER[name].clear()
    CLOCK["now"] = None


# =============================================================================
# Logical clock / timestamps
# =============================================================================
def now():
    if CLOCK["now"] is None:
        return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    return CLOCK["now"]


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(now())


def parse_iso(text):
    if not isinstance(text, str):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 string.")
    try:
        cleaned = text.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_month(text):
    if not isinstance(text, str):
        raise ApiError("ERR_INVALID_REQUEST", "month must be a YYYY-MM string.")
    parts = text.strip().split("-")
    if len(parts) != 2:
        raise ApiError("ERR_INVALID_REQUEST", "month must be a YYYY-MM string.")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "month must be a YYYY-MM string.")
    if not (1 <= month <= 12):
        raise ApiError("ERR_INVALID_REQUEST", "month must be a YYYY-MM string.")
    return datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)


MONTH_MIN = (2015, 1)
SAMPLE_WINDOW_MAX = (2026, 9)
LICENSE_WINDOW_MAX = (2032, 12)


def month_tuple(text):
    parts = str(text).split("-")
    if len(parts) != 2:
        raise ApiError("ERR_INVALID_REQUEST", "Expected a YYYY-MM month.")
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Expected a YYYY-MM month.")


# =============================================================================
# Ids and record scaffolding
# =============================================================================
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(16))


def new_record(common=True, version=1):
    rec = {"id": new_id(), "created_at": now_iso()}
    if common:
        rec["updated_at"] = now_iso()
        rec["version"] = version
    return rec


def touch(rec):
    """Advance updated_at and version on a mutable record (PRD §2.4).

    An append-only ledger row (FeeLedgerEntry, MigrationEvent) deliberately has no
    mutable timeline — it carries only id and created_at (PRD §2.4) — so a touch
    against one must not mint a `version`.
    """
    if "created_at" in rec and "id" in rec and "version" not in rec and "updated_at" not in rec:
        return
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = now_iso()
    else:
        rec["updated_at"] = now_iso()


def store(name, rec):
    DB[name][rec["id"]] = rec
    ORDER[name].append(rec["id"])
    return rec


def table(name):
    return DB[name]


def ordered_ids(name):
    return ORDER[name]


def ordered_rows(name, predicate=None):
    """Rows of a table in created_at-ascending creation order."""
    rows = [DB[name][i] for i in ORDER[name]]
    if predicate:
        rows = [r for r in rows if predicate(r)]
    return rows


# =============================================================================
# Numeric helpers (PRD §2.6)
# =============================================================================
def half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def floor_zero(value):
    from decimal import ROUND_DOWN
    return Decimal(value).to_integral_value(rounding=ROUND_DOWN)


def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_int(value):
    from decimal import ROUND_CEILING
    return int(Decimal(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


def dec_out(value, places=4):
    """Render a Decimal with a fixed number of decimals as a JSON number."""
    d = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return float(d)


def jsonable(rec):
    """Convert Decimal-valued fields into JSON numbers for the wire."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = [float(v) if isinstance(v, Decimal) else v for v in value]
        else:
            out[key] = value
    return out


# =============================================================================
# Response envelope (PRD §2.2 / scaffold response_envelope)
# =============================================================================
def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": iso(datetime.now(timezone.utc))}
    if extra:
        meta.update(extra)
    return meta


def ok(data, http_status=200, response_type="object"):
    if isinstance(data, dict):
        data = jsonable(data)
    return {"meta": _meta(), "response_type": response_type, "data": data}, http_status


def ok_list(rows, limit, offset, total_count):
    payload = [jsonable(row) for row in rows]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(payload)) < total_count,
    }
    return {"meta": _meta(meta_extra), "response_type": "array", "data": payload}, 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# =============================================================================
# Auth (PRD §2.1, validations priority 1-3)
# =============================================================================
def authenticate(request):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return role, user_id


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def resolve_actor(request, allowed_roles, license_id=None):
    """Authenticate, authorise, and enforce the role-identity binding.

    For ScoreConsumer the backing entity is the License that covers the write:
    X-User-ID must name an existing License. When license_id is supplied (the
    posting path) the binding is deferred so that ERR_LICENSE_NOT_OWNED can be
    raised in its declared precedence slot.
    """
    role, user_id = authenticate(request)
    authorize(role, allowed_roles)
    if role == "ScoreConsumer" and license_id is None:
        if user_id not in DB["licenses"]:
            raise ApiError("ERR_UNAUTHORIZED")
    return role, user_id


# =============================================================================
# Pagination (PRD §2.3)
# =============================================================================
def read_pagination(request):
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def ascend_ids(name):
    """Ids of a table ordered by created_at ascending, ties by creation order."""
    ids = ORDER[name]
    with_time = sorted(ids, key=lambda i: (DB[name][i]["created_at"], ids.index(i)))
    return with_time


def filter_args(request, mapping):
    """Return {field: parsed} for query args present in mapping(field -> parser)."""
    out = {}
    for param, parser in mapping.items():
        raw = request.args.get(param)
        if raw is not None:
            out[param] = parser(raw)
    return out


def as_bool(raw):
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        low = raw.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    raise ApiError("ERR_INVALID_REQUEST", "Expected a boolean.")


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset: offset + limit]
    return page, total


# =============================================================================
# Body parsing
# =============================================================================
def body_of(request):
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def reject_unknown(body, allowed):
    for key in body:
        if key not in allowed:
            raise ApiError("ERR_INVALID_REQUEST", f"Unknown field '{key}'.")


def require_fields(body, names):
    for name in names:
        if name not in body:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field '{name}'.")


def as_str(value, field="value"):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", f"'{field}' must be a non-empty string.")
    return value


def as_enum(value, allowed, field="value"):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"'{field}' must be one of {sorted(allowed)}.")
    return value


# =============================================================================
# Optimistic concurrency (validations priority 20)
# =============================================================================
def check_occ(rec, body, field):
    if field in body and body[field] is not None:
        expected = as_int(body[field])
        if expected != rec["version"]:
            raise ApiError("ERR_STALE_VERSION")


# =============================================================================
# Entity resolution (validations priority 4 / 5)
# =============================================================================
def get_or_404(name, ident, error_id, label):
    rec = DB[name].get(ident)
    if rec is None:
        raise ApiError(error_id, f"No {label} carries the requested id.")
    return rec


def bureau(ident):
    return get_or_404("bureaus", ident, "ERR_BUREAU_NOT_FOUND", "Bureau")


def score_model(ident):
    return get_or_404("score_models", ident, "ERR_SCORE_MODEL_NOT_FOUND", "ScoreModel")


def score_variant(ident):
    return get_or_404("score_variants", ident, "ERR_SCORE_VARIANT_NOT_FOUND", "ScoreVariant")


def consumer(ident):
    return get_or_404("consumers", ident, "ERR_CONSUMER_NOT_FOUND", "Consumer")


def archive_sample(ident):
    return get_or_404("archive_samples", ident, "ERR_ARCHIVE_SAMPLE_NOT_FOUND", "ArchiveSample")


def validation_study(ident):
    return get_or_404("validation_studies", ident, "ERR_VALIDATION_STUDY_NOT_FOUND", "ValidationStudy")


def reference_set(ident):
    return get_or_404("reference_sets", ident, "ERR_REFERENCE_SET_NOT_FOUND", "ReferenceSet")


def score_result(ident):
    return get_or_404("score_results", ident, "ERR_SCORE_RESULT_NOT_FOUND", "ScoreResult")


def reason_code(ident):
    return get_or_404("reason_codes", ident, "ERR_REASON_CODE_NOT_FOUND", "ReasonCode")


def license_rec(ident):
    return get_or_404("licenses", ident, "ERR_LICENSE_NOT_FOUND", "License")


def model_documentation(ident):
    return get_or_404("model_documentation", ident, "ERR_MODEL_DOCUMENTATION_NOT_FOUND", "ModelDocumentation")


def migration_event(ident):
    return get_or_404("migration_events", ident, "ERR_MIGRATION_EVENT_NOT_FOUND", "MigrationEvent")


def discovery_request(ident):
    return get_or_404("score_discovery_requests", ident, "ERR_DISCOVERY_REQUEST_NOT_FOUND", "ScoreDiscoveryRequest")


def fee_ledger_entry(ident):
    return get_or_404("fee_ledger_entries", ident, "ERR_FEE_LEDGER_ENTRY_NOT_FOUND", "FeeLedgerEntry")