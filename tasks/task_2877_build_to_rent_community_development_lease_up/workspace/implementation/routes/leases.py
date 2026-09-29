"""Lease drafting, the concession ledger and the contract lifecycle (PRD 3.7 - 3.9)."""
from __future__ import annotations

from flask import Blueprint

import repo
import serializers
from calc import add_months
from db import mark_created, new_record, set_field, set_instant, store
from errors import ApiError
from middleware import acting_role, acting_user_id, endpoint
from response import created
from services import community as community_service, concession as concession_service, pricing
from validation import MISSING, bad, body, opt_str, raw_id, req_enum, req_instant, req_int, req_str

bp = Blueprint("leases", __name__)

TERM_MONTHS_ALLOWED = (12, 18, 24)
OPEN_CONTRACT_STATUSES = ("DRAFT", "PENDING_SIGNATURE", "EXECUTED", "ACTIVE")
CANCELLATION_REASONS = ("POSTURE_FREEZE", "APPLICANT_WITHDREW", "OPERATOR_CANCELLED")
INCOME_QUALIFICATION_MULTIPLE = 3
CONCESSION_REQUEST_ENTRY_STATUSES = ("NONE", "REJECTED", "REVOKED")


def _require_ownership(lease):
    """Guards exactly three operations: reading, signing and noticing a lease."""
    if acting_role() == "Household" and lease["household_id"] != acting_user_id():
        raise ApiError("ERR_OWNERSHIP_VIOLATION")


@bp.post("/leases")
@endpoint("LeasingAgent")
def draft_lease():
    payload = body()
    homesite_ref = raw_id(payload, "homesite_id")
    homesite = repo.get_homesite(homesite_ref) if homesite_ref is not MISSING else None
    household_ref = raw_id(payload, "household_id")
    household = repo.get_household(household_ref) if household_ref is not MISSING else None
    if homesite is None:
        raise bad("homesite_id is required")
    if household is None:
        raise bad("household_id is required")

    term_months = req_int(payload, "term_months")
    if term_months not in TERM_MONTHS_ALLOWED:
        raise bad("term_months must be 12, 18 or 24")
    start_date = req_instant(payload, "start_date")

    phase = repo.phase_of_homesite(homesite)
    community = repo.community_of_phase(phase)
    if community["lifecycle_status"] not in ("LEASE_UP", "STABILIZED"):
        raise ApiError("ERR_INVALID_LIFECYCLE_STATE")
    community_service.require_not_frozen(community)
    if homesite["status"] != "AVAILABLE" or phase["status"] not in ("SECTIONS_RELEASED",
                                                                   "COMPLETE"):
        raise ApiError("ERR_HOMESITE_NOT_LEASABLE")
    for existing in repo.leases_of_household(household):
        if existing["lease_status"] in OPEN_CONTRACT_STATUSES:
            raise ApiError("ERR_HOUSEHOLD_ALREADY_LEASED")

    schedule = pricing.select_pricing_schedule(community, homesite["product_type"], start_date)
    if schedule is None:
        raise ApiError("ERR_NO_PUBLISHED_RENT_SCHEDULE")

    # Base rent is selected, not supplied, and is frozen at creation.
    base_rent_cents = schedule["asking_rent_cents"]
    fee_cents = pricing.community_services_fee_cents(base_rent_cents, homesite["product_type"])
    gross_cents = base_rent_cents + fee_cents
    end_date = add_months(start_date, term_months)

    lease = new_record("Lease", {
        "homesite_id": homesite["id"],
        "household_id": household["id"],
        "concession_program_id": None,
        "priced_by_schedule_id": schedule["id"],
        "term_months": term_months,
        "start_date": None,
        "end_date": None,
        "base_rent_cents": base_rent_cents,
        "community_services_fee_cents": fee_cents,
        "gross_monthly_charge_cents": gross_cents,
        "total_concession_cents": 0,
        "concession_schedule": [],
        "monthly_concession_credit_cents": 0,
        "first_period_charge_cents": 0,
        "net_effective_rent_cents": 0,
        "concession_applied_cents": 0,
        "concession_remaining_cents": 0,
        "credits_applied_count": 0,
        "lease_status": "DRAFT",
        "concession_status": "NONE",
        "concession_requested_by_user_id": None,
        "concession_decided_by_user_id": None,
        "cancellation_reason": None,
        "signed_by_name": None,
        "executed_at": None,
        "_executed_at": None,
        "notice_date": None,
        "_notice_date": None,
        "move_out_date": None,
        "_move_out_date": None,
        "construction_impact_credit_cents": 0,
    })
    store.leases[lease["id"]] = lease
    mark_created(lease)
    set_instant(lease, "start_date", start_date)
    set_instant(lease, "end_date", end_date)
    community_service.recompute_household(household)
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/concession-requests")
@endpoint("LeasingAgent")
def request_concession(identifier):
    lease = repo.get_lease(identifier)
    payload = body()
    program_ref = raw_id(payload, "concession_program_id")
    program = repo.get_program(program_ref) if program_ref is not MISSING else None
    if program is None:
        raise bad("concession_program_id is required")
    homesite = repo.homesite_of_lease(lease)
    community = repo.community_of_homesite(homesite)

    if lease["concession_status"] not in CONCESSION_REQUEST_ENTRY_STATUSES:
        raise ApiError("ERR_INVALID_CONCESSION_STATE")
    if (lease["lease_status"] not in ("DRAFT", "PENDING_SIGNATURE")
            or program["status"] != "ACTIVE"
            or program["community_id"] != community["id"]):
        raise ApiError("ERR_CONCESSION_PROGRAM_NOT_ACTIVE")
    if homesite["product_type"] not in program["eligible_product_types"]:
        raise ApiError("ERR_PRODUCT_TYPE_NOT_ELIGIBLE")

    previous_status = lease["concession_status"]
    set_field(lease, "concession_status", "REQUESTED")
    set_field(lease, "concession_program_id", program["id"])
    set_field(lease, "concession_requested_by_user_id", acting_user_id())
    if previous_status == "REJECTED":
        set_field(lease, "concession_decided_by_user_id", None)
    concession_service.build_amortization(lease, program)
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/concession-decisions")
@endpoint("AssetManager")
def decide_concession(identifier):
    lease = repo.get_lease(identifier)
    requester = lease["concession_requested_by_user_id"]
    if requester is not None and requester == acting_user_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The concession requester may not decide it")
    payload = body()
    decision = req_enum(payload, "decision", ("APPROVE", "REJECT"))
    opt_str(payload, "decision_note", None, 1, None)
    if lease["concession_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_CONCESSION_STATE")
    community = repo.community_of_lease(lease)
    program = store.programs[lease["concession_program_id"]]

    if decision == "APPROVE":
        amount = lease["total_concession_cents"]
        if program["committed_cents"] + amount > program["max_budget_cents"]:
            raise ApiError("ERR_CONCESSION_BUDGET_EXCEEDED",
                           "The program budget cannot absorb this concession")
        if (community["committed_concession_cents"] + amount
                > community["concession_budget_cents"]):
            raise ApiError("ERR_CONCESSION_BUDGET_EXCEEDED",
                           "The community concession budget cannot absorb this concession")
        set_field(lease, "concession_status", "APPROVED")
        set_field(lease, "concession_decided_by_user_id", acting_user_id())
    else:
        set_field(lease, "concession_status", "REJECTED")
        set_field(lease, "concession_decided_by_user_id", acting_user_id())
        concession_service.wind_back_on_rejection(lease)
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/submissions")
@endpoint("LeasingAgent")
def submit_lease(identifier):
    lease = repo.get_lease(identifier)
    homesite = repo.homesite_of_lease(lease)
    community = repo.community_of_homesite(homesite)
    if lease["lease_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    community_service.require_not_frozen(community)
    if homesite["status"] != "AVAILABLE":
        raise ApiError("ERR_HOMESITE_NOT_LEASABLE")
    set_field(lease, "lease_status", "PENDING_SIGNATURE")
    community_service.recompute_household_of_lease(lease)
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/signature")
@endpoint("Household")
def sign_lease(identifier):
    lease = repo.get_lease(identifier)
    _require_ownership(lease)
    payload = body()
    signed_by_name = req_str(payload, "signed_by_name", 1, 120)
    if lease["lease_status"] != "PENDING_SIGNATURE":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    homesite = repo.homesite_of_lease(lease)
    phase = repo.phase_of_homesite(homesite)
    community = repo.community_of_phase(phase)
    household = store.households[lease["household_id"]]

    community_service.require_not_frozen(community)
    if community["posture"] == "RESTRICTED":
        # A resident moving in during an amenity delay must be carrying compensation.
        program = (store.programs.get(lease["concession_program_id"])
                   if lease["concession_program_id"] else None)
        if (lease["concession_status"] != "APPROVED" or program is None
                or program["restricted_posture_eligible"] is not True):
            raise ApiError("ERR_COMMUNITY_POSTURE_RESTRICTED")
    if homesite["status"] != "AVAILABLE":
        raise ApiError("ERR_HOMESITE_NOT_LEASABLE")
    if (household["monthly_income_cents"]
            < INCOME_QUALIFICATION_MULTIPLE * lease["gross_monthly_charge_cents"]):
        raise ApiError("ERR_INCOME_QUALIFICATION_FAILED")

    # Hop zero: the lease itself.
    set_field(lease, "lease_status", "EXECUTED")
    set_instant(lease, "executed_at", store.now())
    set_field(lease, "signed_by_name", signed_by_name)
    community_service.recompute_household(household)
    # Hop one: the home.
    set_field(homesite, "status", "LEASED")
    # Hop two: the phase and community counters.
    community_service.recompute_community(community)
    # Hops three and four fire only when the threshold is actually reached.
    community_service.apply_stabilization(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/activation")
@endpoint("PropertyManager")
def activate_lease(identifier):
    lease = repo.get_lease(identifier)
    community = repo.community_of_lease(lease)
    if lease["lease_status"] != "EXECUTED" or store.now() < lease["_start_date"]:
        raise ApiError("ERR_INVALID_LEASE_STATE")
    set_field(lease, "lease_status", "ACTIVE")
    if lease["concession_status"] == "APPROVED":
        set_field(lease, "concession_status", "AMORTIZING")
    # Only the posture at the instant of activation matters.
    if community["posture"] in ("RESTRICTED", "FROZEN"):
        community_service.accrue_construction_impact_credit(community, lease)
    community_service.recompute_household_of_lease(lease)
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/concession-credit-applications")
@endpoint("PropertyManager")
def apply_concession_credit(identifier):
    lease = repo.get_lease(identifier)
    community = repo.community_of_lease(lease)
    payload = body()
    period_index = req_int(payload, "period_index", minimum=1)
    if lease["concession_status"] != "AMORTIZING":
        raise ApiError("ERR_INVALID_CONCESSION_STATE")
    schedule = lease["concession_schedule"] or []
    if period_index != lease["credits_applied_count"] + 1 or period_index > len(schedule):
        raise ApiError("ERR_CONCESSION_PERIOD_OUT_OF_ORDER")

    credit = schedule[period_index - 1]["credit_cents"]
    applied = lease["concession_applied_cents"] + credit
    set_field(lease, "concession_applied_cents", applied)
    set_field(lease, "concession_remaining_cents", lease["total_concession_cents"] - applied)
    set_field(lease, "credits_applied_count", lease["credits_applied_count"] + 1)
    if lease["concession_remaining_cents"] == 0:
        set_field(lease, "concession_status", "EXHAUSTED")
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/notices")
@endpoint("Household")
def give_notice(identifier):
    lease = repo.get_lease(identifier)
    _require_ownership(lease)
    payload = body()
    notice_date = req_instant(payload, "notice_date")
    move_out_date = req_instant(payload, "move_out_date")
    if move_out_date <= notice_date:
        raise bad("move_out_date must fall strictly after notice_date")
    if lease["lease_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_LEASE_STATE")
    homesite = repo.homesite_of_lease(lease)
    community = repo.community_of_homesite(homesite)
    set_field(lease, "lease_status", "ENDING")
    set_instant(lease, "notice_date", notice_date)
    set_instant(lease, "move_out_date", move_out_date)
    # A home on notice still counts as occupied, so no lifecycle revert follows.
    set_field(homesite, "status", "NOTICE_GIVEN")
    community_service.recompute_household_of_lease(lease)
    community_service.recompute_community(community)
    return created(serializers.lease, lease)


@bp.post("/leases/<identifier>/cancellation")
@endpoint("AssetManager")
def cancel_lease(identifier):
    lease = repo.get_lease(identifier)
    payload = body()
    reason = req_enum(payload, "cancellation_reason", CANCELLATION_REASONS)
    if lease["lease_status"] not in ("DRAFT", "PENDING_SIGNATURE", "EXECUTED"):
        raise ApiError("ERR_INVALID_LEASE_STATE")
    homesite = repo.homesite_of_lease(lease)
    community = repo.community_of_homesite(homesite)
    was_executed = lease["lease_status"] == "EXECUTED"

    set_field(lease, "lease_status", "CANCELLED")
    set_field(lease, "cancellation_reason", reason)
    concession_service.revoke(lease)
    community_service.recompute_household_of_lease(lease)
    if was_executed:
        # The EXECUTED branch has more to undo; released_at is left untouched.
        set_field(homesite, "status", "AVAILABLE")
    community_service.recompute_community(community)
    if was_executed:
        community_service.apply_stabilization_revert(community)
    return created(serializers.lease, lease)
