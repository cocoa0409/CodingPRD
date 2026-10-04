"""Every calculation rule from SCAFFOLD.yaml Table 3 / PRD 2 and 3.

Rounding discipline (PRD 2.5): monetary outputs are integer cents rounded
half-up after each component, and any aggregation sums the already-rounded
components rather than rounding the total.
"""

import math
from decimal import Decimal

import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SALE_STAGING_FACTOR = Decimal("0.36")
PROVISIONAL_DIVISOR = Decimal("7")
FINAL_DIVISOR = Decimal("3")

SERVICE_TIERS = [
    (0, Decimal("0.00")),
    (4000, Decimal("0.15")),
    (8000, Decimal("0.18")),
    (12000, Decimal("0.20")),
]
BANDS = [(0, 4000), (4000, 8000), (8000, 12000), (12000, None)]

STAGE_MARKDOWN_PCT = {"S1": Decimal("0.25"), "S2": Decimal("0.40"),
                      "S3": Decimal("0.55"), "S4": Decimal("0.70")}
STAGE_ORDER = ["S1", "S2", "S3", "S4"]

WEEK_FACTORS = [Decimal("1.00"), Decimal("0.95"), Decimal("0.88"),
                Decimal("0.78"), Decimal("0.70")]
DEFAULT_WEEK_FACTOR = Decimal("0.70")

LIQUIDATION_TIERS = [(Decimal("0.40"), Decimal("0.90")),
                     (Decimal("0.30"), Decimal("0.70")),
                     (Decimal("0.30"), Decimal("0.55"))]

WEEKS_DEMAND_HORIZON = 4
WEEK_DEMAND_CENTS = 300000
SEASON_START = {"HARVEST": 38, "WINTER_HOLIDAY": 40, "SPRING": 10,
                "SUMMER": 26, "NOSTALGIA_CLASSIC": 1}
MARGIN_FLOOR_PCT = Decimal("0.30")

PROFILE_MULTIPLIER = {"FULL": Decimal("1.00"), "REGIONAL_TWEAK": Decimal("1.25"),
                      "MINIMAL": Decimal("0.55")}
DRIFT_BPS_GATE = Decimal("15000")
REGIONAL_TWEAK_BONUS = 4
LOCAL_EVENT_BONUS = 1
# Base count of slots an item is targeted to carry in a region before the tier
# multiplier and the local-event bonus are applied.  PRD 3.9 makes the MINIMAL
# variant read `18 - 4 == 14`, so the standing base is 18.
REGION_TARGET_SLOTS = 18

LINE_KINDS_COUNTED = {"RETAIL", "SEASONAL_DECOR", "NOSTALGIA"}
# PRD 3.2 — the attached-check retail subtotal is the sum over receipts whose
# status is one of DRAFT, RECONCILED, DISPUTED, SETTLED or CLOSED.
RECEIPT_SALES_STATUSES = {"DRAFT", "RECONCILED", "DISPUTED", "SETTLED", "CLOSED"}
# PRD 3.1 — the store day's own retail_sales_cents (and, consequently, its
# retail_transaction_count) is the sum over receipts whose status is one of
# DRAFT, RECONCILED, SETTLED or CLOSED; "a receipt in DISPUTED status is outside
# that set".  The two sets are deliberately different.
RECEIPT_DAY_SALES_STATUSES = {"DRAFT", "RECONCILED", "SETTLED", "CLOSED"}
BRAND_INCLUSION_STATUSES = {"RECONCILED", "SETTLED", "CLOSED"}
RECEIVING_STATUSES = {"RECEIVED", "RECONCILED"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def brand_of_location(location_rec):
    return db.brands.get(location_rec.get("brand_id")) if location_rec else None


def brand_of_store_day(day):
    return brand_of_location(db.locations.get(day.get("location_id")))


def store_day_of_check(check):
    return db.store_days.get(check.get("store_day_id"))


def counted_lines(receipt):
    """Lines with line_kind IN {RETAIL, SEASONAL_DECOR, NOSTALGIA}.

    A GIFT_CARD line is excluded from the base block entirely (PRD 3.3).
    """
    return [ln for ln in (receipt.get("lines") or [])
            if ln.get("line_kind") in LINE_KINDS_COUNTED]


def line_net_cents(line):
    """gross = effective_price * quantity; net = gross - half_up(gross*discount)."""
    item = db.items.get(line.get("item_id"))
    unit = line.get("unit_price_cents")
    if item is not None:
        unit = item.get("effective_price_cents", unit)
    else:
        unit = 0 if unit is None else unit
    gross = db.to_dec(unit) * db.to_dec(line.get("quantity"), Decimal(1))
    discount = db.two_dp(gross * db.to_dec(line.get("discount_pct"), Decimal(0)))
    return db.two_dp(gross - discount)


def _blocks(receipt):
    nets = [line_net_cents(ln) for ln in counted_lines(receipt)]
    base = sum(nets, Decimal(0))
    cleared = sum((db.two_dp(n * SALE_STAGING_FACTOR) for n in nets), Decimal(0))
    return base, cleared


# ---------------------------------------------------------------------------
# provisional_retail_revenue
# ---------------------------------------------------------------------------

def provisional_retail_revenue(receipt):
    base, cleared = _blocks(receipt)
    if receipt.get("guest_check_id"):
        return db.cents(base - db.two_dp(cleared / PROVISIONAL_DIVISOR))
    return db.cents(base)


# ---------------------------------------------------------------------------
# final_retail_revenue
# ---------------------------------------------------------------------------

def final_retail_revenue(receipt):
    base, cleared = _blocks(receipt)
    return db.cents(base - db.two_dp(cleared / FINAL_DIVISOR))


def recognition_policy(brand_rec):
    return (brand_rec or {}).get("retail_recognition_policy", "FINAL_ONLY") or "FINAL_ONLY"


def post_recognition(receipt, brand_rec):
    """Write the recognition pair on a receipt (PRD 3.4).

    The final figure is the one written to `recognized_retail_cents` under both
    policies.  The difference figure carries the divergence between the two
    postings, and PRD 3.4 states it plainly: "Under `FINAL_ONLY` ... the
    difference figure `recognition_delta_cents` [is] left at zero because there
    is only ever one posting."  Only `PROVISIONAL_THEN_FINAL` carries a delta.
    """
    receipt["provisional_retail_cents"] = db.cents(provisional_retail_revenue(receipt))
    receipt["recognized_retail_cents"] = db.cents(final_retail_revenue(receipt))
    if recognition_policy(brand_rec) == "FINAL_ONLY":
        receipt["recognition_delta_cents"] = 0
    else:
        receipt["recognition_delta_cents"] = (
            receipt["recognized_retail_cents"] - receipt["provisional_retail_cents"])
    return receipt


# ---------------------------------------------------------------------------
# compute_service_fee — marginal banded fee (NOT the tier walk)
# ---------------------------------------------------------------------------

def compute_service_fee(basis_cents):
    basis = db.to_dec(basis_cents)
    fee = Decimal(0)
    for index, (lower, upper) in enumerate(BANDS):
        portion = basis - Decimal(lower)
        if upper is not None:
            portion = min(portion, Decimal(upper - lower))
        if portion <= 0:
            if index > 0:
                break
            continue
        fee += db.to_dec(db.cents(portion * SERVICE_TIERS[index][1]))
    return db.cents(fee)


# ---------------------------------------------------------------------------
# combined_check_total — fixed evaluation order, followed literally
# ---------------------------------------------------------------------------

def check_retail_subtotal(check):
    """Step 1: sum of provisional_retail_cents over attached receipts."""
    total = 0
    for rec in db.receipts.values():
        if rec.get("guest_check_id") != check["id"]:
            continue
        if rec.get("status") in RECEIPT_SALES_STATUSES:
            total += rec.get("provisional_retail_cents", 0) or 0
    return total


def select_fee_tier(provisional_total):
    """Step 3: last tier whose min_total_cents <= the provisional total."""
    selected = 0
    for index, (min_total, _pct) in enumerate(SERVICE_TIERS):
        if min_total <= provisional_total:
            selected = index
    return selected


def recompute_check(check):
    """Recompute retail_subtotal_cents, service_fee_cents and total_cents."""
    check["retail_subtotal_cents"] = check_retail_subtotal(check)

    restaurant = check.get("restaurant_subtotal_cents", 0) or 0
    tip = check.get("tip_cents", 0) or 0
    retail = check["retail_subtotal_cents"]

    # Step 2: provisional total, used only to select the fee tier.
    provisional_total = restaurant + retail + tip
    select_fee_tier(provisional_total)

    # Step 4: banded, marginal fee over restaurant + retail (tip excluded).
    check["service_fee_cents"] = compute_service_fee(restaurant + retail)

    # Step 5: final total; the fee is never fed back into the tier walk.
    check["total_cents"] = restaurant + retail + tip + check["service_fee_cents"]
    return check


def allocated_restaurant_share(total_cents, restaurant_subtotal, retail_subtotal):
    """restaurant_share_basis == ALLOCATED (PRD 3.2)."""
    basis = restaurant_subtotal + retail_subtotal
    if basis <= 0:
        return 0
    return db.cents(db.to_dec(total_cents) * db.to_dec(restaurant_subtotal) / db.to_dec(basis))


def recompute_check_tip_fields(check):
    restaurant = check.get("restaurant_subtotal_cents", 0) or 0
    retail = check.get("retail_subtotal_cents", 0) or 0
    basis = restaurant + retail
    if basis <= 0:
        check["tip_pct"] = 0.0
    else:
        check["tip_pct"] = db.pct4(db.to_dec(check.get("tip_cents", 0) or 0) / db.to_dec(basis))
    return check


def recompute_check_tip_eligibility(check):
    """Conjunction over every shift that presented the check, and FINALIZED."""
    presenting = [s for s in db.staff_shifts.values()
                  if s.get("id") == check.get("presented_shift_id")]
    eligible = bool(presenting) and all(s.get("tip_eligible") for s in presenting)
    check["tip_eligible"] = bool(eligible and check.get("check_status") == "FINALIZED")
    return check


# ---------------------------------------------------------------------------
# retail_sales_per_guest
# ---------------------------------------------------------------------------

def retail_sales_of_day(store_day_id):
    total = 0
    for rec in db.receipts.values():
        if rec.get("store_day_id") != store_day_id:
            continue
        if rec.get("status") in RECEIPT_DAY_SALES_STATUSES:
            total += rec.get("provisional_retail_cents", 0) or 0
    return total


def recompute_store_day_retail_sales(day):
    day["retail_sales_cents"] = retail_sales_of_day(day["id"])
    return day


def recompute_store_day_per_guest(day):
    if not day.get("restaurant_guest_count"):
        day["retail_sales_per_guest_cents"] = 0
    else:
        day["retail_sales_per_guest_cents"] = db.cents(
            db.to_dec(day.get("retail_sales_cents", 0)) / db.to_dec(day["restaurant_guest_count"]))
    if not day.get("waiting_area_shopper_count"):
        day["provisional_retail_sales_per_guest_cents"] = 0
    else:
        day["provisional_retail_sales_per_guest_cents"] = db.cents(
            db.to_dec(day.get("retail_sales_cents", 0)) / db.to_dec(day["waiting_area_shopper_count"]))
    return day


def recompute_store_day_transaction_count(day):
    """Count of the day's receipts inside the day's retail-sales inclusion set.

    PRD 3.4: "Disputing a settled ticket is where the day's transaction count
    moves downward", and a DISPUTED receipt is outside the day's sales set
    (PRD 3.1), so the same set that feeds retail_sales_cents feeds this count.
    """
    day["retail_transaction_count"] = sum(
        1 for rec in db.receipts.values()
        if rec.get("store_day_id") == day["id"]
        and rec.get("status") in RECEIPT_DAY_SALES_STATUSES)
    return day


def recompute_store_day_retail_metrics(day):
    recompute_store_day_retail_sales(day)
    recompute_store_day_per_guest(day)
    return day


# ---------------------------------------------------------------------------
# derive_waiting_area_conversion_index
# ---------------------------------------------------------------------------

def tips_earned_cents(store_day_id):
    total = 0
    for check in db.guest_checks.values():
        if check.get("store_day_id") != store_day_id:
            continue
        if check.get("tip_eligible") and check.get("check_status") == "FINALIZED":
            total += check.get("tip_cents", 0) or 0
    return total


def recompute_conversion_index(day):
    shoppers = day.get("waiting_area_shopper_count", 0) or 0
    converted = day.get("waiting_area_converted_count", 0) or 0
    raw_bps = db.cents(db.to_dec(converted) * db.to_dec(10000) / db.to_dec(shoppers + 1))

    decay = min(Decimal(db.to_dec(day.get("retail_transaction_count", 0) or 0)) * Decimal("0.10"),
                Decimal("0.50"))
    conversion_bps = db.cents(db.to_dec(raw_bps) * (Decimal(1) - decay))

    retail_sales = day.get("retail_sales_cents", 0) or 0
    if retail_sales == 0:
        tip_share_bps = 0
    else:
        tip_share_bps = db.cents(db.to_dec(tips_earned_cents(day["id"])) * db.to_dec(10000)
                                 / db.to_dec(retail_sales))

    brand_rec = brand_of_store_day(day)
    weight = brand_rec.get("waiting_area_retail_weight_bps", 6000) if brand_rec else 6000
    blended = (db.to_dec(weight) * db.to_dec(conversion_bps)
               + db.to_dec(10000 - weight) * db.to_dec(tip_share_bps))
    day["waiting_area_conversion_index_bps"] = db.cents(blended / db.to_dec(10000))
    return day


# ---------------------------------------------------------------------------
# derive_tip_eligibility
# ---------------------------------------------------------------------------

TIP_ELIGIBLE_WORKCODES = {"SERVER", "CASHIER"}


def shift_store_day(shift):
    """The store day a shift's gate condition refers to.

    A shift carries a location, not a store day; the day in force is the
    location's most recent business day.
    """
    candidates = [d for d in db.store_days.values() if d.get("location_id") == shift.get("location_id")]
    if not candidates:
        return None
    return sorted(candidates, key=lambda d: (d.get("business_date") or "", d["_order"]))[-1]


def shift_minutes(shift):
    """Rounded-up whole hours, times sixty (PRD 3.6).

    PRD 3.6 pins the sub-hour carve-out explicitly: "A shift whose rounded-up
    length is zero hours — one shorter than an hour — has a minute count of zero
    and is ineligible regardless of its workcode."  At or above an hour the length
    is rounded **up** ("a shift of three hours and five minutes therefore counts
    as four hours, that is 240 minutes"), so 3:59 counts as 240 and 2:59 as 180.
    """
    start = db.parse_ts(shift.get("start_utc"), "start_utc")
    end = db.parse_ts(shift.get("end_utc"), "end_utc")
    seconds = (end - start).total_seconds()
    if seconds <= 0 or seconds < 3600:
        return 0
    return math.ceil(seconds / 3600.0) * 60


def derive_tip_eligibility(shift):
    location_rec = db.locations.get(shift.get("location_id"))
    brand_rec = brand_of_location(location_rec)
    minimum = brand_rec.get("tip_minimum_minutes", 240) if brand_rec else 240

    minutes = shift_minutes(shift)
    shift["tip_eligible_minutes"] = minutes

    day = shift_store_day(shift)
    gate = day.get("conversion_gate", "OPEN") if day else "OPEN"

    shift["tip_eligible"] = bool(
        shift.get("workcode") in TIP_ELIGIBLE_WORKCODES
        and minutes >= minimum
        and gate == "OPEN")
    return shift


def recompute_presented_checks(shift):
    """Recompute tip_eligible for every check this shift presented."""
    for check in db.guest_checks.values():
        if check.get("presented_shift_id") != shift.get("id"):
            continue
        recompute_check_tip_eligibility(check)
        recompute_check_tip_fields(check)


# ---------------------------------------------------------------------------
# apply_stacked_markdown
# ---------------------------------------------------------------------------

def overlapping_active_schedules(item_id):
    return [s for s in db.clearance_schedules.values()
            if s.get("item_id") == item_id
            and s.get("status") in {"ACTIVE", "EXTENDED"}]


def apply_stacked_markdown(item_rec):
    """Recompute effective_price_cents (highest-of) and compounded_price_cents."""
    active = overlapping_active_schedules(item_rec["id"])

    gross = db.to_dec(item_rec.get("unit_retail_cents"))
    for schedule in active:
        gross = db.to_dec(db.cents(gross * (Decimal(1) - db.to_dec(schedule.get("markdown_pct")))))
    week = item_rec.get("clearance_week", 0) or 0
    factor = WEEK_FACTORS[week] if 0 <= week < len(WEEK_FACTORS) else DEFAULT_WEEK_FACTOR
    item_rec["effective_price_cents"] = db.cents(gross * factor)

    compounded = db.to_dec(item_rec.get("unit_retail_cents"))
    ordered = sorted(active, key=lambda s: (s.get("activated_at") or s.get("created_at"), s["_order"]))
    for schedule in ordered:
        compounded = db.to_dec(db.cents(compounded * (Decimal(1) - db.to_dec(schedule.get("markdown_pct")))))
    item_rec["compounded_price_cents"] = db.cents(compounded)

    if active:
        item_rec["current_markdown_pct"] = db.pct4(max(
            (db.to_dec(s.get("markdown_pct")) for s in active), default=Decimal(0)))
    return item_rec


def item_clearance_week(item_rec):
    """Completed whole weeks since the most recent activation, capped at 4."""
    activated = [s for s in db.clearance_schedules.values()
                 if s.get("item_id") == item_rec["id"] and s.get("activated_at")]
    if not activated:
        return 0
    latest = max(db.parse_ts(s["activated_at"]) for s in activated)
    weeks = int((db.now() - latest).total_seconds() // (7 * 24 * 3600))
    return max(0, min(4, weeks))


# ---------------------------------------------------------------------------
# liquidation_tier_price
# ---------------------------------------------------------------------------

def liquidation_tier_price(schedule, item_rec):
    total_units = schedule.get("remaining_units", 0) or 0
    if total_units <= 0:
        return 0, 0, []
    unit_value = min(item_rec.get("unit_cost_cents", 0), item_rec.get("unit_retail_cents", 0))

    buckets = []
    spill = total_units
    for share, rate in LIQUIDATION_TIERS:
        entitled = int(float(db.to_dec(total_units) * share))
        take = min(spill, entitled)
        if take > 0:
            buckets.append({"units": take, "rate": rate,
                            "price_cents": db.cents(db.to_dec(unit_value) * rate)})
        spill -= take
    if spill > 0:
        buckets.append({"units": spill, "rate": LIQUIDATION_TIERS[-1][1],
                        "price_cents": db.cents(db.to_dec(unit_value) * LIQUIDATION_TIERS[-1][1])})

    weighted = sum(db.to_dec(b["units"]) * db.to_dec(b["price_cents"]) for b in buckets)
    blended = db.cents(weighted / db.to_dec(total_units))
    return buckets[0]["price_cents"], blended, [b["units"] for b in buckets]


# ---------------------------------------------------------------------------
# project_import_need
# ---------------------------------------------------------------------------

def current_iso_week():
    return db.now().isocalendar()[1]


def derive_order_deadline(item_rec):
    season_week = SEASON_START.get(item_rec.get("theme_code"), 1)
    days_available = (season_week - current_iso_week()) * 7
    return days_available < (item_rec.get("import_lead_time_days", 0) or 0)


def unit_margin_cents(item_rec):
    return (item_rec.get("unit_retail_cents", 0) or 0) - (item_rec.get("unit_cost_cents", 0) or 0)


def margin_floor_cents(item_rec):
    # PRD 3.9: "The margin floor uses flooring rather than half-up rounding."
    return db.floor_int(db.to_dec(item_rec.get("unit_cost_cents", 0)) * (Decimal(1) + MARGIN_FLOOR_PCT))


def projected_import_need(item_rec, deadline=None):
    if item_rec.get("status") not in {"ACTIVE", "CLEARANCE"}:
        return 0
    if deadline is None:
        deadline = derive_order_deadline(item_rec)

    retail = item_rec.get("unit_retail_cents", 0) or 0
    if retail <= 0:
        return 0
    threshold_units = math.ceil(WEEKS_DEMAND_HORIZON * WEEK_DEMAND_CENTS / retail)
    threshold_units += item_rec.get("on_hand_units", 0) or 0

    live_need = threshold_units
    if deadline and unit_margin_cents(item_rec) < margin_floor_cents(item_rec):
        live_need = 0
    return live_need


# ---------------------------------------------------------------------------
# regionally_adjusted_slot_count
# ---------------------------------------------------------------------------

def region_fit_values(version_rec):
    location_rec = db.locations.get(version_rec.get("location_id")) or {}
    tier = location_rec.get("assortment_tier") or version_rec.get("assortment_tier")
    multiplier = PROFILE_MULTIPLIER.get(tier, Decimal("1.00"))
    drift = (multiplier - Decimal("1.00")) * Decimal("100000")

    target_slots = REGION_TARGET_SLOTS
    tweak_bonus = 0
    if drift > DRIFT_BPS_GATE:
        target_slots += REGIONAL_TWEAK_BONUS
        tweak_bonus = REGIONAL_TWEAK_BONUS
    elif drift < -DRIFT_BPS_GATE:
        target_slots -= REGIONAL_TWEAK_BONUS
        tweak_bonus = -REGIONAL_TWEAK_BONUS

    codes = location_rec.get("local_event_codes") or []
    local_bonus = len(codes) * LOCAL_EVENT_BONUS

    return {
        "regionally_adjusted_slot_count": target_slots + local_bonus,
        "regional_tweak_bonus": tweak_bonus,
        "local_event_bonus": local_bonus,
        "drift_bps": int(drift),
    }


# ---------------------------------------------------------------------------
# Assortment tier carry rules (PRD 2.13)
# ---------------------------------------------------------------------------

REGION_CORE_THEMES = {
    "NORTHEAST": {"HARVEST", "WINTER_HOLIDAY", "NOSTALGIA_CLASSIC"},
    "SOUTHEAST": {"HARVEST", "WINTER_HOLIDAY", "NOSTALGIA_CLASSIC", "SPRING"},
    "MIDWEST": {"HARVEST", "WINTER_HOLIDAY", "NOSTALGIA_CLASSIC", "SUMMER"},
    "SOUTHWEST": {"HARVEST", "SUMMER", "NOSTALGIA_CLASSIC"},
    "WEST": {"SPRING", "SUMMER", "NOSTALGIA_CLASSIC"},
}
ALL_THEMES = set(SEASON_START.keys())


def theme_carried(location_rec, theme_code):
    if location_rec is None:
        return True
    tier = location_rec.get("assortment_tier")
    codes = set(location_rec.get("local_event_codes") or [])
    if tier == "FULL":
        return True
    if tier == "REGIONAL_TWEAK":
        return theme_code in (REGION_CORE_THEMES.get(location_rec.get("region_code"), set()) | codes)
    if tier == "MINIMAL":
        return theme_code in codes
    return True


# ---------------------------------------------------------------------------
# Brand roll-ups (PRD 2.8)
# ---------------------------------------------------------------------------

def recompute_brand_revenue(brand_rec):
    provisional = 0
    recognized = 0
    for rec in db.receipts.values():
        day = db.store_days.get(rec.get("store_day_id"))
        if day is None:
            continue
        location_rec = db.locations.get(day.get("location_id"))
        if location_rec is None or location_rec.get("brand_id") != brand_rec["id"]:
            continue
        if rec.get("status") not in BRAND_INCLUSION_STATUSES:
            continue
        provisional += rec.get("provisional_retail_cents", 0) or 0
        recognized += rec.get("recognized_retail_cents", 0) or 0
    brand_rec["provisional_retail_revenue_cents"] = provisional
    brand_rec["recognized_retail_revenue_cents"] = recognized
    return brand_rec


def recompute_brand_rpg(brand_rec):
    """Guest-count-weighted roll-up over CLOSED store days of the fiscal period."""
    location_ids = {loc["id"] for loc in db.locations.values()
                    if loc.get("brand_id") == brand_rec["id"]}
    guests = 0
    weighted = 0
    for day in db.store_days.values():
        if day.get("location_id") not in location_ids:
            continue
        if day.get("day_status") != "CLOSED":
            continue
        count = day.get("restaurant_guest_count", 0) or 0
        guests += count
        weighted += count * (day.get("retail_sales_per_guest_cents", 0) or 0)
    brand_rec["brand_retail_sales_per_guest_cents"] = (
        db.cents(db.to_dec(weighted) / db.to_dec(guests)) if guests > 0 else 0)
    return brand_rec


# ---------------------------------------------------------------------------
# Location posture (PRD 2.8)
# ---------------------------------------------------------------------------

def recompute_location_posture(location_rec):
    brand_rec = brand_of_location(location_rec)
    corridor = brand_rec.get("food_storage_corridor_units", 40) if brand_rec else 40
    committed = sum(t.get("declared_units", 0) or 0 for t in db.transfers.values()
                    if t.get("location_id") == location_rec["id"]
                    and t.get("status") == "IN_TRANSIT")
    location_rec["backroom_committed_units"] = committed
    location_rec["staging_free_units"] = (
        (location_rec.get("backroom_capacity_units", 0) or 0)
        - (location_rec.get("backroom_occupancy_units", 0) or 0)
        - committed
        - corridor)
    return location_rec


def recompute_active_clearance_count(location_rec):
    location_rec["active_clearance_count"] = sum(
        1 for s in db.clearance_schedules.values()
        if s.get("location_id") == location_rec["id"]
        and s.get("status") in {"ACTIVE", "EXTENDED"})
    return location_rec


def recompute_slot_count(version_rec):
    version_rec["slot_count"] = sum(
        1 for s in db.planogram_slots.values()
        if s.get("planogram_version_id") == version_rec["id"] and s.get("status") != "VACATED")
    return version_rec