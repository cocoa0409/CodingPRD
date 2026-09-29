"""Creation shapes, declared defaults, derived fields and path resolution.

These are the record-level promises the rest of the suite leans on: what a fresh
row looks like, which values the server invents when the client stays silent, and
which error a URL segment that names nothing produces.
"""

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    SCOUT_USER_ID,
    api_client,
    assert_common_fields,
    assert_instant_equals,
    assert_league,
    assert_organization,
    assert_player,
    assert_salary_ledger_balances,
    factories,
    fixtures,
    make_coaching_staff_headers,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_ops_manager_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_league_registration_echoes_every_term_and_derives_the_lock_flag():
    """All six instants and the charter numbers come back, and the lock is not yet active.

    PRD: "A league administrator registers one with a `name` of between 1 and 120 characters and six
    calendar instants: `season_start_at` and `season_end_at`, where the closing instant must be
    strictly later than the opening one; `roster_lock_at`, the instant from which roster-changing
    operations freeze; and `transfer_window_open_at` with `transfer_window_close_at`, where the
    closing instant must again be strictly later than the opening one."
    PRD: "`roster_lock_active` is true exactly when the current instant has reached `roster_lock_at`,
    and false while the current instant is still earlier than that."
    PRD: "`version` is an integer that starts at 1 and increases by exactly 1 on every mutation of
    that resource, whether the mutation was requested directly by a client or produced as a side
    effect of an operation on a different resource."

    Design: Corner/entities/league_creation_returns_every_declared_field_with_the_lock_flag_false
    """
    payload = factories.create_league_payload()
    league = validate_success(
        api_client.create_league(payload, make_league_admin_headers()), 201
    )

    assert_league(league)
    assert league["name"] == "Apex Masters League"
    for field in (
        "season_start_at",
        "season_end_at",
        "roster_lock_at",
        "transfer_window_open_at",
        "transfer_window_close_at",
    ):
        assert_instant_equals(league[field], payload[field], f"League.{field}")
    assert league["minimum_salary_cents"] == 3600000
    assert league["max_negotiation_rounds"] == 3
    assert league["player_association_levy_bp"] == 250
    assert league["roster_lock_active"] is False
    assert league["version"] == 1


def test_a_league_body_carrying_only_the_required_instants_takes_every_default():
    """Fourteen optional terms fall back to the charter values the PRD names.

    PRD: "The remaining charter terms are optional at registration and fall back to league-standard
    defaults: a `minimum_salary_cents` floor of 3,600,000 cents (thirty-six thousand dollars a year)
    which may be any value of zero or more; a `min_roster_size` of 1 and a `max_roster_size` of 7,
    both of which must be zero or more and where the maximum must be greater than or equal to the
    minimum; an `offer_response_window_hours` of 72 (three days), which must be at least 1; and a
    `max_negotiation_rounds` of 3, which must also be at least 1."
    PRD: "The association takes a levy of `player_association_levy_bp`, defaulting to 250 basis
    points, off every gross prize before anyone else is paid; it imposes a prize-split floor of
    `association_min_prize_split_bp`, defaulting to 4000 basis points; and it caps contracted
    streaming at `association_max_streaming_hours_per_week`, defaulting to 20 hours."
    PRD: "Statutory workload protections are also charter-level: `minor_max_weekly_minutes` defaults
    to 1200 minutes (twenty hours a week) and `adult_max_weekly_minutes` to 2700 minutes (forty-five
    hours), both of which must be zero or more; `education_reserved_minutes` defaults to 600 minutes
    (ten hours a week) held back for schooling; and `minor_age_threshold_years` defaults to 18 and
    must lie between 1 and 25."
    PRD: "Finally, `free_agency_cooldown_days` defaults to 14 days and must be zero or more, and
    `tryout_required_before_offer` defaults to false."

    Design: Corner/entities/league_optional_inputs_fall_back_to_their_declared_defaults
    """
    league = validate_success(
        api_client.create_league(
            factories.create_minimal_league_payload(name="Bare Minimum League"),
            make_league_admin_headers(),
        ),
        201,
    )

    assert league["minimum_salary_cents"] == 3600000
    assert league["min_roster_size"] == 1
    assert league["max_roster_size"] == 7
    assert league["offer_response_window_hours"] == 72
    assert league["max_negotiation_rounds"] == 3
    assert league["player_association_levy_bp"] == 250
    assert league["association_min_prize_split_bp"] == 4000
    assert league["association_max_streaming_hours_per_week"] == 20
    assert league["minor_max_weekly_minutes"] == 1200
    assert league["adult_max_weekly_minutes"] == 2700
    assert league["education_reserved_minutes"] == 600
    assert league["minor_age_threshold_years"] == 18
    assert league["free_agency_cooldown_days"] == 14
    assert league["tryout_required_before_offer"] is False


def test_a_new_organization_starts_with_an_empty_ledger_that_already_balances():
    """Nothing is committed yet, so the whole budget is uncommitted in both views.

    PRD: "A newly registered organization starts with `committed_salary_cents` at 0 and
    `uncommitted_salary_cents` equal to its whole `annual_salary_budget_cents`."
    PRD: "Four further counters begin at 0: `active_roster_count`, `prize_payable_cents`,
    `wellness_flag_count`, and the committed figure already mentioned."
    PRD: "`provisional_committed_cents` is the sum of `provisional_cap_charge_cents` over the
    organization's `ACTIVE` and `SUSPENDED` contracts — the same quantity the committed figure tracks
    — while `final_committed_cents` is the sum of `final_cap_charge_cents` over that same set of
    contracts."
    PRD: "Organizations are also registered by the league office, each naming its `league_id`, a
    `name` of 1 to 120 characters, a `tax_jurisdiction_code` of 2 to 8 uppercase characters, an
    `annual_salary_budget_cents` of zero or more, and optionally an `org_prize_share_bp` which
    defaults to 3500 basis points and must lie between 0 and 10000."

    Design: Corner/entities/organization_creation_starts_with_an_empty_salary_and_prize_ledger
    """
    league = fixtures.create_league()
    admin_headers = make_league_admin_headers()

    organization = validate_success(
        api_client.create_organization(
            {
                "league_id": league["id"],
                "name": "Vertex Vanguard",
                "tax_jurisdiction_code": "US-CA",
                "annual_salary_budget_cents": 50000000,
            },
            admin_headers,
        ),
        201,
    )
    assert_organization(organization)
    assert organization["league_id"] == league["id"]
    assert organization["org_prize_share_bp"] == 3500
    assert organization["committed_salary_cents"] == 0
    assert organization["uncommitted_salary_cents"] == 50000000
    assert organization["active_roster_count"] == 0
    assert organization["prize_payable_cents"] == 0
    assert organization["wellness_flag_count"] == 0
    assert organization["version"] == 1

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(organization["id"], admin_headers)
    )
    assert cap_summary["annual_salary_budget_cents"] == 50000000
    assert cap_summary["committed_salary_cents"] == 0
    assert cap_summary["uncommitted_salary_cents"] == 50000000
    assert cap_summary["provisional_committed_cents"] == 0
    assert cap_summary["final_committed_cents"] == 0
    assert_salary_ledger_balances(cap_summary)


def test_age_and_consent_are_derived_for_a_minor_and_for_an_adult():
    """The client sends only a birth date; the server decides the age, the flag and the consent.

    PRD: "`age_years` is the number of whole years between the player's `birth_date` and the current
    instant, counting an anniversary falling exactly on the current date as reached — so a player
    whose eighteenth birthday is today has `age_years` of 18."
    PRD: "`guardian_consent_status` follows directly from that derivation: it is `NOT_REQUIRED` for a
    player who is not a minor, `REQUIRED` for a minor with no consent on file, and `GRANTED` once a
    guardian has recorded consent."
    PRD: "A newly registered player's `player_status` is `PROSPECT`, and `current_organization_id`,
    `free_agency_window_ends_at` and `last_release_organization_id` all start null."
    PRD: "The registering scout's identifier is stamped into `scouted_by_user_id`."

    Design: Corner/entities/player_minor_status_fields_are_derived_from_birth_date_and_the_clock
    """
    scout_headers = make_scout_headers()

    minor = validate_success(
        api_client.create_player(
            {
                "full_name": "Mika Toivonen",
                "birth_date": "2010-02-20",
                "region_code": "FI",
                "association_member": False,
                "education_enrollment_status": "ENROLLED_FULL_TIME",
            },
            scout_headers,
        ),
        201,
    )
    adult = validate_success(
        api_client.create_player(
            {
                "full_name": "Rin Adachi",
                "birth_date": "2001-05-14",
                "region_code": "US",
                "association_member": False,
                "education_enrollment_status": "NOT_ENROLLED",
            },
            scout_headers,
        ),
        201,
    )

    assert_player(minor)
    assert_player(adult)
    assert minor["age_years"] == 16
    assert minor["is_minor"] is True
    assert minor["guardian_consent_status"] == "REQUIRED"
    assert adult["age_years"] == 25
    assert adult["is_minor"] is False
    assert adult["guardian_consent_status"] == "NOT_REQUIRED"

    for player in (minor, adult):
        assert player["player_status"] == "PROSPECT"
        assert player["current_organization_id"] is None
        assert player["free_agency_window_ends_at"] is None
        assert player["last_release_organization_id"] is None

    assert minor["guardian_name"] is None
    assert minor["guardian_email"] is None
    assert minor["guardian_weekly_cap_minutes"] is None
    assert minor["scouted_by_user_id"] == SCOUT_USER_ID


def test_the_player_listing_pages_and_filters_conjunctively():
    """Three rows, two pages, and a region filter that isolates exactly one of them.

    PRD: "The `meta` block of a list response carries `limit` and `offset` as they were applied,
    `total_count` as the number of records matching the filters before the page window is applied,
    and `has_more` as true exactly when records remain beyond the current window."
    PRD: "Players may be listed with any combination of the filters `player_status`, `region_code`,
    `current_organization_id` and `last_release_organization_id`, and an organization's roster read
    returns the players whose `current_organization_id` or `last_release_organization_id` names that
    organization, optionally narrowed by `player_status`."
    PRD: "Unless a subsection states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/entities/player_listing_reports_total_count_has_more_and_honours_region_filter
    """
    scout_headers = make_scout_headers()
    fixtures.create_player(full_name="Rin Adachi", region_code="US")
    fixtures.create_player(
        full_name="Dana Whitfield", birth_date="1999-11-02", region_code="US"
    )
    korean = fixtures.create_player(
        full_name="Ji-ho Park", birth_date="2000-07-19", region_code="KR"
    )

    first_page, first_meta = validate_paginated(
        api_client.list_players(scout_headers, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api_client.list_players(scout_headers, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False

    filtered, filtered_meta = validate_paginated(
        api_client.list_players(
            scout_headers, params={"region_code": "KR", "limit": 10, "offset": 0}
        )
    )
    assert [row["id"] for row in filtered] == [korean["id"]]
    assert filtered_meta["total_count"] == 1
    assert filtered_meta["has_more"] is False

    prospects, prospect_meta = validate_paginated(
        api_client.list_players(
            scout_headers, params={"player_status": "PROSPECT", "limit": 10, "offset": 0}
        )
    )
    assert len(prospects) == 3
    assert prospect_meta["total_count"] == 3


def test_every_path_id_segment_has_its_own_not_found_error():
    """Eleven reads against one absent identifier, eleven entity-specific 404s.

    PRD: "**Path existence** — every `{id}` segment in the URL is resolved from left to right, and
    the leftmost segment that fails to resolve determines the error."
    PRD: "An unresolvable league yields `ERR_LEAGUE_NOT_FOUND`, an organization
    `ERR_ORGANIZATION_NOT_FOUND`, a player `ERR_PLAYER_NOT_FOUND`, a contract offer
    `ERR_OFFER_NOT_FOUND`, a player contract `ERR_CONTRACT_NOT_FOUND`, a team house
    `ERR_TEAM_HOUSE_NOT_FOUND`, a practice block `ERR_PRACTICE_BLOCK_NOT_FOUND`, a sponsorship deal
    `ERR_DEAL_NOT_FOUND`, a deliverable assignment `ERR_DELIVERABLE_NOT_FOUND`, a prize distribution
    `ERR_DISTRIBUTION_NOT_FOUND` and a roster move `ERR_ROSTER_MOVE_NOT_FOUND`."
    PRD: "All of these carry HTTP 404."

    Design: Corner/entities/every_path_id_segment_has_its_own_not_found_error
    """
    admin_headers = make_league_admin_headers()
    probes = [
        (api_client.get_league(MISSING_UUID, admin_headers), ApiErrorId.ERR_LEAGUE_NOT_FOUND),
        (
            api_client.get_organization(MISSING_UUID, admin_headers),
            ApiErrorId.ERR_ORGANIZATION_NOT_FOUND,
        ),
        (api_client.get_player(MISSING_UUID, make_scout_headers()), ApiErrorId.ERR_PLAYER_NOT_FOUND),
        (
            api_client.get_contract_offer(MISSING_UUID, admin_headers),
            ApiErrorId.ERR_OFFER_NOT_FOUND,
        ),
        (api_client.get_contract(MISSING_UUID, admin_headers), ApiErrorId.ERR_CONTRACT_NOT_FOUND),
        (
            api_client.get_team_house(MISSING_UUID, make_ops_manager_headers(MISSING_UUID)),
            ApiErrorId.ERR_TEAM_HOUSE_NOT_FOUND,
        ),
        (
            api_client.get_practice_block(MISSING_UUID, make_coaching_staff_headers()),
            ApiErrorId.ERR_PRACTICE_BLOCK_NOT_FOUND,
        ),
        (
            api_client.get_sponsorship_deal(MISSING_UUID, admin_headers),
            ApiErrorId.ERR_DEAL_NOT_FOUND,
        ),
        (
            api_client.get_deliverable_assignment(
                MISSING_UUID, make_sponsorship_manager_headers(MISSING_UUID)
            ),
            ApiErrorId.ERR_DELIVERABLE_NOT_FOUND,
        ),
        (
            api_client.get_prize_distribution(MISSING_UUID, make_finance_officer_headers()),
            ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND,
        ),
        (
            api_client.get_roster_move(MISSING_UUID, admin_headers),
            ApiErrorId.ERR_ROSTER_MOVE_NOT_FOUND,
        ),
    ]

    for response, expected in probes:
        validate_error(response, expected.value, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_a_dangling_body_key_is_reported_before_the_rules_the_same_body_breaks():
    """Band 6 resolves league, player and house ids from the body ahead of bands 9, 11 and 13.

    PRD: "Checks are grouped into thirteen precedence bands, evaluated in ascending order; **the first
    violated band determines the response, and no later band runs**."
    PRD: "**Foreign keys in the body or query** — a `league_id` that does not resolve yields
    `ERR_LEAGUE_NOT_FOUND`; an `organization_id` or `transfer_to_organization_id` that does not resolve
    yields `ERR_ORGANIZATION_NOT_FOUND`; a `player_id`, or any single entry of
    `participant_player_ids`, that does not resolve yields `ERR_PLAYER_NOT_FOUND`; a `contract_id` that
    does not resolve yields `ERR_CONTRACT_NOT_FOUND`; a `team_house_id` that does not resolve yields
    `ERR_TEAM_HOUSE_NOT_FOUND`; and a `supersedes_offer_id` that either does not resolve or names an
    offer belonging to a different player or a different organization yields `ERR_OFFER_NOT_FOUND`."
    PRD: "Band 6 applies to offer creation, practice-block creation, sponsorship-deal creation,
    prize-distribution creation, organization registration, roster-move filing and deliverable
    placement — wherever those keys appear."
    PRD: "And the fiscal checks sit last, so a booking or a signing that is simultaneously unsafe for a
    minor and unaffordable for the organization reports the safety failure, not the money failure."

    Design: Corner/entities/body_foreign_keys_are_resolved_before_any_business_rule_returns_404
    """
    ctx = fixtures.setup_league_and_org()
    house = fixtures.create_team_house(ctx["org"]["id"])
    player = fixtures.create_player()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    coach_headers = make_coaching_staff_headers()

    validate_error(
        api_client.create_organization(
            {
                "league_id": MISSING_UUID,
                "name": "Ghost Org",
                "tax_jurisdiction_code": "US-CA",
                "annual_salary_budget_cents": 50000000,
            },
            make_league_admin_headers(),
        ),
        ApiErrorId.ERR_LEAGUE_NOT_FOUND.value,
        404,
    )

    validate_error(
        api_client.create_contract_offer(
            {
                "organization_id": ctx["org"]["id"],
                "player_id": MISSING_UUID,
                "base_salary_cents": 1000,
                "term_months": 12,
                "prize_split_player_pct_bp": 4000,
                "streaming_hours_per_week": 10,
                "tax_residency_code": "US-CA",
            },
            gm_headers,
        ),
        ApiErrorId.ERR_PLAYER_NOT_FOUND.value,
        404,
    )

    validate_error(
        api_client.create_practice_block(
            {
                "organization_id": ctx["org"]["id"],
                "team_house_id": MISSING_UUID,
                "block_type": "TRYOUT",
                "starts_at": "2026-08-02T10:00:00Z",
                "ends_at": "2026-08-02T14:00:00Z",
                "participant_player_ids": [player["id"]],
            },
            coach_headers,
        ),
        ApiErrorId.ERR_TEAM_HOUSE_NOT_FOUND.value,
        404,
    )

    validate_error(
        api_client.create_practice_block(
            {
                "organization_id": ctx["org"]["id"],
                "team_house_id": house["id"],
                "block_type": "TRYOUT",
                "starts_at": "2026-08-02T10:00:00Z",
                "ends_at": "2026-08-02T14:00:00Z",
                "participant_player_ids": [MISSING_UUID],
            },
            coach_headers,
        ),
        ApiErrorId.ERR_PLAYER_NOT_FOUND.value,
        404,
    )

    validate_error(
        api_client.create_deliverable_assignment(
            MISSING_UUID,
            {
                "contract_id": MISSING_UUID,
                "deliverable_type": "SOCIAL_POST",
                "due_at": "2026-08-20T00:00:00Z",
                "expected_deal_version": 1,
            },
            make_sponsorship_manager_headers(MISSING_UUID),
        ),
        ApiErrorId.ERR_DEAL_NOT_FOUND.value,
        404,
    )

    _players, player_meta = validate_paginated(api_client.list_players(make_scout_headers()))
    assert player_meta["total_count"] == 1
    _blocks, block_meta = validate_paginated(api_client.list_practice_blocks(coach_headers))
    assert block_meta["total_count"] == 0
    _offers, offer_meta = validate_paginated(api_client.list_contract_offers(gm_headers))
    assert offer_meta["total_count"] == 0


def test_a_team_house_needs_a_real_parent_and_inherits_its_key_from_the_path():
    """The orphan create is a 404; the real one copies the path key and takes both defaults.

    PRD: "Facilities belong to an organization and are opened by its operations manager as a nested
    creation, so the new facility's `organization_id` comes from the path rather than the body."
    PRD: "A team house is described by a `name` of 1 to 120 characters, a `timezone` carrying an IANA
    timezone label which is metadata only — every instant in this API remains UTC — an optional
    `turnaround_buffer_minutes` between 0 and 720 defaulting to 60, and an optional
    `concurrent_seat_capacity` of at least 1 defaulting to 10."
    PRD: "An organization's facilities are reachable as a nested read, and a single facility read
    returns its buffer and capacity."

    Design: Corner/entities/team_house_creation_needs_a_live_parent_organization_and_applies_defaults
    """
    ctx = fixtures.setup_league_and_org()
    ops_headers = make_ops_manager_headers(ctx["org"]["id"])

    validate_error(
        api_client.create_team_house(
            MISSING_UUID,
            {"name": "Orphan House", "timezone": "America/Los_Angeles"},
            make_ops_manager_headers(MISSING_UUID),
        ),
        ApiErrorId.ERR_ORGANIZATION_NOT_FOUND.value,
        404,
    )

    house = validate_success(
        api_client.create_team_house(
            ctx["org"]["id"],
            {"name": "Vanguard House", "timezone": "America/Los_Angeles"},
            ops_headers,
        ),
        201,
    )
    assert_common_fields(house)
    assert house["organization_id"] == ctx["org"]["id"]
    assert house["turnaround_buffer_minutes"] == 60
    assert house["concurrent_seat_capacity"] == 10
    assert house["timezone"] == "America/Los_Angeles"
    assert house["version"] == 1

    rows, meta = validate_paginated(
        api_client.list_organization_team_houses(
            ctx["org"]["id"], ops_headers, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [house["id"]]


def test_six_shape_violations_all_report_the_same_malformed_request_error():
    """A missing field, a bad enum, a zero-length interval, a duplicate, a stray basis point and a page.

    PRD: "**Request shape** — required body fields present; every enum-typed value inside its declared
    value set; every integer inside its declared range; every basis-point field between 0 and 10000
    inclusive; `ends_at` strictly after `starts_at` on a practice block and on a sponsorship deal;
    `participant_player_ids` non-empty and free of duplicate entries; a manual block cancellation
    supplying `cancel_reason` equal to `COACH_CANCELLED`; a `decision` field equal to either `APPROVE`
    or `REJECT`; and pagination inside the bounds of §2.3."
    PRD: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed request and is refused
    with `ERR_INVALID_REQUEST` (HTTP 400) rather than being silently clamped."
    PRD: "Four further attributes are optional at registration: `association_member`, which defaults to
    false and declares whether player-association terms bind this player's contracts; `guardian_name`
    and `guardian_email`, which default to null and may be recorded at scouting time or later;
    `guardian_weekly_cap_minutes`, which defaults to null and, when present, must be zero or more; and
    `education_enrollment_status`, which defaults to `NOT_ENROLLED` and may otherwise be
    `ENROLLED_PART_TIME` or `ENROLLED_FULL_TIME`."

    Design: Corner/entities/malformed_bodies_and_bad_enums_return_invalid_request
    """
    ctx = fixtures.setup_league_and_org()
    house = fixtures.create_team_house(ctx["org"]["id"])
    player = fixtures.create_player()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])
    sponsor_headers = make_sponsorship_manager_headers(ctx["org"]["id"])
    coach_headers = make_coaching_staff_headers()
    scout_headers = make_scout_headers()

    validate_error(
        api_client.create_contract_offer(
            {
                "organization_id": ctx["org"]["id"],
                "player_id": player["id"],
                "term_months": 12,
                "prize_split_player_pct_bp": 4000,
                "streaming_hours_per_week": 10,
                "tax_residency_code": "US-CA",
            },
            gm_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api_client.create_player(
            {
                "full_name": "Ivo Marek",
                "birth_date": "2004-07-07",
                "region_code": "CZ",
                "education_enrollment_status": "HOMESCHOOLED",
            },
            scout_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api_client.create_sponsorship_deal(
            {
                "organization_id": ctx["org"]["id"],
                "sponsor_name": "Voltade",
                "exclusivity_category": "ENERGY_DRINK",
                "total_fee_cents": 1000000,
                "deliverable_count_required": 2,
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-01T00:00:00Z",
            },
            sponsor_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api_client.create_practice_block(
            {
                "organization_id": ctx["org"]["id"],
                "team_house_id": house["id"],
                "block_type": "TRYOUT",
                "starts_at": "2026-08-02T10:00:00Z",
                "ends_at": "2026-08-02T14:00:00Z",
                "participant_player_ids": [player["id"], player["id"]],
            },
            coach_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api_client.create_contract_offer(
            {
                "organization_id": ctx["org"]["id"],
                "player_id": player["id"],
                "base_salary_cents": 12500000,
                "term_months": 12,
                "prize_split_player_pct_bp": 12000,
                "streaming_hours_per_week": 10,
                "tax_residency_code": "US-CA",
            },
            gm_headers,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api_client.list_players(scout_headers, params={"limit": 250, "offset": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _offers, offer_meta = validate_paginated(api_client.list_contract_offers(gm_headers))
    assert offer_meta["total_count"] == 0
    _deals, deal_meta = validate_paginated(api_client.list_sponsorship_deals(sponsor_headers))
    assert deal_meta["total_count"] == 0
    _blocks, block_meta = validate_paginated(api_client.list_practice_blocks(coach_headers))
    assert block_meta["total_count"] == 0
    _players, player_meta = validate_paginated(api_client.list_players(scout_headers))
    assert player_meta["total_count"] == 1


def test_audit_identifiers_are_stamped_and_the_parent_version_keeps_climbing():
    """Three different callers leave three different stamps, and the organization advances 1 -> n -> n+1.

    PRD: "`version` is an integer that starts at 1 and increases by exactly 1 on every mutation of that
    resource, whether the mutation was requested directly by a client or produced as a side effect of
    an operation on a different resource."
    PRD: "The registering scout's identifier is stamped into `scouted_by_user_id`."
    PRD: "The acceptance of an offer records the accepting caller in `signed_by_user_id` on the contract
    it creates."
    PRD: "The move is created with `move_status` of `PENDING`, its `requested_by_user_id` stamped from
    the filing manager, its `approved_by_user_id`, `decision_note` and `reversal_reason` null, and its
    five money fields — `buyout_credit_cents`, `commission_tier_bp`, `agent_commission_cents`,
    `net_to_org_cents` and `released_cap_cents` — all at 0."
    PRD: "Organizations may be listed with an optional `league_id` filter, and the league office may
    later adjust an organization's `annual_salary_budget_cents` or `org_prize_share_bp`, after which the
    uncommitted figure is recomputed and the organization's `version` advances."

    Design: Corner/entities/system_fields_are_server_minted_and_version_advances_on_every_write
    """
    ctx = fixtures.setup_signed_player()
    admin_headers = make_league_admin_headers()
    gm_headers = make_general_manager_headers(ctx["org"]["id"])

    assert ctx["org"]["version"] == 1
    after_acceptance = validate_success(
        api_client.get_organization(ctx["org"]["id"], admin_headers)
    )
    assert after_acceptance["version"] > 1
    assert after_acceptance["committed_salary_cents"] == 12328767

    player = validate_success(api_client.get_player(ctx["player"]["id"], make_scout_headers()))
    assert player["scouted_by_user_id"] == SCOUT_USER_ID
    assert ctx["contract"]["signed_by_user_id"] == ctx["player"]["id"]
    assert ctx["contract"]["version"] == 1
    assert_common_fields(ctx["contract"])

    patched = validate_success(
        api_client.update_organization(
            ctx["org"]["id"], {"annual_salary_budget_cents": 60000000}, admin_headers
        )
    )
    assert patched["version"] > after_acceptance["version"]
    assert patched["annual_salary_budget_cents"] == 60000000
    assert patched["uncommitted_salary_cents"] == 47671233

    move = validate_success(
        api_client.create_roster_move(
            {
                "organization_id": ctx["org"]["id"],
                "player_id": ctx["player"]["id"],
                "move_type": "RELEASE",
                "contract_id": ctx["contract"]["id"],
                "expected_organization_version": patched["version"],
            },
            gm_headers,
        ),
        201,
    )
    assert move["move_status"] == "PENDING"
    assert move["requested_by_user_id"] == ctx["org"]["id"]
    assert move["approved_by_user_id"] is None
    assert move["released_cap_cents"] == 0
