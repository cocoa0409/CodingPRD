"""Illegal-traffic notices and the downstream blocking obligation (PRD 3.8)."""
import datetime

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

bp = Blueprint("notices", __name__)

STATES = ("NOTIFIED", "UNDER_INVESTIGATION", "MITIGATED",
          "ALL_TRAFFIC_BLOCKED", "EXPIRED_UNMITIGATED")
MITIGATION_ACTIONS = ("CUSTOMER_TERMINATED", "NUMBERS_REVOKED",
                      "TRAFFIC_BLOCKED")
MITIGATION_WINDOW_HOURS = 48

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.FRAUD_ANALYST,
              auth.PROVIDER_ADMIN)


def load_notice(notice_id):
    row = db.notices.get(notice_id)
    if row is None:
        errors.fail(errors.ERR_NOTICE_NOT_FOUND,
                    "No illegal-traffic notice with id %s" % notice_id)
    return row


def _closed(message):
    errors.fail(errors.ERR_NOTICE_ALREADY_CLOSED, message)


@bp.route("/rmd/illegal-traffic-notices", methods=["POST"])
@auth.require(auth.REGULATOR)
def serve_notice():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    calling_number = valid.req_str(data, "calling_number")
    description = valid.req_str(data, "description")
    valid.check_e164(calling_number)
    load_provider(provider_id)

    notified_at = db.now()
    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "calling_number": calling_number,
        "description": description,
        "notified_at": notified_at,
        "mitigation_deadline_at": notified_at + datetime.timedelta(
            hours=MITIGATION_WINDOW_HOURS),
        "state": "NOTIFIED",
        "customer_id": None,
        "mitigation_action": None,
        "resolved_at": None,
        "penalty_points_assessed": 0,
    })
    db.notices[row["id"]] = row
    derive.recompute_provider_by_id(provider_id)
    return envelope.created(ser.notice(row))


@bp.route("/rmd/illegal-traffic-notices/<notice_id>/investigate",
          methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def investigate_notice(notice_id):
    data = valid.body()
    customer_id = valid.req_str(data, "customer_id")
    row = load_notice(notice_id)
    customer = load_customer(customer_id)
    if row["state"] != "NOTIFIED":
        _closed("Only a NOTIFIED notice can be investigated")
    if customer["provider_id"] != row["provider_id"]:
        errors.fail(errors.ERR_CUSTOMER_PROVIDER_MISMATCH,
                    "The customer belongs to another provider")

    row["state"] = "UNDER_INVESTIGATION"
    row["customer_id"] = customer_id
    touch(row)
    return envelope.ok(ser.notice(row))


@bp.route("/rmd/illegal-traffic-notices/<notice_id>/mitigate",
          methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def mitigate_notice(notice_id):
    data = valid.body()
    action = valid.req_enum(data, "mitigation_action", MITIGATION_ACTIONS)
    row = load_notice(notice_id)
    if row["state"] != "UNDER_INVESTIGATION" or row["customer_id"] is None:
        _closed("Only an attributed notice UNDER_INVESTIGATION can be "
                "mitigated")

    customer = db.customers.get(row["customer_id"])
    row["mitigation_action"] = action
    row["resolved_at"] = db.now()
    row["state"] = ("ALL_TRAFFIC_BLOCKED" if action == "TRAFFIC_BLOCKED"
                    else "MITIGATED")
    touch(row)

    if customer is not None:
        if action == "CUSTOMER_TERMINATED":
            derive.terminate_customer(customer)
        elif action == "NUMBERS_REVOKED":
            derive.cascade_revoke_assignments(
                customer, only_number=row["calling_number"])
        elif customer["origination_state"] == "ENABLED":
            derive.suspend_customer(customer, "PROVIDER_REQUEST", row["id"])
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.notice(row))


@bp.route("/rmd/illegal-traffic-notices/<notice_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_notice(notice_id):
    row = load_notice(notice_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.notice(row))


@bp.route("/rmd/illegal-traffic-notices", methods=["GET"])
@auth.require(*READ_ROLES)
def list_notices():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    customer_id = valid.arg_str("customer_id")
    state = valid.arg_enum("state", STATES)

    rows = auth.scope_rows(db.notices.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return envelope.collection(rows, ser.notice, limit, offset)
