"""Card account endpoints and the compliance hold dimension machine."""

from flask import Blueprint, request

import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

bp = Blueprint("card_accounts", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)
LIST_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
)


def personalised(account):
    core.refresh_account(account)
    out = core.public(core.CARD_ACCOUNT, account)
    out["compliance_hold_status"] = core.applied_hold_status(account)
    out.pop("_structuring_total_cents", None)
    return out


@bp.post("/v1/card-accounts")
def create_account():
    user_id, role = middleware.authenticate(("PlatformAdmin", "ProgramManager"))
    data = rh.body()
    program_id = rh.require_str(data, "program_id")
    brand_id = rh.require_str(data, "brand_partner_id")
    account_ref = rh.require_str(data, "account_ref")
    cardholder_name = rh.require_str(data, "cardholder_name")
    agreement_type = rh.require_enum(
        data, "cardholder_agreement_type", ("REG_E", "VOLUNTARY", "CORPORATE")
    )

    program = core.ref_program(program_id)
    if role == "ProgramManager" and program["id"] != user_id:
        raise errors.unauthorized("The acting program manager does not own this program.")
    brand = core.ref_brand(brand_id)
    if brand["program_id"] != program["id"]:
        raise errors.invalid_request(
            "brand_partner_id does not belong to the named program."
        )
    core.guard_not_frozen(program)

    for existing in db.card_accounts.values():
        if existing["program_id"] == program["id"] and existing["account_ref"] == account_ref:
            raise errors.invalid_request(
                "account_ref %r is already used within this program." % (account_ref,)
            )

    row = core.common_fields()
    row.update(
        {
            "program_id": program["id"],
            "brand_partner_id": brand["id"],
            "account_ref": account_ref,
            "cardholder_name": cardholder_name,
            "cardholder_agreement_type": agreement_type,
            "balance_cents": 0,
            "ledger_posted_cents": 0,
            "ledger_reversed_cents": 0,
            "funding_status": "UNFUNDED",
            "compliance_hold_status": "CLEAR",
            "window_load_count": 0,
            "window_load_cents": 0,
            "structuring_txn_count": 0,
            "is_structuring": False,
            "frozen_at": None,
        }
    )
    db.register(db.card_accounts, row)
    return response.ok(personalised(row), 201)


@bp.get("/v1/card-accounts/<account_id>")
def get_account(account_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(personalised(core.get_account(account_id)))


@bp.get("/v1/card-accounts")
def list_accounts():
    middleware.authenticate(LIST_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.card_accounts,
        program_id=request.args.get("program_id"),
        brand_partner_id=request.args.get("brand_partner_id"),
    )
    total = len(rows)
    return response.array(
        [personalised(r) for r in rows[offset : offset + limit]], limit, offset, total
    )


# --- hold dimension machine ---------------------------------------------------
@bp.post("/v1/card-accounts/<account_id>/hold")
def move_hold(account_id):
    middleware.authenticate(("ComplianceAnalyst", "ComplianceOfficer"))
    account = core.get_account(account_id)
    program = core.get_program(account["program_id"])

    data = rh.body()
    to_hold = rh.require_enum(data, "to_hold_status", ("CLEAR", "REVIEW", "FROZEN"))
    current = core.applied_hold_status(account)

    if to_hold == current:
        raise errors.invalid_state("The account's hold dimension is already %s." % current)

    if to_hold != "FROZEN" and core.programme_frozen(program):
        raise errors.program_frozen(
            "A frozen program holds every account of the program at FROZEN."
        )

    if current == "CLEAR" and to_hold == "REVIEW":
        account["compliance_hold_status"] = "REVIEW"
        core.touch(account)
        return response.ok(personalised(account))

    if current == "REVIEW" and to_hold == "CLEAR":
        if core.has_non_terminal_alert(account["id"]):
            raise errors.aml_alert_pending(
                "A non-terminal AML alert references this account."
            )
        if core.programme_frozen(program):
            raise errors.program_frozen(
                "A frozen program holds every account of the program at FROZEN."
            )
        account["compliance_hold_status"] = "CLEAR"
        account["frozen_at"] = None
        core.touch(account)
        return response.ok(personalised(account))

    if to_hold == "FROZEN":
        if current == "CLEAR":
            has_confirmed = any(
                a["alert_status"] == "CONFIRMED" for a in core.alerts_of_account(account["id"])
            )
            if not has_confirmed and not core.programme_frozen(program):
                raise errors.invalid_state(
                    "Freezing a CLEAR account requires a CONFIRMED alert or a frozen program."
                )
        frozen_ids = _freeze_account(account)
        core.recover_allocations_for(frozen_ids)
        core.recompute_program(program)
        core.touch(program)
        return response.ok(personalised(account))

    # FROZEN -> REVIEW (PRD §3.6: leaving FROZEN goes only to REVIEW, never
    # straight to CLEAR).
    if to_hold != "REVIEW":
        raise errors.invalid_state(
            "Leaving FROZEN goes only to REVIEW, never straight to %s." % to_hold
        )
    account["compliance_hold_status"] = "REVIEW"
    account["frozen_at"] = None
    core.recompute_account_ledger(account)
    core.touch(account)
    return response.ok(personalised(account))


def _freeze_account(account):
    """hop 1..3 of the freeze cascade; returns the ids of the loads reversed."""
    program = core.get_program(account["program_id"])
    account["compliance_hold_status"] = "FROZEN"
    account["frozen_at"] = timeutil.now()
    core.touch(account)
    reversed_ids = []
    for load in core.account_loads(account):
        if load["load_status"] == "FUNDED":
            core.reverse_load(load, "AML_CONFIRMED", finalize=False)
            reversed_ids.append(load["id"])
    core.dismiss_stale_alerts(account)
    return reversed_ids