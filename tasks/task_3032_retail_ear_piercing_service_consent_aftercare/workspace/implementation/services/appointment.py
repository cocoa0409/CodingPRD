"""Booking, slot discipline, screening fork and service lifecycle.

Implements PRD 3.3, 3.4 and 3.5.
"""

import db
import errors as E
import calculations as calc
from services import common


# =============================================================================
# Slot geometry (PRD 3.3)
# =============================================================================
def _slot_bounds(appointment):
    start = db.parse_instant(appointment.slot_start_at)
    end = db.parse_instant(appointment.slot_end_at)
    return db.floor_to_minute(start), db.floor_to_minute(end)


def _overlaps(first, second):
    """Half-open [start, end): adjacency where one end equals the next start is fine."""
    return first[0] < second[1] and second[0] < first[1]


def validate_slot_duration(start, end):
    if end - start < db.add_minutes(start, db.SLOT_MIN_MINUTES) - start:
        E.fail(E.ERR_INVALID_REQUEST,
               "slot_end_at must be at least %d minutes after slot_start_at"
               % db.SLOT_MIN_MINUTES)


def enforce_piercer_adjacency(candidate_start, candidate_end, store_id, piercer_id,
                              exclude_id=None):
    candidate = (db.floor_to_minute(candidate_start), db.floor_to_minute(candidate_end))
    for other in db.DB.appointments.values():
        if other.id == exclude_id:
            continue
        if other.store_location_id != store_id or other.piercer_id != piercer_id:
            continue
        if other.status == "CANCELLED":
            continue
        if _overlaps(candidate, _slot_bounds(other)):
            E.fail(E.ERR_SLOT_OVERLAP,
                   "The slot overlaps another appointment for this piercer")


def enforce_room_capacity(candidate_start, candidate_end, store, exclude_id=None):
    intervals = []
    for other in db.DB.appointments.values():
        if other.id == exclude_id:
            continue
        if other.store_location_id != store.id:
            continue
        if other.status == "CANCELLED":
            continue
        intervals.append(_slot_bounds(other))
    intervals.append((db.floor_to_minute(candidate_start),
                      db.floor_to_minute(candidate_end)))
    if _peak_overlap(intervals) > store.piercing_room_count:
        E.fail(E.ERR_STORE_ROOM_CAPACITY_EXCEEDED,
               "Concurrent occupancy would exceed piercing_room_count")


def _peak_overlap(intervals):
    events = []
    for start, end in intervals:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    current = 0
    peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


# =============================================================================
# Booking
# =============================================================================
def book_appointment(store, customer, piercer, jurisdiction, intake_type,
                     site_requested, start_at, end_at):
    if (end_at - start_at).total_seconds() < db.SLOT_MIN_MINUTES * 60:
        E.fail(E.ERR_INVALID_REQUEST,
               "slot_end_at must be at least %d minutes after slot_start_at"
               % db.SLOT_MIN_MINUTES)

    # Business safety: age gate, then consent class, then permitted-site gate.
    common.enforce_age_gate(customer, jurisdiction, None)
    common.enforce_consent_class_for_minor(customer, jurisdiction)
    common.enforce_permitted_site(jurisdiction, site_requested)

    # Temporal gates: piercer adjacency, then store room capacity.
    enforce_piercer_adjacency(start_at, end_at, store.id, piercer.id)
    enforce_room_capacity(start_at, end_at, store)

    appointment = db.Appointment()
    appointment.store_location_id = store.id
    appointment.customer_id = customer.id
    appointment.piercer_id = piercer.id
    appointment.jurisdiction_id = jurisdiction.id
    appointment.intake_type = intake_type
    appointment.site_requested = site_requested
    appointment.slot_start_at = db.fmt_instant(start_at)
    appointment.slot_end_at = db.fmt_instant(end_at)
    appointment.reschedule_count = 0
    appointment.status = "BOOKED"
    db.DB.appointments[appointment.id] = appointment
    return appointment


def confirm_appointment(appointment):
    if appointment.status == "BOOKED":
        _validate_confirmation_gates(appointment)
        appointment.status = "CONFIRMED"
        appointment.touch()
        return appointment
    if appointment.status == "RESCHEDULED":
        start = db.parse_instant(appointment.slot_start_at)
        end = db.parse_instant(appointment.slot_end_at)
        enforce_piercer_adjacency(start, end, appointment.store_location_id,
                                  appointment.piercer_id, exclude_id=appointment.id)
        appointment.status = "BOOKED"
        appointment.touch()
        return appointment
    E.fail(E.ERR_INVALID_STATE, "Appointment cannot be confirmed from this state")


def _validate_confirmation_gates(appointment):
    start = db.parse_instant(appointment.slot_start_at)
    end = db.parse_instant(appointment.slot_end_at)
    enforce_piercer_adjacency(start, end, appointment.store_location_id,
                              appointment.piercer_id, exclude_id=appointment.id)
    store = db.DB.stores.get(appointment.store_location_id)
    if store is not None:
        enforce_room_capacity(start, end, store, exclude_id=appointment.id)
    jurisdiction = db.DB.jurisdictions.get(appointment.jurisdiction_id)
    if jurisdiction is None or jurisdiction.status != "ACTIVE":
        E.fail(E.ERR_INVALID_STATE,
               "Only an ACTIVE jurisdiction may gate an appointment confirmation")


def check_in_appointment(appointment):
    if appointment.status != "CONFIRMED":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not CONFIRMED")

    slot_start = db.parse_instant(appointment.slot_start_at)
    earliest = db.add_minutes(slot_start, -db.CHECK_IN_LEAD_MINUTES)
    if db.DB.clock < earliest:
        E.fail(E.ERR_INVALID_STATE,
               "Check-in is not yet open for this slot")

    store = db.DB.stores.get(appointment.store_location_id)
    if store is None or store.status != "OPEN":
        E.fail(E.ERR_INVALID_STATE, "Store status is not OPEN")

    consent = common.active_consent_for(appointment.customer_id)
    if consent is None:
        E.fail(E.ERR_INVALID_STATE,
               "The customer holds no ACTIVE consent")
    jurisdiction = db.DB.jurisdictions.get(consent.jurisdiction_id)
    if jurisdiction is not None:
        common.enforce_guardian_gate(consent, jurisdiction)

    appointment.status = "CHECKED_IN"
    appointment.touch()
    return appointment


def screen_appointment(appointment, piercer_id, anatomy_sites, contraindications):
    """CHECKED_IN -> SCREENED.

    When this step records the screening itself, ``AnatomyScreening.outcome``
    is set to CLEARED or REFUSED by the screening evaluator as part of the
    same step (scaffold 1.2). A controlled screening failure is a refusal
    rather than an error here: the appointment still reaches SCREENED and the
    fork is taken explicitly by ``refuse``. A screening that a caller already
    recorded is left at PENDING so that ``POST /screenings/{id}/evaluate``
    remains its own operation.
    """
    if appointment.status != "CHECKED_IN":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not CHECKED_IN")

    owned = [s for s in db.DB.screenings.values()
             if s.appointment_id == appointment.id and s.piercer_id == piercer_id]
    owned.sort(key=lambda s: (s.created_at, s.id))
    screening = owned[-1] if owned else None

    with db.atomic_mutation(appointment):
        recorded_here = False
        if screening is None:
            if anatomy_sites is None and contraindications is None:
                E.fail(E.ERR_INVALID_STATE,
                       "The acting piercer owns no screening for this appointment")
            screening = create_screening(appointment, piercer_id,
                                         anatomy_sites or [], contraindications or [])
            recorded_here = True
        if recorded_here and screening.outcome == "PENDING":
            try:
                evaluate_screening(screening)
            except E.ApiError as exc:
                if exc.error_id != E.ERR_MEDICAL_CONTRAINDICATION[0]:
                    raise
        appointment.status = "SCREENED"
        common.recompute_appointment_governing_screening(appointment)
    return appointment


def create_screening(appointment, piercer_id, anatomy_sites, contraindications):
    screening = db.AnatomyScreening()
    screening.appointment_id = appointment.id
    screening.piercer_id = piercer_id
    screening.anatomy_sites_examined = list(anatomy_sites)
    screening.contraindication_codes = list(contraindications)
    screening.refusal_reason_code = None
    screening.outcome = "PENDING"
    db.DB.screenings[screening.id] = screening

    # Recording a screening increments the target appointment's version.
    appointment.touch()
    return screening


def evaluate_screening(screening):
    """Resolve a PENDING screening into CLEARED, REFUSED or ESCALATED."""
    if screening.outcome != "PENDING":
        E.fail(E.ERR_SCREENING_ALREADY_EVALUATED,
               "The screening already carries a terminal outcome")

    appointment = db.DB.appointments.get(screening.appointment_id)
    jurisdiction = None
    if appointment is not None:
        jurisdiction = db.DB.jurisdictions.get(appointment.jurisdiction_id)

    codes = list(screening.contraindication_codes or [])

    # PRD 3.4: "A screening carrying any of `KELOID_HISTORY`,
    # `BLOOD_THINNER_THERAPY` or `ACTIVE_INFECTION` can never clear; the refusal
    # or escalation is reported with `ERR_MEDICAL_CONTRAINDICATION` and HTTP
    # 422". The refusal/escalation is therefore the reported outcome of the
    # evaluation — the screening is resolved, and the error carries the failure.
    if _must_not_clear(codes):
        escalation_hits = [c for c in codes if c in db.ESCALATION_RANK_CODES]
        screening.outcome = "ESCALATED" if escalation_hits else "REFUSED"
        screening.refusal_reason_code = _highest_severity(codes)
        screening.touch()
        _recompute_governing(appointment)
        if screening.outcome == "ESCALATED":
            # An ESCALATED screening files a MINOR incident against the linked
            # session.
            session = common.active_session_of_appointment(screening.appointment_id) \
                or (common.session_of_appointment(screening.appointment_id) or [None])[0]
            if session is not None:
                common.file_incident(session.id, "MINOR", [])
        E.fail(E.ERR_MEDICAL_CONTRAINDICATION,
               "A contraindication code requires refusal or escalation")

    if not codes:
        if appointment is not None and jurisdiction is not None:
            common.enforce_permitted_site(jurisdiction, appointment.site_requested)
        screening.outcome = "CLEARED"
        screening.refusal_reason_code = None
        screening.touch()
        _recompute_governing(appointment)
        return screening

    escalation_hits = [c for c in codes if c in db.ESCALATION_RANK_CODES]
    if escalation_hits:
        screening.outcome = "ESCALATED"
        screening.refusal_reason_code = _highest_severity(codes)
        screening.touch()
        _recompute_governing(appointment)
        # An ESCALATED screening files a MINOR incident against the linked session.
        session = common.active_session_of_appointment(screening.appointment_id) \
            or (common.session_of_appointment(screening.appointment_id) or [None])[0]
        if session is not None:
            common.file_incident(session.id, "MINOR", [])
        return screening

    screening.outcome = "REFUSED"
    screening.refusal_reason_code = _highest_severity(codes)
    screening.touch()
    _recompute_governing(appointment)
    E.fail(E.ERR_MEDICAL_CONTRAINDICATION,
           "A contraindication code requires refusal or escalation")


def _must_not_clear(codes):
    """The codes that can never clear (PRD 3.4)."""
    return bool(set(codes) & {"KELOID_HISTORY", "BLOOD_THINNER_THERAPY",
                              "ACTIVE_INFECTION"})


def _highest_severity(codes):
    ranked = sorted(codes, key=lambda c: -db.CONTRAINDICATION_SEVERITY_RANK.get(c, 0))
    return ranked[0] if ranked else None


def _recompute_governing(appointment):
    if appointment is not None:
        common.recompute_appointment_governing_screening(appointment)


def escalate_screening(screening):
    if screening.outcome != "REFUSED":
        E.fail(E.ERR_INVALID_STATE, "Screening is not REFUSED")
    if screening.refusal_reason_code not in ("KELOID_HISTORY", "BLOOD_THINNER_THERAPY"):
        E.fail(E.ERR_INVALID_STATE,
               "Only a KELOID_HISTORY or BLOOD_THINNER_THERAPY refusal may escalate")
    screening.outcome = "ESCALATED"
    screening.touch()
    _recompute_governing(db.DB.appointments.get(screening.appointment_id))
    return screening


def override_screening(screening, medical_clearance_ref, override_outcome):
    if screening.outcome != "ESCALATED":
        E.fail(E.ERR_INVALID_STATE, "Screening is not ESCALATED")

    if override_outcome is not None:
        if override_outcome not in ("CLEARED", "REFUSED"):
            E.fail(E.ERR_INVALID_REQUEST,
                   "override_outcome must be CLEARED or REFUSED")
        target = override_outcome
    elif medical_clearance_ref:
        target = "CLEARED"
    else:
        target = "REFUSED"

    if target == "CLEARED" and not medical_clearance_ref:
        E.fail(E.ERR_INVALID_REQUEST,
               "A signed medical clearance reference is required to clear")

    screening.outcome = target
    if target == "CLEARED":
        screening.refusal_reason_code = None
    screening.touch()
    _recompute_governing(db.DB.appointments.get(screening.appointment_id))
    return screening


def refuse_appointment(appointment, refusal_reason_code):
    if appointment.status != "SCREENED":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not SCREENED")
    governing = _governing(appointment)
    if governing is None or governing.outcome not in ("REFUSED", "ESCALATED"):
        E.fail(E.ERR_INVALID_STATE,
               "The governing screening is not REFUSED or ESCALATED")
    appointment.status = "REFUSED"
    appointment.touch()
    governing.outcome = "REFUSED"
    governing.touch()
    return appointment


def _governing(appointment):
    governing_id = appointment.governing_screening_id
    if not governing_id:
        return None
    return db.DB.screenings.get(governing_id)


# =============================================================================
# Service start / complete / abort (PRD 3.5)
# =============================================================================
def start_service(appointment, session_factory):
    """SCREENED -> IN_SERVICE with the pinned check order."""
    if appointment.status != "SCREENED":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not SCREENED")

    # 1. Governing screening must be CLEARED - checked before all other business checks.
    governing = _governing(appointment)
    if governing is None or governing.outcome != "CLEARED":
        E.fail(E.ERR_SCREENING_NOT_CLEARED,
               "The governing screening does not resolve to CLEARED")

    # 2. Store must permit service.
    store = db.DB.stores.get(appointment.store_location_id)
    if store is None:
        E.fail(E.ERR_STORE_NOT_FOUND)
    if store.compliance_posture != "OPEN" or store.status == "CLOSED":
        E.fail(E.ERR_STORE_POSTURE_BLOCKS_SERVICE,
               "The store's posture or status blocks service")

    # 3. Piercer must be ACTIVE with a VALID governing certification.
    piercer = db.DB.piercers.get(appointment.piercer_id)
    if piercer is None:
        E.fail(E.ERR_PIERCER_NOT_FOUND)
    jurisdiction = db.DB.jurisdictions.get(appointment.jurisdiction_id)
    if piercer.status != "ACTIVE":
        E.fail(E.ERR_PIERCER_NOT_CERTIFIED, "The assigned piercer is not ACTIVE")
    common.enforce_certification_gate(piercer, jurisdiction)

    # 4. At most one IN_PROGRESS session per piercer.
    if piercer.assigned_session_count != 0:
        E.fail(E.ERR_PIERCER_SESSION_IN_PROGRESS,
               "The piercer already holds a session IN_PROGRESS")

    with db.atomic_mutation(appointment, piercer):
        appointment.status = "IN_SERVICE"
        # The session factory raises the piercer's assigned_session_count by
        # one and opens the session in service_status IN_PROGRESS.
        session = session_factory(appointment, piercer, jurisdiction, store)
    return appointment, session


def complete_appointment(appointment):
    if appointment.status != "IN_SERVICE":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not IN_SERVICE")

    session = common.active_session_of_appointment(appointment.id)
    if session is None or session.service_status != "IN_PROGRESS":
        E.fail(E.ERR_INVALID_STATE, "The session is not IN_PROGRESS")

    jurisdiction = db.DB.jurisdictions.get(appointment.jurisdiction_id)
    if jurisdiction is not None and jurisdiction.record_retention_years >= 5:
        if not session.aftercare_kit_included:
            E.fail(E.ERR_AFTERCARE_KIT_REQUIRED,
                   "This jurisdiction mandates an aftercare kit")

    piercer = db.DB.piercers.get(appointment.piercer_id)
    with db.atomic_mutation(appointment, piercer, session):
        appointment.status = "COMPLETED"
        if piercer is not None:
            piercer.assigned_session_count = max(
                piercer.assigned_session_count - 1, 0)
        session.service_status = "COMPLETED"
    session.completed_at = db.fmt_instant(db.DB.clock)
    session.net_fee_cents, _, _ = calc.net_service_fee(
        session.base_fee_cents, session.aftercare_kit_included,
        session.site_pierced, is_re_pierce=False)
    session.follow_up_reminder_due_at = db.fmt_instant(
        db.add_days(db.DB.clock, db.AFTERCARE_FOLLOW_UP_DAYS))
    session.touch()

    lot = db.DB.lots.get(session.cartridge_lot_id) if session.cartridge_lot_id else None
    if lot is not None:
        common.consume_lot_unit(lot)
        common.refresh_lot_availability(lot)

    _ensure_healing_outcome(session)
    return appointment


def _ensure_healing_outcome(session):
    existing = common.latest_outcome_of_session(session.id)
    if existing is not None:
        return existing
    outcome = db.HealingOutcome()
    outcome.session_id = session.id
    outcome.assessed_at = db.fmt_instant(db.DB.clock)
    outcome.healing_result = "PENDING_ASSESSMENT"
    outcome.downgrade_credited_cents = 0
    outcome.re_pierce_eligible = False
    outcome.re_pierce_claim_count = 0
    outcome.status = "ASSESSED"
    db.DB.outcomes[outcome.id] = outcome
    return outcome


def abort_appointment(appointment):
    if appointment.status != "IN_SERVICE":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not IN_SERVICE")

    session = common.active_session_of_appointment(appointment.id)
    if session is None or session.service_status != "IN_PROGRESS":
        E.fail(E.ERR_INVALID_STATE, "The session is not IN_PROGRESS")

    piercer = db.DB.piercers.get(appointment.piercer_id)
    with db.atomic_mutation(appointment, piercer, session):
        appointment.status = "CANCELLED"
        if piercer is not None:
            piercer.assigned_session_count = max(
                piercer.assigned_session_count - 1, 0)
        # healing_status remains HEALING: an aborted session is never assessed.
        session.service_status = "ABORTED"

    lot = db.DB.lots.get(session.cartridge_lot_id) if session.cartridge_lot_id else None
    if lot is not None:
        lot.units_quarantined += 1
        lot.units_available = calc.cartridge_lot_availability(lot)
        lot.touch()
    return appointment


def reschedule_appointment(appointment, new_start, new_end, data):
    if appointment.status not in ("BOOKED", "CONFIRMED"):
        E.fail(E.ERR_INVALID_STATE, "Appointment is not BOOKED or CONFIRMED")
    if appointment.reschedule_count >= 2:
        E.fail(E.ERR_RESCHEDULE_LIMIT_REACHED,
               "The appointment has already been rescheduled twice")

    if (new_end - new_start).total_seconds() < db.SLOT_MIN_MINUTES * 60:
        E.fail(E.ERR_INVALID_REQUEST,
               "slot_end_at must be at least %d minutes after slot_start_at"
               % db.SLOT_MIN_MINUTES)

    enforce_piercer_adjacency(new_start, new_end, appointment.store_location_id,
                              appointment.piercer_id, exclude_id=appointment.id)
    store = db.DB.stores.get(appointment.store_location_id)
    if store is not None:
        enforce_room_capacity(new_start, new_end, store, exclude_id=appointment.id)

    common.check_expected_version(data, "expected_appointment_version", appointment)

    appointment.slot_start_at = db.fmt_instant(new_start)
    appointment.slot_end_at = db.fmt_instant(new_end)
    appointment.reschedule_count += 1
    appointment.status = "RESCHEDULED"
    appointment.touch()
    return appointment


def cancel_appointment(appointment):
    if appointment.status not in ("BOOKED", "CONFIRMED"):
        E.fail(E.ERR_INVALID_STATE, "Appointment is not BOOKED or CONFIRMED")
    appointment.status = "CANCELLED"
    appointment.touch()
    return appointment