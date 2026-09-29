"""Community and homesite registry: creation, retrieval, listing, defaults and rejections."""

from test_helpers import (
    ApiErrorId,
    assert_absorption_review,
    assert_community,
    assert_homesite,
    assert_instant_equals,
    assert_newly_created,
    assert_ratio_equals,
    create_absorption_review,
    create_community_payload,
    create_homesite,
    create_homesite_payload,
    create_household,
    create_phase,
    create_phase_payload,
    create_plat_approved_community,
    draft_lease,
    set_clock,
    setup_released_community,
    sign_lease,
    start_construction,
    submit_lease,
    validate_error,
    validate_paginated,
    validate_success,
)

CONSTRUCTION_WINDOW_START = "2026-08-01T00:00:00Z"
CONSTRUCTION_WINDOW_END = "2026-11-01T00:00:00Z"


def test_community_creation_returns_the_full_declared_field_set(
    api, developer_principal_headers
):
    """A community created from the required inputs echoes them and reports every derived
    dimension at its declared initial value, with the posture already frozen.

    Everything else on a new community is derived or system-owned. `plat_status` starts at `DRAFT`, `plat_revision_round` at 0, `plat_submitted_by_user_id` and `plat_package_reference` at null, `lifecycle_status` at `PLANNING`, `management_mode` at `DEVELOPER_SELF_MANAGED`, `pm_company_name` and `pm_effective_from` at null, `facility_status` at `CONSTRUCTION_DRAW`, and `posture` at `FROZEN` — frozen precisely because the plat has not been approved. The counters `released_unit_count`, `available_unit_count`, `leased_unit_count`, `committed_concession_cents` and `construction_impact_credit_cents` all start at 0, `occupancy_ratio` at 0.0, and `amenity_delivery_ratio` at 1.0. The record's `version` is 1. The service runs on a logical clock rather than wall-clock time, so that window, effective-date and activation rules are testable.
    Design: Corner/entities/community_creation_returns_201_with_the_full_declared_field_set
    """
    set_clock("2026-08-02T00:00:00Z")

    payload = create_community_payload(
        name="Alderway",
        market_code="TX-AUS",
        total_planned_units=6,
        product_mix={"DETACHED": 4, "COTTAGE": 2, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=3_000_000,
        facility_commitment_cents=60_000_000,
        maintenance_tech_headcount=2,
    )
    community = validate_success(
        api.create_community(payload, developer_principal_headers), 201
    )

    assert_community(community)
    assert community["name"] == "Alderway"
    assert community["market_code"] == "TX-AUS"
    assert community["total_planned_units"] == 6
    assert community["product_mix"] == {"DETACHED": 4, "COTTAGE": 2, "TOWNHOME": 0}
    assert community["single_ownership_covenant"] is True
    assert community["concession_budget_cents"] == 3_000_000
    assert community["facility_commitment_cents"] == 60_000_000
    assert community["maintenance_tech_headcount"] == 2

    assert community["plat_status"] == "DRAFT"
    assert community["plat_revision_round"] == 0
    assert community["plat_submitted_by_user_id"] is None
    assert community["plat_package_reference"] is None
    assert community["lifecycle_status"] == "PLANNING"
    assert community["management_mode"] == "DEVELOPER_SELF_MANAGED"
    assert community["pm_company_name"] is None
    assert community["pm_effective_from"] is None
    assert community["facility_status"] == "CONSTRUCTION_DRAW"
    assert community["posture"] == "FROZEN"

    assert community["released_unit_count"] == 0
    assert community["available_unit_count"] == 0
    assert community["leased_unit_count"] == 0
    assert community["committed_concession_cents"] == 0
    assert community["construction_impact_credit_cents"] == 0
    assert_ratio_equals(community["occupancy_ratio"], 0.0, "occupancy_ratio")
    assert_ratio_equals(community["amenity_delivery_ratio"], 1.0, "amenity_delivery_ratio")

    assert community["version"] == 1
    assert_newly_created(community)
    assert_instant_equals(community["created_at"], "2026-08-02T00:00:00Z", "created_at")


def test_community_retrieval_returns_the_stored_entity_unchanged(
    api, developer_principal_headers, entitlement_officer_headers, property_manager_headers
):
    """Two consecutive single-resource reads by two different operator roles return the
    persisted community verbatim and leave its version and derived dimensions alone.

    A newly created resource has `version` equal to 1 and `updated_at` equal to `created_at`. Thereafter, every mutation that changes the resource increments `version` by exactly 1 and refreshes `updated_at`, including mutations that reach the resource indirectly as part of a cascade rather than being addressed directly by the request.
    Design: Corner/entities/community_retrieval_by_id_returns_the_stored_entity_unchanged
    """
    payload = create_community_payload(
        name="Briarlyn",
        market_code="TX-SAT",
        total_planned_units=3,
        product_mix={"DETACHED": 3, "COTTAGE": 0, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=30_000_000,
        maintenance_tech_headcount=2,
    )
    created = validate_success(
        api.create_community(payload, developer_principal_headers), 201
    )

    first = validate_success(
        api.get_community(created["id"], entitlement_officer_headers), 200
    )
    second = validate_success(
        api.get_community(created["id"], property_manager_headers), 200
    )

    for read in (first, second):
        assert_community(read)
        assert read["id"] == created["id"]
        assert read["name"] == "Briarlyn"
        assert read["total_planned_units"] == 3
        assert read["version"] == 1
        assert read["plat_status"] == "DRAFT"
        assert read["posture"] == "FROZEN"
        assert_instant_equals(read["created_at"], created["created_at"], "created_at")
        assert_instant_equals(read["updated_at"], created["updated_at"], "updated_at")

    assert_instant_equals(first["created_at"], second["created_at"], "created_at")
    assert_instant_equals(first["updated_at"], second["updated_at"], "updated_at")


def test_homesite_listing_is_paginated_with_total_count_and_has_more(
    api, leasing_agent_headers
):
    """Two pages of two over a phase holding three homesites report the applied window and
    the unwindowed total, and together cover every row exactly once.

    `limit` controls page size: it defaults to 10 when omitted, may not be smaller than 1, and may not be larger than 100. The `meta` object of a list response carries `limit` and `offset` as they were actually applied, `total_count` as the number of records matching the filters before the page window is taken, and `has_more` as a boolean that is true when records remain beyond the current window.
    Design: Corner/entities/homesite_listing_is_paginated_with_total_count_and_has_more
    """
    community = create_plat_approved_community(
        name="Cinderhold",
        market_code="TX-DFW",
        total_planned_units=3,
        product_mix={"DETACHED": 3, "COTTAGE": 0, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=30_000_000,
        maintenance_tech_headcount=2,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        kind="HOUSING",
        planned_unit_count=3,
        amenity_weight=0,
        construction_window_start=CONSTRUCTION_WINDOW_START,
        construction_window_end=CONSTRUCTION_WINDOW_END,
    )
    start_construction(phase["id"])
    first_home = create_homesite(
        phase["id"], lot_number="C1", product_type="DETACHED", bedrooms=4, square_feet=2100
    )
    second_home = create_homesite(
        phase["id"], lot_number="C2", product_type="DETACHED", bedrooms=4, square_feet=2100
    )
    third_home = create_homesite(
        phase["id"], lot_number="C3", product_type="DETACHED", bedrooms=3, square_feet=1900
    )

    page_one, meta_one = validate_paginated(
        api.list_homesites(
            leasing_agent_headers, {"phase_id": phase["id"], "limit": 2, "offset": 0}
        )
    )
    page_two, meta_two = validate_paginated(
        api.list_homesites(
            leasing_agent_headers, {"phase_id": phase["id"], "limit": 2, "offset": 2}
        )
    )

    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0

    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2

    page_one_ids = [row["id"] for row in page_one]
    page_two_ids = [row["id"] for row in page_two]
    assert set(page_one_ids).isdisjoint(page_two_ids), "no homesite repeats across pages"
    assert set(page_one_ids) | set(page_two_ids) == {
        first_home["id"],
        second_home["id"],
        third_home["id"],
    }


def test_community_get_with_an_unknown_id_returns_community_not_found(
    api, developer_principal_headers, asset_manager_headers
):
    """A well-formed identifier that no community owns is refused in the error envelope, and
    the community that does exist is left untouched.

    Path parameters are resolved strictly left to right, and the first identifier that fails to resolve determines the error. A request addressed at a community that does not exist fails with `ERR_COMMUNITY_NOT_FOUND` (HTTP 404) before anything nested under it is considered; the same pattern gives `ERR_PHASE_NOT_FOUND`, `ERR_HOMESITE_NOT_FOUND`, `ERR_RENT_SCHEDULE_NOT_FOUND`, `ERR_CONCESSION_PROGRAM_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_TURN_WORK_ORDER_NOT_FOUND` and `ERR_ABSORPTION_REVIEW_NOT_FOUND`, each at HTTP 404, for the collection actually addressed.
    Design: Corner/entities/community_get_with_an_unknown_id_returns_not_found
    """
    payload = create_community_payload(
        name="Dunmoor",
        market_code="TX-HOU",
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
    )
    existing = validate_success(
        api.create_community(payload, developer_principal_headers), 201
    )

    response = api.get_community(
        "00000000-0000-4000-8000-0000000000ff", asset_manager_headers
    )
    validate_error(response, ApiErrorId.ERR_COMMUNITY_NOT_FOUND.value)

    untouched = validate_success(
        api.get_community(existing["id"], asset_manager_headers), 200
    )
    assert untouched["version"] == 1


def test_community_create_missing_market_code_returns_invalid_request(
    api, developer_principal_headers
):
    """A registration that omits the submarket label is a schema failure and persists nothing.

    The registration payload carries the community's trade name in `name` — between 1 and 120 characters and not blank — and a `market_code` of between 2 and 8 uppercase characters, which is the submarket label used for reporting. **Schema validity** — the body parses, required fields are present and non-null, enum values are declared members, numeric and instant formats are correct (`ERR_INVALID_REQUEST`).
    Design: Corner/entities/community_create_missing_market_code_returns_invalid_request
    """
    set_clock("2026-08-02T00:00:00Z")

    response = api.create_community(
        {
            "name": "Elmsgate",
            "total_planned_units": 2,
            "product_mix": {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
            "concession_budget_cents": 1_000_000,
            "facility_commitment_cents": 20_000_000,
        },
        developer_principal_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(api.list_communities(developer_principal_headers))
    assert meta["total_count"] == 0, "the rejected registration must not have been stored"


def test_community_create_omitting_the_optional_inputs_applies_the_declared_defaults(
    api, developer_principal_headers
):
    """A registration that omits both optional operational inputs takes their declared
    defaults rather than nulls or zeroes, and the new community is still frozen.

    `maintenance_tech_headcount` is the number of maintenance technicians staffed for turns; it is optional, defaults to 2 when omitted, and must be at least 1. Finally, `single_ownership_covenant` is optional and defaults to true; it records that the plat keeps every home in the community under one owner with no fee-simple lot sales, and while it is false the community can never leave a frozen posture.
    Design: Corner/entities/community_create_omitting_the_optional_inputs_applies_their_declared_defaults
    """
    set_clock("2026-08-02T00:00:00Z")

    community = validate_success(
        api.create_community(
            {
                "name": "Fernlow",
                "market_code": "TX-AUS",
                "total_planned_units": 2,
                "product_mix": {"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
                "concession_budget_cents": 1_000_000,
                "facility_commitment_cents": 20_000_000,
            },
            developer_principal_headers,
        ),
        201,
    )

    assert_community(community)
    assert community["single_ownership_covenant"] is True
    assert community["maintenance_tech_headcount"] == 2
    assert community["posture"] == "FROZEN"
    assert community["plat_status"] == "DRAFT"


def test_homesite_creation_leaves_the_computed_and_system_fields_at_their_initial_values(
    api, asset_manager_headers, construction_manager_headers
):
    """A newly created homesite reports the declared initial inventory state with its
    certificate, release and turn fields unset, and the community sees no availability yet.

    A new homesite starts at `status` `PLANNED` with `off_market_reason`, `occupancy_certificate_number`, `occupancy_certificate_issued_at`, `released_at` and `last_turn_ready_at` all null and `turn_cycle_count` 0. Every persisted resource carries a server-minted `id` — a UUID string with no type prefix, never supplied by the client — and a `created_at` timestamp recorded as an ISO 8601 UTC instant with exactly three fractional digits. `available_unit_count` is the number of homesites whose `status` is `AVAILABLE`.
    Design: Corner/entities/homesite_computed_and_system_fields_ignore_client_supplied_values
    """
    community = create_plat_approved_community(
        name="Gallowmere",
        market_code="TX-SAT",
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        kind="HOUSING",
        planned_unit_count=2,
        amenity_weight=0,
        construction_window_start=CONSTRUCTION_WINDOW_START,
        construction_window_end=CONSTRUCTION_WINDOW_END,
    )
    start_construction(phase["id"])

    homesite = validate_success(
        api.create_homesite(
            create_homesite_payload(
                phase["id"],
                lot_number="G1",
                product_type="DETACHED",
                bedrooms=4,
                square_feet=2100,
            ),
            construction_manager_headers,
        ),
        201,
    )

    assert_homesite(homesite)
    assert homesite["status"] == "PLANNED"
    assert homesite["released_at"] is None
    assert homesite["off_market_reason"] is None
    assert homesite["occupancy_certificate_number"] is None
    assert homesite["occupancy_certificate_issued_at"] is None
    assert homesite["last_turn_ready_at"] is None
    assert homesite["turn_cycle_count"] == 0
    assert homesite["phase_id"] == phase["id"]
    assert homesite["id"] != phase["id"] and homesite["id"] != community["id"]
    assert homesite["version"] == 1
    assert_newly_created(homesite)

    reread = validate_success(api.get_community(community["id"], asset_manager_headers), 200)
    assert reread["available_unit_count"] == 0


def test_homesite_create_with_an_undeclared_product_type_returns_invalid_request(
    api, leasing_agent_headers, construction_manager_headers
):
    """A homesite naming a product configuration outside the declared three is refused at the
    schema tier rather than by the product-mix counting rule, and nothing is persisted.

    A homesite carries a `lot_number` of 1 to 12 characters that must be unique within its phase — a duplicate is `ERR_DUPLICATE_RESOURCE` — a `product_type` of `DETACHED`, `COTTAGE` or `TOWNHOME`, a `bedrooms` count between 1 and 5 inclusive, and a `square_feet` figure of conditioned area between 400 and 4000 inclusive. **Schema validity** — the body parses, required fields are present and non-null, enum values are declared members, numeric and instant formats are correct (`ERR_INVALID_REQUEST`).
    Design: Corner/entities/homesite_create_with_an_undeclared_product_type_returns_invalid_request
    """
    community = create_plat_approved_community(
        name="Hollowfield",
        market_code="TX-DFW",
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
    )
    phase = create_phase(
        community["id"],
        sequence_index=1,
        kind="HOUSING",
        planned_unit_count=2,
        amenity_weight=0,
        construction_window_start=CONSTRUCTION_WINDOW_START,
        construction_window_end=CONSTRUCTION_WINDOW_END,
    )
    start_construction(phase["id"])

    response = api.create_homesite(
        {
            "phase_id": phase["id"],
            "lot_number": "H1",
            "product_type": "DUPLEX",
            "bedrooms": 4,
            "square_feet": 2100,
        },
        construction_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    _rows, meta = validate_paginated(
        api.list_homesites(leasing_agent_headers, {"phase_id": phase["id"]})
    )
    assert meta["total_count"] == 0, "the rejected homesite must not have been stored"


def test_absorption_review_is_immutable_and_carries_no_version_field(
    api, asset_manager_headers
):
    """A recorded review reads back with its pacing verdict frozen at creation and carries
    only an identifier and a creation instant, with no version and no update instant.

    `AbsorptionReview` is the single exception. An absorption review is an immutable snapshot: it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field, and neither is present in its response payload. A review is an immutable snapshot and is never revised. `available_supply_units` is the number of homesites of that `product_type` in the community whose `status` is `AVAILABLE` **at the moment the review is created** — not at the window's end. `pacing_index` is the raw pace multiplied by the supply factor multiplied by the posture penalty, rounded half up to four decimal places. Below 0.8000 the tier is `AGGRESSIVE` and the recommendation is negative 150 basis points.
    Design: Corner/entities/absorption_review_is_immutable_and_carries_no_version_field
    """
    scenario = setup_released_community(
        homesite_count=1,
        product_type="DETACHED",
        asking_rent_cents=285_000,
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        homesite_specs=[
            {
                "product_type": "DETACHED",
                "lot_number": "I1",
                "bedrooms": 4,
                "square_feet": 2100,
            }
        ],
        phase_overrides={"planned_unit_count": 2},
        name="Inglebrook",
        market_code="TX-AUS",
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
    )
    household = create_household(
        primary_applicant_name="Ines Vale",
        email="ines@example.com",
        household_size=4,
        monthly_income_cents=1_200_000,
        credit_tier="A",
    )
    lease = draft_lease(
        scenario["homesites"][0]["id"],
        household["id"],
        term_months=12,
        start_date="2026-08-01T00:00:00Z",
    )
    submit_lease(lease["id"])
    sign_lease(lease["id"], household["id"], "Ines Vale")
    set_clock("2026-08-08T00:00:00Z")
    review = create_absorption_review(
        scenario["community"]["id"],
        product_type="DETACHED",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-08T00:00:00Z",
        planned_absorption_units=1,
    )

    read_back = validate_success(
        api.get_absorption_review(review["id"], asset_manager_headers), 200
    )

    assert_absorption_review(read_back)
    assert read_back["id"] == review["id"]
    assert read_back["community_id"] == scenario["community"]["id"]
    assert read_back["product_type"] == "DETACHED"
    assert read_back["planned_absorption_units"] == 1
    assert read_back["actual_absorption_units"] == 1
    assert read_back["available_supply_units"] == 0
    assert_ratio_equals(read_back["pacing_index"], 0.7500, "pacing_index")
    assert read_back["concession_tier"] == "AGGRESSIVE"
    assert read_back["recommended_growth_bps"] == -150
    assert read_back["posture_at_review"] == "OPEN"
    assert_instant_equals(read_back["window_start"], "2026-08-01T00:00:00Z", "window_start")
    assert_instant_equals(read_back["window_end"], "2026-08-08T00:00:00Z", "window_end")
    assert "version" not in read_back
    assert "updated_at" not in read_back


def test_phase_create_with_an_unknown_community_id_returns_community_not_found(
    api, developer_principal_headers
):
    """A phase whose body names a community that does not exist is refused from the
    body-reference tier, and no orphan phase is persisted against the real community.

    Identifier fields inside a request body are resolved with the same codes and the same 404 status. An unknown `community_id` on a phase, rent schedule or concession program yields `ERR_COMMUNITY_NOT_FOUND`; an unknown `phase_id` on a homesite, or an unknown `predecessor_phase_id` on a phase, yields `ERR_PHASE_NOT_FOUND`; an unknown `homesite_id` on a lease or a turn work order, or any unknown member of the `homesite_ids` list on a section release, yields `ERR_HOMESITE_NOT_FOUND`; an unknown `household_id` on a lease yields `ERR_HOUSEHOLD_NOT_FOUND`; and an unknown `concession_program_id` on a concession request yields `ERR_CONCESSION_PROGRAM_NOT_FOUND`.
    Design: Corner/entities/phase_create_with_an_unknown_community_id_returns_community_not_found
    """
    payload = create_community_payload(
        name="Juniper Hollow",
        market_code="TX-HOU",
        total_planned_units=2,
        product_mix={"DETACHED": 2, "COTTAGE": 0, "TOWNHOME": 0},
        single_ownership_covenant=True,
        concession_budget_cents=1_000_000,
        facility_commitment_cents=20_000_000,
        maintenance_tech_headcount=2,
    )
    existing = validate_success(
        api.create_community(payload, developer_principal_headers), 201
    )

    response = api.create_phase(
        create_phase_payload(
            "00000000-0000-4000-8000-0000000000aa",
            sequence_index=1,
            kind="HOUSING",
            planned_unit_count=2,
            amenity_weight=0,
            construction_window_start=CONSTRUCTION_WINDOW_START,
            construction_window_end=CONSTRUCTION_WINDOW_END,
        ),
        developer_principal_headers,
    )
    validate_error(response, ApiErrorId.ERR_COMMUNITY_NOT_FOUND.value)

    _rows, meta = validate_paginated(
        api.list_phases(developer_principal_headers, {"community_id": existing["id"]})
    )
    assert meta["total_count"] == 0, "the rejected phase must not have been stored"
