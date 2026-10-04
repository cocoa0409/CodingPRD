"""Discount rate resolution and the volume-tier derivation (calculations §1.3).

Two variants are computed and kept apart:

* the PROVISIONAL (quoted) rate, stored on the merchant as
  `applied_discount_rate_bps`, which follows the merchant's current volume tier
  directly; and
* the FINAL (billed) rate, sealed at settlement finalize, which is the
  volume-weighted average across the negotiated tiers.

Basis points are integers throughout; the single documented round_half_up step
per variant is applied once, with no intermediate rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

from names import VOLUME_TIER_ORDER

VOLUME_THRESHOLD_CENTS = 5000000


def round_half_up(value):
    """Round a Decimal half away from zero to a whole number, as an int."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bps(amount_cents, rate_bps):
    """A single-rounding product of an amount in cents and a rate in bps.

    Rounding happens exactly once, here, at the point the rule designates.
    """
    return round_half_up(Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10000))


def industry_of(store, merchant):
    return store.industry_categories.get(merchant["industry_category_id"])


def derive_volume_tier(merchant, industry):
    """ACTIVITY while billed_volume_mtd_cents < VOLUME_THRESHOLD_CENTS, FIXED
    once it reaches the threshold, LOW when the negotiated rate sits below the
    industry base."""
    negotiated = merchant.get("negotiated_rate_bps")
    if negotiated is not None:
        industry_base = industry["base_discount_rate_bps"] if industry else 0
        if negotiated < industry_base:
            return "LOW"
    if merchant["billed_volume_mtd_cents"] < VOLUME_THRESHOLD_CENTS:
        return "ACTIVITY"
    return "FIXED"


def tier_rate_bps(tier, industry, merchant):
    """The rate the quoted rate follows directly, per tier."""
    negotiated = merchant.get("negotiated_rate_bps")
    if tier == "ACTIVITY":
        return industry["base_discount_rate_bps"] if industry else 0
    if tier == "FIXED":
        base = industry["base_discount_rate_bps"] if industry else 0
        return round_half_up(Decimal(base) * Decimal("0.75"))
    # LOW: the negotiated large-merchant rate.
    return negotiated if negotiated is not None else (industry["base_discount_rate_bps"]
                                                      if industry else 0)


def resolve_discount_rate(store, merchant, industry, currency="USD"):
    """The PROVISIONAL quoted rate in basis points."""
    del currency  # single-currency program
    tier = merchant.get("volume_tier") or "ACTIVITY"
    return tier_rate_bps(tier, industry, merchant)


def historical_discount_rate(store, merchant, industry, batch_seq):
    """The rate in force at a batch sequence.

    `applied_discount_rate_bps` is the network's record of the rate current at a
    given instant; the merchant stores the one in force now, so a settlement
    sealed by the batch that is being finalized at this moment uses the
    `applied_discount_rate_bps` current at capture.
    """
    del batch_seq
    return merchant.get("applied_discount_rate_bps",
                        tier_rate_bps("ACTIVITY", industry, merchant))


def final_volume_weighted_rate(store, merchant, industry):
    """The FINAL billed rate: the volume-weighted average across the tiers."""
    base = industry["base_discount_rate_bps"] if industry else 0
    rates = {
        "ACTIVITY": base,
        "FIXED": round_half_up(Decimal(base) * Decimal("0.75")),
        "LOW": merchant.get("negotiated_rate_bps")
        if merchant.get("negotiated_rate_bps") is not None else base,
    }
    volumes = {tier: 0 for tier in VOLUME_TIER_ORDER}
    for settlement in store.settlements_for(merchant["id"]):
        if settlement["settlement_status"] not in ("CAPTURED", "IN_FUNDING", "SETTLED"):
            continue
        band = _tier_of_amount(settlement["post_refund_volume_cents"])
        volumes[band] += settlement["post_refund_volume_cents"]

    total = sum(volumes.values())
    if total <= 0:
        return merchant.get("applied_discount_rate_bps", base)

    weighted = sum(Decimal(rates[tier]) * Decimal(volumes[tier])
                   for tier in VOLUME_TIER_ORDER)
    return round_half_up(weighted / Decimal(total))


def _tier_of_amount(amount_cents):
    """The tier band a settled amount falls in, ordered ACTIVITY < FIXED < LOW."""
    if amount_cents < VOLUME_THRESHOLD_CENTS:
        return "ACTIVITY"
    if amount_cents < VOLUME_THRESHOLD_CENTS * 2:
        return "FIXED"
    return "LOW"