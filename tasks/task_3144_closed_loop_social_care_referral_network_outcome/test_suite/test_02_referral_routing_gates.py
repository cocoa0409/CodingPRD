"""Referral routing gates: state validity, consent pairing, receiver type,
category retirement, eligibility boundary composition, and capacity.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_network, create_category, create_org, create_offering,
    create_client, create_consent, create_and_approve_agreement,
    create_referral, get_referral,
    setup_referral_scenario, setup_routed_referral, add_referral,
    make_case_worker_headers, make_org_admin_headers,
)


def test_accept_draft_referral_returns_invalid_state():
    """PRD §3.5: "Accepting moves `ROUTED` → `ACCEPTED` and requires the
    caller's organization to be the current `receiver_org_id` (else
    `ERR_FORBIDDEN_ORG`)".
    PRD §2.6: "then state validity, where a resource not in a valid from-state
    for the requested transition is rejected with `ERR_INVALID_STATE` (HTTP
    409)".
    PRD §3.5: "Creation lands the referral in `DRAFT` — consent and category
    are validated eagerly, but no capacity is reserved yet."

    Design: Corner/state_machines/accept_draft_referral_returns_invalid_state
    """
    ctx = setup_referral_scenario()
    referral = create_referral(ctx["sender_id"], ctx["client_id"],
                               ctx["receiver_id"], ctx["offering_id"],
                               ctx["consent_id"], ctx["category_code"])
    assert referral["status"] == "DRAFT"

    validate_error(api_client.accept_referral(
        referral["id"], make_org_admin_headers(ctx["receiver_id"])),
        ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    assert get_referral(referral["id"])["status"] == "DRAFT"
    offering = get_success_data(api_client.get_offering(ctx["offering_id"], COORDINATOR))
    assert offering["capacity_consumed"] == 0


def test_route_with_wrong_consent_pair_returns_consent_required():
    """PRD §3.5: "an `ACTIVE` consent must match the sender-receiver pair,
    failing with `ERR_CONSENT_REQUIRED`".
    PRD §3.4: "The second gate is the `Consent`, recorded under a client by a
    `CaseWorker` (or coordinator) and naming the `sender_org_id` and
    `receiver_org_id` it authorizes".

    Design: Corner/validations/route_with_wrong_consent_pair_returns_consent_required
    """
    set_clock()
    create_network()
    create_category("FOOD")
    sender = create_org("Sender S", "CLINIC", "EIN-S")
    r1 = create_org("Receiver R1", "CBO", "EIN-R1")
    r2 = create_org("Receiver R2", "CBO", "EIN-R2")
    offering = create_offering(r1["id"], description="Meals R1")
    create_and_approve_agreement(sender["id"], r1["id"])
    client = create_client(sender["id"])
    # Consent binds (S, R2); the referral targets (S, R1).
    wrong_consent = create_consent(client["id"], sender["id"], r2["id"])
    referral = create_referral(sender["id"], client["id"], r1["id"],
                               offering["id"], wrong_consent["id"], "FOOD")

    validate_error(api_client.route_referral(
        referral["id"], make_case_worker_headers(sender["id"])),
        ApiErrorId.ERR_CONSENT_REQUIRED, expected_status=422)
    assert get_referral(referral["id"])["status"] == "DRAFT"


def test_error_receiver_not_cbo_on_route():
    """PRD §3.5: "The sender organization must be `ACTIVE`; the receiver must
    be `ACTIVE` and of `org_type` `CBO`, failing with `ERR_RECEIVER_NOT_CBO`
    otherwise".

    Design: Corner/errors/error_receiver_not_cbo_on_route
    """
    set_clock()
    create_network()
    create_category("FOOD")
    sender = create_org("Sender S", "CLINIC", "EIN-S")
    clinic_receiver = create_org("Clinic R2", "CLINIC", "EIN-R2")
    offering = create_offering(clinic_receiver["id"], description="Meals R2")
    create_and_approve_agreement(sender["id"], clinic_receiver["id"])
    client = create_client(sender["id"])
    consent = create_consent(client["id"], sender["id"], clinic_receiver["id"])
    referral = create_referral(sender["id"], client["id"], clinic_receiver["id"],
                               offering["id"], consent["id"], "FOOD")

    validate_error(api_client.route_referral(
        referral["id"], make_case_worker_headers(sender["id"])),
        ApiErrorId.ERR_RECEIVER_NOT_CBO, expected_status=422)
    assert get_referral(referral["id"])["status"] == "DRAFT"


def test_eligibility_income_one_cent_below_cap_routes():
    """PRD §3.5: "when `income_cap_annual_cents` is set, the client must have
    disclosed an income strictly below the cap — income exactly equal to the
    cap fails, and an undisclosed income fails a capped offering."
    PRD §3.5: "A successful route reserves the case: the offering's
    `capacity_consumed` increments by 1 and the client's
    `open_referral_count` increments by 1."

    Design: Difficulty/combinatorial_formula/eligibility_multi_input_income_boundary
    """
    ctx = setup_referral_scenario(
        category_code="HOUSING",
        offering_overrides={"min_client_age": 18, "max_client_age": 65,
                            "eligible_zip_codes": ["94110"],
                            "income_cap_annual_cents": 5_000_000},
        client_overrides={"annual_income_cents": 4_999_999})
    referral = create_referral(ctx["sender_id"], ctx["client_id"],
                               ctx["receiver_id"], ctx["offering_id"],
                               ctx["consent_id"], "HOUSING")
    routed = validate_success(api_client.route_referral(
        referral["id"], make_case_worker_headers(ctx["sender_id"])))
    assert routed["status"] == "ROUTED"
    offering = get_success_data(api_client.get_offering(ctx["offering_id"], COORDINATOR))
    assert offering["capacity_consumed"] == 1


def test_eligibility_income_exactly_at_cap_fails():
    """PRD §3.5: "when `income_cap_annual_cents` is set, the client must have
    disclosed an income strictly below the cap — income exactly equal to the
    cap fails, and an undisclosed income fails a capped offering. Any
    eligibility failure is `ERR_ELIGIBILITY_FAILED`."

    Design: Difficulty/combinatorial_formula/eligibility_multi_input_income_boundary
    """
    ctx = setup_referral_scenario(
        category_code="HOUSING",
        offering_overrides={"min_client_age": 18, "max_client_age": 65,
                            "eligible_zip_codes": ["94110"],
                            "income_cap_annual_cents": 5_000_000},
        client_overrides={"annual_income_cents": 5_000_000})
    referral = create_referral(ctx["sender_id"], ctx["client_id"],
                               ctx["receiver_id"], ctx["offering_id"],
                               ctx["consent_id"], "HOUSING")
    validate_error(api_client.route_referral(
        referral["id"], make_case_worker_headers(ctx["sender_id"])),
        ApiErrorId.ERR_ELIGIBILITY_FAILED, expected_status=422)
    assert get_referral(referral["id"])["status"] == "DRAFT"
    offering = get_success_data(api_client.get_offering(ctx["offering_id"], COORDINATOR))
    assert offering["capacity_consumed"] == 0


def test_offering_creation_with_retired_category_rejected():
    """PRD §3.1: "Once a category is `RETIRED`, any attempt to create a new
    offering or a new referral naming that code is rejected with
    `ERR_CATEGORY_RETIRED`."

    Design: Corner/validations/offering_creation_with_retired_category_rejected
    """
    set_clock()
    create_network()
    category = create_category("TRANSPORT")
    get_success_data(api_client.retire_taxonomy_category(category["id"], COORDINATOR))
    receiver = create_org("Receiver R", "CBO", "EIN-R")

    validate_error(api_client.create_offering(
        receiver["id"],
        {"category_code": "TRANSPORT", "description": "Rides", "capacity_total": 5},
        make_org_admin_headers(receiver["id"])),
        ApiErrorId.ERR_CATEGORY_RETIRED, expected_status=422)
