"""Business calculations (PRD 3.5-3.9) and cross-entity cascades.

All constants are copied verbatim from the SCAFFOLD calculations table.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from helpers import wall_ts

# ---------------------------------------------------------------- constants
# rebate_amount tiers (inclusive lower bounds)
TIER1_THRESHOLD_CENTS = 100000
TIER1_RATE = Decimal('0.01')
TIER2_THRESHOLD_CENTS = 500000
TIER2_RATE = Decimal('0.02')
TIER3_THRESHOLD_CENTS = 1000000
TIER3_RATE = Decimal('0.03')
TIER4_THRESHOLD_CENTS = 2000000
TIER4_RATE = Decimal('0.04')
BASE_RATE_FLOOR = Decimal('0.005')
PL_SHARE_BONUS_THRESHOLD = Decimal('0.30')
PL_SHARE_BONUS_RATE = Decimal('0.005')
COMPLIANT_MULTIPLIER = Decimal('1.0')
NONCOMPLIANT_MULTIPLIER = Decimal('0.5')

# rolling_agreement_fill_rate
WINDOW_DAYS = 90
# order_fill_rate
SCALE_PERCENT = 100
EMPTY_DENOMINATOR_FILL = 100.00


def touch(entity):
    """Every mutation bumps version by exactly 1 and refreshes updated_at."""
    entity['version'] += 1
    entity['updated_at'] = wall_ts()


def round_pct(numerator, denominator):
    """100 * num / den, 2 decimal places, round half up; returns float."""
    val = (Decimal(numerator) * SCALE_PERCENT / Decimal(denominator)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(val)


def round_cents(dec_val):
    return int(dec_val.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


# --------------------------------------------------------- agreement expiry
def maybe_expire(agr):
    """Lazy EXPIRED transition (PRD 3.6): applied on any read or write of an
    agreement while the logical clock's date is past end_date (end_date is
    inclusive, so expiry starts the day after)."""
    if agr['status'] in ('ACTIVE', 'SUSPENDED'):
        if db.get_clock().date() > date.fromisoformat(agr['end_date']):
            agr['status'] = 'EXPIRED'
            touch(agr)
            return True
    return False


def facility_agreement(facility_id):
    """The facility's non-EXPIRED agreement, if any (lazy expiry applied)."""
    found = None
    for agr in db.STORES['agreements'].values():
        if agr['facility_id'] != facility_id:
            continue
        maybe_expire(agr)
        if agr['status'] != 'EXPIRED':
            found = agr
    return found


# ------------------------------------------------------------- order pricing
def compute_order_total(lines, agreement):
    """order_price: per-line case-ceiling rounding, then plain sum (pinned)."""
    total = 0
    for ln in lines:
        p = db.STORES['products'][ln['product_id']]
        if p['lum_eligible'] and agreement['lum_commitment']:
            billable = ln['ordered_qty']
        else:
            upc = p['units_per_case']
            billable = -(-ln['ordered_qty'] // upc) * upc
        total += billable * p['each_price_cents']
    return total


# --------------------------------------------------------------- fill rates
def _line_cancelled_units(ln):
    return (ln['ordered_qty'] - ln['shipped_qty']) if ln['backorder_cancelled'] else 0


def _order_units(order):
    shipped = sum(ln['shipped_qty'] for ln in order['lines'])
    ordered = sum(ln['ordered_qty'] for ln in order['lines'])
    cancelled = sum(_line_cancelled_units(ln) for ln in order['lines'])
    return shipped, ordered, cancelled


def provisional_fill(order):
    shipped, ordered, _ = _order_units(order)
    if ordered == 0:
        return EMPTY_DENOMINATOR_FILL
    return round_pct(shipped, ordered)


def final_fill(order):
    shipped, ordered, cancelled = _order_units(order)
    denom = ordered - cancelled
    if denom == 0:
        return EMPTY_DENOMINATOR_FILL
    return round_pct(shipped, denom)


def rolling_fill(agreement_id):
    """Unit-weighted aggregate over RECEIVED orders whose received_at lies in
    the trailing 90-day window [clock-90d, clock], both ends inclusive."""
    now = db.get_clock()
    window_start = now - timedelta(days=WINDOW_DAYS)
    shipped = 0
    wanted = 0
    eligible = 0
    for o in db.STORES['orders'].values():
        if o['agreement_id'] != agreement_id or o['status'] != 'RECEIVED':
            continue
        received_at = o.get('received_at')
        if received_at is None:
            continue
        received_dt = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
        if not (window_start <= received_dt <= now):
            continue
        eligible += 1
        s, ordered, cancelled = _order_units(o)
        shipped += s
        wanted += ordered - cancelled
    if eligible == 0:
        return None
    if wanted == 0:
        return EMPTY_DENOMINATOR_FILL
    return round_pct(shipped, wanted)


def cascade_after_receipt(order):
    """PRD 3.6: lazy expiry first; then spend accrual + rolling recompute
    (+1 version); then breach/recovery auto-transition (+1 version) with the
    inventory-program auto_replenish_enabled cascade."""
    agr = db.STORES['agreements'][order['agreement_id']]
    if maybe_expire(agr):
        return
    agr['spent_cents'] += order['total_price_cents']
    agr['rolling_fill_rate_pct'] = rolling_fill(agr['id'])
    touch(agr)
    rate = agr['rolling_fill_rate_pct']
    if rate is None:
        return
    committed = Decimal(str(agr['committed_fill_rate_pct']))
    current = Decimal(str(rate))
    if agr['status'] == 'ACTIVE' and current < committed:
        agr['status'] = 'SUSPENDED'
        touch(agr)
        for prog in db.STORES['inventory'].values():
            if prog['facility_id'] == agr['facility_id']:
                prog['auto_replenish_enabled'] = False
                touch(prog)
    elif agr['status'] == 'SUSPENDED' and current >= committed:
        agr['status'] = 'ACTIVE'
        touch(agr)
        for prog in db.STORES['inventory'].values():
            if prog['facility_id'] == agr['facility_id']:
                prog['auto_replenish_enabled'] = True
                touch(prog)


# ------------------------------------------------------------------- rebate
def base_tier_rate(eligible_purchase_cents):
    e = int(eligible_purchase_cents)
    if e >= TIER4_THRESHOLD_CENTS:
        return TIER4_RATE
    if e >= TIER3_THRESHOLD_CENTS:
        return TIER3_RATE
    if e >= TIER2_THRESHOLD_CENTS:
        return TIER2_RATE
    if e >= TIER1_THRESHOLD_CENTS:
        return TIER1_RATE
    return BASE_RATE_FLOOR


def provisional_rebate(claim):
    """At creation: base tier rate x eligible volume, no bonus, no multiplier."""
    return round_cents(Decimal(claim['eligible_purchase_cents']) * base_tier_rate(claim['eligible_purchase_cents']))


def validated_rebate(claim):
    """SUBMIT/RESUBMIT: pinned order — (volume x (tier + bonus)) rounded to
    whole cents first, then x compliance multiplier, rounded again."""
    rate = base_tier_rate(claim['eligible_purchase_cents'])
    if Decimal(str(claim['private_label_share'])) >= PL_SHARE_BONUS_THRESHOLD:
        rate += PL_SHARE_BONUS_RATE
    multiplier = COMPLIANT_MULTIPLIER if claim['compliant'] else NONCOMPLIANT_MULTIPLIER
    step1 = round_cents(Decimal(claim['eligible_purchase_cents']) * rate)
    return round_cents(Decimal(step1) * multiplier)


# ---------------------------------------------------------- reorder suggestion
def open_pipeline_qty(facility_id, product_id):
    """Sum of (ordered_qty - shipped_qty) for the product across the facility's
    non-EXPIRED agreement's orders in PLACED or PARTIALLY_SHIPPED status."""
    agr = facility_agreement(facility_id)
    if agr is None:
        return 0
    total = 0
    for o in db.STORES['orders'].values():
        if o['agreement_id'] != agr['id'] or o['status'] not in ('PLACED', 'PARTIALLY_SHIPPED'):
            continue
        for ln in o['lines']:
            if ln['product_id'] == product_id:
                total += ln['ordered_qty'] - ln['shipped_qty']
    return total


def recompute_position(program, pos):
    """reorder_suggestion: pinned 4-step evaluation (PRD 3.9)."""
    p = db.STORES['products'][pos['product_id']]
    raw_need = pos['par_level'] - pos['on_hand']
    if not program['auto_replenish_enabled']:
        pos['suggested_order_qty'] = 0
    else:
        need = max(0, raw_need - open_pipeline_qty(program['facility_id'], pos['product_id']))
        if need > 0:
            om = p['order_multiple']
            pos['suggested_order_qty'] = -(-need // om) * om
        else:
            pos['suggested_order_qty'] = 0
    if pos['on_hand'] == 0:
        pos['reorder_status'] = 'CRITICAL'
    elif pos['on_hand'] <= pos['reorder_point']:
        pos['reorder_status'] = 'DUE'
    else:
        pos['reorder_status'] = 'OK'


def recompute_program_positions(program):
    for pos in program['positions']:
        recompute_position(program, pos)
