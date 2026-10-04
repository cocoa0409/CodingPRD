"""Service contract endpoints: create, reads, activate, uptime
reconciliations."""

from flask import Blueprint, request

from auth import require_roles
from calc import uptime_credit
from envelope import ok, ok_list, sort_items
from errors import ApiError, invalid_state, not_found
from serializers import contract_json
from store import DB, new_id, now, stamp_new, touch
from validate import f_bool, f_dt, f_int, f_num, f_str, get_body, resolve_ref

bp = Blueprint("contracts", __name__)


@bp.post("/genomics/service-contracts")
def create_contract():
    require_roles("FinanceAdmin")
    body = get_body()
    resolve_ref(body, "instrument_id", "instruments")
    account_id = f_str(body, "account_id")
    instrument_id = f_str(body, "instrument_id")
    coverage_start = f_dt(body, "coverage_start")
    coverage_end = f_dt(body, "coverage_end")
    committed_uptime_percent = f_num(body, "committed_uptime_percent")
    monthly_fee_cents = f_int(body, "monthly_fee_cents", min_v=0)
    annual_credit_cap_cents = f_int(body, "annual_credit_cap_cents", min_v=0)
    reagent_guarantee = f_bool(body, "reagent_guarantee", default=False)
    if not (coverage_end > coverage_start):
        raise ApiError(
            "ERR_CONTRACT_WINDOW_INVALID", 422, "coverage_end must be after coverage_start"
        )
    contract = {
        "id": new_id(),
        "account_id": account_id,
        "instrument_id": instrument_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "committed_uptime_percent": committed_uptime_percent,
        "monthly_fee_cents": monthly_fee_cents,
        "annual_credit_cap_cents": annual_credit_cap_cents,
        "reagent_guarantee": reagent_guarantee,
        "contract_state": "DRAFT",
        "credits_issued_ytd_cents": 0,
        "last_reconciliation_end": None,
        "terminated_reason": None,
    }
    stamp_new(contract)
    DB["contracts"][contract["id"]] = contract
    return ok(contract_json(contract), 201)


@bp.get("/genomics/service-contracts/<contract_id>")
def get_contract(contract_id):
    require_roles("FinanceAdmin", "AccountManager")
    contract = DB["contracts"].get(contract_id)
    if contract is None:
        raise not_found("ServiceContract not found")
    return ok(contract_json(contract))


@bp.get("/genomics/service-contracts")
def list_contracts():
    require_roles("FinanceAdmin", "AccountManager")
    items = list(DB["contracts"].values())
    account_id = request.args.get("account_id")
    instrument_id = request.args.get("instrument_id")
    contract_state = request.args.get("contract_state")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if instrument_id is not None:
        items = [c for c in items if c["instrument_id"] == instrument_id]
    if contract_state is not None:
        items = [c for c in items if c["contract_state"] == contract_state]
    return ok_list([contract_json(c) for c in sort_items(items)])


@bp.post("/genomics/service-contracts/<contract_id>/activate")
def activate_contract(contract_id):
    require_roles("FinanceAdmin")
    contract = DB["contracts"].get(contract_id)
    if contract is None:
        raise not_found("ServiceContract not found")
    if contract["contract_state"] != "DRAFT":
        raise invalid_state("activate requires contract_state DRAFT")
    instrument = DB["instruments"].get(contract["instrument_id"])
    if instrument is not None and instrument["install_state"] == "DECOMMISSIONED":
        raise invalid_state("Cannot activate a contract on a DECOMMISSIONED instrument")
    # Single coverage: no overlapping ACTIVE contract on the same instrument
    # (half-open windows; adjacency allowed). Priority 23 before 31.
    for other in DB["contracts"].values():
        if other["id"] == contract["id"]:
            continue
        if other["instrument_id"] != contract["instrument_id"]:
            continue
        if other["contract_state"] != "ACTIVE":
            continue
        if (
            contract["coverage_start"] < other["coverage_end"]
            and other["coverage_start"] < contract["coverage_end"]
        ):
            raise ApiError(
                "ERR_CONTRACT_WINDOW_OVERLAP",
                409,
                "An ACTIVE contract already covers an overlapping window",
            )
    if not (contract["coverage_end"] > contract["coverage_start"]):
        raise ApiError(
            "ERR_CONTRACT_WINDOW_INVALID", 422, "coverage_end must be after coverage_start"
        )
    contract["contract_state"] = "ACTIVE"
    touch(contract)
    return ok(contract_json(contract))


@bp.post("/genomics/service-contracts/<contract_id>/uptime-reconciliations")
def uptime_reconciliation(contract_id):
    require_roles("FinanceAdmin")
    contract = DB["contracts"].get(contract_id)
    if contract is None:
        raise not_found("ServiceContract not found")
    body = get_body()
    period_start = f_dt(body, "period_start")
    period_end = f_dt(body, "period_end")
    if contract["contract_state"] != "ACTIVE":
        raise invalid_state("uptime-reconciliations require contract_state ACTIVE")
    t = now()
    if (
        not (period_start < period_end)
        or period_end > t
        or (
            contract["last_reconciliation_end"] is not None
            and period_start < contract["last_reconciliation_end"]
        )
    ):
        raise ApiError(
            "ERR_RECONCILIATION_PERIOD_INVALID",
            422,
            "Reconciliation window is empty, in the future, or overlaps a reconciled period",
        )
    instrument = DB["instruments"].get(contract["instrument_id"])
    if instrument is None:
        raise not_found("Instrument not found")
    downtime_minutes, uptime_percent, credit = uptime_credit(
        contract, instrument, period_start, period_end
    )
    contract["credits_issued_ytd_cents"] += credit
    contract["last_reconciliation_end"] = period_end
    touch(contract)
    if credit:
        account = DB["accounts"].get(contract["account_id"])
        if account is not None:
            account["credit_balance_cents"] += credit
            touch(account)
    return ok(
        {
            "downtime_minutes": downtime_minutes,
            "uptime_percent": uptime_percent,
            "credit_cents": credit,
            "credits_issued_ytd_cents": contract["credits_issued_ytd_cents"],
        },
        201,
    )
