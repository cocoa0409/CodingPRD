"""CreditProgram lifecycle and the Application / instant-decisioning path
(PRD §3.2, §3.3)."""
from flask import request

from core import auth, clock, computations, domain
from core.auth import optional_field, require_field
from core.errors import ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single

_VALID_SOURCE_CHANNELS = ("IN_STORE", "DIGITAL", "PRESCREENED")


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def require_program(program_id):
    program = store.programs.get(program_id)
    if not program:
        raise _not_found("CreditProgram")
    return program


def require_application(application_id):
    application = store.applications.get(application_id)
    if not application:
        raise _not_found("Application")
    return application


def register(app):

    # --- CreditProgram ----------------------------------------------------

    @app.post("/servicing/credit-programs")
    def create_credit_program():
        auth.require_role("ProgramAdmin")
        payload = auth.body()
        partner_id = require_field(payload, "partner_id", "string")
        agreement_id = require_field(payload, "agreement_id", "string")
        cycle_day = require_field(payload, "cycle_day", "int")
        supersedes = optional_field(payload, "supersedes_program_id", "string")
        if not store.partners.get(partner_id):
            raise _not_found("RetailPartner")
        if not store.agreements.get(agreement_id):
            raise _not_found("ProgramAgreement")
        if supersedes is not None:
            predecessor = store.programs.get(supersedes)
            if not predecessor or predecessor.get("program_status") == "CLOSED":
                raise fail("ERR_SUPERSEDES_INVALID",
                           "supersedes_program_id must name an existing program that is not CLOSED.")
        if cycle_day < 1 or cycle_day > 31:
            raise fail("ERR_INVALID_REQUEST", "cycle_day must be between 1 and 31.")
        program = add("programs", {
            "partner_id": partner_id,
            "agreement_id": agreement_id,
            "program_status": "ACTIVE",
            "supersedes_program_id": supersedes,
            "outstanding_receivable_cents": 0,
            "free_look_exposure_cents": 0,
            "program_profitability_cents": 0,
            "cycle_day": cycle_day,
        })
        return single(program, 201)

    @app.get("/servicing/credit-programs")
    def list_credit_programs():
        auth.require_role("ProgramAdmin", "Underwriter", "CardholderService")
        return listing(list(store.programs.values()), {
            "partner_id": request.args.get("partner_id"),
            "agreement_id": request.args.get("agreement_id"),
            "supersedes_program_id": request.args.get("supersedes_program_id"),
        })

    @app.get("/servicing/credit-programs/<program_id>")
    def read_credit_program(program_id):
        auth.require_role("ProgramAdmin", "Underwriter", "CardholderService",
                          "RetailPartnerAnalyst", "CoBrandIssuer")
        return single(require_program(program_id))

    @app.post("/servicing/credit-programs/<program_id>/open-renewal")
    def open_renewal(program_id):
        auth.require_role("ProgramAdmin")
        program = require_program(program_id)
        payload = auth.body()
        expected = require_field(payload, "expected_program_version", "int")
        to_status = require_field(payload, "to_status", "string")
        status = program["program_status"]

        # A renewal round that fails is expressed by invoking the same
        # capability again against the RENEWAL_NEGOTIATION program with a
        # target status of WINDING_DOWN (PRD §3.2).
        if to_status == "WINDING_DOWN":
            if status not in ("ACTIVE", "RENEWAL_NEGOTIATION"):
                raise fail(ERR_INVALID_STATE,
                           "A failed renewal round can only roll a live program into wind-down.")
            if expected != program["version"]:
                raise fail("ERR_STALE_VERSION",
                           "expected_program_version does not match the program's current version.")
            program["program_status"] = "WINDING_DOWN"
            # Cascade hop 1: zero-balance accounts settle at wind-down; accounts
            # still carrying principal are left so they must be paid off or
            # transferred before closure (PRD §3.2).
            for account in domain.accounts_of_program(program_id):
                if (account.get("outstanding_balance_cents", 0) == 0
                        and account.get("account_status") in ("ACTIVE", "DELINQUENT")):
                    account["account_status"] = "PAID_OFF"
                    account["updated_at"] = clock.now_iso()
            touch(program)
            domain.refresh_program(program)
            return single(program)

        if status != "ACTIVE":
            raise fail(ERR_INVALID_STATE,
                       "Only an ACTIVE program can open a renewal round.")
        if to_status != "RENEWAL_NEGOTIATION":
            raise fail(ERR_INVALID_STATE,
                       "An ACTIVE program's renewal round must target RENEWAL_NEGOTIATION.")
        if expected != program["version"]:
            raise fail("ERR_STALE_VERSION",
                       "expected_program_version does not match the program's current version.")
        program["program_status"] = "RENEWAL_NEGOTIATION"
        touch(program)
        return single(program)

    @app.post("/servicing/credit-programs/<program_id>/complete-renewal")
    def complete_renewal(program_id):
        auth.require_role("ProgramAdmin")
        program = require_program(program_id)
        payload = auth.body()
        expected = require_field(payload, "expected_program_version", "int")
        if program["program_status"] != "RENEWAL_NEGOTIATION":
            raise fail(ERR_INVALID_STATE,
                       "Only a RENEWAL_NEGOTIATION program can complete its renewal round.")
        if expected != program["version"]:
            raise fail("ERR_STALE_VERSION",
                       "expected_program_version does not match the program's current version.")
        program["program_status"] = "ACTIVE"
        touch(program)
        return single(program)

    @app.post("/servicing/credit-programs/<program_id>/close")
    def close_credit_program(program_id):
        auth.require_role("ProgramAdmin")
        program = require_program(program_id)
        payload = auth.body()
        expected = require_field(payload, "expected_program_version", "int")
        if program["program_status"] != "WINDING_DOWN":
            raise fail(ERR_INVALID_STATE,
                       "Only a WINDING_DOWN program can be closed.")
        transfers = [t for t in store.transfers.values() if t.get("program_id") == program_id]
        if any(t.get("transfer_status") != "COMPLETED" for t in transfers):
            raise fail(ERR_INVALID_STATE,
                       "Every wind-down transfer on this program must be COMPLETED before closure.")
        for account in domain.accounts_of_program(program_id):
            if account.get("account_status") not in ("TRANSFERRED", "PAID_OFF"):
                raise fail("ERR_ACCOUNT_NOT_SETTLED",
                           "Every account on the program must be TRANSFERRED or PAID_OFF.")
        if expected != program["version"]:
            raise fail("ERR_STALE_VERSION",
                       "expected_program_version does not match the program's current version.")
        program["program_status"] = "CLOSED"
        program["free_look_exposure_cents"] = 0
        touch(program)
        domain.refresh_program(program)
        _maybe_suspend_partner(program.get("partner_id"))
        return single(program)

    @app.get("/servicing/credit-programs/<program_id>/summary")
    def program_summary(program_id):
        _user_id, role = auth.require_role("ProgramAdmin", "Underwriter", "RetailPartnerAnalyst")
        program = require_program(program_id)
        if role == "RetailPartnerAnalyst" and program.get("partner_id") != _user_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A RetailPartnerAnalyst may only read their own retailer's program.")
        accounts = domain.accounts_of_program(program_id)
        scored = [a for a in accounts if a.get("account_status") != "CHARGED_OFF"]
        if scored:
            scores = [
                computations.delinquency_risk_score(
                    a, domain.days_since_last_payment(a)) for a in scored
            ]
            risk = computations.round_half_up(sum(scores) / len(scores), 0)
        else:
            risk = 0
        agreement_id = program.get("agreement_id")
        settled_count = sum(
            1 for b in store.settlement_batches.values()
            if b.get("agreement_id") == agreement_id and b.get("batch_status") == "SETTLED"
        )
        return single({
            "program_id": program["id"],
            "program_status": program["program_status"],
            "outstanding_receivable_cents": program["outstanding_receivable_cents"],
            "free_look_exposure_cents": program["free_look_exposure_cents"],
            "program_profitability_cents": program["program_profitability_cents"],
            "program_risk_score": int(risk),
            "account_count": len(accounts),
            "settled_batch_count": settled_count,
        })

    # --- Application ------------------------------------------------------

    @app.post("/servicing/applications")
    def create_application():
        auth.require_role("Applicant", "ProgramAdmin")
        payload = auth.body()
        program_id = require_field(payload, "program_id", "string")
        channel = auth.enum_field(payload, "source_channel", _VALID_SOURCE_CHANNELS)
        requested = require_field(payload, "requested_credit_limit_cents", "int")
        program = store.programs.get(program_id)
        if not program:
            raise _not_found("CreditProgram")
        if channel == "PRESCREENED":
            reference = optional_field(payload, "prescreen_reference", "string")
            if not reference:
                raise fail("ERR_PRESCREEN_REQUIRED",
                           "A PRESCREENED application must carry a live prescreen_reference.")
        if requested > computations.CREDIT_APPLICANT_CEILING_CENTS:
            raise fail("ERR_CREDIT_LIMIT_OUT_OF_BAND",
                       "The requested credit limit exceeds the per-applicant ceiling.")
        if program.get("program_status") == "CLOSED":
            raise fail("ERR_PROGRAM_CLOSED",
                       "The program is CLOSED and no longer accepts applications.")
        application = add("applications", {
            "program_id": program_id,
            "source_channel": channel,
            "requested_credit_limit_cents": requested,
            "prescreen_reference": optional_field(payload, "prescreen_reference", "string"),
            "application_status": "PENDING",
            "decision_code": None,
            "approved_credit_limit_cents": None,
            "instant_decision_at": None,
        })
        return single(application, 201)

    @app.get("/servicing/applications")
    def list_applications():
        auth.require_role("ProgramAdmin", "Underwriter")
        return listing(list(store.applications.values()),
                       {"program_id": request.args.get("program_id")})

    @app.get("/servicing/applications/<application_id>")
    def read_application(application_id):
        auth.require_role("ProgramAdmin", "Underwriter", "Applicant")
        return single(require_application(application_id))

    @app.post("/servicing/applications/<application_id>/decide")
    def decide_application(application_id):
        auth.require_role("Underwriter")
        application = require_application(application_id)
        if application["application_status"] != "PENDING":
            raise fail(ERR_INVALID_STATE,
                       "Only a PENDING application can be decisioned.")
        requested = application["requested_credit_limit_cents"]
        application["instant_decision_at"] = clock.now_iso()
        if requested <= computations.CREDIT_APPROVAL_CEILING_CENTS:
            application["application_status"] = "APPROVED"
            application["approved_credit_limit_cents"] = requested
            application["decision_code"] = "APPROVED_WITHIN_BAND"
            touch(application)
            _synthesize_account(application)
        else:
            application["application_status"] = "DECLINED"
            application["approved_credit_limit_cents"] = None
            application["decision_code"] = "DECLINED_LIMIT_OUT_OF_BAND"
            touch(application)
        return single(application)


def _synthesize_account(application):
    """Synthesize the approved account (PRD §3.3)."""
    return add("accounts", {
        "program_id": application["program_id"],
        "cardholder_ref": "**** **** **** " + application["id"][:4],
        "account_status": "ACTIVE",
        "credit_limit_cents": application["approved_credit_limit_cents"],
        "outstanding_balance_cents": 0,
        "linked_loyalty_balance": 0,
    })


def _maybe_suspend_partner(partner_id):
    """Bubble-up: once no program remains ACTIVE/RENEWAL_NEGOTIATION, the
    partner is suspended automatically (PRD §3.1)."""
    partner = store.partners.get(partner_id)
    if not partner or partner.get("partner_status") != "ACTIVE":
        return
    programs = domain.programs_of_partner(partner_id)
    if any(p.get("program_status") in ("ACTIVE", "RENEWAL_NEGOTIATION") for p in programs):
        return
    partner["partner_status"] = "SUSPENDED"
    partner["updated_at"] = clock.now_iso()