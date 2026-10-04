"""Family support service lines, ledgers and the stimulation markup (PRD §3.10)."""

from flask import Blueprint

from db import DB, new_row, touch
from errors import ApiError
from http_util import body_json, optional, required, require_role
from response import success_object
from routes._common import arg, filtered, list_response, ordered
from services import (
    fund_add_patient_support, fund_add_research, get_or_404, serialize_ledger,
    serialize_service, stimulation_markup,
)

bp = Blueprint("services", __name__)

SERVICE_CODES = {"TRAVEL", "HOUSING", "MEALS", "SIBLING_CARE", "COMFORT_ITEM"}


@bp.post("/programs/family-support-services")
def create_service():
    require_role("PatientSupportOfficer")
    data = body_json()
    if "fund_id" not in data or data["fund_id"] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    fund_id = required(data, "fund_id", "str")
    fund = get_or_404("funds", fund_id)
    service_code = required(data, "service_code", "str")
    if service_code not in SERVICE_CODES:
        raise ApiError("ERR_INVALID_REQUEST")
    display_name = required(data, "display_name", "str")
    base_allowance = required(data, "base_allowance_cents", "int")
    if base_allowance < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    eligible = optional(data, "is_stimulation_eligible", False, "bool")
    rate = optional(data, "stimulation_rate", 0, "number")
    if not (0 <= rate <= 1):
        raise ApiError("ERR_INVALID_REQUEST")
    cap = optional(data, "stimulation_cap_cents", 0, "int")

    for existing in DB["services"].values():
        if existing["fund_id"] == fund_id and existing["service_code"] == service_code:
            raise ApiError("ERR_DUPLICATE_ENTITY")

    service = new_row({
        "fund_id": fund_id,
        "service_code": service_code,
        "display_name": display_name,
        "base_allowance_cents": base_allowance,
        "is_stimulation_eligible": eligible,
        "stimulation_rate": rate,
        "stimulation_cap_cents": cap,
    })
    DB["services"][service["id"]] = service

    ledger = new_row({
        "family_support_service_id": service["id"],
        "ledger_epoch": 0,
        "accumulated_cents": 0,
        "status": "ACTIVE",
    })
    DB["ledgers"][ledger["id"]] = ledger
    return success_object(serialize_service(service), 201)


@bp.get("/programs/family-support-services")
def list_services():
    require_role("Any")
    fund_id = arg("fund_id")
    service_code = arg("service_code")
    rows = ordered(DB["services"].values())
    rows = filtered(rows, fund_id=fund_id, service_code=service_code)
    return list_response(rows, serialize_service)


@bp.get("/programs/family-support-services/<service_id>")
def get_service(service_id):
    require_role("Any")
    service = get_or_404("services", service_id)
    return success_object(serialize_service(service), 200)


@bp.get("/programs/family-support-services/<service_id>/ledgers")
def list_service_ledgers(service_id):
    require_role("Any")
    get_or_404("services", service_id)
    status = arg("status")
    rows = ordered([l for l in DB["ledgers"].values()
                    if l["family_support_service_id"] == service_id])
    rows = filtered(rows, status=status)
    return list_response(rows, serialize_ledger)


@bp.post("/programs/family-support-services/<service_id>/allowances")
def accrue_allowance(service_id):
    require_role("PatientSupportOfficer")
    service = get_or_404("services", service_id)
    fund = get_or_404("funds", service["fund_id"])
    data = body_json()
    family_count = required(data, "family_count", "int")
    if family_count < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    expected_epoch = optional(data, "ledger_epoch", None, "int")

    ledgers = [l for l in DB["ledgers"].values()
               if l["family_support_service_id"] == service["id"]]
    ledgers.sort(key=lambda l: l["created_at"])
    if not ledgers:
        raise ApiError("ERR_LEDGER_NOT_FOUND")
    ledger = ledgers[0]

    if expected_epoch is not None and expected_epoch != int(ledger["ledger_epoch"]):
        raise ApiError("ERR_STALE_LEDGER_EPOCH")

    allowance = int(service["base_allowance_cents"]) * family_count
    markup = 0
    if service["is_stimulation_eligible"] and ledger["status"] == "ACTIVE":
        markup = stimulation_markup(service)

    ledger["accumulated_cents"] = int(ledger["accumulated_cents"]) + allowance
    fund_add_patient_support(fund, -allowance)
    if markup:
        fund_add_research(fund, markup)
    touch(ledger)

    return success_object({
        "allowance_cents": allowance,
        "markup_cents": markup,
        "family_service_ledger_id": ledger["id"],
        "service_ledger_status": ledger["status"],
        "ledger_accumulated_cents": ledger["accumulated_cents"],
        "fund_research_balance_cents": fund["research_balance_cents"],
    }, 201)


@bp.get("/programs/family-service-ledgers/<ledger_id>")
def get_ledger(ledger_id):
    require_role("Any")
    ledger = get_or_404("ledgers", ledger_id)
    return success_object(serialize_ledger(ledger), 200)


@bp.post("/programs/family-service-ledgers/<ledger_id>/freeze")
def freeze_ledger(ledger_id):
    require_role("PatientSupportOfficer")
    ledger = get_or_404("ledgers", ledger_id)
    body_json()
    ledger["status"] = "FROZEN"
    touch(ledger)
    return success_object(serialize_ledger(ledger), 200)