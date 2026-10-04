"""Clock advance engine and cross-aggregate cascades (PRD 2.5, 2.10).
The five auto-transition classes fire in the pinned order:
1 determinations, 2 treatments, 3 volunteers (+cascades), 4 programs
(+cascades), 5 permits. Volunteers before programs is contractual."""
from datetime import timedelta
import store
from store import DB, mutate
from util import parse_d
from calc import recompute_posture, recompute_committed


def set_clock(dt):
    DB.clock = dt
    today = dt.date()

    # (1) determinations: PUBLIC_COMMENT past comment_close_date -> ADJUDICATION
    for d in list(DB.determinations.values()):
        if d['status'] == 'PUBLIC_COMMENT' and parse_d(d['comment_close_date']) < today:
            mutate(d, status='ADJUDICATION')

    # (2) treatments: window transitions
    for t in list(DB.treatments.values()):
        ws = parse_d(t['window_start'])
        we = parse_d(t['window_end'])
        if t['status'] == 'SCHEDULED':
            if ws <= today <= we:
                mutate(t, status='WINDOW_OPEN')
            elif today > we:
                mutate(t, status='EXPIRED')
        elif t['status'] == 'WINDOW_OPEN':
            if today > we:
                mutate(t, status='EXPIRED')

    # (3) volunteers: CLEARED at/past cleared_on + 365 days -> EXPIRED (+cascade)
    for v in list(DB.volunteers.values()):
        if v['background_status'] == 'CLEARED' and v['cleared_on'] is not None:
            expiry = parse_d(v['cleared_on']) + timedelta(days=365)
            if today >= expiry:
                expire_volunteer(v)

    # (4) programs: SCHEDULED past program_date -> COMPLETED (+cascade)
    for p in list(DB.programs.values()):
        if p['status'] == 'SCHEDULED' and parse_d(p['program_date']) < today:
            mutate(p, status='COMPLETED')
            for a in list(DB.assignments.values()):
                if a['program_id'] == p['id'] and a['status'] == 'ACTIVE':
                    mutate(a, status='COMPLETED')

    # (5) permits: ACTIVE past end_date -> COMPLETED (release visitor days)
    for pm in list(DB.permits.values()):
        if pm['status'] == 'ACTIVE' and parse_d(pm['end_date']) < today:
            mutate(pm, status='COMPLETED')
            recompute_committed(pm['management_unit_id'])


def cancel_program(p):
    """Program cancellation cascade: every still-ACTIVE assignment -> RELEASED."""
    mutate(p, status='CANCELLED')
    for a in list(DB.assignments.values()):
        if a['program_id'] == p['id'] and a['status'] == 'ACTIVE':
            mutate(a, status='RELEASED')


def expire_volunteer(v):
    """Volunteer expiry cascade: release the volunteer's ACTIVE assignments,
    then cancel any SCHEDULED program left below min_volunteers (whose own
    cascade releases its remaining ACTIVE assignments)."""
    mutate(v, background_status='EXPIRED')
    affected = []
    for a in list(DB.assignments.values()):
        if a['volunteer_id'] == v['id'] and a['status'] == 'ACTIVE':
            mutate(a, status='RELEASED')
            affected.append(a['program_id'])
    for pid in dict.fromkeys(affected):
        p = DB.programs.get(pid)
        if p is not None and p['status'] == 'SCHEDULED':
            active = sum(1 for a in DB.assignments.values()
                         if a['program_id'] == pid and a['status'] == 'ACTIVE')
            if active < p['min_volunteers']:
                cancel_program(p)


def activate_closure(c):
    """Closure activation cascade (PRD 2.10): posture recompute; program
    cancellation (+assignment release) regardless of scope; permit suspension
    only for scope FULL. Each suspension recomputes committed_visitor_days."""
    mutate(c, status='ACTIVE')
    unit_id = c['management_unit_id']
    recompute_posture(unit_id)
    cs = parse_d(c['start_date'])
    ce = parse_d(c['end_date'])
    for p in list(DB.programs.values()):
        if p['management_unit_id'] == unit_id and p['status'] == 'SCHEDULED':
            pd = parse_d(p['program_date'])
            if cs <= pd <= ce:
                cancel_program(p)
    if c['scope'] == 'FULL':
        for pm in list(DB.permits.values()):
            if pm['management_unit_id'] == unit_id and pm['status'] == 'ACTIVE':
                ps = parse_d(pm['start_date'])
                pe = parse_d(pm['end_date'])
                if ps <= ce and cs <= pe:
                    mutate(pm, status='SUSPENDED', suspended_by_closure_id=c['id'])
                    recompute_committed(unit_id)


def lift_closure(c):
    """Closure lift: posture recompute; permits pinned to this closure reinstate
    when end_date >= clock date (re-adding visitor days), else expire.
    Cancelled programs are never restored (cancellation is permanent)."""
    mutate(c, status='LIFTED')
    unit_id = c['management_unit_id']
    recompute_posture(unit_id)
    today = store.clock_date()
    for pm in list(DB.permits.values()):
        if pm.get('suspended_by_closure_id') == c['id'] and pm['status'] == 'SUSPENDED':
            if parse_d(pm['end_date']) >= today:
                mutate(pm, status='ACTIVE', suspended_by_closure_id=None)
            else:
                mutate(pm, status='EXPIRED', suspended_by_closure_id=None)
            recompute_committed(unit_id)


def close_and_select(offering):
    """bid_selection_ranking: eligible = SUBMITTED bids at/above the stewardship
    floor; winner = max rank_score, ties broken by earliest created_at. Empty
    eligible pool -> offering EXPIRED, all SUBMITTED bids REJECTED."""
    submitted = [b for b in DB.bids.values()
                 if b['offering_id'] == offering['id'] and b['status'] == 'SUBMITTED']
    eligible = [b for b in submitted
                if b['stewardship_rating'] >= offering['min_stewardship_rating']]
    if not eligible:
        for b in submitted:
            mutate(b, status='REJECTED')
        mutate(offering, status='EXPIRED')
        return None
    from calc import rank_score
    winner = max(eligible, key=lambda b: (rank_score(b), -b['_seq']))
    for b in submitted:
        mutate(b, status='WINNING' if b['id'] == winner['id'] else 'REJECTED')
    mutate(offering, status='AWARDED')
    from calc import INITIAL_COMPLIANCE_POINTS
    agreement = store.new_record({
        'management_unit_id': offering['management_unit_id'],
        'winning_bid_id': winner['id'],
        'cooperator_ref': winner['cooperator_ref'],
        'aum_cap': offering['aum_cap'],
        'grazing_window_start': offering['grazing_window_start'],
        'grazing_window_end': offering['grazing_window_end'],
        'compliance_points': INITIAL_COMPLIANCE_POINTS,
        'assessed_total_cents': 0,
        'paid_total_cents': 0,
        'refunded_total_cents': 0,
        'outstanding_balance_cents': 0,
        'status': 'ACTIVE',
    })
    DB.agreements[agreement['id']] = agreement
    return agreement
