"""Performance cycles and the certification cascade."""

from flask import Blueprint, request

import auth
import calc
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, BOARD, COMPLIANCE, DELEGATED, PLAN_ADMIN
from errors import ApiError

bp = Blueprint("cycles", __name__)

CYCLE_READERS = (PLAN_ADMIN, BOARD, DELEGATED, COMPLIANCE, AUDITOR)


@bp.route("/performance-cycles", methods=["POST"])
def open_cycle():
    actor = auth.begin(PLAN_ADMIN)
    body = actor.body
    plan_ref = validate.raw_id(body, "plan_id")
    if plan_ref is not None:
        services.plan_or_404(plan_ref)
    plan_id = validate.field_id(body, "plan_id")
    plan = services.plan_or_404(plan_id)
    metric_code = validate.field_str(body, "metric_code")
    target_value = validate.field_number(body, "target_value", greater_than=0)
    due_date = validate.field_date(body, "certification_due_date")
    services.require_plan_active(plan)
    for other in store.cycles.values():
        if (other["plan_id"] == plan_id and other["metric_code"] == metric_code
                and other["status"] != "CANCELLED"):
            raise ApiError("ERR_DUPLICATE_METRIC_CODE")
    row = store.base_row()
    row.update({
        "plan_id": plan_id,
        "metric_code": metric_code,
        "target_value": target_value,
        "certification_due_date": clock.fmt_date(due_date),
        "actual_value": None,
        "payout_multiplier_bps": None,
        "status": "OPEN",
        "certified_at": None,
        "certified_by_user_id": None,
        "created_by_user_id": actor.user_id,
    })
    store.cycles[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/performance-cycles/<cycle_id>", methods=["GET"])
def read_cycle(cycle_id):
    auth.begin(*CYCLE_READERS)
    return envelope.ok(store.public(services.cycle_or_404(cycle_id)))


@bp.route("/equity-plans/<plan_id>/performance-cycles", methods=["GET"])
def list_cycles(plan_id):
    auth.begin(*CYCLE_READERS)
    services.plan_or_404(plan_id)
    rows = [c for c in store.cycles.values() if c["plan_id"] == plan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    metric_code = request.args.get("metric_code")
    if metric_code is not None:
        rows = [r for r in rows if r["metric_code"] == metric_code]
    return envelope.page(store.sort_default(rows))


def _bound_unvested(cycle_id):
    rows = [
        t for t in store.tranches.values()
        if t["performance_cycle_id"] == cycle_id and t["status"] == "UNVESTED"
    ]
    return sorted(rows, key=lambda t: (t["grant_id"], t["tranche_index"], t["_seq"]))


@bp.route("/performance-cycles/<cycle_id>/certify", methods=["POST"])
def certify_cycle(cycle_id):
    actor = auth.begin(BOARD, COMPLIANCE)
    cycle = services.cycle_or_404(cycle_id)
    actual_value = validate.field_number(actor.body, "actual_value")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_INVALID_STATE")
    plan = services.plan_or_404(cycle["plan_id"])
    services.require_plan_active(plan)
    if actor.user_id == cycle["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    multiplier = calc.payout_multiplier_bps(actual_value, cycle["target_value"])
    tranche_rows = _bound_unvested(cycle_id)

    if multiplier > 0:
        _certified_branch(cycle, plan, actor, actual_value, multiplier, tranche_rows)
    else:
        _cancelled_branch(cycle, actual_value, tranche_rows)
    store.touch(cycle)
    return envelope.ok(store.public(cycle))


def _projected_weight(grant, plan, prospective):
    """Weighted reserve the grant would carry once the new tranche counts land."""
    committed = 0
    for tranche in services.tranches_of(grant["id"]):
        if tranche["status"] not in calc.COMMITTED_TRANCHE_STATUSES:
            continue
        committed += prospective.get(tranche["id"], tranche["shares"])
    return calc.fungible_weighted_shares(
        grant["award_type"], committed, plan["fungible_ratio_full_value_bps"])


def _certified_branch(cycle, plan, actor, actual_value, multiplier, tranche_rows):
    prospective = {}
    for tranche in tranche_rows:
        prospective[tranche["id"]] = calc.performance_tranche_shares(
            tranche["target_shares"], multiplier)

    affected = {}
    for tranche in tranche_rows:
        affected.setdefault(tranche["grant_id"], store.grants[tranche["grant_id"]])
    deltas = {}
    plan_delta = {}
    for grant_id, grant in affected.items():
        owning_plan = services.plan_of_grant(grant)
        projected = _projected_weight(grant, owning_plan, prospective)
        delta = projected - grant["weighted_reserve_shares"]
        deltas[grant_id] = delta
        plan_delta[owning_plan["id"]] = plan_delta.get(owning_plan["id"], 0) + delta
    for plan_id, delta in plan_delta.items():
        owning_plan = store.plans[plan_id]
        if owning_plan["available_reserve_shares"] - delta < 0:
            raise ApiError("ERR_RESERVE_INSUFFICIENT")

    cycle["status"] = "CERTIFIED"
    cycle["actual_value"] = actual_value
    cycle["payout_multiplier_bps"] = multiplier
    cycle["certified_at"] = clock.fmt_instant(clock.now())
    cycle["certified_by_user_id"] = actor.user_id
    # Hop 1.
    for tranche in tranche_rows:
        tranche["shares"] = prospective[tranche["id"]]
        store.touch(tranche)
    # Hop 2.
    for grant_id, grant in affected.items():
        services.recompute_grant_shares(grant, services.plan_of_grant(grant))
        store.touch(grant)
    # Hop 3.
    for plan_id, delta in plan_delta.items():
        owning_plan = store.plans[plan_id]
        services.apply_weight_delta(owning_plan, delta)
        services.recompute_reserve(owning_plan)
        services.recompute_burn_rates(owning_plan)
        store.touch(owning_plan)


def _cancelled_branch(cycle, actual_value, tranche_rows):
    cycle["status"] = "CANCELLED"
    cycle["actual_value"] = actual_value
    cycle["payout_multiplier_bps"] = 0
    cycle["certified_at"] = clock.fmt_instant(clock.now())
    affected = {}
    for tranche in tranche_rows:
        affected.setdefault(tranche["grant_id"], store.grants[tranche["grant_id"]])
        tranche["status"] = "FORFEITED"
        tranche["shares"] = 0
        store.touch(tranche)
    decreases = {}
    for grant_id, grant in affected.items():
        owning_plan = services.plan_of_grant(grant)
        delta = services.recompute_grant_shares(grant, owning_plan)
        destination = services.forfeiture_grant_status(
            grant, services.tranches_of(grant_id))
        if destination is not None:
            grant["status"] = destination
            if destination == "FORFEITED":
                grant["weighted_reserve_shares"] = 0
                grant["outstanding_shares"] = 0
        if delta < 0:
            decreases[owning_plan["id"]] = decreases.get(owning_plan["id"], 0) + (-delta)
        store.touch(grant)
    for plan_id, decrease in decreases.items():
        owning_plan = store.plans[plan_id]
        owning_plan["shares_returned_cumulative"] += decrease
        owning_plan["fiscal_year_returned_shares"] += decrease
        services.recompute_reserve(owning_plan)
        services.recompute_burn_rates(owning_plan)
        store.touch(owning_plan)
