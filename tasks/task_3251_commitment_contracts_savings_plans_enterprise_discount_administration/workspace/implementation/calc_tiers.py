from decimal import Decimal, ROUND_HALF_UP


def round_cents(value):
    """Round half-up to integer cents."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def tier_discount_for(amount, c0, tiers):
    """Marginal bracket discount over cumulative consumption.

    amount: Decimal entering stage 3 (post-amendment, post-plan)
    c0: Decimal cumulative consumption before this line
    tiers: list of {'threshold_cents': int, 'rate': float} sorted by threshold ASC
    Returns (discount Decimal, c1 Decimal).
    """
    if amount <= 0 or not tiers:
        return Decimal(0), c0
    c1 = c0 + amount
    discount = Decimal(0)
    for i, t in enumerate(tiers):
        t_lo = Decimal(t['threshold_cents'])
        t_hi = Decimal(tiers[i + 1]['threshold_cents']) if i + 1 < len(tiers) else None
        overlap_lo = max(c0, t_lo)
        overlap_hi = c1 if t_hi is None else min(c1, t_hi)
        span = overlap_hi - overlap_lo
        if span > 0:
            discount += span * Decimal(str(t['rate']))
    return discount, c1


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap; adjacency is NOT overlap."""
    return a_start < b_end and b_start < a_end
