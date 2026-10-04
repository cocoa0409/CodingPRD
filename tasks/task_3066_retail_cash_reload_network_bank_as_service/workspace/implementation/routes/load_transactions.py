"""Load transaction endpoints: taking cash at the register, funding, reversal
and re-instatement."""

from decimal import Decimal

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

from flask import Blueprint, request

bp = Blueprint("load_transactions", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)

REVERSAL_REASONS = (
    "AML_CONFIRMED",
    "DISPUTE_FAVOR_CARDHOLDER",
    "RETAILER_REQUEST",
    "STRUCTURING",
)


def personalised(load, batch=None):
    out = core.public(core.LOAD_TRANSACTION, load)
    out["settlement_batch_id"] = (
        load["settlement_batch_id"] if load["settlement_batch_id"] else None
    )
    return out


@bp.post("/v1/load-transactions")
def create_load():
    user_id, role = middleware.authenticate(("RetailerClerk",))
    data = rh.body()
    location_id = rh.require_str(data, "reload_location_id")
    account_id = rh.require_str(data, "card_account_id")

    location = core.ref_location(location_id)
    account = core.ref_account(account_id)
    agreement = core.agreement_of_location(location)
    program = core.get_program(agreement["program_id"])

    # The clerk may accept cash only at a location governed by its own agreement.
    if agreement["id"] != user_id:
        raise errors.unauthorized(
            "The acting retailer clerk is not the agreement governing this location."
        )

    principal = rh.require_int(data, "principal_cents")
    expected_account_version = rh.require_int(data, "expected_card_account_version")

    core.guard_not_frozen(program)
    core.guard_not_restricted(program)
    if agreement["agreement_status"] != "ACTIVE":
        raise errors.agreement_not_active(
            "The retailer agreement is %s, not ACTIVE." % agreement["agreement_status"]
        )
    if location["location_status"] != "OPEN":
        raise errors.location_not_open(
            "The reload location is %s, not OPEN." % location["location_status"]
        )
    if core.applied_hold_status(account) != "CLEAR":
        raise errors.account_frozen(
            "The card account hold dimension is %s." % core.applied_hold_status(account)
        )
    if core.has_non_terminal_alert(account["id"]) or core.has_unresolved_confirmed_alert(
        account["id"]
    ):
        raise errors.aml_alert_pending(
            "A live AML alert references this card account."
        )
    if expected_account_version != account["version"]:
        raise errors.stale_version()

    # Admission control, in the pinned order.
    if principal < calc.MIN_LOAD_PRINCIPAL_CENTS:
        raise errors.minimum_load_amount(
            "principal_cents must be at least %d." % calc.MIN_LOAD_PRINCIPAL_CENTS
        )
    effective_limit = core.effective_per_transaction_limit(location)
    if principal > effective_limit:
        raise errors.per_transaction_limit_exceeded(
            "principal_cents exceeds the effective per-transaction limit of %d." % effective_limit
        )
    fee = calc.convenience_fee_cents(principal)
    total = calc.posted_total_cents(principal, fee)
    if (
        core._dec(location["daily_accepted_cents"]) + core._dec(total)
        > core._dec(agreement["daily_location_limit_cents"])
    ):
        raise errors.daily_location_limit_exceeded(
            "The load would push the location past its daily location limit."
        )
    if (
        calc.STRUCTURING_LOWER_CENTS <= principal <= calc.STRUCTURING_UPPER_CENTS
        and int(account["structuring_txn_count"]) >= calc.STRUCTURING_TXN_COUNT
    ):
        raise errors.structuring_band(
            "The structuring band is closed while the account is flagged."
        )

    row = core.common_fields()
    row.update(
        {
            "reload_location_id": location["id"],
            "card_account_id": account["id"],
            "settlement_batch_id": None,
            "principal_cents": principal,
            "convenience_fee_cents": fee,
            "posted_total_cents": total,
            "retailer_fee_share_cents": calc.retailer_fee_share_cents(
                fee, agreement["fee_split_retailer_pct"]
            ),
            "program_fee_share_cents": None,
            "load_status": "INITIATED",
            "reversal_reason": "NONE",
            "risk_flag": "NONE",
            "funded_at": None,
            "reversed_at": None,
            "epoch_index": timeutil.current_epoch_index(),
            "decline_reason": None,
        }
    )
    row["program_fee_share_cents"] = calc.num(
        Decimal(str(fee)) - Decimal(str(row["retailer_fee_share_cents"]))
    )
    row["risk_flag"] = (
        "STRUCTURING"
        if _creation_trips_structuring(account, principal)
        else "NONE"
    )
    db.register(db.load_transactions, row)
    core.touch(account)
    return response.ok(personalised(row), 201)


def _creation_trips_structuring(account, principal):
    """Would the creation itself trip the structuring predicate?"""
    if not (calc.STRUCTURING_LOWER_CENTS <= principal <= calc.STRUCTURING_UPPER_CENTS):
        return False
    count = int(account["structuring_txn_count"]) + 1
    total = int(account.get("_structuring_total_cents", 0)) + principal
    return count >= calc.STRUCTURING_TXN_COUNT and total >= calc.STRUCTURING_MIN_TOTAL_CENTS


@bp.get("/v1/load-transactions/<load_id>")
def get_load(load_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(personalised(core.get_load(load_id)))


@bp.get("/v1/load-transactions")
def list_loads():
    middleware.authenticate(READ_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.load_transactions,
        reload_location_id=request.args.get("reload_location_id"),
        card_account_id=request.args.get("card_account_id"),
        settlement_batch_id=request.args.get("settlement_batch_id"),
        load_status=request.args.get("load_status"),
    )
    total = len(rows)
    return response.array(
        [personalised(r) for r in rows[offset : offset + limit]], limit, offset, total
    )


# --- funding ------------------------------------------------------------------
@bp.post("/v1/load-transactions/<load_id>/fund")
def fund_load(load_id):
    user_id, role = middleware.authenticate(("RetailerClerk",))
    load = core.get_load(load_id)
    location = core.get_location(load["reload_location_id"])
    agreement = core.agreement_of_location(location)
    program = core.get_program(agreement["program_id"])
    account = core.get_account(load["card_account_id"])

    if agreement["id"] != user_id:
        raise errors.unauthorized(
            "The acting retailer clerk is not the agreement governing this load."
        )
    if load["load_status"] != "INITIATED":
        # PRD 3.4 names ERR_ALREADY_TERMINAL explicitly for a DECLINED load; any
        # other source state the machine does not permit is ERR_INVALID_STATE (2.4).
        if load["load_status"] in ("DECLINED", "SETTLED"):
            raise errors.already_terminal(
                "A load in status %s can no longer be funded." % load["load_status"]
            )
        raise errors.invalid_state(
            "A load in status %s can no longer be funded." % load["load_status"]
        )
    if core.applied_hold_status(account) != "CLEAR":
        raise errors.account_frozen(
            "The card account hold dimension is %s." % core.applied_hold_status(account)
        )
    if program["compliance_posture"] != "OPEN":
        raise errors.program_frozen("The program is not OPEN.")

    core.recompute_account_window(account)
    candidate_count = int(account["window_load_count"]) + 1
    candidate_cents = int(account["window_load_cents"]) + int(load["principal_cents"])
    if candidate_count > calc.VELOCITY_TXN_LIMIT or candidate_cents > calc.VELOCITY_AMOUNT_LIMIT_CENTS:
        raise errors.velocity_limit_exceeded(
            "Funding this load would push the account window past a velocity limit."
        )

    load["load_status"] = "FUNDED"
    load["funded_at"] = timeutil.now()
    core.touch(load)

    account["balance_cents"] = int(account["balance_cents"]) + int(load["principal_cents"])
    account["ledger_posted_cents"] = int(account["ledger_posted_cents"]) + int(
        load["principal_cents"]
    )
    account["funding_status"] = calc.funding_status_of(
        account["ledger_posted_cents"], account["balance_cents"]
    )
    core.recompute_account_window(account)
    account["funding_status"] = calc.funding_status_of(
        account["ledger_posted_cents"], account["balance_cents"]
    )
    core.touch(account)

    core.rollover_location(location)
    location["daily_accepted_cents"] = core.money_add(
        location["daily_accepted_cents"], load["posted_total_cents"]
    )
    location["daily_txn_count"] = int(location["daily_txn_count"]) + 1
    core.recompute_location(location)
    core.touch(location)

    agreement["accrual_pending_cents"] = calc.num(
        Decimal(str(agreement["accrual_pending_cents"]))
        + Decimal(str(load["retailer_fee_share_cents"]))
    )
    agreement["float_position_cents"] = core.money_add(
        agreement["float_position_cents"], load["posted_total_cents"]
    )
    core.touch(agreement)

    core.maybe_raise_velocity_alert(program, account)
    core.recompute_program(program)
    core.touch(program)
    return response.ok(personalised(load))


# --- decline ------------------------------------------------------------------
@bp.post("/v1/load-transactions/<load_id>/decline")
def decline_load(load_id):
    user_id, role = middleware.authenticate(("RetailerClerk",))
    load = core.get_load(load_id)
    location = core.get_location(load["reload_location_id"])
    agreement = core.agreement_of_location(location)
    if agreement["id"] != user_id:
        raise errors.unauthorized(
            "The acting retailer clerk is not the agreement governing this load."
        )
    if load["load_status"] != "INITIATED":
        raise errors.already_terminal(
            "A load in status %s can no longer be declined." % load["load_status"]
        )
    data = rh.body()
    load["load_status"] = "DECLINED"
    load["reversal_reason"] = "NONE"
    load["decline_reason"] = rh.optional(data, "decline_reason")
    core.touch(load)
    return response.ok(personalised(load))


# --- reversal -----------------------------------------------------------------
@bp.post("/v1/load-transactions/<load_id>/reverse")
def reverse_load_route(load_id):
    middleware.authenticate(("ComplianceAnalyst", "ComplianceOfficer"))
    load = core.get_load(load_id)
    data = rh.body()
    reason = rh.require_str(data, "reversal_reason")
    expected = rh.require_int(data, "expected_load_transaction_version")

    if load["load_status"] != "FUNDED":
        raise errors.invalid_state(
            "A load in status %s cannot be reversed." % load["load_status"]
        )
    if reason not in REVERSAL_REASONS:
        raise errors.invalid_request(
            "reversal_reason must be one of %s." % ", ".join(REVERSAL_REASONS)
        )
    if expected != load["version"]:
        raise errors.stale_version()

    core.reverse_load(load, reason)
    return response.ok(personalised(load))


# --- re-instatement -----------------------------------------------------------
@bp.post("/v1/load-transactions/<load_id>/reinstate")
def reinstate_load(load_id):
    middleware.authenticate(("ComplianceOfficer",))
    load = core.get_load(load_id)
    account = core.get_account(load["card_account_id"])
    program = core.get_program(account["program_id"])

    data = rh.body()
    expected_load = rh.require_int(data, "expected_load_transaction_version")
    expected_account = rh.require_int(data, "expected_card_account_version")

    if load["load_status"] != "REVERSED":
        raise errors.load_not_reversed(
            "A load in status %s is not REVERSED." % load["load_status"]
        )
    if expected_load != load["version"] or expected_account != account["version"]:
        raise errors.stale_version()
    if core.allocations_covering(load["id"]):
        raise errors.invalid_state(
            "A POSTED or RECOVERED loss allocation references this load."
        )
    if core.applied_hold_status(account) == "FROZEN":
        raise errors.account_frozen("The card account is FROZEN.")

    was_aml_confirmed = load["reversal_reason"] == "AML_CONFIRMED"
    load["load_status"] = "SETTLED"
    load["settlement_batch_id"] = None
    core.touch(load)

    account["balance_cents"] = int(account["balance_cents"]) + int(load["principal_cents"])
    account["ledger_reversed_cents"] = int(account["ledger_reversed_cents"]) - int(
        load["principal_cents"]
    )
    account["funding_status"] = "FUNDED"
    core.touch(account)

    if was_aml_confirmed:
        program["unallocated_confirmed_loss_cents"] = max(
            0, int(program["unallocated_confirmed_loss_cents"]) - int(load["principal_cents"])
        )
    core.recompute_program(program)
    core.touch(program)
    return response.ok(personalised(load))