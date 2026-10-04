"""The host's occupancy counter as a conserved quantity across compensating actions."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    setup_basic_scenario,
    setup_confirmed_stay,
    file_stay,
    confirm_stay,
    read_stay,
    read_capacity_summary,
    read_member,
    declare_patronization_record,
    verify_patronization_record,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
)


def test_a_first_round_request_already_holds_a_site_before_the_host_answers(api):
    """PRD §3.4: "It counts toward the host's occupancy immediately when its
    `request_depth` is 1 or under, which is what allows a first-round request to hold
    a site before the host has answered, and the host's `committed_sites`,
    `free_sites` and `posture` are recomputed as soon as it lands."

    Design: Difficulty/compensating_invariant/host_committed_sites_conserved_across_decline_and_counter_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]

    before = read_capacity_summary(host_id)
    stay = file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
                     arrival_date="2026-06-15", nights=2, request_depth=0)
    after = read_capacity_summary(host_id)

    assert before["committed_sites_reserved_basis"] == 0
    assert after["committed_sites_reserved_basis"] == 1
    assert after["free_sites"] == 1
    assert stay["request_status"] == "REQUESTED"


def test_confirming_a_first_round_request_moves_no_occupancy_number(api):
    """PRD §2.4: "Because the stay being confirmed is already inside
    `committed_sites` at the moment of confirmation, the admission test is evaluated
    against `effective_capacity - (committed_sites - 1)`, so a request's own
    reservation can never block its own confirmation."

    Design: Difficulty/compensating_invariant/host_committed_sites_conserved_across_decline_and_counter_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    stay = file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
                     arrival_date="2026-06-15", nights=2, request_depth=0)

    before = read_capacity_summary(host_id)
    confirmed = confirm_stay(host_id, stay["id"], site_label="S1")
    after = read_capacity_summary(host_id)

    assert confirmed["request_status"] == "CONFIRMED"
    assert before["committed_sites_reserved_basis"] == 1
    assert after["committed_sites_reserved_basis"] == 1, (
        "the request was already counted at request_depth 0, so confirming it moved "
        "nothing"
    )
    assert before["free_sites"] == after["free_sites"] == 1


def test_a_second_round_step_subtracts_the_first_round_reservation(api):
    """PRD §2.4: "`count_toward_capacity` is true when its `request_status` is
    `CONFIRMED` and also true when its `request_status` is `REQUESTED` and its
    `request_depth` is 1 or under; in every other case it is false."
    PRD §3.6: "Beyond the status and depth, the pass recomputes the host's
    `committed_sites` and `free_sites`"

    Design: Difficulty/compensating_invariant/host_committed_sites_conserved_across_decline_and_counter_round
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    stay = file_stay(host_id, member_id, parts["vehicle"]["id"],
                     arrival_date="2026-06-15", nights=2, request_depth=0)
    assert read_capacity_summary(host_id)["committed_sites_reserved_basis"] == 1

    # Cancelling the CONFIRMED stay then countering pushes the request to depth 2.
    confirm_stay(host_id, stay["id"], site_label="S1")
    validate_success(
        api.cancel_stay_request(stay["id"], make_member_headers(member_id))
    )
    cancelled = read_capacity_summary(host_id)
    assert cancelled["committed_sites_reserved_basis"] == 0, (
        "a CANCELLED stay never counts, so the occupancy returned to zero"
    )

    reopened = validate_success(
        api.counter_stay_request(
            stay["id"],
            {"arrival_date": "2026-06-17", "nights": 2, "party_size": 1},
            make_member_headers(member_id),
        )
    )
    assert reopened["request_depth"] == 2
    after_counter = read_capacity_summary(host_id)
    assert after_counter["committed_sites_reserved_basis"] == 0, (
        "a request beyond depth 1 no longer counts, so the compensating "
        "subtraction leaves the occupancy at zero"
    )
    assert after_counter["free_sites"] == 2


def test_publishing_a_review_displaces_the_member_mean_and_withdrawing_restores_it(api):
    """PRD §2.6: "`member_rating_average` averages the `rating` of the member-author
    reviews written by a given member that are in `PUBLISHED` status, rounded the same
    way."
    PRD §2.6: "Posting a review recomputes the relevant average, and withdrawing a
    published review recomputes it again in the other direction, so the aggregate
    always reflects the currently published set."

    Design: Difficulty/compensating_invariant/member_review_aggregate_conserved_across_publish_and_withdrawal
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-05", nights=1,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    set_clock("2026-06-05T14:00:00Z")
    validate_success(api.check_in_stay(parts["stay"]["id"], host_headers))
    set_clock("2026-06-06T12:00:00Z")
    validate_success(api.check_out_stay(parts["stay"]["id"], host_headers))

    member_headers = make_member_headers(member_id)
    first = validate_success(
        api.create_review(
            {"author_member_id": member_id, "subject_host_id": host_id,
             "rating": 5, "public_note": "lovely", "advance_notice_hours": 240},
            member_headers,
        ),
        201,
    )
    assert read_member(member_id)["member_rating_average"] == 5.00

    second = validate_success(
        api.create_review(
            {"author_member_id": member_id, "subject_host_id": host_id,
             "rating": 4, "public_note": "good", "advance_notice_hours": 12},
            member_headers,
        ),
        201,
    )
    assert read_member(member_id)["member_rating_average"] == 4.50

    withdrawn = validate_success(api.withdraw_review(second["id"], member_headers))
    assert withdrawn["review_status"] == "WITHDRAWN"
    assert read_member(member_id)["member_rating_average"] == 5.00, (
        "withdrawing exactly one of the two restores the starting mean"
    )
    assert api.get_review(first["id"], member_headers).json()["data"][
        "review_status"
    ] == "PUBLISHED"


def test_withdrawing_the_same_review_twice_is_refused_and_the_mean_holds(api):
    """PRD §2.6: "A review may be withdrawn by either author or by platform staff,
    provided it is currently `PUBLISHED`; an attempt to withdraw a review already in
    `WITHDRAWN` status is rejected with `ERR_REVIEW_ALREADY_WITHDRAWN` (HTTP 409)."
    PRD §3.8: "Withdrawal reverses everything a review did: the review moves to
    `WITHDRAWN`, both rating aggregates are recomputed without it"

    Design: Difficulty/compensating_invariant/member_review_aggregate_conserved_across_publish_and_withdrawal
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-05", nights=1,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    set_clock("2026-06-05T14:00:00Z")
    validate_success(api.check_in_stay(parts["stay"]["id"], host_headers))
    set_clock("2026-06-06T12:00:00Z")
    validate_success(api.check_out_stay(parts["stay"]["id"], host_headers))

    member_headers = make_member_headers(member_id)
    validate_success(
        api.create_review(
            {"author_member_id": member_id, "subject_host_id": host_id,
             "rating": 5, "public_note": "lovely", "advance_notice_hours": 240},
            member_headers,
        ),
        201,
    )
    second = validate_success(
        api.create_review(
            {"author_member_id": member_id, "subject_host_id": host_id,
             "rating": 4, "public_note": "good", "advance_notice_hours": 12},
            member_headers,
        ),
        201,
    )
    assert read_member(member_id)["member_rating_average"] == 4.50

    validate_success(api.withdraw_review(second["id"], member_headers))
    assert read_member(member_id)["member_rating_average"] == 5.00

    resp = api.withdraw_review(second["id"], member_headers)
    validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_WITHDRAWN, 409)
    assert read_member(member_id)["member_rating_average"] == 5.00, (
        "the refused second withdrawal moved nothing"
    )