"""Dispute case endpoints and the cyclic negotiation machine."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

bp = Blueprint("disputes", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)

DISPUTE_REASONS = (
    "UNAUTHORIZED_LOAD",
    "INCORRECT_AMOUNT",
    "GOODS_NOT_RECEIVED",
    "ERROR_RESOLUTION",
)


def _clerk_party_to(clerk_agreement_id, load):
    location = core.get_location(load["reload_location_id"])
    return location["retailer_agreement_id"] == clerk_agreement_id


def _agreement_of_dispute(dispute):
    load = core.get_load(dispute["load_transaction_id"])
    return core.agreement_of_location(core.get_location(load["reload_location_id"]))


@bp.post("/v1/disputes")
def create_dispute():
    middleware.authenticate(("ComplianceAnalyst", "RetailerClerk"))
    data = rh.body()
    program_id = rh.require_str(data, "program_id")
    load_id = rh.require_str(data, "load_transaction_id")
    account_id = rh.require_str(data, "card_account_id")
    reason = rh.require_enum(data, "dispute_reason", DISPUTE_REASONS)
    claimed = rh.require_int(data, "claimed_amount_cents")
    expected_load_version = rh.require_int(data, "expected_load_transaction_version")

    program = core.ref_program(program_id)
    load = core.ref_load(load_id)
    account = core.ref_account(account_id)

    if claimed < 1:
        raise errors.invalid_request("claimed_amount_cents must be at least 1.")
    if expected_load_version != load["version"]:
        raise errors.stale_version()
    core.guard_not_frozen(program)
    if account["id"] != load["card_account_id"]:
        raise errors.invalid_request("card_account_id does not match the disputed load.")

    agreement_type = account["cardholder_agreement_type"]
    error_eligible = reason == "ERROR_RESOLUTION" and load["load_status"] in (
        "FUNDED",
        "SETTLED",
    )

    row = core.common_fields()
    row.update(
        {
            "program_id": program["id"],
            "load_transaction_id": load["id"],
            "card_account_id": account["id"],
            "cardholder_agreement_type": agreement_type,
            "dispute_reason": reason,
            "claimed_amount_cents": claimed,
            "case_status": "OPEN",
            "response_round": 0,
            "provisional_credit_cents": calc.provisional_at_creation(
                agreement_type, claimed, error_eligible
            ),
            "final_liability_cents": 0,
            "retailer_response_due_at": timeutil.now()
            + timedelta(hours=calc.response_window_hours(agreement_type)),
            "error_resolution_eligible": error_eligible,
            "retailer_position": None,
            "resolution": None,
            "escalation_note": None,
        }
    )
    db.register(db.dispute_cases, row)
    core.touch(load)
    return response.ok(core.public(core.DISPUTE_CASE, row), 201)


@bp.get("/v1/disputes/<dispute_id>")
def get_dispute(dispute_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(core.public(core.DISPUTE_CASE, core.get_dispute(dispute_id)))


@bp.get("/v1/disputes")
def list_disputes():
    middleware.authenticate(READ_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.dispute_cases,
        program_id=request.args.get("program_id"),
        load_transaction_id=request.args.get("load_transaction_id"),
        card_account_id=request.args.get("card_account_id"),
    )
    total = len(rows)
    return response.array(
        core.public_list(core.DISPUTE_CASE, rows[offset : offset + limit]), limit, offset, total
    )


# --- negotiation --------------------------------------------------------------
@bp.post("/v1/disputes/<dispute_id>/retailer-response")
def retailer_response(dispute_id):
    user_id, role = middleware.authenticate(("RetailerClerk",))
    dispute = core.get_dispute(dispute_id)
    load = core.get_load(dispute["load_transaction_id"])

    if not _clerk_party_to(user_id, load):
        raise errors.retailer_not_party(
            "The acting clerk's agreement is not party to the disputed load."
        )

    data = rh.body()
    if dispute["case_status"] == "OPEN":
        pass
    elif dispute["case_status"] == "RETAILER_RESPONSE":
        if int(dispute["response_round"]) >= 3:
            raise errors.invalid_state(
                "A third supplemental retailer response is not accepted."
            )
    else:
        raise errors.invalid_state(
            "No retailer response is accepted from status %s." % dispute["case_status"]
        )

    due = dispute["retailer_response_due_at"]
    if due is not None and timeutil.now() > due:
        raise errors.dispute_response_window_closed(
            "The retailer response deadline has passed."
        )

    dispute["case_status"] = "RETAILER_RESPONSE"
    dispute["response_round"] = int(dispute["response_round"]) + 1
    dispute["retailer_position"] = rh.require_str(data, "retailer_position")
    core.touch(dispute)
    return response.ok(core.public(core.DISPUTE_CASE, dispute))


@bp.post("/v1/disputes/<dispute_id>/program-review")
def program_review(dispute_id):
    middleware.authenticate(("ComplianceAnalyst", "ComplianceOfficer"))
    dispute = core.get_dispute(dispute_id)
    data = rh.body()

    if dispute["case_status"] == "RETAILER_RESPONSE":
        pass
    elif dispute["case_status"] == "ESCALATED":
        pass
    else:
        raise errors.invalid_state(
            "A dispute in status %s cannot enter program review." % dispute["case_status"]
        )

    dispute["case_status"] = "PROGRAM_REVIEW"
    dispute["provisional_credit_cents"] = calc.provisional_at_program_review(
        dispute["cardholder_agreement_type"],
        dispute["claimed_amount_cents"],
        dispute["error_resolution_eligible"],
    )
    core.touch(dispute)
    return response.ok(core.public(core.DISPUTE_CASE, dispute))


@bp.post("/v1/disputes/<dispute_id>/return-to-retailer")
def return_to_retailer(dispute_id):
    middleware.authenticate(("ComplianceAnalyst",))
    dispute = core.get_dispute(dispute_id)
    rh.body()
    if dispute["case_status"] != "PROGRAM_REVIEW":
        raise errors.invalid_state(
            "A dispute in status %s cannot be returned to the retailer." % dispute["case_status"]
        )
    if int(dispute["response_round"]) >= 3:
        raise errors.invalid_state(
            "The third round must be resolved or escalated rather than returned."
        )
    dispute["case_status"] = "RETAILER_RESPONSE"
    dispute["retailer_response_due_at"] = timeutil.now() + timedelta(
        hours=calc.response_window_hours(dispute["cardholder_agreement_type"])
    )
    core.touch(dispute)
    return response.ok(core.public(core.DISPUTE_CASE, dispute))


@bp.post("/v1/disputes/<dispute_id>/escalate")
def escalate(dispute_id):
    middleware.authenticate(("ComplianceAnalyst",))
    dispute = core.get_dispute(dispute_id)
    data = rh.body()
    if dispute["case_status"] != "RETAILER_RESPONSE":
        raise errors.invalid_state(
            "A dispute in status %s cannot be escalated." % dispute["case_status"]
        )
    due = dispute["retailer_response_due_at"]
    if due is None or timeutil.now() <= due:
        raise errors.invalid_state(
            "Escalation opens only after the retailer window has closed."
        )
    dispute["case_status"] = "ESCALATED"
    dispute["escalation_note"] = rh.optional(data, "escalation_note")
    core.touch(dispute)
    return response.ok(core.public(core.DISPUTE_CASE, dispute))


@bp.post("/v1/disputes/<dispute_id>/resolve")
def resolve(dispute_id):
    middleware.authenticate(("ComplianceOfficer",))
    dispute = core.get_dispute(dispute_id)
    data = rh.body()
    resolution = rh.require_enum(data, "resolution", ("CARDHOLDER", "RETAILER"))

    if dispute["case_status"] != "PROGRAM_REVIEW":
        raise errors.invalid_state(
            "A dispute in status %s cannot be resolved." % dispute["case_status"]
        )

    load = core.get_load(dispute["load_transaction_id"])
    program = core.get_program(dispute["program_id"])

    if resolution == "CARDHOLDER":
        dispute["case_status"] = "RESOLVED_CARDHOLDER"
        dispute["resolution"] = "CARDHOLDER"
        dispute["final_liability_cents"] = int(dispute["claimed_amount_cents"])
        dispute["provisional_credit_cents"] = calc.provisional_at_resolution(
            dispute["cardholder_agreement_type"],
            dispute["claimed_amount_cents"],
            dispute["error_resolution_eligible"],
            favour_cardholder=True,
        )
        core.touch(dispute)
        if load["load_status"] in ("FUNDED", "SETTLED"):
            core.reverse_load(load, "DISPUTE_FAVOR_CARDHOLDER", finalize=False)
        core.recompute_program(program)
        core.touch(program)
        return response.ok(core.public(core.DISPUTE_CASE, dispute))

    dispute["case_status"] = "RESOLVED_RETAILER"
    dispute["resolution"] = "RETAILER"
    dispute["final_liability_cents"] = 0
    dispute["provisional_credit_cents"] = 0
    core.touch(dispute)
    return response.ok(core.public(core.DISPUTE_CASE, dispute))


@bp.post("/v1/disputes/<dispute_id>/close")
def close(dispute_id):
    middleware.authenticate(("ComplianceOfficer",))
    dispute = core.get_dispute(dispute_id)
    rh.body()

    if dispute["case_status"] == "RESOLVED_RETAILER":
        pass
    elif dispute["case_status"] == "RESOLVED_CARDHOLDER":
        has_allocation = any(
            a["dispute_case_id"] == dispute["id"]
            and a["allocation_status"] in ("POSTED", "RECOVERED")
            for a in db.loss_allocations.values()
        )
        agreement = _agreement_of_dispute(dispute)
        if not has_allocation and int(dispute["final_liability_cents"]) > int(
            agreement["per_transaction_limit_cents"]
        ):
            raise errors.invalid_state(
                "A large cardholder-favouring loss must be taken up by an allocation first."
            )
    else:
        raise errors.invalid_state(
            "A dispute in status %s cannot be closed." % dispute["case_status"]
        )

    dispute["case_status"] = "CLOSED"
    core.touch(dispute)
    return response.ok(core.public(core.DISPUTE_CASE, dispute))