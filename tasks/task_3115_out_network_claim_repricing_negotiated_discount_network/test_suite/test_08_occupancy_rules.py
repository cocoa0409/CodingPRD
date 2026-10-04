"""Difficulty queue: resource temporal overlap — half-open agreement intervals
and single-occupancy negotiation cases."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_provider, create_agreement, create_network_agreement_payload,    setup_priced_claim, open_case, create_negotiation_case_payload,
    TEST_USERS, ApiErrorId,
)

NET = TEST_USERS["network_admin_headers"]


def test_agreement_starting_one_second_before_existing_end_overlaps():
    """PRD §3.2: "Two agreements for the same provider whose intervals overlap
    are forbidden among `ACTIVE` or `SUSPENDED` rows; a creation that would
    overlap is rejected with `ERR_AGREEMENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/agreement_interval_half_open_adjacency
    """
    provider = create_provider(npi="1000000017")
    create_agreement(provider, network_name="A",
                     effective_start="2026-01-01T00:00:00Z",
                     effective_end="2026-07-01T00:00:00Z")
    res = api_client.create_network_agreement(
        create_network_agreement_payload(
            provider["id"], network_name="B", discount_percent=0.35,
            effective_start="2026-06-30T23:59:59Z",
            effective_end="2027-01-01T00:00:00Z"), NET)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_agreement_adjacent_at_half_open_boundary_accepted():
    """PRD §3.2: "an effective interval bracketed by `effective_start`
    (inclusive) and `effective_end` (inclusive as stored, with `effective_end`
    strictly after `effective_start`; overlap detection treats the interval as
    half-open at the end)."
    PRD §3.2: "Two agreements for the same provider whose intervals overlap are
    forbidden among `ACTIVE` or `SUSPENDED` rows; a creation that would overlap
    is rejected with `ERR_AGREEMENT_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/agreement_interval_half_open_adjacency
    """
    provider = create_provider(npi="1000000018")
    create_agreement(provider, network_name="A",
                     effective_start="2026-01-01T00:00:00Z",
                     effective_end="2026-07-01T00:00:00Z")
    overlap = api_client.create_network_agreement(
        create_network_agreement_payload(
            provider["id"], network_name="B", discount_percent=0.35,
            effective_start="2026-06-30T23:59:59Z",
            effective_end="2027-01-01T00:00:00Z"), NET)
    validate_error(overlap, ApiErrorId.ERR_AGREEMENT_OVERLAP)

    adjacent = validate_success(api_client.create_network_agreement(
        create_network_agreement_payload(
            provider["id"], network_name="C", discount_percent=0.35,
            effective_start="2026-07-01T00:00:00Z",
            effective_end="2027-01-01T00:00:00Z"), NET), 201)
    assert adjacent["status"] == "ACTIVE"


def test_second_case_rejected_while_first_open():
    """PRD §3.5: "Only one non-terminal case may exist per claim; opening a
    second surfaces `ERR_CASE_ALREADY_OPEN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/negotiation_case_single_active_occupancy_per_claim
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "R1",
                                              "patient_responsibility_cents": 0},
                             npi="1000000019")
    open_case(env["claim"]["id"], env["ctx"])
    res = api_client.create_negotiation_case(
        create_negotiation_case_payload(env["claim"]["id"]),
        env["ctx"]["provider_rep"])
    validate_error(res, ApiErrorId.ERR_CASE_ALREADY_OPEN)


def test_new_case_accepted_after_first_withdrawn():
    """PRD §3.5: "Only one non-terminal case may exist per claim; opening a
    second surfaces `ERR_CASE_ALREADY_OPEN` (HTTP 409)."
    PRD §3.5: "Either side may walk away while the case is in `OPEN`,
    `OFFER_PENDING`, or `COUNTERED`: withdrawal moves the case to `WITHDRAWN`."

    Design: Difficulty/resource_temporal_overlap/negotiation_case_single_active_occupancy_per_claim
    """
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "R2",
                                              "patient_responsibility_cents": 0},
                             npi="1000000020")
    case = open_case(env["claim"]["id"], env["ctx"])
    res = api_client.create_negotiation_case(
        create_negotiation_case_payload(env["claim"]["id"]),
        env["ctx"]["provider_rep"])
    validate_error(res, ApiErrorId.ERR_CASE_ALREADY_OPEN)

    withdrawn = validate_success(api_client.withdraw_negotiation_case(
        case["id"], env["ctx"]["provider_rep"]), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    second = validate_success(api_client.create_negotiation_case(
        create_negotiation_case_payload(env["claim"]["id"]),
        env["ctx"]["provider_rep"]), 201)
    assert second["status"] == "OPEN"
