"""EscalationAgreement and IndexReading endpoints (PRD 3.4)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import serial
from auth import authorize, current_role, current_user_id
from calc import MAX_NEGOTIATION_ROUNDS
from domain import INDEX_CODES
from envelope import created, ok, paginated
from errors import ApiError
from shapes import Field, validate
from store import ordered, store

bp = Blueprint("agreements", __name__)

AGREEMENT_FIELDS = [
    Field("quote_id", "string", required=True),
    Field("index_code", "enum", required=True, choices=INDEX_CODES),
    Field("baseline_index_period", "period", required=True),
    Field("cap_pct", "number", required=True, exclusive_minimum=0, maximum=25, max_dp=1),
    Field("contractor_share_pct", "number", required=True, minimum=0, maximum=100, max_dp=1),
    Field("price_hold_through", "datetime", required=True),
    Field("deadband_pct", "number", minimum=0, maximum=20, max_dp=1,
          default=Decimal("2.0")),
    Field("proposed_terms_note", "string", nullable=True, allow_blank=True, default=None),
]

PROPOSE_FIELDS = [
    Field("cap_pct", "number", exclusive_minimum=0, maximum=25, max_dp=1),
    Field("contractor_share_pct", "number", minimum=0, maximum=100, max_dp=1),
    Field("deadband_pct", "number", minimum=0, maximum=20, max_dp=1),
    Field("proposed_terms_note", "string", nullable=True, allow_blank=True),
]

COUNTER_FIELDS = [
    Field("cap_pct", "number", required=True, exclusive_minimum=0, maximum=25, max_dp=1),
    Field("contractor_share_pct", "number", required=True, minimum=0, maximum=100, max_dp=1),
    Field("deadband_pct", "number", minimum=0, maximum=20, max_dp=1),
    Field("counter_note", "string", nullable=True, allow_blank=True),
]

READING_FIELDS = [
    Field("index_code", "enum", required=True, choices=INDEX_CODES),
    Field("period", "period", required=True),
    Field("value", "number", required=True, exclusive_minimum=0, max_dp=2),
    Field("published_at", "datetime", required=True),
]


@bp.post("/procurement/escalation-agreements")
@authorize("BuyoutManager")
def create_agreement():
    body = validate(AGREEMENT_FIELDS)
    quote = domain.get_quote(body["quote_id"])
    pkg = store.packages[quote["material_package_id"]]
    if body["index_code"] != pkg["commodity_index_code"]:
        raise ApiError("ERR_INDEX_CODE_MISMATCH")
    if calc.reading_exact(body["index_code"], body["baseline_index_period"]) is None:
        raise ApiError("ERR_INDEX_READING_MISSING")
    if body["price_hold_through"] > quote["expires_at"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "price_hold_through may not be later than the quote's expires_at",
        )
    row = store.new_row()
    row.update(body)
    row["baseline_index_value"] = None
    row["counter_note"] = None
    row["round_number"] = 0
    row["executed_at"] = None
    row["status"] = "DRAFT"
    store.agreements[row["id"]] = row
    return created(serial.agreement(row))


@bp.get("/procurement/escalation-agreements/<agreement_id>")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def read_agreement(agreement_id):
    row = domain.get_agreement(agreement_id)
    return ok(serial.agreement(row))


@bp.get("/procurement/escalation-agreements")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_agreements():
    args = request.args
    quote_id = domain.string_filter(args, "quote_id")
    status = domain.string_filter(args, "status")
    index_code = domain.string_filter(args, "index_code")
    rows = []
    for row in ordered(list(store.agreements.values())):
        if quote_id is not None and row["quote_id"] != quote_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if index_code is not None and row["index_code"] != index_code:
            continue
        rows.append(row)
    return paginated(rows, serial.agreement)


@bp.post("/procurement/escalation-agreements/<agreement_id>/propose")
@authorize("BuyoutManager")
def propose_agreement(agreement_id):
    body = validate(PROPOSE_FIELDS)
    row = domain.get_agreement(agreement_id)
    if row["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    quote = store.quotes[row["quote_id"]]
    if quote["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    for key in ("cap_pct", "contractor_share_pct", "deadband_pct", "proposed_terms_note"):
        if key in body:
            row[key] = body[key]
    row["status"] = "PROPOSED"
    store.touch(row)
    return ok(serial.agreement(row))


@bp.post("/procurement/escalation-agreements/<agreement_id>/counter")
@authorize("SupplierRep")
def counter_agreement(agreement_id):
    body = validate(COUNTER_FIELDS)
    row = domain.get_agreement(agreement_id)
    quote = store.quotes[row["quote_id"]]
    if current_role() == "SupplierRep" and current_user_id() != quote["supplier_id"]:
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    if row["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if row["round_number"] >= MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")
    responsive = (
        body["cap_pct"] > row["cap_pct"]
        or body["contractor_share_pct"] < row["contractor_share_pct"]
    )
    if not responsive:
        raise ApiError("ERR_COUNTER_NOT_RESPONSIVE")
    row["cap_pct"] = body["cap_pct"]
    row["contractor_share_pct"] = body["contractor_share_pct"]
    for key in ("deadband_pct", "counter_note"):
        if key in body:
            row[key] = body[key]
    row["round_number"] = row["round_number"] + 1
    row["status"] = "COUNTERED"
    store.touch(row)
    return ok(serial.agreement(row))


@bp.post("/procurement/escalation-agreements/<agreement_id>/execute")
@authorize("ProjectExecutive")
def execute_agreement(agreement_id):
    validate([])
    row = domain.get_agreement(agreement_id)
    if row["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    quote = store.quotes[row["quote_id"]]
    if quote["status"] != "OPEN":
        raise ApiError("ERR_QUOTE_NOT_OPEN")
    reading = calc.reading_exact(row["index_code"], row["baseline_index_period"])
    if reading is None:
        raise ApiError("ERR_INDEX_READING_MISSING")
    row["baseline_index_value"] = reading["value"]
    row["executed_at"] = store.clock
    row["status"] = "EXECUTED"
    store.touch(row)
    return ok(serial.agreement(row))


@bp.post("/procurement/index-readings")
@authorize("BuyoutManager")
def create_reading():
    body = validate(READING_FIELDS)
    if calc.reading_exact(body["index_code"], body["period"]) is not None:
        raise ApiError("ERR_DUPLICATE_INDEX_READING")
    row = store.new_row(versioned=False)
    row.update(body)
    store.index_readings[row["id"]] = row
    return created(serial.index_reading(row))


@bp.get("/procurement/index-readings")
@authorize("BuyoutManager", "SupplierRep", "ProjectExecutive", "DesignEngineer", "OwnerRep")
def list_readings():
    args = request.args
    index_code = domain.string_filter(args, "index_code")
    period = domain.string_filter(args, "period")
    rows = []
    for row in ordered(list(store.index_readings.values())):
        if index_code is not None and row["index_code"] != index_code:
            continue
        if period is not None and row["period"] != period:
            continue
        rows.append(row)
    return paginated(rows, serial.index_reading)
