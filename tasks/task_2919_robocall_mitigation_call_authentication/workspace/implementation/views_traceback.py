"""Traceback service and response (PRD 3.8)."""
import datetime
import math

from flask import Blueprint

import auth
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_attest import load_attestation
from views_customer import load_customer
from views_number import any_covering_assignment
from views_provider import load_provider

bp = Blueprint("tracebacks", __name__)

STATES = ("RECEIVED", "RESPONDED", "RESPONDED_LATE", "OVERDUE")
RESPONSE_WINDOW_HOURS = 24
HARD_CUTOFF_HOURS = 72
CLOSED_STATES = ("RESPONDED", "RESPONDED_LATE")

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.PROVIDER_ADMIN)


def load_traceback(traceback_id):
    row = db.tracebacks.get(traceback_id)
    if row is None:
        errors.fail(errors.ERR_TRACEBACK_NOT_FOUND,
                    "No traceback request with id %s" % traceback_id)
    return row


@bp.route("/rmd/traceback-requests", methods=["POST"])
@auth.require(auth.REGULATOR)
def serve_traceback():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    calling_number = valid.req_str(data, "calling_number")
    called_number = valid.req_str(data, "called_number")
    origination_time, raw_time = valid.req_dt(data, "origination_time")
    note = valid.opt_str(data, "upstream_provider_note")
    valid.check_e164(calling_number, called_number)
    load_provider(provider_id)

    received_at = db.now()
    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "calling_number": calling_number,
        "called_number": called_number,
        "origination_time": origination_time,
        "received_at": received_at,
        "response_deadline_at": received_at + datetime.timedelta(
            hours=RESPONSE_WINDOW_HOURS),
        "hard_cutoff_at": received_at + datetime.timedelta(
            hours=HARD_CUTOFF_HOURS),
        "state": "RECEIVED",
        "responded_at": None,
        "identified_customer_id": None,
        "produced_attestation_id": None,
        "upstream_provider_note": note,
        "lateness_seconds": 0,
        "call_detail_complete": False,
    })
    store.remember_raw(row, "origination_time", raw_time)
    db.tracebacks[row["id"]] = row
    return envelope.created(ser.traceback(row))


def _incomplete(message):
    errors.fail(errors.ERR_CALL_DETAIL_INCOMPLETE, message)


def _check_call_detail(row, customer_id, attestation_id):
    if customer_id is None or attestation_id is None:
        _incomplete("Both identified_customer_id and produced_attestation_id "
                    "are required on a traceback response")
    attestation = db.attestations[attestation_id]
    if (attestation["provider_id"] != row["provider_id"]
            or attestation["customer_id"] != customer_id
            or attestation["calling_number"] != row["calling_number"]
            or attestation["called_number"] != row["called_number"]
            or attestation["origination_time"] != row["origination_time"]):
        errors.fail(errors.ERR_CALL_DETAIL_MISMATCH,
                    "The produced attestation does not describe the traced "
                    "call")
    if any_covering_assignment(customer_id, row["calling_number"],
                               row["origination_time"]) is None:
        _incomplete("The identified customer holds no number assignment "
                    "covering the traced calling_number")


@bp.route("/rmd/traceback-requests/<traceback_id>/respond", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def respond_traceback(traceback_id):
    data = valid.body()
    customer_id = valid.opt_str(data, "identified_customer_id")
    attestation_id = valid.opt_str(data, "produced_attestation_id")
    note = valid.opt_str(data, "upstream_provider_note")
    row = load_traceback(traceback_id)
    if customer_id is not None:
        load_customer(customer_id)
    if attestation_id is not None:
        load_attestation(attestation_id)
    if row["state"] in CLOSED_STATES:
        errors.fail(errors.ERR_TRACEBACK_ALREADY_CLOSED,
                    "This traceback request has already been answered")

    now = db.now()
    if now > row["hard_cutoff_at"]:
        errors.fail(errors.ERR_RESPONSE_WINDOW_CLOSED,
                    "The hard cutoff for this traceback has passed")
    _check_call_detail(row, customer_id, attestation_id)

    row["identified_customer_id"] = customer_id
    row["produced_attestation_id"] = attestation_id
    if note is not None:
        row["upstream_provider_note"] = note
    row["responded_at"] = now
    row["call_detail_complete"] = True
    if now <= row["response_deadline_at"]:
        row["state"] = "RESPONDED"
        row["lateness_seconds"] = 0
    else:
        row["state"] = "RESPONDED_LATE"
        delta = (now - row["response_deadline_at"]).total_seconds()
        row["lateness_seconds"] = int(math.ceil(delta))
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.traceback(row))


@bp.route("/rmd/traceback-requests/<traceback_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_traceback(traceback_id):
    row = load_traceback(traceback_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.traceback(row))


@bp.route("/rmd/traceback-requests", methods=["GET"])
@auth.require(*READ_ROLES)
def list_tracebacks():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    customer_id = valid.arg_str("identified_customer_id")
    attestation_id = valid.arg_str("produced_attestation_id")
    state = valid.arg_enum("state", STATES)

    rows = auth.scope_rows(db.tracebacks.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if customer_id is not None:
        rows = [r for r in rows
                if r["identified_customer_id"] == customer_id]
    if attestation_id is not None:
        rows = [r for r in rows
                if r["produced_attestation_id"] == attestation_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    return envelope.collection(rows, ser.traceback, limit, offset)
