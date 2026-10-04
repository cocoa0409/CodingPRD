"""Round-half-up helpers.  Every rounding step in this API is round-half-up
(PRD 2.7) and is applied independently at the precision stated for that step.
"""

from decimal import Decimal, ROUND_HALF_UP


def dec(value):
    """Exact Decimal for a client-supplied number (via its literal text)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round to a whole cent and hand back a Python int."""
    return int(round_half_up(value, 0))
