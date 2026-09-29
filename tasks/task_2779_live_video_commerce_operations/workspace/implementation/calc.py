"""Calculations, derived-field reconciliation and cascades (PRD 2.9-2.11, 3.3-3.9).

Every monetary figure is an integer count of cents and every fractional cent is
rounded half up at the point the PRD names (PRD 2.9).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, now, touch, by_created

# ----------------------------------------------------------------- constants
# PRD 3.1
HOST_TURNAROUND_BUFFER_MIN = 45
# PRD 3.3
LATENCY_TARGET_MS = 1500
LATENCY_STEP_MS = 50
FRAME_PENALTY_FACTOR = 400
SIMULCAST_DRIFT_TOLERANCE_MS = 800
DRIFT_STEP_MS = 100
GO_LIVE_MIN_INDEX = 70
CHANNEL_FAIL_INDEX = 40
# PRD 3.4
GO_LIVE_EARLY_MAX_MIN = 30
# PRD 3.6
TIER1_FLOOR_CENTS = 5000
TIER1_PCT = Decimal("0.05")
TIER2_FLOOR_CENTS = 15000
TIER2_PCT = Decimal("0.10")
TAX_RATE = Decimal("0.0875")
MAX_CART_DISTINCT_ITEMS = 3
# PRD 3.7
SHIPPING_FLAT_CENTS = 599
FREE_SHIP_THRESHOLD_CENTS = 7500
RECOVERY_WINDOW_MIN = 20
# PRD 3.8
MUTE_STRIKE_THRESHOLD = 2
MUTE_DURATION_MIN = 15
MAX_DEFERRALS = 2
# PRD 3.9
RETURN_PROVISION_PCT = Decimal("0.06")
DECAY_T1_HOURS = 24
DECAY_T2_HOURS = 48
DECAY_T3_HOURS = 72
W_CONVERSION = Decimal("0.5")
W_ENGAGEMENT = Decimal("0.3")
W_COMPLIANCE = Decimal("0.2")
ANSWER_POINTS = 10
VOTE_POINTS = 2
LATE_ACK_PENALTY = 25
UNSUBSTANTIATED_PENALTY = 50
REPLAY_ORDER_WEIGHT = Decimal("0.5")

PLATFORMS = ("FLAGSHIP_APP", "SOCIAL_A", "SOCIAL_B", "PARTNER_APP")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole unit (PRD 2.9)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ collection reads
def channels_of(show_id):
    return [c for c in db.channels.values() if c["show_id"] == show_id]


def bookings_of(show_id):
    return [b for b in db.bookings.values() if b["show_id"] == show_id]


def slots_of(show_id):
    return [s for s in db.slots.values() if s["show_id"] == show_id]


def disclosures_of(show_id):
    return [d for d in db.disclosures.values() if d["show_id"] == show_id]


def carts_of(show_id):
    return [c for c in db.carts.values() if c["show_id"] == show_id]


def orders_of(show_id):
    return [o for o in db.orders.values() if o["show_id"] == show_id]


def interactions_of(show_id):
    return [i for i in db.interactions.values() if i["show_id"] == show_id]


def items_of_cart(cart_id):
    return [i for i in db.cart_items.values() if i["cart_id"] == cart_id]


def items_of_offer(offer_id):
    return [i for i in db.cart_items.values() if i["flash_offer_id"] == offer_id]


def offers_of_slot(slot_id):
    return [o for o in db.offers.values() if o["lineup_slot_id"] == slot_id]


def offers_of_show(show_id):
    slot_ids = set(s["id"] for s in slots_of(show_id))
    return [o for o in db.offers.values() if o["lineup_slot_id"] in slot_ids]


def slot_of_offer(offer):
    return db.slots.get(offer["lineup_slot_id"])


def show_of_offer(offer):
    slot = slot_of_offer(offer)
    if slot is None:
        return None
    return db.shows.get(slot["show_id"])


def product_of_slot(slot):
    return db.products.get(slot["product_id"])


def product_of_item(item):
    slot = db.slots.get(item["lineup_slot_id"])
    if slot is None:
        return None
    return db.products.get(slot["product_id"])


def primary_booking(show_id, statuses):
    for booking in by_created(bookings_of(show_id)):
        if booking["role"] == "PRIMARY" and booking["status"] in statuses:
            return booking
    return None


def primary_host(show_id):
    """PRD 3.9: the host of the booking whose role is PRIMARY and whose status
    is CONFIRMED or COMPLETED; when no such booking exists commission is 0."""
    booking = primary_booking(show_id, ("CONFIRMED", "COMPLETED"))
    if booking is None:
        return None
    return db.hosts.get(booking["host_id"])


# ------------------------------------------------------- host certification
def certification_status(host):
    """PRD 3.1: derived on every read against the logical clock. A certification
    whose expiry lands exactly on the current instant is still CERTIFIED."""
    expiry = host.get("disclosure_certification_expires_at")
    if expiry is None:
        return "UNCERTIFIED"
    if expiry < now():
        return "EXPIRED"
    return "CERTIFIED"


# ------------------------------------ inventory_pool_reconciliation (PRD 2.10)
def product_pools(product):
    reserved = 0
    committed = 0
    for item in db.cart_items.values():
        candidate = product_of_item(item)
        if candidate is None or candidate["id"] != product["id"]:
            continue
        if item["state"] == "HELD":
            reserved += item["qty"]
        elif item["state"] == "COMMITTED":
            committed += item["qty"]
    available = product["on_hand_qty"] - reserved - committed
    return reserved, committed, available


def product_available(product):
    return product_pools(product)[2]


def offer_pools(offer):
    held = 0
    sold = 0
    for item in items_of_offer(offer["id"]):
        if item["state"] == "HELD":
            held += item["qty"]
        elif item["state"] == "COMMITTED":
            sold += item["qty"]
    remaining = offer["max_qty"] - held - sold
    return held, sold, remaining


def offer_remaining(offer):
    return offer_pools(offer)[2]


def sync_offer_allotment(offer):
    """PRD 3.5: ACTIVE -> EXHAUSTED when the recomputed remaining_qty reaches 0;
    EXHAUSTED -> ACTIVE when allotment returns while the window is still open and
    the show is still LIVE."""
    remaining = offer_remaining(offer)
    if offer["status"] == "ACTIVE" and remaining == 0:
        offer["status"] = "EXHAUSTED"
        touch(offer)
    elif offer["status"] == "EXHAUSTED" and remaining >= 1:
        show = show_of_offer(offer)
        if now() <= offer["window_end_at"] and show is not None and show["status"] == "LIVE":
            offer["status"] = "ACTIVE"
            touch(offer)


# --------------------------------------------- cart_bundle_tier (PRD 3.6 step 2)
def bundle_tier(pre_discount_subtotal_cents):
    """A subtotal of at least 150 dollars takes 0.10; otherwise at least
    50 dollars takes 0.05; otherwise 0.00. Both comparisons inclusive."""
    if pre_discount_subtotal_cents >= TIER2_FLOOR_CENTS:
        return TIER2_PCT
    if pre_discount_subtotal_cents >= TIER1_FLOOR_CENTS:
        return TIER1_PCT
    return Decimal("0.00")


def held_subtotal(cart_id):
    """PRD 3.6 step 1: sum of offer_unit_price_cents * qty over HELD lines only,
    from undiscounted offer prices."""
    total = 0
    for item in items_of_cart(cart_id):
        if item["state"] == "HELD":
            total += item["offer_unit_price_cents"] * item["qty"]
    return total


def lock_line_price(item, pct):
    """PRD 3.6 steps 3 and 4 — flash_offer_effective_unit_price."""
    effective = rhu(dec(item["offer_unit_price_cents"]) * (Decimal("1") - pct))
    item["effective_unit_price_cents"] = effective
    item["line_gross_cents"] = effective * item["qty"]
    item["line_tax_cents"] = rhu(dec(item["line_gross_cents"]) * TAX_RATE)


# ------------------------------------------- simulcast_readiness_index (PRD 3.3)
def recompute_channel_indices(show_id):
    """One health report recomputes readiness_index for every reported
    destination of the show, because the spread changes."""
    reported = [
        c for c in channels_of(show_id)
        if c["status"] in ("PROVISIONED", "LIVE") and c["latency_ms"] is not None
    ]
    if reported:
        latencies = [c["latency_ms"] for c in reported]
        spread = max(latencies) - min(latencies)
    else:
        spread = 0
    for channel in reported:
        latency_penalty = dec(channel["latency_ms"] - LATENCY_TARGET_MS) / dec(LATENCY_STEP_MS)
        if latency_penalty < 0:
            latency_penalty = Decimal("0")
        frame_penalty = dec(channel["dropped_frame_pct"]) * dec(FRAME_PENALTY_FACTOR)
        if channel["platform"] == "PARTNER_APP":
            drift_penalty = Decimal("0")
        else:
            drift_penalty = dec(spread - SIMULCAST_DRIFT_TOLERANCE_MS) / dec(DRIFT_STEP_MS)
            if drift_penalty < 0:
                drift_penalty = Decimal("0")
        # The three penalties are summed and the SUM is rounded half up once.
        index = 100 - rhu(latency_penalty + frame_penalty + drift_penalty)
        if index < 0:
            index = 0
        if index > 100:
            index = 100
        channel["readiness_index"] = index
    return reported


def recompute_show_index(show):
    """Show.simulcast_readiness_index is the minimum readiness_index across the
    show's destinations whose status is PROVISIONED or LIVE; 0 when empty."""
    active = [c for c in channels_of(show["id"]) if c["status"] in ("PROVISIONED", "LIVE")]
    if not active:
        show["simulcast_readiness_index"] = 0
    else:
        show["simulcast_readiness_index"] = min(c["readiness_index"] for c in active)
    return show["simulcast_readiness_index"]


# ------------------------------------------------------- show derived counters
def gross_merchandise_cents(show_id):
    """PRD 3.7: the sum of merchandise_cents across this show's orders whose
    payment_state is CAPTURED."""
    total = 0
    for order in orders_of(show_id):
        if order["payment_state"] == "CAPTURED":
            total += order["merchandise_cents"]
    return total


def abandoned_cart_count(show_id):
    """PRD 3.7: counts the show's carts whose status is ABANDONED or EXPIRED."""
    return len([c for c in carts_of(show_id) if c["status"] in ("ABANDONED", "EXPIRED")])


def abandonment_rate_bp(show_id):
    """PRD 3.7: 10,000 * abandoned_cart_count / carts ever opened, rounded half
    up; 0 when the show has no carts at all."""
    carts = carts_of(show_id)
    if not carts:
        return 0
    return rhu(dec(10000 * abandoned_cart_count(show_id)) / dec(len(carts)))


def pending_question_count(show_id):
    """PRD 3.8: the count of the show's QUESTION interactions in QUEUED, ROUTED
    or DEFERRED."""
    total = 0
    for item in interactions_of(show_id):
        if item["kind"] == "QUESTION" and item["state"] in ("QUEUED", "ROUTED", "DEFERRED"):
            total += 1
    return total


def replay_attributed_revenue_cents(show_id):
    return sum(s["replay_attributed_revenue_cents"] for s in slots_of(show_id))


# ----------------------------------------------- order_totals (PRD 3.7)
def order_totals(items):
    """merchandise, then per-line-rounded tax, then shipping, then total."""
    merchandise = sum(i["line_gross_cents"] for i in items)
    tax = 0
    for item in items:
        tax += rhu(dec(item["line_gross_cents"]) * TAX_RATE)
    if merchandise >= FREE_SHIP_THRESHOLD_CENTS:
        shipping = 0
    else:
        shipping = SHIPPING_FLAT_CENTS
    return merchandise, tax, shipping, merchandise + tax + shipping


# --------------------------------------- show_margin_analysis (PRD 3.9)
def margin_analysis(show, variant):
    host = primary_host(show["id"])
    pct = dec(host["commission_pct"]) if host is not None else Decimal("0")
    if variant == "FINAL":
        scope = [
            o for o in orders_of(show["id"])
            if o["payment_state"] == "CAPTURED" and o["fulfillment_state"] != "CANCELLED"
        ]
    else:
        scope = [
            o for o in orders_of(show["id"])
            if o["payment_state"] in ("AUTHORIZED", "CAPTURED")
            and o["fulfillment_state"] != "CANCELLED"
        ]
    merchandise = sum(o["merchandise_cents"] for o in scope)
    cart_ids = set(o["cart_id"] for o in scope)
    cogs = 0
    for item in db.cart_items.values():
        if item["state"] != "COMMITTED" or item["cart_id"] not in cart_ids:
            continue
        slot = db.slots.get(item["lineup_slot_id"])
        if slot is None:
            continue
        if variant == "FINAL":
            product = db.products.get(slot["product_id"])
            unit_cost = product["unit_cost_cents"] if product is not None else 0
        else:
            unit_cost = slot["unit_cost_snapshot_cents"]
        cogs += unit_cost * item["qty"]
    if variant == "FINAL":
        net_of_returns = rhu(dec(merchandise) * (Decimal("1") - RETURN_PROVISION_PCT))
        return_provision = merchandise - net_of_returns
        commission = rhu(dec(net_of_returns) * pct)
        margin = net_of_returns - cogs - commission
    else:
        return_provision = 0
        commission = rhu(dec(merchandise) * pct)
        margin = merchandise - cogs - commission
    return {
        "order_count": len(scope),
        "merchandise_revenue_cents": merchandise,
        "cogs_cents": cogs,
        "return_provision_cents": return_provision,
        "host_commission_cents": commission,
        "margin_cents": margin,
    }


def stamp_provisional_margin(show):
    """PRD 3.9: the provisional variant is recomputed and stamped on the
    end-of-broadcast transition and on every order capture and refund."""
    show["margin_provisional_cents"] = margin_analysis(show, "PROVISIONAL")["margin_cents"]


# ------------------------------------- host_effectiveness_score (PRD 3.9)
def host_scope_shows(host_id, show_id=None):
    show_ids = []
    for booking in db.bookings.values():
        if booking["host_id"] != host_id:
            continue
        if booking["role"] != "PRIMARY":
            continue
        if booking["status"] not in ("CONFIRMED", "COMPLETED"):
            continue
        if booking["show_id"] not in show_ids:
            show_ids.append(booking["show_id"])
    if show_id is not None:
        show_ids = [s for s in show_ids if s == show_id]
    return show_ids


def host_effectiveness(host, variant, show_id=None):
    scope = host_scope_shows(host["id"], show_id)
    live_orders = 0
    unique_carts = 0
    replay_conversions = 0
    answered = 0
    poll_votes = 0
    late_acks = 0
    unsubstantiated = 0
    for sid in scope:
        for order in orders_of(sid):
            if (order["payment_state"] in ("AUTHORIZED", "CAPTURED")
                    and order["fulfillment_state"] != "CANCELLED"):
                live_orders += 1
        unique_carts += len(carts_of(sid))
        for slot in slots_of(sid):
            replay_conversions += slot["replay_conversions_count"]
            product = db.products.get(slot["product_id"])
            if product is not None and product["claim_substantiation_status"] != "SUBSTANTIATED":
                unsubstantiated = 1
        for item in interactions_of(sid):
            if item["kind"] == "QUESTION" and item["state"] == "ANSWERED":
                answered += 1
            if item["kind"] == "POLL":
                poll_votes += item["vote_count"]
        for record in disclosures_of(sid):
            if record["acknowledged_late"]:
                late_acks += 1
    if variant == "ATTRIBUTED_72H":
        effective_orders = dec(live_orders) + dec(replay_conversions) * REPLAY_ORDER_WEIGHT
    else:
        effective_orders = dec(live_orders)
    denominator = unique_carts if unique_carts > 1 else 1
    conversion = rhu(effective_orders / dec(denominator) * dec(100))
    if conversion > 100:
        conversion = 100
    engagement = answered * ANSWER_POINTS + poll_votes * VOTE_POINTS
    if engagement > 100:
        engagement = 100
    compliance = 100 - late_acks * LATE_ACK_PENALTY - (UNSUBSTANTIATED_PENALTY if unsubstantiated else 0)
    if compliance < 0:
        compliance = 0
    score = rhu(dec(conversion) * W_CONVERSION + dec(engagement) * W_ENGAGEMENT
                + dec(compliance) * W_COMPLIANCE)
    return {
        "live_orders_count": live_orders,
        "replay_conversions_count": replay_conversions,
        "unique_cart_count": unique_carts,
        "answered_questions_count": answered,
        "poll_votes_count": poll_votes,
        "late_ack_count": late_acks,
        "conversion_component": conversion,
        "engagement_component": engagement,
        "compliance_component": compliance,
        "effectiveness_score": score,
    }


# --------------------------------- replay_attributed_revenue (PRD 3.9)
def decay_weight(ended_at, occurred_at):
    """Elapsed time truncated downwards to whole hours; boundaries inclusive."""
    elapsed = occurred_at - ended_at
    hours = int(elapsed.total_seconds() // 3600)
    if hours <= DECAY_T1_HOURS:
        return Decimal("1.0")
    if hours <= DECAY_T2_HOURS:
        return Decimal("0.6")
    if hours <= DECAY_T3_HOURS:
        return Decimal("0.3")
    return Decimal("0.0")


# --------------------------------------------------------------- cascades
def release_held_lines(offer, reason):
    """Release every cart line of this offer still in state HELD (PRD 3.4/3.5)."""
    released = []
    for item in items_of_offer(offer["id"]):
        if item["state"] != "HELD":
            continue
        item["state"] = "RELEASED"
        item["released_reason"] = reason
        item["released_at"] = now()
        touch(item)
        released.append(item)
    return released


def revert_show_to_draft(show):
    """PRD 3.4: READY -> DRAFT runs four links deep."""
    show["status"] = "DRAFT"
    show["readiness_checked_at"] = now()
    touch(show)
    for offer in by_created(offers_of_show(show["id"])):
        if offer["status"] != "SCHEDULED":
            continue
        offer["status"] = "CANCELLED"
        touch(offer)
        release_held_lines(offer, "OFFER_CANCELLED")


def end_show(show):
    """PRD 3.9: the end-of-broadcast cascade, four links deep."""
    stamp = now()
    show["status"] = "ENDED"
    show["ended_at"] = stamp
    touch(show)
    for channel in by_created(channels_of(show["id"])):
        if channel["status"] == "LIVE":
            channel["status"] = "ENDED"
            touch(channel)
    for booking in by_created(bookings_of(show["id"])):
        if booking["status"] == "CONFIRMED":
            booking["status"] = "COMPLETED"
            touch(booking)
    for offer in by_created(offers_of_show(show["id"])):
        if offer["status"] not in ("SCHEDULED", "ACTIVE", "EXHAUSTED"):
            continue
        had_holds = offer["status"] in ("ACTIVE", "EXHAUSTED")
        offer["status"] = "EXPIRED"
        touch(offer)
        if had_holds:
            release_held_lines(offer, "OFFER_EXPIRED")
    for cart in by_created(carts_of(show["id"])):
        if cart["status"] != "OPEN":
            continue
        lines = items_of_cart(cart["id"])
        if not lines:
            continue
        if any(line["state"] != "RELEASED" for line in lines):
            continue
        cart["status"] = "ABANDONED"
        cart["abandoned_at"] = stamp
        cart["recovery_deadline_at"] = stamp + timedelta(minutes=RECOVERY_WINDOW_MIN)
        touch(cart)
    stamp_provisional_margin(show)


def restock_offers_after_release(released_items):
    """PRD 3.5/3.7: an offer that was EXHAUSTED and now shows remaining_qty of at
    least 1 returns to ACTIVE while its window is open and the show is LIVE."""
    seen = []
    for item in released_items:
        offer = db.offers.get(item["flash_offer_id"])
        if offer is None or offer["id"] in seen:
            continue
        seen.append(offer["id"])
        sync_offer_allotment(offer)
