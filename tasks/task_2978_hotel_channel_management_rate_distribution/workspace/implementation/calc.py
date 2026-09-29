"""Derived-value calculations (PRD 2.6, 3.1, 3.2, 3.4, 3.6, 3.8, 3.9, 3.11)."""

import refs
import store
from refs import get, rows, where

LOYALTY_TIER_1_FLOOR_CENTS = 50000
LOYALTY_TIER_2_FLOOR_CENTS = 70000
MAX_DERIVATION_DEPTH = 2
MAX_JOB_ATTEMPTS = 3
CONNECTION_FAILURE_SUSPEND_THRESHOLD = 3
PROMO_STACK_CAP_BP = 3000
PACE_BASELINE_WINDOW_DAYS = 7
STLY_OFFSET_DAYS = 364
PACE_AHEAD_BP = 11000
PACE_BEHIND_BP = 9000
MIN_MIX_ROOM_NIGHTS = 1
FREEZE_PRE_BUFFER_MINUTES = 60
PROMO_KIND_ORDER = ("MEMBER_RATE", "GEO_OFFER", "PACKAGE_INCLUSION")


# --- rounding ------------------------------------------------------------

def rdiv(num, den):
    """Exact quotient rounded half up, away from zero on an exact half."""
    if den == 0:
        return None
    negative = (num < 0) != (den < 0)
    n, d = abs(num), abs(den)
    q = (2 * n + d) // (2 * d)
    return -q if negative else q


def apply_bp(amount, bp):
    return rdiv(amount * bp, 10000)


def floor_div(num, den):
    return num // den


# --- rate plan derivation (3.2) -----------------------------------------

def derivation_depth(parent):
    if parent is None:
        return 0
    return parent["derivation_depth"] + 1


def resolve_base_amount(plan):
    parent_id = plan.get("parent_rate_plan_id")
    if parent_id is None:
        return plan.get("base_amount_cents")
    parent = get("rate_plans", parent_id)
    if parent is None:
        return plan.get("base_amount_cents")
    parent_base = parent.get("resolved_base_amount_cents")
    if parent_base is None:
        parent_base = resolve_base_amount(parent)
    kind = plan.get("offset_kind") or "NONE"
    if kind == "PERCENT":
        return rdiv(parent_base * (10000 + (plan.get("offset_bp") or 0)), 10000)
    if kind == "AMOUNT":
        return parent_base + (plan.get("offset_amount_cents") or 0)
    return parent_base


def rederive_family(plan):
    """Re-derive this plan and every descendant, parent before child.

    Per PRD 2.9 a descendant whose resolved amount the cascade actually moved is
    an entity "touched" by the request, so it takes its own version bump; the
    root's own bump is left to the caller, which owns the direct mutation.
    """
    family = refs.plan_family(plan)
    for member in family:
        previous = member.get("resolved_base_amount_cents")
        member["resolved_base_amount_cents"] = resolve_base_amount(member)
        if member is not plan and member["resolved_base_amount_cents"] != previous:
            store.bump(member)


# --- promotion-free distributed rate (3.4) ------------------------------

def distributed_rate(plan, channel):
    amount = plan["resolved_base_amount_cents"]
    amount = rdiv(amount * (10000 + channel["sell_adjustment_bp"]), 10000)
    amount = clamp(amount, plan)
    return amount + plan["package_inclusion_cents"]


def clamp(amount, plan):
    if amount < plan["floor_amount_cents"]:
        return plan["floor_amount_cents"]
    if amount > plan["ceiling_amount_cents"]:
        return plan["ceiling_amount_cents"]
    return amount


# --- sell rate resolution (3.6) -----------------------------------------

def promotions_of_plan(plan_id):
    return where("promotions", rate_plan_id=plan_id)


def approved_member_promo_in_play(plan, dates):
    for promo in promotions_of_plan(plan["id"]):
        if promo["approval_status"] != "APPROVED":
            continue
        if promo["promo_kind"] != "MEMBER_RATE":
            continue
        for day in dates:
            if promo["start_date"] <= day <= promo["end_date"]:
                return True
    return False


def eligible_promotions(plan, stay_date, member_flag, geo_market_code):
    """At most one approved promotion per kind, earliest created_at wins."""
    picks = {}
    for promo in promotions_of_plan(plan["id"]):
        if promo["approval_status"] != "APPROVED":
            continue
        if not (promo["start_date"] <= stay_date <= promo["end_date"]):
            continue
        kind = promo["promo_kind"]
        if kind == "MEMBER_RATE" and not member_flag:
            continue
        if kind == "GEO_OFFER":
            if geo_market_code is None:
                continue
            if geo_market_code not in (promo["geo_market_codes"] or []):
                continue
        current = picks.get(kind)
        if current is None or (promo["created_at"], promo["_seq"]) < (
                current["created_at"], current["_seq"]):
            picks[kind] = promo
    return [picks[kind] for kind in PROMO_KIND_ORDER if kind in picks]


def resolve_sell_rate(plan, channel, stay_date, member_flag=False,
                      geo_market_code=None):
    """The six ordered steps of PRD 3.6, with every intermediate exposed."""
    base = plan["resolved_base_amount_cents"]
    running = base
    applied = []
    for promo in eligible_promotions(plan, stay_date, member_flag, geo_market_code):
        applied.append(promo["code"])
        if promo["discount_kind"] == "PERCENT":
            running = rdiv(running * (10000 - promo["discount_bp"]), 10000)
        else:
            running = running - promo["discount_amount_cents"]
    total_discount = base - running
    cap = floor_div(base * PROMO_STACK_CAP_BP, 10000)
    if total_discount > cap:
        total_discount = cap
    running = base - total_discount
    adjusted = rdiv(running * (10000 + channel["sell_adjustment_bp"]), 10000)
    clamped = clamp(adjusted, plan)
    sell = clamped + plan["package_inclusion_cents"]
    return {
        "base_amount_cents": base,
        "promotion_discount_cents": total_discount,
        "discount_cap_cents": cap,
        "channel_adjusted_cents": adjusted,
        "clamped_cents": clamped,
        "sell_amount_cents": sell,
        "applied_promotion_codes": applied,
    }


# --- content parity and rate mismatch (3.4) -----------------------------

def parity_verdict(mapping):
    room_type = get("room_types", mapping["room_type_id"])
    prop = refs.prop_of_room_type(room_type)
    if mapping["content_description_hash"] is None:
        return "OUT_OF_PARITY"
    if mapping["content_description_hash"] != room_type["master_description_hash"]:
        return "OUT_OF_PARITY"
    if mapping["content_image_count"] is None:
        return "OUT_OF_PARITY"
    if mapping["content_image_count"] < prop["required_image_count"]:
        return "OUT_OF_PARITY"
    return "IN_PARITY"


def mismatch_verdict(mapping):
    pushed = mapping["last_pushed_rate_cents"]
    observed = mapping["observed_rate_cents"]
    if pushed is None or observed is None:
        return "UNKNOWN", None
    delta = observed - pushed
    room_type = get("room_types", mapping["room_type_id"])
    prop = refs.prop_of_room_type(room_type)
    tolerance = prop["rate_mismatch_tolerance_cents"]
    state = "MISMATCHED" if abs(delta) > tolerance else "IN_SYNC"
    return state, delta


# --- pooled inventory arithmetic (3.8) ----------------------------------

def effective_overbooking_bp(room_type):
    own = room_type.get("overbooking_pct_bp")
    if own is not None:
        return own
    return refs.prop_of_room_type(room_type)["overbooking_pct_bp"]


def overbooking_ceiling(room_type):
    capacity = room_type["physical_capacity_units"]
    uplift = floor_div(capacity * effective_overbooking_bp(room_type), 10000)
    return capacity + uplift


def consumed_units_for(alloc):
    """Peak per-night count of the CONFIRMED reservations this allotment carries.

    PRD 3.8 pins two things at once: a new allotment "starts with consumed_units
    0", and consumed units are the peak per-night count of CONFIRMED reservations
    on the channel inside the window. The two only agree when the count is taken
    over the reservations that actually *drew from this allotment* -- PRD 3.9
    moves consumed_units on an allotment draw and returns a unit to the shared
    pool on a pool draw -- so a stay that took its unit from the shared pool
    before this block existed is not retroactively charged to it.
    """
    peak = 0
    reservations = refs.confirmed_reservations()
    for day in refs.day_span(alloc["start_date"], alloc["end_date"]):
        count = 0
        for res in reservations:
            if res.get("_draw_allocation_id") != alloc["id"]:
                continue
            if refs.stay_covers(res, day):
                count += 1
        if count > peak:
            peak = count
    if peak > alloc["allocated_units"]:
        peak = alloc["allocated_units"]
    return peak


def held_units_on(room_type_id, day_s, exclude_ids=()):
    total = 0
    for alloc in where("allocations", room_type_id=room_type_id):
        if alloc["allocation_state"] not in ("OPEN", "EXHAUSTED"):
            continue
        if alloc["id"] in exclude_ids:
            continue
        if not (alloc["start_date"] <= day_s <= alloc["end_date"]):
            continue
        unconsumed = alloc["allocated_units"] - alloc["consumed_units"]
        if unconsumed > 0:
            total += unconsumed
    return total


def committed_units_on(room_type_id, day_s):
    count = 0
    for res in refs.confirmed_reservations():
        if res["room_type_id"] != room_type_id:
            continue
        if refs.stay_covers(res, day_s):
            count += 1
    return count


def pooled_state_of(physical, ceiling, allocated, committed, shared):
    if committed > physical:
        return "OVERSOLD"
    if shared == 0:
        return "EXHAUSTED"
    if allocated + committed >= physical:
        return "TIGHT"
    return "OPEN"


def day_numbers(day):
    """The five derived numbers of one inventory day, freshly computed."""
    room_type = refs.room_type_of_day(day)
    physical = room_type["physical_capacity_units"]
    ceiling = overbooking_ceiling(room_type)
    allocated = held_units_on(day["room_type_id"], day["stay_date"])
    committed = committed_units_on(day["room_type_id"], day["stay_date"])
    shared = ceiling - allocated - committed
    return {
        "physical_capacity_units": physical,
        "overbooking_ceiling_units": ceiling,
        "allocated_units": allocated,
        "committed_units": committed,
        "shared_pool_units": shared,
        "pooled_state": pooled_state_of(physical, ceiling, allocated, committed, shared),
    }


# --- restriction effects (3.7) ------------------------------------------

def scoped_restrictions(room_type_id, rate_plan_id):
    out = []
    for restriction in where("restrictions", room_type_id=room_type_id):
        if restriction["restriction_state"] != "ACTIVE":
            continue
        scope = restriction["rate_plan_id"]
        if scope is not None and scope != rate_plan_id:
            continue
        out.append(restriction)
    return out


def restriction_block(room_type_id, rate_plan_id, arrival_date, nights):
    """First blocking restriction verdict in the fixed STOP_SELL, CTA, MIN_STAY order."""
    scoped = scoped_restrictions(room_type_id, rate_plan_id)
    night_list = refs.stay_nights(arrival_date, nights)
    for restriction in scoped:
        if restriction["restriction_type"] != "STOP_SELL":
            continue
        for night in night_list:
            if refs.covers(restriction, night):
                return "ERR_STOP_SELL_ACTIVE"
    for restriction in scoped:
        if restriction["restriction_type"] != "CLOSED_TO_ARRIVAL":
            continue
        if refs.covers(restriction, arrival_date):
            return "ERR_CLOSED_TO_ARRIVAL"
    minimum = 0
    for restriction in scoped:
        if restriction["restriction_type"] != "MIN_STAY":
            continue
        if not refs.covers(restriction, arrival_date):
            continue
        value = restriction["value_nights"] or 0
        if value > minimum:
            minimum = value
    if nights < minimum:
        return "ERR_MIN_STAY_NOT_MET"
    return None


# --- reservation charging (3.9) -----------------------------------------

def loyalty_tier_bp(gross):
    if gross < LOYALTY_TIER_1_FLOOR_CENTS:
        return 0
    if gross < LOYALTY_TIER_2_FLOOR_CENTS:
        return 400
    return 600


def charge_stay(plan, channel, arrival_date, nights, member_flag, geo_market_code):
    breakdown = []
    gross = 0
    commission = 0
    for night in refs.stay_nights(arrival_date, nights):
        quote = resolve_sell_rate(plan, channel, night, member_flag, geo_market_code)
        sell = quote["sell_amount_cents"]
        commissionable = sell - plan["package_inclusion_cents"]
        night_commission = rdiv(commissionable * channel["commission_bp"], 10000)
        breakdown.append({
            "stay_date": night,
            "sell_rate_cents": sell,
            "commissionable_cents": commissionable,
            "commission_cents": night_commission,
        })
        gross += sell
        commission += night_commission
    net = gross - commission
    loyalty = rdiv(net * loyalty_tier_bp(gross), 10000)
    return {
        "nightly_breakdown": breakdown,
        "gross_amount_cents": gross,
        "commission_amount_cents": commission,
        "net_amount_cents": net,
        "loyalty_credit_cents": loyalty,
    }


# --- analytics (3.11) ---------------------------------------------------

def window_amounts(channel_id, start_date, end_date, basis):
    gross = 0
    commission = 0
    room_nights = 0
    for res in refs.confirmed_reservations():
        if res["channel_id"] != channel_id:
            continue
        if basis == "BOOKED":
            booked_date = res["created_at"][0:10]
            if not (start_date <= booked_date <= end_date):
                continue
            gross += res["gross_amount_cents"]
            commission += res["commission_amount_cents"]
            room_nights += res["nights"]
        else:
            for night in res["nightly_breakdown"]:
                if not (start_date <= night["stay_date"] <= end_date):
                    continue
                gross += night["sell_rate_cents"]
                commission += night["commission_cents"]
                room_nights += 1
    net = gross - commission
    ratio = rdiv(commission * 10000, gross) if gross > 0 else None
    adr = rdiv(net * 10000, room_nights * 10000) if room_nights > 0 else None
    return {
        "gross_amount_cents": gross,
        "commission_amount_cents": commission,
        "net_amount_cents": net,
        "room_nights": room_nights,
        "net_adr_cents": adr,
        "commission_cost_ratio_bp": ratio,
    }


def health_score_bp(channel_id):
    resolved = 0
    applied = 0
    for job in rows("jobs"):
        mapping = get("mappings", job["channel_mapping_id"])
        if mapping is None or mapping["channel_id"] != channel_id:
            continue
        if job["job_state"] == "APPLIED":
            applied += 1
            resolved += 1
        elif job["job_state"] == "REJECTED":
            resolved += 1
    if resolved == 0:
        return None
    return rdiv(applied * 10000, resolved)


def on_the_books(room_type_id, stay_date, cutoff_date):
    count = 0
    for res in refs.confirmed_reservations():
        if res["room_type_id"] != room_type_id:
            continue
        if not (res["arrival_date"] <= stay_date < res["departure_date"]):
            continue
        if res["created_at"][0:10] > cutoff_date:
            continue
        count += 1
    return count


def booking_pace(room_type, target_stay_date, baseline):
    as_of = refs.clock_date_str()
    days_out = (refs.pd(target_stay_date) - refs.pd(as_of)).days
    target = on_the_books(room_type["id"], target_stay_date, as_of)
    if baseline == "STLY":
        baseline_date = refs.shift(target_stay_date, -STLY_OFFSET_DAYS)
        baseline_nights = on_the_books(
            room_type["id"], baseline_date, refs.shift(baseline_date, -days_out))
        multiplier = 1
    else:
        baseline_nights = 0
        for step in range(PACE_BASELINE_WINDOW_DAYS, 0, -1):
            day = refs.shift(target_stay_date, -step)
            baseline_nights += on_the_books(
                room_type["id"], day, refs.shift(day, -days_out))
        multiplier = PACE_BASELINE_WINDOW_DAYS
    if baseline_nights == 0:
        index = None
        state = "NO_BASELINE"
    else:
        index = rdiv(target * multiplier * 10000, baseline_nights)
        if index > PACE_AHEAD_BP:
            state = "AHEAD"
        elif index >= PACE_BEHIND_BP:
            state = "ON_PACE"
        else:
            state = "BEHIND"
    return {
        "room_type_id": room_type["id"],
        "target_stay_date": target_stay_date,
        "baseline": baseline,
        "as_of_date": as_of,
        "days_out": days_out,
        "target_room_nights": target,
        "baseline_room_nights": baseline_nights,
        "pace_index_bp": index,
        "pace_state": state,
    }


def channel_mix(prop, start_date, end_date):
    entries = []
    for channel in where("channels", property_id=prop["id"]):
        connection = refs.connection_of_channel(channel["id"])
        if connection is None:
            continue
        if connection["connection_state"] not in ("HEALTHY", "DEGRADED"):
            continue
        metrics = window_amounts(channel["id"], start_date, end_date, "STAY")
        if metrics["room_nights"] < MIN_MIX_ROOM_NIGHTS:
            continue
        entries.append((channel, metrics))
    entries.sort(key=lambda pair: (
        -pair[1]["net_adr_cents"],
        pair[0]["commission_bp"],
        pair[0]["created_at"],
        pair[0]["_seq"],
    ))
    ranked = []
    for position, pair in enumerate(entries, start=1):
        channel, metrics = pair
        ranked.append({
            "rank": position,
            "net_adr_cents": metrics["net_adr_cents"],
            "commission_bp": channel["commission_bp"],
            "commission_cost_ratio_bp": metrics["commission_cost_ratio_bp"],
            "room_nights": metrics["room_nights"],
        })
    return ranked
