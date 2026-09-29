"""State paths that are not straight lines.

Two rows in this contract refuse to walk a single ordered chain of states. A
neighbourhood post cycles: it can leave ``REVISION_REQUESTED`` for either
``FLAGGED`` or ``PUBLISHED`` depending on the score its rewrite earns, so it
visits the same states twice while ``flag_count`` keeps climbing, and the third
``REQUEST_REVISION`` decision lands on ``REMOVED`` rather than on
``REVISION_REQUESTED`` because a counter, not the topology, bounds the loop. A
video request instead carries two state dimensions on one row, and each moves
without waiting for or locking the other.

Every scenario pins the logical clock first, quotes the parent ``version`` it
observed on the read immediately preceding each guarded write, and asserts the
full final state rather than the status code alone.
"""

from typing import Any, Dict, List, Tuple

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiClient, assertions, constants as k, factories as f, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    MODERATOR_HEADERS,
    MODERATOR_SECOND_HEADERS,
    make_officer_headers,
    make_resident_headers,
)

# Five camera positions on the northing axis, all inside a 500 m disc at the
# origin, so a locked area freezes a roster of five and the density limb of the
# independent-audit trigger fires.
_FIVE_POSITIONS: Tuple[Tuple[int, int], ...] = ((0, 10), (0, 20), (0, 30), (0, 40), (0, 50))


def _seed_author_and_flaggers(api: ApiClient) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """One author and three other residents, none of whom can be alerted.

    Every account is registered with an alert radius of zero and at its own
    grid position, so publishing never fans out and every state move observed
    afterwards is the moderation machine's own.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    author = fixtures.register_resident(
        api,
        display_name="RA",
        email="ra@example.test",
        home_x_m=0,
        home_y_m=0,
        alert_radius_m=0,
        notification_budget_per_day=6,
    )
    others: List[Dict[str, Any]] = []
    for name, easting in (("RB", 100), ("RC", 200), ("RD", 300)):
        others.append(
            fixtures.register_resident(
                api,
                display_name=name,
                email=f"{name.lower()}@example.test",
                home_x_m=easting,
                home_y_m=0,
                alert_radius_m=0,
                notification_budget_per_day=6,
            )
        )
    return author, others


def _open_case_on_observed_post(
    api: ApiClient, post_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Read the post, then open a case quoting exactly the version just read."""
    observed = fixtures.read_post(api, post_id)
    return fixtures.open_case(api, observed, MODERATOR_HEADERS, **overrides)


def test_post_walks_two_revision_laps_and_the_third_request_removes_it(
    api: ApiClient,
) -> None:
    """A post cycles twice through review and the third revision request removes it.

    PRD: "The post itself moves `PUBLISHED → FLAGGED` with `auto_flag_reason` set to `RESIDENT_FLAG_THRESHOLD` only once `flag_count` has reached the resident-flag threshold of 2; a first, solitary flag leaves the post in `PUBLISHED` while still bumping the counter and the version."
    PRD: "`REQUEST_REVISION` on a post whose `revision_count` is still below the ceiling of 2 sends it `UNDER_REVIEW → REVISION_REQUESTED`; the counter is incremented by the author's revision, not by this decision."
    PRD: "If the new score is 0.49 or above the post drops `REVISION_REQUESTED → FLAGGED` with `auto_flag_reason` set back to `DISCRIMINATION_SCORE` and no fan-out occurs at all, because the post is not in the feed."
    PRD: "If the new score is below 0.49 the post returns `REVISION_REQUESTED → PUBLISHED`, `auto_flag_reason` is cleared, and a fresh fan-out batch is emitted with the three alert counters rewritten from scratch against the post's possibly-changed position."
    PRD: "So does `REQUEST_REVISION` on a post that has already used both its revision laps: a third request for revision is not a reprieve, it is a removal, and it is charged to the author as an accuracy strike."

    Design: Difficulty/non_linear_state_machine/resident_post_two_full_revision_laps_then_cycle_termination
    """
    author, (flagger_b, flagger_c, flagger_d) = _seed_author_and_flaggers(api)

    post = fixtures.create_post(
        api, author["id"], body="Original wording, no problematic signals."
    )
    assert post["state"] == k.POST_PUBLISHED
    assertions.assert_score(post["discrimination_score"], "0.00")
    assertions.assert_nulls(post, "auto_flag_reason")
    assert post["flag_count"] == 0
    assert post["revision_count"] == 0

    after_one_flag = fixtures.flag_post(api, post["id"], flagger_b["id"])
    assert after_one_flag["state"] == k.POST_PUBLISHED
    assert after_one_flag["flag_count"] == 1

    flagged = fixtures.flag_post(api, post["id"], flagger_c["id"])
    assert flagged["state"] == k.POST_FLAGGED
    assert flagged["flag_count"] == k.RESIDENT_FLAG_THRESHOLD
    assert flagged["auto_flag_reason"] == k.AUTO_FLAG_RESIDENT_FLAGS

    case_one = _open_case_on_observed_post(api, post["id"])
    assert fixtures.read_post(api, post["id"])["state"] == k.POST_UNDER_REVIEW

    fixtures.decide_case(
        api,
        case_one["id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_REQUEST_REVISION,
        decision_note="Rewrite the description of the person.",
    )
    sent_back = fixtures.read_post(api, post["id"])
    assert sent_back["state"] == k.POST_REVISION_REQUESTED
    assert sent_back["revision_count"] == 0

    lap_one = fixtures.revise_post(
        api,
        post["id"],
        author["id"],
        body="First rewrite, still leaning on location and tone.",
        location_profiling_count=3,
        hostile_tone_count=3,
    )
    assert lap_one["state"] == k.POST_FLAGGED
    assertions.assert_score(lap_one["discrimination_score"], "0.61")
    assert lap_one["auto_flag_reason"] == k.AUTO_FLAG_DISCRIMINATION_SCORE
    assert lap_one["revision_count"] == 1
    assert lap_one["flag_count"] == 2

    case_two = _open_case_on_observed_post(
        api, post["id"], opened_reason=k.OPENED_REASON_AUTO_SCORE
    )
    assert fixtures.read_post(api, post["id"])["state"] == k.POST_UNDER_REVIEW
    fixtures.decide_case(
        api,
        case_two["id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_REQUEST_REVISION,
        decision_note="Second and final rewrite.",
    )
    assert fixtures.read_post(api, post["id"])["state"] == k.POST_REVISION_REQUESTED

    lap_two = fixtures.revise_post(
        api, post["id"], author["id"], body="Second rewrite, neutral wording throughout."
    )
    assert lap_two["state"] == k.POST_PUBLISHED
    assertions.assert_score(lap_two["discrimination_score"], "0.00")
    assertions.assert_nulls(lap_two, "auto_flag_reason")
    assert lap_two["revision_count"] == k.MAX_REVISIONS
    assert lap_two["flag_count"] == 2

    third_flag = fixtures.flag_post(api, post["id"], flagger_d["id"])
    assert third_flag["state"] == k.POST_FLAGGED
    assert third_flag["flag_count"] == 3
    assert third_flag["auto_flag_reason"] == k.AUTO_FLAG_RESIDENT_FLAGS

    case_three = _open_case_on_observed_post(api, post["id"])
    fixtures.decide_case(
        api,
        case_three["id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_REQUEST_REVISION,
        decision_note="Revision budget exhausted.",
    )

    final_post = fixtures.read_post(api, post["id"])
    assert final_post["state"] == k.POST_REMOVED
    assert final_post["revision_count"] == k.MAX_REVISIONS
    assert final_post["flag_count"] == 3

    for case in (case_one, case_two, case_three):
        decided = fixtures.read_case(api, case["id"])
        assert decided["state"] == k.CASE_DECIDED
        assert decided["decision"] == k.DECISION_REQUEST_REVISION

    struck = fixtures.read_resident(api, author["id"])
    assert struck["accuracy_strike_count"] == 1
    assert struck["discrimination_strike_count"] == 0
    assert struck["total_strike_score"] == 1
    assertions.assert_strike_ladder(struck)
    assert struck["post_privilege_state"] == k.PRIVILEGE_UNRESTRICTED


def _walk_post_through_two_laps(api: ApiClient) -> Dict[str, Any]:
    """Carry one post through both of its revision laps and back into the feed.

    The post is published, flagged to the threshold, sent back for revision,
    rewritten into a score that flags it again, sent back a second time,
    rewritten into a score that publishes it, and then flagged once more so it
    is eligible for a third moderation case.
    """
    author, (flagger_b, flagger_c, flagger_d) = _seed_author_and_flaggers(api)
    post = fixtures.create_post(
        api, author["id"], body="Original wording, no problematic signals."
    )
    fixtures.flag_post(api, post["id"], flagger_b["id"])
    fixtures.flag_post(api, post["id"], flagger_c["id"])

    case_one = _open_case_on_observed_post(api, post["id"])
    fixtures.decide_case(
        api,
        case_one["id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_REQUEST_REVISION,
        decision_note="Rewrite the description of the person.",
    )
    lap_one = fixtures.revise_post(
        api,
        post["id"],
        author["id"],
        body="First rewrite, still leaning on location and tone.",
        location_profiling_count=3,
        hostile_tone_count=3,
    )

    case_two = _open_case_on_observed_post(
        api, post["id"], opened_reason=k.OPENED_REASON_AUTO_SCORE
    )
    fixtures.decide_case(
        api,
        case_two["id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_REQUEST_REVISION,
        decision_note="Second and final rewrite.",
    )
    lap_two = fixtures.revise_post(
        api, post["id"], author["id"], body="Second rewrite, neutral wording throughout."
    )

    third_flag = fixtures.flag_post(api, post["id"], flagger_d["id"])
    return {
        "author": author,
        "author_id": author["id"],
        "post_id": post["id"],
        "lap_one": lap_one,
        "lap_two": lap_two,
        "third_flag": third_flag,
        "case_ids": [case_one["id"], case_two["id"]],
    }


def test_third_revision_request_removes_the_post_and_blocks_a_further_revision(
    api: ApiClient,
) -> None:
    """The third revision request takes the removal edge and no rewrite is accepted after it.

    PRD: "`REQUEST_REVISION` on a post whose `revision_count` is still below the ceiling of 2 sends it `UNDER_REVIEW → REVISION_REQUESTED`; the counter is incremented by the author's revision, not by this decision."
    PRD: "So does `REQUEST_REVISION` on a post that has already used both its revision laps: a third request for revision is not a reprieve, it is a removal, and it is charged to the author as an accuracy strike."
    PRD: "The author revises a post that is in `REVISION_REQUESTED`, and only the author may do so; a post in any other state is refused with `ERR_POST_NOT_REVISABLE`, and an author whose privileges have since been suspended is refused with `ERR_POSTING_SUSPENDED`."

    Design: Difficulty/non_linear_state_machine/resident_post_two_full_revision_laps_then_cycle_termination
    """
    world = _walk_post_through_two_laps(api)
    post_id = world["post_id"]

    exhausted = fixtures.read_post(api, post_id)
    assert exhausted["state"] == k.POST_FLAGGED
    assert exhausted["revision_count"] == k.MAX_REVISIONS

    case_three = _open_case_on_observed_post(api, post_id)
    assert fixtures.read_post(api, post_id)["state"] == k.POST_UNDER_REVIEW
    fixtures.decide_case(
        api,
        case_three["id"],
        MODERATOR_SECOND_HEADERS,
        decision=k.DECISION_REQUEST_REVISION,
        decision_note="Revision budget exhausted.",
    )

    removed = fixtures.read_post(api, post_id)
    assert removed["state"] == k.POST_REMOVED
    assert removed["revision_count"] == k.MAX_REVISIONS
    assert removed["flag_count"] == 3
    removed_version = removed["version"]

    decided = fixtures.read_case(api, case_three["id"])
    assert decided["state"] == k.CASE_DECIDED
    assert decided["decision"] == k.DECISION_REQUEST_REVISION

    refused = api.revise_post(
        post_id,
        f.revise_payload(body="Third rewrite attempt, should be refused."),
        make_resident_headers(world["author_id"]),
    )
    validate_error(refused, ApiErrorId.POST_NOT_REVISABLE.value, 409)

    unchanged = fixtures.read_post(api, post_id)
    assert unchanged["state"] == k.POST_REMOVED
    assertions.assert_version_unchanged(unchanged, removed_version)
    assert unchanged["revision_count"] == k.MAX_REVISIONS

    struck = fixtures.read_resident(api, world["author_id"])
    assert struck["accuracy_strike_count"] == 1
    assert struck["discrimination_strike_count"] == 0
    assert struck["total_strike_score"] == 1
    assert struck["post_privilege_state"] == k.PRIVILEGE_UNRESTRICTED


def test_identical_revision_trigger_closes_into_flagged_then_into_published(
    api: ApiClient,
) -> None:
    """The same rewrite step closes the cycle into FLAGGED once and into PUBLISHED once.

    PRD: "If the new score is 0.49 or above the post drops `REVISION_REQUESTED → FLAGGED` with `auto_flag_reason` set back to `DISCRIMINATION_SCORE` and no fan-out occurs at all, because the post is not in the feed."
    PRD: "If the new score is below 0.49 the post returns `REVISION_REQUESTED → PUBLISHED`, `auto_flag_reason` is cleared, and a fresh fan-out batch is emitted with the three alert counters rewritten from scratch against the post's possibly-changed position."
    PRD: "The revision replaces the `body` and the four classifier signals, re-runs the score, and increments `revision_count` by 1."
    PRD: "`flag_count` is monotonic — it is never decremented, not even when a revision cycle returns the post to the feed, so a post that has once been flagged twice carries that history for good."

    Design: Difficulty/non_linear_state_machine/resident_post_two_full_revision_laps_then_cycle_termination
    """
    world = _walk_post_through_two_laps(api)
    lap_one = world["lap_one"]
    lap_two = world["lap_two"]

    assert lap_one["state"] == k.POST_FLAGGED
    assertions.assert_score(lap_one["discrimination_score"], "0.61")
    assert lap_one["auto_flag_reason"] == k.AUTO_FLAG_DISCRIMINATION_SCORE
    assert lap_one["revision_count"] == 1
    assert lap_one["flag_count"] == k.RESIDENT_FLAG_THRESHOLD

    assert lap_two["state"] == k.POST_PUBLISHED
    assertions.assert_score(lap_two["discrimination_score"], "0.00")
    assertions.assert_nulls(lap_two, "auto_flag_reason")
    assert lap_two["revision_count"] == k.MAX_REVISIONS
    assert lap_two["flag_count"] == k.RESIDENT_FLAG_THRESHOLD
    assert lap_two["version"] > lap_one["version"]

    back_in_the_feed_then_flagged = world["third_flag"]
    assert back_in_the_feed_then_flagged["state"] == k.POST_FLAGGED
    assert back_in_the_feed_then_flagged["flag_count"] == 3
    assert back_in_the_feed_then_flagged["auto_flag_reason"] == k.AUTO_FLAG_RESIDENT_FLAGS
    assert back_in_the_feed_then_flagged["revision_count"] == k.MAX_REVISIONS

    cases = fixtures.list_cases_for_post(api, world["post_id"])
    assert [case["id"] for case in cases] == world["case_ids"]
    for case in cases:
        assert case["state"] == k.CASE_DECIDED
        assert case["decision"] == k.DECISION_REQUEST_REVISION


def _seed_dense_draft_request(api: ApiClient) -> Dict[str, Any]:
    """An onboarded agency, a requester, a separate auditor and a draft request.

    Five residents each own one active camera inside a 500 m disc at the origin,
    so locking the area freezes a roster of five cameras. The request is created
    against the locked area quoting the version read immediately beforehand, and
    is left in draft with nothing justified yet.
    """
    fixtures.set_clock(api, fixtures.SCENARIO_CLOCK)
    world = fixtures.seed_agency_with_officer(
        api,
        min_device_threshold=3,
        max_open_requests=3,
        period_request_quota=20,
        post_share_retention_days=30,
        justification_min_chars=80,
    )
    auditor = fixtures.add_auditor(api, world["agency_id"])
    world["households"] = fixtures.seed_residents_with_devices(api, _FIVE_POSITIONS)
    locked = fixtures.seed_locked_area(api, world["agency_id"], world["officer_id"])
    observed_area = fixtures.read_area(api, locked["id"])
    created = fixtures.create_video_request(
        api, observed_area, world["officer_id"], case_number="CASE-9004"
    )
    world["auditor"] = auditor
    world["auditor_id"] = auditor["id"]
    world["area"] = observed_area
    world["created"] = created
    world["request_id"] = created["id"]
    return world


def test_compliance_dimension_reaches_its_terminal_while_lifecycle_walks_to_fulfilled(
    api: ApiClient,
) -> None:
    """Escalation ends the compliance dimension while the lifecycle dimension runs on to FULFILLED.

    PRD: "The two dimensions advance independently: the compliance dimension moves while the lifecycle dimension is still sitting in `DRAFT`, and the lifecycle dimension moves without disturbing the compliance dimension."
    PRD: "`CLEAR` moves the compliance dimension `AUDIT_FLAGGED → AUDIT_CLEARED` and returns the request to ordinary handling; `ESCALATE` moves it `AUDIT_FLAGGED → AUDIT_ESCALATED`."
    PRD: "Both outcomes store the `audit_note`, stamp `auditor_officer_id` from the acting officer's identity, increment that officer's `audits_completed_count` by 1, advance the request's `version` by 1, and leave `lifecycle_state` entirely alone — a request may be audited while it is still soliciting."
    PRD: "If at least one of the request's solicitations is `SHARED`, the request moves `SOLICITING → FULFILLED` and its `provisional_share_rate_bps` is recomputed."
    PRD: "This is the second and last crossing between the two state dimensions: the compliance dimension is not consulted and does not move."
    PRD: "A request's `provisional_share_rate_bps` is the live share rate over that request's own solicitations, computed in basis points as described in §2.7: the numerator is the number of the request's solicitations in `SHARED`, the denominator is the number of the request's solicitations in total — every one of them, including those still `SOLICITED`, those `WITHDRAWN`, and those whose notification was suppressed."
    PRD: "On success both counters move, but only the first can ever come back down — `open_request_count` is incremented by 1 and is decremented again when the request resolves, whereas `requests_submitted_count` is incremented by 1 and is never decremented."

    Design: Difficulty/non_linear_state_machine/video_request_lifecycle_and_compliance_dimensions_advance_independently
    """
    world = _seed_dense_draft_request(api)
    request_id = world["request_id"]

    fixtures.log_justification(api, request_id, world["officer_id"])
    submitted = fixtures.submit_request(api, request_id, world["officer_id"])
    assert submitted["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assert submitted["compliance_state"] == k.COMPLIANCE_AUDIT_FLAGGED
    assertions.assert_solicitation_buckets(submitted, 5, 0, 0, 0, 0)
    assertions.assert_solicitation_ledger(submitted, 5)

    escalated = fixtures.escalate_audit(
        api,
        request_id,
        world["auditor_id"],
        audit_note="Dense canvass; supervisory hold applied.",
    )
    assert escalated["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assert escalated["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED
    assert escalated["auditor_officer_id"] == world["auditor_id"]
    assert fixtures.read_officer(api, world["auditor_id"])["audits_completed_count"] == 1

    solicitations = fixtures.list_solicitations(api, video_request_id=request_id)
    assert len(solicitations) == 5
    sharer, decliners = solicitations[0], solicitations[1:]
    fixtures.share_footage(
        api,
        sharer["id"],
        sharer["resident_id"],
        recorded_start_utc="2026-08-08T01:00:00Z",
        duration_seconds=1800,
    )
    for solicitation in decliners:
        fixtures.decline_solicitation(
            api,
            solicitation["id"],
            solicitation["resident_id"],
            decline_reason=k.DECLINE_OWNER_DECLINE,
        )

    resolved = fixtures.read_request(api, request_id)
    assert resolved["lifecycle_state"] == k.LIFECYCLE_FULFILLED
    assert resolved["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED
    assertions.assert_solicitation_buckets(resolved, 0, 1, 4, 0, 0)
    assertions.assert_solicitation_ledger(resolved, 5)
    assert resolved["shared_clip_count"] == 1
    assertions.assert_bps(
        resolved["provisional_share_rate_bps"], 2000, "provisional_share_rate_bps"
    )

    agency = fixtures.read_agency(api, world["agency_id"])
    assert agency["open_request_count"] == 0
    assert agency["requests_submitted_count"] == 1


def test_terminal_compliance_state_refuses_a_second_audit_yet_leaves_the_lifecycle_free(
    api: ApiClient,
) -> None:
    """An escalated request accepts no further audit decision but still resolves its canvass.

    PRD: "`compliance_state` tracks justification and audit posture through `JUSTIFICATION_PENDING`, `JUSTIFICATION_LOGGED`, `AUDIT_FLAGGED`, `AUDIT_CLEARED` and `AUDIT_ESCALATED`, of which the last two are terminal."
    PRD: "It is only accepted while `compliance_state` is `AUDIT_FLAGGED` — otherwise `ERR_AUDIT_NOT_PENDING` — and the acting officer must belong to the same agency as the request, must hold a `duty_role` of `AUDITOR` or `DUAL_ROLE`, and must not be the request's `submitting_officer_id`."
    PRD: "If at least one of the request's solicitations is `SHARED`, the request moves `SOLICITING → FULFILLED` and its `provisional_share_rate_bps` is recomputed."

    Design: Difficulty/non_linear_state_machine/video_request_lifecycle_and_compliance_dimensions_advance_independently
    """
    world = _seed_dense_draft_request(api)
    request_id = world["request_id"]
    fixtures.log_justification(api, request_id, world["officer_id"])
    fixtures.submit_request(api, request_id, world["officer_id"])
    escalated = fixtures.escalate_audit(
        api,
        request_id,
        world["auditor_id"],
        audit_note="Dense canvass; supervisory hold applied.",
    )
    assert escalated["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED

    observed = fixtures.read_request(api, request_id)
    version_before = observed["version"]
    refused = api.review_audit(
        request_id,
        f.audit_review_payload(
            decision=k.AUDIT_DECISION_CLEAR, audit_note="Second look after escalation."
        ),
        make_officer_headers(world["auditor_id"]),
    )
    validate_error(refused, ApiErrorId.AUDIT_NOT_PENDING.value, 409)

    unchanged = fixtures.read_request(api, request_id)
    assert unchanged["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED
    assert unchanged["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assertions.assert_version_unchanged(unchanged, version_before)

    solicitations = fixtures.list_solicitations(api, video_request_id=request_id)
    sharer, decliners = solicitations[0], solicitations[1:]
    fixtures.share_footage(
        api,
        sharer["id"],
        sharer["resident_id"],
        recorded_start_utc="2026-08-08T01:00:00Z",
        duration_seconds=1800,
    )
    for solicitation in decliners:
        fixtures.decline_solicitation(
            api,
            solicitation["id"],
            solicitation["resident_id"],
            decline_reason=k.DECLINE_OWNER_DECLINE,
        )

    resolved = fixtures.read_request(api, request_id)
    assert resolved["lifecycle_state"] == k.LIFECYCLE_FULFILLED
    assert resolved["compliance_state"] == k.COMPLIANCE_AUDIT_ESCALATED
    assertions.assert_solicitation_buckets(resolved, 0, 1, 4, 0, 0)


def test_each_trigger_advances_exactly_one_of_the_two_state_dimensions(
    api: ApiClient,
) -> None:
    """Logging the justification moves only the compliance dimension and submitting only the lifecycle one.

    PRD: "On success the request is created with `lifecycle_state` `DRAFT` and `compliance_state` `JUSTIFICATION_PENDING`, its `agency_id` copied from the area, its `submitting_officer_id` stamped from the acting officer's identity, `auditor_officer_id` null, `justification_text`, `statutory_basis`, `justification_logged_at`, `audit_note`, `withdraw_reason`, `submitted_at` and `expires_at` all null, every solicitation counter — `solicitation_count`, `pending_count`, `shared_count`, `declined_count`, `expired_count`, `withdrawn_count` and `shared_clip_count` — at 0, and `provisional_share_rate_bps` at 0."
    PRD: "On success both fields are stored, `justification_logged_at` is stamped from the logical clock, and the compliance dimension moves `JUSTIFICATION_PENDING → JUSTIFICATION_LOGGED`."
    PRD: "When the backing canvass area's `radius_m` is strictly greater than 1000 metres, **or** its frozen `eligible_device_count` is strictly greater than 4, the compliance dimension continues straight on `JUSTIFICATION_LOGGED → AUDIT_FLAGGED`: the request is wide or dense enough that an officer other than its author must sign off on it."
    PRD: "Either way `lifecycle_state` is left untouched at `DRAFT` and the request's `version` advances by 1."
    PRD: "`lifecycle_state` moves `DRAFT → SOLICITING`, `submitted_at` is stamped from the logical clock, and `expires_at` is set to exactly 72 hours after `submitted_at` — three days is the whole window a camera owner gets to answer."

    Design: Difficulty/non_linear_state_machine/video_request_lifecycle_and_compliance_dimensions_advance_independently
    """
    world = _seed_dense_draft_request(api)
    request_id = world["request_id"]
    assert world["area"]["eligible_device_count"] == 5

    created = world["created"]
    assert created["lifecycle_state"] == k.LIFECYCLE_DRAFT
    assert created["compliance_state"] == k.COMPLIANCE_JUSTIFICATION_PENDING
    assertions.assert_solicitation_buckets(created, 0, 0, 0, 0, 0)
    assertions.assert_solicitation_ledger(created, 0)
    assertions.assert_nulls(
        created,
        "auditor_officer_id",
        "justification_logged_at",
        "audit_note",
        "withdraw_reason",
        "submitted_at",
        "expires_at",
    )
    assertions.assert_bps(
        created["provisional_share_rate_bps"], 0, "provisional_share_rate_bps"
    )

    justified = fixtures.log_justification(api, request_id, world["officer_id"])
    assert justified["lifecycle_state"] == k.LIFECYCLE_DRAFT
    assert justified["compliance_state"] == k.COMPLIANCE_AUDIT_FLAGGED
    assertions.assert_version_advanced(justified, created["version"])
    assertions.assert_solicitation_buckets(justified, 0, 0, 0, 0, 0)
    assertions.assert_nulls(justified, "submitted_at", "expires_at")

    submitted = fixtures.submit_request(api, request_id, world["officer_id"])
    assert submitted["lifecycle_state"] == k.LIFECYCLE_SOLICITING
    assert submitted["compliance_state"] == k.COMPLIANCE_AUDIT_FLAGGED
    assertions.assert_version_advanced(submitted, justified["version"])
    assertions.assert_solicitation_buckets(submitted, 5, 0, 0, 0, 0)
    assertions.assert_instant(
        submitted["submitted_at"], fixtures.SCENARIO_CLOCK, "submitted_at"
    )
    assertions.assert_instant(submitted["expires_at"], "2026-08-15T00:00:00Z", "expires_at")
