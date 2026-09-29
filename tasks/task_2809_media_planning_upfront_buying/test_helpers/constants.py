"""Constants and arithmetic mirrors for the Media Planning & Upfront Buying API.

Every literal here is transcribed from the product requirements: the API prefix,
the logical-clock startup instant, the market and daypart planning factors, the
CPM planning band, the agency commission tiers, the negotiation and make-good
caps, the rights windows and the post-buy tolerance.

The small arithmetic helpers reproduce the declared rounding disciplines so a
test can state an expected figure in the same shape the requirement states it.
Money is always integer cents and audience figures are always integers, so the
helpers return ``int`` for those and ``Decimal``-backed floats for percentages
and indices.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Union

Number = Union[int, float, str, Decimal]

# --------------------------------------------------------------------------
# Address space
# --------------------------------------------------------------------------
#: Every resource of the domain lives under this single flat prefix.
API_PREFIX = "/upfront"

#: The clock-driving endpoint sits outside the domain prefix.
CLOCK_PATH = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
#: The instant the logical clock reads before any test moves it.
CLOCK_STARTUP = "2026-08-01T00:00:00.000Z"

#: The same instant in the compact form the clock endpoint accepts.
CLOCK_STARTUP_INPUT = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Envelope and pagination
# --------------------------------------------------------------------------
REQUEST_ID_PREFIX = "req_"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

#: Fractional-second width of every timestamp the API emits.
TIMESTAMP_FRACTIONAL_DIGITS = 3

# --------------------------------------------------------------------------
# Planning factors
# --------------------------------------------------------------------------
#: Market multipliers applied to the planned CPM.
MARKET_MULTIPLIER = {
    "UPFRONT": Decimal("1.00"),
    "SCATTER": Decimal("1.35"),
}

#: Daypart indices applied to the planned CPM.
DAYPART_INDEX = {
    "PRIME": Decimal("1.20"),
    "DAYTIME": Decimal("0.85"),
    "LATE": Decimal("0.70"),
    "DIGITAL_ANY": Decimal("1.00"),
}

#: Relative band around the planned CPM.
CPM_BAND_LOW_FACTOR = Decimal("0.60")
CPM_BAND_HIGH_FACTOR = Decimal("2.50")

#: Absolute band the relative band is combined with.
CPM_ABSOLUTE_FLOOR_CENTS = 200
CPM_ABSOLUTE_CEILING_CENTS = 12000

# --------------------------------------------------------------------------
# Agency commission tiers, selected on the pre-commission net media cost
# --------------------------------------------------------------------------
COMMISSION_TIER_1_CEILING_CENTS = 5_000_000
COMMISSION_TIER_2_CEILING_CENTS = 25_000_000
COMMISSION_RATE_TIER_1 = Decimal("0.0700")
COMMISSION_RATE_TIER_2 = Decimal("0.0550")
COMMISSION_RATE_TIER_3 = Decimal("0.0400")

# --------------------------------------------------------------------------
# Caps
# --------------------------------------------------------------------------
MAX_NEGOTIATION_ROUNDS = 6
MAX_MAKE_GOOD_OFFERS = 3

# --------------------------------------------------------------------------
# Rights windows, measured back from the buy's flight start
# --------------------------------------------------------------------------
OPTION_WINDOW_DAYS_BEFORE_FLIGHT = 45
CANCEL_WINDOW_1_DAYS_BEFORE_FLIGHT = 60
CANCEL_WINDOW_2_DAYS_BEFORE_FLIGHT = 30

#: Cancellation ceiling while the clock is strictly before cancel_window_1_close.
CANCEL_CEILING_EARLY_PCT = Decimal("100.00")
#: Cancellation ceiling from cancel_window_1_close inclusive to window 2 exclusive.
CANCEL_CEILING_LATE_PCT = Decimal("25.00")

# --------------------------------------------------------------------------
# Stewardship, separation and credit
# --------------------------------------------------------------------------
#: A post-buy shortfall at or above this percentage is an under-delivery.
SHORTFALL_TOLERANCE_PCT = Decimal("2.0000")

#: Days the already-placed flight is expanded by on each side for separation.
CATEGORY_SEPARATION_BUFFER_DAYS = 7

#: A first late payment moves the advertiser to WATCH, a second to HOLD.
LATE_PAYMENTS_FOR_WATCH = 1
LATE_PAYMENTS_FOR_HOLD = 2

# --------------------------------------------------------------------------
# Declared defaults for optional inputs
# --------------------------------------------------------------------------
DEFAULT_PAYMENT_TERMS_DAYS = 30
DEFAULT_SEQUENTIAL_LIABILITY_ENABLED = True
DEFAULT_GUARANTEE_PCT = 100
DEFAULT_MAKE_GOOD_PROVISION = "MAKE_GOOD_UNITS"
DEFAULT_OPTION_PCT_CEILING = 25
DEFAULT_EXCLUSIVITY_MODE = "SHARED"
DEFAULT_UNIT_EXCLUSIVE = False

# --------------------------------------------------------------------------
# Compatibility maps
# --------------------------------------------------------------------------
#: The single platform each channel may be delivered on.
PLATFORM_FOR_CHANNEL = {
    "LINEAR_TV": "LINEAR",
    "CTV": "CTV",
    "DIGITAL_VIDEO": "DIGITAL",
    "AUDIO": "AUDIO",
}

#: The reconciliation group each channel folds into, in reporting order.
RECONCILIATION_GROUP_FOR_CHANNEL = {
    "LINEAR_TV": "LINEAR",
    "CTV": "CTV",
    "DIGITAL_VIDEO": "DIGITAL",
    "AUDIO": "DIGITAL",
}

#: Fixed order the reconciliation groups are walked in.
RECONCILIATION_GROUP_ORDER = ("LINEAR", "CTV", "DIGITAL")

#: Buy states whose gross cost counts as committed money.
COMMITTING_BUY_STATUSES = ("PLACED", "IN_FLIGHT", "COMPLETED", "CLOSED")

#: Unit states that occupy inventory on an avail.
OCCUPYING_UNIT_STATUSES = ("SCHEDULED", "AIRED", "MAKE_GOOD_SCHEDULED", "MAKE_GOOD_AIRED")

#: Unit states that may be billed on an invoice line.
BILLABLE_UNIT_STATUSES = ("AIRED", "MAKE_GOOD_AIRED")


# ==========================================================================
# Rounding disciplines
# ==========================================================================
def dec(value: Number) -> Decimal:
    """Coerce a figure to Decimal without going through binary float."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value: Number, places: int = 0) -> Union[int, float]:
    """Round a figure half-up to ``places`` decimals.

    Cent results and every quotient the requirement rounds are half-up, so this
    is the default discipline.  Returns ``int`` for ``places == 0`` so a money
    figure compares equal to the integer cents the API emits.
    """
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    rounded = dec(value).quantize(quant, rounding=ROUND_HALF_UP)
    return int(rounded) if places == 0 else float(rounded)


def floor_int(value: Number) -> int:
    """Truncate towards zero-floor, the discipline for the three floored fields."""
    return int(dec(value).to_integral_value(rounding="ROUND_FLOOR"))


def pct2(value: Number) -> float:
    """A percentage or ratio carried to two decimals, half-up."""
    return round_half_up(value, 2)


def pct4(value: Number) -> float:
    """A percentage, index or rate carried to four decimals, half-up."""
    return round_half_up(value, 4)


# ==========================================================================
# Planning arithmetic
# ==========================================================================
def allocated_cents(total_budget_cents: int, allocation_pct: Number) -> int:
    """floor of the campaign budget times the allocation percentage."""
    return floor_int(dec(total_budget_cents) * dec(allocation_pct) / dec(100))


def effective_planned_cpm_cents(
    planned_cpm_cents: int, market: str, daypart: str
) -> int:
    """The market- and daypart-adjusted CPM clamped into the planning band.

    The relative band is combined with the absolute band, the floor is applied
    first and the ceiling has the final word.
    """
    adjusted = (
        dec(planned_cpm_cents) * MARKET_MULTIPLIER[market] * DAYPART_INDEX[daypart]
    )
    adjusted_cents = round_half_up(adjusted)
    band_floor = max(
        CPM_ABSOLUTE_FLOOR_CENTS,
        round_half_up(CPM_BAND_LOW_FACTOR * dec(planned_cpm_cents)),
    )
    band_ceiling = min(
        CPM_ABSOLUTE_CEILING_CENTS,
        round_half_up(CPM_BAND_HIGH_FACTOR * dec(planned_cpm_cents)),
    )
    clamped = max(adjusted_cents, band_floor)
    return min(clamped, band_ceiling)


def planned_impressions(allocated: int, effective_cpm_cents: int) -> int:
    """Impressions the allocated money buys at the effective CPM, floored."""
    return floor_int(dec(allocated) * dec(1000) / dec(effective_cpm_cents))


def planned_grp(impressions: int, universe_thousands: int) -> float:
    """Gross rating points the impressions represent against the universe."""
    universe = dec(universe_thousands) * dec(1000)
    return pct2(dec(impressions) / universe * dec(100))


def planned_frequency(grp: Number, reach_goal_pct: Number) -> float:
    """Average exposures the plan implies against the reach objective."""
    return pct2(dec(grp) / dec(reach_goal_pct))


# ==========================================================================
# Buy cost arithmetic
# ==========================================================================
def net_media_cost_cents(guaranteed_impressions: int, agreed_cpm_cents: int) -> int:
    """The pre-commission net media cost of the guarantee."""
    return round_half_up(dec(guaranteed_impressions) / dec(1000) * dec(agreed_cpm_cents))


def commission_rate_for_net(net_cents: int) -> float:
    """The commission tier the pre-commission net media cost falls in.

    The tier floors are inclusive and the rate is never re-selected from a
    figure that already carries commission.
    """
    if net_cents < COMMISSION_TIER_1_CEILING_CENTS:
        return float(COMMISSION_RATE_TIER_1)
    if net_cents < COMMISSION_TIER_2_CEILING_CENTS:
        return float(COMMISSION_RATE_TIER_2)
    return float(COMMISSION_RATE_TIER_3)


def agency_commission_cents(net_cents: int, rate: Number = None) -> int:
    """Commission on the net media cost at the tier the net selects."""
    effective_rate = dec(commission_rate_for_net(net_cents) if rate is None else rate)
    return round_half_up(dec(net_cents) * effective_rate)


def gross_cost_cents(guaranteed_impressions: int, agreed_cpm_cents: int) -> int:
    """Net media cost plus the commission it earns."""
    net = net_media_cost_cents(guaranteed_impressions, agreed_cpm_cents)
    return net + agency_commission_cents(net)


def buy_cost_stack(guaranteed_impressions: int, agreed_cpm_cents: int) -> dict:
    """The whole cost stack of a buy: net, rate, commission and gross."""
    net = net_media_cost_cents(guaranteed_impressions, agreed_cpm_cents)
    rate = commission_rate_for_net(net)
    commission = agency_commission_cents(net, rate)
    return {
        "net_media_cost_cents": net,
        "commission_rate": rate,
        "agency_commission_cents": commission,
        "gross_cost_cents": net + commission,
    }


# ==========================================================================
# Line, invoice and settlement arithmetic
# ==========================================================================
def line_net_cents(units: int, unit_rate_cents: int) -> int:
    """Net media cost of one unit line."""
    return round_half_up(dec(units) * dec(unit_rate_cents))


def line_commission_cents(net_cents: int, commission_rate: Number) -> int:
    """Commission of one unit line, rounded on the line before any summation."""
    return round_half_up(dec(net_cents) * dec(commission_rate))


def line_gross_cents(net_cents: int, commission_cents: int) -> int:
    """Gross of one unit line."""
    return net_cents + commission_cents


def shortfall_value_cents(shortfall_impressions: int, agreed_cpm_cents: int) -> int:
    """Cash value of an audience shortfall at the agreed CPM."""
    return round_half_up(dec(shortfall_impressions) / dec(1000) * dec(agreed_cpm_cents))


def delivery_index(credited_impressions: int, guaranteed_impressions: int) -> float:
    """A delivery index carried to four decimals; 0.0000 against a zero guarantee."""
    if guaranteed_impressions == 0:
        return 0.0
    return pct4(dec(credited_impressions) / dec(guaranteed_impressions))


def shortfall_pct(shortfall: int, guaranteed_impressions: int) -> float:
    """The shortfall as a percentage of the guarantee, four decimals."""
    if guaranteed_impressions == 0:
        return 0.0
    return pct4(dec(shortfall) / dec(guaranteed_impressions) * dec(100))


def max_remittable_cents(
    client_paid_cents: int,
    seller_payable_cents: int,
    net_payable_cents: int,
    sequential_liability_enabled: bool = True,
) -> int:
    """The sequential-liability release ceiling, floored to whole cents."""
    if not sequential_liability_enabled:
        return seller_payable_cents
    if net_payable_cents == 0:
        return 0
    pro_rata = floor_int(
        dec(client_paid_cents) * dec(seller_payable_cents) / dec(net_payable_cents)
    )
    return min(seller_payable_cents, pro_rata)


def implied_frequency(gross_reach_pct: Number, unduplicated_reach_pct: Number) -> float:
    """Gross reach over unduplicated reach; 0.00 against zero unduplicated reach."""
    if dec(unduplicated_reach_pct) == 0:
        return 0.0
    return pct2(dec(gross_reach_pct) / dec(unduplicated_reach_pct))


# ==========================================================================
# Instant arithmetic
# ==========================================================================
def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant with or without fractional seconds."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso_millis(moment: datetime) -> str:
    """Render an instant the way the API renders every timestamp."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def iso_seconds(moment: datetime) -> str:
    """Render an instant in the compact form accepted on input."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_instant(value: str) -> str:
    """Canonicalise any ISO-8601 UTC instant to millisecond precision.

    Input timestamps are written compactly while the API answers with three
    fractional digits, so instants are compared through this function rather
    than by raw string equality.
    """
    return iso_millis(parse_instant(value))


def shift_days(value: str, days: int) -> str:
    """Move an instant by whole days, keeping the compact input rendering."""
    return iso_seconds(parse_instant(value) + timedelta(days=days))


def shift_seconds(value: str, seconds: int) -> str:
    """Move an instant by whole seconds, keeping the compact input rendering."""
    return iso_seconds(parse_instant(value) + timedelta(seconds=seconds))


def option_window_close(flight_start: str) -> str:
    """The last instant an option roll-up may be exercised."""
    return shift_days(flight_start, -OPTION_WINDOW_DAYS_BEFORE_FLIGHT)


def cancel_window_1_close(flight_start: str) -> str:
    """The instant the cancellation ceiling drops from 100 to 25 percent."""
    return shift_days(flight_start, -CANCEL_WINDOW_1_DAYS_BEFORE_FLIGHT)


def cancel_window_2_close(flight_start: str) -> str:
    """The instant the cancellation right disappears."""
    return shift_days(flight_start, -CANCEL_WINDOW_2_DAYS_BEFORE_FLIGHT)


def due_date(issued_at: str, payment_terms_days: int = DEFAULT_PAYMENT_TERMS_DAYS) -> str:
    """The payment deadline the issue instant and the terms produce."""
    return shift_days(issued_at, payment_terms_days)
