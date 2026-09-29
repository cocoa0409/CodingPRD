"""Fleet accounts: the periodic reporting declaration and its acceptance.

Declaration periods are INCLUSIVE at both ends, so two periods that merely touch
at an endpoint overlap.
"""

from flask import Blueprint, request

import auth
import calc
import constants as C
import derive
import envelope
import serialize
import services
import util
import validate as V
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("fleet", __name__)

ALL = C.ALL_ROLES
OPEN_WRITE = ["Underwriter", "Broker"]


def _reportable(policy, period_from, period_to):
    rows = []
    for schedule in derive.schedules_of_policy(policy["id"]):
        if schedule["acquisition_source"] != "AUTOMATIC_ACQUISITION":
            continue
        if schedule["reported_declaration_id"] is not None:
            continue
        if schedule["coverage_status"] != "PENDING":
            continue
        if schedule["effective_from"] < period_from or schedule["effective_from"] > period_to:
            continue
        rows.append(schedule)
    rows.sort(key=lambda s: (s["effective_from"], s["created_at"], s["_seq"]))
    return rows


@bp.route("/aviation/fleet-declarations", methods=["POST"])
@auth.endpoint(OPEN_WRITE)
def create_declaration():
    body = V.json_body()
    policy = services.resolve_fk(body, "policy_id", services.get_policy)
    services.scope_policy(policy)

    period_from = V.get_instant(body, "period_from")
    period_to = V.get_instant(body, "period_to")
    V.check_not_after(period_from, period_to, "period_from must be at or before period_to.")

    if policy["status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")

    if period_from < policy["effective_from"]:
        raise ApiError("ERR_DECLARATION_PERIOD_INVALID")
    if not (period_to > period_from):
        raise ApiError("ERR_DECLARATION_PERIOD_INVALID")
    if period_to > policy["effective_to"]:
        raise ApiError("ERR_DECLARATION_PERIOD_INVALID")
    for other in derive.declarations_of_policy(policy["id"]):
        if other["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if other["period_from"] <= period_to and period_from <= other["period_to"]:
            raise ApiError("ERR_DECLARATION_PERIOD_INVALID")

    if not policy["automatic_acquisition_enabled"]:
        raise ApiError("ERR_AUTO_ACQUISITION_DISABLED")

    population = _reportable(policy, period_from, period_to)
    lines_total = 0
    for schedule in population:
        lines_total += calc.declaration_line(schedule["hull_premium_cents"],
                                             schedule["effective_from"],
                                             policy["effective_to"],
                                             policy["term_days"])

    late_flag = util.day_diff(period_to, db.clock) > policy["acquisition_reporting_days"]
    late_loading_cents = calc.late_loading(lines_total) if late_flag else 0

    rec = new_record(db.declarations, {
        "policy_id": policy["id"],
        "period_from": period_from,
        "period_to": period_to,
        "status": "SUBMITTED",
        "declared_count": len(population),
        "declared_premium_cents": lines_total + late_loading_cents,
        "late_flag": late_flag,
        "late_loading_cents": late_loading_cents,
        "reported_schedule_ids": [s["id"] for s in population],
        "rejection_reason": None,
    })
    return envelope.ok(serialize.declaration(rec), 201)


@bp.route("/aviation/fleet-declarations", methods=["GET"])
@auth.endpoint(ALL)
def list_declarations():
    limit, offset = V.pagination()
    late_flag = V.query_bool("late_flag")
    rows = ordered(db.declarations)
    visible = services.visible_policy_ids()
    if visible is not None:
        rows = [r for r in rows if r["policy_id"] in visible]
    rows = V.filter_eq(rows, "policy_id", request.args.get("policy_id"))
    rows = V.filter_eq(rows, "status", request.args.get("status"))
    if late_flag is not None:
        rows = [r for r in rows if r["late_flag"] == late_flag]
    total = len(rows)
    window = V.page(rows, limit, offset)
    return envelope.ok_list(serialize.many(serialize.declaration, window), limit, offset, total)


@bp.route("/aviation/fleet-declarations/<row_id>", methods=["GET"])
@auth.endpoint(ALL)
def read_declaration(row_id):
    rec = services.get_declaration(row_id)
    services.scope_via_policy(rec["policy_id"])
    return envelope.ok(serialize.declaration(rec))


@bp.route("/aviation/fleet-declarations/<row_id>/acceptance", methods=["POST"])
@auth.endpoint(["Underwriter"])
def decide_declaration(row_id):
    rec = services.get_declaration(row_id)
    body = V.json_body()
    decision = V.get_str(body, "decision")
    rejection_reason = V.get_str(body, "rejection_reason", required=False)
    V.check_enum(decision, "decision", ("ACCEPT", "REJECT"))

    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_DECLARATION_NOT_SUBMITTED")

    if decision == "REJECT" and rejection_reason is None:
        raise ApiError("ERR_CONDITIONAL_FIELD_REQUIRED",
                       "rejection_reason is mandatory for a decision of REJECT.")

    if decision == "REJECT":
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = rejection_reason
        touch(rec)
        return envelope.ok(serialize.declaration(rec))

    policy = db.policies[rec["policy_id"]]
    if policy["status"] != "BOUND":
        raise ApiError("ERR_POLICY_NOT_BOUND")

    for schedule_id in rec["reported_schedule_ids"]:
        schedule = db.schedules.get(schedule_id)
        if schedule is None:
            continue
        schedule["reported_declaration_id"] = rec["id"]
        touch(schedule)
        services.activate_schedule(schedule)

    if rec["declared_count"] != 0:
        services.append_transaction(policy["id"], "DECLARATION_PREMIUM",
                                    rec["declared_premium_cents"], rec["period_from"],
                                    "PRO_RATA",
                                    "acceptance of fleet declaration %s" % rec["id"])

    rec["status"] = "ACCEPTED"
    touch(rec)
    touch(policy)
    return envelope.ok(serialize.declaration(rec))
