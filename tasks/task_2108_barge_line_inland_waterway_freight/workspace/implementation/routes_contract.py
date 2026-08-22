"""Freight contracts, the charge breakdown, invoicing and cargo claims."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from common import (ALL_ROLES, ApiError, apply_filters, authenticate, caller_id,
                    caller_role, clock, created, dec, f_enum, f_int, f_num,
                    f_str, fetch, get_body, make_record, ok, paged_response,
                    pagination, sorted_rows, store, touch)
from schema import ser_claim, ser_contract

bp = Blueprint("contract", __name__)

SETTLEMENT_BASES = ["DEDUCTIBLE", "FRANCHISE"]
CLAIM_TYPES = ["SHORTAGE", "DAMAGE", "CONTAMINATION"]
VARIANTS = ["PROVISIONAL", "FINAL"]


# ---------------------------------------------------------------------------
# Freight contracts
# ---------------------------------------------------------------------------
@bp.post("/freight-contracts")
def create_contract():
    authenticate(["ContractManager"])
    body = get_body()
    shipper_id = f_str(body, "shipper_id")
    commodity_id = f_str(body, "commodity_id")
    contracted_tons = f_int(body, "contracted_tons", gt=0)
    origin_mile = f_num(body, "origin_mile")
    destination_mile = f_num(body, "destination_mile")
    laytime_hours = f_int(body, "laytime_hours", ge=0)
    declared_value = f_int(body, "declared_value_cents_per_ton", gt=0)
    basis = f_enum(body, "claim_settlement_basis", SETTLEMENT_BASES,
                   required=False, default="DEDUCTIBLE")
    fetch(store.shippers, shipper_id, "ERR_SHIPPER_NOT_FOUND")
    fetch(store.commodities, commodity_id, "ERR_COMMODITY_NOT_FOUND")
    rec = make_record({
        "shipper_id": shipper_id,
        "commodity_id": commodity_id,
        "contracted_tons": contracted_tons,
        "origin_mile": origin_mile,
        "destination_mile": destination_mile,
        "distance_miles": None,
        "laytime_hours": laytime_hours,
        "declared_value_cents_per_ton": declared_value,
        "claim_settlement_basis": basis,
        "pinned_tariff_filing_id": None,
        "pinned_fuel_price_cents_per_gallon": None,
        "pinned_fuel_surcharge_pct": None,
        "movement_status": "DRAFT",
        "billing_status": "NOT_BILLED",
        "accrued_delay_minutes": 0,
        "delay_protection_applied": False,
        "linehaul_cents": 0,
        "fuel_surcharge_cents": 0,
        "fleeting_fee_cents": 0,
        "cleaning_fee_cents": 0,
        "demurrage_cents": 0,
        "subtotal_cents": 0,
        "volume_rebate_cents": 0,
        "claim_credit_cents": 0,
        "total_cents": 0,
    })
    store.freight_contracts[rec["id"]] = rec
    return created(ser_contract(rec))


@bp.post("/freight-contracts/<freight_contract_id>/book")
def book_contract(freight_contract_id):
    authenticate(["ContractManager"])
    contract = fetch(store.freight_contracts, freight_contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    if contract["movement_status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE")
    contract["movement_status"] = "BOOKED"
    touch(contract)
    return ok(ser_contract(contract))


@bp.post("/freight-contracts/<freight_contract_id>/activate")
def activate_contract(freight_contract_id):
    authenticate(["ContractManager"])
    contract = fetch(store.freight_contracts, freight_contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    if contract["movement_status"] != "BOOKED":
        raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE")
    shipper = store.shippers.get(contract["shipper_id"])
    commodity = store.commodities.get(contract["commodity_id"])
    group = commodity["commodity_group"] if commodity else None

    # priority 17
    filing = calc.effective_filing_for(group)
    if filing is None:
        raise ApiError("ERR_NO_EFFECTIVE_TARIFF")
    # priority 18
    posting = calc.controlling_posting()
    if posting is None:
        raise ApiError("ERR_NO_FUEL_INDEX_POSTING")
    # priority 33
    if shipper is None or shipper["status"] != "ACTIVE":
        raise ApiError("ERR_SHIPPER_ON_CREDIT_HOLD")
    # priority 34
    projected = calc.projected_charge(contract, filing)
    if shipper["outstanding_balance_cents"] + projected > shipper["credit_limit_cents"]:
        raise ApiError("ERR_SHIPPER_CREDIT_EXCEEDED")

    price = posting["diesel_price_cents_per_gallon"]
    contract["movement_status"] = "ACTIVE"
    contract["pinned_tariff_filing_id"] = filing["id"]
    contract["pinned_fuel_price_cents_per_gallon"] = price
    contract["pinned_fuel_surcharge_pct"] = calc.surcharge_pct_for(filing, price)
    distance = abs(dec(contract["destination_mile"]) - dec(contract["origin_mile"]))
    contract["distance_miles"] = float(distance)
    touch(contract)
    return ok(ser_contract(contract))


@bp.post("/freight-contracts/<freight_contract_id>/cancel")
def cancel_contract(freight_contract_id):
    authenticate(["ContractManager"])
    body = get_body()
    reason = f_str(body, "reason", required=False)
    contract = fetch(store.freight_contracts, freight_contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    if contract["movement_status"] not in ("DRAFT", "BOOKED", "ACTIVE"):
        raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE")
    assignments = calc.contract_assignments(contract["id"])
    for a in assignments:
        if a["status"] in ("CONFIRMED", "LOADED"):
            raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE",
                           "A contract with committed barges cannot be cancelled.")
    contract["movement_status"] = "CANCELLED"
    if contract["billing_status"] == "NOT_BILLED":
        contract["billing_status"] = "VOID"
    if reason is not None:
        contract["reason"] = reason
    touch(contract)
    for a in assignments:
        if a["status"] == "PLANNED":
            calc.drop_assignment(a)
    return ok(ser_contract(contract))


@bp.post("/freight-contracts/<freight_contract_id>/issue-invoice")
def issue_invoice(freight_contract_id):
    authenticate(["ContractManager"])
    body = get_body()
    expected_shipper_version = f_int(body, "expected_shipper_version")
    contract = fetch(store.freight_contracts, freight_contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    if contract["billing_status"] != "NOT_BILLED":
        raise ApiError("ERR_CONTRACT_BILLING_INVALID_STATE")
    if contract["movement_status"] not in ("IN_TRANSIT", "DISCHARGED"):
        raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE")
    shipper = store.shippers.get(contract["shipper_id"])
    if shipper is None or expected_shipper_version != shipper["version"]:
        raise ApiError("ERR_STALE_SHIPPER_VERSION")
    billable = [a for a in calc.contract_assignments(contract["id"])
                if a["discharge_status"] in calc.BILLABLE_DISCHARGE_STATUSES]
    if not billable:
        raise ApiError("ERR_NO_BILLABLE_LINES")

    result = calc.compute_breakdown(contract, "FINAL")
    for key in ("linehaul_cents", "fuel_surcharge_cents", "fleeting_fee_cents",
                "cleaning_fee_cents", "demurrage_cents", "subtotal_cents",
                "volume_rebate_cents", "total_cents"):
        contract[key] = result[key]
    contract["billing_status"] = "INVOICED"
    touch(contract)
    calc.credit_shipper(shipper, contract["total_cents"])
    return ok(ser_contract(contract))


@bp.post("/freight-contracts/<freight_contract_id>/mark-paid")
def mark_paid(freight_contract_id):
    authenticate(["ContractManager"])
    body = get_body()
    paid_amount_cents = f_int(body, "paid_amount_cents")
    contract = fetch(store.freight_contracts, freight_contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    if contract["billing_status"] not in ("INVOICED", "ADJUSTED"):
        raise ApiError("ERR_CONTRACT_BILLING_INVALID_STATE")
    if contract["movement_status"] != "DISCHARGED":
        raise ApiError("ERR_CONTRACT_MOVEMENT_INVALID_STATE")
    if paid_amount_cents != contract["total_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")
    contract["billing_status"] = "PAID"
    contract["movement_status"] = "CLOSED"
    touch(contract)
    shipper = store.shippers.get(contract["shipper_id"])
    if shipper is not None:
        calc.relieve_shipper(shipper, contract["total_cents"])
    return ok(ser_contract(contract))


@bp.get("/freight-contracts/<freight_contract_id>")
def get_contract(freight_contract_id):
    authenticate(ALL_ROLES)
    return ok(ser_contract(fetch(store.freight_contracts, freight_contract_id,
                                 "ERR_FREIGHT_CONTRACT_NOT_FOUND")))


@bp.get("/freight-contracts/<freight_contract_id>/charge-breakdown")
def charge_breakdown(freight_contract_id):
    authenticate(ALL_ROLES)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "PROVISIONAL"
    if variant not in VARIANTS:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter 'variant' must be PROVISIONAL or FINAL.")
    contract = fetch(store.freight_contracts, freight_contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    return ok(calc.compute_breakdown(contract, variant))


@bp.get("/freight-contracts")
def list_contracts():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.freight_contracts),
                         [("shipper_id", "shipper_id"),
                          ("commodity_id", "commodity_id"),
                          ("pinned_tariff_filing_id", "pinned_tariff_filing_id"),
                          ("movement_status", "movement_status"),
                          ("billing_status", "billing_status")])
    return paged_response(rows, ser_contract, limit, offset)


# ---------------------------------------------------------------------------
# Cargo claims
# ---------------------------------------------------------------------------
@bp.post("/cargo-claims")
def file_claim():
    authenticate(["ClaimsAdjuster", "Shipper"])
    body = get_body()
    contract_id = f_str(body, "freight_contract_id")
    assignment_id = f_str(body, "barge_assignment_id")
    claim_type = f_enum(body, "claim_type", CLAIM_TYPES)
    claimed_tons = f_num(body, "claimed_tons", gt=0)
    claimed_amount_cents = f_int(body, "claimed_amount_cents", gt=0)
    contract = fetch(store.freight_contracts, contract_id,
                     "ERR_FREIGHT_CONTRACT_NOT_FOUND")
    assignment = fetch(store.barge_assignments, assignment_id,
                       "ERR_BARGE_ASSIGNMENT_NOT_FOUND")
    # priority 7
    if caller_role() == "Shipper" and caller_id() != contract["shipper_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # priority 23
    finished = assignment.get("unload_finished_at")
    if finished is not None:
        if clock.now() > finished + timedelta(days=calc.CLAIM_FILING_WINDOW_DAYS):
            raise ApiError("ERR_CLAIM_WINDOW_EXPIRED")
    # priority 28
    for c in store.cargo_claims.values():
        if (c["barge_assignment_id"] == assignment_id
                and c["status"] not in ("WITHDRAWN", "DENIED")):
            raise ApiError("ERR_CLAIM_ALREADY_FILED")
    # priority 30
    if assignment["freight_contract_id"] != contract_id:
        raise ApiError("ERR_ASSIGNMENT_CONTRACT_MISMATCH")
    # priority 31
    if claim_type == "SHORTAGE":
        if assignment["discharge_status"] not in calc.BILLABLE_DISCHARGE_STATUSES:
            raise ApiError("ERR_SHORTAGE_NOT_SUPPORTED")
        shortfall = dec(assignment["loaded_tons"]) - dec(
            assignment.get("discharged_tons") or 0)
        if dec(claimed_tons) > shortfall:
            raise ApiError("ERR_SHORTAGE_NOT_SUPPORTED")

    rec = make_record({
        "freight_contract_id": contract_id,
        "barge_assignment_id": assignment_id,
        "claim_type": claim_type,
        "claimed_tons": claimed_tons,
        "claimed_amount_cents": claimed_amount_cents,
        "shortage_tons": 0,
        "tolerance_tons": 0,
        "settlement_deductible_cents": 0,
        "settlement_franchise_cents": 0,
        "settlement_cents": 0,
        "revision_round": 0,
        "status": "SUBMITTED",
        "assessed_by_user_id": None,
        "approved_by_user_id": None,
        "denial_reason": None,
        "info_request_note": None,
        "response_note": None,
    })
    store.cargo_claims[rec["id"]] = rec
    shipper = store.shippers.get(contract["shipper_id"])
    if shipper is not None:
        shipper["open_claim_count"] += 1
        touch(shipper)
    return created(ser_claim(rec))


@bp.post("/cargo-claims/<cargo_claim_id>/begin-review")
def begin_review(cargo_claim_id):
    authenticate(["ClaimsAdjuster"])
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/cargo-claims/<cargo_claim_id>/request-info")
def request_info(cargo_claim_id):
    authenticate(["ClaimsAdjuster"])
    body = get_body()
    note = f_str(body, "info_request_note")
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    if claim["revision_round"] >= calc.MAX_CLAIM_REVISION_ROUNDS:
        raise ApiError("ERR_CLAIM_REVISION_LIMIT")
    claim["status"] = "INFO_REQUESTED"
    claim["info_request_note"] = note
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/cargo-claims/<cargo_claim_id>/resume-review")
def resume_review(cargo_claim_id):
    authenticate(["ClaimsAdjuster"])
    body = get_body()
    note = f_str(body, "response_note")
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    if claim["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "UNDER_REVIEW"
    claim["response_note"] = note
    claim["revision_round"] += 1
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/cargo-claims/<cargo_claim_id>/assess")
def assess(cargo_claim_id):
    authenticate(["ClaimsAdjuster"])
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    contract = store.freight_contracts.get(claim["freight_contract_id"])
    assignment = store.barge_assignments.get(claim["barge_assignment_id"])
    calc.assess_claim(claim, contract, assignment)
    claim["status"] = "ASSESSED"
    claim["assessed_by_user_id"] = caller_id()
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/cargo-claims/<cargo_claim_id>/approve")
def approve(cargo_claim_id):
    authenticate(["ClaimsAdjuster"])
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    # priority 8 sits above the state precondition
    if (claim.get("assessed_by_user_id") is not None
            and caller_id() == claim["assessed_by_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if claim["status"] != "ASSESSED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    contract = store.freight_contracts.get(claim["freight_contract_id"])
    if contract is None or contract["billing_status"] != "INVOICED":
        raise ApiError("ERR_CONTRACT_BILLING_INVALID_STATE")

    basis = contract["claim_settlement_basis"]
    settlement = (claim["settlement_franchise_cents"] if basis == "FRANCHISE"
                  else claim["settlement_deductible_cents"])
    claim["status"] = "APPROVED"
    claim["settlement_cents"] = settlement
    claim["approved_by_user_id"] = caller_id()
    touch(claim)

    contract["claim_credit_cents"] = contract.get("claim_credit_cents", 0) + settlement
    contract["total_cents"] = max(0, contract["subtotal_cents"]
                                  - contract["volume_rebate_cents"]
                                  - contract["claim_credit_cents"])
    contract["billing_status"] = "ADJUSTED"
    touch(contract)

    shipper = store.shippers.get(contract["shipper_id"])
    if shipper is not None:
        calc.relieve_shipper(shipper, settlement)
        shipper["open_claim_count"] = max(0, shipper["open_claim_count"] - 1)
        touch(shipper)

    assignment = store.barge_assignments.get(claim["barge_assignment_id"])
    if assignment is not None and assignment["discharge_status"] == "COMPLETED":
        assignment["discharge_status"] = "DISPUTED"
        touch(assignment)
    return ok(ser_claim(claim))


@bp.post("/cargo-claims/<cargo_claim_id>/deny")
def deny(cargo_claim_id):
    authenticate(["ClaimsAdjuster"])
    body = get_body()
    denial_reason = f_str(body, "denial_reason")
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    if (claim.get("assessed_by_user_id") is not None
            and caller_id() == claim["assessed_by_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if claim["status"] != "ASSESSED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    claim["settlement_cents"] = 0
    touch(claim)
    _decrement_open_claims(claim)
    return ok(ser_claim(claim))


@bp.post("/cargo-claims/<cargo_claim_id>/withdraw")
def withdraw(cargo_claim_id):
    authenticate(["ClaimsAdjuster", "Shipper"])
    claim = fetch(store.cargo_claims, cargo_claim_id, "ERR_CARGO_CLAIM_NOT_FOUND")
    contract = store.freight_contracts.get(claim["freight_contract_id"])
    if caller_role() == "Shipper":
        if contract is None or caller_id() != contract["shipper_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if claim["status"] not in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"):
        raise ApiError("ERR_CLAIM_INVALID_STATE")
    claim["status"] = "WITHDRAWN"
    touch(claim)
    _decrement_open_claims(claim)
    return ok(ser_claim(claim))


def _decrement_open_claims(claim):
    contract = store.freight_contracts.get(claim["freight_contract_id"])
    if contract is None:
        return
    shipper = store.shippers.get(contract["shipper_id"])
    if shipper is None:
        return
    shipper["open_claim_count"] = max(0, shipper["open_claim_count"] - 1)
    touch(shipper)


@bp.get("/cargo-claims/<cargo_claim_id>")
def get_claim(cargo_claim_id):
    authenticate(ALL_ROLES)
    return ok(ser_claim(fetch(store.cargo_claims, cargo_claim_id,
                              "ERR_CARGO_CLAIM_NOT_FOUND")))


@bp.get("/cargo-claims")
def list_claims():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = apply_filters(sorted_rows(store.cargo_claims),
                         [("freight_contract_id", "freight_contract_id"),
                          ("barge_assignment_id", "barge_assignment_id"),
                          ("status", "status")])
    return paged_response(rows, ser_claim, limit, offset)
