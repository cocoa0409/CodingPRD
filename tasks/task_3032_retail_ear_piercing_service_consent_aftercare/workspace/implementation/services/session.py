"""Piercing sessions, healing assessment and the downgrade/re-pierce loop.

Implements PRD 3.5, 3.6 and the session-projection rules of 2.7.
"""

import db
import errors as E
import calculations as calc
from services import common


def _resolve_jurisdiction(appointment_id):
    appointment = db.DB.appointments.get(appointment_id)
    if appointment is None:
        return None, None
    return appointment, db.DB.jurisdictions.get(appointment.jurisdiction_id)


def create_session(appointment, piercer, jurisdiction, store,
                   cartridge_lot_id=None, site_pierced=None, base_fee_cents=0,
                   aftercare_kit_included=False, solution_lot_number=None):
    """POST /sessions plus the implicit session opened by start-service.

    When ``cartridge_lot_id`` is None the lot is chosen by the
    ``store_available_lot`` selector policy (PRD 2.6).
    """
    if common.active_session_of_appointment(appointment.id) is not None:
        E.fail(E.ERR_INVALID_STATE,
               "A session for this appointment is already IN_PROGRESS")

    # Posture gate (PRD 3.5): the store must be able to begin a new service.
    if store.compliance_posture != "OPEN" or store.status == "CLOSED":
        E.fail(E.ERR_STORE_POSTURE_BLOCKS_SERVICE,
               "The store's posture or status blocks service")

    if piercer.status != "ACTIVE":
        E.fail(E.ERR_PIERCER_NOT_CERTIFIED, "The piercer is not ACTIVE")
    common.enforce_certification_gate(piercer, jurisdiction)

    if piercer.assigned_session_count != 0:
        E.fail(E.ERR_PIERCER_SESSION_IN_PROGRESS,
               "The piercer already holds a session IN_PROGRESS")

    site = site_pierced or appointment.site_requested
    if site not in db.ALLOWED_SITES:
        E.fail(E.ERR_INVALID_REQUEST, "site_pierced must be a known anatomical site")

    if cartridge_lot_id:
        lot = common.get_lot(cartridge_lot_id)
        if lot.store_location_id != store.id:
            E.fail(E.ERR_CARTRIDGE_LOT_UNAVAILABLE,
                   "The cartridge lot belongs to another store")
        common.enforce_lot_gate(lot)
    else:
        lot = common.select_store_available_lot(store.id, appointment.site_requested)
        if lot is None:
            E.fail(E.ERR_CARTRIDGE_LOT_UNAVAILABLE,
                   "No available cartridge lot for the requested site")

    session = db.PiercingSession()
    session.appointment_id = appointment.id
    session.piercer_id = piercer.id
    session.cartridge_lot_id = lot.id
    session.site_pierced = site
    session.base_fee_cents = int(base_fee_cents or 0)
    session.aftercare_kit_included = bool(aftercare_kit_included)
    session.solution_lot_number = solution_lot_number
    session.follow_up_acknowledged = False
    session.service_status = "IN_PROGRESS"
    session.healing_status = "HEALING"
    session.net_fee_cents, _, _ = calc.net_service_fee(
        session.base_fee_cents, session.aftercare_kit_included, site,
        is_re_pierce=False)
    db.DB.sessions[session.id] = session

    common.consume_lot_unit(lot)
    common.refresh_lot_availability(lot)

    # Start-of-service already holds the piercer inside an atomic mutation, so
    # this increment rides along with it; opening a session through
    # POST /sessions lands it as its own single increment.
    piercer.assigned_session_count += 1
    piercer.touch()
    return session


def healing_assessment(session, assessed_at, failure_codes):
    """HEALING -> HEALED or FAILED (PRD 3.6)."""
    if session.healing_status != "HEALING":
        E.fail(E.ERR_INVALID_STATE, "Session healing_status is not HEALING")

    completion = session.completed_at
    if completion is None:
        E.fail(E.ERR_INVALID_STATE,
               "The session has not been completed and cannot be assessed")
    completed_instant = db.parse_instant(completion)
    earliest = db.add_days(completed_instant, db.HEALING_ASSESSMENT_MIN_DAYS)

    codes = set(failure_codes or [])
    failed = bool(codes & {"DISCHARGE", "EMBEDDED_BACK", "INFECTION"})

    outcome = common.latest_outcome_of_session(session.id)
    if outcome is None:
        outcome = db.HealingOutcome()
        outcome.session_id = session.id
        outcome.downgrade_credited_cents = 0
        outcome.re_pierce_claim_count = 0
        db.DB.outcomes[outcome.id] = outcome

    outcome.assessed_at = db.fmt_instant(assessed_at)

    if failed:
        session.healing_status = "FAILED"
        session.touch()
        outcome.healing_result = "FAILED"
        outcome.status = "ASSESSED"
        outcome.re_pierce_eligible = outcome.re_pierce_claim_count == 0
        if outcome.re_pierce_eligible:
            outcome.status = "RE_PIERCE_ELIGIBLE"
        outcome.touch()
        common.file_incident(session.id, "MODERATE", sorted(codes))
        return session

    if assessed_at < earliest:
        E.fail(E.ERR_INVALID_STATE,
               "The healing assessment must be dated at least %d days after "
               "completion" % db.HEALING_ASSESSMENT_MIN_DAYS)

    session.healing_status = "HEALED"
    session.touch()
    outcome.healing_result = "HEALED"
    outcome.status = "ASSESSED"
    outcome.touch()
    return session


def re_pierce(session):
    """FAILED -> HEALING under the re-pierce policy (PRD 3.6)."""
    if session.healing_status != "FAILED":
        E.fail(E.ERR_INVALID_STATE, "Session healing_status is not FAILED")

    outcome = common.latest_outcome_of_session(session.id)
    if outcome is None or not outcome.re_pierce_eligible \
            or outcome.re_pierce_claim_count != 0:
        E.fail(E.ERR_RE_PIERCE_NOT_ELIGIBLE,
               "No unconsumed re-pierce entitlement exists for this session")

    lot = db.DB.lots.get(session.cartridge_lot_id) if session.cartridge_lot_id else None
    if lot is not None:
        common.enforce_lot_gate(lot)

    session.healing_status = "HEALING"
    session.net_fee_cents, _, _ = calc.net_service_fee(
        session.base_fee_cents, session.aftercare_kit_included,
        session.site_pierced, is_re_pierce=True)
    session.touch()

    outcome.status = "RE_PIERCED"
    outcome.re_pierce_claim_count = 1
    outcome.re_pierce_eligible = False
    outcome.touch()

    if lot is not None:
        common.consume_lot_unit(lot)
        common.refresh_lot_availability(lot)
    return session


def downgrade_session(session, downgraded_sites):
    """HEALED -> RE_PIERCED with a customer credit (PRD 3.6)."""
    if session.healing_status != "HEALED":
        E.fail(E.ERR_INVALID_STATE, "Session healing_status is not HEALED")

    outcome = common.latest_outcome_of_session(session.id)
    if outcome is None:
        E.fail(E.ERR_HEALING_OUTCOME_NOT_FOUND)

    credit = calc.downgrade_credit_amount(downgraded_sites)
    session.healing_status = "RE_PIERCED"
    session.touch()

    outcome.healing_result = "DOWNGRADED"
    outcome.status = "DOWNGRADED"
    outcome.downgrade_credited_cents = credit
    outcome.touch()

    customer = common.session_owner_customer(session)
    if customer is not None:
        customer.aftercare_credit_cents += credit
        customer.touch()
    return session


def acknowledge_follow_up(session, caller_id):
    """A Customer acknowledges their own session's reminder (PRD 3.6).

    Ownership is resolved before the window gate: the acting caller's
    X-User-ID must be the id of the customer the session belongs to.
    """
    customer = common.session_owner_customer(session)
    if customer is None or customer.id != caller_id:
        E.fail(E.ERR_UNAUTHORIZED_ROLE,
               "A customer may only acknowledge their own session's follow-up")

    # The acknowledgement is idempotent (PRD 3.6 renders no other outcome for an
    # already-acknowledged session): `follow_up_acknowledged` is already true, so
    # the operation succeeds without changing the row again.
    if session.follow_up_acknowledged:
        return session

    due = db.parse_instant(session.follow_up_reminder_due_at)
    if due is None:
        E.fail(E.ERR_FOLLOW_UP_NOT_DUE,
               "The follow-up reminder has not been scheduled")
    window_close = db.add_days(due, 7)
    now = db.DB.clock
    if now < due or now >= window_close:
        E.fail(E.ERR_FOLLOW_UP_NOT_DUE,
               "The follow-up reminder may only be acknowledged inside its window")

    session.follow_up_acknowledged = True
    session.touch()
    return session


def fee_quote(data):
    """POST /sessions/fee-quote: read-only, persists nothing (PRD 3.5)."""
    base_fee_cents = common.require_int(data, "base_fee_cents")
    aftercare_kit_included = common.require_bool(data, "aftercare_kit_included")
    site_pierced = common.require_enum(data, "site_pierced", db.ALLOWED_SITES)
    is_re_pierce = bool(data.get("is_re_pierce", False))
    downgraded_sites = data.get("downgraded_sites") or []
    contradiction_count = data.get("contraindication_count", 1)
    site_count_requested = data.get("site_count_requested", 1)

    net_fee_cents, rate, re_pierce_discount = calc.net_service_fee(
        base_fee_cents, aftercare_kit_included, site_pierced, is_re_pierce)
    credit = calc.downgrade_credit_amount(downgraded_sites)
    surcharge = calc.site_complexity_surcharge(
        base_fee_cents, site_pierced, int(contradiction_count),
        int(site_count_requested))

    return {
        "net_fee_cents": net_fee_cents,
        "discount_rate": rate,
        "re_pierce_discount_cents": re_pierce_discount,
        "downgrade_credited_cents": credit,
        "surcharge_cents": surcharge,
    }