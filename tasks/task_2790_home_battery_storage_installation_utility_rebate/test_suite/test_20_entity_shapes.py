"""
The shape of a record as it comes back from the server.

These tests read the resources rather than drive them: what a freshly created row
carries before anything has happened to it, which inputs the server keeps and which it
computes for itself, what a page of a listing reports about the set it was drawn from,
and how a well-formed request naming nothing is answered.
"""

from test_helpers import (
    AHJ_HEADERS,
    UNKNOWN_ENTITY_ID,
    ApiErrorId,
    BackupScope,
    BuildStatus,
    GridStatus,
    LoadCalcStatus,
    LoadMethod,
    WarrantyStatus,
    assert_common_fields,
    assert_quantity,
    assert_status_pair,
    assert_unset,
    factories,
    fixtures,
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_SITE_ID = "22222222-2222-2222-2222-222222222222"
CLIENT_SUPPLIED_ID = "33333333-3333-3333-3333-333333333333"


class TestBatterySystemCreation:
    """What the design endpoint stores, computes and refuses."""

    def _sized_premises(self, api):
        """A certified installer, a premises, and an approved essential-loads sizing."""
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        project = fixtures.approved_load_calculation(api, project)
        return project

    def _design(self, api, project, **overrides):
        return api.create_battery_system(
            factories.battery_system_payload(
                project.site_id,
                project.installer_id,
                project.load_calculation_id,
                **overrides
            ),
            headers=project.installer_headers,
        )

    def test_a_new_bank_derives_its_capacity_and_opens_with_declared_statuses(self, api):
        """Two units of the entry model are 27 kWh and 10 kW, and nothing else is set yet.

        The catalog gives 13.5 kWh and 5.0 kW per unit, so a two-unit bank is 27.0 kWh and
        10.0 kW; both figures come out of the catalog rather than the payload. The bank opens
        as an unenergized original build: a draft design, no interconnection application, an
        unregistered warranty, no verified capacity and no base system it expands.

        PRD 2.11: "Model `PWX_A` provides 13.5 usable kWh and 5.0 kW of continuous power per unit, permits at most 10 units in one bank, and requires firmware `24.4.0` or newer."
        PRD 2.11: "A bank's `usable_kwh` is its `unit_count` multiplied by the per-unit usable energy of its model, and its `continuous_kw` is its `unit_count` multiplied by the per-unit continuous power of its model, each rounded half up to two decimals."
        PRD 3.3: "A new bank opens at `build_status` of `DESIGN_DRAFT` and `grid_status` of `NOT_APPLIED`, with `warranty_status` of `UNREGISTERED`, `verified_capacity_kwh` unset, and `expands_system_id` null because it is an original build rather than an expansion."

        Design: Corner/entities/create_battery_system_returns_catalog_derived_capacity_and_default_statuses
        """
        project = self._sized_premises(api)

        system = validate_success(self._design(api, project), expected_status=201)

        assert_quantity(system, "usable_kwh", 27.0)
        assert_quantity(system, "continuous_kw", 10.0)
        assert_status_pair(system, BuildStatus.DESIGN_DRAFT, GridStatus.NOT_APPLIED)
        assert system["warranty_status"] == WarrantyStatus.UNREGISTERED
        assert_unset(system, "verified_capacity_kwh", "expands_system_id")
        assert_common_fields(system)

    def test_capacity_figures_supplied_by_the_caller_are_discarded(self, api):
        """A payload claiming 99 kWh and 99 kW gets the catalog's figures instead.

        Both capacity fields are computed from the model and the unit count, and the server
        never takes them from the request, so the inflated figures are ignored and the stored
        bank is the two-unit bank the model code describes.

        PRD 2.11: "Neither figure is ever accepted from a caller."
        PRD 3.3: "The bank's `usable_kwh` and `continuous_kw` are derived from the catalog of §2.11 and the unit count; a caller cannot set them."

        Design: Corner/entities/create_battery_system_with_capacity_extra_field_input_ignored
        """
        project = self._sized_premises(api)

        system = validate_success(
            self._design(api, project, usable_kwh=99.0, continuous_kw=99.0),
            expected_status=201,
        )

        assert_quantity(system, "usable_kwh", 27.0)
        assert_quantity(system, "continuous_kw", 10.0)
        assert system["usable_kwh"] != 99.0
        assert system["continuous_kw"] != 99.0

    def test_an_unknown_premises_is_reported_before_any_business_rule(self, api):
        """The body's first foreign key is resolved before the approval rule is consulted.

        The calculation this design cites is approved, so the design-time business rules would
        all pass; what fails is the premises the payload names, which does not exist. The
        answer is the site's own 404 rather than any objection about the calculation, and no
        bank is discoverable against that calculation afterwards.

        PRD 2.4: "When a request names one or more identifiers, resolution is strictly left to right: path parameters first, in the order they appear in the path, then foreign keys carried in the request body, in the order the endpoint declares them."
        PRD 2.12: "Every referenced resource resolves, path parameters left to right and then body foreign keys in declaration order, each miss raising that entity's own 404."

        Design: Corner/entities/create_battery_system_with_unknown_site_returns_not_found
        """
        project = self._sized_premises(api)

        validate_error(
            api.create_battery_system(
                factories.battery_system_payload(
                    UNKNOWN_SITE_ID, project.installer_id, project.load_calculation_id
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_SITE_NOT_FOUND,
            expected_status=404,
        )

        banks, _ = validate_paginated(
            api.list_battery_systems(
                {"load_calculation_id": project.load_calculation_id},
                headers=project.installer_headers,
            )
        )
        assert banks == [], "a refused design left a bank behind"


class TestLoadCalculationReads:
    """The single-resource read and the filtered listing of one site's sizings."""

    def _premises(self, api):
        project = fixtures.certified_installer(api)
        return fixtures.site_for(api, project)

    def test_the_read_returns_the_stored_inputs_and_the_computed_sizing(self, api):
        """Every input comes back unchanged and the three sizing figures come back computed.

        The general lighting term is 7200 volt-amperes, which with the 18000 of appliance load
        makes an other-load subtotal of 25200; the demand split takes the first 3000 in full
        and 40 percent of the remaining 22200, giving 11880, and the HVAC term is the larger
        of the two conditioning figures, 9600 — a connected load of 21.48 kW. The two largest
        circuits total 6.0 kW and half the remaining 2.0 kW adds 1.0, so the continuous
        requirement is 7.00 kW, and the well pump's threefold inrush of 7.5 kW plus a quarter
        of that requirement is a surge figure of 9.25 kW. The authority's read agrees with the
        creation response field for field.

        PRD 3.2: "Under the standard method, `connected_load_kw` is the sum of the demand-split general term and the HVAC term, divided by 1000 to convert volt-amperes to kilowatts, rounded half up to two decimals."
        PRD 3.2: "The continuous requirement is the top-circuit total plus half of the remainder total, but never more than `connected_load_kw` — the smaller of those two quantities is taken — rounded half up to two decimals."
        PRD 3.2: "`required_surge_kw` is then that motor surge figure plus 25 percent of the already-computed `required_continuous_kw`, rounded half up to two decimals."
        PRD 3.2: "A calculation is created in `DRAFT` with `revision_round_count` at zero and `reviewer_notes` unset, and the sizing arithmetic runs immediately, so the computed `connected_load_kw`, `required_continuous_kw` and `required_surge_kw` are already populated in the creation response."

        Design: Corner/entities/get_load_calculation_returns_stored_and_computed_fields
        """
        project = self._premises(api)
        created = validate_success(
            api.create_load_calculation(
                factories.load_calculation_payload(project.site_id),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        calculation = get_success_data(
            api.get_load_calculation(created["id"], headers=AHJ_HEADERS)
        )

        assert calculation["site_id"] == project.site_id
        assert calculation["method"] == LoadMethod.STANDARD
        assert calculation["backup_scope"] == BackupScope.ESSENTIAL_LOADS
        assert calculation["lighting_area_sqft"] == 2400
        assert calculation["appliance_load_va"] == 18000
        assert calculation["heating_va"] == 9600
        assert calculation["cooling_va"] == 7200
        assert [c["label"] for c in calculation["essential_circuits"]] == [
            "KITCHEN",
            "WELL_PUMP",
            "LIGHTS",
            "FRIDGE",
        ]
        assert_quantity(calculation, "connected_load_kw", 21.48)
        assert_quantity(calculation, "required_continuous_kw", 7.00)
        assert_quantity(calculation, "required_surge_kw", 9.25)
        assert calculation["status"] == LoadCalcStatus.DRAFT
        for field in ("connected_load_kw", "required_continuous_kw", "required_surge_kw"):
            assert calculation[field] == created[field], (
                "the read and the creation response disagree on {}".format(field)
            )

    def test_a_page_of_one_sites_calculations_reports_the_whole_filtered_set(self, api):
        """Two pages of a three-record set, each reporting the same total.

        The first page returns two of the three calculations and says there is more; the
        second, skipping those two, returns the last one and says there is not. The total is a
        property of the filtered set rather than of the page, so both pages report three.

        PRD 2.3: "List responses report their paging position in the envelope's `meta` object, which carries `limit`, `offset`, `total_count` and `has_more` alongside the two request-identification fields."
        PRD 2.3: "`offset` is the number of records to skip before the first returned record and defaults to 0."
        PRD 2.4: "Because relationships are not visible in the URL structure, every foreign key has a corresponding filtered-list read."

        Design: Corner/entities/list_load_calculations_with_limit_and_offset_returns_pagination_metadata
        """
        project = self._premises(api)
        for _ in range(3):
            validate_success(
                api.create_load_calculation(
                    factories.whole_home_load_calculation_payload(project.site_id),
                    headers=project.installer_headers,
                ),
                expected_status=201,
            )

        first_page, first_meta = validate_paginated(
            api.list_load_calculations(
                {"site_id": project.site_id, "limit": 2, "offset": 0},
                headers=project.installer_headers,
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_load_calculations(
                {"site_id": project.site_id, "limit": 2, "offset": 2},
                headers=project.installer_headers,
            )
        )

        assert len(first_page) == 2, "the first page should hold two of the three rows"
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(second_page) == 1, "the second page should hold the remaining row"
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2
        for row in first_page + second_page:
            assert row["site_id"] == project.site_id


class TestDeclaredDefaults:
    """What the server writes when the caller leaves a field out, or sets one it may not."""

    def test_omitted_optional_inputs_take_their_declared_defaults(self, api):
        """A premises with no solar and a whole-home sizing with nothing optional supplied.

        The premises omits the rooftop solar rating, which is not an absence but a zero. The
        whole-home calculation omits the measured peak, which the standard method forbids
        anyway, and omits the essential-circuit list, which whole-home scoping requires to be
        empty; it opens as a draft on its first round with no reviewer notes, and its connected
        load is computed from the nameplate inputs all the same.

        PRD 3.1: "The site is described by the `homeowner_name` of record (a non-empty string), the `utility_territory_code` the premise sits in (`TER_WEST`, `TER_EAST` or `TER_NORTH`, which is what later scopes dispatch-event capacity), the `service_panel_amps` main-panel rating (one of 100, 125, 200 or 400), the conditioned `floor_area_sqft` (which must be greater than zero), the five-digit `postal_code`, and `existing_pv_kw_dc`, the nameplate DC rating of solar already on the roof, which must not be negative and defaults to 0 when there is none."
        PRD 3.2: "Under the measured method the installer must supply `measured_peak_kw`, the fifteen-minute measured peak demand, which must be greater than zero; under the standard method that field must be omitted entirely."
        PRD 3.2: "Under essential-loads scoping the installer must enumerate `essential_circuits`, an ordered list of objects each carrying a `label`, a `load_kw` figure and a `has_motor` flag; under whole-home scoping that list must be empty."
        PRD 3.2: "A calculation is created in `DRAFT` with `revision_round_count` at zero and `reviewer_notes` unset, and the sizing arithmetic runs immediately, so the computed `connected_load_kw`, `required_continuous_kw` and `required_surge_kw` are already populated in the creation response."

        Design: Corner/entities/omitting_optional_inputs_applies_declared_defaults
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project, existing_pv_kw_dc=factories.OMIT)

        calculation = validate_success(
            api.create_load_calculation(
                factories.load_calculation_payload(
                    project.site_id,
                    backup_scope=BackupScope.WHOLE_HOME,
                    essential_circuits=factories.OMIT,
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        site = get_success_data(
            api.get_site(project.site_id, headers=project.installer_headers)
        )
        assert_quantity(site, "existing_pv_kw_dc", 0.0)
        assert_unset(calculation, "measured_peak_kw", "reviewer_notes")
        assert calculation["essential_circuits"] == []
        assert calculation["status"] == LoadCalcStatus.DRAFT
        assert calculation["revision_round_count"] == 0
        assert_quantity(calculation, "connected_load_kw", 21.48)

    def test_system_managed_properties_supplied_by_the_caller_are_ignored(self, api):
        """A payload naming its own id and its own version gets neither.

        The identifier is minted by the server, and the version counter is the server's own
        record of how many times the row has been written; a caller cannot open a record at 77.
        The premises is created with a server identifier and both audit timestamps.

        PRD 2.5: "`id` (string): a server-minted UUID. It carries no type prefix and no embedded meaning."
        PRD 2.5: "`version` (integer): a counter that increases by exactly one on every mutation of that resource."
        PRD 2.5: "`created_at` (string): the ISO 8601 UTC instant at which the resource was created, with three fractional-second digits, for example `2026-08-01T00:00:00.000Z`."

        Design: Corner/entities/create_site_with_client_supplied_system_fields_input_ignored
        """
        project = fixtures.certified_installer(api)

        site = validate_success(
            api.create_site(
                factories.site_payload(id=CLIENT_SUPPLIED_ID, version=77),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert site["id"] != CLIENT_SUPPLIED_ID, "the caller's id was stored"
        assert is_valid_uuid(site["id"])
        assert site["version"] != 77, "the caller's version was stored"
        assert_common_fields(site)


class TestRequestsThatNameNothingOrTooLittle:
    """Missing rows, missing fields and values outside a closed enumeration."""

    def test_reading_an_unknown_bank_answers_with_the_error_envelope(self, api):
        """A well-formed identifier matching no row is a 404, not an empty success.

        Nothing has been designed yet, so the identifier resolves to nothing and the bank's own
        not-found code is returned. The body is the error envelope, carrying a machine-readable
        code and a human-readable message rather than a resource.

        PRD 2.4: "The first identifier that resolves to nothing decides the response, and each entity type raises its own 404"
        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD 2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/entities/get_unknown_battery_system_returns_not_found
        """
        project = fixtures.certified_installer(api)
        fixtures.site_for(api, project)

        response = api.get_battery_system(UNKNOWN_ENTITY_ID, headers=AHJ_HEADERS)

        error = validate_error(
            response, ApiErrorId.ERR_BATTERY_SYSTEM_NOT_FOUND, expected_status=404
        )
        assert response.json()["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"], (
            "the error carries no human-readable message"
        )

    def test_a_premises_without_a_postal_code_is_refused(self, api):
        """The postal code is a required input with no default to fall back on.

        Every other field of the premises is present and valid, so the only thing wrong with
        the request is the omission, and the answer is the generic malformed-payload code.

        PRD 2.4: "A request that omits a required field, sends null where a value is required, supplies a value outside a declared enumeration, sends a negative quantity where only non-negative values are meaningful, supplies a window whose `window_end` is not strictly after its `window_start`, sends an empty essential-circuit list under essential-loads scoping, registers a serial-number list whose length differs from the bank's `unit_count`, or supplies a firmware string that is not three dot-separated integers, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD 3.1: "The site is described by the `homeowner_name` of record (a non-empty string), the `utility_territory_code` the premise sits in (`TER_WEST`, `TER_EAST` or `TER_NORTH`, which is what later scopes dispatch-event capacity), the `service_panel_amps` main-panel rating (one of 100, 125, 200 or 400), the conditioned `floor_area_sqft` (which must be greater than zero), the five-digit `postal_code`, and `existing_pv_kw_dc`, the nameplate DC rating of solar already on the roof, which must not be negative and defaults to 0 when there is none."

        Design: Corner/entities/create_site_with_missing_required_postal_code_returns_invalid_request
        """
        project = fixtures.certified_installer(api)

        validate_error(
            api.create_site(
                factories.site_payload(postal_code=factories.OMIT),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

    def test_a_backup_scope_outside_the_enumeration_is_refused(self, api):
        """A third scope name is not stored as an unknown member; it is rejected.

        The scope field admits exactly two values, so a request naming a third is malformed and
        nothing is written — the site's calculations remain an empty set.

        PRD 3.2: "The `backup_scope` is either `WHOLE_HOME` or `ESSENTIAL_LOADS`."
        PRD 2.4: "A request that omits a required field, sends null where a value is required, supplies a value outside a declared enumeration, sends a negative quantity where only non-negative values are meaningful, supplies a window whose `window_end` is not strictly after its `window_start`, sends an empty essential-circuit list under essential-loads scoping, registers a serial-number list whose length differs from the bank's `unit_count`, or supplies a firmware string that is not three dot-separated integers, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_load_calculation_with_invalid_enum_backup_scope_rejected
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)

        validate_error(
            api.create_load_calculation(
                factories.load_calculation_payload(
                    project.site_id,
                    backup_scope="PARTIAL_HOME",
                    essential_circuits=factories.OMIT,
                ),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        calculations, _ = validate_paginated(
            api.list_load_calculations(
                {"site_id": project.site_id}, headers=project.installer_headers
            )
        )
        assert calculations == [], "a refused calculation left a row behind"

    def test_a_permit_naming_a_bank_that_does_not_exist_is_refused(self, api):
        """The child names its parent in the body, and that name has to resolve.

        There is no nested permit URL to make the parent implicit: the permit carries the bank
        it covers as a field of its own payload, so an unknown bank is answered with the bank's
        404 and no permit is discoverable against that identifier.

        PRD 2.4: "There are no nested ownership URLs in this API. Every resource collection is mounted at the root of the service, and a child resource points at its parent through a foreign-key field in its own body rather than through its position in a URL."
        PRD 2.12: "Every referenced resource resolves, path parameters left to right and then body foreign keys in declaration order, each miss raising that entity's own 404."

        Design: Corner/entities/flat_topology_permit_creation_with_unknown_system_returns_not_found
        """
        project = fixtures.certified_installer(api)
        project = fixtures.site_for(api, project)
        project = fixtures.approved_load_calculation(api, project)

        validate_error(
            api.create_permit(
                factories.permit_payload(UNKNOWN_ENTITY_ID),
                headers=project.installer_headers,
            ),
            ApiErrorId.ERR_BATTERY_SYSTEM_NOT_FOUND,
            expected_status=404,
        )

        permits, _ = validate_paginated(
            api.list_permits(
                {"battery_system_id": UNKNOWN_ENTITY_ID},
                headers=project.installer_headers,
            )
        )
        assert permits == [], "a refused permit left a row behind"
