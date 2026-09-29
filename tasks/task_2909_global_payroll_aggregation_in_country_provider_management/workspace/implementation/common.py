"""Foundation helpers: logical clock, ids, timestamps, decimals, errors, envelope."""
import random
import re
import string
import threading
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, getcontext
from fractions import Fraction

getcontext().prec = 60

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
PLATFORM_ADMIN = "PlatformAdmin"
GLOBAL_PAYROLL_OPS = "GlobalPayrollOps"
PAYROLL_CONTROLLER = "PayrollController"
TREASURY_OFFICER = "TreasuryOfficer"
PROVIDER_USER = "ProviderUser"
COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = [
    PLATFORM_ADMIN,
    GLOBAL_PAYROLL_OPS,
    PAYROLL_CONTROLLER,
    TREASURY_OFFICER,
    PROVIDER_USER,
    COMPLIANCE_AUDITOR,
]
CLOCK_ROLES = [
    PLATFORM_ADMIN,
    GLOBAL_PAYROLL_OPS,
    PAYROLL_CONTROLLER,
    TREASURY_OFFICER,
    COMPLIANCE_AUDITOR,
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
REGIONS = ["EU", "UK", "US", "APAC", "LATAM"]
FILING_TYPES = ["INCOME_TAX_WITHHOLDING", "SOCIAL_INSURANCE", "YEAR_END"]
SERVICE_SCOPES = ["GROSS_TO_NET", "STATUTORY_FILING", "PAYMENT_DISBURSEMENT", "ADVISORY"]
FILING_RESPONSIBILITIES = ["PROVIDER", "CLIENT"]
PAY_FREQUENCIES = ["WEEKLY", "BIWEEKLY", "SEMI_MONTHLY", "MONTHLY"]
PROVIDER_STATUSES = ["ACTIVE", "PROBATION", "SUSPENDED", "OFFBOARDED"]
SCORE_VARIANTS = ["ROLLING_WINDOW", "ENGAGEMENT_TO_DATE"]
ENGAGEMENT_STATUSES = [
    "DRAFT",
    "ACTIVE",
    "REJECTED",
    "REMEDIATION_REQUIRED",
    "TRANSITION_PLANNED",
    "TRANSITION_IN_PROGRESS",
]
CYCLE_STATUSES = [
    "DRAFT",
    "ON_HOLD",
    "INPUTS_LOCKED",
    "RESULTS_APPROVED",
    "FUNDED",
    "CLOSED",
    "CANCELLED",
]
HOLD_REASONS = ["PROVIDER_PROBATION", "PROVIDER_SUSPENSION"]
SOURCE_SYSTEMS = ["HRIS_CORE", "HRIS_LEGACY", "MANUAL"]
INPUT_FILE_STATUSES = ["RECEIVED", "VALIDATED", "REJECTED", "SUPERSEDED"]
REJECTION_CODES = ["MISSING_ELEMENTS", "RECORD_COUNT_DRIFT"]
GTN_STATUSES = ["SUBMITTED", "CLEARED", "ESCALATED", "RETURNED", "APPROVED", "SUPERSEDED"]
VARIANCE_BASES = ["HEADCOUNT_NORMALIZED", "ABSOLUTE_TOTAL", "NO_PRIOR_BASELINE"]
BANK_ACCOUNT_STATUSES = ["PENDING_VERIFICATION", "VERIFIED"]
FUNDING_STATUSES = ["DRAFT", "APPROVED", "RELEASED", "RECALLED", "VOIDED"]
FILING_STATUSES = ["PENDING", "LATE", "FILED", "FILED_LATE", "CONFIRMED", "VOIDED"]
PENALTY_STATUSES = ["NONE", "ASSESSED", "DISPUTED", "WAIVED"]
PENALTY_OWNERS = ["NONE", "PROVIDER", "CLIENT", "SHARED"]
INCIDENT_TYPES = [
    "LATE_GTN_DELIVERY",
    "VARIANCE_ESCALATION",
    "FILING_MISS",
    "FUNDING_MISS",
    "DATA_INCIDENT",
]
SEVERITIES = ["SEV1", "SEV2", "SEV3"]
INCIDENT_STATUSES = ["OPEN", "CONFIRMED", "ESCALATED", "REMEDIATED"]
CONTROL_REFS = [
    "CTRL_INPUT_INTEGRITY",
    "CTRL_VARIANCE_REVIEW",
    "CTRL_FUNDING_DUAL_AUTH",
    "CTRL_FILING_CONFIRMATION",
    "CTRL_RESIDENCY_ATTESTATION",
]
EVIDENCE_TYPES = ["SYSTEM_ATTESTATION", "DOCUMENT_HASH"]

# Region -> required country element keys (input validation stage 1)
REGION_ELEMENT_SETS = {
    "EU": ["tax_id", "social_insurance_no", "iban"],
    "UK": ["tax_id", "ni_number", "sort_code", "account_number"],
    "US": ["tax_id", "ssn_last4", "routing_number"],
    "APAC": ["tax_id", "national_id"],
    "LATAM": ["tax_id", "national_id", "clabe"],
}

# ---------------------------------------------------------------------------
# Error catalogue (error_id -> http status)
# ---------------------------------------------------------------------------
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_PROVIDER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DUAL_AUTHORIZATION_REQUIRED": 403,
    "ERR_FILING_RESPONSIBILITY_MISMATCH": 403,
    "ERR_COUNTRY_PROFILE_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_INPUT_FILE_NOT_FOUND": 404,
    "ERR_GTN_RUN_NOT_FOUND": 404,
    "ERR_BANK_ACCOUNT_NOT_FOUND": 404,
    "ERR_FUNDING_INSTRUCTION_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_SLA_INCIDENT_NOT_FOUND": 404,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_STALE_ENGAGEMENT_VERSION": 412,
    "ERR_DATA_RESIDENCY_VIOLATION": 422,
    "ERR_SERVICE_SCOPE_NOT_COVERED": 422,
    "ERR_FILING_CAPABILITY_MISSING": 422,
    "ERR_ENGAGEMENT_NOT_ACTIVE": 409,
    "ERR_ENGAGEMENT_INVALID_STATE": 409,
    "ERR_PROVIDER_INVALID_STATE": 409,
    "ERR_PROVIDER_SUSPENDED": 409,
    "ERR_CYCLE_INVALID_STATE": 409,
    "ERR_HOLD_CAUSE_ACTIVE": 409,
    "ERR_NO_VALIDATED_INPUT": 409,
    "ERR_INPUT_FILE_INVALID_STATE": 409,
    "ERR_GTN_RUN_INVALID_STATE": 409,
    "ERR_FUNDING_INVALID_STATE": 409,
    "ERR_BANK_ACCOUNT_NOT_VERIFIED": 409,
    "ERR_FILING_INVALID_STATE": 409,
    "ERR_PENALTY_INVALID_STATE": 409,
    "ERR_INCIDENT_INVALID_STATE": 409,
    "ERR_INPUT_CUTOFF_PASSED": 409,
    "ERR_PAY_PERIOD_OVERLAP": 409,
    "ERR_PERIOD_FREQUENCY_MISMATCH": 422,
    "ERR_PAY_DATE_OUT_OF_RANGE": 422,
    "ERR_FUNDING_WINDOW_CONFLICT": 409,
    "ERR_INCIDENT_FUTURE_DATED": 422,
    "ERR_PRIOR_CYCLE_ENGAGEMENT_MISMATCH": 422,
    "ERR_CYCLE_ENGAGEMENT_MISMATCH": 422,
    "ERR_INPUT_FILE_CYCLE_MISMATCH": 422,
    "ERR_BANK_ACCOUNT_ENGAGEMENT_MISMATCH": 422,
    "ERR_CURRENCY_MISMATCH": 422,
    "ERR_INCOMING_PROVIDER_INVALID": 422,
    "ERR_FUNDING_CAP_EXCEEDED": 409,
    "ERR_GROSS_TOTAL_OUT_OF_TOLERANCE": 422,
    "ERR_GTN_TOTALS_INCONSISTENT": 422,
    "ERR_VARIANCE_JUSTIFICATION_REQUIRED": 422,
    "ERR_EMPTY_INPUT_FILE": 422,
    "ERR_DUPLICATE_COUNTRY_CODE": 409,
    "ERR_DUPLICATE_ENGAGEMENT": 409,
    "ERR_DUPLICATE_ACCOUNT_REF": 409,
    "ERR_DUPLICATE_PERIOD_LABEL": 409,
    "ERR_DUPLICATE_EVIDENCE_CONTROL": 409,
    "ERR_MANUAL_CONTROL_NOT_ALLOWED": 422,
    "ERR_FUNDING_ALREADY_EXISTS": 409,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_KNOWLEDGE_TRANSFER_INCOMPLETE": 409,
    "ERR_FILINGS_NOT_CONFIRMED": 409,
    "ERR_AUDIT_EVIDENCE_INCOMPLETE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERRORS.get(error_id, 422)
        self.message = message or error_id


def bad_request(message="The request payload is not valid."):
    return ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK}
LOCK = threading.RLock()


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def reset_clock():
    _state["clock"] = DEFAULT_CLOCK


# ---------------------------------------------------------------------------
# Ids / timestamps
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso3(dt):
    """Render an aware datetime as ISO-8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date. Returns date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = DATE_RE.match(text)
    if not m:
        # tolerate a full instant by taking its date component
        mi = INSTANT_RE.match(text)
        if not mi:
            return None
        try:
            return date(int(mi.group(1)), int(mi.group(2)), int(mi.group(3)))
        except ValueError:
            return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_instant(value):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    m = INSTANT_RE.match(text)
    if not m:
        d = DATE_RE.match(text)
        if not d:
            return None
        try:
            return datetime(
                int(d.group(1)), int(d.group(2)), int(d.group(3)), tzinfo=timezone.utc
            )
        except ValueError:
            return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour, minute = int(m.group(4)), int(m.group(5))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        oh, om = int(body[:2]), int(body[2:4])
        base = base - sign * timedelta(hours=oh, minutes=om)
    return base


def date_str(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
TWO = Decimal("0.01")
SIX = Decimal("0.000001")


def round2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round6(value):
    return Decimal(value).quantize(SIX, rounding=ROUND_HALF_UP)


def round_int(value):
    """Round half up to a whole integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def frac_to_decimal(fr):
    """Exact rational -> Decimal at working precision."""
    if isinstance(fr, Fraction):
        return Decimal(fr.numerator) / Decimal(fr.denominator)
    return Decimal(fr)


def round2_frac(fr):
    return round2(frac_to_decimal(fr))


def ceil_days(delta):
    """Whole days rounded up from any positive remainder."""
    total_us = delta.days * 86400 * 10 ** 6 + delta.seconds * 10 ** 6 + delta.microseconds
    day_us = 86400 * 10 ** 6
    if total_us <= 0:
        return 0
    return -(-total_us // day_us)


def num(value):
    """Serialize a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)
