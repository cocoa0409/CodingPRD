"""Calculation rules (scaffold section 1.3 / PRD 2.8, 2.11, 3.x). Money is
integer cents; round-half-up is applied exactly where the PRD pins it."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import store
from store import DB, mutate
from util import parse_d

# permit_fee_assessment constants
BASE_FEE = {'RESEARCH': 15000, 'PHOTOGRAPHY': 7500, 'COMMERCIAL_FILMING': 20000, 'GUIDED_ACTIVITY': 3000}
PER_DAY = {'RESEARCH': 2000, 'PHOTOGRAPHY': 1500, 'COMMERCIAL_FILMING': 5000, 'GUIDED_ACTIVITY': 800}
COMMERCIAL_SURCHARGE_CENTS = 10000
FEE_FLOOR_CENTS = 5000
FEE_CAP_CENTS = 100000
MAX_COMMERCIAL_PERMITS_PER_UNIT_DAY = 2

# compliance_point_deduction constants
SUSPEND_THRESHOLD_POINTS = 60
POINTS = {'MINOR': 10, 'MAJOR': 25, 'CRITICAL': 50}
INITIAL_COMPLIANCE_POINTS = 100

# cost_share_assessment
COOP_SHARE_PCT = 50

# bid_selection_ranking
RATING_WEIGHT = 1000

# habitat_priority_score
WEIGHTS = {'WATER_MANIPULATION': 30, 'PRESCRIBED_BURN': 50, 'INVASIVE_CONTROL': 20}
BREEDING_MULTIPLIER = 2

# seasonal safety
NESTING_BUFFER_DAYS = 14

PERMIT_USE_TYPES = ('RESEARCH', 'PHOTOGRAPHY', 'COMMERCIAL_FILMING', 'GUIDED_ACTIVITY')
DETERMINATION_USE_TYPES = PERMIT_USE_TYPES + ('GRAZING',)


def trip_days(p):
    """Inclusive day count: (end_date - start_date) + 1."""
    return (parse_d(p['end_date']) - parse_d(p['start_date'])).days + 1


def provisional_fee(use_type):
    """Provisional variant: flat base fee only; ignores crew, days, tier,
    surcharge, floor and cap."""
    return BASE_FEE[use_type]


def assessed_fee(use_type, crew_size, start_date, end_date):
    """Assessed variant: base + round_half_up(per_day * days * tier) + surcharge,
    then cap, then floor (cap first, floor second)."""
    days = (parse_d(end_date) - parse_d(start_date)).days + 1
    if crew_size <= 9:
        mult = Decimal('1.0')
    elif crew_size <= 19:
        mult = Decimal('1.25')
    else:
        mult = Decimal('1.5')
    product = (Decimal(PER_DAY[use_type]) * Decimal(days) * mult).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP)
    raw = BASE_FEE[use_type] + int(product) + (
        COMMERCIAL_SURCHARGE_CENTS if use_type == 'COMMERCIAL_FILMING' else 0)
    return max(min(raw, FEE_CAP_CENTS), FEE_FLOOR_CENTS)


def recompute_committed(unit_id):
    """committed_visitor_days: sum of crew_size * inclusive trip days over the
    unit's ACTIVE permits only."""
    unit = DB.units.get(unit_id)
    if unit is None:
        return
    total = sum(
        p['crew_size'] * trip_days(p)
        for p in DB.permits.values()
        if p['management_unit_id'] == unit_id and p['status'] == 'ACTIVE'
    )
    mutate(unit, committed_visitor_days=total)


def derive_posture(unit_id):
    """Scope-based snapshot: any ACTIVE FULL -> CLOSED; else any ACTIVE
    TRAILS_ONLY -> RESTRICTED; else OPEN. SCHEDULED/LIFTED never contribute."""
    active = [c for c in DB.closures.values()
              if c['management_unit_id'] == unit_id and c['status'] == 'ACTIVE']
    if any(c['scope'] == 'FULL' for c in active):
        return 'CLOSED'
    if any(c['scope'] == 'TRAILS_ONLY' for c in active):
        return 'RESTRICTED'
    return 'OPEN'


def recompute_posture(unit_id):
    unit = DB.units.get(unit_id)
    if unit is None:
        return
    mutate(unit, access_posture=derive_posture(unit_id))


def active_closure_count(unit_id):
    return sum(1 for c in DB.closures.values()
               if c['management_unit_id'] == unit_id and c['status'] == 'ACTIVE')


def full_closure_covers(unit_id, day):
    """Date-scoped gate: an ACTIVE FULL-scope closure whose inclusive window
    covers the given date."""
    for c in DB.closures.values():
        if (c['management_unit_id'] == unit_id and c['status'] == 'ACTIVE'
                and c['scope'] == 'FULL'
                and parse_d(c['start_date']) <= day <= parse_d(c['end_date'])):
            return True
    return False


def recompute_habitat(unit_id):
    """Habitat priority scores over the unit's COMPLETED treatments only.
    Breeding variant doubles the weight when [window_start, window_end]
    intersects Mar 1 - Jun 30 of window_start's year."""
    unit = DB.units.get(unit_id)
    if unit is None:
        return
    annual = 0
    breeding = 0
    for t in DB.treatments.values():
        if t['management_unit_id'] != unit_id or t['status'] != 'COMPLETED':
            continue
        w = WEIGHTS[t['treatment_type']]
        annual += w
        ws = parse_d(t['window_start'])
        we = parse_d(t['window_end'])
        bs = date(ws.year, 3, 1)
        be = date(ws.year, 6, 30)
        if ws <= be and bs <= we:
            w *= BREEDING_MULTIPLIER
        breeding += w
    mutate(unit, habitat_priority_breeding=breeding, habitat_priority_annual=annual)


def commercial_capacity_ok(unit_id, start_date, end_date):
    """Approving a COMMERCIAL_FILMING permit: no calendar day in [start, end]
    may already carry >= 2 COMMERCIAL_FILMING permits in {APPROVED, ACTIVE}
    on the same unit (locked adjudication: only commercial permits count)."""
    existing = [p for p in DB.permits.values()
                if p['management_unit_id'] == unit_id
                and p['use_type'] == 'COMMERCIAL_FILMING'
                and p['status'] in ('APPROVED', 'ACTIVE')]
    if not existing:
        return True
    spans = [(parse_d(p['start_date']), parse_d(p['end_date'])) for p in existing]
    day = parse_d(start_date)
    last = parse_d(end_date)
    while day <= last:
        count = sum(1 for s, e in spans if s <= day <= e)
        if count >= MAX_COMMERCIAL_PERMITS_PER_UNIT_DAY:
            return False
        day += timedelta(days=1)
    return True


def period_amount(aum_used, rate_cents_per_aum):
    """cost_share_assessment: round_half_up per period, then summed by caller.
    Pinned example: aum 3, rate 1001 -> round_half_up(1501.5) = 1502."""
    raw = Decimal(aum_used * rate_cents_per_aum * COOP_SHARE_PCT) / Decimal(100)
    return int(raw.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def grazing_determination():
    """The refuge's determination covering use_type GRAZING: the latest-created
    FINAL one governs; None when no GRAZING determination has reached FINAL."""
    finals = [d for d in DB.determinations.values()
              if d['use_type'] == 'GRAZING' and d['status'] == 'FINAL']
    if not finals:
        return None
    return max(finals, key=lambda d: d['_seq'])


def population_status(survey_count, target_count):
    """Integer comparison: AT_TARGET iff survey * 10 >= target * 7."""
    return 'AT_TARGET' if survey_count * 10 >= target_count * 7 else 'BELOW_TARGET'


def rank_score(bid):
    return bid['stewardship_rating'] * RATING_WEIGHT - bid['rate_cents_per_aum']
