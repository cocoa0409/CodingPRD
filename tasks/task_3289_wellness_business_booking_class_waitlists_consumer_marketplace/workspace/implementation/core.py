"""Core constants, logical clock, error types and small utilities.

The whole API runs on a logical clock pinned at boot to 2026-09-01T00:00:00Z.
No wall-clock time is ever consulted.
"""

import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Vocabulary / roster
# ---------------------------------------------------------------------------

API_PREFIX = "/wellness"

ROLES = [
    "OperatorOnly",
    "PlatformAdmin",
    "StudioOwner",
    "Client",
    "StaffMember",
    "Anonymous",
]

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

STATE_CODES = {"CA", "NY", "TX", "WA", "CO"}
TIERS = ("STARTER", "GROWTH", "ENTERPRISE")
PAYROLL_CAP_MODES = ("BONUS_OUTSIDE_CAP", "BONUS_INSIDE_CAP")
BILLING_PERIODS = ("MONTHLY", "ANNUAL")
EXPIRY_SCHEMES = ("NONE", "SEASONAL", "PROMOTIONAL")

# ---------------------------------------------------------------------------
# Temporal constants
# ---------------------------------------------------------------------------

LOGICAL_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

CHECKIN_OPEN_MINUTES = 60
OFFER_WINDOW_MINUTES = 120
OFFER_HOLD_HOLD_MINUTES = 30
STANDBY_CONFIRM_WINDOW_MINUTES = 90
STRIKE_RESTORE_WINDOW_HOURS = 72
STRIKE_REVOCATION_THRESHOLD = 5
STRIKE_OFFER_BLOCK_THRESHOLD = 3
LATE_CANCEL_WINDOW_MINUTES = 720
MEMBER_FEE_STRIKE_THRESHOLD = 3

PORTABILITY_RESPONSE_WINDOW_HOURS = 168
PORTABILITY_ADJUDICATION_WINDOW_HOURS = 336
EXPORT_WINDOW_HOURS = 72
EXPORT_MAX_DOWNLOADS = 3
PORTABILITY_COOLDOWN_DAYS = 30

FREEZE_ANNUAL_CAP_DAYS = 60
DAYS_PER_CYCLE = 30
OVER_FREEZE_PENALTY_DAYS = 5

PACK_EXPIRY_GRACE_DAYS = 14
PACK_VALIDITY_DAYS = 180
PACK_SEASONAL_DAYS = 90
PACK_PROMOTIONAL_DAYS = 30
PACK_PROMOTIONAL_MAX_SIZE = 12
PACK_MAX_EXTENSION_DAYS = 90
UNUSED_CREDIT_RETURN_DENOMINATOR = 4

MIN_PAYROLL_PERIOD_DAYS = 7
PAYROLL_REOPEN_WINDOW_DAYS = 7

GRACE_PERIOD_DAYS = 7
MEMBERSHIP_EXPIRY_GRACE_DAYS = 30
RESTORATION_WINDOW_HOURS = 48

RENEWAL_INTERVAL_DAYS = 30

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------

TIER_PRICE_BPS = {"STARTER": 10000, "GROWTH": 10500, "ENTERPRISE": 11000}
TIER_PRICE_FLOOR_CENTS = {"STARTER": 1500, "GROWTH": 1800, "ENTERPRISE": 2000}
OFF_PEAK_BPS = 8000
FULL_PRICE_BPS = 10000

PROMO_MIN_DISCOUNT_BPS = 500
PROMO_MAX_DISCOUNT_BPS = 5000
PROMO_DEFAULT_VALIDITY_DAYS = 21

INSTRUCTOR_TEACH_COMMISSION_BPS = {
    "STARTER": 2000,
    "GROWTH": 2500,
    "ENTERPRISE": 3000,
}
INSTRUCTOR_DEPUTY_COMMISSION_BPS = {
    "STARTER": 500,
    "GROWTH": 700,
    "ENTERPRISE": 900,
}
PAYROLL_ACCRUAL_CEILING_CENTS = 1200
PAYROLL_TIER_MULTIPLIER = {"STARTER": 1.0, "GROWTH": 1.0, "ENTERPRISE": 1.25}
MARKETPLACE_CHANNEL_BONUS_BPS = 1000
CHANNEL_BONUS_THRESHOLD_CENTS = 150

MARKETPLACE_MIN_COMMISSION_CENTS = 50
MARKETPLACE_PROMO_COMMISSION_BPS = 800

CLAIM_RESUBMIT_MAX = 1
DEFAULT_REMIT_DAYS = 30

# ---------------------------------------------------------------------------
# Feature gates
# ---------------------------------------------------------------------------

GATE_KEYS = (
    "marketplace_listing",
    "staff_payroll",
    "instructor_substitution",
    "waitlist_auto_promotion",
    "benefit_network_billing",
    "client_portability_export",
)

TIER_GATE_SOURCE = {
    "marketplace_listing": "marketplace_listing_enabled",
    "staff_payroll": "staff_payroll_enabled",
    "instructor_substitution": "instructor_substitution_enabled",
    "waitlist_auto_promotion": "waitlist_auto_promotion_enabled",
    "benefit_network_billing": "benefit_network_billing",
    "client_portability_export": "crm_client_export_enabled",
}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_STUDIO_NOT_OWNED": 403,
    "ERR_STUDIO_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_CLASS_SESSION_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_WAITLIST_ENTRY_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_CLASS_PACK_NOT_FOUND": 404,
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_PAYROLL_PERIOD_NOT_FOUND": 404,
    "ERR_PORTABILITY_REQUEST_NOT_FOUND": 404,
    "ERR_BENEFIT_NETWORK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_BOOKING_NOT_RESERVED": 409,
    "ERR_ENTRY_NOT_OFFERED": 409,
    "ERR_SESSION_NOT_SCHEDULED": 409,
    "ERR_PAYROLL_PERIOD_NOT_OPEN": 409,
    "ERR_PORTABILITY_ALREADY_DECIDED": 409,
    "ERR_WAITLIST_TERMINAL": 409,
    "ERR_STUDIO_NOT_OPERATING": 409,
    "ERR_SUBSCRIPTION_INACTIVE": 409,
    "ERR_PAYROLL_HOLD": 409,
    "ERR_FEATURE_NOT_IN_TIER": 403,
    "ERR_CLIENT_SCHEDULE_OVERLAP": 409,
    "ERR_ROOM_OVERLAP": 409,
    "ERR_BUFFER_INSUFFICIENT": 409,
    "ERR_PAYROLL_PERIOD_GAP": 409,
    "ERR_CANCEL_WINDOW_CLOSED": 409,
    "ERR_STUDIO_CAPACITY_EXCEEDED": 409,
    "ERR_ALLOCATION_EXHAUSTED": 409,
    "ERR_NO_ACTIVE_PACK": 409,
    "ERR_MEMBERSHIP_INACTIVE": 409,
    "ERR_PAYROLL_PERIOD_OVERLAP": 409,
    "ERR_CLIENT_EMAIL_CONFLICT": 409,
    "ERR_CLIENT_NOT_ADMISSIBLE": 409,
    "ERR_INSTRUCTOR_NOT_ELIGIBLE": 409,
    "ERR_NO_ELIGIBLE_SUBSTITUTE": 409,
    "ERR_NETWORK_NOT_ACTIVE": 409,
    "ERR_PAYMENT_SOURCE_NOT_PERMITTED": 409,
    "ERR_TIER_CHANGE_FEE_REQUIRED": 402,
    "ERR_EARLY_TERMINATION_FEE_REQUIRED": 402,
    "ERR_FREEZE_CAP_EXCEEDED": 409,
    "ERR_PACK_EXTENSION_CAP_EXCEEDED": 409,
    "ERR_CLIENT_BALANCE_OUTSTANDING": 409,
    "ERR_EXPORT_DOWNLOAD_CAP": 409,
    "ERR_EXPORT_NOT_GRANTED": 409,
    "ERR_PORTABILITY_WINDOW_CLOSED": 409,
    "ERR_PORTABILITY_COOLDOWN_ACTIVE": 409,
    "ERR_CLAIM_WINDOW_CLOSED": 409,
    "ERR_RESTORE_WINDOW_CLOSED": 409,
    "ERR_STALE_VERSION": 412,
}

ERROR_MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (
        "The X-User-ID and X-User-Role headers are required and X-User-Role must "
        "name a declared role."
    ),
    "ERR_UNAUTHORIZED_ROLE": "The acting role is not admitted by this operation.",
    "ERR_STUDIO_NOT_OWNED": (
        "A StudioOwner may only act on the studio bound to its identifier."
    ),
    "ERR_STUDIO_NOT_FOUND": "The referenced studio does not exist.",
    "ERR_SUBSCRIPTION_NOT_FOUND": "The referenced subscription does not exist.",
    "ERR_CLIENT_NOT_FOUND": "The referenced client does not exist.",
    "ERR_CLASS_SESSION_NOT_FOUND": "The referenced class session does not exist.",
    "ERR_BOOKING_NOT_FOUND": "The referenced booking does not exist.",
    "ERR_WAITLIST_ENTRY_NOT_FOUND": "The referenced waitlist entry does not exist.",
    "ERR_MEMBERSHIP_NOT_FOUND": "The referenced membership does not exist.",
    "ERR_CLASS_PACK_NOT_FOUND": "The referenced class pack does not exist.",
    "ERR_STAFF_MEMBER_NOT_FOUND": "The referenced staff member does not exist.",
    "ERR_PAYROLL_PERIOD_NOT_FOUND": "The referenced payroll period does not exist.",
    "ERR_PORTABILITY_REQUEST_NOT_FOUND": (
        "The referenced portability request does not exist."
    ),
    "ERR_BENEFIT_NETWORK_NOT_FOUND": "The referenced benefit network does not exist.",
    "ERR_INVALID_STATE": "The resource is not in a state that admits this operation.",
    "ERR_ALREADY_TERMINAL": "The resource is terminal and admits no transition.",
    "ERR_BOOKING_NOT_RESERVED": "The booking is not in RESERVED state.",
    "ERR_ENTRY_NOT_OFFERED": "The waitlist entry is not in OFFERED state.",
    "ERR_SESSION_NOT_SCHEDULED": "The class session is not in SCHEDULED state.",
    "ERR_PAYROLL_PERIOD_NOT_OPEN": "The payroll period is not in the required state.",
    "ERR_PORTABILITY_ALREADY_DECIDED": (
        "The portability request already carries a decision."
    ),
    "ERR_WAITLIST_TERMINAL": "The waitlist entry is terminal and admits no transition.",
    "ERR_STUDIO_NOT_OPERATING": (
        "The studio posture is SUSPENDED or CANCELLED and the operation requires an "
        "operating business."
    ),
    "ERR_SUBSCRIPTION_INACTIVE": (
        "The subscription is SUSPENDED or CANCELLED while the operation requires an "
        "active subscription."
    ),
    "ERR_PAYROLL_HOLD": "Payroll is on hold for this studio.",
    "ERR_FEATURE_NOT_IN_TIER": (
        "The operation's feature gate is not enabled on the studio's effective tier."
    ),
    "ERR_CLIENT_SCHEDULE_OVERLAP": (
        "The client already holds a booking or waitlist hold overlapping this session."
    ),
    "ERR_ROOM_OVERLAP": "The room is already occupied over this interval.",
    "ERR_BUFFER_INSUFFICIENT": (
        "The changeover buffer against another session in the room is insufficient."
    ),
    "ERR_PAYROLL_PERIOD_GAP": (
        "No payroll period of the studio covers this session's start instant."
    ),
    "ERR_CANCEL_WINDOW_CLOSED": "The session has already started.",
    "ERR_STUDIO_CAPACITY_EXCEEDED": (
        "The session has no seat available on this channel."
    ),
    "ERR_ALLOCATION_EXHAUSTED": "The promotional allocation is exhausted.",
    "ERR_NO_ACTIVE_PACK": "The class pack is not ACTIVE or has no credits remaining.",
    "ERR_MEMBERSHIP_INACTIVE": "The membership is not ACTIVE.",
    "ERR_PAYROLL_PERIOD_OVERLAP": (
        "The payroll period range intersects an existing period or spans too few days."
    ),
    "ERR_CLIENT_EMAIL_CONFLICT": (
        "The email is already used by another client on the same studio roster."
    ),
    "ERR_CLIENT_NOT_ADMISSIBLE": (
        "The client's status does not admit new bookings or holds."
    ),
    "ERR_INSTRUCTOR_NOT_ELIGIBLE": (
        "The nominated instructor is absent from the eligible candidate set."
    ),
    "ERR_NO_ELIGIBLE_SUBSTITUTE": "No eligible substitute instructor exists.",
    "ERR_NETWORK_NOT_ACTIVE": "The benefit network does not exist or is not eligible.",
    "ERR_PAYMENT_SOURCE_NOT_PERMITTED": (
        "The payment source is not permitted on this channel."
    ),
    "ERR_TIER_CHANGE_FEE_REQUIRED": (
        "A valid fee_payment_ref is required for the prorated tier-change fee."
    ),
    "ERR_EARLY_TERMINATION_FEE_REQUIRED": (
        "A valid fee_payment_ref is required for the early-termination fee."
    ),
    "ERR_FREEZE_CAP_EXCEEDED": "The freeze would exceed the permitted freeze days.",
    "ERR_PACK_EXTENSION_CAP_EXCEEDED": (
        "The extension would exceed the lifetime extension cap."
    ),
    "ERR_CLIENT_BALANCE_OUTSTANDING": (
        "The requesting client still carries an outstanding balance."
    ),
    "ERR_EXPORT_DOWNLOAD_CAP": "The export download cap has been reached.",
    "ERR_EXPORT_NOT_GRANTED": "The portability request has no granted export.",
    "ERR_PORTABILITY_WINDOW_CLOSED": "The portability window has lapsed.",
    "ERR_PORTABILITY_COOLDOWN_ACTIVE": (
        "A previous portability request is still inside its cooldown."
    ),
    "ERR_CLAIM_WINDOW_CLOSED": "The benefit-network claim denial window has lapsed.",
    "ERR_RESTORE_WINDOW_CLOSED": "The no-show restore window has lapsed.",
    "ERR_STALE_VERSION": (
        "The supplied expected version no longer matches the current version."
    ),
}


class ApiError(Exception):
    """Carries the declared error identifier, message and HTTP status."""

    def __init__(self, error_id, message=None, status=None):
        self.error_id = error_id
        self.status = status or ERROR_HTTP.get(error_id, 400)
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)
        super().__init__(self.error_id)


def fail(error_id, message=None, status=None):
    raise ApiError(error_id, message, status)


# ---------------------------------------------------------------------------
# Ids and time
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def now():
    """The current logical-clock instant."""
    from store import CLOCK

    return CLOCK["now"]


def set_clock(instant):
    from store import CLOCK

    previous = CLOCK["now"]
    CLOCK["now"] = instant
    return previous


def advance_clock(**kwargs):
    delta = timedelta(**kwargs)
    return set_clock(now() + delta)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_STATE", "Unparseable timestamp: %s" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    # clamp to the length of the target month
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def calendar_days(start, end):
    """Whole calendar days between two instants (negative when end precedes start)."""
    if start is None or end is None:
        return 0
    delta = end - start
    return delta.days


def minutes_between(start, end):
    return int((end - start).total_seconds() // 60)


def floor_div(numerator, denominator):
    return numerator // denominator


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)