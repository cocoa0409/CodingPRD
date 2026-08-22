"""Money, hours and rounding (PRD 2.6).

All monetary amounts are integers denominated in cents. Rounding is half-up --
a value exactly halfway between two integers rounds away from zero -- and it is
applied at each named step of a rule, never once at the end. Every intermediate
value is an exact Fraction, so no binary floating point error can leak in.
"""

from fractions import Fraction

HOURS_PRECISION_DP = 4


def frac(value):
    if isinstance(value, Fraction):
        return value
    return Fraction(value)


def round_half_up(value):
    """Round a Fraction/int to a whole unit, halves away from zero."""
    value = frac(value)
    num, den = value.numerator, value.denominator
    sign = -1 if num < 0 else 1
    num = abs(num)
    whole, rem = divmod(num, den)
    if 2 * rem >= den:
        whole += 1
    return sign * whole


def pct(value, percentage):
    """value * percentage / 100 as an exact Fraction."""
    return frac(value) * Fraction(percentage, 100)


def quantize_hours(value):
    """Hold a duration to four decimal places (half-up)."""
    scale = 10 ** HOURS_PRECISION_DP
    return Fraction(round_half_up(frac(value) * scale), scale)


def hours_between(start_dt, end_dt):
    """Elapsed hours between two instants, held to four decimal places."""
    delta = end_dt - start_dt
    micros = (delta.days * 86400 + delta.seconds) * 10 ** 6 + delta.microseconds
    return quantize_hours(Fraction(micros, 3600 * 10 ** 6))


def exact_hours_between(start_dt, end_dt):
    """Elapsed hours as an exact signed real number (no quantisation)."""
    delta = end_dt - start_dt
    micros = (delta.days * 86400 + delta.seconds) * 10 ** 6 + delta.microseconds
    return Fraction(micros, 3600 * 10 ** 6)


def hours_json(value):
    """Render a stored hours Fraction as a JSON number."""
    return float(value)
