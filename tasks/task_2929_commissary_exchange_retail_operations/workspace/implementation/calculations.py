"""The eight calculation rules of the PRD, kept free of storage side effects.

Money is integer cents throughout; rates are integer basis points.  The single
rounding rule is "nearest whole cent, an exact half away from zero"
(round-half-up), applied with decimal.Decimal so no float ever touches money.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP

import constants as C


# --------------------------------------------------------------------------
# rounding discipline (PRD 2.6)
# --------------------------------------------------------------------------


def round_half_up(numerator, denominator):
    """Round numerator/denominator to the nearest integer, halves away from zero."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_bp(amount_cents, rate_bp):
    """Apply a basis-point rate to a cent amount with the pinned rounding rule."""
    return round_half_up(amount_cents * rate_bp, 10000)


def ceil_div(numerator, denominator):
    """Round up to the next whole unit whenever there is any remainder."""
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------
# 1. governing_assortment_selector (PRD 3.4)
# --------------------------------------------------------------------------


def governing_assortment(assortments, store_id, product_id, reference_instant):
    """Latest-window ACTIVE allocation whose CLOSED window contains the instant.

    Ranked by effective_from DESC, then created_at DESC.  Returns None when the
    candidate set is empty (the caller raises ERR_ITEM_NOT_IN_ASSORTMENT).
    """
    candidates = [
        a
        for a in assortments
        if a["store_id"] == store_id
        and a["product_id"] == product_id
        and a["status"] == "ACTIVE"
        and a["effective_from"] <= reference_instant <= a["effective_to"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["effective_from"], a["created_at"], a["_seq"]), reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------
# 2. line_retail_price (PRD 3.5)
# --------------------------------------------------------------------------


def line_retail_price(store, product, quantity, governing):
    """Price one sale line.  The markup is rounded PER UNIT before quantity."""
    unit_cost = product["unit_cost_cents"]
    if store["channel"] == "COMMISSARY":
        unit_price = unit_cost
    else:
        unit_price = unit_cost + apply_bp(unit_cost, store["exchange_markup_bp"])
    extended = unit_price * quantity
    line_markup = (unit_price - unit_cost) * quantity
    if store["region"] == "OVERSEAS" and governing["supply_mode"] == "WAREHOUSE":
        shipping = governing["overseas_shipping_allowance_cents"] * quantity
    else:
        shipping = 0
    restricted_units = quantity if product["resale_restricted"] else 0
    return {
        "unit_price_cents": unit_price,
        "extended_cents": extended,
        "line_markup_cents": line_markup,
        "line_shipping_allowance_cents": shipping,
        "restricted_units": restricted_units,
    }


# --------------------------------------------------------------------------
# 3. sale_surcharge_rollup (PRD 3.5)
# --------------------------------------------------------------------------


def sale_surcharge_rollup(store, lines):
    """Round the surcharge at the line, THEN sum.  Never rate-apply a subtotal."""
    merchandise = 0
    markup_total = 0
    surcharge_total = 0
    subsidised_shipping = 0
    for line in lines:
        line["line_surcharge_cents"] = apply_bp(line["extended_cents"], store["surcharge_rate_bp"])
        merchandise += line["extended_cents"]
        markup_total += line["line_markup_cents"]
        surcharge_total += line["line_surcharge_cents"]
        subsidised_shipping += line["line_shipping_allowance_cents"]
    tax = 0
    return {
        "line_count": len(lines),
        "merchandise_cents": merchandise,
        "markup_total_cents": markup_total,
        "surcharge_total_cents": surcharge_total,
        "tax_cents": tax,
        "total_due_cents": merchandise + markup_total + surcharge_total + tax,
        "subsidized_shipping_cents": subsidised_shipping,
    }


# --------------------------------------------------------------------------
# 4. vendor_promotional_allowance (PRD 3.6) — PROVISIONAL and SETTLED variants
# --------------------------------------------------------------------------


def _in_promo_window(governing, instant):
    start = governing.get("promo_window_start")
    end = governing.get("promo_window_end")
    if start is None or end is None:
        return False
    return start <= instant < end


def line_allowance_candidate(line, governing):
    if governing is None:
        return 0
    if governing["supply_mode"] == "DSD" and governing["promo_allowance_bp"] > 0:
        return apply_bp(line["extended_cents"], governing["promo_allowance_bp"])
    return 0


def vendor_promotional_allowance(lines, governing_by_line, instant):
    """Rounded per line, then summed; the window test is half-open."""
    total = 0
    per_line = {}
    for line in lines:
        governing = governing_by_line.get(line["id"])
        candidate = line_allowance_candidate(line, governing)
        if governing is not None and _in_promo_window(governing, instant):
            per_line[line["id"]] = candidate
        else:
            per_line[line["id"]] = 0
        total += per_line[line["id"]]
    return total, per_line


# --------------------------------------------------------------------------
# 5. patron_resale_risk_score (PRD 3.7) — ROLLING_30D and LAST_5_SALES
# --------------------------------------------------------------------------


def qualifying_sales(sales, patron_id):
    """Only OPEN or TENDERED sales of that patron qualify; VOIDED never does."""
    return [
        s
        for s in sales
        if s["patron_id"] == patron_id and s["tender_state"] in ("OPEN", "TENDERED")
    ]


def rolling_30d_set(sales, patron_id, clock_now):
    floor = clock_now - datetime.timedelta(days=C.ROLLING_WINDOW_DAYS)
    return [
        s
        for s in qualifying_sales(sales, patron_id)
        if floor <= s["business_date"] <= clock_now
    ]


def last_5_sales_set(sales, patron_id):
    ranked = sorted(
        qualifying_sales(sales, patron_id),
        key=lambda s: (s["business_date"], s["created_at"], s["_seq"]),
        reverse=True,
    )
    return ranked[: C.RECENT_SALES_WINDOW_COUNT]


def risk_score(input_sales, lines_by_sale, manual_strike_count):
    units = 0
    flagged = 0
    for sale in input_sales:
        for line in lines_by_sale.get(sale["id"], []):
            units += line["restricted_units"]
        if sale["compliance_state"] == "FLAGGED":
            flagged += 1
    raw = C.RESTRICTED_UNIT_WEIGHT * units + C.STRIKE_WEIGHT * (flagged + manual_strike_count)
    return min(100, raw), units, flagged


def derive_watch_status(score):
    if score >= C.RESTRICTED_THRESHOLD:
        return "RESTRICTED"
    if score >= C.WATCH_THRESHOLD:
        return "WATCH"
    return "CLEAR"


# --------------------------------------------------------------------------
# 6. capital_contingency_obligation (PRD 3.9)
# --------------------------------------------------------------------------


def capital_contingency_obligation(requested_amount_cents):
    """The tier is selected from the CONTINGENCY-FREE request amount only."""
    if requested_amount_cents < C.TIER_1_CEILING_CENTS:
        contingency_bp = C.TIER_1_BP
    elif requested_amount_cents < C.TIER_2_CEILING_CENTS:
        contingency_bp = C.TIER_2_BP
    else:
        contingency_bp = C.TIER_3_BP
    contingency_cents = apply_bp(requested_amount_cents, contingency_bp)
    return {
        "contingency_bp": contingency_bp,
        "contingency_cents": contingency_cents,
        "obligation_cents": requested_amount_cents + contingency_cents,
    }


# --------------------------------------------------------------------------
# 7. special_order_shipping_allowance (PRD 3.8)
# --------------------------------------------------------------------------


def special_order_shipping(store, product, quantity, route):
    billable_weight_kg = ceil_div(product["unit_weight_grams"] * quantity, 1000)
    rate = C.SHIP_RATE_CENTS_PER_KG[store["region"]]
    if route == "LOCAL_FILL":
        return {
            "billable_weight_kg": billable_weight_kg,
            "gross_ship_cents": 0,
            "patron_share_cents": 0,
            "shipping_allowance_cents": 0,
        }
    gross = billable_weight_kg * rate
    patron_share = apply_bp(gross, C.PATRON_SHARE_BP)
    allowance = min(C.ALLOWANCE_CAP_CENTS, max(0, gross - patron_share))
    return {
        "billable_weight_kg": billable_weight_kg,
        "gross_ship_cents": gross,
        "patron_share_cents": patron_share,
        "shipping_allowance_cents": allowance,
    }


# --------------------------------------------------------------------------
# 8. dividend_waterfall_distribution (PRD 3.9)
# --------------------------------------------------------------------------


def dividend_waterfall_plan(remaining, candidates, ytd_of):
    """Plan the grants without touching storage.

    `candidates` must already be the store's ACTIVE programmes ordered by
    priority_rank ASC then created_at ASC; programmes at or above their ceiling
    are skipped.  Every grant is the min of two integers, so no rounding arises.
    """
    plan = []
    for program in candidates:
        if remaining <= 0:
            break
        ytd = ytd_of(program)
        if ytd >= program["funding_ceiling_cents"]:
            continue
        headroom = program["funding_ceiling_cents"] - ytd
        grant = min(remaining, headroom)
        if grant > 0:
            plan.append((program, grant))
            remaining -= grant
    return plan
