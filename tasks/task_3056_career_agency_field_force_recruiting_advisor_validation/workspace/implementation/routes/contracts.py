"""EmploymentContract, training allowance and ValidationPeriod endpoints
(§1.5; PRD §3.3, §3.4)."""

from flask import Blueprint, request

from db import db, parse_dt
from errors import err, ERR_INVALID_REQUEST
from middleware import body, required, pagination, page
from response import ok, ok_list
from routes._shared import authed
from services import contracts, serialize

bp = Blueprint("contracts", __name__)
READ = ["Any"]
WRITE = ["ManagingDirector"]


@bp.post("/agency/employment-contracts")
@authed(WRITE)
def create(user_id, role):
    data = body()
    row = contracts.create_contract(data)
    return ok(serialize.contract(row), 201)


@bp.get("/agency/employment-contracts")
@authed(READ)
def list_contracts(user_id, role):
    limit, offset = pagination()
    filters = {
        "advisor_id": request.args.get("advisor_id"),
        "candidate_id": request.args.get("candidate_id"),
        "contract_status": request.args.get("contract_status"),
    }
    items = [c for c in db.contracts.values()
             if all(value is None or c.get(key) == value for key, value in filters.items())]
    selected = page(items, limit, offset)
    return ok_list([serialize.contract(c) for c in selected], limit, offset, len(items))


@bp.get("/agency/employment-contracts/<contract_id>")
@authed(READ)
def get_contract(user_id, role, contract_id):
    return ok(serialize.contract(contracts.get(contract_id)))


@bp.get("/agency/employment-contracts/<contract_id>/validation-periods")
@authed(READ)
def contract_periods(user_id, role, contract_id):
    contracts.get(contract_id)
    limit, offset = pagination()
    status = request.args.get("status")
    items = [p for p in db.validation_periods.values()
             if p["contract_id"] == contract_id
             and (status is None or p["status"] == status)]
    selected = page(items, limit, offset)
    return ok_list([serialize.period(p) for p in selected], limit, offset, len(items))


@bp.post("/agency/training-allowance-draws")
@authed(WRITE)
def draw(user_id, role):
    data = body()
    contract_id = required(data, "contract_id")
    row = contracts.get(contract_id)
    contracts.draw_allowance(row)
    return ok(serialize.contract(row))


@bp.post("/agency/validation-periods")
@authed(WRITE)
def create_period(user_id, role):
    data = body()
    row = contracts.create_period(data)
    return ok(serialize.period(row), 201)


@bp.get("/agency/validation-periods/<period_id>")
@authed(READ)
def get_period(user_id, role, period_id):
    return ok(serialize.period(contracts.get_period(period_id)))


@bp.post("/agency/validation-periods/<period_id>/evaluate")
@authed(WRITE)
def evaluate(user_id, role, period_id):
    row = contracts.get_period(period_id)
    contracts.evaluate_period(row)
    return ok(serialize.period(row))


@bp.post("/agency/validation-periods/<period_id>/extend")
@authed(WRITE)
def extend(user_id, role, period_id):
    row = contracts.get_period(period_id)
    new_end_date = body().get("new_end_date")
    if new_end_date is None:
        raise err(ERR_INVALID_REQUEST, "new_end_date is required")
    contracts.extend_period(row, new_end_date)
    return ok(serialize.period(row))