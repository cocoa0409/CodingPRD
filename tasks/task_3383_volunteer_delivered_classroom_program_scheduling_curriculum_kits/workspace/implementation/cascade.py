"""Cascading side effects and the clock-driven scheduled sweeps.

Every cascade-mutated resource gets its own touch (updated_at + version bump)
per PRD 2.5. A delivery whose sessions_blocked_count changes because of a
cascade gets its version bumped exactly once per cascade wave.
"""
from datetime import timedelta

import calc
import db
from db import touch


def mark_volunteer_ineligible(volunteer):
    """Shared cascade for screening EXPIRED / training EXPIRED / DEPARTED:
    the volunteer's SCHEDULED sessions become NEEDS_SUBSTITUTE and each
    affected delivery recomputes sessions_blocked_count (version bump)."""
    touched_delivery_ids = set()
    for s in db.STORES['sessions'].values():
        if s['volunteer_id'] == volunteer['id'] and s['status'] == 'SCHEDULED':
            s['status'] = 'NEEDS_SUBSTITUTE'
            touch(s)
            touched_delivery_ids.add(s['delivery_id'])
    for delivery_id in touched_delivery_ids:
        delivery = db.STORES['deliveries'].get(delivery_id)
        if delivery is not None:
            touch(delivery)


def cancel_capstone(capstone):
    """Capstone CANCEL: students' capstone fields cleared, count reset."""
    for st in db.STORES['students'].values():
        if st['capstone_event_id'] == capstone['id']:
            st['capstone_event_id'] = None
            st['rotation_group'] = None
            st['capstone_role'] = None
            touch(st)
    capstone['assigned_student_count'] = 0
    capstone['status'] = 'CANCELLED'
    touch(capstone)


def _release_kits(delivery):
    """RESERVED/DISTRIBUTED -> RELEASED; full return to available, none
    recorded as consumed."""
    inv = calc.inventory_for_delivery(delivery)
    if inv is not None:
        if delivery['kit_status'] == 'RESERVED':
            inv['reserved_count'] -= delivery['required_kits']
            inv['available_count'] += delivery['required_kits']
            touch(inv)
        elif delivery['kit_status'] == 'DISTRIBUTED':
            inv['distributed_count'] -= delivery['required_kits']
            inv['available_count'] += delivery['required_kits']
            touch(inv)
    delivery['kit_status'] = 'RELEASED'


def cancel_delivery(delivery):
    """Delivery CANCEL cascade: sessions cancelled, kits released, live
    capstone cancelled."""
    for s in db.STORES['sessions'].values():
        if (s['delivery_id'] == delivery['id']
                and s['status'] in ('TENTATIVE', 'SCHEDULED', 'NEEDS_SUBSTITUTE', 'NO_SHOW')):
            s['status'] = 'CANCELLED'
            touch(s)
    if delivery['kit_status'] in ('RESERVED', 'DISTRIBUTED'):
        _release_kits(delivery)
    for c in db.STORES['capstones'].values():
        if (c['delivery_id'] == delivery['id']
                and c['status'] in ('PLANNED', 'READY', 'ROLES_ASSIGNED')):
            cancel_capstone(c)
    delivery['status'] = 'CANCELLED'
    touch(delivery)


def terminate_agreement(agreement):
    """Agreement TERMINATE: every live delivery runs the CANCEL cascade."""
    for d in db.STORES['deliveries'].values():
        if (d['agreement_id'] == agreement['id']
                and d['status'] in ('DRAFT', 'PLANNED', 'SCHEDULED', 'IN_PROGRESS')):
            cancel_delivery(d)
    agreement['status'] = 'TERMINATED'
    touch(agreement)


def churn_district(district):
    """District CHURN cascade: agreements at the district's schools in
    PROPOSED / ACTIVE / AMENDMENT_PENDING terminate (with their cascades)."""
    school_ids = {s['id'] for s in db.STORES['schools'].values()
                  if s['district_id'] == district['id']}
    for a in db.STORES['agreements'].values():
        if (a['school_id'] in school_ids
                and a['status'] in ('PROPOSED', 'ACTIVE', 'AMENDMENT_PENDING')):
            terminate_agreement(a)
    district['relationship_status'] = 'CHURNED'
    touch(district)


def exit_partner(partner):
    """Partner EXIT three-link cascade: volunteers DEPARTED -> their SCHEDULED
    sessions NEEDS_SUBSTITUTE -> affected deliveries bump version."""
    for v in db.STORES['volunteers'].values():
        if v['corporate_partner_id'] == partner['id'] and v['engagement_status'] == 'ACTIVE':
            v['engagement_status'] = 'DEPARTED'
            touch(v)
            mark_volunteer_ineligible(v)
    partner['status'] = 'EXITED'
    touch(partner)


def run_sweeps():
    """Clock-advance sweeps (PRD 2.4): credential expiry first (with the
    ineligibility cascade), then auto-NO_SHOW past the 7-day delivery window."""
    now = db.logical_now()
    for v in list(db.STORES['volunteers'].values()):
        expired = False
        if (v['screening_status'] == 'CLEARED'
                and v['screening_expires_on'] is not None
                and now > v['screening_expires_on']):
            v['screening_status'] = 'EXPIRED'
            expired = True
        if (v['training_status'] == 'COMPLETED'
                and v['training_expires_on'] is not None
                and now > v['training_expires_on']):
            v['training_status'] = 'EXPIRED'
            expired = True
        if expired:
            touch(v)
            mark_volunteer_ineligible(v)

    today = now.date()
    affected_delivery_ids = set()
    for s in list(db.STORES['sessions'].values()):
        if (s['status'] in ('SCHEDULED', 'NEEDS_SUBSTITUTE')
                and today > s['scheduled_date'] + timedelta(days=7)):
            was_blocked = s['status'] == 'NEEDS_SUBSTITUTE'
            s['status'] = 'NO_SHOW'
            touch(s)
            if was_blocked:
                affected_delivery_ids.add(s['delivery_id'])
    for delivery_id in affected_delivery_ids:
        delivery = db.STORES['deliveries'].get(delivery_id)
        if delivery is not None:
            touch(delivery)
