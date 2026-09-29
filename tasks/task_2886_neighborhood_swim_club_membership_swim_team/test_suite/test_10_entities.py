"""Entity-level corners: echoes, born-clean ledgers, filtered pages and 404s."""

from test_helpers import (
    ApiErrorId,
    BondStatus,
    CaseSeverity,
    CaseStatus,
    CategoryCode,
    CertType,
    CertificationStatus,
    HouseholdStanding,
    JobCode,
    PriorityTier,
    RegistrationStatus,
    Residency,
    Squad,
    WaitlistStatus,
    assertions as a,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    certification_payload,
    conduct_case_payload,
    membership_category_payload,
    registration_payload,
    season_payload,
    volunteer_assignment_payload,
    waitlist_entry_payload,
)
from test_helpers.test_users import (
    BOARD_PRESIDENT,
    HEALTH_INSPECTOR,
    MEMBERSHIP_CHAIR,
    POOL_MANAGER,
    POOL_MANAGER_USER_ID,
    SWIM_TEAM_COACH,
    TREASURER,
)

CATEGORY_INPUTS = dict(
    code=CategoryCode.FAMILY,
    label="Family (two adults plus dependents)",
    bond_cents=120000,
    initiation_fee_cents=45000,
    seasonal_dues_cents=78000,
    guest_pass_allotment=4,
    max_household_size=6,
    volunteer_credits_required=4,
    waitlist_required=False,
    proration_allowed=True,
    party_privileges=True,
)


class TestMembershipCategoryEchoesEveryDeclaredInput:
    """The one entity with no computed field at all: eleven inputs, echoed."""

    def test_all_eleven_inputs_come_back_unchanged(self, api):
        """Nothing is coerced, dropped or renamed on the way out.

        PRD §3.2: "A category is identified by its `code`, which must be unique
        across categories and must be one of `FAMILY`, `COUPLE`, `SINGLE`,
        `SENIOR` or `SWIM_TEAM_ONLY`, and it carries a human-readable `label`."

        Design: Corner/entities/creation_membership_category_echoes_every_declared_input_field
        """
        fx.set_clock(api, "2027-03-01T09:00:00Z")

        category = validate_success(
            api.create_membership_category(
                membership_category_payload(**CATEGORY_INPUTS), MEMBERSHIP_CHAIR
            ),
            201,
        )

        for field, value in CATEGORY_INPUTS.items():
            assert category[field] == value, (
                f"{field}: expected {value!r}, got {category[field]!r}"
            )

    def test_the_money_fields_are_integers_and_the_flags_are_booleans(self, api):
        """Integer cents, never a decimal string, and three real booleans.

        PRD §2.6: "All money in this system is an integer number of cents. There
        are no fractional-cent fields, no floating-point money in responses, and
        no currency codes."

        Design: Corner/entities/creation_membership_category_echoes_every_declared_input_field
        """
        fx.set_clock(api, "2027-03-01T09:00:00Z")

        category = validate_success(
            api.create_membership_category(
                membership_category_payload(**CATEGORY_INPUTS), MEMBERSHIP_CHAIR
            ),
            201,
        )

        a.assert_money_integer(
            category, "bond_cents", "initiation_fee_cents", "seasonal_dues_cents"
        )
        for flag in ("waitlist_required", "proration_allowed", "party_privileges"):
            assert isinstance(category[flag], bool)
        a.assert_common_fields(category)


class TestNewHouseholdReadsBackWithEveryCounterZeroed:
    """The money aggregate's baseline, and a GET that matches its POST."""

    def test_every_ledger_counter_is_born_at_zero(self, api):
        """Nine born-clean fields, before any category grants a single pass.

        PRD §3.2: "A household is born in `GOOD_STANDING` with `conduct_points`
        at 0, with `bond_status` `NONE` and `bond_paid_cents` at 0, with all three
        guest-pass counters — `guest_pass_allotment_granted`,
        `guest_passes_consumed` and `guest_pass_balance` — at 0, and with
        `guest_fee_owed_cents`, `party_charges_owed_cents` and
        `account_credit_cents` all at 0."

        Design: Corner/entities/retrieval_new_household_reads_back_with_all_ledger_counters_zeroed
        """
        fx.set_clock(api, "2027-03-01T09:00:00Z")
        household = fx.create_household(
            api, primary_contact_name="Nadia Okonkwo",
            address_line="3 Cedar Court", residency=Residency.IN_DISTRICT,
            member_count=4, prior_member=False,
        )

        fetched = fx.read_household(api, household["id"])

        assert fetched["standing"] == HouseholdStanding.GOOD_STANDING
        assert fetched["bond_status"] == BondStatus.NONE
        a.assert_household_born_clean(fetched)
        assert fetched["member_count"] == 4
        assert fetched["prior_member"] is False

    def test_the_get_representation_equals_the_post_representation(self, api):
        """No counter is computed only on the write path.

        PRD §2.10: "A successful create or modify returns the created or updated
        resource in the `data` field, with one exception: the staffing-window read
        returns a computed object rather than a stored entity, and the
        clock-setting call returns an empty object."

        Design: Corner/entities/retrieval_new_household_reads_back_with_all_ledger_counters_zeroed
        """
        fx.set_clock(api, "2027-03-01T09:00:00Z")
        created = fx.create_household(
            api, primary_contact_name="Nadia Okonkwo",
            address_line="3 Cedar Court", residency=Residency.IN_DISTRICT,
            member_count=4, prior_member=False,
        )

        fetched = fx.read_household(api, created["id"])

        assert fetched == created


def _three_seasons_worth_of_memberships(api):
    """Three 2027 memberships and one 2028 membership, one household in both."""
    fx.set_clock(api, "2027-06-01T09:00:00Z")
    category = fx.create_couple_category(api)
    season_27 = fx.open_season(api, fx.create_season(api)["id"])
    season_28 = fx.open_season(
        api,
        fx.create_season(
            api, year=2028, open_date="2028-05-20", close_date="2028-09-04",
            dues_due_date="2028-04-15",
        )["id"],
    )

    households = [
        fx.create_household(api, primary_contact_name="House One",
                            address_line="1 Cedar Court", member_count=2,
                            prior_member=False),
        fx.create_household(api, primary_contact_name="House Two",
                            address_line="2 Cedar Court", member_count=2,
                            prior_member=False),
        fx.create_household(api, primary_contact_name="House Three",
                            address_line="3 Cedar Court",
                            residency=Residency.OUT_OF_DISTRICT,
                            member_count=2, prior_member=False),
    ]
    in_2027 = [
        fx.setup_membership(api, h["id"], category["id"], season_27["id"],
                            join_date="2027-06-01")
        for h in households
    ]
    in_2028 = fx.setup_membership(
        api, households[0]["id"], category["id"], season_28["id"],
        join_date="2028-05-20",
    )
    return {
        "season_27": season_27, "season_28": season_28,
        "households": households, "in_2027": in_2027, "in_2028": in_2028,
    }


class TestMembershipListingPaginatesOverTheFilteredSet:
    """total_count counts the filter's matches, not the whole table."""

    def test_the_first_page_reports_the_filtered_total_and_has_more(self, api):
        """Three of the four memberships match, so total_count is 3.

        PRD §2.3: "Four pagination fields appear in the `meta` object of every
        list response: `limit` (the effective page size), `offset` (the effective
        starting position), `total_count` (the number of rows matching the
        request's filters before the page window is applied) and `has_more` (true
        when rows remain beyond the current page)."

        Design: Corner/entities/listing_memberships_filtered_by_season_paginates_with_total_count
        """
        ctx = _three_seasons_worth_of_memberships(api)

        rows, meta = validate_paginated(
            api.list_memberships(
                TREASURER,
                {"season_id": ctx["season_27"]["id"], "limit": 2, "offset": 0},
            )
        )

        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_the_second_page_closes_the_set_without_gap_or_duplicate(self, api):
        """The union of the two pages is exactly the three 2027 memberships.

        PRD §2.3: "List results are ordered by `created_at` ascending unless a
        specific narrative in §3 pins a different order for a particular
        computation."

        Design: Corner/entities/listing_memberships_filtered_by_season_paginates_with_total_count
        """
        ctx = _three_seasons_worth_of_memberships(api)
        params = {"season_id": ctx["season_27"]["id"], "limit": 2}

        page_1, _ = validate_paginated(
            api.list_memberships(TREASURER, dict(params, offset=0))
        )
        page_2, meta_2 = validate_paginated(
            api.list_memberships(TREASURER, dict(params, offset=2))
        )

        assert len(page_2) == 1
        assert meta_2["total_count"] == 3
        assert meta_2["has_more"] is False
        assert meta_2["offset"] == 2
        seen = [row["id"] for row in page_1 + page_2]
        assert len(seen) == len(set(seen))
        assert set(seen) == {m["id"] for m in ctx["in_2027"]}

    def test_the_household_filter_is_independent_of_the_season_filter(self, api):
        """One household holds two memberships across two seasons.

        PRD §3.3: "Categories themselves can be listed and filtered by `code` and
        by `waitlist_required`, and memberships by `household_id`,
        `membership_category_id`, `season_id`, `dues_status` and `access_status` —
        the last two independently, which is how the treasurer finds every
        membership that is `DELINQUENT` on money while still `ACTIVE` at the
        gate."

        Design: Corner/entities/listing_memberships_filtered_by_season_paginates_with_total_count
        """
        ctx = _three_seasons_worth_of_memberships(api)

        rows, meta = validate_paginated(
            api.list_memberships(
                TREASURER, {"household_id": ctx["households"][0]["id"]}
            )
        )

        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            ctx["in_2027"][0]["id"], ctx["in_2028"]["id"],
        }
        assert meta["limit"] == 10
        assert meta["offset"] == 0


UNKNOWN_SEASON = "00000000-0000-4000-8000-000000000001"
UNKNOWN_CATEGORY = "00000000-0000-4000-8000-000000000002"
UNKNOWN_HOUSEHOLD = "00000000-0000-4000-8000-000000000003"
UNKNOWN_WAITLIST_ENTRY = "00000000-0000-4000-8000-000000000004"
UNKNOWN_MEMBERSHIP = "00000000-0000-4000-8000-000000000005"
UNKNOWN_VISIT = "00000000-0000-4000-8000-000000000011"
UNKNOWN_LIFEGUARD = "00000000-0000-4000-8000-000000000012"
UNKNOWN_CERTIFICATION = "00000000-0000-4000-8000-000000000013"
UNKNOWN_SHIFT = "00000000-0000-4000-8000-000000000014"
UNKNOWN_REGISTRATION = "00000000-0000-4000-8000-000000000015"
UNKNOWN_MEET = "00000000-0000-4000-8000-000000000021"
UNKNOWN_ASSIGNMENT = "00000000-0000-4000-8000-000000000022"
UNKNOWN_RESERVATION = "00000000-0000-4000-8000-000000000023"
UNKNOWN_FINDING = "00000000-0000-4000-8000-000000000024"
UNKNOWN_CASE = "00000000-0000-4000-8000-000000000025"
UNKNOWN_PROJECT = "00000000-0000-4000-8000-000000000026"


def _distinct(*error_ids):
    assert len(set(error_ids)) == len(error_ids), (
        f"error ids collapsed onto one another: {error_ids}"
    )


class TestExistenceErrorsAreEntitySpecific:
    """Sixteen aggregates, sixteen codes: no funnel through one generic 404."""

    def test_the_five_core_registry_reads_return_five_distinct_codes(self, api):
        """Season, category, household, waitlist entry and membership.

        PRD §2.9: "**Existence**, for every resource addressed in the path or
        referenced by a foreign key in the payload, each with its own code:
        `ERR_SEASON_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`,
        `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`,
        `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_GUEST_VISIT_NOT_FOUND`,
        `ERR_LIFEGUARD_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
        `ERR_GUARD_SHIFT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
        `ERR_MEET_NOT_FOUND`, `ERR_VOLUNTEER_ASSIGNMENT_NOT_FOUND`,
        `ERR_PARTY_RESERVATION_NOT_FOUND`, `ERR_INSPECTION_FINDING_NOT_FOUND`,
        `ERR_CONDUCT_CASE_NOT_FOUND`, `ERR_CAPITAL_PROJECT_NOT_FOUND` — all
        HTTP 404."

        Design: Corner/entities/not_found_core_registry_ids_return_entity_specific_404s
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")

        seen = [
            validate_error(
                api.get_season(UNKNOWN_SEASON, BOARD_PRESIDENT),
                ApiErrorId.SEASON_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_membership_category(UNKNOWN_CATEGORY, MEMBERSHIP_CHAIR),
                ApiErrorId.CATEGORY_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_household(UNKNOWN_HOUSEHOLD, MEMBERSHIP_CHAIR),
                ApiErrorId.HOUSEHOLD_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_waitlist_entry(UNKNOWN_WAITLIST_ENTRY, MEMBERSHIP_CHAIR),
                ApiErrorId.WAITLIST_ENTRY_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_membership(UNKNOWN_MEMBERSHIP, TREASURER),
                ApiErrorId.MEMBERSHIP_NOT_FOUND, 404,
            )["error_id"],
        ]

        _distinct(*seen)

    def test_the_five_operations_reads_separate_child_from_parent(self, api):
        """A certification miss is not reported as a lifeguard miss.

        PRD §2.9: "Within this band the season is resolved first, then the
        membership category, then the household, then the waitlist entry, then
        the membership, then the remaining resources in the order just listed."

        Design: Corner/entities/not_found_operations_ids_return_entity_specific_404s
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")

        seen = [
            validate_error(
                api.get_guest_visit(UNKNOWN_VISIT, POOL_MANAGER),
                ApiErrorId.GUEST_VISIT_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_lifeguard(UNKNOWN_LIFEGUARD, POOL_MANAGER),
                ApiErrorId.LIFEGUARD_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_certification(UNKNOWN_CERTIFICATION, POOL_MANAGER),
                ApiErrorId.CERTIFICATION_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_guard_shift(UNKNOWN_SHIFT, POOL_MANAGER),
                ApiErrorId.GUARD_SHIFT_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_registration(UNKNOWN_REGISTRATION, SWIM_TEAM_COACH),
                ApiErrorId.REGISTRATION_NOT_FOUND, 404,
            )["error_id"],
        ]

        assert seen[2] != ApiErrorId.LIFEGUARD_NOT_FOUND
        _distinct(*seen)

    def test_the_six_program_and_finance_reads_reach_404_not_403(self, api):
        """Restricted aggregates are read by an authorised office, and still 404.

        PRD §2.9: "**Endpoint authorisation.** The acting role appears in the
        endpoint's authorised list — otherwise `ERR_UNAUTHORIZED` (403)."

        Design: Corner/entities/not_found_program_and_finance_ids_return_entity_specific_404s
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")

        seen = [
            validate_error(
                api.get_meet(UNKNOWN_MEET, SWIM_TEAM_COACH),
                ApiErrorId.MEET_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_volunteer_assignment(UNKNOWN_ASSIGNMENT, SWIM_TEAM_COACH),
                ApiErrorId.VOLUNTEER_ASSIGNMENT_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_party_reservation(UNKNOWN_RESERVATION, POOL_MANAGER),
                ApiErrorId.PARTY_RESERVATION_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_inspection_finding(UNKNOWN_FINDING, HEALTH_INSPECTOR),
                ApiErrorId.INSPECTION_FINDING_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_conduct_case(UNKNOWN_CASE, BOARD_PRESIDENT),
                ApiErrorId.CONDUCT_CASE_NOT_FOUND, 404,
            )["error_id"],
            validate_error(
                api.get_capital_project(UNKNOWN_PROJECT, TREASURER),
                ApiErrorId.CAPITAL_PROJECT_NOT_FOUND, 404,
            )["error_id"],
        ]

        _distinct(*seen)


def _three_tiers_in_one_queue(api):
    """One waitlist-gated FAMILY category with a household in each tier."""
    fx.set_clock(api, "2027-06-01T09:00:00Z")
    category = fx.create_family_category(api, waitlist_required=True)
    legacy = fx.create_household(
        api, primary_contact_name="Legacy House",
        address_line="11 Cedar Court", member_count=4, prior_member=True,
    )
    sibling = fx.create_household(
        api, primary_contact_name="Sibling House",
        address_line="12 Cedar Court", member_count=4, prior_member=False,
    )
    standard = fx.create_household(
        api, primary_contact_name="Standard House",
        address_line="13 Cedar Court", residency=Residency.OUT_OF_DISTRICT,
        member_count=4, prior_member=False,
    )

    entries = {}
    entries["legacy"] = validate_success(
        api.create_waitlist_entry(
            waitlist_entry_payload(legacy["id"], category["id"],
                                   priority_tier=PriorityTier.LEGACY),
            MEMBERSHIP_CHAIR,
        ),
        201,
    )
    entries["sibling"] = validate_success(
        api.create_waitlist_entry(
            waitlist_entry_payload(sibling["id"], category["id"],
                                   priority_tier=PriorityTier.SIBLING),
            MEMBERSHIP_CHAIR,
        ),
        201,
    )
    entries["standard"] = validate_success(
        api.create_waitlist_entry(
            waitlist_entry_payload(standard["id"], category["id"],
                                   priority_tier=Ellipsis),
            MEMBERSHIP_CHAIR,
        ),
        201,
    )
    return entries


class TestWaitlistEntryRankAndQueueKeyAreServerDerived:
    """Zero-based rank encoding, and a sort key seeded from created_at."""

    def test_the_rank_encoding_is_zero_based_and_the_tier_defaults(self, api):
        """A 1/2/3 encoding sorts identically and publishes the wrong integers.

        PRD §3.2: "An optional `priority_tier` claims a queue tier — `LEGACY`,
        `SIBLING` or `STANDARD` — and defaults to `STANDARD`. From that tier a
        numeric `priority_tier_rank` is derived and stored as the queue's primary
        sort key: `LEGACY` ranks 0, `SIBLING` ranks 1, `STANDARD` ranks 2, so a
        lower rank is served first."

        Design: Corner/entities/computed_fields_waitlist_entry_rank_and_queue_key_are_server_derived
        """
        entries = _three_tiers_in_one_queue(api)

        assert entries["legacy"]["priority_tier_rank"] == 0
        assert entries["sibling"]["priority_tier_rank"] == 1
        assert entries["standard"]["priority_tier_rank"] == 2
        assert entries["standard"]["priority_tier"] == PriorityTier.STANDARD

    def test_every_fresh_entry_is_waiting_with_its_key_at_creation(self, api):
        """queue_key_at is created_at, not the clock instant it was set from.

        PRD §3.2: "A new entry is born `WAITING` with `deferral_count` at 0,
        `offered_at`, `offer_expires_at` and `requeued_at` all null, and its
        `queue_key_at` seeded from its own `created_at`."

        Design: Corner/entities/computed_fields_waitlist_entry_rank_and_queue_key_are_server_derived
        """
        entries = _three_tiers_in_one_queue(api)

        for entry in entries.values():
            a.assert_waitlist_entry(entry, WaitlistStatus.WAITING)
            assert entry["deferral_count"] == 0
            assert entry["offered_at"] is None
            assert entry["offer_expires_at"] is None
            assert entry["requeued_at"] is None
            assert is_iso8601_timestamp(entry["created_at"])
            assert entry["queue_key_at"] == entry["created_at"]


CASE_NARRATIVE = "Ran on the deck twice after two warnings from the guard chair."


def _a_case_reported_by_the_pool_manager(api):
    """One unattached household with a MINOR case freshly reported against it."""
    fx.set_clock(api, "2027-07-10T15:00:00Z")
    household = fx.create_household(
        api, primary_contact_name="Reporter Test Household",
        address_line="21 Cedar Court", member_count=3, prior_member=False,
    )
    case = validate_success(
        api.create_conduct_case(
            conduct_case_payload(
                household["id"], subject_name="Teen guest of the household",
                severity=CaseSeverity.MINOR, narrative=CASE_NARRATIVE,
            ),
            POOL_MANAGER,
        ),
        201,
    )
    return {"household": household, "case": case}


class TestConductCaseStampsTheActingUserAsReporter:
    """The stamp that makes two-person control enforceable at all."""

    def test_the_reporter_is_taken_from_the_header_and_nothing_is_decided(
        self, api
    ):
        """The payload carries no reporter field, so the header is the only source.

        PRD §3.9: "The case opens at `REPORTED` with the reporter's identity
        captured in `reported_by_user_id`, `points_assessed` at 0 and
        `appeal_count` at 0; `decided_by_user_id`, `sanction_type` and
        `sanctioned_at` are all null until the board decides."

        Design: Corner/entities/system_fields_conduct_case_stamps_reported_by_user_id_from_the_header
        """
        ctx = _a_case_reported_by_the_pool_manager(api)

        case = ctx["case"]
        assert case["status"] == CaseStatus.REPORTED
        assert case["reported_by_user_id"] == POOL_MANAGER_USER_ID
        assert case["points_assessed"] == 0
        assert case["appeal_count"] == 0
        assert case["decided_by_user_id"] is None
        assert case["sanction_type"] is None
        assert case["sanctioned_at"] is None

    def test_the_stamp_is_persisted_and_costs_the_household_no_points(self, api):
        """A different office re-reads the same reporter, and nothing accrued.

        PRD §3.9: "Cases in `REPORTED`, `UNDER_REVIEW`, `APPEALED` or `DISMISSED`
        contribute zero."

        Design: Corner/entities/system_fields_conduct_case_stamps_reported_by_user_id_from_the_header
        """
        ctx = _a_case_reported_by_the_pool_manager(api)

        reread = validate_success(
            api.get_conduct_case(ctx["case"]["id"], BOARD_PRESIDENT), 200
        )
        assert reread["reported_by_user_id"] == POOL_MANAGER_USER_ID
        assert reread["decided_by_user_id"] is None

        household = fx.read_household(api, ctx["household"]["id"])
        assert household["conduct_points"] == 0
        assert household["standing"] == HouseholdStanding.GOOD_STANDING


SWIMMER = dict(swimmer_name="Ida Marsh", swimmer_birthdate="2015-04-02")


def _one_membership_ready_for_a_swimmer(api):
    """An OPEN 2027 season with one COUPLE membership sitting under it."""
    fx.set_clock(api, "2027-06-01T09:00:00Z")
    category = fx.create_couple_category(api)
    season = fx.open_season(api, fx.create_season(api)["id"])
    household = fx.create_household(
        api, primary_contact_name="Enum Test Household",
        address_line="31 Cedar Court", member_count=2, prior_member=False,
    )
    membership = fx.setup_membership(
        api, household["id"], category["id"], season["id"],
        join_date="2027-06-01",
    )
    return {"season": season, "membership": membership}


def _attempt_registration(api, ctx, squad):
    return api.create_registration(
        registration_payload(
            ctx["membership"]["id"], ctx["season"]["id"], squad=squad, **SWIMMER
        ),
        SWIM_TEAM_COACH,
    )


class TestUnknownSquadTokenIsAnEnumFailure:
    """The enum gate outranks every business rule that reads the same field."""

    def test_an_invented_token_and_a_lowercased_token_both_fail_the_gate(
        self, api
    ):
        """Enum matching is exact and case-sensitive, and it is not ERR_VALIDATION.

        PRD §2.9: "**Enumerations.** Every enum-valued input holds one of its
        declared values — otherwise `ERR_INVALID_ENUM` (422)."

        Design: Corner/entities/type_constraints_unknown_squad_value_returns_invalid_enum
        """
        ctx = _one_membership_ready_for_a_swimmer(api)

        invented = validate_error(
            _attempt_registration(api, ctx, "INTERMEDIATE"),
            ApiErrorId.INVALID_ENUM, 422,
        )
        lowercased = validate_error(
            _attempt_registration(api, ctx, "junior"),
            ApiErrorId.INVALID_ENUM, 422,
        )
        assert invented["error_id"] != ApiErrorId.VALIDATION
        assert lowercased["error_id"] != ApiErrorId.VALIDATION

    def test_the_declared_token_registers_and_the_rejects_left_no_row(self, api):
        """One swimmer on the roster, so neither rejected request wrote anything.

        PRD §3.6: "`squad_seq` is the swimmer's 1-based rank **within its own
        membership**, obtained by ordering that membership's registrations whose
        `status` is `PENDING`, `CONFIRMED`, `WAITLISTED` or `COMPLETED` by
        `swimmer_birthdate` ascending and then, for identical birthdates, by
        `created_at` ascending — never by `id`."

        Design: Corner/entities/type_constraints_unknown_squad_value_returns_invalid_enum
        """
        ctx = _one_membership_ready_for_a_swimmer(api)
        _attempt_registration(api, ctx, "INTERMEDIATE")
        _attempt_registration(api, ctx, "junior")

        accepted = validate_success(
            _attempt_registration(api, ctx, Squad.JUNIOR), 201
        )
        assert accepted["squad"] == Squad.JUNIOR
        assert accepted["squad_seq"] == 1
        assert accepted["status"] == RegistrationStatus.PENDING

        _, meta = validate_paginated(
            api.list_registrations(
                SWIM_TEAM_COACH, {"membership_id": ctx["membership"]["id"]}
            )
        )
        assert meta["total_count"] == 1


def _attempt_season(api, open_date, close_date):
    return api.create_season(
        season_payload(open_date=open_date, close_date=close_date),
        BOARD_PRESIDENT,
    )


class TestSeasonWindowComparisonIsStrictlyGreaterThan:
    """A zero-length season would divide by zero inside the dues assessment."""

    def test_an_inverted_pair_and_an_equal_pair_both_fail_the_interval_gate(
        self, api
    ):
        """Equality is rejected exactly as inversion is; both dates are well formed.

        PRD §2.9: "**Paired time ranges.** Within a single payload, a start is
        strictly earlier than its paired end — a guard shift's `start_iso` before
        its `end_iso`, a party's `start_iso` before its `end_iso`, a season's
        `open_date` before its `close_date` — otherwise `ERR_INVALID_TIME_RANGE`
        (422)."

        Design: Corner/entities/type_constraints_season_close_date_must_be_after_open_date
        """
        fx.set_clock(api, "2027-03-01T09:00:00Z")

        inverted = validate_error(
            _attempt_season(api, "2027-09-06", "2027-05-22"),
            ApiErrorId.INVALID_TIME_RANGE, 422,
        )
        equal = validate_error(
            _attempt_season(api, "2027-05-22", "2027-05-22"),
            ApiErrorId.INVALID_TIME_RANGE, 422,
        )
        assert inverted["error_id"] != ApiErrorId.VALIDATION
        assert equal["error_id"] != ApiErrorId.VALIDATION

    def test_a_one_day_season_is_accepted_and_the_rejects_wrote_nothing(self, api):
        """The gate is not off by one in the permissive direction either.

        PRD §3.3: "The arithmetic begins with two measures of the season itself:
        the total number of calendar days in the season, counted from `open_date`
        to `close_date` with both endpoints included, and the total number of swim
        weeks, which is that day count divided by the seven days in a swim week
        and rounded up to the next whole number."

        Design: Corner/entities/type_constraints_season_close_date_must_be_after_open_date
        """
        fx.set_clock(api, "2027-03-01T09:00:00Z")
        _attempt_season(api, "2027-09-06", "2027-05-22")
        _attempt_season(api, "2027-05-22", "2027-05-22")

        season = validate_success(
            _attempt_season(api, "2027-05-22", "2027-05-23"), 201
        )
        assert season["open_date"] == "2027-05-22"
        assert season["close_date"] == "2027-05-23"

        _, meta = validate_paginated(api.list_seasons(BOARD_PRESIDENT))
        assert meta["total_count"] == 1


UNKNOWN_PARENT_LIFEGUARD = "00000000-0000-4000-8000-000000000031"
UNKNOWN_JUNCTION_MEET = "00000000-0000-4000-8000-000000000041"
UNKNOWN_JUNCTION_REGISTRATION = "00000000-0000-4000-8000-000000000042"


class TestCertificationRequiresAnExistingLifeguard:
    """The only declared parent in the model, checked before any field work."""

    def test_an_unknown_parent_is_the_parent_s_own_404(self, api):
        """Not ERR_VALIDATION, and not the child's own not-found code either.

        PRD §3.8: "Hiring a guard is the simplest write in the system and the
        least useful on its own. The `PoolManager` records a `full_name` and a
        `hire_date`, and the new guard starts with `employment_status` `ACTIVE`,
        `scheduled_hours` at 0, and both derived certification flags —
        `has_valid_lifeguard_cert` and `has_valid_cpr_cert` — false."

        Design: Corner/entities/parent_relationships_certification_requires_an_existing_lifeguard
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")
        guard = fx.create_lifeguard(api, full_name="Priya Raman",
                                    hire_date="2027-05-01")
        assert guard["has_valid_lifeguard_cert"] is False

        body = validate_error(
            api.create_certification(
                certification_payload(
                    UNKNOWN_PARENT_LIFEGUARD, cert_type=CertType.LIFEGUARD,
                    issued_on="2027-01-10", expires_on="2029-01-10",
                ),
                POOL_MANAGER,
            ),
            ApiErrorId.LIFEGUARD_NOT_FOUND, 404,
        )
        assert body["error_id"] != ApiErrorId.VALIDATION
        assert body["error_id"] != ApiErrorId.CERTIFICATION_NOT_FOUND

    def test_a_real_parent_gets_a_valid_card_and_one_recomputed_flag(self, api):
        """The child is reachable from the parent id and only its own flag moved.

        PRD §3.8: "Both certification flags are recomputed after every such write
        — `has_valid_lifeguard_cert` is true when at least one of the guard's
        certifications has `cert_type` `LIFEGUARD` and `status` `VALID`, and
        `has_valid_cpr_cert` is the same test for `CPR_AED` — and a guard sitting
        at `INACTIVE` returns to `ACTIVE` the moment a valid lifeguard
        certification exists for them again."

        Design: Corner/entities/parent_relationships_certification_requires_an_existing_lifeguard
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")
        guard = fx.create_lifeguard(api, full_name="Priya Raman",
                                    hire_date="2027-05-01")

        cert = validate_success(
            api.create_certification(
                certification_payload(
                    guard["id"], cert_type=CertType.LIFEGUARD,
                    issued_on="2027-01-10", expires_on="2029-01-10",
                ),
                POOL_MANAGER,
            ),
            201,
        )
        assert cert["status"] == CertificationStatus.VALID
        assert cert["revoked_reason"] is None

        rows, meta = validate_paginated(
            api.list_certifications(POOL_MANAGER, {"lifeguard_id": guard["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [cert["id"]]

        reread = fx.read_lifeguard(api, guard["id"])
        assert reread["has_valid_lifeguard_cert"] is True
        assert reread["has_valid_cpr_cert"] is False


def _one_membership_two_swimmers_two_meets(api):
    """The junction's fixture: two registrations and two meets, one season."""
    ctx = _one_membership_ready_for_a_swimmer(api)
    ctx["older"] = fx.register_swimmer(
        api, ctx["membership"]["id"], ctx["season"]["id"],
        swimmer_name="Ada Older", swimmer_birthdate="2013-02-01",
        squad=Squad.SENIOR,
    )
    ctx["younger"] = fx.register_swimmer(
        api, ctx["membership"]["id"], ctx["season"]["id"],
        swimmer_name="Bo Younger", swimmer_birthdate="2017-09-01",
        squad=Squad.MINI,
    )
    ctx["meet_a"] = fx.create_meet(
        api, ctx["season"]["id"], name="June Dual Meet",
        start_iso="2027-06-12T08:00:00Z", end_iso="2027-06-12T13:00:00Z",
        expected_swimmers=40, volunteer_slots_required=4,
    )
    ctx["meet_b"] = fx.create_meet(
        api, ctx["season"]["id"], name="July Invitational",
        start_iso="2027-07-10T08:00:00Z", end_iso="2027-07-10T14:00:00Z",
        expected_swimmers=60, volunteer_slots_required=4,
    )
    return ctx


def _attempt_assignment(api, meet_id, registration_id, job_code):
    return api.create_volunteer_assignment(
        volunteer_assignment_payload(meet_id, registration_id,
                                     job_code=job_code),
        SWIM_TEAM_COACH,
    )


def _three_assignments(api, ctx):
    return {
        "a1": validate_success(
            _attempt_assignment(api, ctx["meet_a"]["id"], ctx["older"]["id"],
                                JobCode.TIMER),
            201,
        ),
        "a2": validate_success(
            _attempt_assignment(api, ctx["meet_b"]["id"], ctx["older"]["id"],
                                JobCode.SCORER),
            201,
        ),
        "a3": validate_success(
            _attempt_assignment(api, ctx["meet_a"]["id"], ctx["younger"]["id"],
                                JobCode.MARSHAL),
            201,
        ),
    }


class TestVolunteerAssignmentIsAManyToManyJunction:
    """Two foreign keys into different aggregates, and neither is a parent."""

    def test_both_directions_of_the_many_to_many_are_legal(self, api):
        """One swimmer works two meets and one meet is worked by two swimmers.

        PRD §3.6: "Volunteer jobs are taken by naming the `meet_id`, the
        `swim_team_registration_id` whose household is working the job, and a
        `job_code` of `TIMER`, `STARTER`, `CONCESSIONS`, `MARSHAL` or `SCORER`.
        Jobs are not equal: a `credit_value` of 2 is stamped for `STARTER` and for
        `SCORER`, and of 1 for `TIMER`, `CONCESSIONS` and `MARSHAL`."

        Design: Corner/entities/parent_relationships_volunteer_assignment_is_a_many_to_many_junction
        """
        ctx = _one_membership_two_swimmers_two_meets(api)

        made = _three_assignments(api, ctx)

        assert made["a1"]["credit_value"] == 1
        assert made["a2"]["credit_value"] == 2
        assert made["a3"]["credit_value"] == 1
        for assignment in made.values():
            assert is_valid_uuid(assignment["id"])

    def test_each_foreign_key_side_is_validated_independently(self, api):
        """A miss on either end returns that end's own not-found code.

        PRD §2.9: "**Existence**, for every resource addressed in the path or
        referenced by a foreign key in the payload, each with its own code:
        `ERR_SEASON_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`,
        `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_WAITLIST_ENTRY_NOT_FOUND`,
        `ERR_MEMBERSHIP_NOT_FOUND`, `ERR_GUEST_VISIT_NOT_FOUND`,
        `ERR_LIFEGUARD_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`,
        `ERR_GUARD_SHIFT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
        `ERR_MEET_NOT_FOUND`, `ERR_VOLUNTEER_ASSIGNMENT_NOT_FOUND`,
        `ERR_PARTY_RESERVATION_NOT_FOUND`, `ERR_INSPECTION_FINDING_NOT_FOUND`,
        `ERR_CONDUCT_CASE_NOT_FOUND`, `ERR_CAPITAL_PROJECT_NOT_FOUND` — all
        HTTP 404."

        Design: Corner/entities/parent_relationships_volunteer_assignment_is_a_many_to_many_junction
        """
        ctx = _one_membership_two_swimmers_two_meets(api)
        _three_assignments(api, ctx)

        validate_error(
            _attempt_assignment(api, UNKNOWN_JUNCTION_MEET, ctx["older"]["id"],
                                JobCode.TIMER),
            ApiErrorId.MEET_NOT_FOUND, 404,
        )
        validate_error(
            _attempt_assignment(api, ctx["meet_a"]["id"],
                                UNKNOWN_JUNCTION_REGISTRATION, JobCode.TIMER),
            ApiErrorId.REGISTRATION_NOT_FOUND, 404,
        )

    def test_the_junction_is_traversable_from_both_ends_and_credits_stay_home(
        self, api
    ):
        """Two rows each way, and each meet keeps its own two credits.

        PRD §3.6: "**Slots are counted in credits, not in bodies, and a new
        assignment counts the instant it is created** — it is born `ASSIGNED` and
        immediately raises the meet's `volunteer_slots_filled` by its
        `credit_value`."

        Design: Corner/entities/parent_relationships_volunteer_assignment_is_a_many_to_many_junction
        """
        ctx = _one_membership_two_swimmers_two_meets(api)
        made = _three_assignments(api, ctx)

        by_registration, reg_meta = validate_paginated(
            api.list_volunteer_assignments(
                SWIM_TEAM_COACH,
                {"swim_team_registration_id": ctx["older"]["id"]},
            )
        )
        by_meet, meet_meta = validate_paginated(
            api.list_volunteer_assignments(
                SWIM_TEAM_COACH, {"meet_id": ctx["meet_a"]["id"]}
            )
        )

        assert reg_meta["total_count"] == 2
        assert {row["id"] for row in by_registration} == {
            made["a1"]["id"], made["a2"]["id"],
        }
        assert meet_meta["total_count"] == 2
        assert {row["id"] for row in by_meet} == {
            made["a1"]["id"], made["a3"]["id"],
        }

        assert fx.read_meet(api, ctx["meet_a"]["id"])[
            "volunteer_slots_filled"] == 2
        assert fx.read_meet(api, ctx["meet_b"]["id"])[
            "volunteer_slots_filled"] == 2


class TestPaginationBoundsAreRejectedNotClamped:
    """The silent-clamp behaviour most frameworks default to is a defect here."""

    def test_three_out_of_range_arguments_are_refused_on_two_endpoints(self, api):
        """The gate is shared across list endpoints, not implemented once.

        PRD §2.3: "`limit` defaults to 10 when omitted, must be an integer, and
        must lie between a minimum of 1 and a maximum of 100 inclusive. `offset`
        defaults to 0 when omitted, must be an integer, and must be at least 0. A
        `limit` outside that range, or a negative `offset`, or a non-integer value
        for either, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422)."

        Design: Corner/entities/listing_pagination_bounds_are_rejected_not_clamped
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")

        validate_error(
            api.list_memberships(TREASURER, {"limit": 0}),
            ApiErrorId.PAGINATION_INVALID, 422,
        )
        validate_error(
            api.list_memberships(TREASURER, {"limit": 101}),
            ApiErrorId.PAGINATION_INVALID, 422,
        )
        validate_error(
            api.list_memberships(TREASURER, {"offset": -1}),
            ApiErrorId.PAGINATION_INVALID, 422,
        )
        validate_error(
            api.list_certifications(POOL_MANAGER, {"limit": 0}),
            ApiErrorId.PAGINATION_INVALID, 422,
        )

    def test_both_inclusive_bounds_succeed_and_echo_what_was_asked(self, api):
        """Limit 1 and limit 100 are both inside the range.

        PRD §2.3: "Four pagination fields appear in the `meta` object of every
        list response: `limit` (the effective page size), `offset` (the effective
        starting position), `total_count` (the number of rows matching the
        request's filters before the page window is applied) and `has_more` (true
        when rows remain beyond the current page)."

        Design: Corner/entities/listing_pagination_bounds_are_rejected_not_clamped
        """
        fx.set_clock(api, "2027-06-01T09:00:00Z")

        for limit in (1, 100):
            rows, meta = validate_paginated(
                api.list_memberships(TREASURER, {"limit": limit, "offset": 0})
            )
            assert rows == []
            assert meta["limit"] == limit
            assert meta["offset"] == 0
            assert meta["total_count"] == 0
            assert meta["has_more"] is False
