"""Enforcement exposure: assessment, contest, adjudication, payment
(PRD 3.9)."""
from flask import Blueprint

import auth
import calc
import derive
import envelope
import errors
import ser
import store
import valid
from store import db, touch
from views_provider import load_provider

bp = Blueprint("enforcements", __name__)

BASES = ("LATE_TRACEBACK", "UNMITIGATED_NOTICE", "FALSE_ATTESTATION",
         "UNFILED_PLAN")
ASSESSMENT_BASES = ("PER_VIOLATION", "CONTINUING_DAILY")
STATUSES = ("PROPOSED", "CONTESTED", "SUSTAINED", "DISMISSED", "PAID")
OUTCOMES = ("SUSTAIN", "DISMISS")

READ_ROLES = (auth.REGULATOR, auth.COMPLIANCE_OFFICER, auth.PROVIDER_ADMIN)


def load_action(action_id):
    row = db.enforcements.get(action_id)
    if row is None:
        errors.fail(errors.ERR_ENFORCEMENT_NOT_FOUND,
                    "No enforcement action with id %s" % action_id)
    return row


def _bad_state(message):
    errors.fail(errors.ERR_ENFORCEMENT_STATE_INVALID, message)


@bp.route("/rmd/enforcement-actions", methods=["POST"])
@auth.require(auth.REGULATOR)
def assess_forfeiture():
    data = valid.body()
    provider_id = valid.req_str(data, "provider_id")
    basis = valid.req_enum(data, "basis", BASES)
    violation_count = valid.req_int(data, "violation_count", minimum=1)
    violation_days = valid.req_int(data, "violation_days", minimum=1)
    assessment_basis = valid.req_enum(data, "assessment_basis",
                                      ASSESSMENT_BASES)
    load_provider(provider_id)

    source = derive.score_band_source(provider_id)
    band = source["score_band"] if source is not None else "NONE"
    breakdown = calc.forfeiture(assessment_basis, violation_count,
                                violation_days, band)

    row = store.base_row()
    row.update({
        "provider_id": provider_id,
        "basis": basis,
        "violation_count": violation_count,
        "violation_days": violation_days,
        "assessment_basis": assessment_basis,
        "status": "PROPOSED",
        "contested_at": None,
        "adjudicated_at": None,
        "paid_at": None,
        "paid_amount_cents": None,
    })
    row.update(breakdown)
    db.enforcements[row["id"]] = row
    derive.recompute_provider_by_id(provider_id)
    return envelope.created(ser.enforcement(row))


@bp.route("/rmd/enforcement-actions/<action_id>/contest", methods=["POST"])
@auth.require(auth.COMPLIANCE_OFFICER)
def contest_action(action_id):
    row = load_action(action_id)
    if row["status"] != "PROPOSED":
        _bad_state("Only a PROPOSED action can be contested")
    row["status"] = "CONTESTED"
    row["contested_at"] = db.now()
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.enforcement(row))


@bp.route("/rmd/enforcement-actions/<action_id>/adjudicate", methods=["POST"])
@auth.require(auth.REGULATOR)
def adjudicate_action(action_id):
    data = valid.body()
    outcome = valid.req_enum(data, "outcome", OUTCOMES)
    row = load_action(action_id)
    if row["status"] != "CONTESTED":
        _bad_state("Only a CONTESTED action can be adjudicated")
    row["status"] = "SUSTAINED" if outcome == "SUSTAIN" else "DISMISSED"
    row["adjudicated_at"] = db.now()
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.enforcement(row))


@bp.route("/rmd/enforcement-actions/<action_id>/pay", methods=["POST"])
@auth.require(auth.PROVIDER_ADMIN)
def pay_action(action_id):
    data = valid.body()
    amount = valid.req_int(data, "amount_cents", minimum=0)
    row = load_action(action_id)
    auth.own_provider(row["provider_id"])
    if row["status"] not in ("PROPOSED", "SUSTAINED"):
        _bad_state("Only a PROPOSED or SUSTAINED action can be paid")
    if amount != row["total_forfeiture_cents"]:
        errors.fail(errors.ERR_PAYMENT_AMOUNT_MISMATCH,
                    "amount_cents must equal total_forfeiture_cents exactly")
    row["status"] = "PAID"
    row["paid_at"] = db.now()
    row["paid_amount_cents"] = amount
    touch(row)
    derive.recompute_provider_by_id(row["provider_id"])
    return envelope.ok(ser.enforcement(row))


@bp.route("/rmd/enforcement-actions/<action_id>", methods=["GET"])
@auth.require(*READ_ROLES)
def read_action(action_id):
    row = load_action(action_id)
    auth.own_provider(row["provider_id"])
    return envelope.ok(ser.enforcement(row))


@bp.route("/rmd/enforcement-actions", methods=["GET"])
@auth.require(*READ_ROLES)
def list_actions():
    limit, offset = envelope.pagination()
    provider_id = valid.arg_str("provider_id")
    status = valid.arg_enum("status", STATUSES)

    rows = auth.scope_rows(db.enforcements.values(),
                           provider_of=lambda r: r["provider_id"])
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.collection(rows, ser.enforcement, limit, offset)
