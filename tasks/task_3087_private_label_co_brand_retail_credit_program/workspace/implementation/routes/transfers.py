"""Wind-down portfolio transfers and the delegated purchase right (PRD §3.9)."""
from flask import request

from core import auth, clock, computations, domain
from core.auth import optional_field, require_field
from core.errors import ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single

_VALID_BUYER_ROLES = ("RETAILER", "ISSUER")


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def register(app):

    @app.post("/servicing/transfer-agreements")
    def create_transfer():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        program_id = require_field(payload, "program_id", "string")
        buyer_role = auth.enum_field(payload, "buyer_role", _VALID_BUYER_ROLES)
        proposed = optional_field(payload, "proposed_price_cents", "int")

        program = store.programs.get(program_id)
        if not program:
            raise _not_found("CreditProgram")
        agreement = store.agreements.get(program.get("agreement_id"))
        if not agreement:
            raise _not_found("ProgramAgreement")

        book_value = program.get("outstanding_receivable_cents", 0)
        rate = agreement.get("purchase_right_rate", computations.PURCHASE_RIGHT_RATE_DEFAULT)
        floor = computations.money(computations.dec(book_value) * computations.dec(rate))
        if proposed is not None and proposed < floor:
            raise fail("ERR_PURCHASE_PRICE_BELOW_FLOOR",
                       "The proposed price is below book value times purchase_right_rate.")
        purchase_price = proposed if proposed is not None else floor

        transfer = add("transfers", {
            "program_id": program_id,
            "buyer_role": buyer_role,
            "transfer_status": "PROPOSED",
            "portfolio_book_value_cents": book_value,
            "purchase_right_rate": rate,
            "purchase_price_cents": purchase_price,
            "accepted_by_role": None,
            "transfer_executed_at": None,
        })
        return single(transfer, 201)

    @app.get("/servicing/transfer-agreements")
    def list_transfers():
        auth.require_role("ProgramAdmin", "Underwriter", "CoBrandIssuer")
        return listing(list(store.transfers.values()),
                       {"program_id": request.args.get("program_id")})

    @app.get("/servicing/transfer-agreements/<transfer_id>")
    def read_transfer(transfer_id):
        auth.require_role("ProgramAdmin", "Underwriter", "CoBrandIssuer")
        transfer = store.transfers.get(transfer_id)
        if not transfer:
            raise _not_found("WindDownTransfer")
        return single(transfer)

    @app.post("/servicing/transfer-agreements/<transfer_id>/accept")
    def accept_transfer(transfer_id):
        _user_id, role = auth.require_role("ProgramAdmin", "CoBrandIssuer")
        transfer = store.transfers.get(transfer_id)
        if not transfer:
            raise _not_found("WindDownTransfer")
        payload = auth.body()
        accepted_by = require_field(payload, "accepted_by_role", "string")
        if accepted_by not in _VALID_BUYER_ROLES:
            raise fail("ERR_INVALID_REQUEST", "accepted_by_role must be RETAILER or ISSUER.")
        if role == "CoBrandIssuer" and accepted_by != "ISSUER":
            raise fail("ERR_UNAUTHORIZED",
                       "A CoBrandIssuer may accept only as the ISSUER buyer.")
        if transfer["transfer_status"] != "PROPOSED":
            raise fail(ERR_INVALID_STATE, "Only a PROPOSED transfer can be accepted.")
        transfer["transfer_status"] = "AGREEMENT_REACHED"
        transfer["accepted_by_role"] = accepted_by
        touch(transfer)
        return single(transfer)

    @app.post("/servicing/transfer-agreements/<transfer_id>/execute")
    def execute_transfer(transfer_id):
        auth.require_role("ProgramAdmin")
        transfer = store.transfers.get(transfer_id)
        if not transfer:
            raise _not_found("WindDownTransfer")
        if transfer["transfer_status"] != "AGREEMENT_REACHED":
            raise fail(ERR_INVALID_STATE, "Only an AGREEMENT_REACHED transfer can be executed.")
        program = store.programs.get(transfer["program_id"])
        if not program:
            raise _not_found("CreditProgram")
        accounts = domain.accounts_of_program(program["id"])
        if any(a.get("account_status") not in ("PAID_OFF", "TRANSFERRED") for a in accounts):
            raise fail(ERR_INVALID_STATE,
                       "Every account on the program must be PAID_OFF or TRANSFERRED before execution.")
        # Hop 1: cascade every account on the program to TRANSFERRED.
        for account in accounts:
            account["account_status"] = "TRANSFERRED"
            account["updated_at"] = clock.now_iso()
        transfer["transfer_status"] = "COMPLETED"
        transfer["transfer_executed_at"] = clock.now_iso()
        touch(transfer)
        program["program_status"] = "WINDING_DOWN"
        touch(program)
        domain.refresh_program(program)
        return single(transfer)

    @app.post("/servicing/transfer-agreements/<transfer_id>/withdraw")
    def withdraw_transfer(transfer_id):
        auth.require_role("ProgramAdmin")
        transfer = store.transfers.get(transfer_id)
        if not transfer:
            raise _not_found("WindDownTransfer")
        status = transfer["transfer_status"]
        if status == "AGREEMENT_REACHED":
            transfer["transfer_status"] = "PROPOSED"
            transfer["accepted_by_role"] = None
        elif status == "PROPOSED":
            transfer["transfer_status"] = "WITHDRAWN"
        else:
            raise fail(ERR_INVALID_STATE,
                       "Only a PROPOSED or AGREEMENT_REACHED transfer can be withdrawn.")
        touch(transfer)
        return single(transfer)