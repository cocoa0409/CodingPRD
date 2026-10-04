"""Temporal overlap rules (queue A): half-open review windows, closed showtime windows."""
from test_helpers import (
    api_client, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, create_release, open_release, create_title, open_title,
    setup_accredited_publication, setup_accredited_critic, setup_open_release,
    create_audience_member, create_accreditation_review_payload,
    create_ticket_verification_payload, make_audience_member_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_headers"]


def _setup_critic_with_in_review_window():
    """CA accredited with review AR1 over [2026-08-01, 2026-09-01) already
    IN_REVIEW."""
    set_clock()
    pub = setup_accredited_publication()
    critic = setup_accredited_critic(pub["id"], full_name="Critic A")
    review = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(subject_critic_id=critic["id"]),
        BOARD))
    get_success_data(api_client.transition_accreditation_review(
        review["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    return critic, review


def test_adjacent_review_window_is_allowed_not_overlap():
    """PRD section 3.2: "Two windows that merely touch — one review's
    `period_end` equal to the other's `period_start` — are adjacent, not
    overlapping, and are permitted."

    Design: Difficulty/resource_temporal_overlap/accreditation_review_windows_half_open_adjacency_allowed
    """
    critic, _ = _setup_critic_with_in_review_window()
    adjacent = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(
            subject_critic_id=critic["id"],
            period_start="2026-09-01T00:00:00Z",
            period_end="2026-10-01T00:00:00Z"),
        BOARD))
    begun = get_success_data(api_client.transition_accreditation_review(
        adjacent["id"], {"action": "BEGIN_REVIEW"}, BOARD))
    assert begun["status"] == "IN_REVIEW"


def test_one_second_overlap_review_window_rejected():
    """PRD section 3.2: "the window must not half-open-overlap any other
    non-`DISMISSED` review for the same subject. Two windows that merely
    touch — one review's `period_end` equal to the other's `period_start` —
    are adjacent, not overlapping, and are permitted. A true overlap is
    rejected with `ERR_ACC_REVIEW_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/accreditation_review_windows_half_open_adjacency_allowed
    """
    critic, _ = _setup_critic_with_in_review_window()
    overlapping = get_success_data(api_client.create_accreditation_review(
        create_accreditation_review_payload(
            subject_critic_id=critic["id"],
            period_start="2026-08-31T23:59:59Z",
            period_end="2026-10-01T00:00:00Z"),
        BOARD))
    resp = api_client.transition_accreditation_review(
        overlapping["id"], {"action": "BEGIN_REVIEW"}, BOARD)
    validate_error(resp, ApiErrorId.ERR_ACC_REVIEW_PERIOD_OVERLAP)


def _setup_showtimes_at_window_boundaries():
    """Release with closed theatrical window [2026-09-05, 2026-09-20]; three
    members with SUBMITTED verifications at the start, the end, and one
    second past the end."""
    set_clock()
    title = open_title(create_title()["id"])
    release = open_release(create_release(
        title["id"],
        theatrical_window_start="2026-09-05T00:00:00Z",
        theatrical_window_end="2026-09-20T00:00:00Z")["id"])
    members = [create_audience_member() for _ in range(3)]
    showtimes = ["2026-09-05T00:00:00Z", "2026-09-20T00:00:00Z",
                 "2026-09-20T00:00:01Z"]
    tvs = []
    for member, showtime in zip(members, showtimes):
        tvs.append(get_success_data(api_client.create_ticket_verification(
            release["id"],
            create_ticket_verification_payload(
                member["id"], showtime_at=showtime),
            make_audience_member_headers(member["id"]))))
    return tvs


def test_showtime_at_window_start_verifies_closed_interval():
    """PRD section 3.6: "verifying requires the `showtime_at` to fall inside
    the release's theatrical window as a closed interval — a showtime exactly
    at `theatrical_window_start` or exactly at `theatrical_window_end` is
    inside".

    Design: Difficulty/resource_temporal_overlap/ticket_showtime_closed_interval_endpoints_inclusive
    """
    tvs = _setup_showtimes_at_window_boundaries()
    verified = get_success_data(api_client.transition_ticket_verification(
        tvs[0]["id"], {"action": "VERIFY"}, ADMIN))
    assert verified["status"] == "VERIFIED"


def test_showtime_at_window_end_verifies_and_past_end_fails():
    """PRD section 3.6: "verifying requires the `showtime_at` to fall inside
    the release's theatrical window as a closed interval — a showtime exactly
    at `theatrical_window_start` or exactly at `theatrical_window_end` is
    inside — and a showtime outside that window is rejected with
    `ERR_VERIFICATION_WINDOW_MISS` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ticket_showtime_closed_interval_endpoints_inclusive
    """
    tvs = _setup_showtimes_at_window_boundaries()
    verified = get_success_data(api_client.transition_ticket_verification(
        tvs[1]["id"], {"action": "VERIFY"}, ADMIN))
    assert verified["status"] == "VERIFIED"
    resp = api_client.transition_ticket_verification(
        tvs[2]["id"], {"action": "VERIFY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_WINDOW_MISS)
