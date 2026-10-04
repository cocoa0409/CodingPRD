"""Appointment, screening and session routes (PRD 3.3, 3.4, 3.5)."""

from flask import Blueprint, request

import db
import errors as E
import response as R
from middleware import authenticated, acting_user_id
from services import common
from services import appointment as appt_svc
from services import session as session_svc

bp = Blueprint("appointments", __name__)


# =============================================================================
# Appointments
# =============================================================================
@bp.route("/appointments", methods=["POST"])
@authenticated("IntakeAssociate")
def create_appointment():
    data = common.body()
    store = common.get_store(common.require_str(data, "store_location_id"))
    customer = common.get_customer(common.require_str(data, "customer_id"))
    piercer = common.get_piercer(common.require_str(data, "piercer_id"))
    jurisdiction = common.get_jurisdiction(common.require_str(data, "jurisdiction_id"))
    intake_type = common.require_enum(data, "intake_type", ("SCHEDULED", "WALK_IN"))
    site_requested = common.require_enum(data, "site_requested", db.ALLOWED_SITES)
    start_at = common.require_instant(data, "slot_start_at")
    end_at = common.require_instant(data, "slot_end_at")

    appointment = appt_svc.book_appointment(
        store, customer, piercer, jurisdiction, intake_type, site_requested,
        start_at, end_at)
    return R.object_response(appointment, 201)


@bp.route("/appointments", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_appointments():
    limit, offset = common.pagination_params()
    rows = list(db.DB.appointments.values())
    for arg in ("store_location_id", "piercer_id", "customer_id", "jurisdiction_id"):
        requested = request.args.get(arg)
        if requested:
            rows = [row for row in rows if getattr(row, arg) == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/appointments/<appointment_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_appointment(appointment_id):
    return R.object_response(common.get_appointment(appointment_id))


@bp.route("/appointments/<appointment_id>/screenings", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_appointment_screenings(appointment_id):
    common.get_appointment(appointment_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([s for s in db.DB.screenings.values()
                               if s.appointment_id == appointment_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/appointments/<appointment_id>/sessions", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_appointment_sessions(appointment_id):
    common.get_appointment(appointment_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows(common.session_of_appointment(appointment_id))
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/appointments/<appointment_id>/confirm", methods=["POST"])
@authenticated("IntakeAssociate")
def confirm_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    appt_svc.confirm_appointment(appointment)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/check-in", methods=["POST"])
@authenticated("IntakeAssociate")
def check_in_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    appt_svc.check_in_appointment(appointment)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/screen", methods=["POST"])
@authenticated("Piercer")
def screen_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    data = common.body()
    sites = common.validated_list(data, "anatomy_sites_examined", db.ALLOWED_SITES,
                                  optional=True)
    codes = common.validated_list(data, "contraindication_codes",
                                  db.ALLOWED_CONTRAINDICATIONS, optional=True)
    appt_svc.screen_appointment(appointment, acting_user_id(), sites, codes)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/start-service", methods=["POST"])
@authenticated("Piercer")
def start_service(appointment_id):
    appointment = common.get_appointment(appointment_id)

    def factory(appt, piercer, jurisdiction, store):
        # The implicit session opened by start-of-service takes no body
        # (scaffold §1.5: start-service input is empty), so it supplies the
        # mandatory aftercare kit required by PRD 3.5 whenever the jurisdiction
        # mandates one (record_retention_years >= 5).
        mandated_kit = jurisdiction is not None and jurisdiction.record_retention_years >= 5
        return session_svc.create_session(
            appt, piercer, jurisdiction, store,
            aftercare_kit_included=mandated_kit,
        )

    appt_svc.start_service(appointment, factory)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/refuse", methods=["POST"])
@authenticated("Piercer")
def refuse_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    data = common.body()
    refusal_reason_code = common.require_str(data, "refusal_reason_code")
    appt_svc.refuse_appointment(appointment, refusal_reason_code)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/complete", methods=["POST"])
@authenticated("Piercer")
def complete_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    appt_svc.complete_appointment(appointment)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/abort", methods=["POST"])
@authenticated("Piercer")
def abort_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    appt_svc.abort_appointment(appointment)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/reschedule", methods=["POST"])
@authenticated("IntakeAssociate")
def reschedule_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    data = common.body()
    new_start = common.require_instant(data, "new_slot_start_at")
    new_end = common.require_instant(data, "new_slot_end_at")
    appt_svc.reschedule_appointment(appointment, new_start, new_end, data)
    return R.object_response(appointment)


@bp.route("/appointments/<appointment_id>/cancel", methods=["POST"])
@authenticated("IntakeAssociate")
def cancel_appointment(appointment_id):
    appointment = common.get_appointment(appointment_id)
    appt_svc.cancel_appointment(appointment)
    return R.object_response(appointment)


# =============================================================================
# Screenings
# =============================================================================
@bp.route("/screenings", methods=["POST"])
@authenticated("Piercer")
def create_screening():
    data = common.body()
    appointment = common.get_appointment(common.require_str(data, "appointment_id"))
    piercer = common.get_piercer(common.require_str(data, "piercer_id"))
    sites = common.validated_list(data, "anatomy_sites_examined", db.ALLOWED_SITES,
                                  optional=True)
    codes = common.validated_list(data, "contraindication_codes",
                                  db.ALLOWED_CONTRAINDICATIONS, optional=True)
    common.check_expected_version(data, "expected_appointment_version", appointment)

    screening = appt_svc.create_screening(appointment, piercer.id, sites, codes)
    return R.object_response(screening, 201)


@bp.route("/screenings", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_screenings():
    limit, offset = common.pagination_params()
    rows = list(db.DB.screenings.values())
    for arg in ("appointment_id", "piercer_id"):
        requested = request.args.get(arg)
        if requested:
            rows = [row for row in rows if getattr(row, arg) == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/screenings/<screening_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_screening(screening_id):
    return R.object_response(common.get_screening(screening_id))


@bp.route("/screenings/<screening_id>/evaluate", methods=["POST"])
@authenticated("Piercer")
def evaluate_screening(screening_id):
    screening = common.get_screening(screening_id)
    appt_svc.evaluate_screening(screening)
    return R.object_response(screening)


@bp.route("/screenings/<screening_id>/override", methods=["POST"])
@authenticated("ComplianceOfficer")
def override_screening(screening_id):
    screening = common.get_screening(screening_id)
    data = common.body()
    clearance_ref = data.get("medical_clearance_ref")
    override_outcome = common.optional_enum(
        data, "override_outcome", ("CLEARED", "REFUSED"))
    appt_svc.override_screening(screening, clearance_ref, override_outcome)
    return R.object_response(screening)


@bp.route("/screenings/<screening_id>/escalate", methods=["POST"])
@authenticated("Piercer")
def escalate_screening(screening_id):
    screening = common.get_screening(screening_id)
    appt_svc.escalate_screening(screening)
    return R.object_response(screening)


# =============================================================================
# Piercing sessions
# =============================================================================
@bp.route("/sessions", methods=["POST"])
@authenticated("Piercer")
def create_session():
    data = common.body()
    appointment = common.get_appointment(common.require_str(data, "appointment_id"))
    piercer = common.get_piercer(common.require_str(data, "piercer_id"))
    jurisdiction = db.DB.jurisdictions.get(appointment.jurisdiction_id)
    store = common.get_store(appointment.store_location_id)
    customer = db.DB.customers.get(appointment.customer_id)

    if appointment.status != "SCREENED":
        E.fail(E.ERR_INVALID_STATE, "Appointment is not SCREENED")

    # Business safety: the age gate is evaluated before other business rules.
    if customer is not None and jurisdiction is not None:
        common.enforce_age_gate(customer, jurisdiction, None)
        common.enforce_consent_class_for_minor(customer, jurisdiction)

    # Opening a session begins the service, so the same governing-screening
    # gate that guards start-service applies here first (PRD 3.4).
    governing = db.DB.screenings.get(appointment.governing_screening_id) \
        if appointment.governing_screening_id else None
    if governing is None or governing.outcome != "CLEARED":
        E.fail(E.ERR_SCREENING_NOT_CLEARED,
               "The governing screening does not resolve to CLEARED")

    lot_id = data.get("cartridge_lot_id")
    if lot_id is not None and not isinstance(lot_id, str):
        E.fail(E.ERR_INVALID_REQUEST, "cartridge_lot_id must be a string")

    base_fee_cents = common.require_int(data, "base_fee_cents")
    aftercare_kit_included = common.require_bool(data, "aftercare_kit_included")
    site_pierced = common.optional_enum(data, "site_pierced", db.ALLOWED_SITES)

    # A jurisdiction mandates the aftercare kit when its record_retention_years
    # is at least 5 (PRD 3.5); a missing mandatory kit is refused at HTTP 422.
    if jurisdiction is not None and jurisdiction.record_retention_years >= 5 \
            and not aftercare_kit_included:
        E.fail(E.ERR_AFTERCARE_KIT_REQUIRED,
               "This jurisdiction mandates an aftercare kit")

    with db.atomic_mutation(appointment, piercer):
        session = session_svc.create_session(
            appointment, piercer, jurisdiction, store,
            cartridge_lot_id=lot_id, site_pierced=site_pierced,
            base_fee_cents=base_fee_cents,
            aftercare_kit_included=aftercare_kit_included,
            solution_lot_number=data.get("solution_lot_number"))
        appointment.status = "IN_SERVICE"
    return R.object_response(session, 201)


@bp.route("/sessions/fee-quote", methods=["POST"])
@authenticated("IntakeAssociate", "Piercer")
def fee_quote():
    quote = session_svc.fee_quote(common.body())
    return R.success(quote, "object", 200)


@bp.route("/sessions", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_sessions():
    limit, offset = common.pagination_params()
    rows = list(db.DB.sessions.values())
    for arg in ("appointment_id", "piercer_id", "cartridge_lot_id"):
        requested = request.args.get(arg)
        if requested:
            rows = [row for row in rows if getattr(row, arg) == requested]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/sessions/<session_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_session(session_id):
    return R.object_response(common.get_session(session_id))


@bp.route("/sessions/<session_id>/incidents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_session_incidents(session_id):
    common.get_session(session_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows(common.incidents_of_session(session_id))
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/sessions/<session_id>/healing-outcomes", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_session_outcomes(session_id):
    common.get_session(session_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([o for o in db.DB.outcomes.values()
                               if o.session_id == session_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/sessions/<session_id>/healing-assessment", methods=["POST"])
@authenticated("Piercer")
def healing_assessment(session_id):
    session = common.get_session(session_id)
    data = common.body()
    assessed_at = common.require_instant(data, "assessed_at")
    failure_codes = common.validated_list(data, "failure_codes",
                                          db.ALLOWED_REACTIONS, optional=True)
    session_svc.healing_assessment(session, assessed_at, failure_codes)
    return R.object_response(session)


@bp.route("/sessions/<session_id>/re-pierce", methods=["POST"])
@authenticated("Piercer")
def re_pierce(session_id):
    session = common.get_session(session_id)
    session_svc.re_pierce(session)
    return R.object_response(session)


@bp.route("/sessions/<session_id>/downgrade", methods=["POST"])
@authenticated("Piercer")
def downgrade_session(session_id):
    session = common.get_session(session_id)
    data = common.body()
    sites = common.validated_list(data, "downgraded_sites", db.ALLOWED_SITES)
    session_svc.downgrade_session(session, sites)
    return R.object_response(session)


@bp.route("/sessions/<session_id>/follow-up/acknowledge", methods=["POST"])
@authenticated("Customer")
def acknowledge_follow_up(session_id):
    session = common.get_session(session_id)
    session_svc.acknowledge_follow_up(session, acting_user_id())
    return R.object_response(session)