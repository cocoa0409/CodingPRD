"""Core infrastructure: in-memory store, logical clock, envelope, errors, auth.

Storage is plain in-process Python dicts and starts completely EMPTY on every
boot.  Nothing is seeded, preloaded or hardcoded.
"""

import json
import random
import string
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
from fractions import Fraction

from flask import request, Response

# --------------------------------------------------------------------------
# Error catalog (PRD section 5) -- error_id -> HTTP status
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_TERRITORY_OWNERSHIP_REQUIRED": 403,
    "ERR_DESIGNER_OWNERSHIP_REQUIRED": 403,
    "ERR_MOTORIZATION_CERT_REQUIRED": 403,
    "ERR_TERRITORY_NOT_FOUND": 404,
    "ERR_DESIGNER_NOT_FOUND": 404,
    "ERR_SAMPLE_KIT_NOT_FOUND": 404,
    "ERR_LEAD_NOT_FOUND": 404,
    "ERR_CONSULTATION_NOT_FOUND": 404,
    "ERR_SAMPLE_CHECKOUT_NOT_FOUND": 404,
    "ERR_OPENING_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_VENDOR_ORDER_NOT_FOUND": 404,
    "ERR_INSTALL_JOB_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_CROSS_TERRITORY_FORBIDDEN": 422,
    "ERR_OPENING_NOT_ON_QUOTE": 422,
    "ERR_NO_ELIGIBLE_VENDOR": 422,
    "ERR_STALE_CONSULTATION_VERSION": 412,
    "ERR_STALE_QUOTE_VERSION": 412,
    "ERR_TERRITORY_NOT_ACTIVE": 409,
    "ERR_DESIGNER_NOT_ACTIVE": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_QUOTE_NOT_DRAFT": 409,
    "ERR_QUOTE_NOT_PRESENTED": 409,
    "ERR_QUOTE_NOT_ACCEPTED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_QUOTE_HAS_NO_OPENINGS": 422,
    "ERR_CONSULTATION_NOT_SCHEDULED": 409,
    "ERR_CONSULTATION_CLOSED": 409,
    "ERR_KIT_NOT_AVAILABLE": 409,
    "ERR_CHECKOUT_NOT_OPEN": 409,
    "ERR_OPENING_NOT_MEASURED": 409,
    "ERR_OPENING_ALREADY_ORDERED": 409,
    "ERR_ORDER_NOT_SHIPPABLE": 409,
    "ERR_ORDER_NOT_SHIPPED": 409,
    "ERR_ORDER_NOT_RECEIVED": 409,
    "ERR_INSTALL_JOB_NOT_SCHEDULED": 409,
    "ERR_COMMISSIONING_NOT_APPLICABLE": 409,
    "ERR_COMMISSIONING_NOT_PAIRED": 409,
    "ERR_COMMISSIONING_NOT_VERIFIED": 409,
    "ERR_CORD_HAZARD_NOT_PERMITTED": 422,
    "ERR_INSUFFICIENT_MOUNT_DEPTH": 422,
    "ERR_HUB_PLATFORM_UNSUPPORTED": 422,
    "ERR_CHANNEL_COUNT_EXCEEDS_ORDER": 422,
    "ERR_COMMISSIONING_ATTEMPT_LIMIT": 409,
    "ERR_MOTOR_OPTION_MISMATCH": 422,
    "ERR_REMAKE_NOT_OFFERED": 422,
    "ERR_REMAKE_LIMIT_REACHED": 409,
    "ERR_OPENINGS_ALREADY_RESOLVED": 409,
    "ERR_DESIGNER_CALENDAR_CONFLICT": 409,
    "ERR_SAMPLE_KIT_HOLD_CONFLICT": 409,
    "ERR_VENDOR_CAPACITY_EXCEEDED": 409,
    "ERR_REMAKE_WINDOW_CLOSED": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
ROLE_FRANCHISOR = "Franchisor"
ROLE_FRANCHISEE = "Franchisee"
ROLE_DESIGNER = "Designer"
ROLE_VENDOR_REP = "VendorRep"
ALL_ROLES = (ROLE_FRANCHISOR, ROLE_FRANCHISEE, ROLE_DESIGNER, ROLE_VENDOR_REP)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


# --------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.territories = {}
        self.designers = {}
        self.sample_kits = {}
        self.leads = {}
        self.consultations = {}
        self.sample_checkouts = {}
        self.openings = {}
        self.quotes = {}
        self.vendors = {}
        self.vendor_orders = {}
        self.install_jobs = {}
        self.ledger_entries = {}
        self.clock = parse_instant_strict(DEFAULT_CLOCK)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Instants
# --------------------------------------------------------------------------
def parse_instant_strict(value):
    """Parse an ISO-8601 UTC instant string.  Returns tz-aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    # ISO 8601 requires the literal "T" between the date and the time, and the
    # PRD requires a UTC instant, so an explicit UTC designator must be present.
    if "T" not in raw:
        return None
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    elif not (txt.endswith("+00:00") or txt.endswith("-00:00")):
        return None
    try:
        dt = datetime.fromisoformat(txt)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": fmt_instant(datetime.now(timezone.utc)),
    }


def to_json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, datetime):
        return fmt_instant(value)
    if isinstance(value, date):
        return fmt_date(value)
    if isinstance(value, list):
        return [to_json(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    return value


def serialize(row):
    return {k: to_json(v) for k, v in row.items() if not k.startswith("_")}


def _emit(payload, status):
    return Response(
        json.dumps(payload, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def respond_object(data, status=200):
    payload = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _emit(payload, status)


def respond_empty(status=200):
    return respond_object({}, status)


def respond_list(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return _emit(payload, status)


def respond_error(error_id, message, status):
    payload = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)


# --------------------------------------------------------------------------
# Store singleton
# --------------------------------------------------------------------------
store = Store()


def now_dt():
    return store.clock


def new_row(fields, common=True):
    row = {"id": new_id()}
    row.update(fields)
    if common:
        row["created_at"] = store.clock
        row["updated_at"] = store.clock
        row["version"] = 1
    else:
        row["created_at"] = store.clock
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    row["updated_at"] = store.clock
    row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows, primary="created_at"):
    return sorted(rows, key=lambda r: (r[primary], r["_seq"]))


def sort_ledger(rows):
    return sorted(rows, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Authentication / authorization (PRD 2.1, ladder stages 1-2)
# --------------------------------------------------------------------------
class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.territory = None
        self.designer = None
        self.vendor = None

    @property
    def is_franchisor(self):
        return self.role == ROLE_FRANCHISOR

    @property
    def is_franchisee(self):
        return self.role == ROLE_FRANCHISEE

    @property
    def is_designer(self):
        return self.role == ROLE_DESIGNER

    @property
    def is_vendor_rep(self):
        return self.role == ROLE_VENDOR_REP


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "missing user identity header")
    if role is None or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "unknown or missing role")
    actor = Actor(user_id, role)
    if role == ROLE_FRANCHISEE:
        territory = store.territories.get(user_id)
        if territory is None:
            fail("ERR_UNAUTHENTICATED", "identity does not resolve to a territory")
        actor.territory = territory
    elif role == ROLE_DESIGNER:
        designer = store.designers.get(user_id)
        if designer is None:
            fail("ERR_UNAUTHENTICATED", "identity does not resolve to a designer")
        actor.designer = designer
    elif role == ROLE_VENDOR_REP:
        vendor = store.vendors.get(user_id)
        if vendor is None:
            fail("ERR_UNAUTHENTICATED", "identity does not resolve to a vendor")
        actor.vendor = vendor
    return actor


def require(actor, *roles):
    if actor.role not in roles:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % actor.role)
    return actor


def auth(*roles):
    """Ladder stage 1 then stage 2."""
    actor = authenticate()
    require(actor, *roles)
    return actor


# --------------------------------------------------------------------------
# Request body / field primitives (ladder stage 7 unless noted)
# --------------------------------------------------------------------------
def get_body():
    raw = request.get_data() or b""
    if not raw.strip():
        return {}
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        fail("ERR_INVALID_REQUEST", "body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "body must be a JSON object")
    return body


def present(body, key):
    return key in body and body[key] is not None


def _bad(key, why):
    fail("ERR_INVALID_REQUEST", "field %s %s" % (key, why))


def req_str(body, key, min_len=1, max_len=None):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if len(value) < min_len:
        _bad(key, "is too short")
    if max_len is not None and len(value) > max_len:
        _bad(key, "is too long")
    return value


def opt_str(body, key, default=None, min_len=1, max_len=None):
    if not present(body, key):
        return default
    return req_str(body, key, min_len, max_len)


def req_int(body, key):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    return value


def opt_int(body, key, default=None):
    if not present(body, key):
        return default
    return req_int(body, key)


def req_num(body, key):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    try:
        return Decimal(str(value))
    except Exception:
        _bad(key, "must be a number")


def opt_num(body, key, default=None):
    if not present(body, key):
        return default
    return req_num(body, key)


def req_bool(body, key):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def opt_bool(body, key, default=None):
    if not present(body, key):
        return default
    return req_bool(body, key)


def req_enum(body, key, allowed):
    value = req_str(body, key, 1, None)
    if value not in allowed:
        _bad(key, "is not a declared enum member")
    return value


def opt_enum(body, key, allowed, default=None):
    if not present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_instant(body, key):
    value = req_str(body, key, 1, None)
    parsed = parse_instant_strict(value)
    if parsed is None:
        _bad(key, "is not a valid ISO 8601 UTC instant")
    return parsed


def opt_instant(body, key, default=None):
    if not present(body, key):
        return default
    return req_instant(body, key)


def req_list(body, key, min_items=1, max_items=None, unique=True):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if not isinstance(value, list):
        _bad(key, "must be an array")
    if len(value) < min_items:
        _bad(key, "has too few entries")
    if max_items is not None and len(value) > max_items:
        _bad(key, "has too many entries")
    for item in value:
        if not isinstance(item, str):
            _bad(key, "entries must be strings")
    if unique and len(set(value)) != len(value):
        _bad(key, "contains duplicate entries")
    return value


def req_enum_list(body, key, allowed, min_items=1, max_items=None):
    value = req_list(body, key, min_items, max_items, True)
    for item in value:
        if item not in allowed:
            _bad(key, "contains an undeclared enum member")
    return value


def opt_enum_list(body, key, allowed, default=None, min_items=0, max_items=None):
    if not present(body, key):
        return list(default) if default is not None else []
    return req_enum_list(body, key, allowed, min_items, max_items)


def check_postal(value, key):
    if len(value) != 5 or not value.isdigit():
        _bad(key, "must be exactly five digits")
    return value


def req_postal(body, key):
    return check_postal(req_str(body, key, 1, None), key)


def dec_places(value):
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        _bad("value", "is not a finite number")
    return max(0, -exponent)


def out_of_range(message):
    fail("ERR_VALUE_OUT_OF_RANGE", message)


def check_range(condition, message):
    """Ladder stage 8."""
    if not condition:
        out_of_range(message)


# --------------------------------------------------------------------------
# Pagination and filters (PRD 2.3)
# --------------------------------------------------------------------------
def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except Exception:
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            out_of_range("limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except Exception:
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            out_of_range("offset may not be negative")
    return limit, offset


def apply_filters(rows, names):
    """Conjunctive equality filters straight off the query string."""
    out = rows
    for name in names:
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        out = [r for r in out if _matches(r.get(name), raw)]
    return out


def _matches(stored, raw):
    if stored is None:
        return False
    if isinstance(stored, bool):
        return raw.lower() == ("true" if stored else "false")
    return str(stored) == raw


def list_response(rows, filters=()):
    limit, offset = parse_pagination()
    rows = apply_filters(list(rows), filters)
    rows = sort_rows(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return respond_list([serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Existence lookups (ladder stages 3 and 4)
# --------------------------------------------------------------------------
def _lookup(table, entity_id, error_id):
    if not isinstance(entity_id, str):
        fail(error_id, "unknown identifier")
    row = table.get(entity_id)
    if row is None:
        fail(error_id, "unknown identifier")
    return row


def get_territory(entity_id):
    return _lookup(store.territories, entity_id, "ERR_TERRITORY_NOT_FOUND")


def get_designer(entity_id):
    return _lookup(store.designers, entity_id, "ERR_DESIGNER_NOT_FOUND")


def get_kit(entity_id):
    return _lookup(store.sample_kits, entity_id, "ERR_SAMPLE_KIT_NOT_FOUND")


def get_lead(entity_id):
    return _lookup(store.leads, entity_id, "ERR_LEAD_NOT_FOUND")


def get_consultation(entity_id):
    return _lookup(store.consultations, entity_id, "ERR_CONSULTATION_NOT_FOUND")


def get_checkout(entity_id):
    return _lookup(store.sample_checkouts, entity_id, "ERR_SAMPLE_CHECKOUT_NOT_FOUND")


def get_opening(entity_id):
    return _lookup(store.openings, entity_id, "ERR_OPENING_NOT_FOUND")


def get_quote(entity_id):
    return _lookup(store.quotes, entity_id, "ERR_QUOTE_NOT_FOUND")


def get_vendor(entity_id):
    return _lookup(store.vendors, entity_id, "ERR_VENDOR_NOT_FOUND")


def get_order(entity_id):
    return _lookup(store.vendor_orders, entity_id, "ERR_VENDOR_ORDER_NOT_FOUND")


def get_job(entity_id):
    return _lookup(store.install_jobs, entity_id, "ERR_INSTALL_JOB_NOT_FOUND")


def req_fk(body, key, getter, optional=False):
    """Ladder stage 4: resolve a body reference before the shape stage.

    Absent / wrong-typed values are left for the shape stage to reject.
    """
    if not present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str):
        return None
    return getter(value)


# --------------------------------------------------------------------------
# Reverse reachability helpers
# --------------------------------------------------------------------------
def territory_id_of_lead(lead):
    return lead.get("territory_id")


def territory_of_lead(lead):
    tid = lead.get("territory_id")
    return store.territories.get(tid) if tid else None


def territory_of_consultation(consultation):
    lead = store.leads.get(consultation["lead_id"])
    return territory_of_lead(lead) if lead else None


def territory_of_quote(quote):
    lead = store.leads.get(quote["lead_id"])
    return territory_of_lead(lead) if lead else None


def territory_of_opening(opening):
    consultation = store.consultations.get(opening["consultation_id"])
    return territory_of_consultation(consultation) if consultation else None


def territory_of_order(order):
    quote = store.quotes.get(order["quote_id"])
    return territory_of_quote(quote) if quote else None


def territory_of_job(job):
    order = store.vendor_orders.get(job["vendor_order_id"])
    return territory_of_order(order) if order else None


def openings_of_quote(quote_id):
    return [o for o in store.openings.values() if o.get("quote_id") == quote_id]


def openings_of_order(order):
    return [store.openings[oid] for oid in order["opening_ids"] if oid in store.openings]


# --------------------------------------------------------------------------
# Ownership (ladder stages 5 and 6)
# --------------------------------------------------------------------------
def require_territory_ownership(actor, territory_id):
    """Stage 5 -- a Franchisee may only touch rows of its own territory.

    PRD 2.1 scopes the check to a row "belonging to another territory", and to
    "any row that references a territory".  A row whose territory linkage is
    null -- a QUEUED or UNROUTABLE lead -- references no territory at all and so
    belongs to no other territory; it is not withheld from any franchise owner.
    """
    if actor.is_franchisee and territory_id is not None and territory_id != actor.user_id:
        fail("ERR_TERRITORY_OWNERSHIP_REQUIRED", "row belongs to another territory")


def require_territory_ownership_row(actor, territory):
    require_territory_ownership(actor, territory["id"] if territory else None)


def require_designer_assignment(actor, designer_id):
    """Stage 6 -- the acting Designer must be the assigned one."""
    if actor.is_designer and actor.user_id != designer_id:
        fail("ERR_DESIGNER_OWNERSHIP_REQUIRED", "acting designer is not assigned")


def require_territory_active(territory):
    """Stage 12."""
    if territory is not None and territory["status"] != "ACTIVE":
        fail("ERR_TERRITORY_NOT_ACTIVE", "territory status is %s" % territory["status"])


def require_designer_active(designer):
    """Stage 13."""
    if designer["status"] != "ACTIVE":
        fail("ERR_DESIGNER_NOT_ACTIVE", "designer status is %s" % designer["status"])


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------
def money(value):
    """Round to a whole cent, half up."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    elif not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def royalty_on(territory, basis_cents):
    return money(Decimal(int(basis_cents)) * territory["royalty_rate_pct"])


# --------------------------------------------------------------------------
# Derived counters -- always re-derived, never incremented in place
# --------------------------------------------------------------------------
OPEN_LEAD_STATUSES = ("ROUTED", "CONSULT_COMPLETE")
LIVE_ORDER_STATUSES = ("PLACED", "SHIPPED", "REMAKE_REQUESTED")
ROYALTY_TYPES = ("NET_SALES_ROYALTY", "ROYALTY_REVERSAL")
CHARGEBACK_TYPES = ("REMAKE_CHARGEBACK", "REMEASURE_CHARGEBACK")


def rederive_territory(territory, bump=True):
    tid = territory["id"]
    territory["open_leads_count"] = len([
        l for l in store.leads.values()
        if l.get("territory_id") == tid and l["status"] in OPEN_LEAD_STATUSES
    ])
    exposure = 0
    for order in store.vendor_orders.values():
        if order["status"] in LIVE_ORDER_STATUSES:
            t = territory_of_order(order)
            if t is not None and t["id"] == tid:
                exposure += order["order_cost_cents"]
    territory["open_order_exposure_cents"] = exposure
    kits = [k for k in store.sample_kits.values() if k["territory_id"] == tid]
    territory["available_kit_count"] = len([k for k in kits if k["status"] == "AVAILABLE"])
    territory["on_loan_kit_count"] = len([k for k in kits if k["status"] == "ON_LOAN"])
    territory["lost_kit_count"] = len([k for k in kits if k["status"] == "LOST"])
    rows = [e for e in store.ledger_entries.values() if e["territory_id"] == tid]
    territory["royalty_accrued_cents"] = sum(
        e["amount_cents"] for e in rows if e["entry_type"] in ROYALTY_TYPES)
    territory["remake_chargeback_cents"] = sum(
        e["amount_cents"] for e in rows if e["entry_type"] in CHARGEBACK_TYPES)
    if bump:
        touch(territory)
    return territory


def rederive_kit(kit, bump=True):
    kid = kit["id"]
    checkouts = [c for c in store.sample_checkouts.values() if c["sample_kit_id"] == kid]
    kit["loan_count"] = len(checkouts)
    kit["open_loan_count"] = len([c for c in checkouts if c["status"] == "OPEN"])
    if bump:
        touch(kit)
    return kit


def rederive_consultation(consultation, bump=True):
    cid = consultation["id"]
    openings = [o for o in store.openings.values() if o["consultation_id"] == cid]
    consultation["measured_opening_count"] = len([
        o for o in openings if o["measure_status"] in ("MEASURED", "CONFIGURED", "QUOTED")])
    consultation["configured_opening_count"] = len([
        o for o in openings if o["measure_status"] == "CONFIGURED"])
    consultation["open_sample_loan_count"] = len([
        c for c in store.sample_checkouts.values()
        if c["consultation_id"] == cid and c["status"] == "OPEN"])
    if bump:
        touch(consultation)
    return consultation


def rederive_quote_counts(quote, bump=False):
    openings = openings_of_quote(quote["id"])
    quote["opening_count"] = len(openings)
    quote["motorized_opening_count"] = len([
        o for o in openings if o.get("motorization_option") not in (None, "NONE")])
    if bump:
        touch(quote)
    return quote


def rederive_vendor(vendor, bump=True):
    vid = vendor["id"]
    vendor["open_order_count"] = len([
        o for o in store.vendor_orders.values()
        if o["vendor_id"] == vid and o["status"] in LIVE_ORDER_STATUSES])
    if bump:
        touch(vendor)
    return vendor


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
def append_ledger(territory, entry_type, amount_cents, basis_cents,
                  source_entity_type, source_entity_id, memo):
    row = new_row({
        "territory_id": territory["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "basis_cents": int(basis_cents),
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "occurred_at": store.clock,
        "memo": memo,
    }, common=False)
    store.ledger_entries[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# Lead capacity and queue promotion (PRD 3.1)
# --------------------------------------------------------------------------
def promote_queued_lead(territory):
    if territory["status"] != "ACTIVE":
        return None
    candidates = [
        l for l in store.leads.values()
        if l["status"] == "QUEUED" and l["postal_code"] in territory["postal_codes"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["created_at"], l["postal_code"],
                                   l["customer_name"], l["_seq"]))
    lead = candidates[0]
    lead["territory_id"] = territory["id"]
    lead["routed_at"] = store.clock
    lead["status"] = "ROUTED"
    touch(lead)
    rederive_territory(territory)
    return lead


def free_lead_capacity(territory):
    """A lead left the open bucket: re-derive the count, then promote one queued lead."""
    if territory is None:
        return None
    rederive_territory(territory)
    return promote_queued_lead(territory)


# --------------------------------------------------------------------------
# Designer liability score (PRD 3.9)
# --------------------------------------------------------------------------
BASE_SCORE = 100
REMEASURE_PENALTY = 22
LATE_SAMPLE_PENALTY = 9
CLEAN_INSTALL_CREDIT = 3
SUSPENSION_THRESHOLD = 80
LIABILITY_WINDOW_DAYS = 180


def _in_window(stamp, territory):
    if stamp is None:
        return False
    window = territory["liability_window"] if territory else "ROLLING_180D"
    if window == "LIFETIME":
        return True
    return stamp >= store.clock - timedelta(days=LIABILITY_WINDOW_DAYS)


def recompute_designer_score(designer):
    territory = store.territories.get(designer["territory_id"])
    did = designer["id"]
    jobs = [j for j in store.install_jobs.values() if j["designer_id"] == did]
    remeasure = len([
        j for j in jobs
        if j["install_status"] == "EXCEPTION_RAISED" and j["liable_party"] == "MEASURER"
        and _in_window(j.get("exception_raised_at"), territory)])
    my_consults = set(c["id"] for c in store.consultations.values()
                      if c["designer_id"] == did)
    late = len([
        c for c in store.sample_checkouts.values()
        if c["consultation_id"] in my_consults and c["days_late"] > 0
        and _in_window(c.get("returned_at"), territory)])
    clean = len([
        j for j in jobs
        if j["install_status"] == "COMPLETED" and j["exception_reason"] == "NONE"
        and _in_window(j.get("completed_at"), territory)])
    raw = (BASE_SCORE - REMEASURE_PENALTY * remeasure
           - LATE_SAMPLE_PENALTY * late + CLEAN_INSTALL_CREDIT * clean)
    score = max(0, min(BASE_SCORE, raw))
    changed = (designer["remeasure_exception_count"] != remeasure
               or designer["late_sample_return_count"] != late
               or designer["clean_install_count"] != clean
               or designer["remeasure_liability_score"] != score)
    designer["remeasure_exception_count"] = remeasure
    designer["late_sample_return_count"] = late
    designer["clean_install_count"] = clean
    designer["remeasure_liability_score"] = score
    if changed:
        touch(designer)
    if score < SUSPENSION_THRESHOLD and designer["status"] == "ACTIVE":
        designer["status"] = "SUSPENDED"
        if not changed:
            touch(designer)
        cancel_designer_bookings(designer)
    return designer


def cancel_designer_bookings(designer):
    """Suspension / retirement cascade (PRD 3.3, 3.9)."""
    did = designer["id"]
    for consultation in store.consultations.values():
        if (consultation["designer_id"] == did
                and consultation["status"] == "SCHEDULED"
                and consultation["scheduled_start_at"] >= store.clock):
            consultation["status"] = "CANCELLED"
            touch(consultation)
    for job in store.install_jobs.values():
        if (job["designer_id"] == did
                and job["install_status"] == "SCHEDULED"
                and job["scheduled_start_at"] >= store.clock):
            job["install_status"] = "CANCELLED"
            touch(job)


# --------------------------------------------------------------------------
# Shared designer calendar (PRD 3.3)
# --------------------------------------------------------------------------
TRAVEL_BUFFER = timedelta(minutes=45)


def calendar_occupations(designer_id):
    out = []
    for consultation in store.consultations.values():
        if consultation["designer_id"] == designer_id and consultation["status"] == "SCHEDULED":
            out.append((consultation["scheduled_start_at"],
                        consultation["scheduled_end_at"],
                        consultation["service_postal_code"]))
    for job in store.install_jobs.values():
        if job["designer_id"] == designer_id and job["install_status"] == "SCHEDULED":
            out.append((job["scheduled_start_at"], job["scheduled_end_at"],
                        job["service_postal_code"]))
    return out


def check_calendar_conflict(designer_id, start, end, postal_code):
    """Ladder stage 18."""
    for other_start, other_end, other_postal in calendar_occupations(designer_id):
        buffer = timedelta(0) if other_postal == postal_code else TRAVEL_BUFFER
        if start < other_end + buffer and other_start < end + buffer:
            fail("ERR_DESIGNER_CALENDAR_CONFLICT", "window collides with an existing appointment")


