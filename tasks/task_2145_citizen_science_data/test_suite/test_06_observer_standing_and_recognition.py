"""Observer standing, the two quality scores, recognition points and retraction."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_points_ledger_conserved,
    assert_recognition_award,
    build_world,
    cast_vote,
    close_campaign,
    create_accepted_observation,
    create_site,
    drive_to_under_review,
    list_awards,
    open_campaign,
    read_campaign,
    read_certification,
    read_expert,
    read_loan,
    read_observation,
    read_site,
    read_volunteer,
    register_equipment,
    request_loan,
    retract,
    set_clock,
    submit_with_photo,
    start_review,
    STAGE_CAMPAIGN,
    STAGE_OPEN,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def _two_site_world():
    world = build_world(stage=STAGE_CAMPAIGN, clock="2026-08-03T00:00:00Z")
    site_hi = create_site(world["cam1"], site_code="S-HI", latitude=44.0,
                          longitude=-70.0, habitat_type="WETLAND", priority_weight=1.5)
    site_lo = create_site(world["cam1"], site_code="S-LO", latitude=44.5,
                          longitude=-70.5, habitat_type="FOREST", priority_weight=0.8)
    open_campaign(world["cam1"])
    world["s_hi"] = site_hi["id"]
    world["s_lo"] = site_lo["id"]
    return world


def _one_old_hit_and_one_fresh_miss(world):
    """An 89-day-old acceptance and a one-day-old rejection for the same observer."""
    create_accepted_observation(world, site_id=world["s_hi"],
                                observed_at="2026-08-02T00:00:00Z", count_value=2,
                                photo_overrides={"captured_at": "2026-08-02T00:30:00Z"})
    set_clock("2026-10-30T00:00:00Z")
    fresh = drive_to_under_review(
        world, site_id=world["s_lo"], observed_at="2026-10-29T00:00:00Z",
        latitude=44.5, longitude=-70.5, species_code="CORA", count_value=1,
        photo_overrides={"captured_at": "2026-10-29T00:30:00Z",
                         "exif_latitude": 44.5, "exif_longitude": -70.5})
    cast_vote(fresh["id"], world["e1_headers"], "REJECT", 5)
    cast_vote(fresh["id"], world["e2_headers"], "REJECT", 5)
    return fresh


def test_rolling_window_and_lifetime_quality_scores_diverge(api):
    """PRD 3.7: "`quality_score` is the rolling-window variant. Take the 20 most
    recent members of the adjudicated set, ordered by `observed_at` descending with
    `created_at` descending as the tie-break, and divide the number of hits among
    them by how many members the window actually holds, rounding to four decimal
    places."
    PRD 3.7: "Every member of the adjudicated set contributes, discounted
    exponentially by age: a record's weight is one half raised to the power of its
    age in exact fractional days — measured from `observed_at` to the logical clock
    — divided by a half-life of 180 days, so a six-month-old record counts half as
    much as a fresh one and a year-old record a quarter as much."
    PRD 3.7: "The score is the sum of each record's weight times its hit value,
    divided by the sum of all the weights, rounded to four decimal places, with the
    same neutral seed of 0.5 when the set is empty."

    Design: Difficulty/dual_variant_calc/volunteer_rolling_vs_lifetime_quality_score_diverge
    """
    world = _two_site_world()
    rejected = _one_old_hit_and_one_fresh_miss(world)

    assert read_observation(rejected["id"])["review_status"] == "REJECTED"

    volunteer = read_volunteer(world["v1"])
    assert float(volunteer["quality_score"]) == pytest.approx(0.5000, abs=1e-9), (
        f"One hit out of two window members is 0.5000, got {volunteer['quality_score']}")
    assert float(volunteer["lifetime_quality_score"]) == pytest.approx(0.4161, abs=1e-9), (
        f"The age-decayed variant reports 0.4161, got "
        f"{volunteer['lifetime_quality_score']}")
    assert float(volunteer["quality_score"]) != float(volunteer["lifetime_quality_score"])


def test_adjudication_counters_track_the_adjudicated_set(api):
    """PRD 3.7: "Both are computed over the same **adjudicated set** — every
    observation belonging to that volunteer whose `review_status` is `ACCEPTED`,
    `REJECTED`, or `RETRACTED`."
    PRD 3.7: "The third link, caused by the second, fires only when the recomputed
    `quality_score` has fallen below 0.50 and the volunteer was `ACTIVE`: the
    volunteer transitions `ACTIVE → PROBATION`."

    Design: Difficulty/dual_variant_calc/volunteer_rolling_vs_lifetime_quality_score_diverge
    """
    world = _two_site_world()
    _one_old_hit_and_one_fresh_miss(world)

    volunteer = read_volunteer(world["v1"])
    assert volunteer["accepted_observation_count"] == 1
    assert volunteer["rejected_observation_count"] == 1
    assert volunteer["status"] == "ACTIVE", (
        "quality_score 0.5000 has not fallen below 0.50, so the observer stays ACTIVE")


def test_rejection_drives_the_observer_onto_probation(api):
    """PRD 3.7: "**Rejection** runs a five-link chain of its own. The first link
    sets `review_status` to `REJECTED` and leaves `publication_status` at
    `UNPUBLISHED` — a rejected record never enters the publication pipeline."
    PRD 3.7: "The second link, caused by the first, raises the volunteer's
    `rejected_observation_count` and `consecutive_rejections` by one each, resets
    `consecutive_accepted` to 0, and recomputes both quality scores."
    PRD 3.7: "The third link, caused by the second, fires only when the recomputed
    `quality_score` has fallen below 0.50 and the volunteer was `ACTIVE`: the
    volunteer transitions `ACTIVE → PROBATION`."

    Design: Difficulty/transitive_cascade/reject_cascade_probation_suspends_certification_and_cancels_loan
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], world["e1_headers"], "REJECT", 5)
    cast_vote(observation["id"], world["e2_headers"], "REJECT", 5)

    stored = read_observation(observation["id"])
    assert stored["review_status"] == "REJECTED"
    assert float(stored["reject_weight"]) == pytest.approx(4.4000, abs=1e-9)
    assert stored["publication_status"] == "UNPUBLISHED"

    volunteer = read_volunteer(world["v1"])
    assert float(volunteer["quality_score"]) == pytest.approx(0.0000, abs=1e-9)
    assert volunteer["rejected_observation_count"] == 1
    assert volunteer["consecutive_rejections"] == 1
    assert volunteer["consecutive_accepted"] == 0
    assert volunteer["status"] == "PROBATION"


def test_probation_suspends_the_advanced_credential_and_cancels_the_booked_loan(api):
    """PRD 3.7: "The fourth link, caused by the third, suspends the volunteer's
    serious credentials — every certification of theirs whose `status` is
    `CERTIFIED` and whose `level` is `ADVANCED` or `EXPERT` transitions `CERTIFIED →
    SUSPENDED` with `suspended_reason` set to `QUALITY_PROBATION`, while `BASIC`
    credentials survive so the observer can keep contributing simple records."
    PRD 3.7: "The fifth link, caused by the fourth, cancels forward commitments:
    every equipment loan of that volunteer still sitting in `REQUESTED` transitions
    `REQUESTED → CANCELLED`."

    Design: Difficulty/transitive_cascade/reject_cascade_probation_suspends_certification_and_cancels_loan
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    equipment = register_equipment(asset_tag="EQ-002", equipment_type="ACOUSTIC_RECORDER")
    loan = request_loan(equipment["id"], world["v1"], start_at="2026-09-01T00:00:00Z",
                        due_at="2026-09-10T00:00:00Z")
    assert loan["status"] == "REQUESTED"

    observation = drive_to_under_review(world, count_value=3)
    cast_vote(observation["id"], world["e1_headers"], "REJECT", 5)
    cast_vote(observation["id"], world["e2_headers"], "REJECT", 5)

    certification = read_certification(world["c1"])
    assert certification["status"] == "SUSPENDED"
    assert certification["suspended_reason"] == "QUALITY_PROBATION"

    cancelled = read_loan(loan["id"])
    assert cancelled["status"] == "CANCELLED"
    assert validate_success(api.get_equipment(equipment["id"], ADMIN))["status"] == "AVAILABLE"


def _accepted_single_site_world():
    """One site with target 1, one ACCEPTED observation worth 52.80 points."""
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK,
                        campaign_overrides={"target_observations_per_site": 1})
    site = create_site(world["cam1"], site_code="S-ONE", latitude=44.0, longitude=-70.0,
                       habitat_type="WETLAND", priority_weight=1.2)
    world["s_hi"] = site["id"]
    world["s_one"] = site["id"]
    open_campaign(world["cam1"])
    observation = create_accepted_observation(world, count_value=3)
    return world, observation


def test_retracting_an_accepted_record_unwinds_the_coverage_arithmetic(api):
    """PRD 3.7: "The first link moves `review_status` `ACCEPTED → RETRACTED`."
    PRD 3.7: "The third link, caused by the second, unwinds the coverage
    arithmetic: the site's `accepted_observation_count` drops by one and its
    `coverage_ratio` and `coverage_status` are recomputed, and the campaign's
    `accepted_observation_count` drops by one and its `coverage_score` and
    `gap_count` are recomputed."

    Design: Difficulty/transitive_cascade/retract_cascade_reopens_closed_campaign
    """
    world, observation = _accepted_single_site_world()
    close_campaign(world["cam1"])

    retracted = retract(observation["id"], "species misidentified on re-examination")

    assert retracted["review_status"] == "RETRACTED"
    assert retracted["publication_status"] == "WITHDRAWN"

    site = read_site(world["cam1"], world["s_one"])
    assert site["accepted_observation_count"] == 0
    assert float(site["coverage_ratio"]) == pytest.approx(0.00, abs=1e-9)
    assert site["coverage_status"] == "GAP"

    campaign = read_campaign(world["cam1"])
    assert campaign["accepted_observation_count"] == 0
    assert float(campaign["coverage_score"]) == pytest.approx(0.0000, abs=1e-9)
    assert campaign["gap_count"] == 1


def test_retraction_reopens_a_closed_campaign_whose_gap_count_rose(api):
    """PRD 3.7: "The fourth link, caused by the third, can re-open a finished
    campaign: when the recompute has raised the campaign's `gap_count` above the
    value it held before the retraction and the campaign is sitting in `CLOSED`, the
    campaign transitions `CLOSED → OPEN` so the sampling gap can be filled."
    PRD 3.7: "The volunteer's `accepted_observation_count` drops by one,
    `rejected_observation_count` rises by one, `consecutive_accepted` resets to 0,
    and both quality scores are recomputed with the retracted record scoring as a
    miss."

    Design: Difficulty/transitive_cascade/retract_cascade_reopens_closed_campaign
    """
    world, observation = _accepted_single_site_world()
    close_campaign(world["cam1"])
    before = read_campaign(world["cam1"])
    assert before["status"] == "CLOSED"
    assert before["gap_count"] == 0

    retract(observation["id"], "species misidentified on re-examination")

    campaign = read_campaign(world["cam1"])
    assert campaign["status"] == "OPEN", (
        f"A risen gap_count re-opens the CLOSED campaign, got {campaign['status']}")

    volunteer = read_volunteer(world["v1"])
    assert volunteer["accepted_observation_count"] == 0
    assert volunteer["lifetime_points"] == 25, (
        f"Only the 25-point milestone survives the reversal, got "
        f"{volunteer['lifetime_points']}")


def test_quality_score_exactly_at_the_probation_floor_keeps_the_observer_active(api):
    """PRD 3.7: "The third link, caused by the second, fires only when the
    recomputed `quality_score` has fallen below 0.50 and the volunteer was `ACTIVE`:
    the volunteer transitions `ACTIVE → PROBATION`."
    PRD 3.7: "`quality_score` is the rolling-window variant. Take the 20 most
    recent members of the adjudicated set, ordered by `observed_at` descending with
    `created_at` descending as the tie-break, and divide the number of hits among
    them by how many members the window actually holds, rounding to four decimal
    places."

    Design: Difficulty/boundary_precision_check/quality_score_exactly_at_probation_floor_keeps_volunteer_active
    """
    world = _two_site_world()
    rejected = _one_old_hit_and_one_fresh_miss(world)

    assert read_observation(rejected["id"])["review_status"] == "REJECTED"
    volunteer = read_volunteer(world["v1"])
    assert float(volunteer["quality_score"]) == pytest.approx(0.5000, abs=1e-9)
    assert volunteer["status"] == "ACTIVE", (
        f"0.5000 is not below the 0.50 floor, got {volunteer['status']}")


def test_credentials_survive_when_the_probation_floor_is_only_touched(api):
    """PRD 3.7: "The fourth link, caused by the third, suspends the volunteer's
    serious credentials — every certification of theirs whose `status` is
    `CERTIFIED` and whose `level` is `ADVANCED` or `EXPERT` transitions `CERTIFIED →
    SUSPENDED` with `suspended_reason` set to `QUALITY_PROBATION`, while `BASIC`
    credentials survive so the observer can keep contributing simple records."
    PRD 3.7: "The third link, caused by the second, fires only when the recomputed
    `quality_score` has fallen below 0.50 and the volunteer was `ACTIVE`: the
    volunteer transitions `ACTIVE → PROBATION`."

    Design: Difficulty/boundary_precision_check/quality_score_exactly_at_probation_floor_keeps_volunteer_active
    """
    world = _two_site_world()
    _one_old_hit_and_one_fresh_miss(world)

    certification = read_certification(world["c1"])
    assert certification["status"] == "CERTIFIED", (
        f"No probation means no credential suspension, got {certification['status']}")
    assert certification["suspended_reason"] == "NONE"


def test_retraction_appends_an_exact_reversal_row_to_the_recognition_ledger(api):
    """PRD 3.7: "The ledger compensation is exact and additive. A row of
    `award_type` `REVERSAL` is appended whose `points_awarded` is the negation of
    the sum of `points_awarded` across every prior ledger row bearing this
    observation's `observation_id`, and that same sum is subtracted from the
    volunteer's `lifetime_points` — which is how the invariant of §2.10 survives a
    retraction."
    PRD 3.7: "Because milestone rows carry a null `observation_id`, a tier
    promotion is never clawed back."
    PRD 2.10: "The recognition ledger carries the strictest of these invariants:
    for every volunteer, the sum of `points_awarded` across every `RecognitionAward`
    row bearing that volunteer's `volunteer_id` equals that volunteer's
    `lifetime_points` at all times."

    Design: Difficulty/compensating_invariant/recognition_points_ledger_conserved_after_retraction
    """
    world, observation = _accepted_single_site_world()

    before_rows = list_awards(volunteer_id=world["v1"])
    before_volunteer = read_volunteer(world["v1"])
    assert before_volunteer["lifetime_points"] == 77
    assert len(before_rows) == 2, f"Expected two ledger rows before retraction, got {before_rows}"
    assert_points_ledger_conserved(before_volunteer, before_rows)
    assert float(read_observation(observation["id"])["final_quality_points"]) == \
        pytest.approx(52.80, abs=1e-9)

    retract(observation["id"], "duplicate submission found in the archive")

    after_rows = list_awards(volunteer_id=world["v1"])
    assert len(after_rows) == 3, f"Expected three ledger rows after retraction, got {after_rows}"
    by_type = {row["award_type"]: row for row in after_rows}
    assert by_type["OBSERVATION_ACCEPTED"]["points_awarded"] == 52
    assert by_type["OBSERVATION_ACCEPTED"]["observation_id"] == observation["id"]
    assert by_type["MILESTONE"]["points_awarded"] == 25
    assert by_type["MILESTONE"]["observation_id"] is None
    assert by_type["REVERSAL"]["points_awarded"] == -52
    assert by_type["REVERSAL"]["observation_id"] == observation["id"]


def test_lifetime_points_stay_equal_to_the_ledger_sum_after_retraction(api):
    """PRD 2.10: "The recognition ledger carries the strictest of these invariants:
    for every volunteer, the sum of `points_awarded` across every `RecognitionAward`
    row bearing that volunteer's `volunteer_id` equals that volunteer's
    `lifetime_points` at all times."
    PRD 2.10: "There is no separate adjustment path — points are only ever changed
    by appending a ledger row, and a reversal is itself a ledger row with a negative
    value rather than a deletion or an edit of history."

    Design: Difficulty/compensating_invariant/recognition_points_ledger_conserved_after_retraction
    """
    world, observation = _accepted_single_site_world()
    retract(observation["id"], "duplicate submission found in the archive")

    rows = list_awards(volunteer_id=world["v1"])
    volunteer = read_volunteer(world["v1"])
    for row in rows:
        assert_recognition_award(row)
    assert sum(row["points_awarded"] for row in rows) == 25
    assert volunteer["lifetime_points"] == 25
    assert volunteer["status"] == "ACTIVE", (
        "A retraction never drives a volunteer into PROBATION")
    assert_points_ledger_conserved(volunteer, rows)


def test_award_ledger_is_filterable_by_observation_and_award_type(api):
    """PRD 3.7: "The points on that row are computed by reading the volunteer's
    recognition band from their `lifetime_quality_score` **as it stands before this
    acceptance is folded in** — a multiplier of 1.50 at 0.90 or above, 1.25 at 0.75
    or above, 1.10 at 0.60 or above, and 1.00 otherwise — multiplying
    `final_quality_points` by that multiplier, and taking the floor of the result to
    a whole number of points."
    PRD 3.7: "If the tier has climbed — ranking `BRONZE` as 1, `SILVER` as 2, `GOLD`
    as 3, and `PLATINUM` as 4 — a third ledger row of `award_type` `MILESTONE` worth
    a flat 25 points is appended and added to `lifetime_points`. A milestone row is
    not tied to any single observation, so its `observation_id` is null."
    PRD 2.3: "The recognition-award ledger may be filtered by `volunteer_id`,
    `observation_id`, and `award_type`."

    Design: Corner/endpoints/awards_list_filtered_by_observation_id
    """
    world, observation = _accepted_single_site_world()

    rows, meta = validate_paginated(api.list_awards(
        ADMIN, {"observation_id": observation["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, f"Expected one row for the observation, got {meta['total_count']}"
    assert rows[0]["award_type"] == "OBSERVATION_ACCEPTED"
    assert rows[0]["points_awarded"] == 52, (
        f"floor(52.80 * 1.00) is 52, got {rows[0]['points_awarded']}")

    milestone_rows, milestone_meta = validate_paginated(api.list_awards(
        world["vol_headers"], {"volunteer_id": world["v1"], "award_type": "MILESTONE",
                               "limit": 10, "offset": 0}))
    assert milestone_meta["total_count"] == 1
    assert milestone_rows[0]["points_awarded"] == 25
    assert milestone_rows[0]["observation_id"] is None
    assert read_volunteer(world["v1"])["lifetime_points"] == 77


def test_reading_an_unknown_award_row_is_a_not_found(api):
    """PRD 2.7: "**Priority 4 — path resource existence (every operation with a
    templated path segment).** Each templated segment is resolved strictly left to
    right, and the first one that names no row terminates the request with that
    entity's not-found error at HTTP 404: `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND`."

    Design: Corner/errors/award_get_unknown_id_not_found
    """
    response = api.get_award("00000000-0000-4000-8000-0000000000bb", ADMIN)
    validate_error(response, ApiErrorId.ERR_AWARD_NOT_FOUND.value, 404)


def test_two_retracted_confirmations_suspend_the_expert(api):
    """PRD 3.7: "Retraction finally reaches back to the experts who got it wrong.
    For every expert who cast a `CONFIRM` vote in the deciding round of the retracted
    observation, `retracted_confirm_count` rises by one, and any expert whose count
    reaches 2 transitions `ACTIVE → SUSPENDED` and can cast no further votes until
    an administrator intervenes."
    PRD 2.7: "**Priority 34 — expert standing.** Guards `POST
    /citizen-science/observations/{id}/start-review` and `POST
    /citizen-science/observations/{id}/votes`. The acting expert's `status` must be
    `ACTIVE`, otherwise `ERR_EXPERT_SUSPENDED` (403)."

    Design: Corner/errors/expert_suspended_after_two_retracted_confirmations
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    site = create_site(world["cam1"], site_code="S-WIDE", latitude=44.0, longitude=-70.0,
                       habitat_type="WETLAND", priority_weight=1.5)
    world["s_hi"] = site["id"]
    open_campaign(world["cam1"])

    first = create_accepted_observation(world, count_value=1)
    second = create_accepted_observation(world, count_value=2)

    retract(first["id"], "first audit failure")
    assert read_expert(world["e1"])["retracted_confirm_count"] == 1
    assert read_expert(world["e1"])["status"] == "ACTIVE"

    third = submit_with_photo(world, count_value=3)
    third = start_review(third["id"], world["e2_headers"])

    retract(second["id"], "second audit failure")
    suspended = read_expert(world["e1"])
    assert suspended["retracted_confirm_count"] == 2
    assert suspended["status"] == "SUSPENDED"
    assert read_expert(world["e2"])["status"] == "SUSPENDED"

    response = api.cast_vote(third["id"], {
        "decision": "CONFIRM", "confidence": 5,
        "expected_observation_version": third["version"]}, world["e1_headers"])
    validate_error(response, ApiErrorId.ERR_EXPERT_SUSPENDED.value, 403)
    assert float(read_observation(third["id"])["confirm_weight"]) == pytest.approx(0.0, abs=1e-9)


def test_an_expert_may_not_retract_an_observation(api):
    """PRD 2.7: "**Priority 3 — role authorisation (all operations).** The acting
    role must appear in the operation's permitted-role list in §4, otherwise
    `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD 3.7: "**Retraction** is the compensating operation, available to a
    `ProgramAdmin` against any observation in `ACCEPTED` and carrying a free-text
    `reason`."

    Design: Corner/rbac/expert_cannot_retract_observation
    """
    world, observation = _accepted_single_site_world()

    response = api.retract_observation(
        observation["id"], {"reason": "expert attempts an admin action"},
        world["e1_headers"])
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    stored = read_observation(observation["id"])
    assert stored["review_status"] == "ACCEPTED"
    assert stored["publication_status"] == "QUEUED"
    assert read_volunteer(world["v1"])["lifetime_points"] == 77


def test_the_retraction_cascade_is_visible_to_the_next_read(api):
    """PRD 2.8: "Those secondary changes are not incidental bookkeeping — they are
    part of the operation's contract, they are applied within the same request, and
    they are immediately visible to the next read."
    PRD 3.7: "The third link, caused by the second, unwinds the coverage
    arithmetic: the site's `accepted_observation_count` drops by one and its
    `coverage_ratio` and `coverage_status` are recomputed, and the campaign's
    `accepted_observation_count` drops by one and its `coverage_score` and
    `gap_count` are recomputed."
    PRD 3.7: "A row of `award_type` `REVERSAL` is appended whose `points_awarded`
    is the negation of the sum of `points_awarded` across every prior ledger row
    bearing this observation's `observation_id`, and that same sum is subtracted from
    the volunteer's `lifetime_points` — which is how the invariant of §2.10 survives
    a retraction."

    Design: Corner/consistency_model/retraction_cascade_is_visible_to_immediate_follow_up_reads
    """
    world, observation = _accepted_single_site_world()

    retracted = retract(observation["id"], "immediate consistency probe")
    assert retracted["review_status"] == "RETRACTED"
    assert retracted["publication_status"] == "WITHDRAWN"

    campaign = read_campaign(world["cam1"])
    assert float(campaign["coverage_score"]) == pytest.approx(0.0000, abs=1e-9)
    assert campaign["gap_count"] == 1

    rows, meta = validate_paginated(api.list_awards(
        ADMIN, {"volunteer_id": world["v1"], "award_type": "REVERSAL",
                "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert rows[0]["points_awarded"] == -52

    sites, _site_meta = validate_paginated(api.list_sites(
        world["cam1"], ADMIN, {"limit": 10, "offset": 0}))
    target = next(row for row in sites if row["id"] == world["s_one"])
    assert target["accepted_observation_count"] == 0
    assert target["coverage_status"] == "GAP"
    assert read_volunteer(world["v1"])["lifetime_points"] == 25
