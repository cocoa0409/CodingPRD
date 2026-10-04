"""Entity shapes: creation, computed fields, defaults, pagination, lookups.

Contract creation computes ``end_date`` and stamps the full common field set
(PRD 2.6, 3.1); ``term_months`` must divide by twelve; a season's
``month_offset`` derives from the contract start; list endpoints paginate
with a filtered ``total_count`` (PRD 2.3); unknown ids yield the
entity-specific 404; missing required fields yield 400; and child foreign
references resolve only within their own contract (PRD 2.5, 3.10).
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONTRACT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SEASON_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_instant,
    assert_reservation,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    active_contract,
    add_room_class,
    add_season,
    add_study,
    approve_filing,
    book_reservation,
    bookable_inventory,
    create_contract,
    reset_clock,
    submit_filing,
)
from test_helpers.test_users import (
    FRONT_DESK,
    OFFICER,
    OPS_MANAGER,
    RATE_MANAGER,
)

UNKNOWN_CONTRACT = "00000000-0000-4000-8000-000000000000"


class TestContractCreation:
    def test_create_returns_all_fields_and_a_computed_end_date(self, client):
        """PRD 3.1: "From `start_date` and `term_months` the server computes
        `end_date` by advancing the start date by the full term in months. A
        new contract begins life in `DRAFT` status."

        Design: Corner/entities/contract_create_returns_all_fields_and_computed_end_date
        """
        reset_clock(client)
        response = client.create_contract(
            f.contract_payload(
                contract_number="YELL-100", term_months=24,
                start_date="2027-01-01T00:00:00Z",
                franchise_fee_rate=0.04, employee_housing_capacity=60,
                environmental_plan_due_day_of_year=45,
            ),
            headers=OFFICER,
        )
        contract = validate_success(response, expected_status=201)
        assert contract["status"] == C.CONTRACT_DRAFT
        assert contract["version"] == 1
        assert_instant(contract["end_date"], "2029-01-01T00:00:00Z",
                       "computed end_date")
        assert_common_fields(contract, "contract")

    def test_non_multiple_of_twelve_term_months_is_an_invalid_request(
        self, client
    ):
        """PRD 3.1: "The term must be a positive whole number of years:
        `term_months` must be greater than zero and evenly divisible by
        twelve."

        Design: Corner/entities/contract_create_with_non_multiple_of_12_term_rejected
        """
        reset_clock(client)
        response = client.create_contract(
            f.contract_payload(contract_number="YELL-101", term_months=18),
            headers=OFFICER,
        )
        validate_error(response, ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(client.list_contracts(headers=OFFICER))
        assert meta["total_count"] == 0, "no contract row may exist"

    def test_server_mints_id_and_timestamps(self, client):
        """PRD 2.6: "The `id` is a server-minted UUID string with no type
        prefix. The `created_at` is an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created ... The
        `version` is an integer starting at one that increments by one on
        every mutation of the resource."

        Design: Corner/entities/system_fields_id_and_timestamps_are_server_generated
        """
        reset_clock(client)
        contract = validate_success(
            client.create_contract(
                f.contract_payload(contract_number="GRCA-104",
                                   franchise_fee_rate=0.04),
                headers=OFFICER,
            ),
            expected_status=201,
        )
        assert is_valid_uuid(contract["id"])
        assert_instant(contract["created_at"], "2026-09-01T00:00:00Z",
                       "created_at follows the logical clock")
        assert contract["version"] == 1


class TestSeasonComputedFields:
    def test_month_offset_derives_from_the_contract_start(self, client):
        """PRD 3.1: "The server derives each season's `month_offset`, the
        whole number of months elapsed between the contract's `start_date`
        and the season's `open_date`, rounded down. New seasons begin
        `PLANNED`."

        Design: Corner/entities/season_get_returns_computed_month_offset
        """
        reset_clock(client)
        contract = create_contract(client, contract_number="YELL-103")
        season = add_season(client, contract["id"])
        reread = validate_success(client.get_season(
            contract["id"], season["id"], headers=OPS_MANAGER
        ))
        assert reread["month_offset"] == 5, (
            "2027-01-01 -> 2027-06-01 is exactly five months"
        )
        assert reread["status"] == C.SEASON_PLANNED


class TestReservationListingPagination:
    def test_total_count_is_the_filtered_total_not_the_page_size(self, client):
        """PRD 2.3: "The `meta` object of every list response carries
        `limit`, `offset`, `total_count`, and `has_more`, where `total_count`
        is the full count of matching resources and `has_more` reports
        whether further items exist beyond the returned page."

        Design: Corner/entities/reservations_list_paginates_with_total_count_and_has_more
        """
        scenario = bookable_inventory(client)
        contract_id = scenario["contract"]["id"]
        from test_helpers.fixtures import contract_version
        for guest, check_in, check_out in (
            ("g-1", "2027-07-10T00:00:00Z", "2027-07-11T00:00:00Z"),
            ("g-2", "2027-07-11T00:00:00Z", "2027-07-12T00:00:00Z"),
            ("g-3", "2027-07-12T00:00:00Z", "2027-07-13T00:00:00Z"),
        ):
            book_reservation(
                client, contract_id,
                scenario["season"]["id"], scenario["room_class"]["id"],
                contract_version(client, contract_id, headers=FRONT_DESK),
                guest_ref=guest, check_in_date=check_in, check_out_date=check_out,
            )
        page1, meta1 = validate_paginated(client.list_reservations(
            contract_id, headers=FRONT_DESK,
            params={"season_id": scenario["season"]["id"], "limit": 2,
                    "offset": 0},
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(client.list_reservations(
            contract_id, headers=FRONT_DESK,
            params={"season_id": scenario["season"]["id"], "limit": 2,
                    "offset": 2},
        ))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for row in page1 + page2:
            assert_reservation(row)


class TestNotFoundAndRequiredFields:
    def test_unknown_contract_id_returns_contract_not_found(self, client):
        """PRD 2.5: "the contract identifier is resolved first (an unknown
        one yields `ERR_CONTRACT_NOT_FOUND`)".

        Design: Corner/entities/contract_get_unknown_id_returns_contract_not_found
        """
        reset_clock(client)
        response = client.get_contract(UNKNOWN_CONTRACT, headers=FRONT_DESK)
        error = validate_error(response, ERR_CONTRACT_NOT_FOUND)
        assert error.get("message"), "the error envelope must carry a message"

    def test_filing_create_without_submitted_rates_is_an_invalid_request(
        self, client
    ):
        """PRD 3.2: "a `ConcessionerRateManager` submits a rate filing naming
        the `season_id` and `room_class_id` it covers, the
        `reference_study_id` it cites, and the `submitted_rates` — an array
        of exactly three entries, one for each occupancy band `SOLO`,
        `DOUBLE`, and `FAMILY`, each entry carrying a positive
        `nightly_rate_cents`."

        Design: Corner/entities/filing_create_missing_submitted_rates_returns_invalid_request
        """
        scenario = bookable_inventory(client, clock=None)
        contract_id = scenario["contract"]["id"]
        from test_helpers.fixtures import contract_version
        _rows_before, meta_before = validate_paginated(client.list_filings(
            contract_id, headers=RATE_MANAGER
        ))
        payload = {
            "season_id": scenario["season"]["id"],
            "room_class_id": scenario["room_class"]["id"],
            "reference_study_id": scenario["study"]["id"],
            "expected_contract_version": contract_version(
                client, contract_id, headers=RATE_MANAGER
            ),
        }
        response = client.create_filing(contract_id, payload, headers=RATE_MANAGER)
        validate_error(response, ERR_INVALID_REQUEST)
        rows, meta = validate_paginated(client.list_filings(
            contract_id, headers=RATE_MANAGER
        ))
        assert meta["total_count"] == meta_before["total_count"], (
            "the rejected creation may not add a filing row"
        )


class TestChildReferencesResolveWithinTheirContract:
    def test_a_filing_citing_another_contracts_season_is_not_found(self, client):
        """PRD 2.10: "Existence checks follow — path identifiers are resolved
        left to right, and then foreign references in the request body (the
        season, room class, comparability study, service line, housing unit,
        or revision filing a payload names) are verified to exist within the
        same contract."

        Design: Corner/entities/filing_belongs_to_its_own_contract_not_another
        """
        reset_clock(client)
        c1, _s1, _lines1 = active_contract(client, contract_number="YELL-105A")
        c2 = create_contract(client, contract_number="GRCA-105B")
        other_season = add_season(client, c2["id"])
        room_class = add_room_class(client, c1["id"])
        study = add_study(client, c1["id"])
        from test_helpers.fixtures import contract_version
        payload = f.filing_payload(
            other_season["id"], room_class["id"], study["id"],
            contract_version(client, c1["id"], headers=RATE_MANAGER),
        )
        response = client.create_filing(c1["id"], payload, headers=RATE_MANAGER)
        validate_error(response, ERR_SEASON_NOT_FOUND)
