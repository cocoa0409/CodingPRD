"""Gas movement ticket endpoints: metering, confirmation and reversal (PRD 3.6)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError, not_found
from routes.helpers import filter_eq, list_result
from utils import D, round_half_up, round_int

bp = Blueprint("tickets", __name__)


def _check_well_integrity(well):
    """Rung 11, deliberately ahead of availability at rung 12."""
    if well["integrity_state"] == "MIT_FAILED":
        raise ApiError("ERR_WELL_INTEGRITY_FAILED", "this wellbore has failed its integrity test.")
    for program in store.programs_of_well(well["id"]):
        if program["status"] in ("OPEN", "ESCALATED"):
            raise ApiError("ERR_WELL_INTEGRITY_FAILED",
                           "an integrity remediation program is outstanding on this wellbore.")


def _check_well_available(well):
    """Rung 12."""
    if well["operational_state"] != "IN_SERVICE" or well["well_type"] != "INJECTION_WITHDRAWAL":
        raise ApiError("ERR_WELL_NOT_IN_SERVICE",
                       "this wellbore is not an in-service injection/withdrawal wellbore.")


@bp.post("/gas-movement-tickets")
def create_ticket():
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()

    nomination_id = validate.field_id(body, "nomination_id")
    well_id = validate.field_id(body, "well_id")
    actual_volume = validate.field_int(body, "actual_volume_dth", exclusive_minimum=0)

    nomination = validate.resolve_body_fk("Nomination", nomination_id)
    contract = store.contracts[nomination["contract_id"]]
    well = validate.resolve_body_fk("Well", well_id)
    if well["storage_field_id"] != contract["storage_field_id"]:
        raise not_found("Well", "this wellbore is not on the nomination's reservoir.")

    _check_well_integrity(well)
    _check_well_available(well)

    if nomination["status"] != "CONFIRMED" or int(nomination["confirmed_volume_dth"]) <= 0:
        raise ApiError("ERR_INVALID_NOMINATION_STATE",
                       "only a CONFIRMED nomination holding volume may carry a ticket.")
    for existing in store.tickets_of_nomination(nomination["id"]):
        if existing["status"] != "REVERSED":
            raise ApiError("ERR_TICKET_ALREADY_EXISTS",
                           "a live ticket already exists for this nomination.")
    ceiling = round_int(D(nomination["confirmed_volume_dth"])
                        * (D(100) + config.TICKET_OVERRUN_PCT) / D(100))
    if actual_volume > ceiling:
        raise ApiError("ERR_TICKET_OVERRUN_EXCEEDED",
                       "actual_volume_dth exceeds the metering tolerance.")

    ticket = store.new_record()
    ticket.update({
        "nomination_id": nomination["id"],
        "well_id": well["id"],
        "actual_volume_dth": actual_volume,
        "fuel_retention_dth": None,
        "net_volume_dth": None,
        "commodity_charge_usd": None,
        "volume_discount_usd": None,
        "fuel_charge_usd": None,
        "total_charge_usd": None,
        "status": "PENDING",
        "reversal_reason": None,
        "confirmed_at": None,
    })
    store.put("GasMovementTicket", ticket)
    return envelope.created(serialize.ticket(ticket))


@bp.get("/gas-movement-tickets")
def list_tickets():
    user_id, role = auth.require(config.SCHEDULE_READ_ROLES)
    limit, offset = validate.pagination()
    nomination_id = validate.query_id("nomination_id")
    well_id = validate.query_id("well_id")
    status = validate.query_enum("status", config.TICKET_STATUSES)

    rows = store.values("GasMovementTicket")
    visible = auth.visible_contract_ids(user_id, role)
    if visible is not None:
        rows = [row for row in rows
                if store.nominations[row["nomination_id"]]["contract_id"] in visible]
    rows = filter_eq(rows, "nomination_id", nomination_id)
    rows = filter_eq(rows, "well_id", well_id)
    rows = filter_eq(rows, "status", status)
    return list_result(rows, serialize.ticket, limit, offset)


@bp.get("/gas-movement-tickets/<ticket_id>")
def read_ticket(ticket_id):
    user_id, role = auth.require(config.SCHEDULE_READ_ROLES)
    ticket = validate.resolve_path("GasMovementTicket", ticket_id)
    auth.check_contract_ownership(auth.contract_of_ticket(ticket), user_id, role)
    return envelope.object_response(serialize.ticket(ticket))


@bp.post("/gas-movement-tickets/<ticket_id>/confirm")
def confirm_ticket(ticket_id):
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()
    expected_version = validate.field_int(body, "expected_storage_field_version")
    ticket = validate.resolve_path("GasMovementTicket", ticket_id)

    if ticket["status"] != "PENDING":
        raise ApiError("ERR_INVALID_TICKET_STATE", "only a PENDING ticket may be confirmed.")
    nomination = store.nominations[ticket["nomination_id"]]
    contract = store.contracts[nomination["contract_id"]]
    field = store.storage_fields[contract["storage_field_id"]]
    well = store.wells[ticket["well_id"]]

    if int(expected_version) != int(field["version"]):
        raise ApiError("ERR_STALE_FIELD_VERSION",
                       "expected_storage_field_version does not match the field's version.")
    if field["field_posture"] == "FROZEN":
        raise ApiError("ERR_FIELD_FROZEN", "no ticket may be confirmed on a frozen field.")
    _check_well_integrity(well)
    _check_well_available(well)

    direction = nomination["direction"]
    actual = D(ticket["actual_volume_dth"])
    inventory = D(field["working_gas_inventory_dth"])
    breakdown = engine.ticket_charge_breakdown(actual, direction, contract)

    if direction == "WITHDRAWAL" and actual > inventory:
        raise ApiError("ERR_CUSHION_GAS_BREACH",
                       "actual_volume_dth exceeds the field's working gas inventory.")
    if direction == "INJECTION":
        if inventory + breakdown["net_volume_dth"] > D(field["max_working_gas_dth"]):
            raise ApiError("ERR_WORKING_GAS_CAPACITY_EXCEEDED",
                           "this injection would breach the working gas ceiling.")
        projected = inventory + actual
        max_working = D(field["max_working_gas_dth"])
        fraction = projected / max_working if max_working != 0 else D(0)
        pressure = round_int(D(field["base_pressure_psig"])
                             + fraction * D(field["pressure_span_psig"]))
        if pressure > int(field["max_pressure_psig"]):
            raise ApiError("ERR_FIELD_PRESSURE_LIMIT",
                           "this injection would breach the field's pressure limit.")
    if direction == "WITHDRAWAL":
        if actual + breakdown["fuel_retention_dth"] > D(contract["inventory_balance_dth"]):
            raise ApiError("ERR_CONTRACT_INVENTORY_INSUFFICIENT",
                           "the contract does not hold enough inventory for this withdrawal.")

    ticket.update(breakdown)
    ticket["status"] = "CONFIRMED"
    ticket["confirmed_at"] = store.now()
    store.touch(ticket)

    signed = actual if direction == "INJECTION" else -actual
    field["working_gas_inventory_dth"] = inventory + signed
    field["retained_fuel_pool_dth"] = (D(field["retained_fuel_pool_dth"])
                                       + breakdown["fuel_retention_dth"])
    before, after = engine.refresh_field(field, force_touch=True)

    net_signed = (breakdown["net_volume_dth"] if direction == "INJECTION"
                  else -breakdown["net_volume_dth"])
    contract["inventory_balance_dth"] = D(contract["inventory_balance_dth"]) + net_signed
    daily_delta = actual - D(nomination["confirmed_volume_dth"])
    engine.add_ledger(contract, "DAILY_IMBALANCE", nomination["gas_day"], daily_delta, D(0),
                      "ticket confirm %s" % nomination["gas_day"])
    engine.reconcile_contract(contract, force_touch=True)

    engine.phase_b(field, before, after, "ticket confirm %s" % nomination["gas_day"])
    return envelope.object_response(serialize.ticket(ticket))


@bp.post("/gas-movement-tickets/<ticket_id>/reverse")
def reverse_ticket(ticket_id):
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()
    reversal_reason = validate.field_str(body, "reversal_reason")
    ticket = validate.resolve_path("GasMovementTicket", ticket_id)

    if ticket["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_TICKET_STATE", "only a CONFIRMED ticket may be reversed.")
    nomination = store.nominations[ticket["nomination_id"]]
    contract = store.contracts[nomination["contract_id"]]
    field = store.storage_fields[contract["storage_field_id"]]
    gas_day = nomination["gas_day"]

    for report in store.reports_of_field(field["id"]):
        if report["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if report["period_start_date"] <= gas_day <= report["period_end_date"]:
            raise ApiError("ERR_REPORTING_PERIOD_LOCKED",
                           "a filed regulatory report covers this gas day.")

    direction = nomination["direction"]
    actual = D(ticket["actual_volume_dth"])
    signed = actual if direction == "INJECTION" else -actual
    field["working_gas_inventory_dth"] = D(field["working_gas_inventory_dth"]) - signed
    field["retained_fuel_pool_dth"] = (D(field["retained_fuel_pool_dth"])
                                       - D(ticket["fuel_retention_dth"]))

    net_signed = (D(ticket["net_volume_dth"]) if direction == "INJECTION"
                  else -D(ticket["net_volume_dth"]))
    contract["inventory_balance_dth"] = D(contract["inventory_balance_dth"]) - net_signed
    daily_delta = actual - D(nomination["confirmed_volume_dth"])
    engine.add_ledger(contract, "DAILY_IMBALANCE", gas_day, -daily_delta, D(0),
                      "ticket reversal %s" % gas_day)

    ticket["status"] = "REVERSED"
    ticket["reversal_reason"] = reversal_reason
    store.touch(ticket)

    engine.refresh_field(field, force_touch=True)
    engine.reconcile_contract(contract, force_touch=True)
    return envelope.object_response(serialize.ticket(ticket))
