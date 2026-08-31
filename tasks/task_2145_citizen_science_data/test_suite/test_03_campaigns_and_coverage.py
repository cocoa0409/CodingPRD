"""Seasonal campaigns, survey sites and the two-stage coverage arithmetic."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_campaign,
    assert_coverage_consistent,
    assert_survey_site,
    build_world,
    create_accepted_observation,
    create_active_protocol,
    create_campaign,
    create_site,
    open_campaign,
    read_campaign,
    read_site,
    set_clock,
    submit_observation,
    STAGE_CAMPAIGN,
    STAGE_OPEN,
    STAGE_PROTOCOL,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def _two_site_open_world():
    """Standard world with S-HI (1.5) and S-LO (0.8) and the campaign OPEN."""
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    site_hi = create_site(world["cam1"], site_code="S-HI", latitude=44.0,
                          longitude=-70.0, habitat_type="WETLAND", priority_weight=1.5)
    site_lo = create_site(world["cam1"], site_code="S-LO", latitude=44.5,
                          longitude=-70.5, habitat_type="FOREST", priority_weight=0.8)
    world["campaign"] = open_campaign(world["cam1"])
    world["s_hi"] = site_hi["id"]
    world["s_lo"] = site_lo["id"]
    return world


def test_coverage_score_averages_the_already_rounded_per_site_ratios(api):
    """PRD 3.3: "In the first stage, each survey site of the campaign — every site
    row, with no status filter and including sites that have never received a
    single record — has its `accepted_observation_count` recounted as the number of
    that site's observations whose `review_status` is `ACCEPTED`, and its
    `coverage_ratio` set to that count divided by the campaign's
    `target_observations_per_site`, capped at 1.0, and then rounded to two decimal
    places."
    PRD 3.3: "The two-stage rounding is a genuine numerical commitment, not a
    formality. Averaging the unrounded ratios and rounding once at the end produces
    a different answer: a campaign with a target of 3 and two sites holding 1 and 0
    accepted records yields a `coverage_score` of 0.1650 under the pinned order and
    0.1667 under the single-rounding order. The pinned order is the correct one."

    Design: Difficulty/combinatorial_formula/campaign_coverage_two_stage_rounding_order
    """
    world = _two_site_open_world()

    observation = create_accepted_observation(world, site_id=world["s_hi"], count_value=3)
    assert observation["review_status"] == "ACCEPTED"

    campaign = read_campaign(world["cam1"])
    assert float(campaign["coverage_score"]) == pytest.approx(0.1650, abs=1e-9), (
        f"Rounding each site ratio before averaging yields 0.1650, got "
        f"{campaign['coverage_score']}")
    assert float(campaign["coverage_score"]) != pytest.approx(0.1667, abs=1e-9), (
        "Averaging the unrounded ratios first is the wrong order")


def test_coverage_recount_updates_site_ratios_status_and_campaign_counters(api):
    """PRD 3.3: "Each site's `coverage_status` is then decided by a ladder
    evaluated in exactly this order: the site is `GAP` when its `coverage_ratio` is
    below 0.50; otherwise it is `SATURATED` when its `accepted_observation_count`
    has reached twice the campaign's `target_observations_per_site`; otherwise it is
    `MET` when its `coverage_ratio` is exactly 1.00; otherwise it is `UNDER`."
    PRD 3.3: "In the second stage, the campaign's `site_count` is set to the number
    of site rows, its `coverage_score` is set to the arithmetic mean of the
    already-rounded per-site ratios rounded to four decimal places (or 0.0000 when
    the campaign has no sites at all), and its `gap_count` is set to the number of
    sites whose `coverage_ratio` is below 0.50."

    Design: Difficulty/combinatorial_formula/campaign_coverage_two_stage_rounding_order
    """
    world = _two_site_open_world()
    create_accepted_observation(world, site_id=world["s_hi"], count_value=3)

    site_hi = read_site(world["cam1"], world["s_hi"])
    site_lo = read_site(world["cam1"], world["s_lo"])
    campaign = read_campaign(world["cam1"])

    assert_survey_site(site_hi)
    assert site_hi["accepted_observation_count"] == 1
    assert float(site_hi["coverage_ratio"]) == pytest.approx(0.33, abs=1e-9), (
        f"1/3 rounded to two decimal places is 0.33, got {site_hi['coverage_ratio']}")
    assert site_hi["coverage_status"] == "GAP", (
        f"0.33 is below 0.50 so the site is GAP, got {site_hi['coverage_status']}")
    assert float(site_lo["coverage_ratio"]) == pytest.approx(0.00, abs=1e-9)

    assert_campaign(campaign)
    assert campaign["gap_count"] == 2
    assert campaign["site_count"] == 2
    assert campaign["accepted_observation_count"] == 1
    assert_coverage_consistent(campaign, [site_hi, site_lo])


def test_opening_a_campaign_with_no_sites_is_refused(api):
    """PRD 2.7: "**Priority 51 — campaign has sites.** Guards `POST
    /citizen-science/campaigns/{id}/open` and `POST /citizen-science/campaigns/{id}/close`.
    The campaign's `site_count` must be at least 1, otherwise
    `ERR_CAMPAIGN_HAS_NO_SITES` (422)."
    PRD 3.3: "The new campaign lands in `PLANNED` with `coverage_score`,
    `gap_count`, `site_count`, and `accepted_observation_count` all at 0."

    Design: Difficulty/boundary_precision_check/campaign_open_with_zero_sites_rejected_and_with_one_site_accepted
    """
    world = build_world(stage=STAGE_PROTOCOL, clock=CLOCK)
    campaign = create_campaign(world["p1"])

    response = api.open_campaign(campaign["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_HAS_NO_SITES.value, 422)

    stored = read_campaign(campaign["id"])
    assert stored["status"] == "PLANNED"
    assert stored["site_count"] == 0
    assert float(stored["coverage_score"]) == pytest.approx(0.0000, abs=1e-9), (
        "A campaign with no sites reports coverage_score 0.0000 rather than failing")


def test_opening_a_campaign_with_exactly_one_site_succeeds(api):
    """PRD 3.3: "Opening a campaign moves it `PLANNED → OPEN` or `CLOSED → OPEN`.
    It requires the campaign's protocol to be `ACTIVE` and the campaign to hold at
    least one site, and it re-runs the coverage arithmetic before returning."
    PRD 3.3: "In the second stage, the campaign's `site_count` is set to the number
    of site rows, its `coverage_score` is set to the arithmetic mean of the
    already-rounded per-site ratios rounded to four decimal places (or 0.0000 when
    the campaign has no sites at all), and its `gap_count` is set to the number of
    sites whose `coverage_ratio` is below 0.50."

    Design: Difficulty/boundary_precision_check/campaign_open_with_zero_sites_rejected_and_with_one_site_accepted
    """
    world = build_world(stage=STAGE_PROTOCOL, clock=CLOCK)
    campaign = create_campaign(world["p1"])
    site = create_site(campaign["id"], site_code="S-HI", priority_weight=1.5)

    opened = validate_success(api.open_campaign(campaign["id"], ADMIN))

    assert opened["status"] == "OPEN"
    assert float(read_site(campaign["id"], site["id"])["coverage_ratio"]) == \
        pytest.approx(0.00, abs=1e-9)
    stored = read_campaign(campaign["id"])
    assert stored["site_count"] == 1
    assert stored["gap_count"] == 1
    assert float(stored["coverage_score"]) == pytest.approx(0.0000, abs=1e-9)


def test_campaign_season_window_may_not_start_on_another_windows_end_date(api):
    """PRD 2.9: "Adjacency is therefore forbidden: a new campaign whose
    `season_start_date` equals an existing campaign's `season_end_date` is
    rejected."
    PRD 3.3: "Season windows on the same protocol may not intersect, under the
    closed-inclusive regime of §2.9; a collision is refused with
    `ERR_SEASON_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/campaign_season_closed_interval_adjacency_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    protocol = create_active_protocol()
    create_campaign(protocol["id"], name="Summer Survey",
                    season_start_date="2026-08-01", season_end_date="2026-09-30")

    response = api.create_campaign({
        "name": "Autumn Survey Adjacent", "protocol_id": protocol["id"],
        "season_start_date": "2026-09-30", "season_end_date": "2026-10-31",
        "target_observations_per_site": 3}, ADMIN)
    validate_error(response, ApiErrorId.ERR_SEASON_WINDOW_CONFLICT.value, 409)

    _rows, meta = validate_paginated(api.list_campaigns(
        ADMIN, {"protocol_id": protocol["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, (
        f"The adjacent campaign must not have been created, got {meta['total_count']}")


def test_campaign_season_window_starting_one_day_later_is_accepted(api):
    """PRD 2.9: "Two windows intersect unless one ends strictly before the other
    begins — that is, they are disjoint only when the first window's
    `season_end_date` is strictly earlier than the second window's
    `season_start_date`, or the second's `season_end_date` is strictly earlier than
    the first's `season_start_date`."
    PRD 3.3: "The new campaign lands in `PLANNED` with `coverage_score`,
    `gap_count`, `site_count`, and `accepted_observation_count` all at 0."

    Design: Difficulty/resource_temporal_overlap/campaign_season_closed_interval_adjacency_rejected
    """
    set_clock("2026-07-01T00:00:00Z")
    protocol = create_active_protocol()
    create_campaign(protocol["id"], name="Summer Survey",
                    season_start_date="2026-08-01", season_end_date="2026-09-30")

    created = validate_success(api.create_campaign({
        "name": "Autumn Survey Clear", "protocol_id": protocol["id"],
        "season_start_date": "2026-10-01", "season_end_date": "2026-10-31",
        "target_observations_per_site": 3}, ADMIN), 201)

    assert created["status"] == "PLANNED"
    assert created["season_start_date"] == "2026-10-01"
    _rows, meta = validate_paginated(api.list_campaigns(
        ADMIN, {"protocol_id": protocol["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, (
        f"Exactly two campaigns exist on the protocol, got {meta['total_count']}")


def test_campaign_listing_reports_total_count_and_has_more(api):
    """PRD 2.3: "The pagination block returned in `meta` carries `limit`,
    `offset`, `total_count`, and `has_more`, where `total_count` is the number of
    rows matching the filters before pagination is applied and `has_more` is true
    exactly when rows remain beyond the current page."
    PRD 2.3: "Campaigns may be filtered by `protocol_id` and `status`."
    PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/campaign_list_pagination_reports_total_count_and_has_more
    """
    protocol = validate_success(api.create_protocol({
        "code": "PAGE-1", "title": "Pagination Protocol",
        "required_certification_level": "BASIC", "min_photo_count": 1,
        "max_submission_lag_hours": 48}, ADMIN), 201)
    for name, start, end in (("Window A", "2026-08-01", "2026-08-10"),
                             ("Window B", "2026-08-12", "2026-08-20"),
                             ("Window C", "2026-08-22", "2026-08-31")):
        create_campaign(protocol["id"], name=name, season_start_date=start,
                        season_end_date=end, target_observations_per_site=2)

    first = api.list_campaigns(ADMIN, {"protocol_id": protocol["id"],
                                       "limit": 2, "offset": 0})
    rows, meta = validate_paginated(first)
    assert len(rows) == 2, f"Expected a page of 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert first.json()["response_type"] == "array"

    second = api.list_campaigns(ADMIN, {"protocol_id": protocol["id"],
                                        "limit": 2, "offset": 2})
    rows, meta = validate_paginated(second)
    assert len(rows) == 1, f"Expected the tail page of 1 row, got {len(rows)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert second.json()["response_type"] == "array"


def test_adding_a_site_under_an_unknown_campaign_is_a_campaign_not_found(api):
    """PRD 2.7: "**Priority 4 — path resource existence (every operation with a
    templated path segment).** Each templated segment is resolved strictly left to
    right, and the first one that names no row terminates the request with that
    entity's not-found error at HTTP 404: `ERR_PROTOCOL_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_EXPERT_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
    `ERR_CAMPAIGN_NOT_FOUND`, `ERR_OBSERVATION_NOT_FOUND`, `ERR_EQUIPMENT_NOT_FOUND`,
    `ERR_LOAN_NOT_FOUND`, `ERR_PUBLICATION_NOT_FOUND`, `ERR_PARTNER_NOT_FOUND`,
    `ERR_GRANT_NOT_FOUND`, or `ERR_AWARD_NOT_FOUND`."

    Design: Corner/entities/site_create_under_unknown_campaign_not_found
    """
    response = api.create_site("00000000-0000-4000-8000-0000000000aa", {
        "site_code": "S-ORPHAN", "latitude": 1.0, "longitude": 2.0,
        "habitat_type": "COASTAL"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, 404)


def test_campaign_sites_subresource_returns_only_that_campaigns_children(api):
    """PRD 2.8: "Nested collections behave predictably: a request for the sites of
    a campaign, the photo evidence of an observation, the votes on an observation,
    or the votes cast by an expert returns only the children of the named parent,
    paginated and ordered by `created_at` ascending like any other list."
    PRD 2.3: "The site list of a campaign may be filtered by `coverage_status`."
    PRD 3.3: "A newly added site starts with `accepted_observation_count` at 0,
    `coverage_ratio` at 0.0, and `coverage_status` at `GAP`."

    Design: Corner/endpoints/campaign_sites_subresource_returns_children_with_coverage
    """
    world = _two_site_open_world()

    rows, meta = validate_paginated(api.list_sites(
        world["cam1"], ADMIN, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2, f"Expected 2 site rows, got {meta['total_count']}"
    assert {row["id"] for row in rows} == {world["s_hi"], world["s_lo"]}
    for row in rows:
        assert float(row["coverage_ratio"]) == pytest.approx(0.00, abs=1e-9)
        assert row["coverage_status"] == "GAP"

    filtered, filtered_meta = validate_paginated(api.list_sites(
        world["cam1"], world["vol_headers"],
        {"coverage_status": "GAP", "limit": 10, "offset": 0}))
    assert filtered_meta["total_count"] == 2
    assert {row["id"] for row in filtered} == {world["s_hi"], world["s_lo"]}


def test_adding_a_site_reconciles_the_campaigns_derived_coverage_fields(api):
    """PRD 3.3: "Sites may be added to a campaign in any status except `PUBLISHED`
    or `ARCHIVED`; adding one raises the campaign's `site_count`, re-runs the
    coverage arithmetic, and increments the campaign's `version`."
    PRD 3.3: "In the second stage, the campaign's `site_count` is set to the number
    of site rows, its `coverage_score` is set to the arithmetic mean of the
    already-rounded per-site ratios rounded to four decimal places (or 0.0000 when
    the campaign has no sites at all), and its `gap_count` is set to the number of
    sites whose `coverage_ratio` is below 0.50."

    Design: Corner/cross_cutting_layers/campaign_derived_coverage_fields_reconcile_when_a_site_is_added
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    create_accepted_observation(world, count_value=3)

    before = read_campaign(world["cam1"])
    assert before["site_count"] == 1
    assert float(before["coverage_score"]) == pytest.approx(0.3300, abs=1e-9)
    assert before["gap_count"] == 1

    create_site(world["cam1"], site_code="S-LO", latitude=44.5, longitude=-70.5,
                habitat_type="FOREST", priority_weight=0.8)

    after = read_campaign(world["cam1"])
    assert after["site_count"] == 2
    assert float(after["coverage_score"]) == pytest.approx(0.1650, abs=1e-9), (
        f"The mean of the rounded ratios 0.33 and 0.00 is 0.1650, got "
        f"{after['coverage_score']}")
    assert after["gap_count"] == 2
    assert float(read_site(world["cam1"], world["s_hi"])["coverage_ratio"]) == \
        pytest.approx(0.33, abs=1e-9)


def test_closing_a_campaign_with_a_review_still_in_flight_is_refused(api):
    """PRD 3.3: "Closing moves the campaign `OPEN → CLOSED`, again requires at
    least one site, and additionally requires that no observation of the campaign is
    still in flight — nothing in `SUBMITTED`, `UNDER_REVIEW`, or `NEEDS_REVISION` —
    otherwise the close is refused with `ERR_OPEN_REVIEWS_PENDING`."

    Design: Corner/errors/campaign_close_with_open_review_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observation = submit_observation(world, count_value=3)
    assert observation["review_status"] == "SUBMITTED"

    response = api.close_campaign(world["cam1"], ADMIN)
    validate_error(response, ApiErrorId.ERR_OPEN_REVIEWS_PENDING.value, 409)

    assert read_campaign(world["cam1"])["status"] == "OPEN"
