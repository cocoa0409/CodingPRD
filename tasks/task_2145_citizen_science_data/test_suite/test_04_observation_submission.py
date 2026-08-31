"""Filing a field observation and screening its photo evidence."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_observation,
    assert_photo_evidence,
    attach_photo,
    build_world,
    close_campaign,
    create_accepted_observation,
    create_campaign,
    create_site,
    open_campaign,
    read_campaign,
    read_certification,
    read_observation,
    read_site,
    run_maintenance,
    set_clock,
    start_review,
    submit_observation,
    submit_with_photo,
    STAGE_CAMPAIGN,
    STAGE_OPEN,
    STAGE_SITE,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"
OBS_PAYLOAD_BASE = {
    "observed_at": "2026-08-05T06:00:00Z", "latitude": 44.0, "longitude": -70.0,
    "species_code": "BAEA", "count_value": 3,
}


def _observation_payload(world, site_id=None, **overrides):
    payload = dict(OBS_PAYLOAD_BASE)
    payload.update({"campaign_id": world["cam1"],
                    "site_id": site_id or world["s_hi"],
                    "volunteer_id": world["v1"]})
    payload.update(overrides)
    return payload


def test_observation_submission_is_refused_while_the_campaign_is_planned(api):
    """PRD 2.7: "**Priority 22 — campaign state.** Guards five operations: `POST
    /citizen-science/observations` and `POST /citizen-science/observations/{id}/resubmit`
    both require the campaign's `status` to be `OPEN`; `POST
    /citizen-science/campaigns/{id}/open` requires `PLANNED` or `CLOSED`; `POST
    /citizen-science/campaigns/{id}/close` requires `OPEN`; and `POST
    /citizen-science/campaigns/{id}/sites` requires a campaign that is neither
    `PUBLISHED` nor `ARCHIVED`. Otherwise `ERR_CAMPAIGN_NOT_OPEN` (409)."
    PRD 3.5: "The campaign must be `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/observation_submission_requires_campaign_open
    """
    world = build_world(stage=STAGE_SITE, clock=CLOCK)
    assert read_campaign(world["cam1"])["status"] == "PLANNED"

    response = api.create_observation(_observation_payload(world), world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value, 409)

    _rows, meta = validate_paginated(api.list_observations(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, "No observation row may be created"


def test_the_same_submission_succeeds_once_the_campaign_is_opened(api):
    """PRD 3.5: "A surviving submission is created with `review_status`
    `SUBMITTED` and `publication_status` `UNPUBLISHED` — the two independent state
    dimensions this record carries for the rest of its life — plus `revision_round`
    at 0, `photo_count` at 0, `publication_id` null, `final_quality_points` at 0.0,
    and `consensus_confidence`, `confirm_weight`, `reject_weight`, and
    `revision_weight` all at 0.0. Its `submitted_at` is stamped from the logical
    clock, and its `provisional_quality_points` is computed immediately."
    PRD 3.3: "Opening a campaign moves it `PLANNED → OPEN` or `CLOSED → OPEN`. It
    requires the campaign's protocol to be `ACTIVE` and the campaign to hold at
    least one site, and it re-runs the coverage arithmetic before returning."

    Design: Difficulty/cross_entity_state_dependency/observation_submission_requires_campaign_open
    """
    world = build_world(stage=STAGE_SITE, clock=CLOCK)
    validate_error(api.create_observation(_observation_payload(world), world["vol_headers"]),
                   ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value, 409)

    open_campaign(world["cam1"])

    created = validate_success(api.create_observation(
        _observation_payload(world), world["vol_headers"]), 201)

    assert_observation(created)
    assert created["review_status"] == "SUBMITTED"
    assert created["publication_status"] == "UNPUBLISHED"
    assert created["submitted_at"] == "2026-08-05T09:00:00.000Z", (
        f"submitted_at is stamped from the logical clock, got {created['submitted_at']}")
    assert created["revision_round"] == 0
    assert created["photo_count"] == 0
    assert created["publication_id"] is None


def test_campaign_state_check_beats_the_submission_lag_check(api):
    """PRD 2.7: "Most operations in this system are guarded by several checks at
    once, and the order in which those checks run is observable: a request that
    violates two rules must fail with the error belonging to the earlier rule."
    PRD 2.7: "**Priority 22 — campaign state.** Guards five operations: `POST
    /citizen-science/observations` and `POST /citizen-science/observations/{id}/resubmit`
    both require the campaign's `status` to be `OPEN`; `POST
    /citizen-science/campaigns/{id}/open` requires `PLANNED` or `CLOSED`; `POST
    /citizen-science/campaigns/{id}/close` requires `OPEN`; and `POST
    /citizen-science/campaigns/{id}/sites` requires a campaign that is neither
    `PUBLISHED` nor `ARCHIVED`. Otherwise `ERR_CAMPAIGN_NOT_OPEN` (409)."
    PRD 2.7: "**Priority 41 — submission lag.** Guards `POST
    /citizen-science/observations`. The elapsed hours from `observed_at` to the
    logical clock must be at most the protocol's `max_submission_lag_hours`,
    otherwise `ERR_SUBMISSION_LAG_EXCEEDED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/campaign_state_check_beats_submission_lag_check
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    close_campaign(world["cam1"])
    set_clock("2026-08-20T00:00:00Z")

    response = api.create_observation(
        _observation_payload(world, observed_at="2026-08-01T00:00:00Z", count_value=1),
        world["vol_headers"])

    error = validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_SUBMISSION_LAG_EXCEEDED.value, (
        "The campaign-state check at priority 22 pre-empts the lag check at priority 41")


def test_no_observation_row_survives_the_campaign_state_rejection(api):
    """PRD 2.7: "A check whose scope does not include the current operation is
    skipped, and evaluation stops at the first check that fails."
    PRD 2.7: "**Priority 22 — campaign state.** Guards five operations: `POST
    /citizen-science/observations` and `POST /citizen-science/observations/{id}/resubmit`
    both require the campaign's `status` to be `OPEN`; `POST
    /citizen-science/campaigns/{id}/open` requires `PLANNED` or `CLOSED`; `POST
    /citizen-science/campaigns/{id}/close` requires `OPEN`; and `POST
    /citizen-science/campaigns/{id}/sites` requires a campaign that is neither
    `PUBLISHED` nor `ARCHIVED`. Otherwise `ERR_CAMPAIGN_NOT_OPEN` (409)."

    Design: Difficulty/priority_pair_validation_conflict/campaign_state_check_beats_submission_lag_check
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    close_campaign(world["cam1"])
    set_clock("2026-08-20T00:00:00Z")

    validate_error(api.create_observation(
        _observation_payload(world, observed_at="2026-08-01T00:00:00Z", count_value=1),
        world["vol_headers"]), ApiErrorId.ERR_CAMPAIGN_NOT_OPEN.value, 409)

    _rows, meta = validate_paginated(api.list_observations(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0, (
        f"A rejected submission leaves no Observation row, got {meta['total_count']}")


def _saturated_site_with_expired_certification(api):
    """Site holding two accepted records under a certification that has expired."""
    world = build_world(
        stage=STAGE_CAMPAIGN, clock=CLOCK,
        protocol_overrides={"code": "SHORT-CERT", "title": "Short Certification Protocol",
                            "certification_valid_days": 10},
        campaign_overrides={"target_observations_per_site": 1})
    site = create_site(world["cam1"], site_code="S-ONE", latitude=44.0, longitude=-70.0,
                       habitat_type="WETLAND", priority_weight=1.2)
    world["s_hi"] = site["id"]
    world["s_one"] = site["id"]
    open_campaign(world["cam1"])

    create_accepted_observation(world, count_value=1)
    create_accepted_observation(world, count_value=2)

    set_clock("2026-08-16T00:00:00Z")
    sweep = run_maintenance()
    assert sweep["expired_certification_count"] == 1, (
        f"Setup failed: expected one expired certification, got {sweep}")
    return world


def test_certification_validity_check_beats_the_site_saturation_check(api):
    """PRD 2.7: "**Priority 31 — valid certification.** Guards `POST
    /citizen-science/observations` and `POST /citizen-science/observations/{id}/resubmit`.
    The observer must hold a certification for the campaign's protocol whose
    `status` is `CERTIFIED` and whose `expires_at` is strictly later than the
    logical clock, otherwise `ERR_CERTIFICATION_NOT_VALID` (403)."
    PRD 2.7: "**Priority 53 — site saturation.** Guards `POST
    /citizen-science/observations`. The target site's `accepted_observation_count`
    must be strictly less than twice the campaign's `target_observations_per_site`
    at submission time, otherwise `ERR_SITE_SATURATED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/certification_safety_check_beats_site_saturation_check
    """
    world = _saturated_site_with_expired_certification(api)

    response = api.create_observation(
        _observation_payload(world, observed_at="2026-08-15T23:00:00Z", count_value=1),
        world["vol_headers"])

    error = validate_error(response, ApiErrorId.ERR_CERTIFICATION_NOT_VALID.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_SITE_SATURATED.value, (
        "The certification check at priority 31 pre-empts saturation at priority 53")


def test_expired_certification_and_saturated_site_coexist_before_the_conflict(api):
    """PRD 3.9: "First, certifications expire: every certification in `CERTIFIED`
    whose `expires_at` the clock has reached or passed moves `CERTIFIED → EXPIRED`."
    PRD 3.3: "Each site's `coverage_status` is then decided by a ladder evaluated
    in exactly this order: the site is `GAP` when its `coverage_ratio` is below
    0.50; otherwise it is `SATURATED` when its `accepted_observation_count` has
    reached twice the campaign's `target_observations_per_site`; otherwise it is
    `MET` when its `coverage_ratio` is exactly 1.00; otherwise it is `UNDER`."

    Design: Difficulty/priority_pair_validation_conflict/certification_safety_check_beats_site_saturation_check
    """
    world = _saturated_site_with_expired_certification(api)

    assert read_certification(world["c1"])["status"] == "EXPIRED"
    site = read_site(world["cam1"], world["s_one"])
    assert site["accepted_observation_count"] == 2
    assert site["coverage_status"] == "SATURATED", (
        f"2 accepted records against a target of 1 saturates the site, got "
        f"{site['coverage_status']}")


def test_reading_an_unknown_observation_is_a_not_found(api):
    """PRD 2.7: "**Priority 4 — path resource existence (every operation with a
    templated path segment).** Each templated segment is resolved strictly left to
    right, and the first one that names no row terminates the request with that
    entity's not-found error at HTTP 404: `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND`."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/entities/observation_get_unknown_id_not_found
    """
    response = api.get_observation("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(response, ApiErrorId.ERR_OBSERVATION_NOT_FOUND.value, 404)
    assert response.json()["response_type"] == "error"


def test_photo_count_is_recounted_from_accepted_evidence_only(api):
    """PRD 3.5: "After each upload the observation's `photo_count` is recounted as
    the number of its photo-evidence children whose `status` is `ACCEPTED` — flagged
    and rejected images are stored and readable but contribute nothing — and
    `provisional_quality_points` is recomputed from the new count, with the
    observation's `version` incrementing."
    PRD 3.5: "First the service computes `geo_delta_meters`: the planar distance
    between the EXIF fix and the observation's own fix, obtained by taking the
    difference in latitude and the difference in longitude, squaring each, summing
    them, taking the square root, multiplying by 111320.0 metres per degree, and
    rounding to two decimal places."

    Design: Corner/entities/observation_photo_count_is_computed_and_input_ignored
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_observation(world, count_value=3)
    assert observation["photo_count"] == 0

    photo = validate_success(api.attach_photo(observation["id"], {
        "file_hash": "ph-corner", "captured_at": "2026-08-05T06:05:00Z",
        "exif_latitude": 44.0, "exif_longitude": -70.0}, world["vol_headers"]), 201)

    assert_photo_evidence(photo)
    assert photo["status"] == "ACCEPTED"
    assert float(photo["geo_delta_meters"]) == pytest.approx(0.00, abs=1e-9)

    stored = read_observation(observation["id"])
    assert stored["photo_count"] == 1
    assert float(stored["provisional_quality_points"]) == pytest.approx(60.00, abs=1e-9), (
        f"40 base * 1.00 timeliness * 1.50 site factor is 60.00, got "
        f"{stored['provisional_quality_points']}")


def test_photo_captured_exactly_two_hours_after_the_sighting_is_accepted(api):
    """PRD 3.5: "If `captured_at` is earlier than `observed_at` by more than two
    hours, or later than `observed_at` by more than two hours, the photo's `status`
    is set to `REJECTED` and the geographic comparison is not evaluated at all on
    that branch."
    PRD 3.5: "Both tolerance comparisons are strict, so a photograph captured
    exactly two hours after `observed_at`, or sitting exactly 250.00 metres from the
    observation fix, is `ACCEPTED`."

    Design: Corner/calculations/photo_time_window_boundary_accepts_exact_two_hour_offset
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_observation(world, count_value=3)

    on_boundary = validate_success(api.attach_photo(observation["id"], {
        "file_hash": "ph-edge-in", "captured_at": "2026-08-05T08:00:00Z",
        "exif_latitude": 44.0, "exif_longitude": -70.0}, world["vol_headers"]), 201)
    one_second_past = validate_success(api.attach_photo(observation["id"], {
        "file_hash": "ph-edge-out", "captured_at": "2026-08-05T08:00:01Z",
        "exif_latitude": 44.0, "exif_longitude": -70.0}, world["vol_headers"]), 201)

    assert on_boundary["status"] == "ACCEPTED", (
        f"Exactly two hours after observed_at is inside tolerance, got "
        f"{on_boundary['status']}")
    assert one_second_past["status"] == "REJECTED", (
        f"More than two hours after observed_at is REJECTED, got "
        f"{one_second_past['status']}")
    assert float(on_boundary["geo_delta_meters"]) == pytest.approx(0.00, abs=1e-9)
    assert read_observation(observation["id"])["photo_count"] == 1


def test_geographically_mismatched_photo_is_flagged_and_never_counted(api):
    """PRD 3.5: "Otherwise, if `geo_delta_meters` is greater than 250.00, the
    `status` is `FLAGGED_MISMATCH`."
    PRD 3.5: "After each upload the observation's `photo_count` is recounted as the
    number of its photo-evidence children whose `status` is `ACCEPTED` — flagged and
    rejected images are stored and readable but contribute nothing — and
    `provisional_quality_points` is recomputed from the new count, with the
    observation's `version` incrementing."
    PRD 2.7: "**Priority 50 — photo evidence sufficiency.** Guards `POST
    /citizen-science/observations/{id}/start-review`. The observation's
    `photo_count` must be at least the protocol's `min_photo_count`, otherwise
    `ERR_PHOTO_EVIDENCE_INSUFFICIENT` (422)."

    Design: Corner/calculations/photo_geo_mismatch_flagged_and_excluded_from_photo_count
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_observation(world, count_value=3)

    photo = validate_success(api.attach_photo(observation["id"], {
        "file_hash": "ph-far", "captured_at": "2026-08-05T06:05:00Z",
        "exif_latitude": 44.005, "exif_longitude": -70.0}, world["vol_headers"]), 201)

    assert float(photo["geo_delta_meters"]) == pytest.approx(556.60, abs=1e-9), (
        f"0.005 degrees * 111320.0 metres per degree is 556.60, got "
        f"{photo['geo_delta_meters']}")
    assert photo["status"] == "FLAGGED_MISMATCH"
    assert read_observation(observation["id"])["photo_count"] == 0

    validate_error(api.start_review(observation["id"], world["e1_headers"]),
                   ApiErrorId.ERR_PHOTO_EVIDENCE_INSUFFICIENT.value, 422)
    assert read_observation(observation["id"])["review_status"] == "SUBMITTED"


def test_photo_time_test_short_circuits_the_geographic_test(api):
    """PRD 3.5: "Then the time test runs first and the geographic test second. If
    `captured_at` is earlier than `observed_at` by more than two hours, or later than
    `observed_at` by more than two hours, the photo's `status` is set to `REJECTED`
    and the geographic comparison is not evaluated at all on that branch."
    PRD 3.5: "First the service computes `geo_delta_meters`: the planar distance
    between the EXIF fix and the observation's own fix, obtained by taking the
    difference in latitude and the difference in longitude, squaring each, summing
    them, taking the square root, multiplying by 111320.0 metres per degree, and
    rounding to two decimal places."

    Design: Corner/calculations/photo_time_check_precedes_geo_check
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_observation(world, count_value=3)

    photo = validate_success(api.attach_photo(observation["id"], {
        "file_hash": "ph-both-bad", "captured_at": "2026-08-05T12:00:00Z",
        "exif_latitude": 44.005, "exif_longitude": -70.0}, world["vol_headers"]), 201)

    assert photo["status"] == "REJECTED", (
        f"The time test decides the branch, got {photo['status']}")
    assert photo["status"] != "FLAGGED_MISMATCH"
    assert float(photo["geo_delta_meters"]) == pytest.approx(556.60, abs=1e-9)
    assert read_observation(observation["id"])["photo_count"] == 0


def test_photo_bonus_is_capped_and_the_site_factor_is_clamped(api):
    """PRD 3.5: "On top of that sits a photo bonus: 5 points for each accepted
    photo beyond the protocol's `min_photo_count`, never less than zero and capped
    at 20 points, so five surplus photographs earn the same bonus as fifty."
    PRD 3.5: "The product is then multiplied by a site factor equal to the site's
    `priority_weight` clamped into the range 0.80 to 1.50 — a weight below 0.80 is
    treated as 0.80 and a weight above 1.50 as 1.50."
    PRD 3.5: "`provisional_quality_points` is that raw score rounded to two decimal
    places."

    Design: Corner/calculations/observation_photo_bonus_capped_and_site_factor_clamped
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    site = create_site(world["cam1"], site_code="S-MAX", latitude=44.0, longitude=-70.0,
                       habitat_type="GRASSLAND", priority_weight=2.0)
    world["s_hi"] = site["id"]
    open_campaign(world["cam1"])

    observation = submit_observation(world, observed_at="2026-08-02T01:00:00Z",
                                     count_value=9)
    for index in range(1, 6):
        attach_photo(world, observation["id"], file_hash=f"ph-max-{index}",
                     captured_at=f"2026-08-02T01:0{index}:00Z",
                     exif_latitude=44.0, exif_longitude=-70.0)

    sixth = validate_success(api.attach_photo(observation["id"], {
        "file_hash": "ph-max-6", "captured_at": "2026-08-02T01:06:00Z",
        "exif_latitude": 44.0, "exif_longitude": -70.0}, world["vol_headers"]), 201)

    assert sixth["status"] == "ACCEPTED"
    stored = read_observation(observation["id"])
    assert stored["photo_count"] == 6
    assert float(stored["provisional_quality_points"]) == pytest.approx(45.00, abs=1e-9), (
        f"(40 + capped 20) * 0.50 timeliness * clamped 1.50 site factor is 45.00, "
        f"got {stored['provisional_quality_points']}")
    assert float(read_site(world["cam1"], site["id"])["priority_weight"]) == 2.0


def test_observation_outside_the_season_window_is_refused_at_the_boundary(api):
    """PRD 2.7: "**Priority 40 — observation inside season.** Guards `POST
    /citizen-science/observations`. The calendar date of `observed_at` must fall
    inside the campaign's season window, inclusive of both `season_start_date` and
    `season_end_date`, otherwise `ERR_OBSERVED_OUTSIDE_SEASON` (422)."
    PRD 3.5: "The calendar date of `observed_at` must fall inside the campaign's
    season window with both boundary dates included."

    Design: Corner/validations/observation_observed_outside_season_returns_error
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)

    outside = api.create_observation(
        _observation_payload(world, observed_at="2026-07-31T23:00:00Z", count_value=1),
        world["vol_headers"])
    validate_error(outside, ApiErrorId.ERR_OBSERVED_OUTSIDE_SEASON.value, 422)

    inside = validate_success(api.create_observation(
        _observation_payload(world, observed_at="2026-08-01T12:00:00Z", count_value=1),
        world["vol_headers"]), 201)

    assert inside["review_status"] == "SUBMITTED"
    assert inside["observed_at"] == "2026-08-01T12:00:00.000Z", (
        f"The first season date is included, got {inside['observed_at']}")


def test_site_campaign_mismatch_is_reported_before_the_season_check(api):
    """PRD 2.7: "**Priority 36 — site belongs to campaign.** Guards `POST
    /citizen-science/observations`. The supplied `site_id` must name a site whose
    `campaign_id` equals the supplied `campaign_id`, otherwise
    `ERR_SITE_CAMPAIGN_MISMATCH` (409)."
    PRD 2.7: "**Priority 40 — observation inside season.** Guards `POST
    /citizen-science/observations`. The calendar date of `observed_at` must fall
    inside the campaign's season window, inclusive of both `season_start_date` and
    `season_end_date`, otherwise `ERR_OBSERVED_OUTSIDE_SEASON` (422)."

    Design: Corner/validations/site_campaign_mismatch_beats_observed_outside_season
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK,
                        campaign_overrides={"season_end_date": "2026-08-31"})
    site = create_site(world["cam1"], site_code="S-HI", priority_weight=1.5)
    world["s_hi"] = site["id"]
    open_campaign(world["cam1"])

    other_campaign = create_campaign(
        world["p1"], name="Late Count", season_start_date="2026-09-01",
        season_end_date="2026-09-30")
    other_site = create_site(other_campaign["id"], site_code="S-OTHER", latitude=45.0,
                             longitude=-71.0, habitat_type="FOREST", priority_weight=1.0)

    response = api.create_observation(_observation_payload(
        world, site_id=other_site["id"], observed_at="2026-07-01T00:00:00Z",
        latitude=45.0, longitude=-71.0, count_value=1), world["vol_headers"])

    error = validate_error(response, ApiErrorId.ERR_SITE_CAMPAIGN_MISMATCH.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_OBSERVED_OUTSIDE_SEASON.value
    assert error["error_id"] != ApiErrorId.ERR_SUBMISSION_LAG_EXCEEDED.value


def test_start_review_needs_exactly_the_protocols_minimum_photo_count(api):
    """PRD 2.7: "**Priority 50 — photo evidence sufficiency.** Guards `POST
    /citizen-science/observations/{id}/start-review`. The observation's
    `photo_count` must be at least the protocol's `min_photo_count`, otherwise
    `ERR_PHOTO_EVIDENCE_INSUFFICIENT` (422)."
    PRD 3.6: "The observation must actually satisfy the protocol's evidence
    requirement by this point, meaning its `photo_count` is at or above the
    protocol's `min_photo_count`, otherwise `ERR_PHOTO_EVIDENCE_INSUFFICIENT`."

    Design: Corner/validations/photo_evidence_exact_minimum_satisfies_start_review
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK,
                        protocol_overrides={"code": "PHOTO-2",
                                            "title": "Two Photo Protocol",
                                            "min_photo_count": 2})
    observation = submit_observation(world, count_value=3)
    attach_photo(world, observation["id"], file_hash="ph-1",
                 captured_at="2026-08-05T06:05:00Z")

    validate_error(api.start_review(observation["id"], world["e1_headers"]),
                   ApiErrorId.ERR_PHOTO_EVIDENCE_INSUFFICIENT.value, 422)

    attach_photo(world, observation["id"], file_hash="ph-2",
                 captured_at="2026-08-05T06:10:00Z")
    assert read_observation(observation["id"])["photo_count"] == 2

    started = validate_success(api.start_review(observation["id"], world["e1_headers"]))
    assert started["review_status"] == "UNDER_REVIEW"


def test_certification_below_the_required_level_cannot_submit(api):
    """PRD 2.7: "**Priority 32 — certification level.** Guards `POST
    /citizen-science/observations`. The observer's certification `level` must rank at
    or above the protocol's `required_certification_level`, using the ordinal
    ranking where `BASIC` is 1, `ADVANCED` is 2, and `EXPERT` is 3. Otherwise
    `ERR_CERTIFICATION_LEVEL_INSUFFICIENT` (403)."

    Design: Corner/errors/observation_below_required_certification_level_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK, cert_level="BASIC",
                        protocol_overrides={"code": "EXPERT-ONLY",
                                            "title": "Expert Only Protocol",
                                            "required_certification_level": "EXPERT"})

    response = api.create_observation(_observation_payload(world, count_value=1),
                                      world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_LEVEL_INSUFFICIENT.value, 403)

    assert read_certification(world["c1"])["status"] == "CERTIFIED"
    _rows, meta = validate_paginated(api.list_observations(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_submission_without_the_required_instrument_loan_is_refused(api):
    """PRD 2.7: "**Priority 33 — equipment requirement.** Guards `POST
    /citizen-science/observations`. When the protocol's `required_equipment_type` is
    anything other than `NONE`, the submission must supply an `equipment_loan_id`
    whose loan has `status` `ISSUED`, whose loan `volunteer_id` equals the observer,
    and whose instrument's `equipment_type` equals the required type. Otherwise
    `ERR_EQUIPMENT_REQUIREMENT_UNMET` (422)."

    Design: Corner/errors/observation_without_required_equipment_loan_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK,
                        protocol_overrides={"code": "ACOUSTIC-1",
                                            "title": "Acoustic Protocol",
                                            "required_equipment_type": "ACOUSTIC_RECORDER"})

    response = api.create_observation(_observation_payload(world, count_value=1),
                                      world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_EQUIPMENT_REQUIREMENT_UNMET.value, 422)

    _rows, meta = validate_paginated(api.list_observations(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_submission_beyond_the_protocol_lag_window_is_refused(api):
    """PRD 2.7: "**Priority 41 — submission lag.** Guards `POST
    /citizen-science/observations`. The elapsed hours from `observed_at` to the
    logical clock must be at most the protocol's `max_submission_lag_hours`,
    otherwise `ERR_SUBMISSION_LAG_EXCEEDED` (422)."
    PRD 3.5: "The gap between `observed_at` and the logical clock, measured in
    hours, must not exceed the protocol's `max_submission_lag_hours`; a protocol set
    to 72 gives observers three days to write up their notes and no more."

    Design: Corner/errors/submission_lag_exceeded_returns_error
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    set_clock("2026-08-20T00:00:00Z")

    response = api.create_observation(
        _observation_payload(world, observed_at="2026-08-01T00:00:00Z", count_value=1),
        world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_SUBMISSION_LAG_EXCEEDED.value, 422)

    assert read_campaign(world["cam1"])["status"] == "OPEN"


def test_a_saturated_site_blocks_further_submissions(api):
    """PRD 2.7: "**Priority 53 — site saturation.** Guards `POST
    /citizen-science/observations`. The target site's `accepted_observation_count`
    must be strictly less than twice the campaign's `target_observations_per_site`
    at submission time, otherwise `ERR_SITE_SATURATED` (409)."
    PRD 3.5: "Finally the target site must not already be saturated: its
    `accepted_observation_count` must be strictly below twice the campaign's
    `target_observations_per_site`, otherwise the submission is refused with
    `ERR_SITE_SATURATED`."

    Design: Corner/errors/site_saturated_blocks_further_submission
    """
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK,
                        campaign_overrides={"target_observations_per_site": 1})
    site = create_site(world["cam1"], site_code="S-ONE", latitude=44.0, longitude=-70.0,
                       habitat_type="WETLAND", priority_weight=1.2)
    world["s_hi"] = site["id"]
    open_campaign(world["cam1"])

    create_accepted_observation(world, count_value=1)
    create_accepted_observation(world, count_value=2)

    response = api.create_observation(_observation_payload(world, count_value=7),
                                      world["vol_headers"])
    validate_error(response, ApiErrorId.ERR_SITE_SATURATED.value, 409)

    stored = read_site(world["cam1"], site["id"])
    assert stored["accepted_observation_count"] == 2
    assert stored["coverage_status"] == "SATURATED"
    assert float(stored["coverage_ratio"]) == pytest.approx(1.00, abs=1e-9)


def test_observation_listing_filters_by_review_status_and_paginates(api):
    """PRD 2.3: "Observations may be filtered by `campaign_id`, `site_id`,
    `volunteer_id`, `equipment_loan_id`, `publication_id`, `review_status`, and
    `publication_status`."
    PRD 2.3: "The pagination block returned in `meta` carries `limit`, `offset`,
    `total_count`, and `has_more`, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` is true exactly
    when rows remain beyond the current page."

    Design: Corner/endpoints/observation_list_filters_by_review_status_and_paginates
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    under_review = submit_with_photo(world, count_value=1)
    start_review(under_review["id"], world["e1_headers"])
    second = submit_observation(world, count_value=2)
    third = submit_observation(world, count_value=3)

    submitted = api.list_observations(ADMIN, {
        "campaign_id": world["cam1"], "review_status": "SUBMITTED",
        "limit": 1, "offset": 0})
    rows, meta = validate_paginated(submitted)
    assert meta["total_count"] == 2, f"Two rows are still SUBMITTED, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(rows) == 1
    assert rows[0]["id"] in (second["id"], third["id"])
    assert rows[0]["id"] != under_review["id"]
    assert submitted.json()["response_type"] == "array"

    reviewing = api.list_observations(world["e1_headers"], {
        "campaign_id": world["cam1"], "review_status": "UNDER_REVIEW",
        "limit": 10, "offset": 0})
    rows, meta = validate_paginated(reviewing)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == under_review["id"]
    assert reviewing.json()["response_type"] == "array"
