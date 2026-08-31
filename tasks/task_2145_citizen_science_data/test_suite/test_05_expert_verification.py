"""Expert verification, weighted consensus and the bounded revision cycle."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_observation,
    assert_verification_vote,
    build_world,
    cast_vote,
    create_expert,
    create_site,
    drive_to_under_review,
    make_expert_headers,
    open_campaign,
    push_revision_round,
    read_certification,
    read_expert,
    read_observation,
    read_volunteer,
    resubmit,
    start_review,
    submit_with_photo,
    STAGE_CAMPAIGN,
    STAGE_OPEN,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def test_provisional_points_are_fixed_at_submission_and_final_points_diverge(api):
    """PRD 3.5: "`provisional_quality_points` is that raw score rounded to two
    decimal places."
    PRD 3.6: "The first is a confidence multiplier equal to 0.60 plus 0.10 times
    the observation's stored four-decimal `consensus_confidence`."
    PRD 3.6: "Because the raw score is never rounded before this multiplication,
    `final_quality_points` will generally differ from `provisional_quality_points`
    even when the confidence multiplier and revision penalty happen to work out to
    1.00."

    Design: Difficulty/dual_variant_calc/observation_provisional_vs_final_points_diverge
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    assert float(observation["provisional_quality_points"]) == pytest.approx(60.00, abs=1e-9)
    assert float(observation["final_quality_points"]) == pytest.approx(0.0, abs=1e-9)

    cast_vote(observation["id"], world["e1_headers"], "CONFIRM", 5)
    cast_vote(observation["id"], world["e2_headers"], "CONFIRM", 5)

    stored = read_observation(observation["id"])
    assert float(stored["provisional_quality_points"]) == pytest.approx(60.00, abs=1e-9), (
        f"The provisional variant rounds the raw score to 60.00, got "
        f"{stored['provisional_quality_points']}")
    assert float(stored["final_quality_points"]) == pytest.approx(66.00, abs=1e-9), (
        f"60 raw * 1.10 confidence multiplier is 66.00, got "
        f"{stored['final_quality_points']}")
    assert float(stored["final_quality_points"]) != \
        float(stored["provisional_quality_points"])


def test_acceptance_records_consensus_weights_and_queues_the_record(api):
    """PRD 3.6: "The observation's `confirm_weight`, `reject_weight`, and
    `revision_weight` are the sums of the already-rounded `weight_applied` values of
    the current round's `CONFIRM`, `REJECT`, and `REQUEST_REVISION` votes
    respectively, each carried to four decimal places."
    PRD 3.6: "Otherwise, if `confirm_weight` has reached 3.0 and is strictly
    greater than `reject_weight`, the observation resolves `UNDER_REVIEW →
    ACCEPTED`."
    PRD 3.7: "In the first link the observation's `final_quality_points` are
    computed as described in §3.6 and its `publication_status` moves `UNPUBLISHED →
    QUEUED`, making it a candidate for the campaign's next publication."

    Design: Difficulty/dual_variant_calc/observation_provisional_vs_final_points_diverge
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], world["e1_headers"], "CONFIRM", 5)
    cast_vote(observation["id"], world["e2_headers"], "CONFIRM", 5)

    stored = read_observation(observation["id"])
    assert_observation(stored)
    assert float(stored["consensus_confidence"]) == pytest.approx(5.0000, abs=1e-9)
    assert float(stored["confirm_weight"]) == pytest.approx(4.4000, abs=1e-9), (
        f"Two weight-2.00 experts at confidence 5 sum to 4.4000, got "
        f"{stored['confirm_weight']}")
    assert stored["review_status"] == "ACCEPTED"
    assert stored["publication_status"] == "QUEUED"


def test_resubmission_reopens_the_record_in_a_new_revision_round(api):
    """PRD 3.6: "The observer may then act on it: resubmitting moves the record
    `NEEDS_REVISION → SUBMITTED`, and only the observer who filed it may do so."
    PRD 3.6: "A resubmission may correct the record in place by supplying any of
    `latitude`, `longitude`, `species_code`, or `count_value`; each is optional and
    an omitted field keeps its existing value."
    PRD 3.6: "On success `revision_round` increments by one, `submitted_at` is
    re-stamped from the logical clock, and `provisional_quality_points` is recomputed
    from the new `submitted_at` — which usually means the timeliness factor drops,
    because the clock has moved on since the sighting."

    Design: Difficulty/non_linear_state_machine/observation_revision_cycle_returns_to_submitted
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_with_photo(world, count_value=3)
    push_revision_round(world, observation["id"], confidence=2)
    assert read_observation(observation["id"])["review_status"] == "NEEDS_REVISION"

    resubmitted = resubmit(world, observation["id"], count_value=4)

    assert resubmitted["review_status"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["count_value"] == 4
    assert resubmitted["submitted_at"] == "2026-08-05T09:00:00.000Z"
    assert float(resubmitted["provisional_quality_points"]) == pytest.approx(60.00, abs=1e-9), (
        f"The lag is unchanged so the provisional figure stays 60.00, got "
        f"{resubmitted['provisional_quality_points']}")


def test_earlier_round_votes_are_retained_but_stop_counting(api):
    """PRD 3.6: "Votes from the earlier round remain on file but stop counting,
    since consensus only ever sums the current round."
    PRD 3.6: "Each accepted vote is stored as a ledger row bearing its
    `observation_id`, `expert_id`, the `round_number` copied from the observation's
    current `revision_round` at insert time, the `decision`, the `confidence`, the
    `comment`, and a `weight_applied` computed as the expert's `verification_weight`
    multiplied by the quantity 0.6 plus 0.1 times the vote's `confidence`, rounded
    to four decimal places — so a weight-2.00 expert voting at confidence 5
    contributes 2.2000, while the same expert voting at confidence 1 contributes
    1.4000."
    PRD 3.6: "Only votes whose `round_number` equals the observation's current
    `revision_round` participate; votes from earlier rounds are retained for audit
    and are never re-summed."

    Design: Difficulty/non_linear_state_machine/observation_revision_cycle_returns_to_submitted
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_with_photo(world, count_value=3)
    push_revision_round(world, observation["id"], confidence=2)
    resubmit(world, observation["id"], count_value=4)

    rows, meta = validate_paginated(api.list_votes(
        observation["id"], ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, f"Both round-0 votes stay on file, got {meta['total_count']}"
    assert all(row["round_number"] == 0 for row in rows), (
        f"Retained votes keep their original round_number, got "
        f"{[row['round_number'] for row in rows]}")

    # The next consensus recompute sums the current round alone: the two
    # round-0 REQUEST_REVISION votes (1.6000 each) are never re-summed.
    start_review(observation["id"], world["e1_headers"])
    cast_vote(observation["id"], world["e1_headers"], "REQUEST_REVISION", 2)

    stored = read_observation(observation["id"])
    assert stored["revision_round"] == 1, (
        f"Resubmission advanced the observation to round 1, got {stored['revision_round']}")
    assert float(stored["revision_weight"]) == pytest.approx(1.6000, abs=1e-9), (
        f"Only the single round-1 vote counts (2.00 x (0.6 + 0.1 x 2) = 1.6000), "
        f"got {stored['revision_weight']}")

    rows, meta = validate_paginated(api.list_votes(
        observation["id"], ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 3, (
        f"The round-0 votes remain on file alongside the new one, got {meta['total_count']}")
    assert sorted(row["round_number"] for row in rows) == [0, 0, 1], (
        f"Retained votes keep their original round_number, got "
        f"{sorted(row['round_number'] for row in rows)}")


def test_verification_vote_is_an_append_only_ledger_row(api):
    """PRD 2.4: "Two record types are exceptions: `VerificationVote` and
    `RecognitionAward` are append-only ledger rows. Both carry only `id` and
    `created_at`; neither carries `updated_at` and neither carries `version`."
    PRD 3.6: "Each accepted vote is stored as a ledger row bearing its
    `observation_id`, `expert_id`, the `round_number` copied from the observation's
    current `revision_round` at insert time, the `decision`, the `confidence`, the
    `comment`, and a `weight_applied` computed as the expert's `verification_weight`
    multiplied by the quantity 0.6 plus 0.1 times the vote's `confidence`, rounded
    to four decimal places — so a weight-2.00 expert voting at confidence 5
    contributes 2.2000, while the same expert voting at confidence 1 contributes
    1.4000."

    Design: Corner/entities/verification_vote_is_append_only_with_no_version_field
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], world["e1_headers"], "CONFIRM", 5)

    rows, meta = validate_paginated(api.list_votes(
        observation["id"], ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"Expected exactly one vote row, got {meta['total_count']}"

    vote = rows[0]
    assert_verification_vote(vote)
    assert vote["observation_id"] == observation["id"]
    assert vote["expert_id"] == world["e1"]
    assert vote["round_number"] == 0
    assert vote["decision"] == "CONFIRM"
    assert vote["confidence"] == 5
    assert float(vote["weight_applied"]) == pytest.approx(2.2000, abs=1e-9)
    assert "version" not in vote or vote["version"] is None
    assert "updated_at" not in vote or vote["updated_at"] is None


def test_starting_review_on_an_observation_already_under_review_is_refused(api):
    """PRD 2.7: "**Priority 23 — observation review state.** Guards four
    operations: `POST /citizen-science/observations/{id}/start-review` requires
    `SUBMITTED`, `POST /citizen-science/observations/{id}/votes` requires
    `UNDER_REVIEW`, `POST /citizen-science/observations/{id}/resubmit` requires
    `NEEDS_REVISION`, and `POST /citizen-science/observations/{id}/retract` requires
    `ACCEPTED`. Otherwise `ERR_OBSERVATION_STATE_INVALID` (409)."
    PRD 3.6: "Review begins when an expert picks a record out of the queue and
    moves it `SUBMITTED → UNDER_REVIEW`."

    Design: Corner/state_machines/observation_start_review_twice_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    version_after_first = observation["version"]

    response = api.start_review(observation["id"], world["e2_headers"])
    validate_error(response, ApiErrorId.ERR_OBSERVATION_STATE_INVALID.value, 409)

    stored = read_observation(observation["id"])
    assert stored["review_status"] == "UNDER_REVIEW"
    assert stored["version"] == version_after_first, (
        f"A refused transition leaves the row untouched, got version {stored['version']}")


def test_vote_weight_is_rounded_per_vote_before_it_joins_the_tally(api):
    """PRD 3.6: "Each accepted vote is stored as a ledger row bearing its
    `observation_id`, `expert_id`, the `round_number` copied from the observation's
    current `revision_round` at insert time, the `decision`, the `confidence`, the
    `comment`, and a `weight_applied` computed as the expert's `verification_weight`
    multiplied by the quantity 0.6 plus 0.1 times the vote's `confidence`, rounded
    to four decimal places — so a weight-2.00 expert voting at confidence 5
    contributes 2.2000, while the same expert voting at confidence 1 contributes
    1.4000."
    PRD 3.6: "The observation's `consensus_confidence` is 0.0000 when the current
    round holds no `CONFIRM` vote at all; otherwise it is the weighted mean
    confidence of the confirming votes — the sum over confirming votes of the vote's
    `confidence` multiplied by that expert's `verification_weight`, divided by the
    sum of those same experts' `verification_weight` values, rounded to four decimal
    places."
    PRD 3.6: "If the current round holds fewer than two votes, the outcome is a
    hold: the vote is stored but `review_status` stays where it is, a self-loop
    written `UNDER_REVIEW → UNDER_REVIEW`."

    Design: Corner/calculations/vote_weight_applied_rounded_per_vote_before_summation
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    create_site(world["cam1"], site_code="S-HI", priority_weight=1.5)
    sites, _meta = validate_paginated(api.list_sites(world["cam1"], ADMIN,
                                                     {"limit": 10, "offset": 0}))
    world["s_hi"] = sites[0]["id"]
    mid_weight = create_expert(full_name="Cy Verifier", verification_weight=1.50)
    open_campaign(world["cam1"])

    observation = drive_to_under_review(world, count_value=3)
    vote = validate_success(api.cast_vote(observation["id"], {
        "decision": "CONFIRM", "confidence": 3,
        "expected_observation_version": observation["version"],
        "comment": "plumage consistent"}, make_expert_headers(mid_weight["id"])), 201)

    assert float(vote["weight_applied"]) == pytest.approx(1.3500, abs=1e-9), (
        f"1.50 * (0.6 + 0.1 * 3) is 1.3500, got {vote['weight_applied']}")
    assert vote["round_number"] == 0

    stored = read_observation(observation["id"])
    assert float(stored["confirm_weight"]) == pytest.approx(1.3500, abs=1e-9)
    assert float(stored["consensus_confidence"]) == pytest.approx(3.0000, abs=1e-9)
    assert stored["review_status"] == "UNDER_REVIEW"
    assert read_expert(mid_weight["id"])["vote_count"] == 1


def test_quorum_of_two_is_required_even_when_one_vote_carries_enough_weight(api):
    """PRD 3.6: "If the current round holds fewer than two votes, the outcome is a
    hold: the vote is stored but `review_status` stays where it is, a self-loop
    written `UNDER_REVIEW → UNDER_REVIEW`."
    PRD 3.6: "Otherwise, if `confirm_weight` has reached 3.0 and is strictly
    greater than `reject_weight`, the observation resolves `UNDER_REVIEW →
    ACCEPTED`."

    Design: Corner/calculations/consensus_holds_below_quorum_even_when_weight_would_resolve
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    create_site(world["cam1"], site_code="S-HI", priority_weight=1.5)
    sites, _meta = validate_paginated(api.list_sites(world["cam1"], ADMIN,
                                                     {"limit": 10, "offset": 0}))
    world["s_hi"] = sites[0]["id"]
    heavy_one = create_expert(full_name="Hera Heavy", verification_weight=4.00)
    heavy_two = create_expert(full_name="Hugo Heavy", verification_weight=4.00)
    open_campaign(world["cam1"])

    observation = drive_to_under_review(world, count_value=3)
    first_vote = validate_success(api.cast_vote(observation["id"], {
        "decision": "CONFIRM", "confidence": 5,
        "expected_observation_version": observation["version"]},
        make_expert_headers(heavy_one["id"])), 201)

    assert float(first_vote["weight_applied"]) == pytest.approx(4.4000, abs=1e-9)
    midpoint = read_observation(observation["id"])
    assert float(midpoint["confirm_weight"]) == pytest.approx(4.4000, abs=1e-9)
    assert midpoint["review_status"] == "UNDER_REVIEW", (
        "A single vote is below quorum, so the outcome is a hold")

    cast_vote(observation["id"], make_expert_headers(heavy_two["id"]), "CONFIRM", 5)

    resolved = read_observation(observation["id"])
    assert resolved["review_status"] == "ACCEPTED"
    assert float(resolved["confirm_weight"]) == pytest.approx(8.8000, abs=1e-9)
    assert float(resolved["consensus_confidence"]) == pytest.approx(5.0000, abs=1e-9)


def test_an_exact_weight_tie_resolves_to_rejection(api):
    """PRD 3.6: "Otherwise, if `reject_weight` has reached 3.0 and is greater than
    or equal to `confirm_weight`, the observation resolves `UNDER_REVIEW → REJECTED`
    — ties go to rejection, which is the program's conservative default."
    PRD 3.7: "The third link, caused by the second, fires only when the recomputed
    `quality_score` has fallen below 0.50 and the volunteer was `ACTIVE`: the
    volunteer transitions `ACTIVE → PROBATION`."
    PRD 3.7: "The fourth link, caused by the third, suspends the volunteer's
    serious credentials — every certification of theirs whose `status` is
    `CERTIFIED` and whose `level` is `ADVANCED` or `EXPERT` transitions `CERTIFIED →
    SUSPENDED` with `suspended_reason` set to `QUALITY_PROBATION`, while `BASIC`
    credentials survive so the observer can keep contributing simple records."

    Design: Corner/calculations/consensus_reject_wins_on_exact_weight_tie
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK, cert_level="BASIC")
    heavy_one = create_expert(full_name="Hera Heavy", verification_weight=4.00)
    heavy_two = create_expert(full_name="Hugo Heavy", verification_weight=4.00)

    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], make_expert_headers(heavy_one["id"]), "CONFIRM", 2)
    cast_vote(observation["id"], make_expert_headers(heavy_two["id"]), "REJECT", 2)

    stored = read_observation(observation["id"])
    assert float(stored["confirm_weight"]) == pytest.approx(3.2000, abs=1e-9)
    assert float(stored["reject_weight"]) == pytest.approx(3.2000, abs=1e-9)
    assert stored["review_status"] == "REJECTED", (
        f"Ties go to rejection, got {stored['review_status']}")
    assert stored["review_status"] != "ACCEPTED"
    assert float(stored["final_quality_points"]) == pytest.approx(0.0, abs=1e-9)

    volunteer = read_volunteer(world["v1"])
    assert float(volunteer["quality_score"]) == pytest.approx(0.0000, abs=1e-9)
    assert volunteer["status"] == "PROBATION"
    assert read_certification(world["c1"])["status"] == "CERTIFIED", (
        "A BASIC credential survives the probation cascade")


def test_a_second_vote_from_the_same_expert_in_one_round_is_refused(api):
    """PRD 2.7: "**Priority 11 — duplicate vote.** Guards `POST
    /citizen-science/observations/{id}/votes` only. No `VerificationVote` may
    already exist for the same combination of `observation_id`, `expert_id`, and
    `round_number`, otherwise `ERR_DUPLICATE_VOTE` (409)."
    PRD 3.6: "Finally, an expert gets one vote per round: a second vote from the
    same expert on the same observation in the same `round_number` is refused with
    `ERR_DUPLICATE_VOTE`."

    Design: Corner/validations/duplicate_vote_in_same_round_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], world["e1_headers"], "CONFIRM", 5)
    current = read_observation(observation["id"])

    response = api.cast_vote(observation["id"], {
        "decision": "CONFIRM", "confidence": 4,
        "expected_observation_version": current["version"]}, world["e1_headers"])
    validate_error(response, ApiErrorId.ERR_DUPLICATE_VOTE.value, 409)

    stored = read_observation(observation["id"])
    assert float(stored["confirm_weight"]) == pytest.approx(2.2000, abs=1e-9)
    assert stored["review_status"] == "UNDER_REVIEW"
    _rows, meta = validate_paginated(api.list_votes(observation["id"], ADMIN,
                                                    {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1


def test_resubmitting_after_the_second_revision_round_is_refused(api):
    """PRD 2.7: "**Priority 49 — revision budget.** Guards `POST
    /citizen-science/observations/{id}/resubmit`. The observation's
    `revision_round` must be strictly less than 2, otherwise
    `ERR_REVISION_LIMIT_REACHED` (409)."
    PRD 3.6: "The cycle `SUBMITTED → UNDER_REVIEW → NEEDS_REVISION → SUBMITTED` may
    therefore be traversed at most twice."

    Design: Corner/validations/resubmit_after_max_revision_rounds_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_with_photo(world, count_value=3)

    push_revision_round(world, observation["id"], confidence=2)
    resubmit(world, observation["id"], count_value=4)
    push_revision_round(world, observation["id"], confidence=2)
    resubmit(world, observation["id"], count_value=5)
    push_revision_round(world, observation["id"], confidence=2)

    before = read_observation(observation["id"])
    assert before["review_status"] == "NEEDS_REVISION"
    assert before["revision_round"] == 2

    response = api.resubmit_observation(observation["id"], {"count_value": 9},
                                        world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value, 409)

    stored = read_observation(observation["id"])
    assert stored["revision_round"] == 2
    assert stored["count_value"] == 5, "The refused correction must not be applied"
    _rows, meta = validate_paginated(api.list_votes(observation["id"], ADMIN,
                                                    {"limit": 20, "offset": 0}))
    assert meta["total_count"] == 6


def test_an_expert_linked_to_the_observer_cannot_start_the_review(api):
    """PRD 2.7: "**Priority 9 — self-verification bar.** Guards `POST
    /citizen-science/observations/{id}/start-review` and `POST
    /citizen-science/observations/{id}/votes`. The acting `Expert`'s
    `linked_volunteer_id` must not equal the observation's `volunteer_id`, otherwise
    `ERR_SELF_VERIFICATION` (403)."
    PRD 3.6: "must not be the observer in disguise: if the expert's
    `linked_volunteer_id` equals the observation's `volunteer_id`, the attempt is
    refused with `ERR_SELF_VERIFICATION`."

    Design: Corner/errors/expert_cannot_verify_own_linked_volunteer_submission
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK, cert_level="BASIC")
    self_expert = create_expert(full_name="Self Sam", verification_weight=2.00,
                                linked_volunteer_id=world["v1"])
    observation = submit_with_photo(world, count_value=3)

    response = api.start_review(observation["id"],
                                make_expert_headers(self_expert["id"]))
    validate_error(response, ApiErrorId.ERR_SELF_VERIFICATION.value, 403)

    assert read_observation(observation["id"])["review_status"] == "SUBMITTED"
    assert read_expert(self_expert["id"])["linked_volunteer_id"] == world["v1"]


def test_the_trainer_may_not_cast_the_opening_round_vote_on_their_trainee(api):
    """PRD 2.7: "**Priority 10 — trainer-conflict bar.** Guards `POST
    /citizen-science/observations/{id}/votes` only. When the observation's
    `revision_round` is 0, the acting `Expert` must not be the `trainer_expert_id`
    on the observer's certification for the campaign's protocol, otherwise
    `ERR_TRAINER_VERIFICATION_CONFLICT` (403)."
    PRD 3.6: "And while the observation is still in its opening round — that is,
    while `revision_round` is 0 — the acting expert must not be the
    `trainer_expert_id` on the observer's certification for this campaign's
    protocol, since someone who trained an observer cannot impartially validate that
    observer's first attempt; a breach is refused with
    `ERR_TRAINER_VERIFICATION_CONFLICT`."

    Design: Corner/errors/trainer_cannot_cast_round_zero_vote_on_own_trainee
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)

    response = api.cast_vote(observation["id"], {
        "decision": "CONFIRM", "confidence": 5,
        "expected_observation_version": observation["version"]},
        world["trainer_headers"])
    validate_error(response, ApiErrorId.ERR_TRAINER_VERIFICATION_CONFLICT.value, 403)

    assert float(read_observation(observation["id"])["confirm_weight"]) == \
        pytest.approx(0.0, abs=1e-9)
    assert read_expert(world["et"])["vote_count"] == 0


def test_expert_vote_subresource_returns_only_that_experts_votes(api):
    """PRD 2.8: "Nested collections behave predictably: a request for the sites of
    a campaign, the photo evidence of an observation, the votes on an observation,
    or the votes cast by an expert returns only the children of the named parent,
    paginated and ordered by `created_at` ascending like any other list."
    PRD 3.6: "Storing the vote also raises the acting expert's `vote_count` by one
    and the observation's `version` by one, whatever the outcome turns out to be."

    Design: Corner/endpoints/expert_votes_subresource_lists_all_votes_by_expert
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], world["e1_headers"], "CONFIRM", 5)

    rows, meta = validate_paginated(api.list_expert_votes(
        world["e1"], world["e1_headers"], {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"Expected one vote, got {meta['total_count']}"
    assert rows[0]["observation_id"] == observation["id"]
    assert rows[0]["decision"] == "CONFIRM"
    assert float(rows[0]["weight_applied"]) == pytest.approx(2.2000, abs=1e-9)

    _other_rows, other_meta = validate_paginated(api.list_expert_votes(
        world["e2"], ADMIN, {"limit": 10, "offset": 0}))
    assert other_meta["total_count"] == 0

    assert read_expert(world["e1"])["vote_count"] == 1
    assert read_expert(world["e2"])["vote_count"] == 0


def test_voting_against_a_stale_observation_version_is_rejected(api):
    """PRD 2.5: "Casting a verification vote — `POST
    /citizen-science/observations/{id}/votes` — requires
    `expected_observation_version` carrying the client's last observed `version` of
    the target `Observation`. If it does not equal the observation's current
    `version`, the vote is rejected with `ERR_STALE_OBSERVATION_VERSION` (HTTP
    412)."
    PRD 3.6: "Storing the vote also raises the acting expert's `vote_count` by one
    and the observation's `version` by one, whatever the outcome turns out to be."

    Design: Corner/cross_cutting_layers/occ_stale_observation_version_on_vote_returns_412
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    stale_version = observation["version"]
    cast_vote(observation["id"], world["e1_headers"], "CONFIRM", 5)

    response = api.cast_vote(observation["id"], {
        "decision": "CONFIRM", "confidence": 5,
        "expected_observation_version": stale_version}, world["e2_headers"])
    validate_error(response, ApiErrorId.ERR_STALE_OBSERVATION_VERSION.value, 412)

    midpoint = read_observation(observation["id"])
    assert float(midpoint["confirm_weight"]) == pytest.approx(2.2000, abs=1e-9)
    assert midpoint["review_status"] == "UNDER_REVIEW"
    assert midpoint["version"] > stale_version

    validate_success(api.cast_vote(observation["id"], {
        "decision": "CONFIRM", "confidence": 5,
        "expected_observation_version": midpoint["version"]}, world["e2_headers"]), 201)

    resolved = read_observation(observation["id"])
    assert resolved["review_status"] == "ACCEPTED"
    assert float(resolved["confirm_weight"]) == pytest.approx(4.4000, abs=1e-9)
