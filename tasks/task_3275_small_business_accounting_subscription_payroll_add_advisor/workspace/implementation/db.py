"""In-memory store. Everything wiped on process restart (per-test-server isolation)."""
import uuid
from datetime import datetime, timezone

BOOT_TIME_STR = "2026-09-01T00:00:00Z"


def _new_tables():
    return {
        "AccountantFirm": {},
        "AccountantUser": {},
        "ClientCompany": {},
        "CompanyUser": {},
        "SubscriptionPlan": {},
        "Subscription": {},
        "PayrollAddon": {},
        "PayrollEmployee": {},
        "Invoice": {},
        "BankConnection": {},
        "BankTransaction": {},
        "Category": {},
        "CategorizationRule": {},
        "Reconciliation": {},
        "AppIntegration": {},
        "SyncConflict": {},
        "MigrationJob": {},
        "BillingTransfer": {},
        "AccessGrant": {},
        "ExportRequest": {},
    }


TABLES = _new_tables()

# Logical clock — starts at the boot instant; never falls back to wall clock.
CLOCK = {"current_utc": None}


def parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    if isinstance(s, str):
        t = s.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(t)
        except ValueError:
            return None
    return None


def fmt(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def boot_now():
    return parse_iso(BOOT_TIME_STR)


def now():
    cur = CLOCK.get("current_utc")
    if cur is None:
        CLOCK["current_utc"] = boot_now()
        return CLOCK["current_utc"]
    return cur


def set_now(dt):
    CLOCK["current_utc"] = dt


def new_id():
    return str(uuid.uuid4())


def stamp_common(obj, kind_has_version=True):
    t = now()
    obj["id"] = new_id()
    obj["created_at"] = fmt(t)
    if kind_has_version:
        obj["updated_at"] = fmt(t)
        obj["version"] = 1


def touch(obj):
    t = now()
    obj["updated_at"] = fmt(t)
    if "version" in obj:
        obj["version"] += 1
