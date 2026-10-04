"""Rebate programs and accrual settlement (PRD §3.7): create (ChannelManager),
advance DRAFT->ACTIVE->CLOSED (FinanceController, SoD-gated activation), and
the claim/pay settlement ladder."""

from flask import Blueprint, request

import auth
import calcs
import cascades
import envelope
import serialization as ser
import store
import validation
from errors import api_err, invalid_request, invalid_state, not_found

bp = Blueprint("rebates", __name__)

PARTNER_TYPES = {"CONVERTER", "DISTRIBUTOR"}


def _get_program(pid):
    row = store.STORE["programs"].get(pid)
    if row is None:
        raise not_found("RebateProgram not found")
    return row


def _get_accrual(aid):
    row = store.STORE["accruals"].get(aid)
    if row is None:
        raise not_found("RebateAccrual not found")
    return row


def _validate_rebate_tiers(payload):
    tiers = validation.req_list(payload, "rebate_tiers")
    cleaned = []
    for entry in tiers:
        if not isinstance(entry, dict):
            raise invalid_request("rebate_tiers entries must be objects")
        threshold = validation.req_int(entry, "threshold_qty")
        rate = validation.req_number(entry, "rate_pct")
        cleaned.append({"threshold_qty": threshold, "rate_pct": rate})
    if not cleaned:
        raise invalid_request("rebate_tiers must be a non-empty array")
    for prev, curr in zip(cleaned, cleaned[1:]):
        if curr["threshold_qty"] < prev["threshold_qty"]:
            raise invalid_request(
                "rebate_tiers must be sorted by threshold_qty ascending")
    if cleaned[0]["threshold_qty"] != 0:
        raise invalid_request("rebate_tiers' first threshold_qty must be 0")
    return cleaned


@bp.post("/stewardship/rebate-programs")
def create_program():
    uid, role = auth.authenticate()
    auth.require_role(role, ["ChannelManager"])
    payload = validation.get_payload()
    formulation_id = validation.req_str(payload, "formulation_id")
    partner_type = validation.req_enum(payload, "partner_type", PARTNER_TYPES)
    period_start = validation.req_dt(payload, "period_start")
    period_end = validation.req_dt(payload, "period_end")
    validation.check_half_open_window(period_start, period_end,
                                      "period_start", "period_end")
    tiers = _validate_rebate_tiers(payload)
    budget_cap_cents = validation.req_int(payload, "budget_cap_cents")
    if budget_cap_cents <= 0:
        raise invalid_request("budget_cap_cents must be > 0")
    converter_id = validation.opt_str(payload, "converter_id")
    distributor_id = validation.opt_str(payload, "distributor_id")
    if converter_id is None and distributor_id is None:
        raise invalid_request(
            "Exactly one of converter_id / distributor_id must be set")
    if store.STORE["formulations"].get(formulation_id) is None:
        raise not_found("Formulation not found")
    if (converter_id is not None
            and store.STORE["converters"].get(converter_id) is None):
        raise not_found("Converter not found")
    if (distributor_id is not None
            and store.STORE["distributors"].get(distributor_id) is None):
        raise not_found("Distributor not found")
    # Priority 17: partner identity consistent with partner_type.
    if converter_id is not None and distributor_id is not None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "Both converter_id and distributor_id were supplied")
    if partner_type == "CONVERTER" and converter_id is None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "partner_type CONVERTER requires converter_id")
    if partner_type == "DISTRIBUTOR" and distributor_id is None:
        raise api_err("ERR_BUYER_AMBIGUOUS",
                      "partner_type DISTRIBUTOR requires distributor_id")
    row = store.stamp_new({
        "formulation_id": formulation_id,
        "partner_type": partner_type,
        "converter_id": converter_id,
        "distributor_id": distributor_id,
        "period_start": period_start,
        "period_end": period_end,
        "rebate_tiers": tiers,
        "budget_cap_cents": budget_cap_cents,
        "status": "DRAFT",
        "created_by": uid,
        "paid_out_cents": 0,
    })
    store.STORE["programs"][row["id"]] = row
    return envelope.success_object(ser.rebate_program(row), 201)


@bp.get("/stewardship/rebate-programs/<pid>")
def get_program(pid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.rebate_program(_get_program(pid)), 200)


@bp.get("/stewardship/rebate-programs")
def list_programs():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["programs"].values(), request.args,
        ["formulation_id", "converter_id", "distributor_id", "status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.rebate_program(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/rebate-programs/<pid>/advance")
def advance_program(pid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["FinanceController"])
    program = _get_program(pid)
    if program["status"] == "DRAFT":
        # Tier 4 segregation of duties: the creator may not activate.
        if uid == program["created_by"]:
            raise api_err(
                "ERR_SEGREGATION_OF_DUTIES",
                "The program's creator may not activate it")
        # An already-closed window cannot be opened.
        if not store.now() < program["period_end"]:
            raise invalid_state(
                "Cannot activate a program whose period has already ended")
        program["status"] = "ACTIVE"
        store.touch(program)
        # Activation spawns the partner's single PROVISIONAL accrual.
        accrual = store.stamp_new({
            "program_id": program["id"],
            "converter_id": program["converter_id"],
            "distributor_id": program["distributor_id"],
            "provisional_amount_cents": 0,
            "final_amount_cents": None,
            "excluded_order_count": 0,
            "status": "PROVISIONAL",
        })
        store.STORE["accruals"][accrual["id"]] = accrual
    elif program["status"] == "ACTIVE":
        # The period must have ended before close.
        if store.now() < program["period_end"]:
            raise invalid_state(
                "Cannot close a program before its period_end")
        program["status"] = "CLOSED"
        store.touch(program)
        accrual = cascades.accrual_for_program(program["id"])
        if accrual is not None and accrual["status"] == "PROVISIONAL":
            amount, excluded = calcs.rebate_accrual_amount(program, final=True)
            accrual["final_amount_cents"] = amount
            accrual["excluded_order_count"] = excluded
            accrual["status"] = "FINALIZED"
            store.touch(accrual)
    else:
        raise invalid_state("A CLOSED program cannot advance")
    return envelope.success_object(ser.rebate_program(program), 200)


@bp.get("/stewardship/rebate-accruals/<aid>")
def get_accrual(aid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.rebate_accrual(_get_accrual(aid)), 200)


@bp.get("/stewardship/rebate-accruals")
def list_accruals():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["accruals"].values(), request.args,
        ["program_id", "converter_id", "distributor_id", "status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.rebate_accrual(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/rebate-accruals/<aid>/claim")
def claim_accrual(aid):
    uid, role = auth.authenticate()
    auth.require_role(role, ["Converter", "Distributor"])
    accrual = _get_accrual(aid)
    # Tier 3 ownership: the accrual's partner claims its own accrual.
    if role == "Converter":
        if accrual["converter_id"] is None or accrual["converter_id"] != uid:
            raise api_err("ERR_OWNERSHIP_VIOLATION",
                          "Converter role may only claim its own accruals")
    else:
        if accrual["distributor_id"] is None or accrual["distributor_id"] != uid:
            raise api_err("ERR_OWNERSHIP_VIOLATION",
                          "Distributor role may only claim its own accruals")
    # Specialized state error at the same tier as ERR_INVALID_STATE.
    if accrual["status"] != "FINALIZED":
        raise api_err("ERR_ACCRUAL_NOT_FINALIZED",
                      "Only a FINALIZED accrual can be claimed")
    # Priority 28: budget gate — remaining cap must cover this accrual.
    program = store.STORE["programs"][accrual["program_id"]]
    committed = sum(
        a["final_amount_cents"] or 0
        for a in store.STORE["accruals"].values()
        if a["program_id"] == program["id"]
        and a["status"] in ("CLAIMED", "PAID"))
    if program["budget_cap_cents"] - committed < accrual["final_amount_cents"]:
        raise api_err("ERR_REBATE_BUDGET_EXCEEDED",
                      "Claim exceeds the program's remaining budget")
    accrual["status"] = "CLAIMED"
    store.touch(accrual)
    return envelope.success_object(ser.rebate_accrual(accrual), 200)


@bp.post("/stewardship/rebate-accruals/<aid>/pay")
def pay_accrual(aid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["FinanceController"])
    accrual = _get_accrual(aid)
    if accrual["status"] != "CLAIMED":
        raise invalid_state("Only a CLAIMED accrual can be paid")
    accrual["status"] = "PAID"
    store.touch(accrual)
    program = store.STORE["programs"][accrual["program_id"]]
    program["paid_out_cents"] += accrual["final_amount_cents"]
    store.touch(program)
    return envelope.success_object(ser.rebate_accrual(accrual), 200)
