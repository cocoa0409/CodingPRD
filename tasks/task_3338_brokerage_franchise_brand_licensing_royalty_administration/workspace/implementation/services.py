"""Shared business logic: stamps, cascades, royalty assessment, fund math."""
from datetime import timedelta

import db
from errors import ApiError

# Agreement statuses that block a brand-market re-grant on activation.
BLOCKING_CONFLICT_STATUSES = {'ACTIVE', 'SUSPENDED', 'TERMINATED', 'DEIDENTIFYING'}
# Non-terminal agreement statuses (terminal: EXPIRED, CLOSED).
NON_TERMINAL_AGREEMENT_STATUSES = {'DRAFT', 'ACTIVE', 'SUSPENDED', 'TERMINATED', 'DEIDENTIFYING'}

DEIDENTIFY_CATEGORIES = [
    'SIGNAGE_REMOVAL', 'MARKETING_WITHDRAWAL', 'DATA_PURGE',
    'DOMAIN_RELEASE', 'DIRECTORY_REMOVAL',
]

REBATE_PCT = 50
BPS_DENOMINATOR = 10000
CURE_WINDOW_DAYS = 30
DEIDENTIFY_WINDOW_DAYS = 60


def get_or_404(store, entity_id, label='resource'):
    e = store.get(entity_id)
    if e is None:
        raise ApiError('ERR_NOT_FOUND', 404, f'{label} not found: {entity_id}')
    return e


def stamp_new(e):
    """System fields for versioned entities: version starts at 1."""
    e['_seq'] = db.next_seq()
    now = db.wall_now_iso()
    e['created_at'] = now
    e['updated_at'] = now
    e['version'] = 1


def stamp_append(e):
    """System fields for append-only entities (no updated_at / version)."""
    e['_seq'] = db.next_seq()
    e['created_at'] = db.wall_now_iso()


def touch(e):
    """Every mutation refreshes updated_at and bumps version by exactly 1."""
    e['updated_at'] = db.wall_now_iso()
    e['version'] += 1


# --- DefaultCase / agreement interplay ---------------------------------------

def create_default_case(agreement_id, reason_code):
    now = db.logical_now()
    case = {
        'id': db.new_id(),
        'agreement_id': agreement_id,
        'reason_code': reason_code,
        'status': 'OPEN',
        'opened_at': db.iso_ms(now),
        'cure_deadline': db.iso_ms(now + timedelta(days=CURE_WINDOW_DAYS)),
        'escalated_at': None,
    }
    stamp_new(case)
    db.DEFAULTS[case['id']] = case
    return case


def recompute_open_cure_count(agreement):
    count = sum(1 for c in db.DEFAULTS.values()
                if c['agreement_id'] == agreement['id']
                and c['status'] in ('OPEN', 'CURING'))
    if agreement['open_cure_count'] != count:
        agreement['open_cure_count'] = count
        touch(agreement)


def maybe_resume_agreement(agreement):
    """System SUSPENDED -> ACTIVE hop when the last open default resolves."""
    if agreement['status'] == 'SUSPENDED' and agreement['open_cure_count'] == 0:
        agreement['status'] = 'ACTIVE'
        touch(agreement)


def maybe_terminate_brokerage(agreement):
    """Brokerage FRANCHISED -> TERMINATED once no non-terminal agreement remains."""
    brokerage = db.BROKERAGES.get(agreement['brokerage_id'])
    if brokerage is None or brokerage['status'] != 'FRANCHISED':
        return
    remaining = any(
        a['brokerage_id'] == brokerage['id']
        and a['status'] in NON_TERMINAL_AGREEMENT_STATUSES
        for a in db.AGREEMENTS.values())
    if remaining:
        return
    brokerage['status'] = 'TERMINATED'
    touch(brokerage)
    # Cascade: every still-ACTIVE agent of the brokerage flips to INACTIVE.
    for agent in db.AGENTS.values():
        if agent['brokerage_id'] == brokerage['id'] and agent['status'] == 'ACTIVE':
            agent['status'] = 'INACTIVE'
            touch(agent)


def close_agreement_if_ready(agreement):
    """System DEIDENTIFYING -> CLOSED once all tasks VERIFIED and no live defaults."""
    if agreement['status'] != 'DEIDENTIFYING':
        return
    tasks = [t for t in db.TASKS.values() if t['agreement_id'] == agreement['id']]
    if not tasks or any(t['status'] != 'VERIFIED' for t in tasks):
        return
    live_default = any(
        c['agreement_id'] == agreement['id']
        and c['status'] in ('OPEN', 'CURING', 'ESCALATED')
        for c in db.DEFAULTS.values())
    if live_default:
        return
    agreement['status'] = 'CLOSED'
    touch(agreement)
    maybe_terminate_brokerage(agreement)


def spawn_deidentification_tasks(agreement):
    """One PENDING task per category, due_at = termination timestamp + 60 days."""
    now = db.logical_now()
    for category in DEIDENTIFY_CATEGORIES:
        task = {
            'id': db.new_id(),
            'agreement_id': agreement['id'],
            'category': category,
            'status': 'PENDING',
            'due_at': db.iso_ms(now + timedelta(days=DEIDENTIFY_WINDOW_DAYS)),
        }
        stamp_new(task)
        db.TASKS[task['id']] = task


# --- money --------------------------------------------------------------------

def assess_royalty(agreement, period_month, gci_report):
    """Five-step royalty pipeline + ad-fund accrual; creates the RoyaltyPeriod."""
    G = gci_report['gci_cents']
    B = agreement['base_royalty_rate_bps']
    V = agreement['volume_incentive_rate_bps']
    T = agreement['volume_incentive_threshold_cents']
    C = agreement['annual_royalty_cap_cents']

    # Calendar-year reset of both cumulative counters before the formula runs.
    priors = [p for p in db.PERIODS.values() if p['agreement_id'] == agreement['id']]
    if priors:
        latest_year = max(p['period_month'] for p in priors)[:4]
        reset = latest_year != period_month[:4]
    else:
        reset = agreement['_term_start_dt'].strftime('%Y') != period_month[:4]
    if reset:
        Y, R = 0, 0
    else:
        Y = agreement['cumulative_gci_cents']
        R = agreement['cumulative_billed_royalty_cents']

    # Step 1-2: tier split on annual cumulative GCI; floor per leg, then sum.
    pre_gci = Y
    post_gci = Y + G
    low_part = max(0, min(post_gci, T) - min(pre_gci, T))
    high_part = G - low_part
    raw_royalty = (low_part * B) // BPS_DENOMINATOR + (high_part * V) // BPS_DENOMINATOR
    # Step 3: annual cap (headroom floored at zero).
    billed = min(raw_royalty, max(0, C - R))
    # Step 4: volume-incentive rebate, evaluated strictly after the cap.
    rebate = 0
    if post_gci > T:
        rebate = (high_part * (B - V) * REBATE_PCT) // (100 * BPS_DENOMINATOR)
    royalty_due = max(0, billed - rebate)
    provisional = raw_royalty  # provisional variant: skip cap and rebate

    # Ad-fund accrual: one floor at accrual; zero and no entry when SUSPENDED.
    if agreement['status'] == 'SUSPENDED':
        ad_due = 0
    else:
        ad_due = (G * agreement['ad_fund_rate_bps']) // BPS_DENOMINATOR

    period = {
        'id': db.new_id(),
        'agreement_id': agreement['id'],
        'period_month': period_month,
        'gci_cents': G,
        'royalty_due_cents': royalty_due,
        'provisional_royalty_cents': provisional,
        'ad_fund_due_cents': ad_due,
        'status': 'ASSESSED',
        'settled_at': None,
    }
    stamp_new(period)
    db.PERIODS[period['id']] = period

    # Step 5: advance running totals (billed from step 3, GCI after this month).
    agreement['cumulative_billed_royalty_cents'] = R + billed
    agreement['cumulative_gci_cents'] = post_gci
    touch(agreement)

    if ad_due > 0:
        entry = {
            'id': db.new_id(),
            'brand_id': agreement['brand_id'],
            'agreement_id': agreement['id'],
            'period_id': period['id'],
            'entry_type': 'COLLECT',
            'amount_cents': ad_due,
        }
        stamp_append(entry)
        db.LEDGER.append(entry)
    return period


def fund_balance(brand_id):
    bal = 0
    for e in db.LEDGER:
        if e['brand_id'] != brand_id:
            continue
        if e['entry_type'] == 'COLLECT':
            bal += e['amount_cents']
        elif e['entry_type'] == 'SPEND':
            bal -= e['amount_cents']
    return bal


def council_eligible(brokerage_id, brand_id, exclude_council_id=None):
    has_live_agreement = any(
        a['brokerage_id'] == brokerage_id and a['brand_id'] == brand_id
        and a['status'] in ('ACTIVE', 'SUSPENDED')
        for a in db.AGREEMENTS.values())
    if not has_live_agreement:
        return False
    for c in db.COUNCILS.values():
        if (c['brand_id'] == brand_id and c['id'] != exclude_council_id
                and brokerage_id in c['member_brokerage_ids']):
            return False
    return True
