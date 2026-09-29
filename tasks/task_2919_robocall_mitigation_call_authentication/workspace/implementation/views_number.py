"""Number inventory and ownership evidence (PRD 3.5)."""
from flask import Blueprint

import auth
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_customer import load_customer
from views_provider import load_provider

bp = Blueprint("assignments", __name__)

OWNERSHIP_EVIDENCE = ("DIRECT_ALLOCATION", "PORTED_IN", "LEASED_FROM_CARRIER",
                      "UNVERIFIED")
STATUSES = ("ACTIVE", "SUSPENDED_BY_CUSTOMER", "REVOKED")
VERIFIED_EVIDENCE = ("DIRECT_ALLOCATION", "PORTED_IN")

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.FRAUD_ANALYST,
              auth.PROVIDER_ADMIN, auth.CALLER)


def load_assignment(assignment_id):
    row = db.assignments.get(assignment_id)
    if row is None:
        errors.fail(errors.ERR_ASSIGNMENT_NOT_FOUND,
                    "No number assignment with id %s" % assignment_id)
    return row


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; a null upper bound is +infinity."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


def covering_assignment(customer_id, number, moment):
    """The ACTIVE assignment whose half-open interval contains moment."""
    rows = store.order_rows(derive.assignments_of_customer(customer_id))
    for row in rows:
        if row["telephone_number"] != number or row["status"] != "ACTIVE":
            continue
        if row["effective_from"] > moment:
            continue
        if row["effective_to"] is not None and moment >= row["effective_to"]:
            continue
        return row
    return None


def any_covering_assignment(customer_id, number, moment):
    """Any non-revoked assignment covering the number at moment (PRD 3.8)."""
    for row in store.order_rows(derive.assignments_of_customer(customer_id)):
        if row["telephone_number"] != number:
            continue
        if row["effective_from"] > moment:
            continue
        if row["effective_to"] is not None and moment >= row["effective_to"]:
            continue
        return row
    return None


@bp.route("/rmd/number-assignments", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def create_assignment():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    customer_id = valid.req_str(data, "customer_id")
    number = valid.req_str(data, "telephone_number")
    evidence = valid.req_enum(data, "ownership_evidence", OWNERSHIP_EVIDENCE)
    effective_from, raw_from = valid.req_dt(data, "effective_from")
    effective_to, raw_to = valid.opt_dt(data, "effective_to")
    valid.check_e164(number)
    if effective_to is not None:
        valid.check_interval(effective_from, effective_to)
    load_provider(provider_id)
    customer = load_customer(customer_id)
    auth.own_provider(provider_id)

    if customer["kyc_state"] != "VERIFIED":
        errors.fail(errors.ERR_CUSTOMER_NOT_KYC_VERIFIED,
                    "The customer's kyc_state is not VERIFIED")
    if customer["origination_state"] != "ENABLED":
        errors.fail(errors.ERR_ORIGINATION_NOT_ENABLED,
                    "The customer's origination_state is not ENABLED")
    for other in db.assignments.values():
        if other["provider_id"] != provider_id:
            continue
        if other["telephone_number"] != number:
            continue
        if other["status"] == "REVOKED":
            continue
        if _overlaps(effective_from, effective_to, other["effective_from"],
                     other["effective_to"]):
            errors.fail(errors.ERR_NUMBER_INTERVAL_OVERLAP,
                        "The occupation interval overlaps an existing "
                        "assignment of this number")
    if customer["provider_id"] != provider_id:
        errors.fail(errors.ERR_CUSTOMER_PROVIDER_MISMATCH,
                    "The customer belongs to another provider")

    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "customer_id": customer_id,
        "telephone_number": number,
        "ownership_evidence": evidence,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
        "revoked_at": None,
    })
    store.remember_raw(row, "effective_from", raw_from)
    store.remember_raw(row, "effective_to", raw_to)
    db.assignments[row["id"]] = row
    derive.recompute_provider_by_id(provider_id)
    return envelope.created(ser.assignment(row))


@bp.route("/rmd/number-assignments/<assignment_id>/revoke", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def revoke_assignment(assignment_id):
    row = load_assignment(assignment_id)
    auth.own_provider(row["provider_id"])
    if row["status"] not in ("ACTIVE", "SUSPENDED_BY_CUSTOMER"):
        errors.fail(errors.ERR_ASSIGNMENT_NOT_ACTIVE,
                    "A REVOKED assignment cannot be revoked again")
    row["status"] = "REVOKED"
    row["revoked_at"] = db.now()
    row["_raw"].pop("revoked_at", None)
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.assignment(row))


@bp.route("/rmd/number-assignments/<assignment_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_assignment(assignment_id):
    row = load_assignment(assignment_id)
    auth.own(provider_id=row["provider_id"], customer_id=row["customer_id"])
    return envelope.ok(ser.assignment(row))


@bp.route("/rmd/number-assignments", methods=["GET"])
@auth.require(*READ_ROLES)
def list_assignments():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    customer_id = valid.arg_str("customer_id")
    number = valid.arg_str("telephone_number")
    status = valid.arg_enum("status", STATUSES)

    rows = auth.scope_rows(db.assignments.values(),
                           provider_of=lambda r: r["provider_id"],
                           customer_of=lambda r: r["customer_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if number is not None:
        rows = [r for r in rows if r["telephone_number"] == number]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.collection(rows, ser.assignment, limit, offset)
