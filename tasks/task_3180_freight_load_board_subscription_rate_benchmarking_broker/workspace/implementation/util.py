import random
import string
import uuid
from datetime import datetime, timedelta, timezone

EQUIPMENT_TYPES = ("DRY_VAN", "REEFER", "FLATBED")
PLAN_CODES = ("BASIC", "PRO", "ENTERPRISE")
ANALYTICS_DEPTHS = ("NONE", "LANE_LEVEL", "FULL")
RATE_KINDS = ("SPOT", "CONTRACT")
ALERT_TYPES = ("DOUBLE_BROKERING", "IDENTITY_SPOOFING", "CARGO_THEFT")
VARIANTS = ("SPOT_ONLY", "BLENDED")
ROLES = ("PlatformAdmin", "BrokerAdmin", "CarrierAdmin", "ComplianceAnalyst", "DataOps")
ALL_ROLES = set(ROLES)

PLAN_BASE_CENTS = {"BASIC": 9900, "PRO": 24900, "ENTERPRISE": 49900}
OVERAGE_TIER1_RATE_CENTS = 150
OVERAGE_TIER2_RATE_CENTS = 300
ANALYTICS_ADDON_CENTS = {"NONE": 0, "LANE_LEVEL": 2000, "FULL": 5000}

BASE_FUEL_CENTS = 300
STEP_CENTS = 25
STEP_PCT = 0.01
MAX_FSC_PCT = 0.20

CONTRIBUTION_MIN = 10
CONTRIBUTION_WINDOW_DAYS = 30
CREDIT_WINDOW_DAYS = 365
DISPUTE_WINDOW_DAYS = 90
GRACE_DAYS_AFTER_PERIOD = 7
REFUND_WINDOW_HOURS = 24
BENCHMARK_MIN_SAMPLE = 5

BADGES = ("GOLD", "STANDARD", "WATCH", "CRITICAL")


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def iso_ms(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_dt():
    return datetime.now(timezone.utc)


def initial_clock():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
