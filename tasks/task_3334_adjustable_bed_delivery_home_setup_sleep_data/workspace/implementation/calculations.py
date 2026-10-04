"""Calculation rules (SCAFFOLD §1.3). All money math in integer cents with
round-half-up semantics."""
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from errors import err_validation


def round_half_up(x):
    """Round a numeric/Decimal to nearest integer, half up."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(a, b):
    """Ceiling of a/b for positive integers."""
    return -(-int(a) // int(b))


# ---------------------------------------------------------------- firmness
_FIRMNESS_BASE = {"SIDE": 35, "BACK": 55, "STOMACH": 65, "COMBINATION": 50}
_FIRMNESS_WEIGHT = {"UNDER_130": -10, "BAND_130_230": 0, "OVER_230": 10}
_FIRMNESS_FEEL = {"PLUSH": -10, "MEDIUM": 0, "FIRM": 10}


def recommended_firmness(sleep_position, weight_band, partner_sleeper, preferred_feel):
    raw = (
        _FIRMNESS_BASE[sleep_position]
        + _FIRMNESS_WEIGHT[weight_band]
        + _FIRMNESS_FEEL[preferred_feel]
        + (-5 if partner_sleeper else 0)
    )
    # round to nearest multiple of 5, half up
    rounded = round_half_up(Decimal(raw) / Decimal(5)) * 5
    return max(5, min(100, rounded))


REQUIRED_CATEGORIES = ["MATTRESS", "ADJUSTABLE_BASE", "AIR_CHAMBER", "PUMP"]


def recommended_skus(product_models):
    """Lowest price_cents per required category; tie-break created_at ASC."""
    skus = []
    for category in REQUIRED_CATEGORIES:
        candidates = [pm for pm in product_models if pm["category"] == category]
        if not candidates:
            raise err_validation(
                "no ProductModel candidates for category %s" % category
            )
        candidates.sort(
            key=lambda pm: (pm["price_cents"], pm["created_at"], pm.get("_seq", 0))
        )
        skus.append(candidates[0]["sku"])
    return skus


# ---------------------------------------------------------------- order totals
def compute_order_totals(line_items):
    """line_items: already expanded with unit_price_cents. Returns totals dict."""
    subtotal = 0
    for line in line_items:
        line["line_total_cents"] = round_half_up(line["qty"] * line["unit_price_cents"])
        subtotal += line["line_total_cents"]
    if subtotal >= 1000000:
        discount_pct = Decimal("0.15")
    elif subtotal >= 500000:
        discount_pct = Decimal("0.10")
    else:
        discount_pct = Decimal("0")
    discount = round_half_up(Decimal(subtotal) * discount_pct)
    delivery_fee = 0 if subtotal >= 200000 else 9900
    total_due = subtotal - discount + delivery_fee
    return {
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "delivery_fee_cents": delivery_fee,
        "total_due_cents": total_due,
    }


# ---------------------------------------------------------------- financing
def financing_schedule(offer_type, principal_cents, term_months, apr_bps):
    """Returns (monthly_payment_cents, promo_months)."""
    if offer_type == "ZERO_APR":
        return ceil_div(principal_cents, term_months), 0
    if offer_type == "DEFERRED_INTEREST":
        pay = int(
            (Decimal(principal_cents) * Decimal("0.03")).quantize(
                Decimal("1"), rounding=ROUND_CEILING
            )
        )
        return pay, 12
    # STANDARD amortization
    r = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
    if r == 0:
        return round_half_up(Decimal(principal_cents) / Decimal(term_months)), 0
    denom = Decimal(1) - (Decimal(1) + r) ** (-term_months)
    pay = round_half_up(Decimal(principal_cents) * r / denom)
    return pay, 0


def deferred_retro_interest(principal_cents, apr_bps, promo_months):
    return round_half_up(
        Decimal(principal_cents)
        * (Decimal(apr_bps) / Decimal(10000))
        * (Decimal(promo_months) / Decimal(12))
    )


# ---------------------------------------------------------------- sleep score
def _rest_component(restlessness_events):
    return max(0, 100 - 2 * restlessness_events)


def _duration_component(minutes_asleep):
    return min(100, round_half_up(Decimal(minutes_asleep) * 100 / Decimal(480)))


def _heart_component(avg_heart_rate):
    return max(0, 100 - abs(avg_heart_rate - 60))


def provisional_score(minutes_asleep, restlessness_events):
    rest = _rest_component(restlessness_events)
    dur = _duration_component(minutes_asleep)
    return round_half_up(Decimal("0.6") * rest + Decimal("0.4") * dur)


def final_score(minutes_asleep, restlessness_events, avg_heart_rate):
    rest = _rest_component(restlessness_events)
    dur = _duration_component(minutes_asleep)
    heart = _heart_component(avg_heart_rate)
    raw = round_half_up(
        Decimal("0.5") * rest + Decimal("0.3") * dur + Decimal("0.2") * heart
    )
    return max(0, min(100, raw))


# ---------------------------------------------------------------- warranty
WARRANTY_MONTHS = {"STRUCTURAL": 120, "CHAMBER": 60, "PUMP": 36, "ELECTRONICS": 24}

_CATEGORY_TO_COMPONENT = {
    "AIR_CHAMBER": "CHAMBER",
    "PUMP": "PUMP",
    "ELECTRONICS": "ELECTRONICS",
    "MATTRESS": "STRUCTURAL",
    "ADJUSTABLE_BASE": "STRUCTURAL",
}


def warranty_base_price(line_items, product_models_by_sku, component_category):
    """Among order lines whose ProductModel category maps to component_category,
    pick highest replacement_part_price_cents; tie-break lowest price_cents,
    then earliest created_at. Returns replacement_part_price_cents (0 if none)."""
    matches = []
    for line in line_items:
        pm = product_models_by_sku.get(line.get("sku"))
        if pm is None:
            continue
        if _CATEGORY_TO_COMPONENT.get(pm["category"]) == component_category:
            matches.append(pm)
    if not matches:
        return 0
    matches.sort(
        key=lambda pm: (
            -pm.get("replacement_part_price_cents", 0),
            pm["price_cents"],
            pm["created_at"],
            pm.get("_seq", 0),
        )
    )
    return matches[0].get("replacement_part_price_cents", 0)


def prorated_warranty_credit(
    base_price, component_category, proration_variant, months_in_service, final_nights_used
):
    months = WARRANTY_MONTHS[component_category]
    if proration_variant == "TIME_BASED":
        pct = max(Decimal(0), Decimal(1) - Decimal(months_in_service) / Decimal(months))
    else:  # NIGHTS_USED
        expected = months * 30
        pct = max(Decimal(0), Decimal(1) - Decimal(final_nights_used) / Decimal(expected))
    return round_half_up(Decimal(base_price) * pct)


# ---------------------------------------------------------------- restocking
_DEP_RATES = {
    "GOOD": {"MATTRESS": Decimal("0.15"), "ADJUSTABLE_BASE": Decimal("0.10")},
    "DAMAGED": {"MATTRESS": Decimal("0.30"), "ADJUSTABLE_BASE": Decimal("0.20")},
}
_DEP_OTHER = {"GOOD": Decimal("0.05"), "DAMAGED": Decimal("0.10")}


def restocking_refund(line_items, product_models_by_sku, condition, total_paid_cents):
    """Returns (depreciation_cents, restocking_fee_cents, refund_cents)."""
    depreciation = 0
    for line in line_items:
        pm = product_models_by_sku.get(line.get("sku"))
        category = pm["category"] if pm is not None else None
        rate = _DEP_RATES[condition].get(category, _DEP_OTHER[condition])
        depreciation += round_half_up(Decimal(line["line_total_cents"]) * rate)
    restocking_fee = max(9900, round_half_up(Decimal("0.10") * total_paid_cents))
    refund = max(0, total_paid_cents - depreciation - restocking_fee)
    return depreciation, restocking_fee, refund


# ---------------------------------------------------------------- visits
def slot_need(remove_old_mattress):
    return 2 + (1 if remove_old_mattress else 0)


def entitlements_for_tier(tier):
    if tier == "PLUS":
        return ["SCORE_BASIC", "SCORE_DETAIL"]
    if tier == "PREMIUM":
        return ["SCORE_BASIC", "SCORE_DETAIL", "TRENDS"]
    return ["SCORE_BASIC"]
