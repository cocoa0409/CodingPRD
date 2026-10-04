"""Loan submission, underwriting, closing and escalation endpoints."""

from flask import Blueprint

import db
import serializers
from services import loans, shared
from routes.helpers import endpoint, ok, listing, query, resolve_pagination

bp = Blueprint("loans_routes", __name__)

BLUEPRINTS = [bp]


# --- Submissions -----------------------------------------------------------
@bp.route("/loan-submissions", methods=["POST"])
@endpoint("POST", "/loan-submissions")
def create_loan_submission(caller, body):
    row = loans.create_loan_submission(caller, body)
    return ok(serializers.loan_submission, row), 201


@bp.route("/loan-submissions", methods=["GET"])
@endpoint("GET", "/loan-submissions")
def list_loan_submissions(caller, body):
    rows = list(db.loan_submissions.values())
    for name, key in (
        ("broker_id", "broker_id"),
        ("status", "status"),
        ("property_state", "property_state"),
        ("pricing_quote_id", "pricing_quote_id"),
        ("comp_plan_id", "comp_plan_id"),
    ):
        value = query(name)
        if value:
            rows = [row for row in rows if row.get(key) == value]
    return listing(serializers.loan_submission, rows)


@bp.route("/loan-submissions/<loan_id>", methods=["GET"])
@endpoint("GET", "/loan-submissions/<loan_id>")
def get_loan_submission(caller, body, loan_id):
    return ok(serializers.loan_submission, shared.get_loan(loan_id))


@bp.route("/loan-submissions/<loan_id>/compensation-election", methods=["POST"])
@endpoint("POST", "/loan-submissions/<loan_id>/compensation-election")
def elect_compensation(caller, body, loan_id):
    return ok(serializers.loan_submission,
              loans.elect_compensation(loan_id, caller, body))


@bp.route("/loan-submissions/<loan_id>/underwrite", methods=["POST"])
@endpoint("POST", "/loan-submissions/<loan_id>/underwrite")
def underwrite_loan(caller, body, loan_id):
    return ok(serializers.loan_submission, loans.underwrite_loan(loan_id, body))


@bp.route("/loan-submissions/<loan_id>/resubmit", methods=["POST"])
@endpoint("POST", "/loan-submissions/<loan_id>/resubmit")
def resubmit_loan(caller, body, loan_id):
    return ok(serializers.loan_submission, loans.resubmit_loan(loan_id, caller, body))


@bp.route("/loan-submissions/<loan_id>/withdraw", methods=["POST"])
@endpoint("POST", "/loan-submissions/<loan_id>/withdraw")
def withdraw_loan(caller, body, loan_id):
    return ok(serializers.loan_submission, loans.withdraw_loan(loan_id, caller))


@bp.route("/loan-submissions/<loan_id>/clear-to-close", methods=["POST"])
@endpoint("POST", "/loan-submissions/<loan_id>/clear-to-close")
def clear_to_close(caller, body, loan_id):
    return ok(serializers.loan_submission, loans.clear_to_close(loan_id))


@bp.route("/loan-submissions/<loan_id>/fund", methods=["POST"])
@endpoint("POST", "/loan-submissions/<loan_id>/fund")
def fund_loan(caller, body, loan_id):
    return ok(serializers.loan_submission, loans.fund_loan(loan_id))


@bp.route("/closing-pipeline", methods=["GET"])
@endpoint("GET", "/closing-pipeline")
def closing_pipeline(caller, body):
    from flask import request
    from response import resolved_paged_object
    broker_id = query("broker_id")
    payload = loans.closing_pipeline(broker_id)
    limit, offset = resolve_pagination(request.args)
    total = payload["escalated_count"] + payload["standard_count"]
    return resolved_paged_object(payload, limit, offset, total)


# --- Underwriting decisions ------------------------------------------------
@bp.route("/underwriting-decisions", methods=["POST"])
@endpoint("POST", "/underwriting-decisions")
def create_underwriting_decision(caller, body):
    row = loans.create_underwriting_decision(caller, body)
    return ok(serializers.underwriting_decision, row), 201


@bp.route("/loan-submissions/<loan_id>/underwriting-decisions", methods=["GET"])
@endpoint("GET", "/loan-submissions/<loan_id>/underwriting-decisions")
def list_loan_decisions(caller, body, loan_id):
    loan = shared.get_loan(loan_id)
    rows = [row for row in db.underwriting_decisions.values()
            if row["loan_submission_id"] == loan["id"]]
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return listing(serializers.underwriting_decision, rows)


@bp.route("/brokers/<broker_id>/underwriting-decisions", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/underwriting-decisions")
def list_broker_decisions(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.underwriting_decisions.values()
            if row["broker_id"] == broker["id"]]
    decision_type = query("decision_type")
    if decision_type:
        rows = [row for row in rows if row["decision_type"] == decision_type]
    return listing(serializers.underwriting_decision, rows)


# --- Turn-time escalations -------------------------------------------------
@bp.route("/loan-submissions/<loan_id>/turn-time-escalations", methods=["GET"])
@endpoint("GET", "/loan-submissions/<loan_id>/turn-time-escalations")
def list_loan_escalations(caller, body, loan_id):
    loan = shared.get_loan(loan_id)
    rows = shared.escalations_for_loan(loan["id"], status=query("status"))
    return listing(serializers.turn_time_escalation, rows)


@bp.route("/brokers/<broker_id>/turn-time-escalations", methods=["GET"])
@endpoint("GET", "/brokers/<broker_id>/turn-time-escalations")
def list_broker_escalations(caller, body, broker_id):
    broker = shared.get_broker(broker_id)
    rows = [row for row in db.turn_time_escalations.values() if row["broker_id"] == broker["id"]]
    status = query("status")
    if status:
        rows = [row for row in rows if row["status"] == status]
    stage = query("stage")
    if stage:
        rows = [row for row in rows if row["stage"] == stage]
    return listing(serializers.turn_time_escalation, rows)


@bp.route("/turn-time-escalations/<escalation_id>/resolve", methods=["POST"])
@endpoint("POST", "/turn-time-escalations/<escalation_id>/resolve")
def resolve_escalation(caller, body, escalation_id):
    return ok(serializers.turn_time_escalation,
              loans.resolve_escalation(escalation_id, body))