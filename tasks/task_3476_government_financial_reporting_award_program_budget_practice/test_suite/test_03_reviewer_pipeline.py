"""Reviewer recruitment: self-application defaults, the ordered training /
attestation pipeline, closed-interval availability windows, and self-service
ownership (PRD §3.3, §2.1).
"""

from test_helpers import (
    ApiErrorId,
    PLATFORM_ADMIN,
    apply_for_reviewer,
    assert_reviewer_profile,
    attest_independence,
    create_government,
    create_member,
    make_member_headers,
    make_reviewer_headers,
    refresh_reviewer,
    reviewer_profile_payload,
    set_logical_clock,
    train_reviewer,
    update_reviewer_profile,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_reviewer_profile_create_defaults(api):
    """PRD §3.3: "The new profile starts as `APPLICANT`, its three counters
    `open_assignment_count`, `completed_review_count`, and
    `declined_assignment_count` start at zero, and `trained_at` stays null."
    PRD §3.3: "naming an `employer_government_id` and optionally attesting
    `conflicted_government_ids` and `unavailability_windows`, both of which
    default to empty lists."

    Design: Corner/entities/reviewer_profile_create_defaults
    """
    set_logical_clock(api)
    member = create_member(api)
    employer = create_government(api)

    resp = api.create_reviewer_profile(
        reviewer_profile_payload(member["id"], employer["id"]),
        headers=make_member_headers(member["id"]),
    )
    data = validate_success(resp, 201)
    assert_reviewer_profile(data)
    assert data["status"] == "APPLICANT"
    assert data["independence_attested"] is False
    assert data["open_assignment_count"] == 0
    assert data["completed_review_count"] == 0
    assert data["declined_assignment_count"] == 0
    assert data["trained_at"] is None
    assert data["conflicted_government_ids"] == []
    assert data["unavailability_windows"] == []


def test_reviewer_attestation_before_training_returns_not_trained(api):
    """PRD §3.3: "Attesting while still `APPLICANT` is rejected with
    `ERR_REVIEWER_NOT_TRAINED`, since training must come first, and attesting
    from any other state is rejected with `ERR_REVIEWER_STATE_INVALID`."
    PRD §3.3: "setting `independence_attested` to true moves the profile from
    `TRAINED` to `ELIGIBLE`."

    Design: Corner/state_machines/reviewer_attestation_before_training_returns_not_trained
    """
    set_logical_clock(api)
    member = create_member(api)
    employer = create_government(api)
    profile = apply_for_reviewer(api, member["id"], employer["id"])

    early = api.update_reviewer_profile(
        profile["id"],
        {"independence_attested": True},
        headers=make_reviewer_headers(profile["id"]),
    )
    validate_error(early, ApiErrorId.ERR_REVIEWER_NOT_TRAINED)
    assert refresh_reviewer(api, profile["id"])["status"] == "APPLICANT"

    trained = train_reviewer(api, profile["id"])
    assert trained["status"] == "TRAINED"
    assert trained["trained_at"] is not None

    attested = attest_independence(api, profile["id"])
    assert attested["status"] == "ELIGIBLE"


def test_reviewer_windows_closed_interval_touching_is_overlap(api):
    """PRD §3.3: "Each unavailability window is a pair of `start_date` and
    `end_date` forming a closed interval — both endpoints inclusive — and the
    windows on a profile must not intersect; since the intervals are closed,
    two windows that merely touch at an endpoint already count as overlapping
    and are rejected with `ERR_AVAILABILITY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/reviewer_windows_closed_interval_touching_is_overlap
    """
    set_logical_clock(api)
    member = create_member(api)
    employer = create_government(api)
    profile = apply_for_reviewer(api, member["id"], employer["id"])
    headers = make_reviewer_headers(profile["id"])

    base_window = {"start_date": "2026-10-01", "end_date": "2026-10-10"}
    updated = update_reviewer_profile(
        api, profile["id"], {"unavailability_windows": [base_window]}
    )
    assert len(updated["unavailability_windows"]) == 1

    # Touching at the endpoint (10-10 meets 10-10) already overlaps.
    touching = api.update_reviewer_profile(
        profile["id"],
        {
            "unavailability_windows": [
                base_window,
                {"start_date": "2026-10-10", "end_date": "2026-10-15"},
            ]
        },
        headers=headers,
    )
    validate_error(touching, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP)
    after_failure = refresh_reviewer(api, profile["id"])
    assert after_failure["unavailability_windows"] == [base_window], (
        "the rejected PUT must leave the original single window intact"
    )

    # A gap day (start 10-11) is not an intersection under closed semantics.
    gapped = validate_success(
        api.update_reviewer_profile(
            profile["id"],
            {
                "unavailability_windows": [
                    base_window,
                    {"start_date": "2026-10-11", "end_date": "2026-10-20"},
                ]
            },
            headers=headers,
        )
    )
    assert len(gapped["unavailability_windows"]) == 2


def test_member_cannot_apply_reviewer_for_other_member(api):
    """PRD §3.3: "a `Member` creates a reviewer profile whose `member_id` must
    equal the caller's own identity"
    PRD §2.1: "Any attempt to act on a resource owned by someone else — another
    government's submission, another reviewer's assignment or profile, a
    publication whose committee the caller does not sit on — is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/member_cannot_apply_reviewer_for_other_member
    """
    set_logical_clock(api)
    member_1 = create_member(api)
    member_2 = create_member(api)
    employer = create_government(api)

    resp = api.create_reviewer_profile(
        reviewer_profile_payload(member_2["id"], employer["id"]),
        headers=make_member_headers(member_1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

    rows, meta = validate_paginated(
        api.list_reviewer_profiles(
            headers=PLATFORM_ADMIN, params={"member_id": member_2["id"]}
        )
    )
    assert meta["total_count"] == 0 and rows == [], (
        "no reviewer profile may be created for another member"
    )
