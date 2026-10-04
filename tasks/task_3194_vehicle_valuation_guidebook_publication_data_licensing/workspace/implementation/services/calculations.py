"""Domain calculation rules per SCAFFOLD §1.3 / PRD §3."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from db import DB, CLOCK


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 string; 'Z' treated as UTC."""
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_iso8601_ms(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt_utc.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return to_iso8601_ms(CLOCK.now())


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def round_half_up_int(value) -> int:
    """Round to integer using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value) -> float:
    """Round to 4 decimal places using ROUND_HALF_UP. Returned as float."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Condition tier fixed catalog
# ---------------------------------------------------------------------------

TIER_MULTIPLIERS = {
    "EXCELLENT": Decimal("1.10"),
    "GOOD": Decimal("1.00"),
    "FAIR": Decimal("0.85"),
    "POOR": Decimal("0.70"),
}


# ---------------------------------------------------------------------------
# Trailing market reference + blending
# ---------------------------------------------------------------------------

WINDOW_DAYS = 90
RECENT_DAYS = 30
WEIGHT_RECENT = 2
WEIGHT_OLD = 1


def _accepted_items_for(configuration_id: str, region_id: str):
    """Yield (item, batch) pairs from ACCEPTED batches matching the pair."""
    for batch in DB.batches.values():
        if batch["status"] != "ACCEPTED":
            continue
        for item in batch["items"]:
            if (item.get("configuration_id") == configuration_id
                    and item.get("region_id") == region_id):
                yield item, batch


def _window_items(configuration_id: str, region_id: str, now: datetime):
    """Items within [now - 90d, now] (inclusive)."""
    window_start = now - timedelta(days=WINDOW_DAYS)
    out = []
    for item, batch in _accepted_items_for(configuration_id, region_id):
        sd = item.get("sale_date")
        if isinstance(sd, str):
            # May be a date-only string (YYYY-MM-DD)
            try:
                sd_dt = parse_iso8601(sd)
            except ValueError:
                # Try date-only
                sd_dt = datetime.fromisoformat(sd).replace(tzinfo=timezone.utc)
        else:
            sd_dt = sd
        if sd_dt.tzinfo is None:
            sd_dt = sd_dt.replace(tzinfo=timezone.utc)
        if window_start <= sd_dt <= now:
            out.append((item, batch, sd_dt))
    return out


def compute_reference_price(configuration_id: str, region_id: str,
                            effective_at: datetime,
                            now: Optional[datetime] = None) -> Optional[int]:
    """Return blended reference_price_cents, or None when the window is empty."""
    if now is None:
        now = CLOCK.now()
    items = _window_items(configuration_id, region_id, now)
    if not items:
        return None

    recent_threshold = now - timedelta(days=RECENT_DAYS)
    weighted_sum = Decimal(0)
    weight_total = 0
    for item, _batch, sd_dt in items:
        weight = WEIGHT_RECENT if sd_dt >= recent_threshold else WEIGHT_OLD
        weighted_sum += Decimal(item["sold_price_cents"]) * weight
        weight_total += weight
    raw = weighted_sum / Decimal(weight_total)
    raw_int = round_half_up_int(raw)

    # Blend ACTIVE market shifts
    series_region_id = region_id
    config = DB.configurations.get(configuration_id)
    segment = config["segment"] if config else None

    total_pct = Decimal(0)
    for shift in DB.market_shifts.values():
        if shift["status"] != "ACTIVE":
            continue
        shift_eff = shift["effective_at_dt"]
        # only shifts with effective_at <= edition.effective_at blend
        if shift_eff > effective_at:
            continue
        # scope match
        if shift["region_id"] is not None and shift["region_id"] != series_region_id:
            continue
        if shift["segment"] is not None and shift["segment"] != segment:
            continue
        total_pct += Decimal(str(shift["pct_adjustment"]))

    if total_pct != 0:
        blended = Decimal(raw_int) * (Decimal(1) + total_pct)
        return round_half_up_int(blended)
    return raw_int


def compute_tier_values(reference_price_cents: int):
    ref = Decimal(reference_price_cents)
    trade_in = round_half_up_int(ref * Decimal("0.87"))
    private_party = round_half_up_int(ref * Decimal("0.95"))
    retail = round_half_up_int(ref * Decimal("1.08"))
    return trade_in, private_party, retail


# ---------------------------------------------------------------------------
# Confidence score
# ---------------------------------------------------------------------------

CONFIDENCE_GATE = Decimal("0.25")


def compute_confidence(configuration_id: str, region_id: str,
                       now: Optional[datetime] = None) -> float:
    if now is None:
        now = CLOCK.now()
    items = _window_items(configuration_id, region_id, now)
    n = len(items)
    if n == 0:
        return 0.0
    recent_threshold = now - timedelta(days=RECENT_DAYS)
    recent_count = sum(1 for _i, _b, sd in items if sd >= recent_threshold)
    source_types = set()
    for _item, batch, _sd in items:
        src = DB.sources.get(batch["source_id"])
        if src is not None:
            source_types.add(src["source_type"])
    diversity = len(source_types) / 3.0
    recency = recent_count / n
    volume_term = Decimal("0.5") * min(Decimal(1), Decimal(n) / Decimal(30))
    diversity_term = Decimal("0.3") * Decimal(str(diversity))
    recency_term = Decimal("0.2") * Decimal(str(recency))
    total = volume_term + diversity_term + recency_term
    return round_half_up_4dp(total)


# ---------------------------------------------------------------------------
# Offer amount
# ---------------------------------------------------------------------------

FIRST_SLAB = 10000
FIRST_RATE = Decimal("0.15")
SECOND_RATE = Decimal("0.10")
OPTION_CAP_PCT = Decimal("0.08")
FLOOR_PCT = Decimal("0.20")
INSPECT_FLOOR_PCT = Decimal("0.90")


def compute_offer_amount(edition: dict, configuration: dict,
                         mileage: int, age_years: int,
                         tier: str, option_ids: list) -> int:
    """Compute the quoted (or re-priced) offer amount per calculations.offer_amount
    + mileage_option_adjustment. Returns integer cents."""
    ref = Decimal(edition["reference_price_cents"])
    pp = Decimal(edition["private_party_cents"])
    mult = TIER_MULTIPLIERS[tier]
    base = pp * mult  # raw Decimal
    base_rounded = Decimal(round_half_up_int(base))

    # Mileage deduction: formula rates are in DOLLARS per excess mile
    # (10000 * 0.15 + 10000 * 0.10 = 2500 dollars = 250000 cents per PRD §3.6
    # and the pinned numeric examples in §1.8).
    expected = Decimal(age_years) * Decimal(configuration["annual_expected_miles"])
    excess = max(Decimal(0), Decimal(mileage) - expected)
    if excess <= FIRST_SLAB:
        deduction_dollars = excess * FIRST_RATE
    else:
        deduction_dollars = (Decimal(FIRST_SLAB) * FIRST_RATE
                             + (excess - Decimal(FIRST_SLAB)) * SECOND_RATE)
    deduction = deduction_dollars * Decimal(100)  # dollars -> cents

    # Options credit, capped at 8% of reference (cap itself rounded half-up)
    options_sum = Decimal(0)
    for oid in option_ids:
        pkg = DB.option_packages.get(oid)
        if pkg is not None:
            options_sum += Decimal(pkg["credit_cents"])
    cap = Decimal(round_half_up_int(ref * OPTION_CAP_PCT))
    options_credit = min(options_sum, cap)

    floor = Decimal(round_half_up_int(ref * FLOOR_PCT))
    raw = base_rounded - deduction + options_credit
    # Final integer rounding on the raw line (deduction may be fractional cents)
    raw_int = Decimal(round_half_up_int(raw))
    return int(max(raw_int, floor))


def apply_inspect_cap(repriced: int, offer_amount_cents: int) -> int:
    floor = round_half_up_int(Decimal(offer_amount_cents) * INSPECT_FLOOR_PCT)
    return max(repriced, floor)


# ---------------------------------------------------------------------------
# Dispute settlement credit
# ---------------------------------------------------------------------------

MAX_CREDIT = 25000


def compute_dispute_credit(retail_cents: int) -> int:
    raw = round_half_up_int(Decimal(retail_cents) * Decimal("0.02"))
    return min(MAX_CREDIT, raw)
