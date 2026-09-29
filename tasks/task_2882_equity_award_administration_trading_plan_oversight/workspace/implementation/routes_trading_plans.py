"""Rule 10b5-1 trading plans and Section 16 transaction reports."""

from flask import Blueprint, request

import auth
import calc
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, COMPLIANCE, PARTICIPANT, PLAN_ADMIN
from errors import ApiError

bp = Blueprint("trading_plans", __name__)

LIST_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR)
ROW_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR, PARTICIPANT)
MAX_MODIFICATIONS = 2


def _equity_plan_for(participant_id):
    """The plan referenced by the participant's grants, else the sole plan row."""
    for grant in services.grants_of_participant(participant_id):
        plan = store.plans.get(grant["plan_id"])
        if plan is not None:
            return plan
    rows = store.sort_default(list(store.plans.values()))
    return rows[0] if rows else None


def _apply_cooling_off(row, participant):
    plan = _equity_plan_for(participant["id"])
    earnings = None
    if plan is not None and plan["next_earnings_release_at"] is not None:
        earnings = clock.parse_instant(plan["next_earnings_release_at"])
    adopted_at = clock.parse_instant(row["adopted_at"])
    days = calc.cooling_off_days(row["insider_status_at_adoption"], adopted_at, earnings)
    row["cooling_off_days"] = days
    row["first_trade_allowed_at"] = clock.fmt_instant(clock.add_days(adopted_at, days))


@bp.route("/trading-plans", methods=["POST"])
def adopt_plan():
    actor = auth.begin(PARTICIPANT, COMPLIANCE)
    body = actor.body
    participant_ref = validate.raw_id(body, "participant_id")
    auth.scope(actor, participant_ref)
    if participant_ref is not None:
        services.participant_or_404(participant_ref)
    participant_id = validate.field_id(body, "participant_id")
    participant = services.participant_or_404(participant_id)
    document_ref = validate.field_str(body, "plan_document_ref")
    first_trade_date = validate.field_date(body, "first_scheduled_trade_date")
    total_shares = validate.field_int(body, "total_shares", minimum=1)
    expected_version = validate.field_int(body, "expected_participant_version")
    if expected_version != participant["version"]:
        raise ApiError("ERR_STALE_PARTICIPANT_VERSION")
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    existing = [
        p for p in store.sort_default(list(store.trading_plans.values()))
        if p["participant_id"] == participant_id
    ]
    if any(p["status"] == "PENDING_COOLING_OFF" for p in existing):
        raise ApiError("ERR_TRADING_PLAN_CONFLICT")
    superseded = next((p for p in existing if p["status"] == "EFFECTIVE"), None)

    row = store.base_row()
    row.update({
        "participant_id": participant_id,
        "plan_document_ref": document_ref,
        "adopted_at": clock.fmt_instant(clock.now()),
        "first_scheduled_trade_date": clock.fmt_date(first_trade_date),
        "total_shares": total_shares,
        "insider_status_at_adoption": participant["insider_status"],
        "cooling_off_days": 0,
        "first_trade_allowed_at": None,
        "status": "PENDING_COOLING_OFF",
        "modification_count": 0,
        "termination_reason": None,
        "superseded_plan_id": None,
    })
    _apply_cooling_off(row, participant)
    if superseded is not None:
        superseded["status"] = "EXPIRED"
        superseded["termination_reason"] = "SUPERSEDED_BY_NEW_ADOPTION"
        store.touch(superseded)
        row["superseded_plan_id"] = superseded["id"]
    store.trading_plans[row["id"]] = row
    store.touch(participant)
    return envelope.created(store.public(row))


@bp.route("/trading-plans", methods=["GET"])
def list_plans():
    auth.begin(*LIST_READERS)
    rows = list(store.trading_plans.values())
    for param in ("participant_id", "superseded_plan_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return envelope.page(store.sort_default(rows))


@bp.route("/trading-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    actor = auth.begin(*ROW_READERS)
    row = services.trading_plan_or_404(plan_id)
    auth.scope(actor, row["participant_id"])
    return envelope.ok(store.public(row))


@bp.route("/trading-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    auth.begin(COMPLIANCE)
    row = services.trading_plan_or_404(plan_id)
    if row["status"] != "PENDING_COOLING_OFF":
        raise ApiError("ERR_TRADING_PLAN_INVALID_STATE")
    if clock.now() < clock.parse_instant(row["first_trade_allowed_at"]):
        raise ApiError("ERR_COOLING_OFF_NOT_ELAPSED")
    participant = store.participants[row["participant_id"]]
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    row["status"] = "EFFECTIVE"
    store.touch(row)
    return envelope.ok(store.public(row))


@bp.route("/trading-plans/<plan_id>/modify", methods=["POST"])
def modify_plan(plan_id):
    actor = auth.begin(PARTICIPANT, COMPLIANCE)
    row = services.trading_plan_or_404(plan_id)
    auth.scope(actor, row["participant_id"])
    first_trade_date = validate.field_date(actor.body, "first_scheduled_trade_date")
    total_shares = validate.field_int(actor.body, "total_shares", minimum=1)
    if row["status"] != "EFFECTIVE":
        raise ApiError("ERR_TRADING_PLAN_INVALID_STATE")
    if row["modification_count"] >= MAX_MODIFICATIONS:
        raise ApiError("ERR_MAX_MODIFICATIONS_EXCEEDED")
    participant = store.participants[row["participant_id"]]
    row["status"] = "PENDING_COOLING_OFF"
    row["first_scheduled_trade_date"] = clock.fmt_date(first_trade_date)
    row["total_shares"] = total_shares
    row["modification_count"] += 1
    row["adopted_at"] = clock.fmt_instant(clock.now())
    row["insider_status_at_adoption"] = participant["insider_status"]
    _apply_cooling_off(row, participant)
    store.touch(row)
    return envelope.ok(store.public(row))


@bp.route("/trading-plans/<plan_id>/terminate", methods=["POST"])
def terminate_plan(plan_id):
    actor = auth.begin(PARTICIPANT, COMPLIANCE)
    row = services.trading_plan_or_404(plan_id)
    auth.scope(actor, row["participant_id"])
    reason = validate.field_str(actor.body, "termination_reason")
    if row["status"] not in ("PENDING_COOLING_OFF", "EFFECTIVE"):
        raise ApiError("ERR_TRADING_PLAN_INVALID_STATE")
    row["status"] = "TERMINATED"
    row["termination_reason"] = reason
    store.touch(row)
    return envelope.ok(store.public(row))


# --- Section 16 transaction reports -----------------------------------------

@bp.route("/transaction-reports/<report_id>", methods=["GET"])
def read_report(report_id):
    actor = auth.begin(*ROW_READERS)
    row = services.report_or_404(report_id)
    auth.scope(actor, row["participant_id"])
    return envelope.ok(store.public(row))


@bp.route("/transaction-reports/<report_id>/file", methods=["POST"])
def file_report(report_id):
    actor = auth.begin(COMPLIANCE)
    row = services.report_or_404(report_id)
    if row["status"] != "PENDING":
        raise ApiError("ERR_REPORT_INVALID_STATE")
    if actor.user_id == row["participant_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    now = clock.now()
    row["filed_at"] = clock.fmt_instant(now)
    row["status"] = "FILED" if now <= clock.parse_instant(row["due_at"]) else "LATE_FILED"
    store.touch(row)
    return envelope.ok(store.public(row))
