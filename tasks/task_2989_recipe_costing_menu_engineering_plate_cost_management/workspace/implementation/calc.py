"""Plate costing, price-change projection, menu-mix classification, period
variance and LTO profitability (PRD 3.5, 3.7, 3.8, 3.9)."""
from core import (
    CAP_RELIEF_BPS, DEFAULT_BASELINE_UNITS, GARNISH_BPS, GARNISH_FLOOR_MICROS,
    LTO_MIN_ATTAINMENT_BPS, LTO_MIN_CONTRIBUTION_CENTS, LTO_SUPPORT_BPS,
    MAX_SINGLE_INCREASE_BPS, PLATE_WASTE_BPS, POPULARITY_FACTOR_BPS,
    REGION_CAP_MULTIPLIER_BPS, REGION_COMPETITOR_INDEX_CENTS,
    REGION_FREIGHT_UPLIFT_BPS, VARIANCE_TOLERANCE_BPS, db, order_key, rhu,
    sign, touch,
)
from graph import count_lines_of, expected_base_units, latest_published, mix_lines_of


# ---------------------------------------------------------------------------
# Plate cost (PRD 3.5)
# ---------------------------------------------------------------------------
def plate_cost(item, recipe):
    uplift = REGION_FREIGHT_UPLIFT_BPS[item["region_code"]]
    s1 = rhu(recipe["portion_cost_micros"] * (10000 + uplift), 10000)
    s2 = rhu(s1 * (10000 + PLATE_WASTE_BPS), 10000)
    garnish = max(GARNISH_FLOOR_MICROS, rhu(s2 * GARNISH_BPS, 10000))
    plate_cost_micros = s2 + garnish
    plate_cost_cents = rhu(plate_cost_micros, 10000)
    item["plate_cost_micros"] = plate_cost_micros
    item["plate_cost_cents"] = plate_cost_cents
    item["food_cost_bps"] = rhu(plate_cost_cents * 10000, item["current_price_cents"])
    item["contribution_margin_cents"] = item["current_price_cents"] - plate_cost_cents
    item["allergen_mask"] = recipe["allergen_mask"]
    item["sodium_mcg_per_portion"] = recipe["sodium_mcg_per_portion"]
    item["cost_basis"] = recipe["cost_basis"]
    item["plate_cost_state"] = "FRESH"
    touch(item)
    return item


# ---------------------------------------------------------------------------
# Price-change projection (PRD 3.7)
# ---------------------------------------------------------------------------
def baseline_units_for(menu_item_id):
    candidates = []
    for review in db.period_reviews.values():
        if review["status"] != "CLOSED":
            continue
        lines = [line for line in mix_lines_of(review["id"])
                 if line["menu_item_id"] == menu_item_id]
        if not lines:
            continue
        candidates.append((review, lines[0]))
    if not candidates:
        return DEFAULT_BASELINE_UNITS
    candidates.sort(key=lambda pair: order_key(pair[0]))
    candidates.sort(key=lambda pair: pair[0]["period_end"], reverse=True)
    return candidates[0][1]["units_sold"]


def price_projection(item, proposed_price_cents, elasticity_bps):
    current = item["current_price_cents"]
    plate = item["plate_cost_cents"]

    # STEP 1
    difference = proposed_price_cents - current
    price_delta_bps = sign(difference) * rhu(abs(difference) * 10000, current)

    # STEP 2
    projected_unit_delta_bps = -sign(price_delta_bps) * rhu(
        abs(price_delta_bps) * elasticity_bps, 10000)

    # STEP 3
    region = item["region_code"]
    index_cap = rhu(REGION_COMPETITOR_INDEX_CENTS[region]
                    * REGION_CAP_MULTIPLIER_BPS[region], 10000)
    step_cap = rhu(current * (10000 + MAX_SINGLE_INCREASE_BPS), 10000)
    market_cap_price_cents = min(index_cap, step_cap)

    # STEP 4
    baseline_units = baseline_units_for(item["id"])
    projected_units = max(0, rhu(baseline_units * (10000 + projected_unit_delta_bps),
                                 10000))

    # STEP 5 -- always against the proposed price, never the capped price.
    projected_food_cost_bps = rhu(plate * 10000, proposed_price_cents)

    # STEP 6
    relief_bps = CAP_RELIEF_BPS if projected_food_cost_bps > item["target_food_cost_bps"] else 0
    effective_cap_price_cents = rhu(market_cap_price_cents * (10000 + relief_bps), 10000)

    # STEP 7
    projected_contribution_delta_cents = (
        projected_units * (proposed_price_cents - plate)
        - baseline_units * (current - plate))

    return {
        "baseline_units": baseline_units,
        "price_delta_bps": price_delta_bps,
        "projected_unit_delta_bps": projected_unit_delta_bps,
        "projected_units": projected_units,
        "projected_food_cost_bps": projected_food_cost_bps,
        "market_cap_price_cents": market_cap_price_cents,
        "effective_cap_price_cents": effective_cap_price_cents,
        "projected_contribution_delta_cents": projected_contribution_delta_cents,
    }


# ---------------------------------------------------------------------------
# Menu-mix classification (PRD 3.8)
# ---------------------------------------------------------------------------
def classify(review):
    lines = mix_lines_of(review["id"])
    mix_line_count = len(lines)
    total_units = sum(line["units_sold"] for line in lines)
    total_gross = sum(line["gross_sales_cents"] for line in lines)
    popularity_threshold_bps = rhu(POPULARITY_FACTOR_BPS, mix_line_count)

    for line in lines:
        if total_units > 0:
            line["mix_pct_bps"] = rhu(line["units_sold"] * 10000, total_units)
        else:
            line["mix_pct_bps"] = 0
        if line["units_sold"] > 0:
            line["cm_per_unit_cents"] = (
                rhu(line["gross_sales_cents"], line["units_sold"])
                - line["plate_cost_cents_snapshot"])
        else:
            line["cm_per_unit_cents"] = 0

    weighted = sum(line["units_sold"] * line["cm_per_unit_cents"] for line in lines)
    margin_threshold_cents = rhu(weighted, total_units) if total_units > 0 else 0

    for line in lines:
        popular = line["mix_pct_bps"] >= popularity_threshold_bps
        high_margin = line["cm_per_unit_cents"] >= margin_threshold_cents
        if popular and high_margin:
            margin_class = "STAR"
        elif popular:
            margin_class = "PLOWHORSE"
        elif high_margin:
            margin_class = "PUZZLE"
        else:
            margin_class = "DOG"
        line["margin_class"] = margin_class
        touch(line)
        item = db.menu_items.get(line["menu_item_id"])
        if item is not None:
            item["margin_class"] = margin_class
            touch(item)

    review["total_units_sold"] = total_units
    review["total_gross_sales_cents"] = total_gross
    review["popularity_threshold_bps"] = popularity_threshold_bps
    review["margin_threshold_cents"] = margin_threshold_cents
    review["status"] = "CLASSIFIED"
    touch(review)
    return review


# ---------------------------------------------------------------------------
# Theoretical versus actual variance (PRD 3.8)
# ---------------------------------------------------------------------------
def close_review(review):
    lines = count_lines_of(review["id"])
    actual_micros = 0
    theoretical_micros = 0
    for line in lines:
        chosen = latest_published(line["ingredient_id"])
        if chosen is None:
            unit_cost, pack_base_units = 0, 1
        else:
            unit_cost, pack_base_units = chosen
        line["valued_usage_micros"] = rhu(line["used_base_units"] * unit_cost,
                                          pack_base_units)
        actual_micros += line["valued_usage_micros"]
        theoretical_micros += rhu(line["expected_base_units"] * unit_cost,
                                  pack_base_units)
        touch(line)

    if review["basis"] == "SALES_MIX_BASED":
        theoretical = sum(line["units_sold"] * line["plate_cost_cents_snapshot"]
                          for line in mix_lines_of(review["id"]))
    else:
        theoretical = rhu(theoretical_micros, 10000)
    actual = rhu(actual_micros, 10000)

    review["theoretical_food_cost_cents"] = theoretical
    review["actual_food_cost_cents"] = actual
    if theoretical == 0:
        review["variance_bps"] = 0
        review["variance_flag"] = "NO_BASIS"
    else:
        difference = actual - theoretical
        variance_bps = sign(difference) * rhu(abs(difference) * 10000, theoretical)
        review["variance_bps"] = variance_bps
        review["variance_flag"] = ("OVER_TOLERANCE"
                                   if abs(variance_bps) > VARIANCE_TOLERANCE_BPS
                                   else "WITHIN_TOLERANCE")
    review["status"] = "CLOSED"
    review["closed_at"] = db.now()
    touch(review)
    return review


def refresh_count_line(line, review_id):
    line["expected_base_units"] = expected_base_units(review_id, line["ingredient_id"])
    line["used_base_units"] = max(0, line["opening_base_units"]
                                  + line["received_base_units"]
                                  - line["counted_base_units"])
    line["variance_base_units"] = line["used_base_units"] - line["expected_base_units"]
    return line


# ---------------------------------------------------------------------------
# LTO campaigns (PRD 3.9)
# ---------------------------------------------------------------------------
def lto_costing(campaign, item):
    plate = item["plate_cost_cents"]
    campaign["promo_plate_cost_cents"] = plate
    campaign["promo_food_cost_bps"] = rhu(plate * 10000, campaign["promo_price_cents"])
    campaign["forecast_contribution_cents"] = (
        campaign["forecast_units"] * (campaign["promo_price_cents"] - plate))
    campaign["status"] = "COSTED"
    touch(campaign)
    return campaign


def lto_post_promo(campaign, actual_units, actual_gross_sales_cents):
    support = rhu(actual_gross_sales_cents * LTO_SUPPORT_BPS, 10000)
    contribution = (actual_gross_sales_cents
                    - actual_units * campaign["promo_plate_cost_cents"]
                    - support)
    attainment = rhu(actual_units * 10000, campaign["forecast_units"])
    campaign["actual_units"] = actual_units
    campaign["actual_gross_sales_cents"] = actual_gross_sales_cents
    campaign["promo_support_cost_cents"] = support
    campaign["promo_contribution_cents"] = contribution
    campaign["forecast_attainment_bps"] = attainment
    campaign["verdict"] = ("PROFITABLE"
                           if contribution >= LTO_MIN_CONTRIBUTION_CENTS
                           and attainment >= LTO_MIN_ATTAINMENT_BPS
                           else "UNPROFITABLE")
    campaign["status"] = "CLOSED"
    campaign["reviewed_at"] = db.now()
    touch(campaign)
    return campaign
