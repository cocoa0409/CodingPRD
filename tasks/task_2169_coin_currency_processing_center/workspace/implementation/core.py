"""Core infrastructure: in-memory store, logical clock, envelope, errors, auth,
request-shape validation helpers.

Every structural name in this module (headers, envelope fields, pagination
parameter names, error ids, OCC field names) is taken verbatim from
workspace/PRD.md and SCAFFOLD.yaml for this task.
"""

import random
import re
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import request, jsonify, g

getcontext().prec = 60

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_VAULT_MANAGER = "VaultManager"
ROLE_VAULT_TELLER = "VaultTeller"
ROLE_ARMORED_CARRIER = "ArmoredCarrier"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_CUSTOMER = "CustomerAccountHolder"
ROLE_FED_AGENT = "FederalReserveAgent"

ALL_ROLES = {
    ROLE_VAULT_MANAGER,
    ROLE_VAULT_TELLER,
    ROLE_ARMORED_CARRIER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CUSTOMER,
    ROLE_FED_AGENT,
}

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# --------------------------------------------------------------------------
# Error catalogue (PRD 5)
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_ACCOUNT_OWNERSHIP": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VAULT_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_BAG_NOT_FOUND": 404,
    "ERR_MACHINE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_FED_DEPOSIT_NOT_FOUND": 404,
    "ERR_COIN_ORDER_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_BAG_NOT_RECEIVED": 409,
    "ERR_BAG_COUNT_MISMATCH": 409,
    "ERR_BAG_NOT_COUNTED": 409,
    "ERR_VAULT_FROZEN": 409,
    "ERR_VAULT_RESTRICTED": 409,
    "ERR_MACHINE_UNAVAILABLE": 409,
    "ERR_DUAL_CONTROL_VIOLATION": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_COUNTERFEIT_REPORT_PENDING": 409,
    "ERR_MACHINE_TYPE_MISMATCH": 422,
    "ERR_REPORT_LOT_MISMATCH": 422,
    "ERR_LOT_NOT_ELIGIBLE": 422,
    "ERR_LOT_VAULT_MISMATCH": 422,
    "ERR_MACHINE_WINDOW_CONFLICT": 409,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_PICKUP_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_DENOMINATION": 422,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_CLAIM_ROUND_LIMIT": 409,
    "ERR_DUPLICATE_SEAL": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_SEAL_TAMPERED": 409,
    "ERR_NO_ELIGIBLE_LOTS": 422,
    "ERR_LOT_TOTAL_MISMATCH": 422,
    "ERR_MATERIAL_VARIANCE_UNRESOLVED": 409,
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_INSUFFICIENT_COIN_INVENTORY": 409,
    "ERR_INVENTORY_NEGATIVE": 422,
    "ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED": 422,
    "ERR_RESOLUTION_EXCEEDS_CLAIM": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Global constants (SCAFFOLD global_constants + calculations)
# --------------------------------------------------------------------------
VARIANCE_MATERIALITY_CENTS = 2500
CLAIM_WINDOW_HOURS = 24
MAX_CLAIM_ROUNDS = 3
MACHINE_CLEANING_BUFFER_MINUTES = 15
DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

BASE_BAG_FEE_CENTS = Decimal(250)
PER_NOTE_RATE_MILLICENTS = Decimal(35)
PER_KG_COIN_RATE_CENTS = Decimal(180)
MIXED_HANDLING_SURCHARGE_CENTS = Decimal(125)

HAIRCUT_PCT_BY_TIER = {
    "PREMIUM": Decimal("0.00"),
    "STANDARD": Decimal("0.02"),
    "WATCH": Decimal("0.05"),
}
PROVISIONAL_CREDIT_CAP_CENTS = 5000000
VOLUME_TIER_1_CENTS = 2500000
VOLUME_TIER_2_CENTS = 10000000
VOLUME_DISCOUNT_1_PCT = Decimal("0.10")
VOLUME_DISCOUNT_2_PCT = Decimal("0.20")

VARIANCE_WEIGHT = Decimal("1.5")
COUNTERFEIT_WEIGHT = Decimal(8)
CLAIM_WEIGHT = Decimal(3)
SCORE_FLOOR = Decimal(0)
SCORE_CEILING = Decimal(100)
GRADE_A_MIN = Decimal(80)
GRADE_B_MIN = Decimal(60)
GRADE_C_MIN = Decimal(40)

COIN_VALUE_CENTS = {"PENNY": 1, "NICKEL": 5, "DIME": 10, "QUARTER": 25}
BOX_FACE_VALUE_CENTS = {"PENNY": 2500, "NICKEL": 10000, "DIME": 25000, "QUARTER": 50000}
DENOMINATIONS = ("PENNY", "NICKEL", "DIME", "QUARTER")

MACHINE_TYPE_ACCEPTS = {
    "CURRENCY_SORTER": {"CURRENCY"},
    "COIN_COUNTER": {"COIN"},
    "MIXED_PROCESSOR": {"CURRENCY", "COIN", "MIXED"},
}

# Enum vocabularies
VAULT_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
CUSTOMER_TIERS = ("PREMIUM", "STANDARD", "WATCH")
CUSTOMER_STATUSES = ("ACTIVE", "SUSPENDED")
TICKET_STATUSES = (
    "INTAKE",
    "VERIFIED",
    "PROVISIONAL_CREDITED",
    "HELD",
    "SETTLEMENT_READY",
    "SETTLED",
)
BAG_TYPES = ("CURRENCY", "COIN", "MIXED")
CUSTODY_STATUSES = ("SEALED", "IN_TRANSIT", "VAULT_RECEIVED", "OPENED")
COUNT_STATUSES = ("PENDING", "COUNTING", "COUNTED", "ADJUSTED")
CUSTODY_EVENT_TYPES = ("PICKUP", "TRANSFER", "VAULT_RECEIPT", "OPEN")
MACHINE_TYPES = ("CURRENCY_SORTER", "COIN_COUNTER", "MIXED_PROCESSOR")
MACHINE_STATUSES = ("AVAILABLE", "MAINTENANCE")
SESSION_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "SUPERSEDED")
LOT_CATEGORIES = ("FIT", "UNFIT", "COUNTERFEIT_SUSPECT")
LOT_STATUSES = ("PENDING_DEPOSIT", "PENDING_REVIEW", "ATTACHED", "DEPOSITED", "SEIZED")
REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACKNOWLEDGED")
CLAIM_TYPES = ("COUNT_VARIANCE", "STATEMENT_ADJUSTMENT")
CLAIM_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED")
FED_STATUSES = ("PREPARED", "SUBMITTED", "CONFIRMED", "CONFIRMED_WITH_ADJUSTMENT")
COIN_ORDER_STATUSES = (
    "REQUESTED",
    "APPROVED_FULL",
    "APPROVED_PARTIAL",
    "REJECTED",
    "RELEASED",
    "RETURNED",
)


# --------------------------------------------------------------------------
# Decimal / rounding helpers (PRD 2.7 - round half up)
# --------------------------------------------------------------------------
def round_half_up(value, places=0):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def dec2(value):
    """Decimal with exactly 2 decimal places for JSON output."""
    return float(round_half_up(value, 2))


# --------------------------------------------------------------------------
# Timestamps (PRD 2.4 - ISO 8601 UTC with exactly three fractional digits)
# --------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_utc():
    return datetime.now(timezone.utc)


def server_now_iso():
    return fmt_dt(now_utc())


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([Zz]|[+-]\d{2}:?\d{2})?$")


def parse_dt(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw or not _ISO_RE.match(raw):
        return None
    text = raw.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# In-memory store. Starts empty on every boot; nothing is ever seeded.
# --------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.vaults = {}
        self.customers = {}
        self.tickets = {}
        self.bags = {}
        self.custody_events = {}
        self.machines = {}
        self.sessions = {}
        self.lots = {}
        self.reports = {}
        self.claims = {}
        self.fed_deposits = {}
        self.coin_orders = {}
        self.coin_lines = {}
        self.inventory = {}
        self._seq = 0
        self.clock = DEFAULT_CLOCK_UTC

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
store_lock = threading.RLock()


def clock_now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def make_row(common=True):
    row = {
        "id": new_id(),
        "_seq": db.next_seq(),
        "created_at": server_now_iso(),
    }
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version - once per row per request."""
    if row is None:
        return
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(row)
    if key in touched:
        return
    touched.add(key)
    if "version" in row:
        row["version"] = row.get("version", 0) + 1
    if "updated_at" in row:
        row["updated_at"] = server_now_iso()


def ordered(rows):
    return sorted(rows, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": server_now_iso(),
    }


def respond(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Ladder rungs 1-3: authentication, role recognition, authorization
# --------------------------------------------------------------------------
class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == ROLE_CUSTOMER


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)
    return Actor(str(user_id).strip(), role)


def authorize(*allowed_roles):
    actor = authenticate()
    if actor.role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % actor.role)
    return actor


def check_ownership(actor, account_id):
    """Ladder rung 7 - account ownership for CustomerAccountHolder."""
    if actor.is_customer and actor.user_id != account_id:
        fail("ERR_ACCOUNT_OWNERSHIP", "Caller does not own this resource.")


# --------------------------------------------------------------------------
# Ladder rung 4: request shape
# --------------------------------------------------------------------------
def body_json(required=True):
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            return {}
        return {}
    try:
        parsed = request.get_json(silent=True, force=True)
    except Exception:
        parsed = None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "'%s' must be a string." % name)
    if len(value.strip()) < min_len:
        fail("ERR_INVALID_REQUEST", "'%s' must not be blank." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "'%s' exceeds %d characters." % (name, max_len))
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "'%s' must be a string." % name)
    return value


def _as_int(name, value, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "'%s' must be at least %d." % (name, minimum))
    return value


def req_int(body, name, minimum=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    return _as_int(name, body[name], minimum)


def opt_int(body, name, default=None, minimum=None):
    if not _present(body, name):
        return default
    return _as_int(name, body[name], minimum)


def req_bool(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "'%s' must be a boolean." % name)
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_datetime(body, name):
    """Returns (raw_string, datetime)."""
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    raw = body[name]
    if not isinstance(raw, str):
        fail("ERR_INVALID_REQUEST", "'%s' must be an ISO 8601 datetime string." % name)
    parsed = parse_dt(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "'%s' must be an ISO 8601 datetime string." % name)
    return raw, parsed


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(body, name):
    value = req_str(body, name)
    if not _DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "'%s' must be a YYYY-MM-DD date." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail("ERR_INVALID_REQUEST", "'%s' must be a valid calendar date." % name)
    return value


def req_list(body, name, allow_empty=False):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "'%s' is required." % name)
    value = body[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "'%s' must be an array." % name)
    if not allow_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "'%s' must not be empty." % name)
    return value


# --------------------------------------------------------------------------
# Pagination (PRD 2.3) - limit/offset/total_count/has_more
# --------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "'offset' must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "'%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return respond_list([serializer(r) for r in window], limit, offset, total)


# --------------------------------------------------------------------------
# Ladder rungs 5/6: existence lookups
# --------------------------------------------------------------------------
def _lookup(bucket, entity_id, error_id):
    row = bucket.get(entity_id) if isinstance(entity_id, str) else None
    if row is None:
        fail(error_id, "Resource '%s' was not found." % entity_id)
    return row


def get_vault(vault_id):
    return _lookup(db.vaults, vault_id, "ERR_VAULT_NOT_FOUND")


def get_customer(customer_id):
    return _lookup(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")


def get_ticket(ticket_id):
    return _lookup(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")


def get_bag(bag_id):
    return _lookup(db.bags, bag_id, "ERR_BAG_NOT_FOUND")


def get_machine(machine_id):
    return _lookup(db.machines, machine_id, "ERR_MACHINE_NOT_FOUND")


def get_session(session_id):
    return _lookup(db.sessions, session_id, "ERR_SESSION_NOT_FOUND")


def get_lot(lot_id):
    return _lookup(db.lots, lot_id, "ERR_LOT_NOT_FOUND")


def get_report(report_id):
    return _lookup(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


def get_claim(claim_id):
    return _lookup(db.claims, claim_id, "ERR_CLAIM_NOT_FOUND")


def get_fed_deposit(fed_id):
    return _lookup(db.fed_deposits, fed_id, "ERR_FED_DEPOSIT_NOT_FOUND")


def get_coin_order(order_id):
    return _lookup(db.coin_orders, order_id, "ERR_COIN_ORDER_NOT_FOUND")


# --------------------------------------------------------------------------
# Relationship helpers
# --------------------------------------------------------------------------
def bags_of_ticket(ticket_id):
    return ordered([b for b in db.bags.values() if b["deposit_ticket_id"] == ticket_id])


def sessions_of_bag(bag_id):
    return ordered([s for s in db.sessions.values() if s["sealed_bag_id"] == bag_id])


def lots_of_session(session_id):
    return ordered([l for l in db.lots.values() if l["count_session_id"] == session_id])


def lines_of_order(order_id):
    return ordered([l for l in db.coin_lines.values() if l["coin_order_id"] == order_id])


def inventory_of_vault(vault_id):
    return ordered([i for i in db.inventory.values() if i["vault_id"] == vault_id])


def inventory_row(vault_id, denomination):
    for row in db.inventory.values():
        if row["vault_id"] == vault_id and row["denomination"] == denomination:
            return row
    return None


def custody_events_of_bag(bag_id):
    return ordered([e for e in db.custody_events.values() if e["sealed_bag_id"] == bag_id])


def bag_of_lot(lot):
    session = db.sessions.get(lot["count_session_id"])
    if session is None:
        return None
    return db.bags.get(session["sealed_bag_id"])


def ticket_of_bag(bag):
    if bag is None:
        return None
    return db.tickets.get(bag["deposit_ticket_id"])


def account_of_bag(bag):
    ticket = ticket_of_bag(bag)
    if ticket is None:
        return None
    return db.customers.get(ticket["customer_account_id"])


def vault_of_session(session):
    machine = db.machines.get(session["counting_machine_id"])
    if machine is None:
        return None
    return db.vaults.get(machine["vault_id"])
