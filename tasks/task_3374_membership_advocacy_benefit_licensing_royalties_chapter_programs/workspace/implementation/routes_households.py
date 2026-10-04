"""Households, members, membership terms: enrollment, reads, cancellation."""

from flask import Blueprint

from auth import require_roles
from db import locked, mint, store, touch
from serializers import household_view, member_view, term_view
from services import add_years, cancel_refund_cents, clock_date, compute_age_years, price_term_cents
from util import (
    err,
    get_body,
    is_int,
    optional_bool,
    paginate,
    parse_date_strict,
    require_str,
    success_object,
)

bp = Blueprint("households", __name__)

ALLOWED_TERM_YEARS = (1, 3, 5)
MINIMUM_PRIMARY_AGE = 50
CANCEL_REASONS = ("VOLUNTARY", "DECEASED")


@bp.post("/api/households")
@locked
def create_household():
    require_roles("MemberServicesAgent")
    body = get_body()

    # Rung 5: request schema.
    state_code = require_str(body, "state_code")
    term_years = body.get("term_years")
    if term_years is None or not is_int(term_years):
        err("ERR_INVALID_REQUEST", 400, "term_years is required and must be an integer")
    primary_full_name = require_str(body, "primary_full_name")
    primary_dob_raw = body.get("primary_date_of_birth")
    primary_dob = parse_date_strict(primary_dob_raw)
    if primary_dob is None:
        err("ERR_INVALID_REQUEST", 400, "primary_date_of_birth is required and must be an ISO date")
    auto_renew = optional_bool(body, "auto_renew_enabled")
    primary_opt_out = optional_bool(body, "primary_benefit_marketing_opt_out")
    secondary_opt_out = optional_bool(body, "secondary_benefit_marketing_opt_out")
    secondary_name = body.get("secondary_full_name")
    secondary_dob_raw = body.get("secondary_date_of_birth")
    if (secondary_name is None) != (secondary_dob_raw is None):
        err(
            "ERR_INVALID_REQUEST",
            400,
            "secondary_full_name and secondary_date_of_birth must be supplied together",
        )
    secondary_dob = None
    if secondary_name is not None:
        if not isinstance(secondary_name, str):
            err("ERR_INVALID_REQUEST", 400, "secondary_full_name must be a string")
        secondary_dob = parse_date_strict(secondary_dob_raw)
        if secondary_dob is None:
            err("ERR_INVALID_REQUEST", 400, "secondary_date_of_birth must be an ISO date")

    # Rung 10: age eligibility is evaluated BEFORE the term-length constraint.
    if compute_age_years(primary_dob) < MINIMUM_PRIMARY_AGE:
        err("ERR_AGE_INELIGIBLE", 422, "Primary member must be at least 50 years old at enrollment")

    # Rung 11: term length.
    if term_years not in ALLOWED_TERM_YEARS:
        err("ERR_INVALID_TERM_YEARS", 422, "term_years must be one of 1, 3, 5")

    # Atomic creation: household + primary member (+ secondary) + initial term.
    today = clock_date()
    paid_cents = price_term_cents(term_years, False)

    household = mint(store.households)
    primary = mint(store.members)
    primary.update(
        {
            "household_id": household["id"],
            "full_name": primary_full_name,
            "date_of_birth": primary_dob_raw,
            "role_in_household": "PRIMARY",
            "benefit_marketing_opt_out": primary_opt_out,
        }
    )
    secondary_id = None
    if secondary_name is not None:
        secondary = mint(store.members)
        secondary.update(
            {
                "household_id": household["id"],
                "full_name": secondary_name,
                "date_of_birth": secondary_dob_raw,
                "role_in_household": "SECONDARY",
                "benefit_marketing_opt_out": secondary_opt_out,
            }
        )
        secondary_id = secondary["id"]

    household.update(
        {
            "state_code": state_code,
            "auto_renew_enabled": auto_renew,
            "primary_member_id": primary["id"],
            "secondary_member_id": secondary_id,
            "lifetime_collected_cents": paid_cents,
            "lifetime_refunded_cents": 0,
        }
    )
    term = mint(store.terms)
    term.update(
        {
            "household_id": household["id"],
            "term_years": term_years,
            "is_renewal": False,
            "start_date": today.isoformat(),
            "end_date": add_years(today, term_years).isoformat(),
            "purchased_at": store.clock_raw,
            "paid_cents": paid_cents,
            "refunded_cents": 0,
            "cancel_reason": None,
            "cancelled_at": None,
            "status": "ACTIVE",
        }
    )
    return success_object(household_view(household), status=201)


@bp.get("/api/households/<household_id>")
@locked
def get_household(household_id):
    require_roles("MemberServicesAgent", "PlatformAdmin")
    household = store.households.get(household_id)
    if household is None:
        err("ERR_NOT_FOUND", 404, "Household not found")
    return success_object(household_view(household))


@bp.get("/api/households/<household_id>/members")
@locked
def list_household_members(household_id):
    require_roles("MemberServicesAgent", "AdvocacyDirector", "PlatformAdmin")
    if household_id not in store.households:
        err("ERR_NOT_FOUND", 404, "Household not found")
    members = sorted(
        (m for m in store.members.values() if m["household_id"] == household_id),
        key=lambda r: r["_seq"],
    )
    return paginate([member_view(m) for m in members])


@bp.get("/api/households/<household_id>/terms")
@locked
def list_household_terms(household_id):
    require_roles("MemberServicesAgent", "PlatformAdmin")
    if household_id not in store.households:
        err("ERR_NOT_FOUND", 404, "Household not found")
    terms = sorted(
        (t for t in store.terms.values() if t["household_id"] == household_id),
        key=lambda r: r["_seq"],
    )
    return paginate([term_view(t) for t in terms])


@bp.post("/api/membership-terms/<term_id>/cancel")
@locked
def cancel_term(term_id):
    require_roles("MemberServicesAgent")
    body = get_body()
    # Rung 5: schema (reason enum) precedes existence and state.
    reason = body.get("reason")
    if reason not in CANCEL_REASONS:
        err("ERR_INVALID_REQUEST", 400, "reason must be VOLUNTARY or DECEASED")
    term = store.terms.get(term_id)
    if term is None:
        err("ERR_NOT_FOUND", 404, "Membership term not found")
    if term["status"] != "ACTIVE":
        err("ERR_TERM_NOT_ACTIVE", 409, "Only an ACTIVE term can be cancelled")

    refund = cancel_refund_cents(term, reason)
    term["refunded_cents"] = refund
    term["cancel_reason"] = reason
    term["cancelled_at"] = store.clock_raw
    term["status"] = "CANCELLED"
    touch(term)

    household = store.households.get(term["household_id"])
    if household is not None:
        household["lifetime_refunded_cents"] += refund
        touch(household)
    return success_object(term_view(term))
