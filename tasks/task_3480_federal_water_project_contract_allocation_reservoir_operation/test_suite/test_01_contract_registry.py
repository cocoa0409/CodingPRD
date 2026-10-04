"""Contract registry, project seeding, and authentication-tier tests.

Covers contract creation shape (required fields, enums, system-managed
fields), retrieval round-trip, list filtering with pagination, foreign-key
and duplicate-key rejections, the singleton reservoir rule, the version
increment on suspension, and the missing-credentials rejection - PRD §2.1,
§2.3, §2.5, §2.8, §2.9 and §3.1.
"""

from test_helpers import (
    ApiErrorId,
    FINANCE_OFFICER_HEADERS,
    NON_EXISTENT_UUID,
    RECLAMATION_OPERATOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    assert_water_contract,
    canonical_instant,
    factories,
    fixtures,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    validate_error,
    validate_paginated,
    validate_success,
)

READ = RECLAMATION_OPERATOR_HEADERS


def test_contract_create_returns_201_with_system_fields_and_active_status(api):
    """A contract created with the five required inputs returns 201 carrying
    ACTIVE status, zero repaid credits, version 1 and minted identity fields.

    PRD §3.1: "The contract's `repaid_credits_cents`, the hydropower revenue
    credits applied so far, starts at zero and grows only when a revenue
    period settles; its `status` starts `ACTIVE`."
    PRD §4: "Operations that create a new resource return `201 Created`"

    Design: Corner/entities/contract_create_returns_201_with_system_fields_and_active_status
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    district = fixtures.create_district(api)

    response = api.create_contract(factories.contract_payload(district["id"]), SYSTEM_ADMIN_HEADERS)
    contract = validate_success(response, 201)

    assert_water_contract(contract)
    assert contract["status"] == "ACTIVE", f"new contract must start ACTIVE, got {contract['status']}"
    assert contract["repaid_credits_cents"] == 0
    assert contract["version"] == 1
    assert contract["contract_number"] == "C-100"
    assert contract["district_id"] == district["id"]


def test_contract_get_round_trips_stored_fields_immediately(api):
    """GET returns exactly what POST stored, in the same logical instant.

    PRD §3.1: "A `SystemAdmin` executes each contract with the contracting
    `district_id`, a unique `contract_number` string (a duplicate is refused
    with `ERR_DUPLICATE_CONTRACT_NUMBER`), a `priority_class` of either
    `SENIOR` or `JUNIOR`"

    Design: Corner/entities/contract_get_round_trips_stored_fields_immediately
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    district = fixtures.create_district(api)
    created = fixtures.create_contract(api, district["id"])

    fetched = validate_success(api.get_contract(created["id"], FINANCE_OFFICER_HEADERS))

    assert fetched["district_id"] == district["id"]
    assert fetched["contract_number"] == "C-100"
    assert fetched["priority_class"] == "SENIOR"
    assert fetched["max_annual_quantity_af"] == 6_000
    assert fetched["repayment_obligation_cents"] == 120_000_000
    assert fetched["status"] == "ACTIVE"
    assert fetched["repaid_credits_cents"] == 0


def test_contracts_list_filters_by_district_and_paginates_with_totals(api):
    """district_id and priority_class filters select exact subsets, and
    limit/offset pages report the filtered totals with has_more flips.

    PRD §3.1: "The contract collection can be listed with filters on
    `district_id`, `status`, and `priority_class`."
    PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response envelope."

    Design: Corner/entities/contracts_list_filters_by_district_and_paginates_with_totals
    """
    world = fixtures.setup_project(api, reservoir_profile=None, contract_plan="standard_with_third")
    third = world["contract_tp"]

    page1, meta1 = validate_paginated(api.list_contracts(READ, {"limit": 2, "offset": 0}))
    assert len(page1) == 2 and meta1["total_count"] == 3 and meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_contracts(READ, {"limit": 2, "offset": 2}))
    assert len(page2) == 1 and meta2["total_count"] == 3 and meta2["has_more"] is False

    by_district, _ = validate_paginated(api.list_contracts(READ, {"district_id": world["district_tp"]["id"]}))
    assert [row["id"] for row in by_district] == [third["id"]]

    juniors, _ = validate_paginated(api.list_contracts(READ, {"priority_class": "JUNIOR"}))
    assert len(juniors) == 2, f"expected the two JUNIOR contracts, got {len(juniors)}"

    everything, meta_all = validate_paginated(api.list_contracts(READ))
    assert len(everything) == 3 and meta_all["limit"] == 10 and meta_all["offset"] == 0


def test_contract_get_unknown_id_returns_not_found(api):
    """An unallocated path id yields 404 ERR_NOT_FOUND with the error envelope.

    PRD §2.8: "Identifiers appearing in a request URL are resolved strictly
    left to right: the first path identifier that does not correspond to an
    existing resource rejects the request with `ERR_NOT_FOUND` (HTTP 404),
    and the error message names the entity type that failed to resolve."

    Design: Corner/entities/contract_get_unknown_id_returns_not_found
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")

    error = validate_error(api.get_contract(NON_EXISTENT_UUID, READ), ApiErrorId.ERR_NOT_FOUND)

    assert error["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error.get("message"), str) and error["message"]


def test_contract_create_missing_required_priority_class_returns_invalid_request(api):
    """Omitting required priority_class is a 400 shape rejection; nothing persists.

    PRD §2.9: "3. **Request shape** — required fields are present, types are
    valid, enum members are valid, and ranges hold"

    Design: Corner/entities/contract_create_missing_required_priority_class_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    district = fixtures.create_district(api)

    payload = {
        "district_id": district["id"],
        "contract_number": "C-900",
        "max_annual_quantity_af": 100,
        "repayment_obligation_cents": 1000,
    }
    validate_error(api.create_contract(payload, SYSTEM_ADMIN_HEADERS), ApiErrorId.ERR_INVALID_REQUEST)

    persisted, _ = validate_paginated(api.list_contracts(READ, {"district_id": district["id"]}))
    assert persisted == [], "the rejected contract must not persist"


def test_contract_create_with_status_and_version_input_ignored(api):
    """System-managed fields in the payload are not honored: the row is
    created ACTIVE with version 1 regardless of the supplied values.

    PRD §2.5: "Every primary resource in the system carries a standard set of
    system-managed fields"
    PRD §3.1: "its `status` starts `ACTIVE`."

    Design: Corner/entities/contract_create_with_status_and_version_input_ignored
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    district = fixtures.create_district(api)

    payload = factories.contract_payload(
        district["id"],
        contract_number="C-910",
        max_annual_quantity_af=100,
        repayment_obligation_cents=1000,
        status="SUSPENDED",
        version=99,
    )
    contract = validate_success(api.create_contract(payload, SYSTEM_ADMIN_HEADERS), 201)

    assert contract["status"] == "ACTIVE", "client-supplied status must not be honored"
    assert contract["version"] == 1, "client-supplied version must not be honored"


def test_contract_create_invalid_enum_priority_class_returns_invalid_request(api):
    """priority_class is a closed enum; MIDDLE is rejected 400, not coerced.

    PRD §2.9: "3. **Request shape** — required fields are present, types are
    valid, enum members are valid, and ranges hold"
    PRD §3.1: "a `priority_class` of either `SENIOR` or `JUNIOR`"

    Design: Corner/entities/contract_create_invalid_enum_priority_class_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    district = fixtures.create_district(api)

    payload = factories.contract_payload(
        district["id"], contract_number="C-911", priority_class="MIDDLE",
        max_annual_quantity_af=100, repayment_obligation_cents=1000,
    )
    validate_error(api.create_contract(payload, SYSTEM_ADMIN_HEADERS), ApiErrorId.ERR_INVALID_REQUEST)

    persisted, _ = validate_paginated(api.list_contracts(READ, {"district_id": district["id"]}))
    assert persisted == [], "the rejected contract must not persist"


def test_contract_create_with_unknown_district_returns_not_found(api):
    """An unknown body foreign key is a 404 after shape validation passes.

    PRD §2.8: "Only after every path identifier resolves does the server
    resolve foreign-key identifiers supplied in the request body, and it does
    so in the endpoint's declared input order, rejecting the first unresolved
    one with `ERR_NOT_FOUND` in the same way."

    Design: Corner/entities/contract_create_with_unknown_district_returns_not_found
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")

    payload = factories.contract_payload(
        NON_EXISTENT_UUID, contract_number="C-912",
        max_annual_quantity_af=100, repayment_obligation_cents=1000,
    )
    validate_error(api.create_contract(payload, SYSTEM_ADMIN_HEADERS), ApiErrorId.ERR_NOT_FOUND)

    persisted, _ = validate_paginated(api.list_contracts(READ))
    assert persisted == [], "no contract may persist against a missing district"


def test_duplicate_contract_number_rejected(api):
    """contract_number is globally unique across districts.

    PRD §3.1: "a unique `contract_number` string (a duplicate is refused with
    `ERR_DUPLICATE_CONTRACT_NUMBER`)"

    Design: Corner/validations/duplicate_contract_number_rejected
    """
    world = fixtures.setup_project(api, reservoir_profile=None, contract_plan="standard")

    payload = factories.contract_payload(
        world["district_jr"]["id"], contract_number="C-100", priority_class="JUNIOR",
        max_annual_quantity_af=100, repayment_obligation_cents=1000,
    )
    validate_error(api.create_contract(payload, SYSTEM_ADMIN_HEADERS), ApiErrorId.ERR_DUPLICATE_CONTRACT_NUMBER)

    juniors, _ = validate_paginated(api.list_contracts(READ, {"district_id": world["district_jr"]["id"]}))
    assert [row["contract_number"] for row in juniors] == ["C-200"]


def test_second_reservoir_create_rejected_singleton(api):
    """The project has exactly one reservoir; a second create is refused.

    PRD §3.1: "The reservoir is a singleton: a second creation is rejected
    with `ERR_RESERVOIR_ALREADY_EXISTS`."

    Design: Corner/validations/second_reservoir_create_rejected_singleton
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir = world["reservoir"]

    payload = factories.reservoir_payload(
        name="Second Unit", capacity_af=100_000, dead_pool_af=1_000,
        flood_control_max_storage_af=50_000, initial_storage_af=10_000,
        outlet_capacity_cfs=5_000, power_conversion_mwh_per_af=0.4,
    )
    validate_error(api.create_reservoir(payload, SYSTEM_ADMIN_HEADERS), ApiErrorId.ERR_RESERVOIR_ALREADY_EXISTS)

    unchanged = validate_success(api.get_reservoir(reservoir["id"], READ))
    assert unchanged["name"] == "Shasta Unit"
    assert unchanged["capacity_af"] == 4_552_000
    assert unchanged["current_storage_af"] == 3_000_000


def test_contract_version_increments_on_suspend_mutation(api):
    """version increments by exactly one on every mutation: a contract created
    at version 1 advances to exactly 2 on suspend, with updated_at refreshed.

    PRD §2.5: "`version` (integer): a system-managed integer that increments
    by one on every mutation of the resource."
    PRD §3.1: "A `FinanceOfficer` suspends a contract, moving its `status`
    from `ACTIVE` to `SUSPENDED` and incrementing its `version`"

    Design: Corner/cross_cutting_complexity_layers/contract_version_increments_on_suspend_mutation
    """
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    district = fixtures.create_district(api)
    contract = fixtures.create_contract(api, district["id"])
    assert contract["version"] == 1

    # Advance the logical clock so the mutation instant is distinguishable
    # from the creation instant.
    fixtures.set_clock(api, "2026-10-02T00:00:00Z")
    suspended = fixtures.suspend_contract(api, contract["id"])

    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == 2, f"suspend must increment version to 2, got {suspended['version']}"
    assert canonical_instant(suspended["updated_at"]) > canonical_instant(suspended["created_at"]), (
        "updated_at must be refreshed to the mutation instant"
    )


def test_missing_auth_headers_return_unauthenticated(api):
    """Requests without the credential headers, or naming an undeclared role,
    are rejected 401 ERR_UNAUTHENTICATED before any other check.

    PRD §2.1: "A request whose headers are missing, or whose role is not one
    of these seven, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_return_unauthenticated
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]

    validate_error(api.get_reservoir(reservoir_id, headers_without_role()), ApiErrorId.ERR_UNAUTHENTICATED)
    validate_error(api.get_reservoir(reservoir_id, headers_without_user_id()), ApiErrorId.ERR_UNAUTHENTICATED)
    validate_error(
        api.get_reservoir(reservoir_id, headers_with_undeclared_role()),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )
