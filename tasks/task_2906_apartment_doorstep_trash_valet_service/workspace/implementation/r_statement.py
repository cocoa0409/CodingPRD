"""MonthlyStatement endpoints (PRD s3.8)."""

from flask import Blueprint

import shape
from authz import admit, get_contract, get_statement
from calc import nights_in_period, statement_settlement, statements_of_contract
from envelope import array_response, object_response
from errors import ApiError
from serializers import statement_out
from shape import pagination, paginate, q
from store import db, parse_date, period_bounds, sort_rows, stamp_new, touch

bp = Blueprint("statement", __name__)

TERMINAL_NIGHT_STATES = ("VERIFIED", "PARTIAL", "MISSED", "CANCELLED")


@bp.route("/valet/contracts/<contract_id>/statements", methods=["POST"])
def draft_statement(contract_id):
    actor = admit(("BillingAnalyst", "PlatformAdmin"))
    contract = get_contract(contract_id)
    body = shape.body()
    billing_period = shape.req_period(body, "billing_period")
    expected_version = shape.req_int(body, "expected_contract_version")

    # rung 5 -- the period must intersect the contract's closed effective period
    first_date, last_date = period_bounds(billing_period)
    eff_from = parse_date(contract["effective_from"])
    eff_to = parse_date(contract["effective_to"])
    if not (first_date <= eff_to and eff_from <= last_date):
        shape.bad("Field 'billing_period' must intersect the contract's effective period.")

    # rung 10
    if expected_version != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")

    # rung 25
    existing_draft = None
    for other in statements_of_contract(contract["id"]):
        if other["billing_period"] != billing_period:
            continue
        if other["status"] == "ISSUED":
            raise ApiError("ERR_PERIOD_ALREADY_INVOICED")
        if other["status"] == "DRAFT":
            existing_draft = other

    prop = db.properties.get(contract["property_id"])
    money = statement_settlement(contract, prop, billing_period, "PROVISIONAL")

    superseded_id = None
    if existing_draft is not None:
        existing_draft["status"] = "VOID"
        existing_draft["void_reason"] = "SUPERSEDED"
        touch(existing_draft)
        superseded_id = existing_draft["id"]

    row = {
        "contract_id": contract["id"],
        "superseded_statement_id": superseded_id,
        "billing_period": billing_period,
        "variant": "PROVISIONAL",
        "gross_passthrough_cents": money["gross_passthrough_cents"],
        "scheduled_night_count": money["scheduled_night_count"],
        "missed_equivalent_nights": money["missed_equivalent_nights"],
        "missed_service_bps": money["missed_service_bps"],
        "sla_credit_rate_bps": money["sla_credit_rate_bps"],
        "missed_service_credit_cents": money["missed_service_credit_cents"],
        "property_revenue_share_cents": money["property_revenue_share_cents"],
        "net_due_from_property_cents": money["net_due_from_property_cents"],
        "status": "DRAFT",
        "created_by_user_id": actor.user_id,
        "issued_by_user_id": None,
        "void_reason": None,
    }
    stamp_new(row)
    db.statements[row["id"]] = row

    touch(contract)
    return object_response(statement_out(row), 201)


@bp.route("/valet/statements/<statement_id>", methods=["GET"])
def read_statement(statement_id):
    admit(("PlatformAdmin", "BillingAnalyst", "PropertyManager"))
    row = get_statement(statement_id)
    return object_response(statement_out(row))


@bp.route("/valet/statements", methods=["GET"])
def list_statements():
    admit(("PlatformAdmin", "BillingAnalyst", "PropertyManager"))
    limit, offset = pagination()
    f_contract = q("contract_id")
    f_period = q("billing_period")
    f_status = q("status")
    f_variant = q("variant")
    f_superseded = q("superseded_statement_id")
    rows = sort_rows(list(db.statements.values()))
    if f_contract is not None:
        rows = [r for r in rows if r["contract_id"] == f_contract]
    if f_period is not None:
        rows = [r for r in rows if r["billing_period"] == f_period]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    if f_variant is not None:
        rows = [r for r in rows if r["variant"] == f_variant]
    if f_superseded is not None:
        rows = [r for r in rows if r["superseded_statement_id"] == f_superseded]
    page, total, has_more = paginate(rows, limit, offset)
    return array_response([statement_out(r) for r in page], limit, offset, total, has_more)


@bp.route("/valet/statements/<statement_id>/issue", methods=["POST"])
def issue_statement(statement_id):
    actor = admit(("BillingAnalyst", "PlatformAdmin"))
    statement = get_statement(statement_id)
    shape.body()

    # rung 8
    if statement["status"] in ("ISSUED", "VOID"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if statement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    # rung 13
    if actor.user_id == statement["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    contract = db.contracts.get(statement["contract_id"])
    period_nights = nights_in_period(statement["contract_id"], statement["billing_period"])

    # rung 26
    for night in period_nights:
        if night["verification_status"] not in TERMINAL_NIGHT_STATES:
            raise ApiError("ERR_PERIOD_NOT_CLOSED")

    prop = db.properties.get(contract["property_id"]) if contract is not None else None
    money = statement_settlement(contract, prop, statement["billing_period"], "FINAL")
    statement["variant"] = "FINAL"
    statement["gross_passthrough_cents"] = money["gross_passthrough_cents"]
    statement["scheduled_night_count"] = money["scheduled_night_count"]
    statement["missed_equivalent_nights"] = money["missed_equivalent_nights"]
    statement["missed_service_bps"] = money["missed_service_bps"]
    statement["sla_credit_rate_bps"] = money["sla_credit_rate_bps"]
    statement["missed_service_credit_cents"] = money["missed_service_credit_cents"]
    statement["property_revenue_share_cents"] = money["property_revenue_share_cents"]
    statement["net_due_from_property_cents"] = money["net_due_from_property_cents"]
    statement["status"] = "ISSUED"
    statement["issued_by_user_id"] = actor.user_id
    touch(statement)

    # the billing dimension of the period's nights advances
    for night in period_nights:
        if night["billing_status"] != "ACCRUED":
            continue
        if night["verification_status"] == "VERIFIED":
            night["billing_status"] = "INVOICED"
            touch(night)
        elif night["verification_status"] in ("MISSED", "PARTIAL"):
            night["billing_status"] = "CREDITED"
            touch(night)

    if contract is not None:
        contract["last_invoiced_period"] = statement["billing_period"]
        touch(contract)
    return object_response(statement_out(statement))


@bp.route("/valet/statements/<statement_id>/void", methods=["POST"])
def void_statement(statement_id):
    admit(("PlatformAdmin",))
    statement = get_statement(statement_id)
    body = shape.body()
    reason = shape.req_str(body, "reason", min_len=1, max_len=500, non_blank=True)

    contract = db.contracts.get(statement["contract_id"])

    # rung 8 -- VOID is terminal; an ISSUED statement is reversible only for the
    # most recently settled period
    if statement["status"] == "VOID":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if statement["status"] == "ISSUED":
        if contract is None or contract.get("last_invoiced_period") != statement["billing_period"]:
            raise ApiError("ERR_INVALID_STATE")
    elif statement["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    was_issued = statement["status"] == "ISSUED"
    statement["status"] = "VOID"
    statement["void_reason"] = reason
    touch(statement)

    if was_issued:
        for night in nights_in_period(statement["contract_id"], statement["billing_period"]):
            if night["billing_status"] in ("INVOICED", "CREDITED"):
                night["billing_status"] = "ACCRUED"
                touch(night)
        if contract is not None:
            contract["last_invoiced_period"] = None
            touch(contract)
    return object_response(statement_out(statement))
