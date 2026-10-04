"""In-memory store. Starts empty on every boot; never persisted, never seeded."""
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

# Logical clock default: fixed, never wall-clock.
CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0)

KINDS = [
    "accounts", "leases", "transaction_requests", "commission_records",
    "broker_engagements", "service_level_kpis", "facilities_vendors",
    "facility_sites", "consolidation_projects", "scorecards",
    "discipline_audits", "data_licenses", "transition_tasks",
    "fee_accruals", "account_assignments", "audit_reviews",
    "account_transitions",
]

# Map plural collection name -> python singular decl used by the domain layer.
SINGULAR = {
    "accounts": "account",
    "leases": "lease",
    "transaction_requests": "transaction_request",
    "commission_records": "commission_record",
    "broker_engagements": "broker_engagement",
    "service_level_kpis": "service_level_kpi",
    "facilities_vendors": "facilities_vendor",
    "facility_sites": "facility_site",
    "consolidation_projects": "consolidation_project",
    "scorecards": "scorecard",
    "discipline_audits": "discipline_audit",
    "data_licenses": "data_license",
    "transition_tasks": "transition_task",
    "fee_accruals": "fee_accrual",
    "account_assignments": "account_assignment",
    "audit_reviews": "audit_review",
    "account_transitions": "account_transition",
}


class Store:
    def __init__(self):
        self.tables = {k: {} for k in KINDS}
        self.seq = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self.seq += 1
        return self.seq

    def insert(self, kind, obj):
        self.tables[kind][obj["id"]] = obj
        return obj

    def get(self, kind, oid):
        return self.tables[kind].get(oid)

    def rows(self, kind):
        return list(self.tables[kind].values())

    def ordered(self, kind):
        return sorted(self.rows(kind), key=lambda o: o.get("_seq", 0))

    def children(self, kind, account_id):
        return [o for o in self.ordered(kind) if o.get("account_id") == account_id]


DB = Store()


def new_id():
    return str(uuid.uuid4())


def utcnow():
    return DB.clock


def now_iso(dt=None):
    d = dt or DB.clock
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO 8601 instant; accepts a trailing Z."""
    if value is None or isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso(dt):
    """Serialize a stored datetime; naive values are UTC."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        return dt
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def add_months(dt, months):
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                       31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def dec(value):
    return Decimal(str(value))


def rhu(value, places=2):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def fnum(d):
    """Decimal -> JSON number with at most 2 decimals."""
    try:
        q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return float(d)
    q = q.normalize()
    val = float(q)
    return int(val) if val == int(val) else val


def serialize(obj):
    if obj is None:
        return None
    if isinstance(obj, list):
        return [serialize(o) for o in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.startswith("_"):
                continue
            out[k] = serialize(v)
        return out
    if isinstance(obj, datetime):
        return iso(obj)
    if isinstance(obj, Decimal):
        return fnum(obj)
    return obj


def new_common():
    ts = DB.clock
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }


def touch(obj):
    obj["version"] = obj.get("version", 1) + 1
    obj["updated_at"] = DB.clock


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + limit < total}