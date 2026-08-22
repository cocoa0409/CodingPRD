"""Calculation rules (SCAFFOLD 1.3 / PRD 3.5, 3.8, 3.9). Every ordering below
is pinned by the PRD and must not be re-associated."""

from decimal import Decimal

from util import dec, rhu, rhu_int, floor_int

# --- constants -------------------------------------------------------------
VOLUME_DISCOUNT_TIERS = [
    (1000000, Decimal("0.04")),
    (2500000, Decimal("0.08")),
    (5000000, Decimal("0.12")),
]

IN_KIND_HAIRCUT = {
    "MEDIA_TRADE": Decimal("0.50"),
    "PRODUCT": Decimal("0.35"),
    "SERVICES": Decimal("0.40"),
    "TICKETS": Decimal("0.20"),
}
IN_KIND_CAP_PCT = Decimal("0.25")
MAX_MAKEGOOD_PCT = Decimal("0.15")
OVERSELL_ALLOWANCE = Decimal("1.10")
MIN_REST_MINUTES = 45
INTENT_ADJUSTMENT = {"YES": Decimal("10"), "MAYBE": Decimal("0"), "NO": Decimal("-15")}
BAND_HIGH_MIN = Decimal("70")
BAND_MEDIUM_MIN = Decimal("40")


# --- entitlement_unit_valuation -------------------------------------------
def tiered_unit_price(line, promised_units):
    """Highest tier break whose min_units is <= promised_units wins; the
    boundary is inclusive. No break reached leaves the base price standing."""
    unit_price = dec(line["base_unit_price_cents"])
    for tb in sorted(line.get("tier_breaks", []), key=lambda t: t["min_units"]):
        if promised_units >= tb["min_units"]:
            unit_price = dec(tb["unit_price_cents"])
    return unit_price


def entitlement_unit_valuation(line, promised_units, seasonality_index, exclusivity_scope):
    """Round the per-unit value FIRST, then multiply by promised_units."""
    unit_price = tiered_unit_price(line, promised_units)
    excl = dec(line["exclusivity_multiplier"]) if exclusivity_scope == "CATEGORY" else Decimal("1.00")
    unit_value_cents = rhu_int(unit_price * dec(seasonality_index) * excl)
    return unit_value_cents, unit_value_cents * promised_units


# --- volume discount -------------------------------------------------------
def volume_discount_pct(gross_entitlement_value_cents):
    rate = Decimal("0.00")
    for threshold, value in VOLUME_DISCOUNT_TIERS:
        if gross_entitlement_value_cents >= threshold:
            rate = value
    return rate


# --- in_kind_recognized_valuation (dual variant) ---------------------------
def in_kind_recognized_valuation(declared_cents, in_kind_category, cash_value_cents, variant):
    haircut = IN_KIND_HAIRCUT[in_kind_category]
    cap = rhu_int(dec(cash_value_cents) * IN_KIND_CAP_PCT)
    if variant == "CONSERVATIVE":
        # haircut first, then cap bites on the already-discounted number
        return min(rhu_int(dec(declared_cents) * (Decimal("1") - haircut)), cap)
    # AUDITED: cap the raw declared value first, then apply the haircut
    return rhu_int(dec(min(declared_cents, cap)) * (Decimal("1") - haircut))


# --- contract_value_rollup -------------------------------------------------
def contract_value_rollup(entitlements, declared_cents, in_kind_category, variant):
    """Five pinned steps. The discount tier is keyed on the pre-discount,
    cash-only gross and never on the total."""
    gross = sum(e["gross_value_cents"] for e in entitlements if e["status"] != "WAIVED")
    pct = volume_discount_pct(gross)
    cash = gross - rhu_int(dec(gross) * pct)
    in_kind = in_kind_recognized_valuation(declared_cents, in_kind_category, cash, variant)
    total = cash + in_kind
    return {
        "gross_entitlement_value_cents": gross,
        "volume_discount_pct": rhu(pct, 2),
        "cash_value_cents": cash,
        "in_kind_recognized_value_cents": in_kind,
        "total_recognized_value_cents": total,
    }


# --- makegood_credit_allocation -------------------------------------------
def makegood_credit_allocation(contract, entitlements):
    """Per-bucket floor first, then the whole remainder to the largest bucket."""
    considered = [e for e in entitlements if e["status"] != "WAIVED"]
    shortfall = {}
    for e in considered:
        shortfall[e["id"]] = max(0, e["promised_units"] - e["delivered_units"]) * e["unit_value_cents"]
    total_shortfall = sum(shortfall.values())
    allocation = dict((e["id"], 0) for e in considered)
    if total_shortfall == 0:
        return 0, allocation
    pool = min(total_shortfall, floor_int(dec(contract["cash_value_cents"]) * MAX_MAKEGOOD_PCT))
    order = [e for e in considered if shortfall[e["id"]] > 0]
    order.sort(key=lambda e: (-shortfall[e["id"]], e["created_at"], e["_seq"]))
    for e in order:
        allocation[e["id"]] = floor_int(dec(pool) * dec(shortfall[e["id"]]) / dec(total_shortfall))
    remainder = pool - sum(allocation[e["id"]] for e in order)
    if order:
        allocation[order[0]["id"]] += remainder
    return pool, allocation


# --- survey composite ------------------------------------------------------
def survey_composite_score(satisfaction, activation_quality, reporting_quality, renewal_intent):
    weighted = (dec(satisfaction) * Decimal("0.40")
                + dec(activation_quality) * Decimal("0.35")
                + dec(reporting_quality) * Decimal("0.25"))
    score = rhu(weighted * Decimal("10"), 2) + INTENT_ADJUSTMENT[renewal_intent]
    if score < 0:
        score = Decimal("0")
    if score > 100:
        score = Decimal("100")
    return rhu(score, 2)


# --- renewal_likelihood_scoring (dual variant) ----------------------------
def renewal_likelihood(target_contract, target_entitlements, target_surveys):
    """Returns (score Decimal 2dp, band). target_contract may be None."""
    if target_contract is None:
        return Decimal("0.00"), "LOW"

    considered = [e for e in target_entitlements if e["status"] != "WAIVED"]
    promised = sum(e["promised_units"] for e in considered)
    delivered = sum(e["delivered_units"] for e in considered)
    if promised == 0:
        delivery_factor = Decimal("100.00")
    else:
        delivery_factor = rhu(Decimal("100") * dec(delivered) / dec(promised), 2)

    cash = target_contract["cash_value_cents"]
    if cash == 0:
        penalty = Decimal("0.00")
    else:
        penalty = rhu(Decimal("100") * dec(target_contract["makegood_credit_cents"]) / dec(cash), 2)
    reliability = Decimal("100") - min(Decimal("100"), penalty)

    if target_surveys:
        composites = [dec(s["composite_score"]) for s in target_surveys]
        survey_composite = rhu(sum(composites) / dec(len(composites)), 2)
        raw = (Decimal("0.50") * survey_composite
               + Decimal("0.35") * delivery_factor
               + Decimal("0.15") * reliability)
    else:
        raw = Decimal("0.75") * delivery_factor + Decimal("0.25") * reliability

    if raw < 0:
        raw = Decimal("0")
    if raw > 100:
        raw = Decimal("100")
    score = rhu(raw, 2)
    if score >= BAND_HIGH_MIN:
        band = "HIGH"
    elif score >= BAND_MEDIUM_MIN:
        band = "MEDIUM"
    else:
        band = "LOW"
    return score, band
