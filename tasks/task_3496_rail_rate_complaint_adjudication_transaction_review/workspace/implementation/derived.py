"""Derived carrier condition registers (PRD 2.9), the merger service hold, and
the lazy emergency-service-order expiry sweep (PRD 2.5).

Carrier condition is derived, never edited directly. Each recompute applies the
new value and, when the stored value actually changes, bumps the carrier's
version and refreshed updated_at — the PRD 2.4 rule that cascaded mutations
each gain one version increment. A recompute that leaves the value unchanged is
not a mutation.
"""
import store


def _carrier(carrier_id):
    return store.db['carriers'].get(carrier_id)


def carrier_has_active_eso(carrier_id):
    return any(
        e['carrier_id'] == carrier_id and e['status'] == 'ACTIVE'
        for e in store.db['esos'].values()
    )


def recompute_carrier_mileage(carrier):
    abandoned = sum(
        a['segment_miles']
        for a in store.db['abandonments'].values()
        if a['carrier_id'] == carrier['id'] and a['status'] == 'CONSUMMATED'
    )
    trail = sum(
        a['segment_miles']
        for a in store.db['abandonments'].values()
        if a['carrier_id'] == carrier['id'] and a['status'] == 'TRAIL_CONVERTED'
    )
    active = carrier['base_route_miles'] - abandoned - trail
    if (carrier['abandoned_route_miles'] != abandoned
            or carrier['trail_use_route_miles'] != trail
            or carrier['active_route_miles'] != active):
        carrier['abandoned_route_miles'] = abandoned
        carrier['trail_use_route_miles'] = trail
        carrier['active_route_miles'] = active
        store.touch(carrier)


def recompute_revenue_status(carrier):
    findings = [f for f in store.db['findings'].values() if f['carrier_id'] == carrier['id']]
    status = 'UNDETERMINED'
    if findings:
        latest = max(findings, key=lambda f: f['fiscal_year'])
        status = latest['finding']
    if carrier['revenue_adequacy_status'] != status:
        carrier['revenue_adequacy_status'] = status
        store.touch(carrier)


def recompute_standing(carrier):
    standing = 'PROBATION' if carrier_has_active_eso(carrier['id']) else 'GOOD'
    if carrier['compliance_standing'] != standing:
        carrier['compliance_standing'] = standing
        store.touch(carrier)


def recompute_merger_holds(carrier_id):
    """service_review_hold is true iff the acquiring carrier has any ACTIVE ESO;
    only COMMENT_PERIOD applications are revisited (PRD 3.5 hop 3)."""
    hold = carrier_has_active_eso(carrier_id)
    for m in store.db['mergers'].values():
        if m['acquiring_carrier_id'] == carrier_id and m['status'] == 'COMMENT_PERIOD':
            if m['service_review_hold'] != hold:
                m['service_review_hold'] = hold
                store.touch(m)


def recompute_exposure(carrier):
    """Sum of award_outstanding_cents over the carrier's DECIDED complaints."""
    total = sum(
        c['award_outstanding_cents']
        for c in store.db['rate_complaints'].values()
        if c['carrier_id'] == carrier['id'] and c['status'] == 'DECIDED'
    )
    if carrier['reparation_exposure_cents'] != total:
        carrier['reparation_exposure_cents'] = total
        store.touch(carrier)


def sweep_eso_expiry():
    """Lazy expiry: any ACTIVE ESO whose expires_at the clock has reached or
    passed transitions to EXPIRED; carrier standing and merger holds recompute.
    Evaluated on every read or write (PRD 2.5)."""
    now = store.clock_now()
    expired = [
        e for e in store.db['esos'].values()
        if e['status'] == 'ACTIVE' and e['_expires_at_dt'] is not None
        and now >= e['_expires_at_dt']
    ]
    if not expired:
        return
    carrier_ids = set()
    for e in expired:
        e['status'] = 'EXPIRED'
        store.touch(e)
        carrier_ids.add(e['carrier_id'])
    for cid in carrier_ids:
        carrier = _carrier(cid)
        if carrier is not None:
            recompute_standing(carrier)
        recompute_merger_holds(cid)
