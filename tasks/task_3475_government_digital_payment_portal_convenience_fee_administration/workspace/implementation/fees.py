"""Calculation rules (scaffold section 1.3): convenience fee gross-up,
absorbed tier invoicing (both variants), value-date lags, self-funding
constants. All money is integer cents."""
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err

MIN_FEE_CENTS = 100
QUOTE_TTL_MINUTES = 30

# method -> (rate_bp, fixed_cents); CARD is keyed further by cost bucket.
FEE_RATES = {
    "CARD": {
        "CONSUMER_DEBIT": (150, 25),
        "CONSUMER_CREDIT": (220, 30),
        "COMMERCIAL": (290, 35),
    },
    "ECHECK": (0, 150),   # flat 150 cents, no rate, no gross-up
    "WALLET": (180, 25),
}

METHOD_LAG_DAYS = {"CARD": 1, "WALLET": 1, "ECHECK": 2}

TOTAL_PORTAL_COST_CENTS = 12000000
AMORTIZATION_MONTHS = 60
MONTHLY_AMORTIZATION_CENTS = 200000

GRACE_DAYS = 1


def convenience_fee(amount_cents, method, card_cost_bucket):
    """The four pinned steps. card_cost_bucket is the variant's bucket
    (CONSUMER_CREDIT for QUOTED CARD fees, the instrument's own bucket for
    FINAL); ignored for ECHECK and WALLET. Returns the floored fee in cents.
    The statutory cap is a separate hard-stop check performed by the caller.

    Step 2 closed form: fee_raw = ceil((rate*amount + fixed*10000) /
    (10000 - rate)); resolve the rate first, never iterate.
    """
    if method == "ECHECK":
        fee_raw = 150
    else:
        if method == "CARD":
            rate_bp, fixed_cents = FEE_RATES["CARD"][card_cost_bucket]
        else:
            rate_bp, fixed_cents = FEE_RATES[method]
        numerator = rate_bp * amount_cents + fixed_cents * 10000
        denominator = 10000 - rate_bp
        fee_raw = -(-numerator // denominator)  # ceiling division
    return max(MIN_FEE_CENTS, fee_raw)


# --- absorbed-model monthly invoice ------------------------------------------

def _sorted_bands(bands):
    return sorted(bands, key=lambda b: b["volume_min_cents"])


def _band_hi(band):
    hi = band["volume_max_cents"]
    return hi if hi is not None else float("inf")


def _covers(bands, first, last):
    """True iff the closed interval [first, last] is fully covered by the
    union of the (non-overlapping) closed band intervals."""
    pos = first
    for band in bands:
        lo = band["volume_min_cents"]
        hi = _band_hi(band)
        if hi < pos:
            continue
        if lo > pos:
            return False
        pos = hi + 1
        if pos > last:
            return True
    return pos > last


def _band_containing(bands, cent):
    for band in bands:
        if band["volume_min_cents"] <= cent <= _band_hi(band):
            return band
    return None


def _round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def absorbed_invoice_marginal(txns, bands):
    """MARGINAL_CHRONOLOGICAL: each transaction's cumulative cent span is
    split across the bands it touches; the per-transaction line is rounded
    half-up FIRST, then lines are summed as integers."""
    bands = _sorted_bands(bands)
    cumulative = 0
    invoice = 0
    for txn in txns:
        first = cumulative + 1
        last = cumulative + txn["amount_cents"]
        if not _covers(bands, first, last):
            raise_err(
                "ERR_TIER_COVERAGE_GAP",
                409,
                "Pricing bands for the month do not cover the reached "
                "cumulative volume",
            )
        unrounded = Decimal(0)
        for band in bands:
            lo = band["volume_min_cents"]
            hi = _band_hi(band)
            ov_lo = max(first, lo)
            ov_hi = min(last, hi)
            if ov_lo <= ov_hi:
                portion = int(ov_hi - ov_lo + 1)
                unrounded += Decimal(portion) * Decimal(band["rate_bp"]) / Decimal(10000)
        first_band = _band_containing(bands, first)
        invoice += _round_half_up(unrounded) + first_band["per_txn_cents"]
        cumulative = last
    return invoice


def absorbed_invoice_flat(txns, bands):
    """FLAT_RETROACTIVE (audit-only): the month's TOTAL volume selects one
    band whose rate applies to all volume."""
    if not txns:
        return 0
    bands = _sorted_bands(bands)
    total_volume = sum(t["amount_cents"] for t in txns)
    band = _band_containing(bands, total_volume)
    if band is None:
        raise_err(
            "ERR_TIER_COVERAGE_GAP",
            409,
            "Pricing bands for the month do not cover the reached "
            "cumulative volume",
        )
    unrounded = Decimal(total_volume) * Decimal(band["rate_bp"]) / Decimal(10000)
    return _round_half_up(unrounded) + len(txns) * band["per_txn_cents"]
