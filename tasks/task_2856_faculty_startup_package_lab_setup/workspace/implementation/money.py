"""Cent arithmetic, rounding discipline and the three-funder cost share split.

All money is an integer number of cents; percentages are integer percentage
points.  No floating point currency arithmetic anywhere (PRD 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

# Fixed funder ordering used to break ties in the largest-remainder split.
FUNDER_ORDINAL = ("DEPARTMENT", "COLLEGE", "DEAN_OFFICE")

RENOVATION_SUBSIDY_PCT = {"COSMETIC": 0, "MODERATE": 25, "GUT": 40}
RENOVATION_SUBSIDY_CAP_CENTS = 20000000
OVERRUN_TOLERANCE_PCT = 10
COLLEGE_HOLDBACK_PCT = 15
MIN_NEW_MONEY_CENTS = 2500000
MIN_SPENDDOWN_RATIO_FOR_CARRYFORWARD = Decimal("0.5000")
PHASE_BUFFER_DAYS = 2


def dec(value):
    """Exact Decimal from any JSON scalar (never through binary float)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def cents_half_up(value):
    """Round an exact Decimal amount half up to whole cents."""
    return int(round_half_up(value, 0))


def pct_of_cents(amount_cents, pct):
    """percentage of a cent amount, rounded half up to whole cents."""
    return cents_half_up(Decimal(int(amount_cents)) * Decimal(int(pct)) / Decimal(100))


def kw(value):
    """Power in kilowatts carried to two decimal places, half-up."""
    return round_half_up(value, 2)


def kw_out(value):
    v = kw(value)
    return float(v)


def ratio4(numerator, denominator):
    """spend_down_ratio: half up to four decimal places, 0.0 when denom is 0."""
    if int(denominator) == 0:
        return Decimal("0.0000")
    return round_half_up(Decimal(int(numerator)) / Decimal(int(denominator)), 4)


def cost_share_split(amount_cents, dept_pct, college_pct, dean_pct):
    """Split ONE transaction amount across the three funder units.

    Floor of the exact rational product per funder, then the 0/1/2 cent
    remainder handed out largest-fractional-part-first, ties broken by the
    fixed funder ordering DEPARTMENT, COLLEGE, DEAN_OFFICE.
    """
    amount = int(amount_cents)
    pcts = [int(dept_pct), int(college_pct), int(dean_pct)]
    bases = []
    fracs = []
    for pct in pcts:
        product = amount * pct
        bases.append(product // 100)
        fracs.append(product % 100)
    remainder = amount - sum(bases)
    order = sorted(range(3), key=lambda i: (-fracs[i], i))
    for i in order[:remainder]:
        bases[i] += 1
    return bases[0], bases[1], bases[2]
