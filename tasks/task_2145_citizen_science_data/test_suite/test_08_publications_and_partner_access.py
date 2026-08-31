"""Assembling datasets and granting research partners scoped access."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_data_publication,
    assert_partner_access_grant,
    assert_research_partner,
    api_client,
    approve_grant,
    build_world,
    close_campaign,
    create_accepted_observation,
    create_publication,
    create_site,
    open_campaign,
    read_campaign,
    read_grant,
    read_observation,
    read_partner,
    read_publication,
    register_partner,
    request_grant,
    set_clock,
    setup_publishable_campaign,
    STAGE_CAMPAIGN,
    STAGE_OPEN,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-05T09:00:00Z"


def _four_accepted_records_world():
    """Two sites, four ACCEPTED records worth 12.80, 25.60, 66.00 and 66.00."""
    world = build_world(stage=STAGE_CAMPAIGN, clock=CLOCK)
    site_hi = create_site(world["cam1"], site_code="S-HI", latitude=44.0, longitude=-70.0,
                          habitat_type="WETLAND", priority_weight=1.5)
    site_lo = create_site(world["cam1"], site_code="S-LO", latitude=44.5, longitude=-70.5,
                          habitat_type="FOREST", priority_weight=0.8)
    world["s_hi"] = site_hi["id"]
    world["s_lo"] = site_lo["id"]
    open_campaign(world["cam1"])

    low = create_accepted_observation(
        world, site_id=site_lo["id"], confidence=2, observed_at="2026-08-02T01:00:00Z",
        latitude=44.5, longitude=-70.5, species_code="CORA", count_value=1,
        photo_overrides={"captured_at": "2026-08-02T01:30:00Z",
                         "exif_latitude": 44.5, "exif_longitude": -70.5})
    mid = create_accepted_observation(
        world, site_id=site_lo["id"], confidence=2, latitude=44.5, longitude=-70.5,
        species_code="CORA", count_value=2,
        photo_overrides={"exif_latitude": 44.5, "exif_longitude": -70.5})
    high_a = create_accepted_observation(world, site_id=site_hi["id"], confidence=5,
                                         count_value=4)
    high_b = create_accepted_observation(world, site_id=site_hi["id"], confidence=5,
                                         count_value=5)
    close_campaign(world["cam1"])
    return world, low, mid, high_a, high_b


def test_publication_quality_floor_is_the_lower_median_of_the_candidate_set(api):
    """PRD 3.8: "From that set alone the `quality_floor` is derived: when the
    candidate set is empty the floor is 0.00, and otherwise the candidates are sorted
    by `final_quality_points` ascending with `created_at` ascending as the tie-break,
    the lower median is taken — for an odd-sized set the middle element, and for an
    even-sized set the lower of the two central elements — and the floor is that
    element's `final_quality_points` multiplied by 0.80 and rounded to two decimal
    places."
    PRD 3.8: "The floor is never re-derived from the included subset — evaluation
    stops here and there is no fixed-point iteration; recomputing the median from the
    survivors would be wrong."

    Design: Difficulty/combinatorial_formula/publication_quality_floor_pinned_to_candidate_set
    """
    world, low, mid, high_a, high_b = _four_accepted_records_world()

    assert float(read_observation(low["id"])["final_quality_points"]) == \
        pytest.approx(12.80, abs=1e-9)
    assert float(read_observation(mid["id"])["final_quality_points"]) == \
        pytest.approx(25.60, abs=1e-9)
    assert float(read_observation(high_a["id"])["final_quality_points"]) == \
        pytest.approx(66.00, abs=1e-9)
    assert float(read_observation(high_b["id"])["final_quality_points"]) == \
        pytest.approx(66.00, abs=1e-9)

    publication = create_publication(world["cam1"], doi="10.5555/cs-2026-01")

    assert_data_publication(publication)
    assert float(publication["quality_floor"]) == pytest.approx(20.48, abs=1e-9), (
        f"The lower median 25.60 times 0.80 is 20.48, got {publication['quality_floor']}")
    assert publication["record_count"] == 3, (
        f"Three candidates clear the pinned floor, got {publication['record_count']}")
    assert float(publication["mean_quality"]) == pytest.approx(52.53, abs=1e-9)
    assert publication["status"] == "DRAFT"


def test_publication_binds_only_the_candidates_at_or_above_the_floor(api):
    """PRD 3.8: "Inclusion is then decided against that floor and is inclusive at
    it: every candidate whose `final_quality_points` is greater than or equal to
    `quality_floor` is included."
    PRD 3.8: "**Step three** binds the result: every included observation has its
    `publication_id` set to the new publication. Those observations stay in `QUEUED`;
    nothing moves to `PUBLISHED` until the dataset is actually released."

    Design: Difficulty/combinatorial_formula/publication_quality_floor_pinned_to_candidate_set
    """
    world, low, mid, high_a, high_b = _four_accepted_records_world()

    publication = create_publication(world["cam1"], doi="10.5555/cs-2026-01")

    assert read_observation(low["id"])["publication_id"] is None, (
        "12.80 sits below the 20.48 floor and stays unbound")
    for observation in (mid, high_a, high_b):
        stored = read_observation(observation["id"])
        assert stored["publication_id"] == publication["id"]
        assert stored["publication_status"] == "QUEUED"


def test_releasing_a_publication_advances_only_the_publication_dimension(api):
    """PRD 3.8: "When `embargo_until` is null, or when the logical clock has
    reached or passed it, the publication moves `DRAFT → RELEASED`: `released_at` is
    stamped from the logical clock, every bound observation moves
    `publication_status` `QUEUED → PUBLISHED`, and the owning campaign moves `CLOSED →
    PUBLISHED`."
    PRD 3.8: "From that set alone the `quality_floor` is derived: when the candidate
    set is empty the floor is 0.00, and otherwise the candidates are sorted by
    `final_quality_points` ascending with `created_at` ascending as the tie-break, the
    lower median is taken — for an odd-sized set the middle element, and for an
    even-sized set the lower of the two central elements — and the floor is that
    element's `final_quality_points` multiplied by 0.80 and rounded to two decimal
    places."

    Design: Corner/state_machines/publication_release_advances_observation_publication_dimension_only
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observations = setup_publishable_campaign(world, accepted_count=2)
    publication = create_publication(world["cam1"], doi="10.5555/cs-2026-09")

    assert float(publication["quality_floor"]) == pytest.approx(52.80, abs=1e-9)
    assert publication["record_count"] == 2
    assert float(publication["mean_quality"]) == pytest.approx(66.00, abs=1e-9)

    released = validate_success(api.release_publication(publication["id"], ADMIN))

    assert released["status"] == "RELEASED"
    assert released["released_at"] == "2026-08-05T09:00:00.000Z"
    for observation in observations:
        stored = read_observation(observation["id"])
        assert stored["publication_status"] == "PUBLISHED"
        assert stored["review_status"] == "ACCEPTED", (
            "The review dimension is untouched by a release")
    assert read_campaign(world["cam1"])["status"] == "PUBLISHED"


def test_withdrawing_a_publication_revokes_grants_and_suspends_the_partner(api):
    """PRD 3.8: "The second link, caused by the first, tears down access: every
    access grant on this publication whose `status` is `APPROVED` transitions
    `APPROVED → REVOKED` with `denied_reason` set to `PUBLICATION_WITHDRAWN` and the
    owning partner's `active_grant_count` decremented, while every grant still in
    `REQUESTED` transitions `REQUESTED → DENIED` with the same `denied_reason`."
    PRD 3.8: "The third link, caused by the second, disciplines the partners: every
    research partner whose `active_grant_count` reached 0 as a consequence of the
    second link, and whose own `status` was `APPROVED`, transitions `APPROVED →
    SUSPENDED`."
    PRD 3.8: "The first link separates the bound observations: those whose
    `publication_status` is `PUBLISHED` move to `WITHDRAWN`, and those whose
    `publication_status` is `QUEUED` move `QUEUED → UNPUBLISHED` with `publication_id`
    cleared to null, so they can be picked up by a later dataset."
    PRD 3.8: "Alongside the chain, the owning campaign moves `PUBLISHED → CLOSED`
    once no `RELEASED` publication remains on it."

    Design: Corner/state_machines/publication_withdraw_cascade_revokes_grant_and_suspends_partner
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observations = setup_publishable_campaign(world, accepted_count=2)
    publication = create_publication(world["cam1"], doi="10.5555/cs-2026-10")
    validate_success(api.release_publication(publication["id"], ADMIN))

    partner = register_partner(approved=True, org_name="Boreal Institute",
                               contact_email="data@boreal.example",
                               trust_tier="STANDARD",
                               data_use_agreement_signed_at="2026-07-01T00:00:00Z")
    grant = approve_grant(request_grant(publication["id"], partner["id"], "FULL")["id"])
    assert grant["status"] == "APPROVED"

    withdrawn = validate_success(api.withdraw_publication(
        publication["id"], {"reason": "systematic geolocation error discovered"}, ADMIN))

    assert withdrawn["status"] == "WITHDRAWN"
    stored_grant = read_grant(grant["id"])
    assert_partner_access_grant(stored_grant)
    assert stored_grant["status"] == "REVOKED"
    assert stored_grant["denied_reason"] == "PUBLICATION_WITHDRAWN"

    stored_partner = read_partner(partner["id"])
    assert_research_partner(stored_partner)
    assert stored_partner["active_grant_count"] == 0
    assert stored_partner["status"] == "SUSPENDED"

    for observation in observations:
        stored = read_observation(observation["id"])
        assert stored["publication_status"] == "WITHDRAWN"
        assert stored["review_status"] == "ACCEPTED"
    assert read_campaign(world["cam1"])["status"] == "CLOSED"


def test_the_maintenance_sweep_releases_a_matured_embargo(api):
    """PRD 3.8: "When `embargo_until` is set and the logical clock has not yet
    reached it, the publication instead moves `DRAFT → EMBARGOED` and its bound
    observations stay in `QUEUED`; the campaign does not change status and the
    dataset waits."
    PRD 3.9: "Fourth, matured embargoes release: every publication in `EMBARGOED`
    whose `embargo_until` the clock has reached or passed moves `EMBARGOED →
    RELEASED`, stamping `released_at`, moving its bound observations `QUEUED →
    PUBLISHED`, and moving its campaign `CLOSED → PUBLISHED`."
    PRD 3.9: "Sixth and last, campaigns archive: every campaign in `PUBLISHED` whose
    `season_end_date` plus 30 days is strictly earlier than the clock's calendar date
    moves `PUBLISHED → ARCHIVED`."

    Design: Corner/state_machines/maintenance_run_releases_matured_embargo
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observations = setup_publishable_campaign(world, accepted_count=2)
    publication = create_publication(world["cam1"], doi="10.5555/cs-2026-11",
                                     embargo_until="2026-09-01T00:00:00Z")
    embargoed = validate_success(api.release_publication(publication["id"], ADMIN))

    assert embargoed["status"] == "EMBARGOED"
    assert read_observation(observations[0]["id"])["publication_status"] == "QUEUED"

    set_clock("2026-09-01T00:00:00Z")
    sweep = validate_success(api.run_maintenance(ADMIN))

    assert sweep["released_publication_count"] == 1
    assert sweep["archived_campaign_count"] == 0
    stored = read_publication(publication["id"])
    assert stored["status"] == "RELEASED"
    assert stored["released_at"] == "2026-09-01T00:00:00.000Z"
    assert read_observation(observations[0]["id"])["publication_status"] == "PUBLISHED"
    assert read_campaign(world["cam1"])["status"] == "PUBLISHED"


def test_withdrawing_an_already_withdrawn_publication_is_refused(api):
    """PRD 2.7: "**Priority 25 — publication state.** Guards `POST
    /citizen-science/publications` (the owning campaign's `status` must be `CLOSED` or
    `PUBLISHED`), `POST /citizen-science/publications/{id}/release` (the publication
    must be `DRAFT`), and `POST /citizen-science/publications/{id}/withdraw` (the
    publication must be `DRAFT`, `EMBARGOED`, or `RELEASED`). Otherwise
    `ERR_PUBLICATION_STATE_INVALID` (409)."
    PRD 3.8: "`WITHDRAWN` is terminal for a publication."

    Design: Corner/state_machines/publication_withdraw_from_withdrawn_state_rejected
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    setup_publishable_campaign(world, accepted_count=2)
    publication = create_publication(world["cam1"], doi="10.5555/cs-2026-12")
    validate_success(api.release_publication(publication["id"], ADMIN))
    first = validate_success(api.withdraw_publication(
        publication["id"], {"reason": "first withdrawal"}, ADMIN))

    response = api.withdraw_publication(
        publication["id"], {"reason": "second withdrawal attempt"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_PUBLICATION_STATE_INVALID.value, 409)

    stored = read_publication(publication["id"])
    assert stored["status"] == "WITHDRAWN"
    assert stored["version"] == first["version"], (
        f"A refused withdrawal leaves the row untouched, got version {stored['version']}")


def test_assembling_a_publication_from_a_single_candidate_is_refused(api):
    """PRD 2.7: "**Priority 52 — record floor.** Guards `POST
    /citizen-science/publications` and `POST /citizen-science/publications/{id}/release`.
    At creation, the candidate set must hold at least 2 observations, counted after
    any superseded publication has released its queued observations back into the
    pool; at release, the publication's `record_count` must be at least 2. Otherwise
    `ERR_INSUFFICIENT_RECORDS` (422)."
    PRD 3.8: "Assembly requires at least 2 candidate observations to exist, counted
    after step one has returned any superseded publication's queued records to the
    pool, and a shortfall is refused with `ERR_INSUFFICIENT_RECORDS`."

    Design: Corner/calculations/publication_create_with_single_candidate_returns_insufficient_records
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observations = setup_publishable_campaign(world, accepted_count=1)
    campaign = read_campaign(world["cam1"])

    response = api.create_publication({
        "campaign_id": world["cam1"], "doi": "10.5555/cs-2026-13",
        "expected_campaign_version": campaign["version"]}, ADMIN)
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_RECORDS.value, 422)

    _rows, meta = validate_paginated(api.list_publications(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0
    stored = read_observation(observations[0]["id"])
    assert stored["publication_id"] is None
    assert stored["publication_status"] == "QUEUED"


def _released_publication_world(doi, partner_kwargs=None, embargo_until=None):
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    setup_publishable_campaign(world, accepted_count=2)
    publication = create_publication(world["cam1"], doi=doi, embargo_until=embargo_until)
    publication = validate_success(api_client.release_publication(publication["id"], ADMIN))
    partner = None
    if partner_kwargs is not None:
        partner = register_partner(**partner_kwargs)
    return world, publication, partner


def test_approving_a_grant_for_an_unapproved_partner_is_refused(api):
    """PRD 2.7: "**Priority 27 — partner standing.** Guards `POST
    /citizen-science/access-grants/{id}/approve`. The referenced partner's `status`
    must be `APPROVED`, otherwise `ERR_PARTNER_NOT_APPROVED` (409)."
    PRD 3.8: "A new partner sits in `PENDING` with `active_grant_count` at 0 and
    gains nothing until approved; approval moves a partner `PENDING → APPROVED` or
    `SUSPENDED → APPROVED`, the latter closing the reinstatement cycle `APPROVED →
    SUSPENDED → APPROVED` that a publication withdrawal can open."

    Design: Corner/errors/grant_approve_before_partner_approved_returns_partner_not_approved
    """
    world, publication, partner = _released_publication_world(
        "10.5555/cs-2026-20",
        partner_kwargs={"approved": False, "org_name": "Tundra Lab",
                        "contact_email": "data@example.org", "trust_tier": "STANDARD",
                        "data_use_agreement_signed_at": "2026-07-01T00:00:00Z"})
    grant = request_grant(publication["id"], partner["id"], "AGGREGATE")

    response = api.approve_access_grant(grant["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_PARTNER_NOT_APPROVED.value, 409)

    assert read_grant(grant["id"])["status"] == "REQUESTED"
    assert read_partner(partner["id"])["active_grant_count"] == 0


def test_the_sensitive_scope_gate_is_evaluated_before_the_agreement_gate(api):
    """PRD 2.7: "**Priority 38 — sensitive scope.** Guards `POST
    /citizen-science/access-grants/{id}/approve`. A grant whose `scope` is
    `SENSITIVE` requires the partner's `trust_tier` to be `TRUSTED`, otherwise
    `ERR_SCOPE_NOT_PERMITTED` (403)."
    PRD 2.7: "**Priority 39 — data use agreement.** Guards `POST
    /citizen-science/access-grants/{id}/approve`. A grant whose `scope` is `FULL` or
    `SENSITIVE` requires the partner's `data_use_agreement_signed_at` to be non-null,
    otherwise `ERR_DUA_NOT_SIGNED` (403)."

    Design: Corner/errors/grant_approve_scope_gate_precedes_dua_gate
    """
    world, publication, partner = _released_publication_world(
        "10.5555/cs-2026-21",
        partner_kwargs={"approved": True, "org_name": "Steppe Trust",
                        "contact_email": "data@example.org", "trust_tier": "STANDARD"})
    sensitive = request_grant(publication["id"], partner["id"], "SENSITIVE")
    full = request_grant(publication["id"], partner["id"], "FULL")

    validate_error(api.approve_access_grant(sensitive["id"], ADMIN),
                   ApiErrorId.ERR_SCOPE_NOT_PERMITTED.value, 403)
    validate_error(api.approve_access_grant(full["id"], ADMIN),
                   ApiErrorId.ERR_DUA_NOT_SIGNED.value, 403)

    assert read_grant(sensitive["id"])["status"] == "REQUESTED"
    assert read_grant(full["id"])["status"] == "REQUESTED"
    assert read_partner(partner["id"])["active_grant_count"] == 0


def test_an_embargoed_dataset_admits_only_aggregate_scope_grants(api):
    """PRD 2.7: "**Priority 47 — embargo scope.** Guards `POST
    /citizen-science/access-grants/{id}/approve`. A grant against an `EMBARGOED`
    publication may only be approved when its `scope` is `AGGREGATE`, otherwise
    `ERR_EMBARGO_ACTIVE` (409)."
    PRD 3.8: "On success the grant moves `REQUESTED → APPROVED` and the partner's
    `active_grant_count` rises by one."

    Design: Corner/errors/grant_approve_on_embargoed_publication_allows_aggregate_only
    """
    world, publication, partner = _released_publication_world(
        "10.5555/cs-2026-22", embargo_until="2026-09-01T00:00:00Z",
        partner_kwargs={"approved": True, "org_name": "Fjord Analytics",
                        "contact_email": "data@example.org", "trust_tier": "STANDARD",
                        "data_use_agreement_signed_at": "2026-07-01T00:00:00Z"})
    assert publication["status"] == "EMBARGOED"

    full = request_grant(publication["id"], partner["id"], "FULL")
    aggregate = request_grant(publication["id"], partner["id"], "AGGREGATE")

    validate_error(api.approve_access_grant(full["id"], ADMIN),
                   ApiErrorId.ERR_EMBARGO_ACTIVE.value, 409)
    approved = validate_success(api.approve_access_grant(aggregate["id"], ADMIN))

    assert approved["status"] == "APPROVED"
    assert read_partner(partner["id"])["active_grant_count"] == 1


def test_approving_an_already_approved_grant_is_refused(api):
    """PRD 2.7: "**Priority 26 — grant state.** Guards `POST
    /citizen-science/access-grants/{id}/approve` (requires `REQUESTED`) and `POST
    /citizen-science/access-grants/{id}/revoke` (requires `APPROVED`). Otherwise
    `ERR_GRANT_STATE_INVALID` (409)."
    PRD 3.8: "On success the grant moves `REQUESTED → APPROVED` and the partner's
    `active_grant_count` rises by one."

    Design: Corner/errors/grant_approve_twice_returns_grant_state_invalid
    """
    world, publication, partner = _released_publication_world(
        "10.5555/cs-2026-23",
        partner_kwargs={"approved": True, "org_name": "Kelp Consortium",
                        "contact_email": "data@example.org", "trust_tier": "STANDARD",
                        "data_use_agreement_signed_at": "2026-07-01T00:00:00Z"})
    grant = approve_grant(request_grant(publication["id"], partner["id"], "AGGREGATE")["id"])

    response = api.approve_access_grant(grant["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_GRANT_STATE_INVALID.value, 409)

    assert read_grant(grant["id"])["status"] == "APPROVED"
    assert read_partner(partner["id"])["active_grant_count"] == 1


def test_requesting_a_grant_that_has_already_expired_is_refused(api):
    """PRD 2.7: "**Priority 46 — grant expiry in the future.** Guards `POST
    /citizen-science/access-grants` and `POST /citizen-science/access-grants/{id}/approve`.
    The grant's `expires_at` must be strictly later than the logical clock, otherwise
    `ERR_GRANT_EXPIRY_IN_PAST` (422)."
    PRD 3.8: "A request names the `publication_id`, the `partner_id`, the `scope` of
    `AGGREGATE`, `FULL`, or `SENSITIVE`, and an `expires_at` instant strictly later
    than the logical clock; it lands in `REQUESTED` with `denied_reason` at `NONE`."

    Design: Corner/errors/grant_request_with_past_expiry_rejected
    """
    world, publication, partner = _released_publication_world(
        "10.5555/cs-2026-24",
        partner_kwargs={"approved": True, "org_name": "Delta Survey",
                        "contact_email": "data@example.org", "trust_tier": "STANDARD",
                        "data_use_agreement_signed_at": "2026-07-01T00:00:00Z"})

    response = api.create_access_grant({
        "publication_id": publication["id"], "partner_id": partner["id"],
        "scope": "AGGREGATE", "expires_at": "2026-08-01T00:00:00Z"}, ADMIN)
    validate_error(response, ApiErrorId.ERR_GRANT_EXPIRY_IN_PAST.value, 422)

    _rows, meta = validate_paginated(api.list_access_grants(
        ADMIN, {"partner_id": partner["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 0


def test_assembling_against_a_stale_campaign_version_is_rejected(api):
    """PRD 2.5: "Creating a publication — `POST /citizen-science/publications` —
    requires `expected_campaign_version` carrying the client's last observed `version`
    of the owning `Campaign`. A mismatch with the campaign's current `version` is
    rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412)."
    PRD 2.7: "**Priority 12 — optimistic concurrency.** Guards `POST
    /citizen-science/observations/{id}/votes`, `POST /citizen-science/equipment-loans`,
    and `POST /citizen-science/publications`. The supplied
    `expected_observation_version`, `expected_equipment_version`, or
    `expected_campaign_version` must equal the parent row's current `version`,
    otherwise `ERR_STALE_OBSERVATION_VERSION`, `ERR_STALE_EQUIPMENT_VERSION`, or
    `ERR_STALE_CAMPAIGN_VERSION` respectively (412)."

    Design: Corner/cross_cutting_layers/occ_stale_campaign_version_on_publication_create_returns_412
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    setup_publishable_campaign(world, accepted_count=2)
    stale_version = read_campaign(world["cam1"])["version"]
    first = create_publication(world["cam1"], doi="10.5555/cs-2026-30")

    response = api.create_publication({
        "campaign_id": world["cam1"], "doi": "10.5555/cs-2026-31",
        "expected_campaign_version": stale_version}, ADMIN)
    error = validate_error(response, ApiErrorId.ERR_STALE_CAMPAIGN_VERSION.value, 412)
    assert error["error_id"] != ApiErrorId.ERR_INSUFFICIENT_RECORDS.value

    assert read_publication(first["id"])["status"] == "DRAFT"
    _rows, meta = validate_paginated(api.list_publications(
        ADMIN, {"campaign_id": world["cam1"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1


def test_superseding_a_draft_returns_its_queued_records_to_the_candidate_pool(api):
    """PRD 3.8: "**Step one runs first, before anything is measured.** When the
    campaign already carries a publication in `DRAFT`, `EMBARGOED`, or `RELEASED`,
    that prior publication is superseded: it transitions to `WITHDRAWN`, and the new
    row's `supersedes_publication_id` is set to point at it."
    PRD 3.8: "The superseded publication's bound observations are treated
    asymmetrically by design — those whose `publication_status` is `QUEUED` have their
    `publication_id` cleared back to null and their `publication_status` moved `QUEUED
    → UNPUBLISHED`, which puts them straight back into the candidate pool, while those
    whose `publication_status` is `PUBLISHED` move to `WITHDRAWN` and do **not**
    re-enter, because a record that has already been released under a DOI cannot
    quietly reappear in a successor dataset."
    PRD 2.3: "Publications may be filtered by `campaign_id`,
    `supersedes_publication_id`, and `status`."

    Design: Corner/cross_cutting_layers/publication_supersede_returns_prior_observations_to_the_pool
    """
    world = build_world(stage=STAGE_OPEN, clock=CLOCK)
    observations = setup_publishable_campaign(world, accepted_count=2)
    first = create_publication(world["cam1"], doi="10.5555/cs-2026-32")

    second = create_publication(world["cam1"], doi="10.5555/cs-2026-33")

    assert second["record_count"] == 2, (
        f"Both queued records return to the pool, got {second['record_count']}")
    assert float(second["quality_floor"]) == pytest.approx(52.80, abs=1e-9)
    assert second["supersedes_publication_id"] == first["id"]
    assert read_publication(first["id"])["status"] == "WITHDRAWN"
    assert read_publication(second["id"])["status"] == "DRAFT"
    for observation in observations:
        stored = read_observation(observation["id"])
        assert stored["publication_id"] == second["id"]
        assert stored["publication_status"] == "QUEUED"

    rows, meta = validate_paginated(api.list_publications(
        ADMIN, {"supersedes_publication_id": first["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]
