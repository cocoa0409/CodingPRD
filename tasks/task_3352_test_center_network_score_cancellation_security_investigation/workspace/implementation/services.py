"""Business logic: calculations (PRD 2.8 / scaffold calculations table),
cascades, recomputes, and shared lookups. Every numeric constant below is a
literal from PRD.md."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import db
from db import touch

UTC = timezone.utc

# --- Calculation constants (PRD 3 / scaffold calculations.constants) ---
SECTION_WEIGHTS = [Decimal('1.2'), Decimal('0.8'), Decimal('1.0')]
EQUATE_FACTOR = Decimal('0.5')
PASS_THRESHOLD = 80
FACILITY_WEIGHT = 5
STAFFING_WEIGHT = 7
EQUIPMENT_WEIGHT = 3
UNANNOUNCED_MULTIPLIER = Decimal('1.5')
GAIN_THRESHOLD = 30
SIMILARITY_THRESHOLD = Decimal('0.85')
MIN_MATCHED_ITEMS = 20
SAME_FORM_FACTOR = Decimal('1.0')
DIFF_FORM_FACTOR = Decimal('0.5')
ADJACENT_FACTOR = Decimal('1.0')
NONADJACENT_FACTOR = Decimal('0.7')
TURNAROUND_BUFFER_MIN = 60
LATE_ARRIVAL_MIN = 15
RESPONSE_WINDOW_DAYS = 30

OPEN_CASE_STATUSES = ('OPENED', 'NOTIFIED', 'RESPONSE_RECEIVED', 'WINDOW_EXPIRED')


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def time_to_minutes(t):
    return int(t[0:2]) * 60 + int(t[3:5])


def session_start_dt(sess):
    d = datetime.strptime(sess['test_date'], '%Y-%m-%d').date()
    return datetime(d.year, d.month, d.day,
                    int(sess['start_time'][0:2]), int(sess['start_time'][3:5]),
                    tzinfo=UTC)


def session_end_dt(sess):
    d = datetime.strptime(sess['test_date'], '%Y-%m-%d').date()
    return datetime(d.year, d.month, d.day,
                    int(sess['end_time'][0:2]), int(sess['end_time'][3:5]),
                    tzinfo=UTC)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def find_score_record_for_registration(registration_id):
    for rec in db.score_records.values():
        if rec['registration_id'] == registration_id:
            return rec
    return None


def find_open_case_for_registration(registration_id):
    for c in db.review_cases.values():
        if c['registration_id'] == registration_id and c['status'] in OPEN_CASE_STATUSES:
            return c
    return None


# ---------------------------------------------------------------------------
# Recompute helpers (the caller decides whether to touch the parent)
# ---------------------------------------------------------------------------
def recompute_active_staff_count(center):
    center['active_staff_count'] = sum(
        1 for s in db.staff_members.values() if s['center_id'] == center['id'])


def recompute_session_counts(sess):
    confirmed = 0
    waitlisted = 0
    for r in db.registrations.values():
        if r['session_id'] != sess['id']:
            continue
        if r['booking_status'] == 'CONFIRMED':
            confirmed += 1
        elif r['booking_status'] == 'WAITLISTED':
            waitlisted += 1
    sess['confirmed_count'] = confirmed
    sess['waitlist_count'] = waitlisted


def recompute_released_report_count(rec):
    """PRD 3.7: at every moment exactly the number of this record's reports
    currently in RELEASED status. Returns True when the value changed."""
    n = sum(1 for rp in db.score_reports.values()
            if rp['score_record_id'] == rec['id'] and rp['status'] == 'RELEASED')
    changed = n != rec['released_report_count']
    rec['released_report_count'] = n
    return changed


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_compliance_score(audit_type, facility, staffing, equipment, high):
    """PRD 3.1 audit_compliance_score; returns (score, outcome)."""
    base = (FACILITY_WEIGHT * facility + STAFFING_WEIGHT * staffing
            + EQUIPMENT_WEIGHT * equipment)
    if audit_type == 'UNANNOUNCED':
        deduction = int((UNANNOUNCED_MULTIPLIER * base).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP))
    else:
        deduction = base
    score = max(0, 100 - deduction)
    outcome = 'FAILED' if (score < PASS_THRESHOLD or high >= 1) else 'PASSED'
    return score, outcome


def compute_provisional_scaled_score(section_raws):
    """PRD 3.5: round each weighted section half-up to an integer FIRST, then
    sum (sum-then-round is the pinned rejected variant)."""
    total = 0
    for raw, weight in zip(section_raws, SECTION_WEIGHTS):
        total += int((Decimal(raw) * weight).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    return total


def compute_session_mean_raw(raw_totals):
    """PRD 3.5 step 2: mean over ALL session records (including the record
    being scored), kept at exactly 2 decimals, round-half-up."""
    mean = Decimal(sum(raw_totals)) / Decimal(len(raw_totals))
    return mean.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def compute_equate_adjustment(raw_total, session_mean_raw):
    """PRD 3.5 step 3: floor(0.5 * (raw_total - mean) + 0.5); negative halves
    round toward zero."""
    value = EQUATE_FACTOR * (Decimal(raw_total) - session_mean_raw) + Decimal('0.5')
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def compute_similarity_index(matched, total_items, same_form, adjacent_seated):
    """PRD 3.5 response_similarity_index: 4 decimals, round-half-up."""
    form = SAME_FORM_FACTOR if same_form else DIFF_FORM_FACTOR
    adj = ADJACENT_FACTOR if adjacent_seated else NONADJACENT_FACTOR
    value = (Decimal(matched) / Decimal(total_items)) * form * adj
    return value.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Scheduling rules (PRD 3.2)
# ---------------------------------------------------------------------------
def session_overlaps_turnaround(center_id, test_date, room_label, start_min, end_min):
    """True when the candidate interval fails to leave a >= 60 minute gap to
    any existing non-CANCELLED session at the same (center, test_date, room)."""
    for s in db.sessions.values():
        if s['center_id'] != center_id or s['test_date'] != test_date:
            continue
        if s['room_label'] != room_label or s['status'] == 'CANCELLED':
            continue
        s2 = time_to_minutes(s['start_time'])
        e2 = time_to_minutes(s['end_time'])
        if not (end_min + TURNAROUND_BUFFER_MIN <= s2 or e2 + TURNAROUND_BUFFER_MIN <= start_min):
            return True
    return False


def proctor_has_overlap(staff_id, test_date, start_min, end_min):
    """True when the staff member already proctors a non-CANCELLED session on
    the same test_date whose half-open [start, end) strictly overlaps the
    candidate (touching intervals are allowed)."""
    for s in db.sessions.values():
        if s['test_date'] != test_date or s['status'] == 'CANCELLED':
            continue
        if staff_id not in s['proctor_staff_ids']:
            continue
        s2 = time_to_minutes(s['start_time'])
        e2 = time_to_minutes(s['end_time'])
        if start_min < e2 and s2 < end_min:
            return True
    return False


# ---------------------------------------------------------------------------
# Registration pools and waitlist (PRD 3.3)
# ---------------------------------------------------------------------------
def has_approved_accommodation(examinee_id):
    for a in db.accommodation_requests.values():
        if a['examinee_id'] == examinee_id and a['status'] == 'APPROVED':
            return True
    return False


def pool_size(sess, pool):
    if pool == 'ACCOMMODATION':
        return sess['reserved_accommodation_seats']
    return sess['effective_general_cap']


def pool_occupancy(session_id, pool):
    return sum(1 for r in db.registrations.values()
               if r['session_id'] == session_id and r['pool'] == pool
               and r['booking_status'] == 'CONFIRMED')


def waitlist_size(session_id, pool):
    return sum(1 for r in db.registrations.values()
               if r['session_id'] == session_id and r['pool'] == pool
               and r['booking_status'] == 'WAITLISTED')


def promote_waitlist(sess, pool):
    """waitlist_promotion_selection: promote the WAITLISTED registration in
    this (session, pool) with the smallest created_at, then renumber the rest
    1..n in created_at ascending order."""
    candidates = [r for r in db.registrations.values()
                  if r['session_id'] == sess['id'] and r['pool'] == pool
                  and r['booking_status'] == 'WAITLISTED']
    if not candidates:
        return
    candidates.sort(key=lambda r: r['created_at'])
    if pool_occupancy(sess['id'], pool) >= pool_size(sess, pool):
        return
    promoted = candidates[0]
    promoted['booking_status'] = 'CONFIRMED'
    promoted['waitlist_position'] = None
    touch(promoted)
    for position, r in enumerate(candidates[1:], start=1):
        r['waitlist_position'] = position
        touch(r)


# ---------------------------------------------------------------------------
# Audit outcome -> TestCenter authorization cascade (PRD 3.1)
# ---------------------------------------------------------------------------
def apply_audit_outcome(center, outcome):
    center['last_audit_outcome'] = outcome
    status = center['authorization_status']
    if outcome == 'PASSED':
        if status in ('APPLIED', 'SUSPENDED'):
            center['authorization_status'] = 'AUTHORIZED'
    else:  # FAILED
        if status == 'AUTHORIZED':
            center['authorization_status'] = 'SUSPENDED'
            # hop 1: cancel DRAFT/PUBLISHED sessions of this center
            for sess in db.sessions.values():
                if sess['center_id'] != center['id']:
                    continue
                if sess['status'] not in ('DRAFT', 'PUBLISHED'):
                    continue
                sess['status'] = 'CANCELLED'
                # hop 2: cancel their CONFIRMED/WAITLISTED registrations
                # (attendance untouched; no waitlist promotion on cascade)
                for reg in db.registrations.values():
                    if reg['session_id'] != sess['id']:
                        continue
                    if reg['booking_status'] in ('CONFIRMED', 'WAITLISTED'):
                        reg['booking_status'] = 'CANCELLED'
                        reg['waitlist_position'] = None
                        touch(reg)
                # hop 3: ledger sync; exactly one version bump per session
                recompute_session_counts(sess)
                touch(sess)
        # APPLIED + FAILED is a self-loop: only last_audit_outcome changes.
    touch(center)
