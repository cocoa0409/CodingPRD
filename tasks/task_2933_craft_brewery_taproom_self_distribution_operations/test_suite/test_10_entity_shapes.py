"""Entity-level contract: creation echoes, defaults, computed and system fields."""

from test_helpers import (
    CELLAR,
    COMPLIANCE,
    CONTAINER_PINT_16OZ,
    CONTAINER_SAMPLE_4OZ,
    DEFAULT_TERMINATION_NOTICE_DAYS,
    DESTINATION_TAPROOM,
    ERR_BEER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_TANK_NOT_FOUND,
    KEG_EMPTY_DIRTY,
    KEG_SIZE_HALF_BBL,
    LABEL_NO_LABEL,
    LICENSE_ACTIVE,
    LICENSE_SELF_DISTRIBUTION,
    LICENSE_WHOLESALER_ONLY,
    PACKAGE_HALF_BBL_KEG,
    REG_DRAFT,
    REGULATOR,
    SANITATION_NOT_REQUIRED,
    TANK_TYPE_FERMENTER,
    TAPROOM,
    UNKNOWN_UUID,
    assert_bbl,
    assert_common_fields,
    assert_instant_equals,
    assert_no_prefix_uuid,
    assert_oz,
    assert_pagination_meta,
    assert_pour_shape,
    batch_payload,
    is_iso8601_timestamp,
    pour_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_DEFAULT_UTC
from test_helpers.fixtures import (
    bootstrap_brewery,
    create_completed_run,
    create_conditioning_batch,
    create_exempt_beer,
    create_license,
    create_tank,
    create_tapped_keg,
)
from test_helpers.test_users import USER_TAPROOM_1

def _taproom_keg(api):
    beer = create_exempt_beer(
        api, name="Ridgeline IPA", abv_pct=6.8, price_per_bbl_cents=42000
    )
    tank = create_tank(api, code="FV-01", capacity_bbl=30.00)
    batch = create_conditioning_batch(
        api,
        beer["id"],
        tank["id"],
        actual_yield_bbl=16.000,
        batch_code="B-1001",
        planned_volume_bbl=16.00,
        brew_start_utc="2026-08-01T06:00:00Z",
        brew_end_utc="2026-08-08T06:00:00Z",
    )
    run = create_completed_run(
        api,
        batch["id"],
        package_type=PACKAGE_HALF_BBL_KEG,
        destination=DESTINATION_TAPROOM,
        units_planned=10,
        run_code="R-TAP-1",
    )
    return create_tapped_keg(api, run["id"], KEG_SIZE_HALF_BBL, keg_serial="KEG-0001")


class TestStateLicenceShape:
    def test_a_new_licence_opens_active_with_a_zeroed_barrel_ledger(self, api):
        """Every system field of a fresh licence is initialised by the server.

        PRD §3.6: "A licence opens with `status` `ACTIVE`, a
        `carry_in_barrels_ytd` of 0.000, a `barrels_shipped_ytd` of 0.000 and an
        `active_appointment_count` of 0."

        Design: Corner/entities/create_state_license_with_all_required_fields_returns_201
        """
        bootstrap_brewery(api, home_state_code="OR")

        license_row = validate_success(
            api.create_state_license(
                {
                    "state_code": "ID",
                    "license_type": LICENSE_SELF_DISTRIBUTION,
                    "annual_barrel_cap": 1000.00,
                    "franchise_state": False,
                    "effective_from_utc": "2026-01-01T00:00:00Z",
                    "expires_at_utc": "2027-01-01T00:00:00Z",
                    "termination_notice_days": 90,
                },
                COMPLIANCE,
            ),
            201,
        )

        assert license_row["state_code"] == "ID"
        assert license_row["license_type"] == LICENSE_SELF_DISTRIBUTION
        assert_bbl(license_row["annual_barrel_cap"], 1000.00, "annual_barrel_cap")
        assert license_row["franchise_state"] is False
        assert license_row["status"] == LICENSE_ACTIVE
        assert_bbl(license_row["carry_in_barrels_ytd"], 0.000, "carry_in_barrels_ytd")
        assert_bbl(license_row["barrels_shipped_ytd"], 0.000, "barrels_shipped_ytd")
        assert license_row["active_appointment_count"] == 0
        assert_common_fields(license_row, expected_version=1)

    def test_reading_a_licence_back_is_not_a_mutation(self, api):
        """The GET echoes the stored row with the default notice period and version 1.

        PRD §3.6: "An optional `termination_notice_days`, defaulting to **90**,
        records the statutory notice the state demands before an appointment may
        be ended."

        Design: Corner/entities/get_state_license_returns_the_stored_row
        """
        bootstrap_brewery(api, home_state_code="OR")
        created = create_license(
            api,
            "WA",
            LICENSE_WHOLESALER_ONLY,
            annual_barrel_cap=0.00,
            franchise_state=True,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )

        stored = validate_success(api.get_state_license(created["id"], REGULATOR))

        assert stored["id"] == created["id"]
        assert stored["state_code"] == "WA"
        assert stored["license_type"] == LICENSE_WHOLESALER_ONLY
        assert stored["franchise_state"] is True
        assert stored["termination_notice_days"] == DEFAULT_TERMINATION_NOTICE_DAYS
        assert stored["version"] == 1


class TestTaproomPourListing:
    def test_the_pour_list_pages_over_the_filtered_set(self, api):
        """limit=2 over three pours reports total_count 3 and has_more true.

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` in its `meta`, where `total_count` is the number of rows
        matching the filter before pagination and `has_more` is true exactly when
        `offset` plus the number of rows returned is strictly less than
        `total_count`."

        Design: Corner/entities/list_taproom_pours_paginates_with_total_count_and_has_more
        """
        bootstrap_brewery(api)
        keg = _taproom_keg(api)
        for _ in range(3):
            validate_success(
                api.create_taproom_pour(
                    pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
                ),
                201,
            )

        first_page, first_meta = validate_paginated(
            api.list_taproom_pours(
                TAPROOM, {"keg_asset_id": keg["id"], "limit": 2, "offset": 0}
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_taproom_pours(
                TAPROOM, {"keg_asset_id": keg["id"], "limit": 2, "offset": 2}
            )
        )

        assert len(first_page) == 2
        assert_pagination_meta(
            first_meta, total_count=3, has_more=True, limit=2, offset=0
        )
        assert len(second_page) == 1
        assert_pagination_meta(second_meta, total_count=3, has_more=False, offset=2)
        for row in first_page + second_page:
            assert_oz(row["volume_oz"], 16, "volume_oz")
            assert row["sanitation_verdict"] == SANITATION_NOT_REQUIRED
            assert_pour_shape(row)


class TestExistenceErrors:
    def test_a_uuid_naming_no_beer_answers_the_beer_not_found_error(self, api):
        """A well-formed identifier that names nothing is a 404, not an empty 200.

        PRD §2.8: "**Path-parameter existence** — resources named by URL path
        variables are resolved **left to right**, and the first identifier that
        resolves to nothing produces its own entity-specific 404."

        Design: Corner/entities/get_beer_with_unknown_uuid_returns_beer_not_found
        """
        bootstrap_brewery(api)

        body = validate_error(
            api.get_beer(UNKNOWN_UUID, COMPLIANCE), ERR_BEER_NOT_FOUND, 404
        )

        assert isinstance(body["message"], str)
        assert body["message"].strip() != ""

    def test_a_batch_naming_no_tank_answers_the_tank_not_found_error(self, api):
        """The flat topology validates tank_id as a foreign key on the body.

        PRD §2.8: "**Body foreign-key existence** — identifiers carried in the
        request body are resolved next, using the same entity-specific 404
        vocabulary."

        Design: Corner/entities/create_batch_referencing_unknown_tank_returns_tank_not_found
        """
        bootstrap_brewery(api)
        beer = create_exempt_beer(api, name="Ridgeline IPA")

        validate_error(
            api.create_batch(
                batch_payload(
                    beer["id"],
                    UNKNOWN_UUID,
                    batch_code="B-1001",
                    planned_volume_bbl=16.00,
                    brew_start_utc="2026-08-01T06:00:00Z",
                    brew_end_utc="2026-08-08T06:00:00Z",
                ),
                CELLAR,
            ),
            ERR_TANK_NOT_FOUND,
            404,
        )

        _, meta = validate_paginated(api.list_batches(CELLAR))
        assert meta["total_count"] == 0


class TestSchemaGuards:
    def test_a_tank_without_a_capacity_is_a_schema_failure(self, api):
        """capacity_bbl is required, and the refusal creates no vessel.

        PRD §2.8: "**Request and query schema** — `ERR_INVALID_REQUEST` (400).
        Covers unknown enum values, numeric range violations, excess decimal
        places, missing required fields, datetime strings that will not parse as
        ISO 8601 UTC instants, the pagination guards from §2.3, and the
        interval-ordering guards from §2.5."

        Design: Corner/entities/create_tank_missing_required_capacity_returns_invalid_request
        """
        bootstrap_brewery(api)

        validate_error(
            api.create_tank({"code": "FV-01", "tank_type": TANK_TYPE_FERMENTER}, CELLAR),
            ERR_INVALID_REQUEST,
            400,
        )

        _, meta = validate_paginated(api.list_tanks(CELLAR))
        assert meta["total_count"] == 0

    def test_an_event_window_that_does_not_advance_is_a_schema_failure(self, api):
        """An event ending at the instant it starts never reaches the permit rules.

        PRD §3.9: "The two instants `event_start_utc` and `event_end_utc` delimit
        the event, with the end strictly after the start, and both are stored as
        given."

        Design: Corner/entities/create_event_permit_with_end_not_after_start_returns_invalid_request
        """
        bootstrap_brewery(api, home_state_code="OR")
        beer = create_exempt_beer(api, name="Ridgeline IPA")
        create_license(
            api,
            "OR",
            LICENSE_SELF_DISTRIBUTION,
            annual_barrel_cap=1000.00,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2027-01-01T00:00:00Z",
        )

        validate_error(
            api.create_event_permit(
                {
                    "featured_beer_id": beer["id"],
                    "event_name": "Zero Length Fest",
                    "permit_type": "FESTIVAL",
                    "venue_state_code": "OR",
                    "event_start_utc": "2026-09-10T12:00:00Z",
                    "event_end_utc": "2026-09-10T12:00:00Z",
                    "requested_bbl": 2.00,
                },
                COMPLIANCE,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        _, meta = validate_paginated(api.list_event_permits(COMPLIANCE))
        assert meta["total_count"] == 0


class TestDefaultsComputedAndSystemFields:
    def test_a_beer_registered_without_the_flag_needs_a_formula(self, api):
        """An omitted requires_formula leaves the brand in DRAFT and unsellable.

        PRD §3.1: "A `requires_formula` flag, optional and defaulting to **true**,
        decides which of the two registration paths the brand takes."

        Design: Corner/entities/create_beer_omitting_requires_formula_defaults_to_true
        """
        bootstrap_brewery(api)

        beer = validate_success(
            api.create_beer(
                {
                    "name": "Coastal Pils",
                    "style": "German Pilsner",
                    "abv_pct": 5.0,
                    "price_per_bbl_cents": 38000,
                },
                COMPLIANCE,
            ),
            201,
        )

        assert beer["requires_formula"] is True
        assert beer["registration_state"] == REG_DRAFT
        assert beer["label_state"] == LABEL_NO_LABEL
        assert beer["cola_id"] is None
        assert beer["taproom_sellable"] is False
        assert beer["distribution_sellable"] is False

    def test_a_pours_volume_comes_from_its_container_and_not_from_the_client(self, api):
        """A SAMPLE_4OZ pour is 4 ounces even when the body claims 64.

        PRD §3.5: "A `SAMPLE_4OZ` pour is 4 ounces, a `HALF_PINT_8OZ` is 8, a
        `PINT_16OZ` is 16, a `CROWLER_32OZ` is 32 and a `GROWLER_64OZ` is 64, and
        the chosen figure is stored as the pour's `volume_oz`."

        Design: Corner/entities/pour_volume_oz_is_computed_and_submitted_extra_field_is_ignored
        """
        bootstrap_brewery(api)
        keg = _taproom_keg(api)

        pour = validate_success(
            api.create_taproom_pour(
                {
                    "keg_asset_id": keg["id"],
                    "container_type": CONTAINER_SAMPLE_4OZ,
                    "price_cents": 0,
                    "volume_oz": 64,
                },
                TAPROOM,
            ),
            201,
        )

        assert_oz(pour["volume_oz"], 4, "volume_oz")
        assert pour["price_cents"] == 0
        assert pour["sanitation_verdict"] == SANITATION_NOT_REQUIRED
        stored = validate_success(api.get_keg_asset(keg["id"], CELLAR))
        assert_oz(stored["poured_volume_oz"], 4.00, "poured_volume_oz")
        assert_oz(stored["remaining_volume_oz"], 1980.00, "remaining_volume_oz")

    def test_a_keg_cannot_be_registered_into_a_state_it_has_not_earned(self, api):
        """Server-owned fields ignore whatever the create body claims.

        PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
        timestamp with three fractional digits recording when the row was first
        written."

        Design: Corner/entities/keg_asset_system_fields_are_server_minted_and_input_ignored
        """
        bootstrap_brewery(api)

        keg = validate_success(
            api.create_keg_asset(
                {
                    "keg_serial": "KEG-0001",
                    "size_bbl": KEG_SIZE_HALF_BBL,
                    "state": "FILLED",
                    "filled_volume_oz": 1984.00,
                    "version": 99,
                },
                CELLAR,
            ),
            201,
        )

        assert keg["state"] == KEG_EMPTY_DIRTY
        assert_oz(keg["filled_volume_oz"], 0.00, "filled_volume_oz")
        assert_oz(keg["remaining_volume_oz"], 0.00, "remaining_volume_oz")
        assert keg["packaging_run_id"] is None
        assert keg["cycle_count"] == 0
        assert keg["version"] == 1
        assert_no_prefix_uuid(keg["id"])
        assert is_iso8601_timestamp(keg["created_at"])
        assert_common_fields(keg, expected_version=1)


class TestPourImmutability:
    def test_a_pour_carries_no_version_and_no_updated_at(self, api):
        """The pour is a write-once record of a sale.

        PRD §2.4: "The one exception is the taproom pour, which is immutable once
        recorded and therefore carries only `id` and `created_at`."

        Design: Corner/entities/taproom_pour_is_immutable_with_no_version_field
        """
        bootstrap_brewery(api)
        keg = _taproom_keg(api)
        created = validate_success(
            api.create_taproom_pour(
                pour_payload(keg["id"], CONTAINER_PINT_16OZ, price_cents=800), TAPROOM
            ),
            201,
        )

        stored = validate_success(api.get_taproom_pour(created["id"], COMPLIANCE))

        assert stored["id"] == created["id"]
        assert_pour_shape(stored)
        assert_oz(stored["volume_oz"], 16, "volume_oz")
        assert stored["poured_by_user_id"] == USER_TAPROOM_1
        assert_instant_equals(stored["poured_at_utc"], CLOCK_DEFAULT_UTC, "poured_at_utc")
