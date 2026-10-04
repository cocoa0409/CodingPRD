"""Program endpoints, including the posture state machine and oversight review."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

bp = Blueprint("programs", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)


@bp.post("/v1/programs")
def create_program():
    middleware.authenticate(("PlatformAdmin",))
    data = rh.body()
    name = rh.require_str(data, "name")
    sponsor_id = rh.require_str(data, "sponsor_bank_id")
    program_type = rh.require_enum(
        data, "program_type", ("BAAS_PROGRAM_MANAGER", "OWN_BANK_PROGRAM")
    )
    settlement_cycle = rh.optional(data, "settlement_cycle", "DAILY")
    if settlement_cycle not in ("DAILY", "WEEKLY"):
        raise errors.invalid_request("settlement_cycle must be DAILY or WEEKLY.")
    oversight_review_due_at = rh.require_datetime(data, "oversight_review_due_at")
    sponsor = core.ref_bank(sponsor_id)

    row = core.common_fields()
    row.update(
        {
            "name": name,
            "sponsor_bank_id": sponsor["id"],
            "program_type": program_type,
            "settlement_cycle": settlement_cycle,
            "oversight_review_due_at": oversight_review_due_at,
            "compliance_posture": "OPEN",
            "open_aml_alert_count": 0,
            "posture_breach_count": 0,
            "posture_score": 0.0,
            "is_oversight_overdue": timeutil.now() > oversight_review_due_at,
            "last_posture_review_at": None,
            "suspended_brand_count": 0,
            "allocated_loss_total_cents": 0,
            "unallocated_confirmed_loss_cents": 0,
        }
    )
    db.register(db.programs, row)
    core.recompute_sponsor(sponsor)
    return response.ok(personalised(row), 201)


def personalised(program):
    """Clock-derived posture fields are recomputed for reporting: the overdue
    flag and the decay factor move with the logical clock, and nothing resets
    them on its own."""
    core.refresh_program(program)
    return core.public(core.PROGRAM, program)


@bp.get("/v1/programs/<program_id>")
def get_program(program_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(personalised(core.get_program(program_id)))


@bp.get("/v1/programs")
def list_programs():
    middleware.authenticate(READ_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(db.programs, sponsor_bank_id=request.args.get("sponsor_bank_id"))
    total = len(rows)
    return response.array(
        [personalised(r) for r in rows[offset : offset + limit]], limit, offset, total
    )


# --- posture state machine ----------------------------------------------------
@bp.post("/v1/programs/<program_id>/state")
def move_program_state(program_id):
    user_id, role = middleware.authenticate(("BankSponsor", "PlatformAdmin"))
    program = core.get_program(program_id)
    if role == "BankSponsor" and program["sponsor_bank_id"] != user_id:
        raise errors.unauthorized("The acting bank does not sponsor this program.")

    data = rh.body()
    to_posture = rh.require_enum(data, "to_posture", ("OPEN", "RESTRICTED", "FROZEN"))
    expected = rh.require_int(data, "expected_program_version")
    if expected != program["version"]:
        raise errors.stale_version()

    current = program["compliance_posture"]
    if to_posture == current:
        raise errors.invalid_state("The program is already in posture %s." % current)

    score = calc.round_half_up(program["posture_score"], 2)

    if current == "OPEN" and to_posture == "RESTRICTED":
        if not (Decimal("4.00") <= score <= Decimal("59.99")):
            raise errors.posture_transition_blocked(
                "A move to RESTRICTED requires a posture_score between 4.00 and 59.99."
            )
        _enter_restricted(program)
    elif current == "OPEN" and to_posture == "FROZEN":
        if score < calc.FREEZE_THRESHOLD:
            raise errors.posture_transition_blocked(
                "A move to FROZEN requires a posture_score of at least 60.00."
            )
        _enter_frozen(program)
    elif current == "RESTRICTED" and to_posture == "OPEN":
        if score > calc.UNFREEZE_THRESHOLD:
            raise errors.posture_transition_blocked(
                "A move to OPEN requires a posture_score of at most 3.99."
            )
        _restricted_to_open(program)
    elif current == "RESTRICTED" and to_posture == "FROZEN":
        if score < calc.FREEZE_THRESHOLD:
            raise errors.posture_transition_blocked(
                "A move to FROZEN requires a posture_score of at least 60.00."
            )
        _enter_frozen(program)
    elif current == "FROZEN" and to_posture == "RESTRICTED":
        if score > Decimal("0.00"):
            raise errors.posture_transition_blocked(
                "Leaving FROZEN requires a posture_score of 0.00 or lower."
            )
        _frozen_to_restricted(program)
    elif current == "FROZEN" and to_posture == "OPEN":
        if score > Decimal("0.00"):
            raise errors.posture_transition_blocked(
                "Leaving FROZEN requires a posture_score of 0.00 or lower."
            )
        _frozen_to_open(program)
    else:
        raise errors.invalid_state("No transition from %s to %s." % (current, to_posture))

    program["last_posture_review_at"] = timeutil.now()
    core.recompute_program(program)
    core.touch(program)
    return response.ok(personalised(program))


# --- posture cascade helpers --------------------------------------------------
def _program_brands(program):
    return [b for b in db.brand_partners.values() if b["program_id"] == program["id"]]


def _program_agreements(program):
    return [a for a in db.retailer_agreements.values() if a["program_id"] == program["id"]]


def _program_locations(program):
    agreement_ids = {a["id"] for a in _program_agreements(program)}
    return [
        l for l in db.reload_locations.values() if l["retailer_agreement_id"] in agreement_ids
    ]


def _program_accounts(program):
    return [a for a in db.card_accounts.values() if a["program_id"] == program["id"]]


def _enter_restricted(program):
    """OPEN -> RESTRICTED: a single hop across brands, locations and agreements."""
    for brand in _program_brands(program):
        if brand["partner_status"] == "ACTIVE":
            brand["partner_status"] = "SUSPENDED"
            brand["suspension_source"] = "POSTURE"
            core.touch(brand)
    for location in _program_locations(program):
        if location["location_status"] == "OPEN":
            location["location_status"] = "RESTRICTED"
            location["aml_velocity_score"] = calc.num(
                min(
                    Decimal("100.00"),
                    Decimal(str(location["aml_velocity_score"])) + Decimal("5.00"),
                )
            )
            core.touch(location)
    for agreement in _program_agreements(program):
        if agreement["agreement_status"] == "ACTIVE":
            agreement["agreement_status"] = "SUSPENDED"
            core.touch(agreement)
    program["compliance_posture"] = "RESTRICTED"


def _enter_frozen(program):
    """Both FROZEN entries share this five-hop shape."""
    # hop 1
    for brand in _program_brands(program):
        if brand["partner_status"] in ("ACTIVE", "SUSPENDED"):
            brand["partner_status"] = "SUSPENDED"
            brand["suspension_source"] = "POSTURE"
            core.touch(brand)
    for location in _program_locations(program):
        if location["location_status"] in ("OPEN", "RESTRICTED"):
            location["location_status"] = "CLOSED"
            core.touch(location)

    # hop 2 - open alerts into review, severity HIGH, assigned analyst untouched
    for alert in db.aml_alerts.values():
        if alert["program_id"] == program["id"] and alert["alert_status"] == "OPEN":
            alert["alert_status"] = "UNDER_REVIEW"
            alert["severity"] = "HIGH"
            core.touch(alert)

    # hop 3 - every account of the program frozen
    frozen_accounts = _program_accounts(program)
    for account in frozen_accounts:
        account["compliance_hold_status"] = "FROZEN"
        account["frozen_at"] = timeutil.now()
        core.touch(account)

    # hop 4 - reverse the funded loads of those accounts
    reversed_ids = []
    for account in frozen_accounts:
        for load in core.account_loads(account):
            if load["load_status"] == "FUNDED":
                core.reverse_load(load, "AML_CONFIRMED", finalize=False)
                reversed_ids.append(load["id"])
        core.dismiss_stale_alerts(account)

    # hop 5 - posted allocations covering those loads become RECOVERED
    core.recover_allocations_for(reversed_ids)
    program["compliance_posture"] = "FROZEN"


def _restricted_to_open(program):
    """Revives only what the posture cascade suspended."""
    for brand in _program_brands(program):
        if brand["suspension_source"] == "POSTURE":
            brand["partner_status"] = "ACTIVE"
            brand["suspension_source"] = "NONE"
            core.touch(brand)
    for location in _program_locations(program):
        if location["location_status"] == "RESTRICTED":
            location["location_status"] = "OPEN"
            core.touch(location)
    for agreement in _program_agreements(program):
        if agreement["agreement_status"] == "SUSPENDED":
            agreement["agreement_status"] = "ACTIVE"
            core.touch(agreement)
    program["compliance_posture"] = "OPEN"


def _frozen_to_restricted(program):
    for location in _program_locations(program):
        if location["location_status"] == "CLOSED":
            location["location_status"] = "RESTRICTED"
            core.touch(location)
    for account in _program_accounts(program):
        if account["compliance_hold_status"] == "FROZEN":
            account["compliance_hold_status"] = "REVIEW"
            core.touch(account)
    program["compliance_posture"] = "RESTRICTED"


def _frozen_to_open(program):
    for brand in _program_brands(program):
        if brand["suspension_source"] == "POSTURE":
            brand["partner_status"] = "ACTIVE"
            brand["suspension_source"] = "NONE"
            core.touch(brand)
    for location in _program_locations(program):
        if location["location_status"] == "CLOSED":
            location["location_status"] = "OPEN"
            core.touch(location)
    for account in _program_accounts(program):
        if account["compliance_hold_status"] == "FROZEN":
            account["compliance_hold_status"] = "REVIEW"
            core.touch(account)
    program["compliance_posture"] = "OPEN"


# --- oversight review ---------------------------------------------------------
@bp.post("/v1/programs/<program_id>/oversight-review")
def oversight_review(program_id):
    user_id, role = middleware.authenticate(("BankSponsor", "PlatformAdmin"))
    program = core.get_program(program_id)
    if role == "BankSponsor" and program["sponsor_bank_id"] != user_id:
        raise errors.unauthorized("The acting bank does not sponsor this program.")
    core.guard_not_frozen(program)

    rh.body()
    sponsor = core.get_bank(program["sponsor_bank_id"])

    sponsor["oversight_reviews_completed"] = int(sponsor["oversight_reviews_completed"]) + 1
    program["last_posture_review_at"] = timeutil.now()
    program["oversight_review_due_at"] = timeutil.now() + timedelta(
        days=calc.OVERSIGHT_INTERVAL_DAYS
    )
    core.recompute_program(program)
    core.touch(program)
    return response.ok(personalised(program))