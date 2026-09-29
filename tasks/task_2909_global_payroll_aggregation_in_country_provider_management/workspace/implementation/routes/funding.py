"""Treasury funding: drafting, dual authorization, release and recall."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import serial
import services
import store
import validate as v
from auth import require
from common import (
    ALL_ROLES,
    FUNDING_STATUSES,
    GLOBAL_PAYROLL_OPS,
    TREASURY_OFFICER,
    ApiError,
    date_str,
)
from response import created, object_response, page_response
from store import new_row, touch

bp = Blueprint("funding", __name__)


@bp.post("/payroll/funding-instructions")
@require(GLOBAL_PAYROLL_OPS, TREASURY_OFFICER)
def create_funding_instruction():
    body = v.json_body()
    cycle_id = v.req_id(body, "cycle_id")
    account_id = v.req_id(body, "bank_account_id")
    value_date = v.req_date(body, "value_date")
    currency = v.req_currency(body, "funding_currency")
    fx_rate = v.req_rate(body, "fx_rate")

    cycle = store.get_cycle(cycle_id)
    account = store.get_bank_account(account_id)

    if cycle["status"] != "RESULTS_APPROVED":
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "Funding may only be drafted for a cycle in RESULTS_APPROVED.",
        )
    if account["engagement_id"] != cycle["engagement_id"]:
        raise ApiError(
            "ERR_BANK_ACCOUNT_ENGAGEMENT_MISMATCH",
            "The local account belongs to another engagement.",
        )
    if currency == account["account_currency"]:
        raise ApiError(
            "ERR_CURRENCY_MISMATCH",
            "The funding currency must differ from the account currency.",
        )
    for other in store.funding_of_cycle(cycle["id"]):
        if other["status"] in ("DRAFT", "APPROVED", "RELEASED"):
            raise ApiError(
                "ERR_FUNDING_ALREADY_EXISTS",
                "The cycle already carries a live funding instruction.",
            )

    run = store.approved_run_of_cycle(cycle["id"])
    if run is None:
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE",
            "The cycle has no approved gross-to-net run to fund.",
        )
    requested_local, components, funded_source = calc.convert_funding(
        run["net_minor"], run["employer_cost_minor"], run["provider_fee_minor"], fx_rate
    )
    window_start, window_end = calc.settlement_window(
        value_date, account["settlement_window_hours"]
    )

    row = new_row(
        {
            "cycle_id": cycle["id"],
            "bank_account_id": account["id"],
            "value_date": date_str(value_date),
            "funding_currency": currency,
            "fx_rate": fx_rate,
            "requested_local_minor": requested_local,
            "component_source_minor": components,
            "funded_source_minor": funded_source,
            "window_start_at": window_start,
            "window_end_at": window_end,
            "status": "DRAFT",
            "approver_user_id": None,
            "releaser_user_id": None,
            "recall_reason": None,
        }
    )
    store.funding_instructions[row["id"]] = row
    return created(serial.funding_instruction(row))


@bp.get("/payroll/funding-instructions/<ident>")
@require(*ALL_ROLES)
def read_funding_instruction(ident):
    return object_response(serial.funding_instruction(store.get_funding(ident)))


@bp.get("/payroll/funding-instructions")
@require(*ALL_ROLES)
def list_funding_instructions():
    limit, offset = v.pagination()
    status = v.query_enum("status", FUNDING_STATUSES)
    cycle_id = v.query_value("cycle_id")
    account_id = v.query_value("bank_account_id")

    rows = list(store.funding_instructions.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if account_id is not None:
        rows = [r for r in rows if r["bank_account_id"] == account_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page_response(store.ordered(rows), serial.funding_instruction, limit, offset)


@bp.post("/payroll/funding-instructions/<ident>/approve")
@require(TREASURY_OFFICER)
def approve_funding_instruction(ident):
    instruction = store.get_funding(ident)
    cycle = store.get_cycle(instruction["cycle_id"])
    if instruction["status"] != "DRAFT":
        raise ApiError(
            "ERR_FUNDING_INVALID_STATE", "Only a DRAFT instruction can be approved."
        )
    if cycle["status"] != "RESULTS_APPROVED":
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE", "The cycle must still be in RESULTS_APPROVED."
        )
    instruction["approver_user_id"] = g.user_id
    instruction["status"] = "APPROVED"
    touch(instruction)
    return object_response(serial.funding_instruction(instruction))


@bp.post("/payroll/funding-instructions/<ident>/release")
@require(TREASURY_OFFICER)
def release_funding_instruction(ident):
    instruction = store.get_funding(ident)
    cycle = store.get_cycle(instruction["cycle_id"])
    account = store.get_bank_account(instruction["bank_account_id"])

    if instruction["approver_user_id"] is not None and (
        g.user_id == instruction["approver_user_id"]
    ):
        raise ApiError(
            "ERR_DUAL_AUTHORIZATION_REQUIRED",
            "The approver of an instruction may not release it.",
        )
    if instruction["status"] != "APPROVED":
        raise ApiError(
            "ERR_FUNDING_INVALID_STATE", "Only an APPROVED instruction can be released."
        )
    if cycle["status"] != "RESULTS_APPROVED":
        raise ApiError(
            "ERR_CYCLE_INVALID_STATE", "The cycle must still be in RESULTS_APPROVED."
        )
    if account["status"] != "VERIFIED":
        raise ApiError(
            "ERR_BANK_ACCOUNT_NOT_VERIFIED",
            "The destination account is not bank-verified.",
        )

    buffer_delta = timedelta(hours=account["buffer_hours"])
    extended_start = instruction["window_start_at"] - buffer_delta
    extended_end = instruction["window_end_at"] + buffer_delta
    for other in store.funding_instructions.values():
        if other["id"] == instruction["id"]:
            continue
        if other["bank_account_id"] != account["id"] or other["status"] != "RELEASED":
            continue
        if extended_start <= other["window_end_at"] and other["window_start_at"] <= extended_end:
            raise ApiError(
                "ERR_FUNDING_WINDOW_CONFLICT",
                "The buffered settlement window conflicts with a released instruction.",
            )

    total = instruction["requested_local_minor"]
    for other in store.funding_instructions.values():
        if other["id"] == instruction["id"]:
            continue
        if (
            other["bank_account_id"] == account["id"]
            and other["status"] == "RELEASED"
            and other["value_date"] == instruction["value_date"]
        ):
            total += other["requested_local_minor"]
    if total > account["daily_cap_minor"]:
        raise ApiError(
            "ERR_FUNDING_CAP_EXCEEDED",
            "The value date's released total would exceed the account's daily cap.",
        )

    instruction["releaser_user_id"] = g.user_id
    instruction["status"] = "RELEASED"
    touch(instruction)

    engagement = store.engagement_of_cycle(cycle)
    engagement["treasury_committed_minor"] += instruction["funded_source_minor"]
    touch(engagement)
    cycle["funded_total_minor"] += instruction["funded_source_minor"]
    cycle["status"] = "FUNDED"
    touch(cycle)
    services.mint_system_evidence(cycle["id"], "CTRL_FUNDING_DUAL_AUTH")
    return object_response(serial.funding_instruction(instruction))


@bp.post("/payroll/funding-instructions/<ident>/recall")
@require(TREASURY_OFFICER)
def recall_funding_instruction(ident):
    body = v.json_body()
    reason = v.req_str(body, "recall_reason", 10, None)

    instruction = store.get_funding(ident)
    cycle = store.get_cycle(instruction["cycle_id"])
    if instruction["status"] != "RELEASED":
        raise ApiError(
            "ERR_FUNDING_INVALID_STATE", "Only a RELEASED instruction can be recalled."
        )
    if cycle["status"] != "FUNDED":
        raise ApiError("ERR_CYCLE_INVALID_STATE", "The cycle must be in FUNDED.")

    amount = instruction["funded_source_minor"]
    instruction["recall_reason"] = reason
    instruction["status"] = "RECALLED"
    touch(instruction)

    engagement = store.engagement_of_cycle(cycle)
    engagement["treasury_committed_minor"] -= amount
    touch(engagement)
    cycle["funded_total_minor"] -= amount
    still_released = any(
        other["status"] == "RELEASED" for other in store.funding_of_cycle(cycle["id"])
    )
    if not still_released:
        cycle["status"] = "RESULTS_APPROVED"
    touch(cycle)
    return object_response(serial.funding_instruction(instruction))
