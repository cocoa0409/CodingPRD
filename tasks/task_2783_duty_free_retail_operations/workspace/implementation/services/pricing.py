"""The per-category allowance waterfall (PRD sections 3.5 to 3.7)."""
import db
from errors import ApiError
from services.money import apply_bps

SUSPENDED_ESTIMATE = "SUSPENDED_ESTIMATE"
EXEMPT_CONFIRMED_FINAL = "EXEMPT_CONFIRMED_FINAL"


def lines_of(sale):
    """Basket lines in ascending created_at order (creation order breaks ties)."""
    return db.ordered(db.sale_lines, lambda line: line["sale_id"] == sale["id"])


def active_rule(destination_country, category):
    for rule in db.ordered(db.allowance_rules,
                           lambda r: r["status"] == "ACTIVE"
                           and r["destination_country"] == destination_country
                           and r["category"] == category):
        return rule
    return None


def effective_destination(itinerary, variant):
    if variant == SUSPENDED_ESTIMATE:
        return itinerary["destination_country"]
    if itinerary["has_connection"]:
        return itinerary["final_destination_country"]
    return itinerary["destination_country"]


def require_rules(sale, destination_country):
    """Tier 11: an ACTIVE rule must exist for every distinct category in the basket."""
    for line in lines_of(sale):
        product = db.products[line["product_id"]]
        if active_rule(destination_country, product["category"]) is None:
            raise ApiError(
                "ERR_ALLOWANCE_RULE_MISSING",
                "No ACTIVE arrival-allowance rule for %s / %s." % (destination_country, product["category"]),
            )


def price(sale, variant):
    itinerary = db.itineraries[sale["itinerary_id"]]
    destination = effective_destination(itinerary, variant)
    consumed = {}
    advisory = {}
    gross = 0
    exempt = 0
    duty = 0
    for line in lines_of(sale):
        product = db.products[line["product_id"]]
        rule = active_rule(destination, product["category"])
        if rule is None:
            raise ApiError(
                "ERR_ALLOWANCE_RULE_MISSING",
                "No ACTIVE arrival-allowance rule for %s / %s." % (destination, product["category"]),
            )
        category = product["category"]
        consumed_before = consumed.get(category, 0)
        qty = line["qty"]
        running = consumed_before + qty
        excess = 0
        if running > rule["allowance_units"]:
            excess = min(qty, running - rule["allowance_units"])
        consumed[category] = running
        unit_price = line["unit_price_cents"]
        line["allowance_excess_qty"] = excess
        line["line_total_cents"] = qty * unit_price
        line["line_exempt_cents"] = (qty - excess) * unit_price
        line["line_duty_cents"] = apply_bps(
            excess * unit_price, product["duty_rate_bps"] + product["vat_rate_bps"]
        )
        advisory[category] = rule["advisory_text"]
        gross += line["line_total_cents"]
        exempt += line["line_exempt_cents"]
        duty += line["line_duty_cents"]
    sale["gross_amount_cents"] = gross
    sale["exempt_amount_cents"] = exempt
    sale["duty_liability_cents"] = duty
    sale["effective_destination_country"] = destination
    sale["eligibility_variant"] = variant
    sale["arrival_advisory"] = [advisory[category] for category in sorted(advisory)]


def recompute_gross(sale):
    sale["gross_amount_cents"] = sum(line["line_total_cents"] for line in lines_of(sale))


def forfeit(sale):
    """Tampered-seal forfeiture: every unit falls outside the allowance."""
    duty = 0
    for line in lines_of(sale):
        product = db.products[line["product_id"]]
        line["allowance_excess_qty"] = line["qty"]
        line["line_exempt_cents"] = 0
        line["line_duty_cents"] = apply_bps(
            line["qty"] * line["unit_price_cents"],
            product["duty_rate_bps"] + product["vat_rate_bps"],
        )
        duty += line["line_duty_cents"]
    sale["exempt_amount_cents"] = 0
    sale["duty_liability_cents"] = duty


def revert_to_cart(sale):
    """The amendment compensation of PRD section 3.4."""
    for line in lines_of(sale):
        line["allowance_excess_qty"] = 0
        line["line_exempt_cents"] = 0
        line["line_duty_cents"] = 0
    sale["fulfillment_status"] = "CART"
    sale["exempt_amount_cents"] = 0
    sale["duty_liability_cents"] = 0
    sale["eligibility_variant"] = None
    sale["effective_destination_country"] = None
    sale["cleared_at"] = None
    sale["arrival_advisory"] = []
    sale["sealed_bag_required"] = False


def sealed_bag_required(sale):
    itinerary = db.itineraries[sale["itinerary_id"]]
    terminal = db.terminals[sale["terminal_id"]]
    if terminal["sealed_bag_regime"] != "ICAO_STEB":
        return False
    if not itinerary["has_connection"]:
        return False
    for line in lines_of(sale):
        if db.products[line["product_id"]]["is_liquid"]:
            return True
    return False


def total_liquid_ml(sale):
    total = 0
    for line in lines_of(sale):
        product = db.products[line["product_id"]]
        if product["is_liquid"]:
            total += line["qty"] * (product["liquid_ml"] or 0)
    return total
