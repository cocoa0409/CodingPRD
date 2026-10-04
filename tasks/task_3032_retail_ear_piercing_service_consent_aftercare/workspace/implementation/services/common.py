"""Shared request-validation, lookup and reconciliation helpers."""

import db
import errors as E
import calculations as calc


# =============================================================================
# Request body helpers
# =============================================================================
def body():
    from flask import request
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require(data, field):
    """Required field, rejected with ERR_INVALID_REQUEST when absent."""
    if field not in data or data[field] is None:
        E.fail(E.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return data[field]


def require_str(data, field):
    value = require(data, field)
    if not isinstance(value, str) or value == "":
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return value


def require_enum(data, field, allowed):
    value = require(data, field)
    if value not in allowed:
        E.fail(E.ERR_INVALID_REQUEST,
               "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def optional_enum(data, field, allowed):
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if value not in allowed:
        E.fail(E.ERR_INVALID_REQUEST,
               "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


def require_int(data, field):
    value = require(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return value


def require_bool(data, field):
    value = require(data, field)
    if not isinstance(value, bool):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return value


def require_instant(data, field):
    raw = require(data, field)
    parsed = db.parse_instant(raw)
    if parsed is None:
        E.fail(E.ERR_INVALID_REQUEST,
               "Field %s must be an ISO 8601 instant" % field)
    return parsed


def optional_instant(data, field):
    if field not in data or data[field] is None:
        return None
    parsed = db.parse_instant(data[field])
    if parsed is None:
        E.fail(E.ERR_INVALID_REQUEST,
               "Field %s must be an ISO 8601 instant" % field)
    return parsed


def optional_number(data, field):
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return float(value)


def require_list(data, field):
    value = require(data, field)
    if not isinstance(value, list):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be an array" % field)
    return value


def validated_list(data, field, allowed, optional=False):
    if optional and (field not in data or data[field] is None):
        return []
    value = require_list(data, field)
    for item in value:
        if item not in allowed:
            E.fail(E.ERR_INVALID_REQUEST,
                   "Field %s contains an unknown value: %s" % (field, item))
    return list(value)


# =============================================================================
# Lookups. Path identifiers resolve left to right (PRD 2.11).
# =============================================================================
def get_or_404(table, row_id, spec):
    row = table.get(row_id)
    if row is None:
        E.fail(spec)
    return row


def get_jurisdiction(jurisdiction_id):
    return get_or_404(db.DB.jurisdictions, jurisdiction_id,
                      E.ERR_JURISDICTION_NOT_FOUND)


def get_store(store_id):
    return get_or_404(db.DB.stores, store_id, E.ERR_STORE_NOT_FOUND)


def get_piercer(piercer_id):
    return get_or_404(db.DB.piercers, piercer_id, E.ERR_PIERCER_NOT_FOUND)


def get_certification(certification_id):
    return get_or_404(db.DB.certifications, certification_id,
                      E.ERR_CERTIFICATION_NOT_FOUND)


def get_cycle(cycle_id):
    return get_or_404(db.DB.cycles, cycle_id, E.ERR_CYCLE_NOT_FOUND)


def get_lot(lot_id):
    return get_or_404(db.DB.lots, lot_id, E.ERR_CARTRIDGE_LOT_NOT_FOUND)


def get_customer(customer_id):
    return get_or_404(db.DB.customers, customer_id, E.ERR_CUSTOMER_NOT_FOUND)


def get_consent(consent_id):
    return get_or_404(db.DB.consents, consent_id, E.ERR_CONSENT_NOT_FOUND)


def get_appointment(appointment_id):
    return get_or_404(db.DB.appointments, appointment_id,
                      E.ERR_APPOINTMENT_NOT_FOUND)


def get_screening(screening_id):
    return get_or_404(db.DB.screenings, screening_id, E.ERR_SCREENING_NOT_FOUND)


def get_session(session_id):
    return get_or_404(db.DB.sessions, session_id, E.ERR_SESSION_NOT_FOUND)


def get_incident(incident_id):
    return get_or_404(db.DB.incidents, incident_id, E.ERR_INCIDENT_NOT_FOUND)


def get_outcome(outcome_id):
    return get_or_404(db.DB.outcomes, outcome_id,
                      E.ERR_HEALING_OUTCOME_NOT_FOUND)


# =============================================================================
# Pagination (PRD 2.3)
# =============================================================================
def pagination_params():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10 if limit_raw is None or limit_raw == "" else _parse_int(limit_raw, "limit")
    offset = 0 if offset_raw is None or offset_raw == "" else _parse_int(offset_raw, "offset")
    if limit < 1 or limit > 100:
        E.fail(E.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        E.fail(E.ERR_INVALID_REQUEST, "offset must not be negative")
    return limit, offset


def _parse_int(raw, field):
    try:
        return int(raw)
    except (TypeError, ValueError):
        E.fail(E.ERR_INVALID_REQUEST, "%s must be an integer" % field)


def sorted_rows(rows):
    """Default ordering: created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r.created_at, r.id))


# =============================================================================
# OCC (PRD 2.9)
# =============================================================================
def check_expected_version(data, field, parent):
    if field not in data or data[field] is None:
        return
    supplied = data[field]
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        E.fail(E.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if supplied != parent.version:
        E.fail(E.ERR_STALE_VERSION,
               "The supplied %s no longer describes the resource" % field)


# =============================================================================
# Derived-field reconciliation
# =============================================================================
def recompute_store_posture(store_location):
    posture, count = calc.store_posture_computation(db.DB, store_location.id)
    if (posture != store_location.compliance_posture
            or count != store_location.open_incident_count):
        store_location.compliance_posture = posture
        store_location.open_incident_count = count
        store_location.touch()
    return posture


def refresh_store_posture_read(store_location):
    """Reading a store's posture recomputes it before returning (PRD 2.7)."""
    return recompute_store_posture(store_location)


def select_governing_certification(piercer_id):
    """Selector policy piercer_governing_certification (PRD 2.6)."""
    store = db.DB
    rows = [c for c in store.certifications.values() if c.piercer_id == piercer_id]
    candidates = [c for c in rows if c.status in ("VALID", "EXPIRING_SOON")]
    if not candidates:
        candidates = [c for c in rows
                      if c.status in ("RECERTIFICATION_PENDING", "EXPIRED", "REVOKED")]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (
        -db.CERTIFICATION_LEVEL_ORDER.get(c.certification_level, 0),
        -db.CERTIFICATION_STATUS_ORDER.get(c.status, 0),
        -_issued_sort_key(c),
        c.created_at,
    ))
    return candidates[0]


def _issued_sort_key(cert):
    parsed = db.parse_instant(cert.issued_at)
    if parsed is None:
        return float("-inf")
    return parsed.timestamp()


def recompute_piercer_governing_state(piercer):
    governing = select_governing_certification(piercer.id)
    new_id = governing.id if governing else None
    changed = new_id != piercer.active_certification_id
    piercer.active_certification_id = new_id
    if changed:
        piercer.touch()
    return governing


def recompute_piercer_eligibility(piercer):
    score = calc.piercer_eligibility_score(piercer.id, "rolling_window")
    if score != piercer.eligibility_score:
        piercer.eligibility_score = score
        piercer.touch()
    return score


def evaluate_piercer_suspension(piercer):
    """Automatic ACTIVE -> SUSPENDED (PRD 2.10)."""
    if piercer.status != "ACTIVE":
        return
    low_score = piercer.eligibility_score < 60
    qualifying = [c for c in db.DB.certifications.values()
                  if c.piercer_id == piercer.id
                  and c.certification_level in ("STANDARD", "SENIOR", "INSTRUCTOR")
                  and c.status in ("VALID", "EXPIRING_SOON")]
    if low_score or not qualifying:
        piercer.status = "SUSPENDED"
        piercer.touch()
        recompute_piercer_governing_state(piercer)


def select_governing_screening(appointment_id):
    """Selector policy appointment_governing_screening (PRD 2.6)."""
    rows = [s for s in db.DB.screenings.values()
            if s.appointment_id == appointment_id
            and s.outcome in ("CLEARED", "REFUSED", "ESCALATED")]
    if not rows:
        return None
    rows.sort(key=lambda s: (
        -db.SCREENING_OUTCOME_ORDER.get(s.outcome, 0),
        _reverse_created_key(s.created_at),
        -db.SCREENING_OUTCOME_RANKS.get(s.outcome, 0),
    ))
    return rows[0]


def _reverse_created_key(created_at):
    # created_at DESC: negate the sortable epoch value.
    parsed = db.parse_instant(created_at)
    if parsed is None:
        return 0.0
    return -parsed.timestamp()


def recompute_appointment_governing_screening(appointment):
    governing = select_governing_screening(appointment.id)
    new_id = governing.id if governing else None
    if new_id != appointment.governing_screening_id:
        appointment.governing_screening_id = new_id
        appointment.touch()


def select_store_available_lot(store_id, site_type):
    """Selector policy store_available_lot (PRD 2.6)."""
    now = db.DB.clock
    candidates = []
    for lot in db.DB.lots.values():
        if lot.store_location_id != store_id:
            continue
        if lot.site_type != site_type:
            continue
        if lot.status != "AVAILABLE":
            continue
        if lot.units_available < 1:
            continue
        expiration = db.parse_instant(lot.expiration_date)
        if expiration is None or expiration <= now:
            continue
        candidates.append(lot)
    if not candidates:
        return None
    candidates.sort(key=lambda lot: (
        -lot.units_available,
        db.parse_instant(lot.expiration_date).timestamp(),
        lot.created_at,
    ))
    return candidates[0]


# =============================================================================
# Jurisdiction / consent rules
# =============================================================================
def customer_age(customer):
    dob = db.parse_instant(customer.date_of_birth)
    if dob is None:
        E.fail(E.ERR_INVALID_REQUEST, "Customer date_of_birth is not a valid instant")
    return db.age_in_whole_years(dob, db.DB.clock)


def enforce_age_gate(customer, jurisdiction, consent_types=None):
    """Age ladder (PRD 2.4 / 3.1). Evaluated before other business rules."""
    age = customer_age(customer)
    if age < jurisdiction.min_age_absolute:
        E.fail(E.ERR_AGE_BELOW_JURISDICTION_MINIMUM,
               "Customer is below the absolute minimum age for this jurisdiction")
    if age < jurisdiction.min_age_with_guardian:
        E.fail(E.ERR_AGE_BELOW_JURISDICTION_MINIMUM,
               "Customer is below the minimum age for piercing in this jurisdiction")
    if age < jurisdiction.min_age_self_consent:
        if consent_types is not None:
            allowed = {"GUARDIAN_PRESENT", "GUARDIAN_NOTARIZED", "COURT_ORDER"}
            if not (set(consent_types) & allowed):
                E.fail(E.ERR_AGE_BELOW_JURISDICTION_MINIMUM,
                       "A guardian-executed consent is required for this customer")
    return age


def enforce_consent_class_for_minor(customer, jurisdiction):
    """A customer below min_age_self_consent must be covered by a guardian
    consent instrument (PRD 3.1).

    At booking and at session opening there is no consent_type parameter, so
    the requirement is read off the customer's own consent records: once the
    customer holds any consent at all, at least one of them must be executed
    by a guardian.
    """
    if customer_age(customer) >= jurisdiction.min_age_self_consent:
        return
    held = [c for c in db.DB.consents.values() if c.customer_id == customer.id]
    if not held:
        return
    allowed = {"GUARDIAN_PRESENT", "GUARDIAN_NOTARIZED", "COURT_ORDER"}
    if not any(c.consent_type in allowed for c in held):
        E.fail(E.ERR_AGE_BELOW_JURISDICTION_MINIMUM,
               "A guardian-executed consent is required for this customer")


def enforce_permitted_site(jurisdiction, site):
    """Permitted-site gate (PRD 2.4 / 3.3)."""
    if site not in (jurisdiction.permitted_sites or []):
        E.fail(E.ERR_SITE_NOT_PERMITTED_IN_JURISDICTION,
               "Site %s is not permitted in this jurisdiction" % site)


def enforce_guardian_gate(consent, jurisdiction):
    """Guardian gate (PRD 3.2); outranks the identification gate."""
    if consent.consent_type == "SELF":
        return
    if consent.consent_type == "GUARDIAN_PRESENT" or consent.consent_type == "GUARDIAN_NOTARIZED":
        if consent.guardian_verification_status != "VERIFIED":
            E.fail(E.ERR_GUARDIAN_VERIFICATION_REQUIRED,
                   "Guardian identity verification is not VERIFIED")
    if consent.consent_type == "GUARDIAN_NOTARIZED" and jurisdiction.requires_guardian_presence:
        E.fail(E.ERR_GUARDIAN_VERIFICATION_REQUIRED,
               "This jurisdiction requires the guardian to be physically present")


def enforce_identification_gate(consent):
    if consent.identification_type != consent.required_identification_type:
        E.fail(E.ERR_IDENTIFICATION_TYPE_MISMATCH,
               "Presented identification does not match the required type")


def required_identification_type(customer, jurisdiction, consent_type):
    age = customer_age(customer)
    if age >= jurisdiction.min_age_self_consent and consent_type == "SELF":
        return db.REQUIRED_IDENTIFICATION_BY_CONSENT_TYPE["SELF"]
    return db.REQUIRED_IDENTIFICATION_BY_CONSENT_TYPE.get(
        consent_type, db.REQUIRED_IDENTIFICATION_BY_CONSENT_TYPE["SELF"])


def active_consent_for(customer_id):
    for consent in db.DB.consents.values():
        if consent.customer_id == customer_id and consent.consent_status == "ACTIVE":
            return consent
    return None


def enforce_certification_gate(piercer, jurisdiction):
    """Certification gate (PRD 3.5): VALID governing cert, protocol match."""
    governing_id = piercer.active_certification_id
    governing = db.DB.certifications.get(governing_id) if governing_id else None
    if governing is None or governing.status != "VALID":
        E.fail(E.ERR_PIERCER_NOT_CERTIFIED,
               "The assigned piercer holds no governing VALID certification")
    if governing.sterilization_protocol_code != jurisdiction.sterilization_protocol_code:
        E.fail(E.ERR_PIERCER_NOT_CERTIFIED,
               "The governing certification protocol does not match the jurisdiction's")


def enforce_lot_gate(lot):
    """Sterilization gate (PRD 3.5)."""
    if lot.status != "AVAILABLE":
        E.fail(E.ERR_CARTRIDGE_LOT_UNAVAILABLE, "Cartridge lot is not AVAILABLE")
    cycle = db.DB.cycles.get(lot.sterilization_cycle_id)
    if cycle is None or cycle.status not in ("PASSED", "RELEASED"):
        E.fail(E.ERR_CARTRIDGE_LOT_UNAVAILABLE,
               "Cartridge lot is not bound to a released sterilization cycle")
    expiration = db.parse_instant(lot.expiration_date)
    if expiration is None or expiration <= db.DB.clock:
        E.fail(E.ERR_CARTRIDGE_LOT_UNAVAILABLE, "Cartridge lot has expired")


def consume_lot_unit(lot):
    lot.units_consumed += 1
    lot.units_available = calc.cartridge_lot_availability(lot)
    if lot.status == "AVAILABLE" and lot.units_available <= 0:
        lot.status = "DEPLETED"
    lot.touch()


def quarantine_lot(lot):
    lot.status = "QUARANTINED"
    lot.units_quarantined = lot.units_available
    lot.units_available = 0
    lot.touch()


def release_lot(lot):
    if lot.status != "QUARANTINED":
        return
    expiration = db.parse_instant(lot.expiration_date)
    if expiration is None or expiration <= db.DB.clock:
        return
    lot.status = "AVAILABLE"
    lot.units_available = lot.units_quarantined
    lot.units_quarantined = 0
    lot.touch()


def refresh_lot_availability(lot):
    availability = calc.cartridge_lot_availability(lot)
    if availability != lot.units_available:
        lot.units_available = availability
        lot.touch()
    if lot.status == "AVAILABLE" and lot.units_available <= 0:
        lot.status = "DEPLETED"
        lot.touch()


# =============================================================================
# Session lookup helpers
# =============================================================================
def session_of_appointment(appointment_id):
    rows = [s for s in db.DB.sessions.values() if s.appointment_id == appointment_id]
    rows.sort(key=lambda s: (s.created_at, s.id))
    return rows


def active_session_of_appointment(appointment_id):
    for session in db.DB.sessions.values():
        if session.appointment_id == appointment_id \
                and session.service_status == "IN_PROGRESS":
            return session
    return None


def session_owner_customer(session):
    appointment = db.DB.appointments.get(session.appointment_id)
    if appointment is None:
        return None
    return db.DB.customers.get(appointment.customer_id)


def latest_outcome_of_session(session_id):
    rows = [o for o in db.DB.outcomes.values() if o.session_id == session_id]
    rows.sort(key=lambda o: (o.created_at, o.id))
    return rows[-1] if rows else None


def incidents_of_session(session_id):
    rows = [i for i in db.DB.incidents.values() if i.session_id == session_id]
    rows.sort(key=lambda i: (i.created_at, i.id))
    return rows


def session_store(session):
    appointment = db.DB.appointments.get(session.appointment_id)
    if appointment is None:
        return None
    return db.DB.stores.get(appointment.store_location_id)


def file_incident(session_id, severity, reaction_codes):
    incident = db.IncidentReport()
    incident.session_id = session_id
    incident.reported_at = db.fmt_instant(db.DB.clock)
    incident.severity = severity
    incident.reaction_codes = list(reaction_codes)
    db.DB.incidents[incident.id] = incident
    session = db.DB.sessions.get(session_id)
    if session is not None:
        session.touch()
        recompute_store_of_session(session)
    return incident


def recompute_store_of_session(session):
    """Reconcile the owning store's derived posture after an incident change.

    PRD 2.7: "Posture is recomputed whenever any incident escalation status
    changes at the store". `open_incident_count` is a pure function of the
    store's reachable non-terminal incident rows plus its failed-cycle lot
    exposure, so reconciliation recomputes rather than blind-incrementing.
    """
    store = session_store(session)
    if store is not None:
        recompute_store_posture(store)
    return store


def cancel_booking_rows(appointments):
    for appointment in appointments:
        appointment.status = "CANCELLED"
        appointment.touch()


def appointments_at_store(store_id):
    return [a for a in db.DB.appointments.values()
            if a.store_location_id == store_id]


# =============================================================================
# Lifecycle sweeps driven by the logical clock (PRD 2.10 / 3.2 / 3.3)
# =============================================================================
def sweep_clock_driven_transitions():
    store = db.DB
    now = store.clock

    for cert in list(store.certifications.values()):
        due = db.parse_instant(cert.recertification_due_at)
        expires = db.parse_instant(cert.expires_at)
        if cert.status == "VALID" and due is not None and now >= due:
            cert.status = "EXPIRING_SOON"
            cert.touch()
            _cascade_piercer_recompute(cert.piercer_id)
        if cert.status == "EXPIRING_SOON" and expires is not None and now >= expires:
            cert.status = "EXPIRED"
            cert.touch()
            _cascade_piercer_recompute(cert.piercer_id)
            _cascade_suspend_on_expiry(cert)

    for consent in list(store.consents.values()):
        if consent.consent_status != "ACTIVE":
            continue
        expires = db.parse_instant(consent.expires_at)
        if expires is not None and now >= expires:
            consent.consent_status = "EXPIRED"
            consent.touch()

    for appointment in list(store.appointments.values()):
        if appointment.status != "CONFIRMED":
            continue
        slot_end = db.parse_instant(appointment.slot_end_at)
        if slot_end is not None and now > slot_end:
            appointment.status = "NO_SHOW"
            appointment.touch()


def _cascade_piercer_recompute(piercer_id):
    piercer = db.DB.piercers.get(piercer_id)
    if piercer is None:
        return
    recompute_piercer_eligibility(piercer)
    recompute_piercer_governing_state(piercer)
    evaluate_piercer_suspension(piercer)


def _cascade_suspend_on_expiry(cert):
    if cert.certification_level in ("STANDARD", "SENIOR", "INSTRUCTOR"):
        piercer = db.DB.piercers.get(cert.piercer_id)
        if piercer is not None and piercer.status == "ACTIVE":
            piercer.status = "SUSPENDED"
            piercer.touch()


def cascade_customer_flags(piercer_id=None):
    """Automatic ACTIVE -> FLAGGED for affected customers (PRD 3.7)."""
    store = db.DB
    for customer in list(store.customers.values()):
        if customer.status != "ACTIVE":
            continue
        if _customer_should_be_flagged(customer, piercer_id):
            customer.status = "FLAGGED"
            customer.touch()
            cancel_booking_rows([a for a in appointments_at_store_any(customer)
                                 if a.status in ("BOOKED", "CONFIRMED")])


def appointments_at_store_any(customer):
    return [a for a in db.DB.appointments.values() if a.customer_id == customer.id]


def _customer_should_be_flagged(customer, piercer_filter=None):
    store = db.DB
    appointments = {a.id: a for a in store.appointments.values()
                    if a.customer_id == customer.id}
    sessions = [s for s in store.sessions.values() if s.appointment_id in appointments]
    session_ids = {s.id for s in sessions}
    for incident in store.incidents.values():
        if incident.session_id not in session_ids:
            continue
        if incident.severity in ("SEVERE", "MEDICAL_EMERGENCY") \
                and incident.escalation_status in db.NON_TERMINAL_INCIDENT_STATES:
            return True
    for session in sessions:
        if piercer_filter is not None and session.piercer_id != piercer_filter:
            continue
        piercer = store.piercers.get(session.piercer_id)
        if piercer is not None and piercer.eligibility_score < 60:
            return True
    return False