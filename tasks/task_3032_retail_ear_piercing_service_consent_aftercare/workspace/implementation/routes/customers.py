"""Customer routes (PRD 3.1, 3.7, 3.8)."""

from flask import Blueprint

import db
import errors as E
import response as R
from middleware import authenticated
from services import common

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
@authenticated("IntakeAssociate", "Anonymous")
def create_customer():
    data = common.body()
    customer = db.Customer()
    customer.full_name = common.require_str(data, "full_name")
    customer.date_of_birth = db.fmt_instant(common.require_instant(data, "date_of_birth"))
    customer.guardian_name = data.get("guardian_name")
    customer.guardian_contact = data.get("guardian_contact")
    customer.aftercare_credit_cents = 0
    customer.refunded_cents = 0
    customer.retained_cents = 0
    customer.status = "ACTIVE"
    db.DB.customers[customer.id] = customer
    return R.object_response(customer, 201)


@bp.route("/customers", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_customers():
    limit, offset = common.pagination_params()
    rows = common.sorted_rows(db.DB.customers.values())
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/customers/<customer_id>", methods=["GET"])
@authenticated("AnyAuthenticated")
def get_customer(customer_id):
    return R.object_response(common.get_customer(customer_id))


@bp.route("/customers/<customer_id>/consents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_customer_consents(customer_id):
    common.get_customer(customer_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([c for c in db.DB.consents.values()
                               if c.customer_id == customer_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/customers/<customer_id>/appointments", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_customer_appointments(customer_id):
    common.get_customer(customer_id)
    limit, offset = common.pagination_params()
    rows = common.sorted_rows([a for a in db.DB.appointments.values()
                               if a.customer_id == customer_id])
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/customers/<customer_id>/open-incidents", methods=["GET"])
@authenticated("AnyAuthenticated")
def list_customer_open_incidents(customer_id):
    customer = common.get_customer(customer_id)
    limit, offset = common.pagination_params()
    appointments = {a.id for a in db.DB.appointments.values()
                    if a.customer_id == customer.id}
    session_ids = {s.id for s in db.DB.sessions.values()
                   if s.appointment_id in appointments}
    rows = [i for i in db.DB.incidents.values()
            if i.session_id in session_ids
            and i.escalation_status in db.NON_TERMINAL_INCIDENT_STATES]
    rows = common.sorted_rows(rows)
    page, meta = R.paginate(rows, limit, offset)
    return R.success([r.to_dict() for r in page], "array", 200, meta)


@bp.route("/customers/<customer_id>/clear-flag", methods=["POST"])
@authenticated("ComplianceOfficer")
def clear_flag(customer_id):
    customer = common.get_customer(customer_id)
    if customer.status != "FLAGGED":
        E.fail(E.ERR_INVALID_STATE, "Customer is not FLAGGED")

    appointments = {a.id for a in db.DB.appointments.values()
                    if a.customer_id == customer.id}
    sessions = [s for s in db.DB.sessions.values() if s.appointment_id in appointments]
    session_ids = {s.id for s in sessions}
    open_incidents = [i for i in db.DB.incidents.values()
                      if i.session_id in session_ids
                      and i.escalation_status in db.NON_TERMINAL_INCIDENT_STATES]
    if open_incidents:
        E.fail(E.ERR_INVALID_STATE,
               "No incident may remain in LOGGED, TRIAGED, ESCALATED or REOPENED")
    for session in sessions:
        piercer = db.DB.piercers.get(session.piercer_id)
        if piercer is not None and piercer.eligibility_score < 60:
            E.fail(E.ERR_INVALID_STATE,
                   "Every piercer who served this customer must score at least 60")

    customer.status = "ACTIVE"
    customer.touch()
    return R.object_response(customer)


@bp.route("/customers/<customer_id>/close", methods=["POST"])
@authenticated("ComplianceOfficer")
def close_customer(customer_id):
    customer = common.get_customer(customer_id)
    if customer.status == "CLOSED":
        E.fail(E.ERR_INVALID_STATE, "Customer is already CLOSED")

    appointments = [a for a in db.DB.appointments.values()
                    if a.customer_id == customer.id]

    if customer.status == "ACTIVE":
        blocking = [a for a in appointments
                    if a.status in ("BOOKED", "CONFIRMED", "CHECKED_IN",
                                    "SCREENED", "IN_SERVICE")]
        if blocking:
            E.fail(E.ERR_INVALID_STATE,
                   "No appointment may be BOOKED, CONFIRMED, CHECKED_IN, "
                   "SCREENED or IN_SERVICE")
    elif customer.status == "FLAGGED":
        if customer.aftercare_credit_cents != 0:
            E.fail(E.ERR_INVALID_STATE, "aftercare_credit_cents must be 0")
        session_ids = {s.id for s in db.DB.sessions.values()
                       if s.appointment_id in {a.id for a in appointments}}
        pending = [i for i in db.DB.incidents.values()
                   if i.session_id in session_ids and i.refund_status == "PENDING"]
        if pending:
            E.fail(E.ERR_INVALID_STATE,
                   "No incident may have refund_status PENDING")
    else:
        E.fail(E.ERR_INVALID_STATE, "Customer status does not permit closure")

    customer.status = "CLOSED"
    customer.touch()
    return R.object_response(customer)


@bp.route("/customers/<customer_id>/credit-redemptions", methods=["POST"])
@authenticated("IntakeAssociate")
def redeem_credit(customer_id):
    customer = common.get_customer(customer_id)
    data = common.body()
    amount = common.require_int(data, "amount_cents")
    if amount < 0:
        E.fail(E.ERR_INVALID_REQUEST, "amount_cents must not be negative")
    if amount > customer.aftercare_credit_cents:
        E.fail(E.ERR_INSUFFICIENT_AFTERCARE_CREDIT,
               "Redemption exceeds the customer's available aftercare credit")
    customer.aftercare_credit_cents -= amount
    customer.touch()
    return R.object_response(customer)