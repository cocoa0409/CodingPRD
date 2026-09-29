"""Resource registry behaviour: creation shapes, defaults, computed and system
fields, read paths, listing windows, type and range constraints, immutable
reference rows, and the existence ladder on parent and foreign-key references.

Every test builds its own preconditions through the declared endpoints only and
pins the logical clock as its first call.
"""

from test_helpers import (
    CLOCK_DEFAULT,
    DEFAULT_LIMIT,
    DEFAULT_OFFSET,
    FILM_BUDGET,
    FILM_CAST_SCORE,
    NON_EXISTENT_UUID,
    TERRITORY_DE_INDEX,
    agreement_payload,
    assert_buyer_exposure,
    assert_common_fields,
    assert_created,
    assert_empty_collection,
    assert_facility_figures,
    assert_film_counters,
    assert_instant,
    assert_list_response,
    assert_money,
    assert_object_response,
    assert_page_window,
    assert_reference_row,
    buyer_payload,
    comparable_payload,
    facility_payload,
    film_amendment_payload,
    film_payload,
    make_film,
    make_head_of_sales_headers,
    make_lender_headers,
    make_market,
    make_platform_admin_headers,
    make_sales_agent_headers,
    make_territory,
    market_payload,
    pin_clock,
    screening_slot_payload,
    territory_payload,
    valuation_payload,
    validate_error,
)


class TestFilmRegistration:
    def test_registration_seeds_every_derived_slate_counter(self, api):
        """Registering a picture returns the seeded slate counters, not nulls.

        PRD: "Registration sets the picture's `sales_status` to `DEVELOPMENT` and initialises the derived slate counters that the rest of the system will maintain: `total_mg_committed_usd` and `total_mg_collected_usd` both start at 0.00, `published_territory_count` and `licensed_territory_count` both start at 0, and `financing_gap_usd` starts equal to the full `production_budget_usd`, because at this point nothing at all has been pre-sold."

        Design: Corner/entities/film_create_returns_every_declared_field_and_zeroed_slate_counters
        """
        pin_clock(api, CLOCK_DEFAULT)

        response = api.create_film(
            film_payload(completion_status="IN_PRODUCTION"), make_platform_admin_headers()
        )
        film = assert_created(response)

        assert film["title"] == "Northern Lights"
        assert film["genre"] == "ACTION"
        assert_film_counters(
            film,
            committed=0.00,
            collected=0.00,
            gap=24000000.00,
            published_count=0,
            licensed_count=0,
            sales_status="DEVELOPMENT",
        )

    def test_registration_honours_the_supplied_completion_status_and_starts_at_version_one(
        self, api
    ):
        """A supplied completion_status is kept and the row opens at version 1.

        PRD: "Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each successful mutation of that row."

        Design: Corner/entities/film_create_returns_every_declared_field_and_zeroed_slate_counters
        """
        pin_clock(api, CLOCK_DEFAULT)

        film = assert_created(
            api.create_film(
                film_payload(completion_status="IN_PRODUCTION"),
                make_platform_admin_headers(),
            )
        )

        assert film["completion_status"] == "IN_PRODUCTION"
        assert film["version"] == 1
        assert_common_fields(film, "Film")

    def test_reading_a_film_returns_the_stored_row_without_advancing_version(self, api):
        """A read echoes the stored production facts and never counts as a mutation.

        PRD: "Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each successful mutation of that row."

        Design: Corner/entities/film_retrieval_returns_the_stored_row_byte_for_byte
        """
        pin_clock(api, CLOCK_DEFAULT)
        created = make_film(api)

        film = assert_object_response(api.get_film(created["id"], make_sales_agent_headers()))

        assert film["principal_cast_score"] == FILM_CAST_SCORE
        assert_money(film["production_budget_usd"], FILM_BUDGET, "production_budget_usd")
        assert film["completion_status"] == "SCRIPT"
        assert film["version"] == 1


class TestFilmListing:
    def _three_films(self, api):
        pin_clock(api, CLOCK_DEFAULT)
        make_film(api, title="Alpha", genre="ACTION", production_budget_usd=10000000.00)
        make_film(api, title="Beta", genre="DRAMA", production_budget_usd=8000000.00)
        make_film(api, title="Gamma", genre="ACTION", production_budget_usd=12000000.00)

    def test_page_window_reports_total_count_and_has_more(self, api):
        """total_count counts all matching rows while has_more tracks the window.

        PRD: "For list responses the `meta` object carries four pagination fields: `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filter before the page window is applied, and `has_more` indicating whether any row remains beyond the current page."

        Design: Corner/entities/film_listing_paginates_with_total_count_has_more_and_a_genre_filter
        """
        self._three_films(api)

        first_rows, first_meta = assert_list_response(
            api.list_films(make_sales_agent_headers(), {"limit": 2, "offset": 0}),
            expected_total=3,
            expected_rows=2,
        )
        assert_page_window(first_meta, limit=2, offset=0, total_count=3, has_more=True)

        second_rows, second_meta = assert_list_response(
            api.list_films(make_sales_agent_headers(), {"limit": 2, "offset": 2}),
            expected_total=3,
            expected_rows=1,
        )
        assert_page_window(second_meta, limit=2, offset=2, total_count=3, has_more=False)

        first_ids = {row["id"] for row in first_rows}
        assert second_rows[0]["id"] not in first_ids

    def test_omitted_pagination_parameters_fall_back_to_the_declared_defaults(self, api):
        """With no window supplied the effective limit is 10 and the offset 0.

        PRD: "`limit` controls page size: it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100."

        Design: Corner/entities/film_listing_paginates_with_total_count_has_more_and_a_genre_filter
        """
        self._three_films(api)

        rows, meta = assert_list_response(
            api.list_films(make_sales_agent_headers()), expected_total=3, expected_rows=3
        )
        assert_page_window(
            meta,
            limit=DEFAULT_LIMIT,
            offset=DEFAULT_OFFSET,
            total_count=3,
            has_more=False,
        )
        assert len(rows) == 3


class TestExistenceLadder:
    def test_unknown_film_id_on_a_read_reports_the_film_specific_not_found_code(self, api):
        """A well-formed but unregistered film id yields the domain 404 code.

        PRD: "A film referenced by path or by a body `film_id` must exist, else `ERR_FILM_NOT_FOUND`; then a territory referenced by path or by a body `territory_id`, else `ERR_TERRITORY_NOT_FOUND`; then a market referenced by path or by a body `market_id`, else `ERR_MARKET_NOT_FOUND`; then a buyer referenced by path or by a body `buyer_id`, else `ERR_BUYER_NOT_FOUND`; then a pre-sale contract referenced by path, else `ERR_CONTRACT_NOT_FOUND`; then a territory valuation, else `ERR_VALUATION_NOT_FOUND`; then a sales agency agreement, else `ERR_AGREEMENT_NOT_FOUND`; then a payment milestone, else `ERR_MILESTONE_NOT_FOUND`; then a deliverable package, else `ERR_PACKAGE_NOT_FOUND`; then a banking facility, else `ERR_FACILITY_NOT_FOUND`; then a collection account, else `ERR_ACCOUNT_NOT_FOUND`; and finally a screening slot or buyer meeting referenced by path, either of which when unresolvable yields `ERR_MARKET_ITEM_NOT_FOUND`."

        Design: Corner/entities/film_read_with_an_unknown_uuid_returns_film_not_found
        """
        pin_clock(api, CLOCK_DEFAULT)
        make_film(api)

        response = api.get_film(NON_EXISTENT_UUID, make_sales_agent_headers())

        validate_error(response, "ERR_FILM_NOT_FOUND", 404)
        assert response.json()["response_type"] == "error"


class TestRequiredInputFields:
    def test_market_creation_without_the_inventory_counts_is_rejected_and_persists_nothing(
        self, api
    ):
        """Omitting the two inventory counts is malformed, not silently defaulted.

        PRD: "Every required body field present, every enum value a member of its declared set, every number inside its declared range, and every end-or-close instant strictly after its start counterpart, else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/market_create_missing_required_inventory_fields_returns_invalid_request
        """
        pin_clock(api, CLOCK_DEFAULT)

        response = api.create_market(
            market_payload(
                name="EFM Berlin",
                city="Berlin",
                start_date="2027-02-11T00:00:00Z",
                end_date="2027-02-17T00:00:00Z",
                screening_room_count=None,
                meeting_table_count=None,
            ),
            make_platform_admin_headers(),
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        assert_empty_collection(api.list_markets(make_platform_admin_headers()))


class TestCreationDefaults:
    def test_film_completion_status_and_comparable_verified_take_their_declared_defaults(
        self, api
    ):
        """An omitted completion_status is SCRIPT and an omitted verified flag is false.

        PRD: "A `completion_status` may optionally be supplied to record physical production progress; when omitted it defaults to `SCRIPT`."

        PRD: "A `verified` flag may be supplied and defaults to false; it is set true only once the datapoint has been confirmed against a signed contract."

        Design: Corner/entities/creation_defaults_apply_on_film_buyer_comparable_and_facility
        """
        pin_clock(api, CLOCK_DEFAULT)
        territory = make_territory(api)

        film = assert_created(
            api.create_film(film_payload(), make_platform_admin_headers())
        )
        comparable = assert_created(
            api.create_comparable_title(
                territory["id"],
                comparable_payload(800000.00, 2022, name="Comp Alpha", verified=None),
                make_platform_admin_headers(),
            )
        )

        assert film["completion_status"] == "SCRIPT"
        assert comparable["verified"] is False

    def test_buyer_status_defaults_to_active_with_both_exposure_figures_at_zero(self, api):
        """An onboarded distributor trades as ACTIVE and carries no exposure yet.

        PRD: "A trading `status` may optionally be supplied and defaults to `ACTIVE`. Both denormalised exposure figures, `outstanding_exposure_usd` and `net_unpaid_exposure_usd`, start at 0.00."

        Design: Corner/entities/creation_defaults_apply_on_film_buyer_comparable_and_facility
        """
        pin_clock(api, CLOCK_DEFAULT)
        territory = make_territory(api)

        buyer = assert_created(
            api.create_buyer(
                territory["id"],
                buyer_payload(company_name="Rhein Films"),
                make_platform_admin_headers(),
            )
        )

        assert buyer["status"] == "ACTIVE"
        assert_buyer_exposure(buyer, gross=0.00, net=0.00)

    def test_facility_bond_requirement_defaults_to_true_on_a_zeroed_proposed_row(self, api):
        """The one default whose value is true survives, alongside the zeroed figures.

        PRD: "A `completion_bond_required` flag may be supplied and defaults to true. A new facility has `status` `PROPOSED`, `completion_bond_posted` false, `bond_provider` and `bond_amount_usd` null, and `eligible_collateral_usd`, `advance_amount_usd`, `drawn_amount_usd` and `outstanding_debt_usd` all 0.00."

        Design: Corner/entities/creation_defaults_apply_on_film_buyer_comparable_and_facility
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api)

        facility = assert_created(
            api.create_banking_facility(
                film["id"],
                facility_payload(completion_bond_required=None),
                make_lender_headers(),
            )
        )

        assert facility["completion_bond_required"] is True
        assert facility["completion_bond_posted"] is False
        assert facility["bond_provider"] is None
        assert facility["bond_amount_usd"] is None
        assert_facility_figures(
            facility,
            collateral=0.00,
            advance=0.00,
            drawn=0.00,
            outstanding=0.00,
            status="PROPOSED",
        )


class TestComputedAndSystemFields:
    def test_smuggled_counter_and_version_values_in_the_create_body_are_ignored(self, api):
        """Derived slate figures and the write counter are owned by the server.

        PRD: "Those five counters are never client-settable and each has an exact definition."

        PRD: "Most resources additionally carry `updated_at` — same format as `created_at`, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each successful mutation of that row."

        Design: Corner/entities/film_create_computed_and_system_field_input_ignored
        """
        pin_clock(api, CLOCK_DEFAULT)

        film = assert_created(
            api.create_film(
                film_payload(
                    sales_status="IN_MARKET", financing_gap_usd=1.00, version=99
                ),
                make_platform_admin_headers(),
            )
        )

        assert film["sales_status"] == "DEVELOPMENT"
        assert_money(film["financing_gap_usd"], 24000000.00, "financing_gap_usd")
        assert film["version"] == 1
        assert film["published_territory_count"] == 0
        assert film["licensed_territory_count"] == 0

    def test_an_amendment_advances_version_to_two_and_restamps_updated_at(self, api):
        """version counts writes while created_at stays at the insert instant.

        PRD: "Each amendment is available to `PlatformAdmin` alone, increments the picture's `version` by 1, and refreshes `updated_at`."

        PRD: "Time in this system is a **logical clock**, not wall-clock time."

        Design: Corner/entities/film_system_fields_are_server_generated_and_version_advances_on_write
        """
        pin_clock(api, CLOCK_DEFAULT)
        created = make_film(api)
        assert created["version"] == 1

        pin_clock(api, "2026-08-02T00:00:00Z")
        patched = assert_object_response(
            api.patch_film(
                created["id"],
                film_amendment_payload(completion_status="POST"),
                make_platform_admin_headers(),
            )
        )

        assert patched["version"] == 2
        assert_instant(patched["created_at"], created["created_at"], "created_at")
        assert_instant(patched["updated_at"], "2026-08-02T00:00:00Z", "updated_at")
        assert patched["completion_status"] == "POST"


class TestFieldConstraints:
    def test_film_creation_rejects_an_out_of_set_genre_and_an_out_of_range_cast_score(
        self, api
    ):
        """Both a foreign enum member and a score above 100 are malformed requests.

        PRD: "Every required body field present, every enum value a member of its declared set, every number inside its declared range, and every end-or-close instant strictly after its start counterpart, else `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD: "A film's `genre` is one of `ACTION`, `DRAMA`, `COMEDY`, `THRILLER` or `DOCUMENTARY`, and a comparable title's `genre` draws from the same set."

        Design: Corner/entities/entity_field_type_and_range_constraints_are_rejected_at_creation
        """
        pin_clock(api, CLOCK_DEFAULT)
        make_film(api)

        bad_genre = api.create_film(
            film_payload(
                title="Bad Genre", genre="SCI_FI", production_budget_usd=1000000.00,
                principal_cast_score=50,
            ),
            make_platform_admin_headers(),
        )
        bad_score = api.create_film(
            film_payload(
                title="Bad Cast", production_budget_usd=1000000.00,
                principal_cast_score=101,
            ),
            make_platform_admin_headers(),
        )

        validate_error(bad_genre, "ERR_INVALID_REQUEST", 400)
        validate_error(bad_score, "ERR_INVALID_REQUEST", 400)
        assert_list_response(
            api.list_films(make_platform_admin_headers()), expected_total=1
        )

    def test_territory_index_and_commission_rate_outside_their_bounds_are_rejected(self, api):
        """A base value index of 3.00 and a commission of 0.30 both breach their ranges.

        PRD: "A `PlatformAdmin` creates each one with a `code` — a 2-to-3-letter uppercase identifier that must be unique across every territory in the system, with a duplicate rejected as `ERR_TERRITORY_CODE_TAKEN` — a human-readable `name`, a `region` grouping, a `market_tier` between 1 and 3 inclusive where 1 denotes a major territory, a `currency_code` naming the local settlement currency for information only, and a `base_value_index` between 0.10 and 2.00 inclusive."

        PRD: "A `HeadOfSales` drafts a **sales agency agreement** against the picture, supplying `commission_pct` — the base commission rate on gross receipts, which must be strictly greater than 0 and at most 0.25 — together with `expense_cap_usd`, the hard ceiling on recoupable sales expenses, `term_months`, the length of the term of representation in whole months which must be at least 6, and `term_start_date`, the first instant of that term."

        Design: Corner/entities/entity_field_type_and_range_constraints_are_rejected_at_creation
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api)

        bad_index = api.create_territory(
            territory_payload(code="FR", name="France", base_value_index=3.00),
            make_platform_admin_headers(),
        )
        bad_commission = api.create_agency_agreement(
            film["id"],
            agreement_payload(commission_pct=0.30),
            make_head_of_sales_headers(),
        )

        validate_error(bad_index, "ERR_INVALID_REQUEST", 400)
        validate_error(bad_commission, "ERR_INVALID_REQUEST", 400)
        assert_empty_collection(api.list_territories(make_platform_admin_headers()))

    def test_market_whose_end_date_equals_its_start_date_is_rejected_and_not_stored(
        self, api
    ):
        """A closing instant must be strictly after its opening counterpart.

        PRD: "Every required body field present, every enum value a member of its declared set, every number inside its declared range, and every end-or-close instant strictly after its start counterpart, else `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/entity_field_type_and_range_constraints_are_rejected_at_creation
        """
        pin_clock(api, CLOCK_DEFAULT)

        response = api.create_market(
            market_payload(
                name="EFM Berlin",
                city="Berlin",
                start_date="2027-02-11T00:00:00Z",
                end_date="2027-02-11T00:00:00Z",
                screening_room_count=3,
                meeting_table_count=4,
            ),
            make_platform_admin_headers(),
        )

        validate_error(response, "ERR_INVALID_REQUEST", 400)
        assert_empty_collection(api.list_markets(make_platform_admin_headers()))


class TestReferenceRows:
    def test_territories_and_comparable_titles_carry_no_version_and_no_updated_at(self, api):
        """Reference data is written once and exposes neither audit column.

        PRD: "Three resource types are the exception and deliberately carry only `id` and `created_at`, with neither `updated_at` nor `version` present in their payloads at all: territories, comparable titles, and distribution runs."

        Design: Corner/entities/territory_and_comparable_title_are_immutable_rows_without_version
        """
        pin_clock(api, CLOCK_DEFAULT)
        created = make_territory(api)
        api.create_comparable_title(
            created["id"],
            comparable_payload(800000.00, 2022, name="Comp Alpha"),
            make_platform_admin_headers(),
        )

        territory = assert_object_response(
            api.get_territory(created["id"], make_sales_agent_headers())
        )
        comparables, _meta = assert_list_response(
            api.list_comparable_titles(created["id"], make_sales_agent_headers()),
            expected_total=1,
            expected_rows=1,
        )

        assert_reference_row(territory, "Territory")
        for field in ("code", "name", "region", "market_tier", "currency_code"):
            assert field in territory, f"the territory payload is missing {field}"
        assert territory["base_value_index"] == TERRITORY_DE_INDEX
        assert_reference_row(comparables[0], "ComparableTitle")


class TestForeignKeyResolution:
    def test_screening_slot_creation_reports_the_first_unresolved_reference_in_order(
        self, api
    ):
        """Each dangling reference names its own resource, ahead of any state check.

        PRD: "A film referenced by path or by a body `film_id` must exist, else `ERR_FILM_NOT_FOUND`; then a territory referenced by path or by a body `territory_id`, else `ERR_TERRITORY_NOT_FOUND`; then a market referenced by path or by a body `market_id`, else `ERR_MARKET_NOT_FOUND`; then a buyer referenced by path or by a body `buyer_id`, else `ERR_BUYER_NOT_FOUND`; then a pre-sale contract referenced by path, else `ERR_CONTRACT_NOT_FOUND`; then a territory valuation, else `ERR_VALUATION_NOT_FOUND`; then a sales agency agreement, else `ERR_AGREEMENT_NOT_FOUND`; then a payment milestone, else `ERR_MILESTONE_NOT_FOUND`; then a deliverable package, else `ERR_PACKAGE_NOT_FOUND`; then a banking facility, else `ERR_FACILITY_NOT_FOUND`; then a collection account, else `ERR_ACCOUNT_NOT_FOUND`; and finally a screening slot or buyer meeting referenced by path, either of which when unresolvable yields `ERR_MARKET_ITEM_NOT_FOUND`."

        Design: Corner/entities/child_creation_against_an_unknown_parent_returns_that_parents_not_found_code
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api)
        market = make_market(
            api,
            name="EFM Berlin",
            city="Berlin",
            start_date="2027-02-11T00:00:00Z",
            end_date="2027-02-17T00:00:00Z",
            screening_room_count=3,
            meeting_table_count=4,
        )

        unknown_market = api.create_screening_slot(
            screening_slot_payload(
                NON_EXISTENT_UUID,
                film["id"],
                1,
                "2027-02-12T09:00:00Z",
                "2027-02-12T11:00:00Z",
                capacity=60,
            ),
            make_sales_agent_headers(),
        )
        unknown_film = api.create_screening_slot(
            screening_slot_payload(
                market["id"],
                NON_EXISTENT_UUID,
                1,
                "2027-02-12T09:00:00Z",
                "2027-02-12T11:00:00Z",
                capacity=60,
            ),
            make_sales_agent_headers(),
        )
        unknown_territory = api.create_comparable_title(
            NON_EXISTENT_UUID,
            comparable_payload(800000.00, 2022, name="Orphan Comp"),
            make_platform_admin_headers(),
        )

        validate_error(unknown_market, "ERR_MARKET_NOT_FOUND", 404)
        validate_error(unknown_film, "ERR_FILM_NOT_FOUND", 404)
        validate_error(unknown_territory, "ERR_TERRITORY_NOT_FOUND", 404)
        assert_empty_collection(api.list_screening_slots(make_sales_agent_headers()))

    def test_valuation_creation_names_the_film_first_when_both_references_dangle(self, api):
        """With both body references unknown the film check reports first.

        PRD: "A film referenced by path or by a body `film_id` must exist, else `ERR_FILM_NOT_FOUND`; then a territory referenced by path or by a body `territory_id`, else `ERR_TERRITORY_NOT_FOUND`; then a market referenced by path or by a body `market_id`, else `ERR_MARKET_NOT_FOUND`; then a buyer referenced by path or by a body `buyer_id`, else `ERR_BUYER_NOT_FOUND`; then a pre-sale contract referenced by path, else `ERR_CONTRACT_NOT_FOUND`; then a territory valuation, else `ERR_VALUATION_NOT_FOUND`; then a sales agency agreement, else `ERR_AGREEMENT_NOT_FOUND`; then a payment milestone, else `ERR_MILESTONE_NOT_FOUND`; then a deliverable package, else `ERR_PACKAGE_NOT_FOUND`; then a banking facility, else `ERR_FACILITY_NOT_FOUND`; then a collection account, else `ERR_ACCOUNT_NOT_FOUND`; and finally a screening slot or buyer meeting referenced by path, either of which when unresolvable yields `ERR_MARKET_ITEM_NOT_FOUND`."

        Design: Corner/entities/valuation_creation_validates_both_foreign_keys_in_declared_priority_order
        """
        pin_clock(api, CLOCK_DEFAULT)
        film = make_film(api)
        make_territory(api)

        unknown_territory = api.create_valuation(
            valuation_payload(film["id"], NON_EXISTENT_UUID),
            make_sales_agent_headers(),
        )
        both_unknown = api.create_valuation(
            valuation_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
            make_sales_agent_headers(),
        )

        validate_error(unknown_territory, "ERR_TERRITORY_NOT_FOUND", 404)
        validate_error(both_unknown, "ERR_FILM_NOT_FOUND", 404)
        assert_empty_collection(api.list_valuations(make_sales_agent_headers()))


class TestUniqueness:
    def test_a_second_territory_with_the_same_code_conflicts_and_leaves_the_first_intact(
        self, api
    ):
        """A duplicate code is a conflict, and the original row keeps its values.

        PRD: "A `PlatformAdmin` creates each one with a `code` — a 2-to-3-letter uppercase identifier that must be unique across every territory in the system, with a duplicate rejected as `ERR_TERRITORY_CODE_TAKEN` — a human-readable `name`, a `region` grouping, a `market_tier` between 1 and 3 inclusive where 1 denotes a major territory, a `currency_code` naming the local settlement currency for information only, and a `base_value_index` between 0.10 and 2.00 inclusive."

        Design: Corner/entities/territory_code_uniqueness_rejects_a_second_row_with_the_same_code
        """
        pin_clock(api, CLOCK_DEFAULT)
        first = make_territory(api)

        duplicate = api.create_territory(
            territory_payload(
                name="Germany duplicate", market_tier=2, base_value_index=0.90
            ),
            make_platform_admin_headers(),
        )

        validate_error(duplicate, "ERR_TERRITORY_CODE_TAKEN", 409)
        stored = assert_object_response(
            api.get_territory(first["id"], make_platform_admin_headers())
        )
        assert stored["name"] == "Germany"
        assert stored["market_tier"] == 1
        assert stored["base_value_index"] == TERRITORY_DE_INDEX
        assert_list_response(
            api.list_territories(make_platform_admin_headers()), expected_total=1
        )
