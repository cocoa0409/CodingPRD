"""Gates one entity's state imposes on another's transitions."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    suspend_host,
    setup_basic_scenario,
    setup_confirmed_stay,
    setup_checked_in_stay,
    file_stay,
    try_file_stay,
    confirm_stay,
    read_member,
    read_stay,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
    make_platform_admin_headers,
)


def test_a_stay_is_confirmable_while_its_host_is_approved(api):
    """PRD §3.4: "Confirming a stay is the platform's most heavily guarded
    transition, and its checks run in order. The request must still be `REQUESTED`;
    the host must still be `APPROVED` and its posture must be `OPEN` or `LIMITED`"
    PRD §3.4: "A confirmed stay moves to `request_status` `CONFIRMED`, records the
    assigned site in `confirmed_site_id`"

    Design: Difficulty/cross_entity_state_dependency/member_stay_confirmable_only_while_host_onboarding_approved
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    stay = file_stay(parts["host"]["id"], parts["member"]["id"],
                     parts["vehicle"]["id"], arrival_date="2026-06-10", nights=2)
    confirmed = confirm_stay(parts["host"]["id"], stay["id"], site_label="S1")
    assert confirmed["request_status"] == "CONFIRMED"
    assert confirmed["confirmed_site_id"] is not None


def test_the_same_request_is_refused_once_the_host_is_suspended(api):
    """PRD §3.4: "a suspended host refused as `ERR_HOST_NOT_ACCEPTING_STAYS`
    (HTTP 409)"
    PRD §2.10: "State suitability is checked next, yielding `ERR_INVALID_STATE`
    (HTTP 409) whenever a target resource is not in a state that permits the
    requested operation."

    Design: Difficulty/cross_entity_state_dependency/member_stay_confirmable_only_while_host_onboarding_approved
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    # A second-round request is left open, then the host is suspended so the
    # cascade declines it before the gate can be observed second-hand.
    file_stay(host_id, member_id, parts["vehicle"]["id"],
              arrival_date="2026-06-20", nights=2, request_depth=2)
    suspend_host(host_id)

    resp = try_file_stay(host_id, member_id, parts["vehicle"]["id"],
                         arrival_date="2026-06-25", nights=2)
    validate_error(resp, ApiErrorId.ERR_HOST_NOT_ACCEPTING_STAYS, 409)

    member = read_member(member_id)
    assert member["subscription_status"] == "ACTIVE", (
        "the gate that fired belongs to the host pair and not to the member"
    )


def test_a_member_author_review_requires_a_completed_stay_with_the_host(api):
    """PRD §3.8: "A member-author review requires a stay request between that member
    and the host that has reached `CHECKED_IN` or `CHECKED_OUT` and whose
    `occupancy_end` is at or before the current logical clock; a member attempting to
    review a host with no such completed stay is refused with
    `ERR_REVIEW_NOT_ELIGIBLE` (HTTP 403)."

    Design: Difficulty/cross_entity_state_dependency/member_author_review_gated_on_stay_checkout_completion
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-15", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    resp = api.create_review(
        {
            "author_member_id": parts["member"]["id"],
            "subject_host_id": parts["host"]["id"],
            "rating": 5,
            "public_note": "quiet and friendly",
            "advance_notice_hours": 240,
        },
        make_member_headers(parts["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ELIGIBLE, 403)


def test_a_member_author_review_is_admitted_after_the_stay_completes(api):
    """PRD §3.8: "Withdrawal reverses everything a review did: the review moves to
    `WITHDRAWN`, both rating aggregates are recomputed without it"
    PRD §2.6: "`member_rating_average` averages the `rating` of the member-author
    reviews written by a given member that are in `PUBLISHED` status, rounded the same
    way."

    Design: Difficulty/cross_entity_state_dependency/member_author_review_gated_on_stay_checkout_completion
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-10", nights=1,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    host_headers = make_host_operator_headers(host_id)

    set_clock("2026-06-10T14:00:00Z")
    validate_success(api.check_in_stay(parts["stay"]["id"], host_headers))
    set_clock("2026-06-11T12:00:00Z")
    validate_success(api.check_out_stay(parts["stay"]["id"], host_headers))

    review = validate_success(
        api.create_review(
            {
                "author_member_id": member_id,
                "subject_host_id": host_id,
                "rating": 5,
                "public_note": "quiet and friendly",
                "advance_notice_hours": 240,
            },
            make_member_headers(member_id),
        ),
        201,
    )
    assert review["author_kind"] == "MEMBER"
    assert review["review_status"] == "PUBLISHED"

    member = read_member(member_id)
    assert member["member_rating_average"] == 5.00
    assert member["total_stays_completed"] == 1