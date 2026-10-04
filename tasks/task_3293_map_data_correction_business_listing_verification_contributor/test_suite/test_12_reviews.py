"""Review moderation: flag limits, fake detection, and aggregate restore."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_review_flag_payload,
    create_review_payload,
    flag_review,
    get_listing,
    make_contributor,
    make_contributor_headers,
    make_listing,
    make_region,
    make_review,
    open_moderation_ticket,
    resolve_ticket,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_review_count_add_then_remove_restores_aggregate(api):
    """PRD §3.5: "The listing's `review_count` and `rating_avg` recompute over
    published reviews only — the mean rating rounds half-up to two decimals
    and is 0.0 when no published reviews exist — and both health variants
    recompute."
    PRD §3.5: "Removing the review moves it to `REMOVED`, upholds the flag,
    revokes the author's review grant — returning `total_points` to its
    pre-review value — and recomputes the listing aggregates and health; if
    the public health score drops below 30 the listing's `visibility` becomes
    `RESTRICTED`."

    Design: Difficulty/compensating_invariant/listing_review_count_add_then_remove_restores_aggregate
    """
    region = make_region(name="R18")
    reviewer = make_contributor(region["id"], display_name="C17", email="c17@x.com")
    flagger = make_contributor(region["id"], display_name="C18", email="c18@x.com")
    listing = make_listing(region["id"], name="Cafe Eighteen")

    review = make_review(listing["id"], reviewer["id"], rating=4,
                         text="Solid coffee and quick service, will visit again.")
    after_add = get_listing(listing["id"])
    assert after_add["review_count"] == 1
    assert after_add["rating_avg"] == pytest.approx(4.0, abs=0.005)

    flag = flag_review(review["id"], flagger["id"], reason="SPAM")
    ticket = open_moderation_ticket(flag["id"], "mod-1")
    resolve_ticket(ticket["id"], "mod-1", "REMOVE")

    final = get_listing(listing["id"])
    assert final["review_count"] == 0, (
        f"REMOVE restores review_count to its pre-creation value, "
        f"got {final['review_count']}"
    )
    assert final["rating_avg"] == pytest.approx(0.0, abs=0.005), (
        f"empty PUBLISHED set -> rating_avg 0.0, got {final['rating_avg']}"
    )
    review_read = validate_success(api.get_review(review["id"], ADMIN))
    assert review_read["status"] == "REMOVED"


def test_review_remove_revokes_grant_restoring_total_points(api):
    """PRD §3.5: "A new review publishes immediately as `PUBLISHED` and earns
    its author a `REVIEW` grant with `base_points` of 2 and the author's
    level-based multiplier."
    PRD §3.5: "Removing the review moves it to `REMOVED`, upholds the flag,
    revokes the author's review grant — returning `total_points` to its
    pre-review value — and recomputes the listing aggregates and health; if
    the public health score drops below 30 the listing's `visibility` becomes
    `RESTRICTED`."

    Design: Difficulty/compensating_invariant/listing_review_count_add_then_remove_restores_aggregate
    """
    region = make_region(name="R18b")
    reviewer = make_contributor(region["id"], display_name="C17b",
                                email="c17b@x.com")
    flagger = make_contributor(region["id"], display_name="C18b",
                               email="c18b@x.com")
    listing = make_listing(region["id"], name="Cafe Eighteen B")

    before = validate_success(api.get_contributor(reviewer["id"], ADMIN))
    assert before["total_points"] == 0

    review = make_review(listing["id"], reviewer["id"], rating=4,
                         text="Solid coffee and quick service, will visit again.")
    mid = validate_success(api.get_contributor(reviewer["id"], ADMIN))
    # NEWCOMER multiplier 1.0? The level-based review multiplier for a fresh
    # NEWCOMER reviewer yields round(2 * weight) points posted.
    assert mid["total_points"] > 0

    flag = flag_review(review["id"], flagger["id"], reason="SPAM")
    ticket = open_moderation_ticket(flag["id"], "mod-1")
    resolve_ticket(ticket["id"], "mod-1", "REMOVE")

    after = validate_success(api.get_contributor(reviewer["id"], ADMIN))
    assert after["total_points"] == before["total_points"], (
        f"total_points returns to its pre-review value, got "
        f"{after['total_points']}"
    )
    assert after["lifetime_points"] == mid["lifetime_points"], (
        "revocation preserves grant history in lifetime_points"
    )


def test_flag_limit_and_sixth_flag_rejected(api):
    """PRD §3.5: "Flagging requires the review to be `PUBLISHED` (or already
    `FLAGGED`) and its `flag_count` to be below five; a review at five open
    flags, or in any other state, refuses further flags with
    `ERR_FLAG_LIMIT_REACHED` (HTTP 409)."

    Design: Corner/validations/flag_limit_and_non_owner_submit_code
    """
    region = make_region(name="RFlag")
    flaggers = [
        make_contributor(region["id"], display_name=f"F{i}", email=f"f{i}@x.com")
        for i in range(1, 8)
    ]
    reviewer = flaggers[0]
    listing = make_listing(region["id"], name="Flag Biz")
    review = make_review(listing["id"], reviewer["id"], rating=2,
                         text="Mediocre at best, staff seemed distracted throughout.")

    for flagger in flaggers[1:6]:
        flag_review(review["id"], flagger["id"], reason="SPAM")
    review_read = validate_success(api.get_review(review["id"], ADMIN))
    assert review_read["flag_count"] == 5

    resp = api.flag_review(
        review["id"], create_review_flag_payload(reason="HATE"),
        make_contributor_headers(flaggers[6]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FLAG_LIMIT_REACHED)


def test_fake_probability_auto_flag_at_threshold(api):
    """PRD §3.5: "Four binary signals feed the probability: the reviewer's
    `finalized_trust_score` below 30 contributes 0.10; a burst pattern — at
    least three other reviews by the same reviewer within the trailing 24
    hours on listings in the same region — contributes 0.25; text shorter than
    20 characters contributes 0.30; and a reviewer account less than seven
    days old contributes 0.35."
    PRD §3.5: "At or above the auto-flag threshold of 0.80, the system itself
    opens a `FAKE` flag with no reporter and moves the review from `PUBLISHED`
    to `FLAGGED`."

    Design: Corner/calculations/fake_probability_auto_flag_at_threshold
    """
    region = make_region(name="RFake")
    target = make_listing(region["id"], name="Target")
    others = [make_listing(region["id"], name=f"Other{i}") for i in (1, 2, 3)]
    newbie = make_contributor(region["id"], display_name="Newbie", email="nb@x.com")

    for other in others:
        make_review(other["id"], newbie["id"], rating=5, text="ok")

    resp = api.create_review(
        create_review_payload(listing_id=target["id"],
                              contributor_id=newbie["id"], rating=1, text="bad"),
        make_contributor_headers(newbie["id"]),
    )
    review = validate_success(resp, expected_status=201)
    assert review["fake_probability"] == pytest.approx(0.90, abs=0.005), (
        f"0.35 new account + 0.30 short text + 0.25 burst = 0.90, "
        f"got {review['fake_probability']}"
    )
    assert review["status"] == "FLAGGED", (
        f"auto-flag at >= 0.80, got {review['status']}"
    )

    flags, _meta = validate_paginated(
        api.list_review_flags(ADMIN, params={"review_id": review["id"]})
    )
    auto = [f for f in flags
            if f["reason"] == "FAKE" and f["status"] == "OPEN"
            and f["reporter_contributor_id"] is None]
    assert len(auto) == 1, f"expected one auto FAKE flag, got {len(auto)}"
