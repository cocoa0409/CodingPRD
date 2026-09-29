"""What a create returns, what it defaults, and what it refuses to accept.

Every resource in this service publishes computed fields the client never sends,
defaults the client may omit, and closed enumerations the client may not widen.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_BRANCH_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERROR_HTTP_STATUS,
)
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_common_fields,
    assert_instant_equals,
    assert_object_envelope,
    assert_lot_conservation,
    assert_program_status,
)
from test_helpers.factories import (
    branch_payload,
    program_payload,
    reservation_payload,
)
from test_helpers.fixtures import LibraryWorld


class TestBranchResource:
    """The branch is the root of the topology and carries one roll-up counter."""

    def test_a_new_branch_publishes_a_zero_over_budget_counter(
        self, world: LibraryWorld
    ) -> None:
        """The roll-up is present and 0, neither null nor absent.

        "A newly created branch reports `programs_over_budget_count` as 0; that
        field is a roll-up the branch never accepts as input, and it is recomputed
        only when one of the branch's programs changes its budget posture."

        Design: Corner/entities/branch_creation_returns_all_declared_fields_with_zero_over_budget_counter
        """
        world.pin_clock()

        response = world.api.create_branch(
            branch_payload(
                name="Central Library",
                branch_code="CEN",
                overlapping_program_capacity=2,
                per_program_fee_cap_cents=150000,
            ),
            world.manager,
        )
        branch = get_success_data(response, 201)

        assert branch["name"] == "Central Library"
        assert branch["branch_code"] == "CEN"
        assert branch["overlapping_program_capacity"] == 2
        assert branch["per_program_fee_cap_cents"] == 150000
        assert branch["programs_over_budget_count"] == 0
        assert_common_fields(branch, expected_version=1)
        assert_object_envelope(response)

    def test_reading_the_branch_back_reproduces_every_stored_value(
        self, world: LibraryWorld
    ) -> None:
        """A read introduces no re-derivation drift in the counter.

        "`per_program_fee_cap_cents`, a non-negative ceiling on what any single
        program at this branch may pay one presenter."

        Design: Corner/entities/branch_retrieval_by_id_returns_the_stored_branch_unchanged
        """
        created = world.branch(
            name="Central Library",
            branch_code="CEN",
            overlapping_program_capacity=2,
            per_program_fee_cap_cents=150000,
        )

        response = world.api.get_branch(created["id"], world.officer)
        branch = get_success_data(response, 200)

        assert branch["branch_code"] == "CEN"
        assert branch["per_program_fee_cap_cents"] == 150000
        assert branch["programs_over_budget_count"] == 0
        assert_object_envelope(response)


class TestRoomResource:
    """A room is created inside its branch and defaults its own status."""

    def test_an_omitted_status_defaults_to_available_and_the_branch_comes_from_the_path(
        self, world: LibraryWorld
    ) -> None:
        """Neither the status nor the owning branch needs to be sent.

        "Rooms belong to a branch and are created inside it, so a room's
        `branch_id` is taken from the creation path and any `branch_id` in the
        body is ignored." "A room's `status` is either `AVAILABLE` or
        `OUT_OF_SERVICE` and defaults to `AVAILABLE` when the creating request
        omits it".

        Design: Corner/entities/room_creation_defaults_status_to_available_and_takes_branch_id_from_the_path
        """
        branch = world.branch()

        response = world.api.create_room(
            branch["id"],
            {
                "room_name": "Story Room",
                "capacity_seats": 60,
                "min_setup_minutes": 15,
                "min_teardown_minutes": 15,
            },
            world.manager,
        )
        room = get_success_data(response, 201)

        assert room["status"] == "AVAILABLE"
        assert room["branch_id"] == branch["id"]
        assert room["accessibility_features"] == []
        assert_common_fields(room)

    def test_a_room_without_a_capacity_is_refused_and_not_created(
        self, world: LibraryWorld
    ) -> None:
        """The seated capacity is a required input with no default.

        "A room carries a `room_name` label, a `capacity_seats` nominal seated
        capacity of at least 1". "Request shape, required fields, types, enum
        members, ISO-8601 formats and declared field constraints —
        `ERR_INVALID_REQUEST`".

        Design: Corner/entities/room_creation_missing_required_capacity_seats_rejected
        """
        branch = world.branch()

        response = world.api.create_room(
            branch["id"],
            {
                "room_name": "Story Room",
                "min_setup_minutes": 15,
                "min_teardown_minutes": 15,
            },
            world.manager,
        )
        validate_error(
            response, ERR_INVALID_REQUEST, ERROR_HTTP_STATUS[ERR_INVALID_REQUEST]
        )

        _, meta = validate_paginated(
            world.api.list_rooms(world.manager, branch_id=branch["id"])
        )
        assert meta["total_count"] == 0


class TestProgramResource:
    """The program's derived flag, its defaults, its enum and its system fields."""

    def test_all_ages_serves_minors_and_only_adult_does_not(
        self, world: LibraryWorld
    ) -> None:
        """The flag is computed from the age group and never supplied.

        "`serves_minors` is true whenever `age_group` is `EARLY_CHILDHOOD`,
        `SCHOOL_AGE`, `TEEN` or `ALL_AGES`, and is false only for `ADULT`. An
        `ALL_AGES` story time serves minors exactly as much as a `SCHOOL_AGE` one
        does, and the entire background-screening regime keys off this flag."

        Design: Corner/entities/program_creation_derives_serves_minors_from_age_group_for_all_ages_and_adult
        """
        branch = world.branch()

        all_ages = world.program(
            branch["id"],
            title="Family Story Time",
            age_group="ALL_AGES",
            attendance_target=40,
            attendance_cap=50,
        )
        adult = world.program(
            branch["id"],
            title="Adult Book Club",
            age_group="ADULT",
            start_utc="2026-08-12T18:00:00.000Z",
            end_utc="2026-08-12T19:00:00.000Z",
            attendance_target=20,
            attendance_cap=25,
        )

        assert all_ages["serves_minors"] is True
        assert adult["serves_minors"] is False
        assert all_ages["age_group"] == "ALL_AGES"
        assert adult["age_group"] == "ADULT"

    def test_the_omitted_partner_and_season_fields_default_and_the_counters_start_clean(
        self, world: LibraryWorld
    ) -> None:
        """Every money counter starts at 0 with the variance equal to both budgets.

        "Its counters start clean: `registered_count` 0, `registrant_references`
        empty, `confirmed_room_capacity` 0, `supply_draw_lines` empty,
        `materials_committed_cents` 0, `materials_spent_cents` 0,
        `presenter_fee_committed_cents` 0, `presenter_fee_spent_cents` 0".

        Design: Corner/entities/program_creation_defaults_partner_fields_accommodations_and_money_counters
        """
        branch = world.branch()

        program = world.program(
            branch["id"],
            title="Craft Hour",
            attendance_target=40,
            attendance_cap=50,
            materials_budget_cents=50000,
            presenter_fee_budget_cents=200000,
        )

        assert program["partner_type"] == "NONE"
        assert program["partner_org_name"] is None
        assert program["partner_insurance_expires_on"] is None
        assert program["accessibility_accommodations"] == []
        assert program["challenge_id"] is None
        assert program["registered_count"] == 0
        assert program["confirmed_room_capacity"] == 0
        assert program["materials_committed_cents"] == 0
        assert program["presenter_fee_committed_cents"] == 0
        assert program["materials_available_cents"] == 50000
        assert program["budget_variance_cents"] == 250000
        assert program["budget_posture"] == "WITHIN_BUDGET"
        assert_program_status(
            program, operational_status="DRAFT", compliance_status="UNVERIFIED"
        )

    def test_an_age_group_outside_the_closed_enumeration_is_refused(
        self, world: LibraryWorld
    ) -> None:
        """The enumeration has five members and is not widened by a plausible sixth.

        "an `age_group` drawn from `EARLY_CHILDHOOD`, `SCHOOL_AGE`, `TEEN`,
        `ADULT` and `ALL_AGES`".

        Design: Corner/entities/program_creation_with_unknown_age_group_enum_rejected
        """
        branch = world.branch()

        response = world.api.create_program(
            program_payload(
                branch["id"],
                title="Craft Hour",
                age_group="PRESCHOOL",
                attendance_target=40,
                attendance_cap=50,
            ),
            world.coordinator,
        )
        validate_error(
            response, ERR_INVALID_REQUEST, ERROR_HTTP_STATUS[ERR_INVALID_REQUEST]
        )

        _, meta = validate_paginated(
            world.api.list_programs(world.coordinator, branch_id=branch["id"])
        )
        assert meta["total_count"] == 0

    def test_a_client_supplied_identifier_version_and_status_are_all_ignored(
        self, world: LibraryWorld
    ) -> None:
        """Unknown body keys cannot preempt the server-minted id or the initial state.

        "Unknown fields in a body are ignored rather than rejected." "`id`
        (string): a server-minted UUID. It carries no type prefix and is never
        supplied by the client."

        Design: Corner/entities/program_creation_client_supplied_id_and_status_input_ignored
        """
        branch = world.branch()

        response = world.api.create_program(
            program_payload(
                branch["id"],
                title="Craft Hour",
                attendance_target=40,
                attendance_cap=50,
                id="00000000-0000-0000-0000-000000000009",
                version=99,
                operational_status="CONFIRMED",
            ),
            world.coordinator,
        )
        program = get_success_data(response, 201)

        assert program["id"] != "00000000-0000-0000-0000-000000000009"
        assert_program_status(program, operational_status="DRAFT")
        assert program["version"] != 99
        assert_common_fields(program, expected_version=1)

    def test_an_unresolvable_branch_in_the_body_is_a_branch_not_found(
        self, world: LibraryWorld
    ) -> None:
        """The body foreign key is resolved and reported with the branch family code.

        "Body foreign keys resolve, in field-declaration order — the appropriate
        `ERR_*_NOT_FOUND` — the six write operations named in section 2.6."
        "`branch_id` and `home_branch_id` resolve to `ERR_BRANCH_NOT_FOUND`".

        Design: Corner/entities/program_creation_with_unknown_branch_id_body_fk_returns_not_found
        """
        world.pin_clock()

        response = world.api.create_program(
            program_payload(
                "00000000-0000-0000-0000-0000000000ff",
                title="Craft Hour",
                attendance_target=40,
                attendance_cap=50,
            ),
            world.coordinator,
        )
        validate_error(
            response, ERR_BRANCH_NOT_FOUND, ERROR_HTTP_STATUS[ERR_BRANCH_NOT_FOUND]
        )

        _, meta = validate_paginated(world.api.list_programs(world.coordinator))
        assert meta["total_count"] == 0


class TestReservationAndPresenterResources:
    """Two resources whose most interesting fields are computed on the server."""

    def test_the_reservation_publishes_its_occupancy_window_and_frozen_capacity(
        self, world: LibraryWorld
    ) -> None:
        """Three fields the client never sent are derived from the ones it did.

        "`occupancy_start_utc` is `start_utc` moved earlier by `setup_minutes`,
        and `occupancy_end_utc` is `end_utc` moved later by `teardown_minutes`".
        "Its `effective_capacity_seats` is the reserved room's `capacity_seats`
        when the program promises no wheelchair layout."

        Design: Corner/entities/reservation_retrieval_exposes_computed_occupancy_window_and_effective_capacity
        """
        branch = world.branch()
        room = world.room(
            branch["id"],
            room_name="Story Room",
            capacity_seats=60,
            min_setup_minutes=15,
            min_teardown_minutes=15,
        )
        program = world.program(
            branch["id"], title="Craft Hour", attendance_target=40, attendance_cap=50
        )

        created = get_success_data(
            world.api.create_reservation(
                program["id"],
                reservation_payload(
                    room["id"],
                    program["version"],
                    start_utc="2026-08-12T14:00:00.000Z",
                    end_utc="2026-08-12T15:00:00.000Z",
                    setup_minutes=15,
                    teardown_minutes=15,
                ),
                world.coordinator,
            ),
            201,
        )

        response = world.api.get_reservation(created["id"], world.coordinator)
        reservation = get_success_data(response, 200)

        assert_instant_equals(
            reservation["occupancy_start_utc"],
            "2026-08-12T13:45:00.000Z",
            "occupancy_start_utc",
        )
        assert_instant_equals(
            reservation["occupancy_end_utc"],
            "2026-08-12T15:15:00.000Z",
            "occupancy_end_utc",
        )
        assert reservation["effective_capacity_seats"] == 60
        assert reservation["status"] == "HELD"
        assert reservation["program_id"] == program["id"]

    def test_registering_a_presenter_implies_no_screening_at_all(
        self, world: LibraryWorld
    ) -> None:
        """Every screening field starts empty and the engagement starts prospective.

        "A new presenter reports `engagement_status` of `PROSPECT`,
        `screening_decision`, `screening_status` and `screening_tier` all `NONE`,
        `screening_decided_on` and `screening_valid_until` both null, and
        `executed_contract_count` of 0."

        Design: Corner/entities/presenter_creation_initialises_screening_and_engagement_fields
        """
        world.pin_clock()

        presenter = world.presenter(
            legal_name="Marisol Vega",
            presenter_type="INDIVIDUAL",
            insurance_certificate_expires_on="2027-01-01",
            quoted_fee_cents=50000,
        )

        assert presenter["engagement_status"] == "PROSPECT"
        assert presenter["screening_decision"] == "NONE"
        assert presenter["screening_tier"] == "NONE"
        assert presenter["screening_status"] == "NONE"
        assert presenter["screening_valid_until"] is None
        assert presenter["screening_decided_on"] is None
        assert presenter["executed_contract_count"] == 0
        assert_common_fields(presenter, expected_version=1)


class TestReadingSeasonResources:
    """The ledger entry, the ladder tier, the stock lot and the reader listing."""

    def test_a_reading_log_entry_publishes_neither_a_version_nor_an_updated_stamp(
        self, world: LibraryWorld
    ) -> None:
        """The one resource in the service that is append-only rather than mutable.

        "A reading log entry is an append-only ledger record: it carries `id` and
        `created_at` — `created_at` is both the chronological replay key for the
        ledger and the target that a correction points at — but it has **no**
        `updated_at` and **no** `version`, because an entry is never mutated."

        Design: Corner/entities/reading_log_entry_carries_no_version_or_updated_at_field
        """
        branch = world.branch()
        opened = world.opened_challenge(
            tiers=[
                {
                    "tier_index": 1,
                    "threshold_units": 5000,
                    "prize_sku": "MEDAL",
                    "prize_units_per_participant": 1,
                }
            ],
            name="Summer 2026",
            logging_method="MINUTES",
            unit_label="minutes",
            start_on="2026-07-01",
            end_on="2026-08-31",
            correction_policy="LEDGER_TRUTH",
            prize_budget_cents=10000,
        )
        participant = world.participant(
            opened["challenge"]["id"],
            branch["id"],
            display_name="Ada L.",
            age_band="AGE_5_11",
        )
        created = world.log_entry(participant["id"], 30, "2026-08-01")

        entry = get_success_data(
            world.api.get_log_entry(created["id"], world.coordinator), 200
        )
        assert_append_only_fields(entry)
        assert entry["entry_type"] == "LOG"
        assert entry["units"] == 30
        assert entry["units_delta"] == 0
        assert entry["participant_id"] == participant["id"]
        assert entry["corrected_entry_id"] is None

    def test_a_tier_takes_its_challenge_from_the_path_and_is_listable_from_it(
        self, world: LibraryWorld
    ) -> None:
        """The parent link is a system field, and the filtered listing reaches back.

        "The tier's `challenge_id` is taken from the creation path and any value
        in the body is ignored." "A new tier reports `award_count` and
        `deferred_count` of 0".

        Design: Corner/entities/incentive_tier_creation_takes_challenge_id_from_the_path_parent
        """
        challenge = world.challenge(
            name="Summer 2026",
            logging_method="MINUTES",
            unit_label="minutes",
            start_on="2026-07-01",
            end_on="2026-08-31",
            correction_policy="LEDGER_TRUTH",
            prize_budget_cents=10000,
        )

        response = world.api.create_incentive_tier(
            challenge["id"],
            {
                "tier_index": 1,
                "threshold_units": 60,
                "prize_sku": "MEDAL",
                "prize_units_per_participant": 1,
            },
            world.manager,
        )
        tier = get_success_data(response, 201)

        assert tier["challenge_id"] == challenge["id"]
        assert tier["award_count"] == 0
        assert tier["deferred_count"] == 0

        rows, meta = validate_paginated(
            world.api.list_incentive_tiers(
                world.manager, challenge_id=challenge["id"]
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [tier["id"]]

    def test_a_new_lot_puts_its_whole_procurement_into_availability(
        self, world: LibraryWorld
    ) -> None:
        """The three-way split starts wholly available and the identity already holds.

        "`quantity_procured` is never mutated for the life of the lot; instead
        the lot publishes a three-way split, starting with `quantity_available`
        equal to `quantity_procured`, `quantity_reserved` at 0 and
        `quantity_issued` at 0, and a `status` of `ACTIVE`."

        Design: Corner/entities/inventory_lot_creation_initialises_availability_and_active_status
        """
        branch = world.branch()

        response = world.api.create_inventory_lot(
            {
                "branch_id": branch["id"],
                "category": "SUPPLY",
                "sku": "CRAFT-KIT",
                "unit_cost_cents": 250,
                "quantity_procured": 100,
                "reuse_pool": False,
            },
            world.manager,
        )
        lot = get_success_data(response, 201)

        assert lot["quantity_available"] == 100
        assert lot["quantity_reserved"] == 0
        assert lot["quantity_issued"] == 0
        assert lot["status"] == "ACTIVE"
        assert_lot_conservation(lot)

    def test_the_reader_listing_pages_three_rows_two_at_a_time(
        self, world: LibraryWorld
    ) -> None:
        """The total counts every match while the page carries only its slice.

        "The `meta` object of a list response carries `limit`, `offset`,
        `total_count` and `has_more`, where `total_count` is the number of items
        matching the filters before pagination is applied and `has_more` states
        whether any matching item lies beyond the returned page."

        Design: Corner/entities/participants_listing_reports_pagination_metadata_and_filters_by_challenge
        """
        branch = world.branch()
        challenge = world.challenge(
            name="Summer 2026",
            logging_method="MINUTES",
            unit_label="minutes",
            start_on="2026-07-01",
            end_on="2026-08-31",
            correction_policy="LEDGER_TRUTH",
            prize_budget_cents=10000,
        )
        for display_name, age_band in (
            ("Ada L.", "AGE_5_11"),
            ("Ben O.", "AGE_12_17"),
            ("Cy P.", "ADULT"),
        ):
            world.participant(
                challenge["id"],
                branch["id"],
                display_name=display_name,
                age_band=age_band,
            )

        first_page, first_meta = validate_paginated(
            world.api.list_participants(
                world.coordinator, challenge_id=challenge["id"], limit=2, offset=0
            )
        )
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert len(first_page) == 2

        last_page, last_meta = validate_paginated(
            world.api.list_participants(
                world.coordinator, challenge_id=challenge["id"], limit=2, offset=2
            )
        )
        assert last_meta["total_count"] == 3
        assert last_meta["has_more"] is False
        assert len(last_page) == 1

        assert world.read_challenge(challenge["id"])["participant_count"] == 3
