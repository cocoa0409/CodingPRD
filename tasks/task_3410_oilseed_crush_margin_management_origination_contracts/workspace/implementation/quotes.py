"""As-of market quote selector (PRD section 2.6)."""
from store import db, get_clock


def asof(commodity, month, at=None):
    """Latest quote for (commodity, quote_month) with quote_date <= `at`;
    ties on quote_date broken by latest created_at (insertion order)."""
    at = at if at is not None else get_clock()
    best = None
    for q in db["quotes"].values():
        if q["commodity"] != commodity or q["quote_month"] != month:
            continue
        qd = q["quote_date"]
        if qd > at:
            continue
        if (best is None or qd > best["quote_date"]
                or (qd == best["quote_date"] and q["_seq"] > best["_seq"])):
            best = q
    return best["price_cents"] if best is not None else None
