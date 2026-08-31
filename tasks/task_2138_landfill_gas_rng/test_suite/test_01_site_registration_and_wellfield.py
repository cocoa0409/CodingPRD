"""Registering a host landfill and adding extraction wells to its wellfield."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    approx_2dp,
    assert_gas_well,
    assert_landfill_site,
    create_site_payload,
    create_well_payload,
    fixtures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import BASE_CLOCK_UTC


class TestSiteRegistration:
    def test_new_site_opens_with_every_ledger_counter_at_zero(self, api, admin_headers):
        """PRD §3.1: "A freshly registered site starts with every ledger counter at
        zero — `energy_produced_mmbtu`, `energy_injected_mmbtu`, `energy_flared_mmbtu`,
        `energy_vented_mmbtu`, `rin_generated_total`, `rin_available_count`,
        `rin_retired_count`, `rin_reversed_count` and `royalty_payable_usd` are all 0 —
        and with `compliance_posture` at `COMPLIANT`."
        PRD §2.4: "Most resources additionally carry `updated_at`, refreshed to the
        current logical instant on every mutation, and `version`, an integer that starts
        at 1 on creation and increments by exactly one on every mutation of the row."

        Design: Corner/entities/site_creation_initialises_every_ledger_counter_to_zero
        """
        data, meta = validate_paginated(
            api.list_sites(admin_headers, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, "the database starts empty"

        response = api.create_site(
            create_site_payload(
                royalty_floor_usd_per_mmbtu=0.25, design_collection_efficiency_pct=85.0
            ),
            admin_headers,
        )
        site = validate_success(response, 201)
        assert_landfill_site(site)

        assert site["energy_produced_mmbtu"] == approx_2dp(0.0)
        assert site["energy_injected_mmbtu"] == approx_2dp(0.0)
        assert site["energy_flared_mmbtu"] == approx_2dp(0.0)
        assert site["energy_vented_mmbtu"] == approx_2dp(0.0)
        assert site["rin_generated_total"] == 0
        assert site["rin_available_count"] == 0
        assert site["rin_retired_count"] == 0
        assert site["rin_reversed_count"] == 0
        assert site["royalty_payable_usd"] == approx_2dp(0.0)
        assert site["collected_flow_scfm"] == approx_2dp(0.0)
        assert site["collection_efficiency_pct"] == approx_2dp(0.0)
        assert site["compliance_posture"] == "COMPLIANT"
        assert site["version"] == 1, "version starts at 1 on creation"

    def test_omitted_optional_site_terms_fall_back_to_their_declared_defaults(
        self, api, admin_headers
    ):
        """PRD §3.1: "`royalty_floor_usd_per_mmbtu`, a contractual minimum payment per
        billable MMBtu that defaults to 0.25 and may not be negative"
        PRD §3.1: "A `design_collection_efficiency_pct` may also be supplied, defaulting
        to 85.0; it appears in the permit narrative and is a reference value only, never
        participating in any calculation."

        Design: Corner/entities/site_optional_fields_fall_back_to_declared_defaults
        """
        payload = create_site_payload(
            name="Cedar Ridge Landfill",
            state_code="TX",
            host_royalty_pct=0.10,
            royalty_variant="NETBACK_SHARE",
            permit_nmoc_limit_lb_per_hr=4.0,
        )
        payload.pop("royalty_floor_usd_per_mmbtu", None)
        payload.pop("design_collection_efficiency_pct", None)

        site = validate_success(api.create_site(payload, admin_headers), 201)

        assert site["royalty_floor_usd_per_mmbtu"] == approx_2dp(0.25)
        assert site["design_collection_efficiency_pct"] == approx_2dp(85.0)
        assert site["royalty_variant"] == "NETBACK_SHARE"

    def test_site_create_without_host_royalty_pct_is_a_schema_violation(
        self, api, admin_headers
    ):
        """PRD §3.1: "The registration also captures the commercial and permit terms
        that will govern the project for its life: `host_royalty_pct`, the fraction of
        revenue owed to the landfill owner, which must be greater than zero and no
        greater than 0.50"
        PRD §2.5: "**Body schema (priority 40).** Required fields present, types
        correct, enum members recognised, numeric ranges respected, and string patterns
        matched — including a `generation_period` shaped `YYYY-MM` and a compliance
        report `period` shaped `YYYY-Qn`. Otherwise `ERR_VALIDATION` with HTTP 400.
        Applies to every write endpoint."

        Design: Corner/entities/site_create_missing_required_host_royalty_pct_returns_invalid_request
        """
        payload = create_site_payload(name="Broken Site")
        payload.pop("host_royalty_pct")

        validate_error(
            api.create_site(payload, admin_headers), ApiErrorId.ERR_VALIDATION.value
        )

        _, meta = validate_paginated(
            api.list_sites(admin_headers, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 0, "the rejected create must persist nothing"

    def test_site_create_with_an_unrecognised_royalty_variant_is_rejected(
        self, api, admin_headers
    ):
        """PRD §3.1: "`royalty_variant`, the site's default settlement method, either
        `GROSS_REVENUE_SHARE` or `NETBACK_SHARE`"
        PRD §2.5: "**Body schema (priority 40).** Required fields present, types
        correct, enum members recognised, numeric ranges respected, and string patterns
        matched — including a `generation_period` shaped `YYYY-MM` and a compliance
        report `period` shaped `YYYY-Qn`. Otherwise `ERR_VALIDATION` with HTTP 400.
        Applies to every write endpoint."

        Design: Corner/entities/site_create_with_invalid_enum_royalty_variant_is_rejected
        """
        validate_error(
            api.create_site(
                create_site_payload(name="Bad Enum Site", royalty_variant="BEST_DEAL"),
                admin_headers,
            ),
            ApiErrorId.ERR_VALIDATION.value,
        )


class TestWellfieldRegistration:
    def test_unknown_well_id_reports_the_missing_well(self, api, technician_headers):
        """PRD §2.5: "**Path existence (priority 30).** Every resource identifier in the
        URL path resolves, validated left to right, or the not-found error naming that
        resource type: `ERR_SITE_NOT_FOUND`, `ERR_WELL_NOT_FOUND`,
        `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_DOWNTIME_EVENT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
        `ERR_INJECTION_BATCH_NOT_FOUND`, `ERR_ATTRIBUTE_BATCH_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND` or `ERR_ROYALTY_STATEMENT_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_unknown_gas_well_returns_well_not_found
        """
        fixtures.create_site()

        validate_error(
            api.get_well(NON_EXISTENT_UUID, technician_headers),
            ApiErrorId.ERR_WELL_NOT_FOUND.value,
        )

    def test_well_create_naming_an_unknown_site_reports_the_missing_site(
        self, api, admin_headers
    ):
        """PRD §2.5: "**Body foreign keys (priority 50).** Every foreign key supplied in
        a request body resolves to an existing row, or the matching not-found error from
        the set `ERR_SITE_NOT_FOUND`, `ERR_WELL_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
        `ERR_INJECTION_BATCH_NOT_FOUND`. This guards well creation, plant creation,
        offtake contract creation, nomination creation, injection batch creation,
        attribute batch creation, compliance report creation, royalty statement creation,
        work order creation, downtime event creation, and the `nomination_id` supplied
        when an injection batch is attached to a nomination."

        Design: Corner/entities/well_create_with_unknown_site_returns_site_not_found
        """
        set_clock(BASE_CLOCK_UTC)

        validate_error(
            api.create_well(
                create_well_payload(NON_EXISTENT_UUID, well_code="W-99"), admin_headers
            ),
            ApiErrorId.ERR_SITE_NOT_FOUND.value,
        )

    def test_body_schema_violation_is_reported_before_an_unknown_body_foreign_key(
        self, api, admin_headers
    ):
        """PRD §2.5: "Checks run in a fixed ascending priority order and the **first**
        failing check decides the response."
        PRD §2.5: "**Body schema (priority 40).** Required fields present, types
        correct, enum members recognised, numeric ranges respected, and string patterns
        matched — including a `generation_period` shaped `YYYY-MM` and a compliance
        report `period` shaped `YYYY-Qn`. Otherwise `ERR_VALIDATION` with HTTP 400.
        Applies to every write endpoint."
        PRD §2.5: "**Body foreign keys (priority 50).** Every foreign key supplied in a
        request body resolves to an existing row, or the matching not-found error from
        the set `ERR_SITE_NOT_FOUND`, `ERR_WELL_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`,
        `ERR_CONTRACT_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`,
        `ERR_INJECTION_BATCH_NOT_FOUND`."

        Design: Corner/validations/body_schema_check_beats_body_foreign_key_existence_returns_invalid_request
        """
        set_clock(BASE_CLOCK_UTC)

        error = validate_error(
            api.create_well(
                {"site_id": NON_EXISTENT_UUID, "well_code": "W-09"}, admin_headers
            ),
            ApiErrorId.ERR_VALIDATION.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_SITE_NOT_FOUND.value, (
            "the schema rung sits above the body foreign-key rung"
        )

    def test_reusing_a_live_wells_code_on_the_same_site_is_rejected(
        self, api, admin_headers
    ):
        """PRD §3.1: "A well code must be unique among the wells of that site that have
        not been decommissioned; reusing a code that a live well already holds is
        rejected with `ERR_WELL_CODE_DUPLICATE`, while reusing the code of a
        decommissioned well is permitted."

        Design: Corner/entities/duplicate_well_code_on_same_site_is_rejected
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        fixtures.create_well(site["id"], well_code="W-01")

        validate_error(
            api.create_well(
                create_well_payload(site["id"], well_code="W-01", target_flow_scfm=400.0),
                admin_headers,
            ),
            ApiErrorId.ERR_WELL_CODE_DUPLICATE.value,
        )

        _, meta = validate_paginated(
            api.list_wells(
                admin_headers,
                params={"site_id": site["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1, "the duplicate must not have been persisted"

    def test_a_new_well_produces_nothing_until_its_first_reading_arrives(
        self, api, admin_headers
    ):
        """PRD §3.1: "Every new well starts in `operating_state` `ONLINE` with
        `current_flow_scfm` at 0, `last_reading_flow_scfm` and `wellhead_vacuum_inhg` at
        0, `consecutive_good_readings` at 0, `last_quality_class` at `NONE`, and
        `last_reading_at` null — it produces nothing on paper until its first field
        reading arrives."
        PRD §3.1: "`collection_efficiency_pct` is that collected flow, multiplied by
        100, divided by the sum of `target_flow_scfm` over the site's wells whose
        `operating_state` is anything other than `DECOMMISSIONED`, rounded half up to two
        decimal places; when that denominator is zero the efficiency is reported as 0.00
        rather than as an error."

        Design: Corner/entities/well_current_flow_is_computed_and_starts_at_zero
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()

        well = validate_success(
            api.create_well(create_well_payload(site["id"], well_code="W-01"), admin_headers),
            201,
        )
        assert_gas_well(well)

        assert well["operating_state"] == "ONLINE"
        assert well["current_flow_scfm"] == approx_2dp(0.0)
        assert well["last_reading_flow_scfm"] == approx_2dp(0.0)
        assert well["last_quality_class"] == "NONE"
        assert well["last_reading_at"] is None
        assert well["consecutive_good_readings"] == 0

        site_after = fixtures.read_site(site["id"])
        assert site_after["collected_flow_scfm"] == approx_2dp(0.0)
        assert site_after["collection_efficiency_pct"] == approx_2dp(0.0)


class TestWellListing:
    def test_well_listing_windows_rows_and_reports_the_unwindowed_total(
        self, api, technician_headers
    ):
        """PRD §2.3: "Successful list responses set `response_type` to `"array"` and
        populate `limit`, `offset`, `total_count` and `has_more` in `meta`, where
        `total_count` counts every row matching the request's filters before the window
        is applied and `has_more` is true whenever rows remain beyond the returned
        window."
        PRD §2.3: "Gas wells filter on `site_id` and `operating_state`."

        Design: Corner/entities/wells_list_is_filterable_and_paginated
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        for code in ("W-01", "W-02", "W-03"):
            fixtures.create_well(site["id"], well_code=code)

        response = api.list_wells(
            technician_headers,
            params={"site_id": site["id"], "limit": 2, "offset": 1},
        )
        body = response.json()
        assert body["response_type"] == "array"

        rows, meta = validate_paginated(response)
        assert len(rows) == 2, f"limit 2 at offset 1 over 3 wells, got {len(rows)}"
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 1
        assert meta["has_more"] is False
        for row in rows:
            assert row["site_id"] == site["id"]

    def test_limit_above_one_hundred_is_a_schema_violation(self, api, technician_headers):
        """PRD §2.3: "`limit` defaults to 10 when omitted, may be no smaller than 1 and
        no larger than 100. `offset` defaults to 0 and may not be negative. A `limit` or
        `offset` outside those bounds is a schema violation and is rejected with
        `ERR_VALIDATION` and HTTP 400."

        Design: Corner/entities/pagination_limit_above_maximum_returns_invalid_request
        """
        site = fixtures.create_site()
        fixtures.create_well(site["id"], well_code="W-01")

        validate_error(
            api.list_wells(
                technician_headers,
                params={"site_id": site["id"], "limit": 101, "offset": 0},
            ),
            ApiErrorId.ERR_VALIDATION.value,
        )
