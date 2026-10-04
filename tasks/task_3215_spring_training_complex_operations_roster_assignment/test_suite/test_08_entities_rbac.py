"""Corner coverage: entity contracts, defaults, uniqueness and role denials.

Each test here exercises a declarative claim made by the PRD's own prose
rather than a workflow rule.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    assign_player,
    create_agreement,
    create_complex,
    create_workout_group,
    field_maintenance,
    fresh_group_version,
    get_complex,
    get_player,
    onboard_player,
    open_roster_record,
    register_player,
    set_test_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_complex_create_returns_every_derived_field_at_its_starting_value():
    """PRD 3.1: "A newly created complex starts with `field_maintenance_status`
    at `OPEN`, `facility_posture` at `NORMAL`, `maintenance_block_units` at 0 and
    `posture_sweep_index` at 0"

    Design: Corner/entities/complex_create_returns_every_declared_field_and_starts_normal
    """
    set_test_clock()
    complex_ = validate_success(api_client.create_complex(
        {"name": "Cubs Mesa Complex", "host_city": "Mesa", "season_split_track": "DEDICATED",
         "timezone": "America/Phoenix", "facility_capacity_units": 200},
        TEST_USERS["platform_admin_headers"]), 201)

    assert complex_["name"] == "Cubs Mesa Complex"
    assert complex_["host_city"] == "Mesa"
    assert complex_["field_maintenance_status"] == "OPEN"
    assert complex_["facility_posture"] == "NORMAL"
    assert complex_["maintenance_block_units"] == 0
    assert complex_["posted_occupancy_units"] == 0
    assert complex_["posture_sweep_index"] == 0
    assert complex_["version"] == 1
    assert complex_["id"] and complex_["created_at"] and complex_["updated_at"]


def test_player_get_round_trips_every_stored_field_and_its_defaults():
    """PRD 3.2: "Player records are created with `full_name`, `idp_number`,
    `position_code`, `acquisition_channel`, `home_country` and `home_complex_id`,
    plus optional `mlb_service_days` and `minor_league_option_years_used`."

    Design: Corner/entities/player_get_round_trips_every_stored_field
    """
    set_test_clock()
    complex_ = create_complex()
    created = validate_success(api_client.create_player(
        {"full_name": "Hector Villalobos", "idp_number": "IDP-60101", "position_code": "C",
         "acquisition_channel": "TRADE", "home_country": "Venezuela",
         "home_complex_id": complex_["id"]},
        TEST_USERS["roster_manager_headers"]), 201)

    fetched = get_player(created["id"])
    assert fetched["full_name"] == "Hector Villalobos"
    assert fetched["idp_number"] == "IDP-60101"
    assert fetched["position_code"] == "C"
    assert fetched["acquisition_channel"] == "TRADE"
    assert fetched["mlb_service_days"] == 0
    assert fetched["minor_league_option_years_used"] == 0
    assert fetched["clearance_status"] == "PENDING"
    assert fetched["home_country"] == "Venezuela"
    assert fetched["home_complex_id"] == complex_["id"]


def test_players_list_paginates_and_counts_the_whole_filtered_set():
    """PRD 2.3: "`total_count` is the number of records matching the filter
    across all pages, not merely the number on the current page, and `has_more`
    states whether any records remain beyond the current window."

    Design: Corner/entities/players_list_paginates_and_counts_the_whole_filtered_set
    """
    set_test_clock()
    complex_ = create_complex()
    for i in range(3):
        register_player(complex_["id"], full_name=f"Page {i}", idp_number=f"IDP-6020{i}")

    page_one, meta_one = validate_paginated(api_client.list_players(
        TEST_USERS["roster_manager_headers"], params={"limit": 2, "offset": 0}))
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(api_client.list_players(
        TEST_USERS["roster_manager_headers"], params={"limit": 2, "offset": 2}))
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False


def test_unknown_complex_id_returns_resource_not_found():
    """PRD 2.7: "A path resource that does not exist yields
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/unknown_complex_id_returns_resource_not_found
    """
    set_test_clock()
    resp = api_client.get_complex(NON_EXISTENT_UUID, TEST_USERS["complex_director_headers"])
    error = validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    assert error["message"]


def test_player_create_missing_a_required_field_is_refused():
    """PRD 2.9: "Structural validity last: a missing required body field or a
    structurally invalid value ... is `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/player_create_missing_required_field_returns_invalid_request
    """
    set_test_clock()
    complex_ = create_complex()
    validate_error(
        api_client.create_player(
            {"full_name": "No Idp", "position_code": "OF", "acquisition_channel": "DRAFT_PICK",
             "home_country": "United States", "home_complex_id": complex_["id"]},
            TEST_USERS["roster_manager_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    data, meta = validate_paginated(api_client.list_players(TEST_USERS["roster_manager_headers"]))
    assert meta["total_count"] == 0


def test_an_undeclared_position_code_is_refused():
    """PRD 3.2: "The position code is one of `P`, `C`, `INF`, `OF` or `DH`"

    Design: Corner/entities/invalid_position_code_and_negative_option_years_are_rejected
    """
    set_test_clock()
    complex_ = create_complex()
    validate_error(
        api_client.create_player(
            {"full_name": "Bad Position", "idp_number": "IDP-60501", "position_code": "GOALKEEPER",
             "acquisition_channel": "DRAFT_PICK", "home_country": "United States",
             "home_complex_id": complex_["id"]},
            TEST_USERS["roster_manager_headers"]),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    data, meta = validate_paginated(api_client.list_players(TEST_USERS["roster_manager_headers"]))
    assert meta["total_count"] == 0


def test_an_omitted_season_split_track_defaults_to_shared():
    """PRD 3.1: "The season split track defaults to `SHARED`, meaning major and
    minor league camps co-tenure the facility"

    Design: Corner/entities/omitting_player_optional_fields_applies_the_declared_defaults
    """
    set_test_clock()
    complex_ = validate_success(api_client.create_complex(
        {"name": "Default Complex", "host_city": "Mesa", "timezone": "America/Phoenix",
         "facility_capacity_units": 50},
        TEST_USERS["platform_admin_headers"]), 201)
    assert complex_["season_split_track"] == "SHARED"


def test_roster_records_are_reachable_through_both_reverse_forms():
    """PRD 2.7: "Where this document describes an operation as scoped to a
    nested path, the path parameters are validated strictly left to right."

    Design: Corner/entities/roster_records_are_discovered_through_both_reverse_reachability_forms
    """
    set_test_clock()
    complex_ = create_complex()
    player = register_player(complex_["id"])
    record = open_roster_record(player["id"])

    nested = validate_success(api_client.list_player_roster_records(
        player["id"], TEST_USERS["roster_manager_headers"]))
    filtered = validate_success(api_client.list_roster_records(
        TEST_USERS["roster_manager_headers"], params={"player_id": player["id"]}))

    assert len(nested) == 1 and len(filtered) == 1
    assert nested[0]["id"] == record["id"] == filtered[0]["id"]
    assert nested[0]["player_id"] == player["id"]
    assert nested[0]["current_roster_status"] == "NRI"


def test_a_workout_group_opens_forming_with_its_normalized_tag():
    """PRD 3.5: "its `assignment_group_tag` is derived by normalizing the
    `group_name` to upper snake case"

    Design: Corner/state_machines/workout_group_create_starts_in_forming
    """
    set_test_clock()
    complex_ = create_complex()
    group = validate_success(api_client.create_workout_group(
        complex_["id"],
        {"complex_id": complex_["id"], "roster_bucket": "MAJOR",
         "group_name": "Pitchers Group A", "facility_kind": "FIELD", "capacity_units": 40},
        TEST_USERS["complex_director_headers"]), 201)

    assert group["group_status"] == "FORMING"
    assert group["assigned_units"] == 0
    assert group["assignment_group_tag"] == "PITCHERS_GROUP_A"
    assert group["version"] == 1


def test_a_duplicate_idp_number_is_rejected_across_the_whole_player_table():
    """PRD 3.2: "The `idp_number` is unique across all players without regard to
    scope — a duplicate, even for a player on a different complex, is refused with
    `ERR_DUPLICATE_IDP_NUMBER` (HTTP 409)."

    Design: Corner/validations/duplicate_idp_number_is_rejected_across_the_whole_player_table
    """
    set_test_clock()
    first_complex = create_complex(name="Cubs Mesa Complex")
    second_complex = create_complex(name="Cubs Riverview Complex")
    register_player(first_complex["id"], idp_number="IDP-61601")

    validate_error(
        api_client.create_player(
            {"full_name": "Duplicate Idp", "idp_number": "IDP-61601", "position_code": "P",
             "acquisition_channel": "NRI_ASSIGNMENT", "home_country": "United States",
             "home_complex_id": second_complex["id"]},
            TEST_USERS["roster_manager_headers"]),
        ApiErrorId.ERR_DUPLICATE_IDP_NUMBER,
    )
    _data, meta = validate_paginated(api_client.list_players(TEST_USERS["roster_manager_headers"]))
    assert meta["total_count"] == 1


def test_an_assignment_beyond_group_capacity_is_rejected():
    """PRD 3.5: "the create must not push the group's `assigned_units` above its
    `capacity_units` (a create that would is refused with
    `ERR_GROUP_CAPACITY_EXCEEDED`, HTTP 409)."

    Design: Corner/validations/assignment_create_beyond_group_capacity_is_rejected
    """
    set_test_clock()
    complex_ = create_complex()
    first = register_player(complex_["id"])
    second = register_player(complex_["id"])
    group = create_workout_group(complex_["id"], capacity_units=1)
    assign_player(group["id"], first["id"])

    validate_error(
        api_client.create_assignment(
            group["id"],
            {"workout_group_id": group["id"], "player_id": second["id"],
             "roster_bucket": "MAJOR", "assignment_kind": "ACTIVE_WORKOUT",
             "expected_group_version": fresh_group_version(group["id"])},
            TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_GROUP_CAPACITY_EXCEEDED,
    )
    assert api_client.get_workout_group(
        group["id"], TEST_USERS["complex_director_headers"]).json()["data"]["assigned_units"] == 1


def test_an_assignment_bucket_that_differs_from_its_group_is_rejected():
    """PRD 3.5: "the assignment's `roster_bucket` must equal the owning group's
    own `roster_bucket` (an assignment whose bucket differs is refused with
    `ERR_BUCKET_MISMATCH`, HTTP 422)"

    Design: Corner/validations/assignment_bucket_must_match_the_owning_group_bucket
    """
    set_test_clock()
    complex_ = create_complex()
    player = register_player(complex_["id"])
    group = create_workout_group(complex_["id"], roster_bucket="MAJOR")

    validate_error(
        api_client.create_assignment(
            group["id"],
            {"workout_group_id": group["id"], "player_id": player["id"],
             "roster_bucket": "MINOR", "assignment_kind": "ACTIVE_WORKOUT",
             "expected_group_version": fresh_group_version(group["id"])},
            TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_BUCKET_MISMATCH,
    )
    assert api_client.get_workout_group(
        group["id"], TEST_USERS["complex_director_headers"]).json()["data"]["assigned_units"] == 0


def test_an_unresolvable_body_reference_is_distinguishable_from_a_path_404():
    """PRD 2.7: "A body-supplied identifier that fails to resolve to any declared
    entity is a different failure and yields `ERR_FOREIGN_KEY_NOT_FOUND` (HTTP
    404); this code is distinct from the path-level 404"

    Design: Corner/validations/unresolvable_foreign_key_on_assignment_create_returns_foreign_key_not_found
    """
    set_test_clock()
    complex_ = create_complex()
    group = create_workout_group(complex_["id"])

    validate_error(
        api_client.create_assignment(
            group["id"],
            {"workout_group_id": group["id"], "player_id": NON_EXISTENT_UUID,
             "roster_bucket": "MAJOR", "assignment_kind": "ACTIVE_WORKOUT",
             "expected_group_version": fresh_group_version(group["id"])},
            TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_FOREIGN_KEY_NOT_FOUND,
    )
    validate_error(
        api_client.get_workout_group(NON_EXISTENT_UUID, TEST_USERS["complex_director_headers"]),
        ApiErrorId.ERR_RESOURCE_NOT_FOUND,
    )


def test_a_stale_group_version_on_assignment_create_is_refused():
    """PRD 2.8: "If the group has advanced since the client last read it — for
    instance because a withdrawal just freed a seat and legitimately changed the
    group's capacity position — the create is refused with `ERR_STALE_VERSION` at
    HTTP 412"

    Design: Corner/errors/stale_group_version_on_assignment_create_returns_precondition_failed
    """
    set_test_clock()
    complex_ = create_complex()
    player = register_player(complex_["id"])
    group = create_workout_group(complex_["id"])
    observed = group["version"]
    validate_success(api_client.disband_group(group["id"], TEST_USERS["complex_director_headers"]))

    validate_error(
        api_client.create_assignment(
            group["id"],
            {"workout_group_id": group["id"], "player_id": player["id"],
             "roster_bucket": "MAJOR", "assignment_kind": "ACTIVE_WORKOUT",
             "expected_group_version": observed},
            TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_STALE_VERSION,
    )


def test_a_stale_invitation_version_on_arrangement_confirm_is_refused():
    """PRD 2.8: "If the invitation has advanced since the client last read it —
    for instance because its letter was just sent or the player has just arrived
    ... the confirmation is refused with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/errors/stale_invitation_version_on_arrangement_confirm_returns_precondition_failed
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False)
    invitation = validate_success(api_client.create_invitation(
        onboarded["player"]["id"],
        {"player_id": onboarded["player"]["id"], "invitation_kind": "CAMP_INVITEE"},
        TEST_USERS["travel_coordinator_headers"]), 201)
    observed = invitation["version"]
    validate_success(api_client.send_letter(
        invitation["id"], TEST_USERS["travel_coordinator_headers"]))

    validate_error(
        api_client.create_travel_arrangement(
            invitation["id"],
            {"camp_invitation_id": invitation["id"], "mode": "AIR", "travel_radius_miles": 300,
             "departure_at": "2026-01-20T00:00:00Z", "travel_cost_cents": 50000, "confirm": True,
             "expected_invitation_version": observed},
            TEST_USERS["travel_coordinator_headers"]),
        ApiErrorId.ERR_STALE_VERSION,
    )
    refreshed = validate_success(api_client.list_invitations(
        TEST_USERS["travel_coordinator_headers"], params={"player_id": onboarded["player"]["id"]}))[0]
    assert refreshed["travel_arrangement_status"] == "NOT_ARRANGED"


def test_the_analytics_role_cannot_perform_a_mutating_operation():
    """PRD 2.1: "When both headers are present and well formed but the named role
    is not among the roles the target operation permits, the refusal is
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/analytics_role_cannot_perform_any_mutating_operation
    """
    set_test_clock()
    complex_ = create_complex()
    validate_error(
        api_client.field_maintenance(
            complex_["id"], "CLOSED", TEST_USERS["analytics_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    assert get_complex(complex_["id"])["field_maintenance_status"] == "OPEN"


def test_a_field_coordinator_cannot_create_a_community_agreement():
    """PRD 3.1: "Each complex may host a stadium lease agreement created by a
    `CommunityLiaison` — the `CommunityLiaison` and the `PlatformAdmin` are both
    permitted here."

    Design: Corner/rbac/field_coordinator_cannot_create_a_community_agreement
    """
    set_test_clock()
    complex_ = create_complex()
    payload = {"complex_id": complex_["id"], "stadium_name": "Sloan Park",
               "lease_start_date": "2026-01-01T00:00:00Z",
               "lease_end_date": "2026-03-31T23:59:59Z",
               "annual_rent_cents": 250000, "sponsorship_minor_league_base_cents": 100000,
               "sponsorship_major_league_base_cents": 250000, "ticket_price_cents": 400,
               "ticket_sellout_capacity": 120}
    validate_error(
        api_client.create_agreement(payload, TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api_client.create_workout_group(
            complex_["id"],
            {"complex_id": complex_["id"], "roster_bucket": "MAJOR",
             "group_name": "Pitchers Group A", "facility_kind": "FIELD", "capacity_units": 40},
            TEST_USERS["community_liaison_headers"]),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def test_an_undeclared_role_is_refused_before_any_business_check():
    """PRD 2.9: "Authentication first: missing or unrecognized credentials are
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.1: "a role string that differs in case or spacing is not recognized and
    falls to `ERR_UNAUTHENTICATED` rather than `ERR_UNAUTHORIZED`."

    Design: Corner/validations/missing_role_header_is_rejected_before_any_business_check
    """
    set_test_clock()
    complex_ = create_complex()
    from test_helpers import build_user_headers
    validate_error(
        api_client.field_maintenance(
            complex_["id"], "FIELD_RESTRICTED",
            build_user_headers("someone", "GroundskeeperUnknown")),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
    assert get_complex(complex_["id"])["field_maintenance_status"] == "OPEN"
    assert get_complex(complex_["id"])["facility_posture"] == "NORMAL"


def test_ticketing_cannot_open_while_the_agreement_is_still_draft():
    """PRD 3.7: "A `CommunityLiaison` opens ticketing on a record only when the
    owning agreement is `ACTIVE` — otherwise `ERR_AGREEMENT_NOT_ACTIVE` (HTTP
    409)"

    Design: Corner/validations/ticketing_cannot_open_while_the_agreement_is_still_draft
    """
    set_test_clock()
    complex_ = create_complex()
    agreement = create_agreement(complex_["id"])
    record = validate_success(api_client.open_host_community_record(
        agreement["id"], TEST_USERS["community_liaison_headers"]), 201)

    validate_error(
        api_client.open_ticketing(record["id"], TEST_USERS["community_liaison_headers"]),
        ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE,
    )
    assert api_client.get_host_community_record(
        record["id"], TEST_USERS["community_liaison_headers"]
    ).json()["data"]["ticketing_status"] == "NOT_OPEN"

    validate_success(api_client.activate_agreement(
        agreement["id"], TEST_USERS["community_liaison_headers"]))
    opened = validate_success(api_client.open_ticketing(
        record["id"], TEST_USERS["community_liaison_headers"]))
    assert opened["ticketing_status"] == "ON_SALE"