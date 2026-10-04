"""Calculation rules (scaffold Table 3, PRD sections 2.10 and 3) and the
relationship resolvers / derived-field computations that read the store."""
import bisect
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

import db

# required_kits constants
BASE_KITS = 3
SESSION_PACK_RATIO = Decimal('0.20')

# funding_floor constants
FUNDING_BASE_CENTS = 75000
FUNDING_PER_SESSION_CENTS = 25000

# recognition_tier constants
GOLD_HOURS = 40
GOLD_FUNDING_CENTS = 2000000
SILVER_HOURS = 25
SILVER_FUNDING_CENTS = 1000000
SILVER_HOURS_ONLY = 60
BRONZE_HOURS = 10
BRONZE_FUNDING_CENTS = 500000

# session_cadence constants
MIN_SESSION_GAP_DAYS = 3
MAX_SESSION_GAP_DAYS = 14

# facility_capacity constants
TOWN_CAPACITY = 60
PARK_CAPACITY = 90
TURNOVER_BUFFER_MINUTES = 30
FACILITY_CAPACITY = {'SIMULATED_TOWN': TOWN_CAPACITY, 'FINANCE_PARK': PARK_CAPACITY}

# Sessions counted as "scheduled" for reporting / projected tiers.
NON_TERMINAL_SESSION_STATUSES = ('TENTATIVE', 'SCHEDULED', 'NEEDS_SUBSTITUTE')


def session_hours(duration_minutes):
    """Per-session hours: duration/60 rounded half-up to 2 decimals, rounded
    per session BEFORE any summation (PRD 2.10)."""
    return (Decimal(duration_minutes) / Decimal(60)).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP)


def required_kits(enrolled_count, session_count):
    """ceil per session first, then multiply and sum; never sum-then-round."""
    per_session = int((Decimal(enrolled_count) * SESSION_PACK_RATIO)
                      .to_integral_value(rounding=ROUND_CEILING))
    return BASE_KITS + session_count * per_session


def funding_floor_cents(session_count):
    return FUNDING_BASE_CENTS + session_count * FUNDING_PER_SESSION_CENTS


def recognition_tier(sponsor_hours, funding_received_cents):
    """Tier ladder, strict precedence GOLD > SILVER > BRONZE > NONE."""
    if sponsor_hours >= GOLD_HOURS and funding_received_cents >= GOLD_FUNDING_CENTS:
        return 'GOLD'
    if ((sponsor_hours >= SILVER_HOURS and funding_received_cents >= SILVER_FUNDING_CENTS)
            or sponsor_hours >= SILVER_HOURS_ONLY):
        return 'SILVER'
    if ((sponsor_hours >= BRONZE_HOURS and funding_received_cents >= BRONZE_FUNDING_CENTS)
            or funding_received_cents >= GOLD_FUNDING_CENTS):
        return 'BRONZE'
    return 'NONE'


# --- relationship resolvers ----------------------------------------------
def sessions_of_delivery(delivery_id):
    return [s for s in db.STORES['sessions'].values() if s['delivery_id'] == delivery_id]


def students_of_delivery(delivery_id):
    return [s for s in db.STORES['students'].values() if s['delivery_id'] == delivery_id]


def capstones_of_delivery(delivery_id):
    return [c for c in db.STORES['capstones'].values() if c['delivery_id'] == delivery_id]


def deliveries_of_agreement(agreement_id):
    return [d for d in db.STORES['deliveries'].values() if d['agreement_id'] == agreement_id]


def agreement_of(delivery):
    return db.STORES['agreements'][delivery['agreement_id']]


def school_of_delivery(delivery):
    agreement = agreement_of(delivery)
    return db.STORES['schools'][agreement['school_id']]


def office_of_delivery(delivery):
    school = school_of_delivery(delivery)
    district = db.STORES['districts'][school['district_id']]
    return db.STORES['area_offices'][district['area_office_id']]


def inventory_for_delivery(delivery):
    """Kit stock row resolved via school -> district -> office plus the
    delivery's snapshotted program; None when no row exists (zero stock)."""
    office = office_of_delivery(delivery)
    for inv in db.STORES['inventories'].values():
        if (inv['area_office_id'] == office['id']
                and inv['program_catalog_id'] == delivery['program_catalog_id']):
            return inv
    return None


# --- derived fields --------------------------------------------------------
def is_eligible(volunteer):
    partner = db.STORES['partners'].get(volunteer['corporate_partner_id'])
    return (volunteer['screening_status'] == 'CLEARED'
            and volunteer['training_status'] == 'COMPLETED'
            and volunteer['engagement_status'] == 'ACTIVE'
            and partner is not None and partner['status'] == 'ACTIVE')


def volunteer_hours(volunteer_id):
    total = Decimal('0')
    for s in db.STORES['sessions'].values():
        if s['volunteer_id'] == volunteer_id and s['status'] == 'DELIVERED':
            total += session_hours(s['duration_minutes'])
    return total


def sponsor_hours_for(agreement, statuses):
    deliveries = deliveries_of_agreement(agreement['id'])
    delivery_ids = {d['id'] for d in deliveries}
    total = Decimal('0')
    for s in db.STORES['sessions'].values():
        if s['delivery_id'] not in delivery_ids or s['status'] not in statuses:
            continue
        v = db.STORES['volunteers'].get(s['volunteer_id'])
        if v is not None and v['corporate_partner_id'] == agreement['sponsor_partner_id']:
            total += session_hours(s['duration_minutes'])
    return total


def agreement_recognition_tier(agreement):
    """Persisted EARNED variant: sponsor hours over DELIVERED sessions only."""
    return recognition_tier(sponsor_hours_for(agreement, ('DELIVERED',)),
                            agreement['funding_received_cents'])


def sessions_blocked_count(delivery_id):
    return sum(1 for s in db.STORES['sessions'].values()
               if s['delivery_id'] == delivery_id and s['status'] == 'NEEDS_SUBSTITUTE')


def sessions_delivered_count(delivery_id):
    return sum(1 for s in db.STORES['sessions'].values()
               if s['delivery_id'] == delivery_id and s['status'] == 'DELIVERED')


def deliveries_completed_count(agreement_id):
    return sum(1 for d in deliveries_of_agreement(agreement_id) if d['status'] == 'COMPLETED')


# --- temporal checks -------------------------------------------------------
def overlap_exists(volunteer_id, date_value, start_minutes, end_minutes,
                   exclude_session_id=None):
    """Half-open overlap: clash iff cand.start < other.end AND other.start <
    cand.end; back-to-back is allowed. Only SCHEDULED sessions of the same
    volunteer on the same date participate."""
    for s in db.STORES['sessions'].values():
        if exclude_session_id is not None and s['id'] == exclude_session_id:
            continue
        if (s['volunteer_id'] != volunteer_id or s['status'] != 'SCHEDULED'
                or s['scheduled_date'] != date_value):
            continue
        if start_minutes < s['end_minutes'] and s['start_minutes'] < end_minutes:
            return True
    return False


def cadence_insert_ok(delivery_id, candidate_date, exclude_session_id=None):
    """Insert the candidate among the delivery's SCHEDULED sessions and check
    only the gaps to its immediate date neighbors (both bounds inclusive)."""
    dates = sorted(s['scheduled_date'] for s in db.STORES['sessions'].values()
                   if s['delivery_id'] == delivery_id and s['status'] == 'SCHEDULED'
                   and s['id'] != exclude_session_id)
    idx = bisect.bisect_left(dates, candidate_date)
    if idx > 0:
        gap = (candidate_date - dates[idx - 1]).days
        if gap < MIN_SESSION_GAP_DAYS or gap > MAX_SESSION_GAP_DAYS:
            return False
    if idx < len(dates):
        gap = (dates[idx] - candidate_date).days
        if gap < MIN_SESSION_GAP_DAYS or gap > MAX_SESSION_GAP_DAYS:
            return False
    return True


def cadence_full_ok(delivery_id):
    """Full adjacent-pair sweep over the delivery's SCHEDULED sessions, sorted
    by (scheduled_date, created_at)."""
    scheduled = [s for s in db.STORES['sessions'].values()
                 if s['delivery_id'] == delivery_id and s['status'] == 'SCHEDULED']
    scheduled.sort(key=lambda s: (s['scheduled_date'], s['created_at'], s['_seq']))
    for prev, nxt in zip(scheduled, scheduled[1:]):
        gap = (nxt['scheduled_date'] - prev['scheduled_date']).days
        if gap < MIN_SESSION_GAP_DAYS or gap > MAX_SESSION_GAP_DAYS:
            return False
    return True


def facility_capacity_ok(candidate):
    """Buffered half-open overlap with aggregate capacity; == capacity passes."""
    capacity = FACILITY_CAPACITY[candidate['facility']]
    total = db.STORES['deliveries'][candidate['delivery_id']]['enrolled_count']
    for other in db.STORES['capstones'].values():
        if other['id'] == candidate['id']:
            continue
        if (other['facility'] != candidate['facility']
                or other['event_date'] != candidate['event_date']):
            continue
        if other['status'] not in ('READY', 'ROLES_ASSIGNED', 'COMPLETED'):
            continue
        if (other['start_minutes'] < candidate['end_minutes'] + TURNOVER_BUFFER_MINUTES
                and candidate['start_minutes'] < other['end_minutes'] + TURNOVER_BUFFER_MINUTES):
            total += db.STORES['deliveries'][other['delivery_id']]['enrolled_count']
    return total <= capacity


def evaluation_report(agreement, variant):
    """Computed (never persisted) funder report; PROVISIONAL default / FINAL."""
    deliveries = deliveries_of_agreement(agreement['id'])
    delivery_ids = {d['id'] for d in deliveries}
    all_sessions = [s for s in db.STORES['sessions'].values()
                    if s['delivery_id'] in delivery_ids]
    all_students = [s for s in db.STORES['students'].values()
                    if s['delivery_id'] in delivery_ids]

    sessions_delivered = sum(1 for s in all_sessions if s['status'] == 'DELIVERED')
    sessions_scheduled = sum(1 for s in all_sessions
                             if s['status'] in NON_TERMINAL_SESSION_STATUSES)

    if variant == 'FINAL':
        pool_statuses = ('DELIVERED',)
        included_statuses = ('VALIDATED',)
    else:
        pool_statuses = ('DELIVERED', 'TENTATIVE', 'SCHEDULED', 'NEEDS_SUBSTITUTE')
        included_statuses = ('PRE_SUBMITTED', 'PAIRED', 'VALIDATED')

    total_hours = Decimal('0')
    sponsor_hours = Decimal('0')
    for s in all_sessions:
        if s['status'] not in pool_statuses:
            continue
        hours = session_hours(s['duration_minutes'])
        total_hours += hours
        v = db.STORES['volunteers'].get(s['volunteer_id'])
        if v is not None and v['corporate_partner_id'] == agreement['sponsor_partner_id']:
            sponsor_hours += hours

    included = [s for s in all_students if s['survey_status'] in included_statuses]
    paired = [s for s in included
              if s['pre_score'] is not None and s['post_score'] is not None]
    if paired:
        growth = sum(Decimal(s['post_score'] - s['pre_score']) for s in paired) \
            / Decimal(len(paired))
        avg_growth = float(growth.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
    else:
        avg_growth = None

    session_count_total = 0
    for d in deliveries:
        program = db.STORES['programs'].get(d['program_catalog_id'])
        if program is not None:
            session_count_total += program['session_count']
    if session_count_total > 0:
        rate = (Decimal(sessions_delivered * 100) / Decimal(session_count_total)) \
            .quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        completion = float(rate)
    else:
        completion = None

    earned = recognition_tier(sponsor_hours_for(agreement, ('DELIVERED',)),
                              agreement['funding_received_cents'])
    projected = recognition_tier(
        sponsor_hours_for(agreement, NON_TERMINAL_SESSION_STATUSES + ('DELIVERED',)),
        agreement['funding_received_cents'])

    return {
        'agreement_id': agreement['id'],
        'variant': variant,
        'sessions_delivered': sessions_delivered,
        'sessions_scheduled': sessions_scheduled,
        'total_volunteer_hours': float(total_hours),
        'sponsor_volunteer_hours': float(sponsor_hours),
        'students_included': len(included),
        'students_paired': len(paired),
        'avg_growth_score': avg_growth,
        'completion_rate_pct': completion,
        'recognition_tier_earned': earned,
        'recognition_tier_projected': projected,
        'generated_at': db.now_iso(),
    }
