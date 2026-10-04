"""Operator contracts: create, fetch, governance transitions, performance
preview (PROVISIONAL), period close (FINAL snapshot), snapshot listing."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_PERIOD_NOT_CLOSABLE,
)
from helpers import (
    get_body,
    check_unknown,
    as_str,
    as_enum,
    pagination_params,
    paginate,
    date_obj,
)
import domain
import serializers

bp = Blueprint("operator_contracts", __name__)

CONTRACT_ACTIONS = ["probate", "reinstate", "terminate"]


def get_contract_or_404(contract_id):
    k = STORE.operator_contracts.get(contract_id)
    if k is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Operator contract not found")
    return k


@bp.route("/jc/operator-contracts", methods=["POST"])
def create_contract():
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    body = get_body()
    check_unknown(body, {"center_id", "operator_name", "contract_code"})
    center_id = as_str(body, "center_id", required=True)
    operator_name = as_str(body, "operator_name", required=True)
    contract_code = as_str(body, "contract_code", required=True)
    if center_id not in STORE.centers:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Center not found")
    if any(k["contract_code"] == contract_code for k in STORE.operator_contracts.values()):
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "contract_code must be unique across all contracts",
        )
    rec = new_record()
    rec.update(
        {
            "center_id": center_id,
            "operator_name": operator_name,
            "contract_code": contract_code,
            "status": "ACTIVE",
            "current_period_start": STORE.clock_date_str(),
            "period_sequence": 1,
        }
    )
    STORE.operator_contracts[rec["id"]] = rec
    return ok_object(serializers.contract_view(rec), status=201)


@bp.route("/jc/operator-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    return ok_object(serializers.contract_view(get_contract_or_404(contract_id)))


@bp.route("/jc/operator-contracts/<contract_id>/transition", methods=["POST"])
def contract_transition(contract_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    k = get_contract_or_404(contract_id)
    body = get_body()
    check_unknown(body, {"action"})
    action = as_enum(body, "action", CONTRACT_ACTIONS, required=True)
    if k["status"] == "TERMINATED":
        raise ApiError(
            ERR_ALREADY_TERMINAL[0],
            ERR_ALREADY_TERMINAL[1],
            "Operator contract is TERMINATED",
        )
    status = k["status"]
    if action == "probate":
        if status != "ACTIVE":
            _invalid_state(action, status)
        k["status"] = "PROBATION"
    elif action == "reinstate":
        if status != "PROBATION":
            _invalid_state(action, status)
        k["status"] = "ACTIVE"
    elif action == "terminate":
        if status not in ("ACTIVE", "PROBATION"):
            _invalid_state(action, status)
        k["status"] = "TERMINATED"
    bump(k)
    return ok_object(serializers.contract_view(k), status=200)


@bp.route("/jc/operator-contracts/<contract_id>/performance-preview", methods=["GET"])
def performance_preview(contract_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    k = get_contract_or_404(contract_id)
    calc = domain.performance_calc(k, "PROVISIONAL")
    data = {
        "variant": "PROVISIONAL",
        "period_start": calc["period_start"],
        "period_end": calc["period_end"],
        "graduates_count": calc["graduates_count"],
        "leavers_count": calc["leavers_count"],
        "projected_actives_count": calc["projected_actives_count"],
        "graduation_rate": float(calc["graduation_rate"]),
        "placement_rate": float(calc["placement_rate"]),
        "avg_starting_wage_cents": calc["avg_starting_wage_cents"],
        "payment_cents": calc["payment_cents"],
    }
    return ok_object(data, status=200)


@bp.route("/jc/operator-contracts/<contract_id>/close-period", methods=["POST"])
def close_period(contract_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    k = get_contract_or_404(contract_id)
    if request_body_present():
        body = get_body()
        check_unknown(body, set())
    # Priority 25: the period must be closable.
    today = STORE.clock_date_str()
    if not (today > k["current_period_start"]) or k["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError(
            ERR_PERIOD_NOT_CLOSABLE[0],
            ERR_PERIOD_NOT_CLOSABLE[1],
            "The review period is not closable",
        )
    calc = domain.performance_calc(k, "FINAL")
    snap = {
        "id": STORE.new_id(),
        "created_at": STORE.tick(),
        "contract_id": k["id"],
        "variant": "FINAL",
        "period_start": calc["period_start"],
        "period_end": calc["period_end"],
        "graduates_count": calc["graduates_count"],
        "leavers_count": calc["leavers_count"],
        "graduation_rate": calc["graduation_rate"],
        "placement_rate": calc["placement_rate"],
        "avg_starting_wage_cents": calc["avg_starting_wage_cents"],
        "payment_cents": calc["payment_cents"],
    }
    STORE.performance_snapshots[snap["id"]] = snap
    # Advance the period window: next start = period_end + 1 day.
    k["current_period_start"] = (
        date_obj(calc["period_end"]) + timedelta(days=1)
    ).isoformat()
    k["period_sequence"] += 1
    # Automatic governance transitions against the floors.
    failing = calc["graduation_rate"] < domain.GRADUATION_RATE_FLOOR or (
        calc["graduates_count"] > 0
        and calc["placement_rate"] < domain.PLACEMENT_RATE_FLOOR
    )
    if failing:
        k["status"] = "PROBATION"
    elif k["status"] == "PROBATION":
        k["status"] = "ACTIVE"
    bump(k)
    return ok_object(serializers.snapshot_view(snap), status=201)


def request_body_present():
    from flask import request

    return bool(request.data)


@bp.route("/jc/operator-contracts/<contract_id>/performance-snapshots", methods=["GET"])
def list_snapshots(contract_id):
    user_id, role = authenticate()
    require_role(role, {"OperatorAdmin"})
    k = get_contract_or_404(contract_id)
    limit, offset = pagination_params()
    items = [s for s in STORE.performance_snapshots.values() if s["contract_id"] == k["id"]]
    items.sort(key=lambda s: s["created_at"])
    page, meta = paginate([serializers.snapshot_view(s) for s in items], limit, offset)
    return ok_list(page, meta)


def _invalid_state(action, status):
    raise ApiError(
        ERR_INVALID_STATE[0],
        ERR_INVALID_STATE[1],
        "Action {} is not defined from state {}".format(action, status),
    )
