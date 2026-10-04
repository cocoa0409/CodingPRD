"""Calculation rules (PRD 2.7, 2.8, 3.5, 3.6, 3.7, 3.9; scaffold 1.3).

Money is integer cents throughout. Scale steps floor to whole cents except the
downgrade credit, which rounds half up per site.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import db


def _floor_cents(amount):
    return int(Decimal(str(amount)).to_integral_value(rounding=ROUND_FLOOR))


def _round_half_up_cents(amount):
    return int(Decimal(str(amount)).to_integral_value(rounding=ROUND_HALF_UP))


# =============================================================================
# net_service_fee (PRD 3.5)
# =============================================================================
def discount_rate_for(pre_discount_subtotal_cents):
    if pre_discount_subtotal_cents < db.TIER_1_FLOOR_CENTS:
        return 0.00
    if pre_discount_subtotal_cents < db.TIER_2_FLOOR_CENTS:
        return db.TIER_1_RATE
    return db.TIER_2_RATE


def net_service_fee(base_fee_cents, aftercare_kit_included, site_pierced,
                    is_re_pierce=False):
    """Returns (net_fee_cents, discount_rate, re_pierce_discount_cents)."""
    aftercare_component = (db.AFTERCARE_KIT_FEE_CENTS
                           if aftercare_kit_included else 0)
    pre_discount_subtotal = int(base_fee_cents) + aftercare_component
    rate = discount_rate_for(pre_discount_subtotal)
    re_pierce_discount = 0
    if is_re_pierce:
        re_pierce_discount = _floor_cents(pre_discount_subtotal * db.RE_PIERCE_RATE)
    net = (pre_discount_subtotal
           - _floor_cents(pre_discount_subtotal * rate)
           - re_pierce_discount)
    net = max(net, db.SITE_MINIMUM_CENTS)
    return net, rate, re_pierce_discount


# =============================================================================
# incident_refund_allocation (PRD 3.7)
# =============================================================================
def refundable_portion(severity, gross_fee_cents):
    if severity == "MINOR":
        return 0
    if severity == "MODERATE":
        return _floor_cents(gross_fee_cents * db.MODERATE_RATE)
    if severity == "SEVERE":
        return _floor_cents(gross_fee_cents * db.SEVERE_RATE)
    if severity == "MEDICAL_EMERGENCY":
        return gross_fee_cents
    return 0


def incident_refund_allocation(incident, session, customer, variant):
    """variant is 'provisional_at_triage' or 'final_at_resolution'."""
    base_fee_cents = session.base_fee_cents
    if variant == "provisional_at_triage":
        # The provisional variant uses the session's recorded net_fee_cents.
        gross_fee_cents = session.net_fee_cents
    else:
        aftercare_kit_fee = (db.AFTERCARE_KIT_FEE_CENTS
                             if session.aftercare_kit_included else 0)
        gross_fee_cents = base_fee_cents + aftercare_kit_fee

    prior_refunded_cents = customer.refunded_cents
    refund = max(refundable_portion(incident.severity, gross_fee_cents)
                 - prior_refunded_cents, 0)
    retain_cap = max(gross_fee_cents - db.AFTERCARE_RETAIN_FLOOR_CENTS, 0)
    if refund > retain_cap:
        refund = retain_cap
    return refund


# =============================================================================
# piercer_eligibility_score (PRD 2.10)
# =============================================================================
CERT_CONTRIBUTION = {
    "VALID": 0,
    "EXPIRING_SOON": -10,
    "RECERTIFICATION_PENDING": -15,
    "EXPIRED": -30,
    "REVOKED": -40,
}

INCIDENT_CONTRIBUTION = {
    "MINOR": -5,
    "MODERATE": -12,
    "SEVERE": -25,
    "MEDICAL_EMERGENCY": -50,
}


def _sessions_of_piercer(store, piercer_id):
    return [s for s in store.sessions.values() if s.piercer_id == piercer_id]


def _incidents_attributable(store, piercer_id):
    """Incident rows whose session was performed by this piercer."""
    by_session = {}
    for session in _sessions_of_piercer(store, piercer_id):
        by_session[session.id] = session
    rows = [i for i in store.incidents.values() if i.session_id in by_session]
    return rows, by_session


def piercer_eligibility_score(piercer_id, variant="rolling_window", store=None):
    store = store or db.DB
    piercer = store.piercers.get(piercer_id)
    if piercer is None:
        return 0
    certs = [c for c in store.certifications.values() if c.piercer_id == piercer_id]
    certs.sort(key=lambda c: (c.created_at, c.id))
    incidents, _ = _incidents_attributable(store, piercer_id)

    if variant == "cumulative_chronological":
        incidents.sort(key=lambda i: (i.reported_at or "", i.created_at, i.id))
    else:
        window_start = db.add_days(store.clock, -db.ELIGIBILITY_WINDOW_DAYS)
        certs = [c for c in certs
                 if db.parse_instant(c.created_at) >= window_start]
        incidents = [i for i in incidents
                     if db.parse_instant(i.reported_at) >= window_start]
        incidents.sort(key=lambda i: (i.reported_at or "", i.created_at, i.id))

    raw = db.BASE_SCORE
    for cert in certs:
        raw += CERT_CONTRIBUTION.get(cert.status, 0)
    for incident in incidents:
        raw += INCIDENT_CONTRIBUTION.get(incident.severity, 0)

    # Completion bonus: +8 per COMPLETED session since the most recent incident.
    latest_incident_at = None
    if incidents:
        latest_incident_at = max((i.reported_at or "") for i in incidents)
    bonus_count = 0
    for session in _sessions_of_piercer(store, piercer_id):
        if session.service_status != "COMPLETED":
            continue
        completed_at = getattr(session, "completed_at", None)
        if latest_incident_at is None:
            bonus_count += 1
        elif completed_at is not None and completed_at >= latest_incident_at:
            bonus_count += 1
    raw += db.COMPLETION_BONUS * bonus_count

    return max(db.FLOOR_SCORE, min(raw, db.CEILING_SCORE))


# =============================================================================
# downgrade_credit_amount (PRD 3.6) — round PER SITE, then sum
# =============================================================================
def downgrade_credit_amount(downgraded_sites):
    total = 0
    for site in downgraded_sites:
        base_value = db.SITE_BASE_VALUE_CENTS.get(site, 0)
        total += _round_half_up_cents(base_value * db.DOWNGRADE_RATE)
    return total


# =============================================================================
# site_complexity_surcharge (PRD 3.5)
# =============================================================================
def site_complexity_surcharge(base_fee_cents, site_pierced, contraindication_count,
                              site_count_requested):
    site_factor = db.SITE_FACTORS.get(site_pierced, 1.0)
    cartilage_hazard = min(max(contraindication_count - 1, 0), 3) \
        * db.PER_CONTRAINDICATION_CENTS
    quantity_hazard = max(site_count_requested - 1, 0) * db.PER_EXTRA_SITE_CENTS
    site_term = _floor_cents(base_fee_cents * (site_factor - 1.0))
    return min(cartilage_hazard + quantity_hazard + site_term,
               db.MAX_SURCHARGE_CENTS)


# =============================================================================
# store_posture_computation (PRD 2.7)
# =============================================================================
def store_failed_cycle_count(store, store_id):
    return sum(1 for c in store.cycles.values()
               if c.store_location_id == store_id and c.status == "FAILED")


def store_failed_cycle_lot_contribution(store, store_id):
    """Count of bound lots over the store's FAILED cycles.

    PRD 2.7: the failure of a cycle "propagates in a four-step chain: every bound
    `CartridgeLot` becomes `QUARANTINED`; for each such lot the owning store's
    `open_incident_count` increases by one and that store's posture is
    recomputed". Deriving the contribution from the FAILED cycles keeps the
    denormalized `open_incident_count` a pure function of store state.
    """
    total = 0
    for cycle in store.cycles.values():
        if cycle.store_location_id != store_id or cycle.status != "FAILED":
            continue
        total += sum(1 for lot in store.lots.values()
                     if lot.sterilization_cycle_id == cycle.id)
    return total


def store_incident_rows(store, store_id):
    """Incident rows reachable through the store's sessions."""
    session_ids = {s.id for s in store.sessions.values()
                   if s.appointment_id is not None
                   and _appointment_at_store(store, s.appointment_id, store_id)}
    return [i for i in store.incidents.values() if i.session_id in session_ids]


def _appointment_at_store(store, appointment_id, store_id):
    appointment = store.appointments.get(appointment_id)
    return appointment is not None and appointment.store_location_id == store_id


def store_posture_computation(store, store_id):
    """Returns (compliance_posture, open_incident_count)."""
    rows = store_incident_rows(store, store_id)
    open_rows = [i for i in rows
                 if i.escalation_status in db.NON_TERMINAL_INCIDENT_STATES]
    open_incident_count = (len(open_rows)
                           + store_failed_cycle_lot_contribution(store, store_id))
    critical_incident_count = sum(1 for i in open_rows
                                  if i.severity == "MEDICAL_EMERGENCY")
    failed_cycle_count = store_failed_cycle_count(store, store_id)

    if (critical_incident_count >= 1
            or failed_cycle_count >= db.FREEZE_FAILED_CYCLE_THRESHOLD):
        posture = "FROZEN"
    elif (open_incident_count >= db.RESTRICTION_INCIDENT_THRESHOLD
          or failed_cycle_count >= db.RESTRICTION_FAILED_CYCLE_THRESHOLD):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return posture, open_incident_count


# =============================================================================
# cartridge_lot_availability (PRD 2.7)
# =============================================================================
def cartridge_lot_availability(lot):
    available = lot.units_received - lot.units_consumed - lot.units_quarantined
    return max(available, 0)


# =============================================================================
# certification_recertification_due (PRD 2.10)
# =============================================================================
def certification_recertification_due(expires_at):
    return db.add_days(expires_at, -db.RECERTIFICATION_LEAD_DAYS)


def consent_expiry(signed_at):
    return db.add_days(signed_at, db.CONSENT_VALIDITY_DAYS)


# =============================================================================
# quarantine_unit_exposure (PRD 2.7)
# =============================================================================
def quarantine_unit_exposure(store, cycle_id):
    return sum(lot.units_available for lot in store.lots.values()
               if lot.sterilization_cycle_id == cycle_id)