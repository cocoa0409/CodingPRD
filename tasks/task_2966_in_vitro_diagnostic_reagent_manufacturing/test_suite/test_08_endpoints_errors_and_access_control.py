"""Endpoint surface, error surface and access control.

Covers the reference-data CRUD shape and the response envelope, the declared
list filters, the child collections hanging off each parent, the logical-clock
endpoint, one representative of every HTTP status class in the error catalogue,
the role closures of PRD §2.1 and §4, the duty separation of PRD §2.9, the two
optimistic-concurrency guards of PRD §2.5, the strict cold-chain limits of
PRD §3.9 and the immediate visibility promised by PRD §2.10.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions, factories, fixtures, test_users
from test_helpers.api_errors import HTTP_STATUS_CODES, ApiErrorId

# Query parameters travel as strings, so booleans are spelled out.
TRUE = "true"
FALSE = "false"


def _three_reference_specifications(api):
    """One specification per material type the filters must separate: a critical
    antibody, a non-critical enzyme and a critical calibrator material."""
    antibody = fixtures.create_material_specification(
        api, test_users.REGULATORY_AFFAIRS,
        material_type="ANTIBODY", is_critical=True)
    enzyme = fixtures.create_material_specification(
        api, test_users.REGULATORY_AFFAIRS,
        material_type="ENZYME", is_critical=False)
    calibrator = fixtures.create_material_specification(
        api, test_users.REGULATORY_AFFAIRS,
        material_type="CALIBRATOR_MATERIAL", is_critical=True)
    return antibody, enzyme, calibrator


def _codes_of(rows):
    return sorted(row["material_code"] for row in rows)


class TestReferenceDataShapeAndEnvelope:
    """The raw material specification collection, read through its full shape."""

    def test_registering_a_specification_returns_the_created_resource(self, api):
        """PRD §4: "Endpoints that create a new resource answer with HTTP 201 and
        return the created resource in `data`; endpoints that modify an existing
        resource, read one, or list many answer with HTTP 200 and return the
        affected or requested resource (or array of resources) in `data`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."
        PRD §2.4: "Every resource this API returns carries a server-minted `id`: a
        UUID string with no type prefix and no embedded meaning."
        PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC
        timestamp rendered with exactly three fractional digits."
        PRD §2.4: "Twelve of the fourteen aggregates additionally carry
        `updated_at` — same format as `created_at`, refreshed on every mutation of
        the row — and `version`, an integer that starts at 1 when the row is
        created and increases by exactly 1 on every mutation of that row,
        including mutations reached indirectly through a cascade."

        Design: Corner/endpoints/reference_data_endpoints_expose_the_full_crud_shape_and_the_declared_envelope
        """
        payload = factories.material_specification_payload(
            material_type="ANTIBODY", is_critical=True)
        response = api.create_material_specification(
            payload, test_users.REGULATORY_AFFAIRS)
        assert response.status_code == 201
        body = response.json()
        assert body["response_type"] == "object"
        created = validate_success(response, 201)

        assertions.assert_material_specification(created)
        assert is_valid_uuid(created["id"])
        assertions.assert_three_fractional_digits(created["created_at"])
        assert created["version"] == 1
        assert created["material_code"] == payload["material_code"]
        assert created["material_type"] == "ANTIBODY"
        assert created["is_critical"] is True

    def test_reading_a_specification_echoes_every_declared_bound(self, api):
        """PRD §3.1: "The specification declares its `material_type` as one of
        `ANTIBODY`, `ENZYME`, `CALIBRATOR_MATERIAL` or `BUFFER`, and it declares
        the acceptance bounds the laboratory will test against: `potency_min_pct`
        and `potency_max_pct` as the lower and upper percent-of-label window,
        `purity_min_pct` as the percent-purity floor, and
        `endotoxin_max_eu_per_ml` as the endotoxin ceiling in EU per millilitre."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
        timestamp with three fractional digits."

        Design: Corner/endpoints/reference_data_endpoints_expose_the_full_crud_shape_and_the_declared_envelope
        """
        payload = factories.material_specification_payload(
            potency_min_pct=92.5, potency_max_pct=107.5,
            purity_min_pct=96.0, endotoxin_max_eu_per_ml=8.0)
        created = fixtures.created(api.create_material_specification(
            payload, test_users.REGULATORY_AFFAIRS))

        response = api.get_material_specification(
            created["id"], test_users.QC_ANALYST)
        read = validate_success(response, 200)
        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assertions.assert_three_fractional_digits(meta["api_request_timestamp"])

        assert read["id"] == created["id"]
        assert read["version"] == 1
        assert read["potency_min_pct"] == 92.5
        assert read["potency_max_pct"] == 107.5
        assert read["purity_min_pct"] == 96.0
        assert read["endotoxin_max_eu_per_ml"] == 8.0
        assert read["required_test_codes"] == payload["required_test_codes"]

    def test_the_unfiltered_list_reports_the_declared_pagination_defaults(self, api):
        """PRD §2.3: "`limit` controls page size: its default is 10, its minimum
        accepted value is 1, and its maximum accepted value is 100."
        PRD §2.3: "`offset` controls the starting position: its default is 0 and
        its minimum accepted value is 0, with no upper bound."
        PRD §2.3: "Every list response populates four pagination fields inside
        `meta`: `limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many rows matched the filters before the page
        window was applied, and `has_more` is true exactly when rows matching the
        filters remain beyond the current window."
        PRD §2.3: "Unless a subsection of §3 states a different ordering for a
        particular collection, list results are sorted by `created_at` ascending."

        Design: Corner/endpoints/reference_data_endpoints_expose_the_full_crud_shape_and_the_declared_envelope
        """
        antibody, enzyme, calibrator = _three_reference_specifications(api)

        rows, meta = validate_paginated(
            api.list_material_specifications(test_users.PLATFORM_ADMIN))
        assertions.assert_paginated_meta(meta, expected_limit=10,
                                         expected_offset=0, expected_total=3,
                                         expected_has_more=False)
        assert len(rows) == 3
        assertions.assert_sorted_by_created_at(rows)
        assert _codes_of(rows) == _codes_of([antibody, enzyme, calibrator])

    def test_each_declared_filter_narrows_the_specification_list(self, api):
        """PRD §3.1: "Specifications can be listed and filtered by
        `material_type` and by `is_critical`."
        PRD §2.3: "Every list response populates four pagination fields inside
        `meta`: `limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many rows matched the filters before the page
        window was applied, and `has_more` is true exactly when rows matching the
        filters remain beyond the current window."

        Design: Corner/endpoints/reference_data_endpoints_expose_the_full_crud_shape_and_the_declared_envelope
        """
        antibody, enzyme, calibrator = _three_reference_specifications(api)

        rows, meta = validate_paginated(api.list_material_specifications(
            test_users.QC_ANALYST, params={"material_type": "ENZYME"}))
        assertions.assert_paginated_meta(meta, expected_total=1,
                                         expected_has_more=False)
        assert _codes_of(rows) == [enzyme["material_code"]]

        rows, meta = validate_paginated(api.list_material_specifications(
            test_users.QC_ANALYST, params={"is_critical": TRUE}))
        assertions.assert_paginated_meta(meta, expected_total=2,
                                         expected_has_more=False)
        assert _codes_of(rows) == _codes_of([antibody, calibrator])

    def test_two_filters_that_share_no_row_return_an_empty_page(self, api):
        """PRD §2.3: "Filters offered by a specific list endpoint are named in
        §4's description column and in the §3 narrative that governs the
        corresponding workflow; filters combine conjunctively, so a request that
        supplies two filters returns only rows satisfying both."

        Design: Corner/endpoints/reference_data_endpoints_expose_the_full_crud_shape_and_the_declared_envelope
        """
        _three_reference_specifications(api)

        response = api.list_material_specifications(
            test_users.REGULATORY_AFFAIRS,
            params={"material_type": "ANTIBODY", "is_critical": FALSE})
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0,
                                         expected_has_more=False)

    def test_an_unknown_specification_identifier_returns_the_error_envelope(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/reference_data_endpoints_expose_the_full_crud_shape_and_the_declared_envelope
        """
        response = api.get_material_specification(
            NON_EXISTENT_UUID, test_users.QC_ANALYST)
        error = validate_error(
            response, ApiErrorId.ERR_MATERIAL_SPECIFICATION_NOT_FOUND.value, 404)
        assert error["message"].strip()
        assert set(response.json()["meta"].keys()) == {
            "api_request_id", "api_request_timestamp"}


class TestFilteredListDimensions:
    """The finished-lot and measurement collections, narrowed one dimension at
    a time."""

    def test_finished_lots_narrow_by_their_parent_product(self, api):
        """PRD §3.3: "Finished lots are listable and filterable independently on
        both axes by `disposition_status` and `distribution_status`, and
        additionally by `product_specification_id`, by `lot_code`, and by
        `shelf_life_basis_study_id` for finding every lot whose shelf life was
        pinned from one particular stability study."

        Design: Corner/endpoints/filtered_lists_narrow_the_same_collection_along_each_declared_dimension
        """
        first_product = fixtures.create_product_specification(api)
        second_product = fixtures.create_product_specification(api)
        lot_a = fixtures.create_reagent_lot(api, first_product["id"])
        lot_b = fixtures.create_reagent_lot(api, first_product["id"])
        lot_c = fixtures.create_reagent_lot(api, second_product["id"])

        rows, meta = validate_paginated(api.list_reagent_lots(
            test_users.PRODUCTION_OPERATOR,
            params={"product_specification_id": first_product["id"]}))
        assertions.assert_paginated_meta(meta, expected_total=2,
                                         expected_has_more=False)
        assert sorted(row["id"] for row in rows) == sorted(
            [lot_a["id"], lot_b["id"]])
        assert lot_c["id"] not in [row["id"] for row in rows]

        rows, meta = validate_paginated(api.list_reagent_lots(
            test_users.PRODUCTION_OPERATOR,
            params={"lot_code": lot_c["lot_code"]}))
        assertions.assert_paginated_meta(meta, expected_total=1)
        assert rows[0]["id"] == lot_c["id"]

    def test_the_two_finished_lot_state_axes_filter_together(self, api):
        """PRD §3.3: "Finished lots are listable and filterable independently on
        both axes by `disposition_status` and `distribution_status`, and
        additionally by `product_specification_id`, by `lot_code`, and by
        `shelf_life_basis_study_id` for finding every lot whose shelf life was
        pinned from one particular stability study."
        PRD §2.3: "Filters offered by a specific list endpoint are named in §4's
        description column and in the §3 narrative that governs the corresponding
        workflow; filters combine conjunctively, so a request that supplies two
        filters returns only rows satisfying both."

        Design: Corner/endpoints/filtered_lists_narrow_the_same_collection_along_each_declared_dimension
        """
        product = fixtures.create_product_specification(api)
        for _ in range(3):
            fixtures.create_reagent_lot(api, product["id"])

        rows, meta = validate_paginated(api.list_reagent_lots(
            test_users.QA_RELEASER,
            params={"disposition_status": "PLANNED",
                    "distribution_status": "WITHHELD"}))
        assertions.assert_paginated_meta(meta, expected_total=3,
                                         expected_has_more=False)
        assert len(rows) == 3
        for row in rows:
            assert row["disposition_status"] == "PLANNED"
            assert row["distribution_status"] == "WITHHELD"

        rows, meta = validate_paginated(api.list_reagent_lots(
            test_users.QA_RELEASER,
            params={"disposition_status": "RELEASED"}))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0,
                                         expected_has_more=False)

    def test_measurements_narrow_by_subject_and_by_test_code(self, api):
        """PRD §3.5: "Measurements of all three subject kinds are readable
        individually and listable together, filterable by `subject_type`, by
        `material_lot_id`, by `reagent_lot_id`, by `stability_study_id`, by
        `test_code` and by `is_retest`; like monitoring samples they are immutable
        event records carrying `id` and `created_at` but no `updated_at` and no
        `version`."

        Design: Corner/endpoints/filtered_lists_narrow_the_same_collection_along_each_declared_dimension
        """
        bundle = fixtures.material_lot_under_test(
            api, test_codes=["POTENCY", "PURITY"])
        lot_id = bundle["lot"]["id"]

        rows, meta = validate_paginated(api.list_test_results(
            test_users.QC_ANALYST,
            params={"subject_type": "MATERIAL_LOT", "material_lot_id": lot_id}))
        assertions.assert_paginated_meta(meta, expected_total=2,
                                         expected_has_more=False)
        assert sorted(row["test_code"] for row in rows) == ["POTENCY", "PURITY"]
        for row in rows:
            assertions.assert_event_record_fields(row, "test result")

        rows, meta = validate_paginated(api.list_test_results(
            test_users.QC_ANALYST,
            params={"subject_type": "MATERIAL_LOT", "material_lot_id": lot_id,
                    "test_code": "PURITY"}))
        assertions.assert_paginated_meta(meta, expected_total=1)
        assert rows[0]["test_code"] == "PURITY"

    def test_a_subject_kind_with_no_measurement_lists_empty(self, api):
        """PRD §3.5: "Measurements of all three subject kinds are readable
        individually and listable together, filterable by `subject_type`, by
        `material_lot_id`, by `reagent_lot_id`, by `stability_study_id`, by
        `test_code` and by `is_retest`; like monitoring samples they are immutable
        event records carrying `id` and `created_at` but no `updated_at` and no
        `version`."
        PRD §2.3: "Every list response populates four pagination fields inside
        `meta`: `limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many rows matched the filters before the page
        window was applied, and `has_more` is true exactly when rows matching the
        filters remain beyond the current window."

        Design: Corner/endpoints/filtered_lists_narrow_the_same_collection_along_each_declared_dimension
        """
        fixtures.material_lot_under_test(api, test_codes=["POTENCY"])

        rows, meta = validate_paginated(api.list_test_results(
            test_users.QC_ANALYST, params={"subject_type": "REAGENT_LOT"}))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_limit=10,
                                         expected_offset=0, expected_total=0,
                                         expected_has_more=False)


class TestChildCollections:
    """Every child collection reachable from the parent that owns it."""

    def test_one_dispensing_row_is_readable_from_both_of_its_parents(self, api):
        """PRD §3.1: "Every dispensing record ever drawn from a raw material lot
        remains readable against that lot, `CONSUMED` and `RETURNED` rows alike,
        filterable by `status`."
        PRD §3.3: "The dispensing rows of a finished lot are listable and
        filterable by `status` and by `component_role`."
        PRD §3.3: "Each successful call creates a dispensing row whose
        `reagent_lot_id` points at the finished lot, whose `status` starts as
        `CONSUMED`, and whose two snapshot fields are copied at creation time:
        `material_code_snapshot` takes the `material_code` of the consumed lot's
        specification, and `vendor_lot_code_snapshot` takes the consumed lot's
        `vendor_lot_code`."

        Design: Corner/endpoints/child_collections_are_reachable_from_each_declared_parent_and_start_empty
        """
        bundle = fixtures.reagent_lot_with_bom(
            api, material_types=("ANTIBODY",), quantity_used=120.00)
        component = bundle["components"][0]
        material_lot = bundle["materials"][0]["lot"]

        from_material, material_meta = validate_paginated(
            api.list_material_lot_components(material_lot["id"],
                                             test_users.QC_ANALYST))
        assertions.assert_paginated_meta(material_meta, expected_total=1,
                                         expected_has_more=False)
        from_reagent, reagent_meta = validate_paginated(
            api.list_reagent_lot_components(bundle["lot"]["id"],
                                            test_users.QC_ANALYST))
        assertions.assert_paginated_meta(reagent_meta, expected_total=1,
                                         expected_has_more=False)

        assert from_material[0]["id"] == component["id"]
        assert from_reagent[0]["id"] == component["id"]
        for row in (from_material[0], from_reagent[0]):
            assert row["status"] == "CONSUMED"
            assert row["quantity_used"] == 120.00
            assert row["reagent_lot_id"] == bundle["lot"]["id"]
            assert row["material_lot_id"] == material_lot["id"]
            assert row["component_role"] == "ANTIBODY"

    def test_a_component_role_filter_matching_nothing_returns_an_empty_page(self, api):
        """PRD §3.3: "The dispensing rows of a finished lot are listable and
        filterable by `status` and by `component_role`."
        PRD §2.3: "Every list response populates four pagination fields inside
        `meta`: `limit` and `offset` echo the effective values used for the page,
        `total_count` reports how many rows matched the filters before the page
        window was applied, and `has_more` is true exactly when rows matching the
        filters remain beyond the current window."

        Design: Corner/endpoints/child_collections_are_reachable_from_each_declared_parent_and_start_empty
        """
        bundle = fixtures.reagent_lot_with_bom(api, material_types=("ANTIBODY",))

        rows, meta = validate_paginated(api.list_reagent_lot_components(
            bundle["lot"]["id"], test_users.PRODUCTION_OPERATOR,
            params={"component_role": "ENZYME"}))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0,
                                         expected_has_more=False)

        rows, meta = validate_paginated(api.list_reagent_lot_components(
            bundle["lot"]["id"], test_users.PRODUCTION_OPERATOR,
            params={"component_role": "ANTIBODY", "status": "CONSUMED"}))
        assertions.assert_paginated_meta(meta, expected_total=1)
        assert rows[0]["component_role"] == "ANTIBODY"

    def test_monitoring_samples_hang_off_their_run_and_filter_by_type(self, api):
        """PRD §3.4: "They are listable per run and filterable by `sample_type`
        and by `excursion`."
        PRD §3.4: "Each sample records the `fill_run_id` of the run it belongs to,
        taken from the path rather than the body."
        PRD §3.4: "Monitoring samples are immutable event records: they carry `id`
        and `created_at` but no `updated_at` and no `version`."

        Design: Corner/endpoints/child_collections_are_reachable_from_each_declared_parent_and_start_empty
        """
        bundle = fixtures.running_fill_run(api)
        run_id = bundle["run"]["id"]
        fixtures.record_monitoring_sample(api, run_id, "VIABLE_AIR", 4.00)
        fixtures.record_bioburden_sample(api, run_id, 2.00)

        rows, meta = validate_paginated(
            api.list_monitoring_samples(run_id, test_users.QC_ANALYST))
        assertions.assert_paginated_meta(meta, expected_total=2,
                                         expected_has_more=False)
        assert sorted(row["sample_type"] for row in rows) == [
            "BIOBURDEN_BULK", "VIABLE_AIR"]
        for row in rows:
            assert row["fill_run_id"] == run_id
            assertions.assert_event_record_fields(row, "monitoring sample")

        rows, meta = validate_paginated(api.list_monitoring_samples(
            run_id, test_users.QC_ANALYST,
            params={"sample_type": "BIOBURDEN_BULK"}))
        assertions.assert_paginated_meta(meta, expected_total=1)
        assert rows[0]["sample_type"] == "BIOBURDEN_BULK"

    def test_an_excursion_filter_finds_nothing_among_conforming_samples(self, api):
        """PRD §3.4: "`excursion` is true exactly when `result_value` is strictly
        greater than `limit_value`; a result equal to its limit is conforming."
        PRD §3.4: "The four monitoring channels each have their own action limit,
        which the server writes onto the sample as `limit_value`: viable air is
        limited to 10 colony-forming units per cubic metre, surface sampling to 5
        colony-forming units, non-viable particle counting to 3,520 particles per
        cubic metre, and bulk bioburden to 10 colony-forming units per millilitre."
        PRD §3.4: "They are listable per run and filterable by `sample_type` and
        by `excursion`."

        Design: Corner/endpoints/child_collections_are_reachable_from_each_declared_parent_and_start_empty
        """
        bundle = fixtures.running_fill_run(api)
        run_id = bundle["run"]["id"]
        viable_air = fixtures.record_monitoring_sample(
            api, run_id, "VIABLE_AIR", 4.00)
        bioburden = fixtures.record_bioburden_sample(api, run_id, 2.00)

        assert viable_air["limit_value"] == 10
        assert bioburden["limit_value"] == 10
        assert viable_air["excursion"] is False
        assert bioburden["excursion"] is False

        rows, meta = validate_paginated(api.list_monitoring_samples(
            run_id, test_users.QC_ANALYST, params={"excursion": TRUE}))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0,
                                         expected_has_more=False)

    def test_a_lot_with_no_reservation_lists_an_empty_allocation_page(self, api):
        """PRD §3.5: "Every reservation ever drawn from a finished lot remains
        readable against that lot in any status, filterable by `status`."
        PRD §3.3: "The new lot starts with `disposition_status` `PLANNED` on the
        quality axis and `distribution_status` `WITHHELD` on the availability
        axis, with all five unit counters — `filled_units`, `available_units`,
        `allocated_units`, `shipped_units` and `quarantined_units` — initialised
        to 0, which satisfies the finished-goods ledger of §2.8 trivially."

        Design: Corner/endpoints/child_collections_are_reachable_from_each_declared_parent_and_start_empty
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])

        response = api.list_reagent_lot_allocations(
            lot["id"], test_users.DISTRIBUTION_PLANNER)
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_limit=10,
                                         expected_offset=0, expected_total=0,
                                         expected_has_more=False)
        assert lot["allocated_units"] == 0
        assert lot["shipped_units"] == 0
        assert lot["quarantined_units"] == 0


class TestLogicalClockEndpoint:
    """The shared clock every derived instant is read from."""

    def test_every_declared_role_may_move_the_logical_clock(self, api):
        """PRD §2.4: "Any of the six roles may move the clock to an arbitrary
        instant by supplying `current_utc`; the endpoint echoes the new value back
        as `{ current_utc: datetime }` and every subsequent server-stamped instant,
        every deadline comparison, every expiry comparison, every
        retest-window comparison and every remaining-shelf-life computation reads
        the value that was last set."

        Design: Corner/endpoints/the_clock_endpoint_is_shared_by_every_role_and_governs_every_derived_timestamp
        """
        instants = {
            "QCAnalyst": "2026-08-03T01:00:00.000Z",
            "ProductionOperator": "2026-08-04T02:00:00.000Z",
            "QAReleaser": "2026-08-05T03:00:00.000Z",
            "RegulatoryAffairs": "2026-08-06T04:00:00.000Z",
            "DistributionPlanner": "2026-08-07T05:00:00.000Z",
            "PlatformAdmin": "2026-08-08T06:00:00.000Z",
        }
        assert set(instants) == set(test_users.ROLE_HEADERS)
        for role, headers in test_users.ROLE_HEADERS.items():
            instant = instants[role]
            echoed = validate_success(api.set_clock(instant, headers), 200)
            assertions.assert_same_instant(echoed["current_utc"], instant,
                                           f"clock set by {role}")

    def test_server_stamped_instants_read_the_clock_that_was_last_set(self, api):
        """PRD §2.4: "Timestamps that the server stamps itself —
        `dispositioned_at`, `approved_at`, `cleared_at`, `released_at`,
        `fill_completed_at`, `started_at`, `ended_at`, `performed_at`,
        `decided_at`, `received_at`, `reported_at`, `field_action_decided_at`,
        `shipped_at` — are all read from a **logical clock** rather than from
        wall-clock time."
        PRD §2.4: "Before any caller has moved it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time
        under any circumstance."
        PRD §3.1: "The server stamps `performed_by_user_id` from the acting
        operator's identity and `performed_at` from the logical clock, and it
        computes `outcome` itself — clients never supply it."

        Design: Corner/endpoints/the_clock_endpoint_is_shared_by_every_role_and_governs_every_derived_timestamp
        """
        bundle = fixtures.material_lot_under_test(
            api, spec_overrides={"required_test_codes": ["POTENCY", "PURITY"]},
            test_codes=["POTENCY"])
        first = bundle["results"][0]
        assertions.assert_same_instant(first["performed_at"], "2026-08-01T00:00:00Z",
                                       "performed_at on the untouched clock")

        instant = "2026-09-10T08:15:00.000Z"
        assertions.assert_same_instant(
            fixtures.set_clock(api, instant, test_users.QC_ANALYST), instant)

        purity = fixtures.record_material_measurement(
            api, bundle["lot"]["id"], "PURITY",
            fixtures.passing_value_for(bundle["spec"], "PURITY"))
        assertions.assert_same_instant(purity["performed_at"], instant,
                                       "performed_at")
        assertions.assert_three_fractional_digits(purity["created_at"])

        lot = fixtures.ok(api.disposition_material_lot(
            bundle["lot"]["id"],
            factories.material_lot_disposition_payload("QUALIFY"),
            test_users.QA_RELEASER))
        assert lot["qualification_status"] == "QUALIFIED"
        assertions.assert_same_instant(lot["dispositioned_at"], instant,
                                       "dispositioned_at")

    def test_two_stamps_taken_after_one_clock_move_are_the_same_instant(self, api):
        """PRD §3.4: "On success `started_at` is stamped from the logical clock and
        the finished lot's `version` increases by 1."
        PRD §2.4: "Timestamps that the server stamps itself — `dispositioned_at`,
        `approved_at`, `cleared_at`, `released_at`, `fill_completed_at`,
        `started_at`, `ended_at`, `performed_at`, `decided_at`, `received_at`,
        `reported_at`, `field_action_decided_at`, `shipped_at` — are all read from
        a **logical clock** rather than from wall-clock time."
        PRD §2.4: "Before any caller has moved it, the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time
        under any circumstance."

        Design: Corner/endpoints/the_clock_endpoint_is_shared_by_every_role_and_governs_every_derived_timestamp
        """
        bundle = fixtures.reagent_lot_with_bom(api)
        instant = "2026-08-20T11:45:00.000Z"
        assertions.assert_same_instant(
            fixtures.set_clock(api, instant, test_users.PRODUCTION_OPERATOR),
            instant)

        run = fixtures.schedule_fill_run(api, bundle["lot"]["id"])
        run = fixtures.start_fill_run(api, run["id"])
        assertions.assert_same_instant(run["started_at"], instant, "started_at")

        aborted = fixtures.abort_fill_run(api, run["id"])
        assertions.assert_same_instant(aborted["ended_at"], instant, "ended_at")
        assertions.assert_same_instant(aborted["ended_at"], run["started_at"],
                                       "ended_at against started_at")


class TestErrorStatusClasses:
    """One representative identifier per HTTP status class the catalogue
    declares."""

    def test_a_read_with_no_identity_headers_answers_401(self, api):
        """PRD §2.1: "If either header is absent, or is present but empty, the
        request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD §2.6: "`X-User-ID` and `X-User-Role` are both present and non-empty,
        otherwise `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_UNAUTHENTICATED.value
        assert HTTP_STATUS_CODES[error_id] == 401

        response = api.list_material_specifications(test_users.NO_AUTH_HEADERS)
        error = validate_error(response, error_id, 401)
        assert error["message"].strip()

    def test_a_role_the_endpoint_does_not_grant_answers_403(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD §2.6: "`X-User-Role` is one of the six declared role names and is among
        the roles the endpoint grants, otherwise `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_FORBIDDEN_ROLE.value
        assert HTTP_STATUS_CODES[error_id] == 403

        response = api.create_material_specification(
            factories.material_specification_payload(),
            test_users.PRODUCTION_OPERATOR)
        validate_error(response, error_id, 403)

    def test_a_page_size_outside_the_declared_window_answers_400(self, api):
        """PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a
        malformed request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400
        rather than silently clamped."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_INVALID_REQUEST.value
        assert HTTP_STATUS_CODES[error_id] == 400

        validate_error(api.list_material_specifications(
            test_users.QC_ANALYST, params={"limit": 0}), error_id, 400)
        validate_error(api.list_material_specifications(
            test_users.QC_ANALYST, params={"limit": 101}), error_id, 400)
        validate_error(api.list_material_specifications(
            test_users.QC_ANALYST, params={"offset": -1}), error_id, 400)

    def test_an_unresolvable_path_identifier_answers_404(self, api):
        """PRD §2.6: "All not-found conditions carry HTTP 404."
        PRD §2.6: "Each identifier in the path resolves, left to right, to an
        existing row, otherwise the matching code from
        `ERR_MATERIAL_SPECIFICATION_NOT_FOUND`, `ERR_MATERIAL_LOT_NOT_FOUND`,
        `ERR_PRODUCT_SPECIFICATION_NOT_FOUND`,
        `ERR_DESIGN_CONTROL_RECORD_NOT_FOUND`, `ERR_REAGENT_LOT_NOT_FOUND`,
        `ERR_FILL_RUN_NOT_FOUND`, `ERR_STABILITY_STUDY_NOT_FOUND`,
        `ERR_BRIDGING_STUDY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
        `ERR_DISTRIBUTION_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or
        `ERR_TEST_RESULT_NOT_FOUND` (404)."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_MATERIAL_SPECIFICATION_NOT_FOUND.value
        assert HTTP_STATUS_CODES[error_id] == 404

        response = api.get_material_specification(
            NON_EXISTENT_UUID, test_users.REGULATORY_AFFAIRS)
        validate_error(response, error_id, 404)

    def test_a_repeated_material_code_answers_409(self, api):
        """PRD §3.1: "A `RegulatoryAffairs` user (or a `PlatformAdmin` maintaining
        reference data) registers one specification per raw material, identified by
        a `material_code` between 3 and 32 characters long that must be unique
        across the whole catalogue — a repeat registration is refused with
        `ERR_DUPLICATE_MATERIAL_CODE`."
        PRD §2.6: "All five carry HTTP 409, and the rung guards
        `POST /material-specifications`, `POST /product-specifications`,
        `POST /material-lots`, `POST /reagent-lots` and `POST /test-results`."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_DUPLICATE_MATERIAL_CODE.value
        assert HTTP_STATUS_CODES[error_id] == 409

        payload = factories.material_specification_payload()
        fixtures.created(api.create_material_specification(
            payload, test_users.REGULATORY_AFFAIRS))
        repeat = api.create_material_specification(
            factories.material_specification_payload(
                material_code=payload["material_code"]),
            test_users.PLATFORM_ADMIN)
        validate_error(repeat, error_id, 409)

    def test_a_stale_parent_version_answers_412(self, api):
        """PRD §2.5: "A `POST /reagent-lots/{id}/components` request must carry
        `expected_reagent_lot_version` as a non-optional input field, holding the
        `version` of the finished lot as the client last read it."
        PRD §2.5: "If that value does not equal the finished lot's current
        `version`, the request is rejected with `ERR_STALE_REAGENT_LOT_VERSION` and
        HTTP 412."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_STALE_REAGENT_LOT_VERSION.value
        assert HTTP_STATUS_CODES[error_id] == 412

        setup = fixtures.manufacturing_setup(
            api, material_types=("ANTIBODY", "ENZYME"), cleared=False)
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])
        stale_version = lot["version"]
        fixtures.dispense_component(api, lot["id"],
                                    setup["materials"][0]["lot"]["id"],
                                    "ANTIBODY")

        response = api.add_reagent_lot_component(
            lot["id"],
            factories.lot_component_payload(setup["materials"][1]["lot"]["id"],
                                            "ENZYME", stale_version),
            test_users.PRODUCTION_OPERATOR)
        validate_error(response, error_id, 412)

    def test_a_test_code_outside_the_specification_answers_422(self, api):
        """PRD §3.1: "The `test_code` must be a member of the governing
        specification's `required_test_codes`, otherwise the record is refused with
        `ERR_TEST_CODE_NOT_IN_SPEC`."
        PRD §5: "Every failure answers with the error envelope of §2.2, carrying
        the `error_id` from the table below in `data` together with a
        human-readable `message`."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_TEST_CODE_NOT_IN_SPEC.value
        assert HTTP_STATUS_CODES[error_id] == 422

        spec = fixtures.create_material_specification(
            api, test_users.REGULATORY_AFFAIRS,
            required_test_codes=["POTENCY"])
        lot = fixtures.create_material_lot(api, spec["id"])

        response = api.create_test_result(
            factories.material_test_result_payload(lot["id"], "PURITY", 99.0),
            test_users.QC_ANALYST)
        validate_error(response, error_id, 422)

    def test_a_trace_link_to_the_wrong_predecessor_answers_422(self, api):
        """PRD §3.2: "The traceability rules are strict and are enforced together:
        `traces_to_record_id` must be null exactly when `record_type` is
        `DESIGN_INPUT` and non-null otherwise, a `DESIGN_OUTPUT` must trace to a
        `DESIGN_INPUT`, a `VERIFICATION` or a `VALIDATION` must trace to a
        `DESIGN_OUTPUT`, and the predecessor must belong to the same
        `product_specification_id`."
        PRD §3.2: "Any breach — a null link on a non-input record, a link set on a
        design input, a link to the wrong predecessor type, or a link reaching
        across product specifications — is refused with `ERR_INVALID_TRACE_LINK`
        and HTTP 422."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        error_id = ApiErrorId.ERR_INVALID_TRACE_LINK.value
        assert HTTP_STATUS_CODES[error_id] == 422

        product = fixtures.create_product_specification(api)
        design_input = fixtures.file_design_record(api, product["id"],
                                                   "DESIGN_INPUT")
        current_version = fixtures.product_specification_version(
            api, product["id"])

        response = api.create_design_control_record(
            factories.design_control_record_payload(
                product["id"], "VERIFICATION", current_version,
                traces_to_record_id=design_input["id"]),
            test_users.REGULATORY_AFFAIRS)
        validate_error(response, error_id, 422)

    def test_none_of_the_refused_requests_persisted_anything(self, api):
        """PRD §2.1: "Authentication is checked before authorization, and both are
        checked before the request body is examined at all."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/errors/every_http_status_class_in_the_catalog_is_reachable_with_the_declared_status_code
        """
        payload = factories.material_specification_payload()
        fixtures.created(api.create_material_specification(
            payload, test_users.REGULATORY_AFFAIRS))

        validate_error(api.create_material_specification(
            factories.material_specification_payload(),
            test_users.NO_AUTH_HEADERS),
            ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        validate_error(api.create_material_specification(
            factories.material_specification_payload(),
            test_users.QC_ANALYST),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        validate_error(api.create_material_specification(
            factories.material_specification_payload(
                material_code=payload["material_code"]),
            test_users.REGULATORY_AFFAIRS),
            ApiErrorId.ERR_DUPLICATE_MATERIAL_CODE.value, 409)

        rows, meta = validate_paginated(
            api.list_material_specifications(test_users.QC_ANALYST))
        assertions.assert_paginated_meta(meta, expected_total=1,
                                         expected_has_more=False)
        assert [row["material_code"] for row in rows] == [payload["material_code"]]


def _expect_forbidden(responses):
    """Every response in the batch must be the role refusal of PRD §2.1."""
    for response in responses:
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


class TestPlatformAdminAuthority:
    """The reference-data-only role."""

    def test_the_administrator_may_maintain_reference_data(self, api):
        """PRD §2.1: "This role maintains reference data (raw material and product
        specifications) and books raw material in, but holds no quality,
        regulatory or distribution authority whatsoever: it cannot disposition,
        release, allocate, or decide anything."
        PRD §3.1: "When a vendor delivery arrives, a `ProductionOperator` (or a
        `PlatformAdmin`) books it in at goods-in against the governing
        specification."
        PRD §3.1: "The lot is created in `qualification_status` `RECEIVED`, with
        `available_quantity_units` initialised to `received_quantity_units`,
        `consumed_quantity_units` initialised to 0, `retest_count` at 0, and
        `first_oos_at`, `acceptance_score`, `dispositioned_by_user_id`,
        `dispositioned_at` and `quarantine_reason` all null."

        Design: Corner/rbac/platform_admin_holds_reference_data_only_and_every_decision_endpoint_returns_forbidden_role
        """
        admin = test_users.PLATFORM_ADMIN
        spec = validate_success(api.create_material_specification(
            factories.material_specification_payload(), admin), 201)
        product = validate_success(api.create_product_specification(
            factories.product_specification_payload(), admin), 201)
        lot = validate_success(api.create_material_lot(
            factories.material_lot_payload(spec["id"]), admin), 201)

        assert product["clearance_status"] == "DESIGN"
        assert lot["qualification_status"] == "RECEIVED"
        assert lot["available_quantity_units"] == lot["received_quantity_units"]
        assert lot["consumed_quantity_units"] == 0
        assert lot["dispositioned_by_user_id"] is None
        assert lot["dispositioned_at"] is None

    def test_the_administrator_is_refused_every_laboratory_and_production_write(self, api):
        """PRD §2.1: "This role maintains reference data (raw material and product
        specifications) and books raw material in, but holds no quality,
        regulatory or distribution authority whatsoever: it cannot disposition,
        release, allocate, or decide anything."
        PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/platform_admin_holds_reference_data_only_and_every_decision_endpoint_returns_forbidden_role
        """
        admin = test_users.PLATFORM_ADMIN
        _expect_forbidden([
            api.create_test_result(factories.material_test_result_payload(
                NON_EXISTENT_UUID, "POTENCY", 100.00), admin),
            api.disposition_material_lot(
                NON_EXISTENT_UUID,
                factories.material_lot_disposition_payload("QUALIFY"), admin),
            api.create_reagent_lot(
                factories.reagent_lot_payload(NON_EXISTENT_UUID), admin),
            api.add_reagent_lot_component(
                NON_EXISTENT_UUID,
                factories.lot_component_payload(NON_EXISTENT_UUID, "ANTIBODY", 1),
                admin),
            api.create_fill_run(
                factories.fill_run_payload(NON_EXISTENT_UUID), admin),
            api.start_fill_run(NON_EXISTENT_UUID, admin),
            api.complete_fill_run(
                NON_EXISTENT_UUID, factories.fill_run_complete_payload(10), admin),
            api.abort_fill_run(
                NON_EXISTENT_UUID, factories.fill_run_abort_payload(), admin),
            api.create_monitoring_sample(
                NON_EXISTENT_UUID,
                factories.monitoring_sample_payload("VIABLE_AIR", 4.00), admin),
        ])

    def test_the_administrator_is_refused_every_quality_decision(self, api):
        """PRD §2.1: "This role maintains reference data (raw material and product
        specifications) and books raw material in, but holds no quality,
        regulatory or distribution authority whatsoever: it cannot disposition,
        release, allocate, or decide anything."
        PRD §2.1: "This is the only role that dispositions raw material lots and
        finished lots, moves a lot's commercial-availability dimension, approves
        design-control records and stability protocols, decides bridging studies,
        and decides complaint field actions."

        Design: Corner/rbac/platform_admin_holds_reference_data_only_and_every_decision_endpoint_returns_forbidden_role
        """
        admin = test_users.PLATFORM_ADMIN
        _expect_forbidden([
            api.disposition_reagent_lot(
                NON_EXISTENT_UUID,
                factories.reagent_lot_disposition_payload("RELEASE"), admin),
            api.set_reagent_lot_distribution_status(
                NON_EXISTENT_UUID,
                factories.distribution_status_payload("AVAILABLE"), admin),
            api.approve_design_control_record(NON_EXISTENT_UUID, admin),
            api.approve_stability_protocol(NON_EXISTENT_UUID, admin),
            api.decide_bridging_study(
                NON_EXISTENT_UUID,
                factories.bridging_decision_payload("APPROVE"), admin),
            api.decide_field_action(
                NON_EXISTENT_UUID,
                factories.field_action_payload("ADVISORY"), admin),
        ])

    def test_the_administrator_is_refused_the_regulatory_file(self, api):
        """PRD §2.1: "This role owns the design history file, the clearance
        submission, the stability and bridging programmes, and the complaint
        reporting file."
        PRD §2.1: "It has no operation of its own that no other role shares."

        Design: Corner/rbac/platform_admin_holds_reference_data_only_and_every_decision_endpoint_returns_forbidden_role
        """
        admin = test_users.PLATFORM_ADMIN
        _expect_forbidden([
            api.create_design_control_record(
                factories.design_control_record_payload(
                    NON_EXISTENT_UUID, "DESIGN_INPUT", 1), admin),
            api.record_product_clearance(
                NON_EXISTENT_UUID, factories.clearance_payload(), admin),
            api.create_stability_study(factories.stability_study_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID), admin),
            api.conclude_stability_study(NON_EXISTENT_UUID, admin),
            api.create_bridging_study(factories.bridging_study_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID), admin),
            api.create_complaint(
                factories.complaint_payload(NON_EXISTENT_UUID), admin),
            api.triage_complaint(
                NON_EXISTENT_UUID, factories.triage_payload("HIGH", True), admin),
            api.file_malfunction_report(
                NON_EXISTENT_UUID, factories.malfunction_report_payload(), admin),
            api.close_complaint(NON_EXISTENT_UUID, admin),
        ])

    def test_the_administrator_is_refused_distribution_and_leaves_no_trace(self, api):
        """PRD §2.1: "This role books customer orders, runs the allocation
        waterfall, ships and cancels reservations, and records cold-chain events."
        PRD §2.1: "This role maintains reference data (raw material and product
        specifications) and books raw material in, but holds no quality,
        regulatory or distribution authority whatsoever: it cannot disposition,
        release, allocate, or decide anything."

        Design: Corner/rbac/platform_admin_holds_reference_data_only_and_every_decision_endpoint_returns_forbidden_role
        """
        admin = test_users.PLATFORM_ADMIN
        spec = validate_success(api.create_material_specification(
            factories.material_specification_payload(), admin), 201)
        lot = validate_success(api.create_material_lot(
            factories.material_lot_payload(spec["id"]), admin), 201)

        _expect_forbidden([
            api.create_distribution_order(
                factories.distribution_order_payload(NON_EXISTENT_UUID), admin),
            api.allocate_distribution_order(NON_EXISTENT_UUID, admin),
            api.ship_allocation(NON_EXISTENT_UUID, admin),
            api.cancel_allocation(NON_EXISTENT_UUID, admin,
                                  factories.cancel_allocation_payload()),
            api.create_cold_chain_event(
                NON_EXISTENT_UUID,
                factories.cold_chain_event_payload(10.00, 8.0), admin),
            api.disposition_material_lot(
                lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
                admin),
        ])

        after = validate_success(api.get_material_lot(lot["id"], admin), 200)
        assert after["qualification_status"] == "RECEIVED"
        assert after["version"] == lot["version"]
        rows, meta = validate_paginated(api.list_reagent_lots(admin))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0)


class TestLaboratoryAndProductionClosure:
    """The analyst, the operator and the releaser cannot reach into each other's
    operations."""

    def test_only_the_analyst_may_record_measurements_and_samples(self, api):
        """PRD §2.1: "This role records every analytical measurement, whatever its
        subject, and every environmental or bioburden monitoring sample."
        PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/laboratory_and_production_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        bundle = fixtures.running_fill_run(api)
        lot_id = bundle["materials"][0]["lot"]["id"]
        run_id = bundle["run"]["id"]

        _expect_forbidden([
            api.create_test_result(factories.material_test_result_payload(
                lot_id, "POTENCY", 100.00), test_users.PRODUCTION_OPERATOR),
            api.create_test_result(factories.material_test_result_payload(
                lot_id, "POTENCY", 100.00), test_users.QA_RELEASER),
            api.create_monitoring_sample(
                run_id, factories.monitoring_sample_payload("VIABLE_AIR", 4.00),
                test_users.PRODUCTION_OPERATOR),
            api.create_monitoring_sample(
                run_id, factories.monitoring_sample_payload("VIABLE_AIR", 4.00),
                test_users.QA_RELEASER),
        ])

        rows, meta = validate_paginated(
            api.list_monitoring_samples(run_id, test_users.QC_ANALYST))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0)

    def test_only_the_operator_may_open_lots_and_drive_the_lines(self, api):
        """PRD §2.1: "This role books incoming raw material in at goods-in, opens
        finished-goods lots, dispenses the bill of materials, and schedules,
        starts, completes and aborts the filling lines."
        PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/laboratory_and_production_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        bundle = fixtures.reagent_lot_with_bom(api)
        lot_id = bundle["lot"]["id"]
        run = fixtures.schedule_fill_run(api, lot_id)

        _expect_forbidden([
            api.create_reagent_lot(
                factories.reagent_lot_payload(bundle["product"]["id"]),
                test_users.QC_ANALYST),
            api.create_fill_run(factories.fill_run_payload(lot_id),
                                test_users.QC_ANALYST),
            api.start_fill_run(run["id"], test_users.QC_ANALYST),
            api.complete_fill_run(run["id"],
                                  factories.fill_run_complete_payload(10),
                                  test_users.QC_ANALYST),
            api.abort_fill_run(run["id"], factories.fill_run_abort_payload(),
                               test_users.QA_RELEASER),
        ])

        after = validate_success(api.get_fill_run(run["id"],
                                                  test_users.QC_ANALYST), 200)
        assert after["status"] == "SCHEDULED"

    def test_the_releaser_cannot_dispense_even_with_a_fresh_parent_version(self, api):
        """PRD §2.1: "Authentication is checked before authorization, and both are
        checked before the request body is examined at all."
        PRD §2.6: "`X-User-Role` is one of the six declared role names and is among
        the roles the endpoint grants, otherwise `ERR_FORBIDDEN_ROLE` (403)."
        PRD §2.6: "When a single request violates several rules, exactly one error
        is returned: the one belonging to the lowest-numbered rung of the ladder
        below."

        Design: Corner/rbac/laboratory_and_production_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        setup = fixtures.manufacturing_setup(api, material_types=("ANTIBODY",),
                                             cleared=False)
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])
        fresh_version = fixtures.reagent_lot_version(api, lot["id"])

        response = api.add_reagent_lot_component(
            lot["id"],
            factories.lot_component_payload(setup["materials"][0]["lot"]["id"],
                                            "ANTIBODY", fresh_version),
            test_users.QA_RELEASER)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        rows, meta = validate_paginated(api.list_reagent_lot_components(
            lot["id"], test_users.QA_RELEASER))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0)

    def test_neither_the_analyst_nor_the_operator_may_decide_a_disposition(self, api):
        """PRD §2.1: "This is the only role that dispositions raw material lots and
        finished lots, moves a lot's commercial-availability dimension, approves
        design-control records and stability protocols, decides bridging studies,
        and decides complaint field actions."
        PRD §2.1: "It never decides a disposition."

        Design: Corner/rbac/laboratory_and_production_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        bundle = fixtures.material_lot_under_test(api, test_codes=["POTENCY"])
        material_lot_id = bundle["lot"]["id"]

        _expect_forbidden([
            api.disposition_material_lot(
                material_lot_id,
                factories.material_lot_disposition_payload("QUALIFY"),
                test_users.QC_ANALYST),
            api.disposition_material_lot(
                material_lot_id,
                factories.material_lot_disposition_payload("REJECT"),
                test_users.PRODUCTION_OPERATOR),
            api.disposition_reagent_lot(
                NON_EXISTENT_UUID,
                factories.reagent_lot_disposition_payload("RELEASE"),
                test_users.QC_ANALYST),
            api.set_reagent_lot_distribution_status(
                NON_EXISTENT_UUID,
                factories.distribution_status_payload("AVAILABLE"),
                test_users.PRODUCTION_OPERATOR),
            api.approve_design_control_record(NON_EXISTENT_UUID,
                                              test_users.QC_ANALYST),
            api.approve_stability_protocol(NON_EXISTENT_UUID,
                                           test_users.PRODUCTION_OPERATOR),
        ])

        after = validate_success(api.get_material_lot(
            material_lot_id, test_users.QA_RELEASER), 200)
        assert after["qualification_status"] == "UNDER_TEST"

    def test_each_role_still_performs_its_own_operation(self, api):
        """PRD §2.1: "This role records every analytical measurement, whatever its
        subject, and every environmental or bioburden monitoring sample."
        PRD §2.1: "This role books incoming raw material in at goods-in, opens
        finished-goods lots, dispenses the bill of materials, and schedules,
        starts, completes and aborts the filling lines."
        PRD §3.1: "The first acceptance measurement on a lot moves it from
        `RECEIVED` to `UNDER_TEST`."

        Design: Corner/rbac/laboratory_and_production_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        spec = fixtures.create_material_specification(
            api, test_users.REGULATORY_AFFAIRS, required_test_codes=["POTENCY"])
        product = fixtures.create_product_specification(api)

        lot = validate_success(api.create_material_lot(
            factories.material_lot_payload(spec["id"]),
            test_users.PRODUCTION_OPERATOR), 201)
        measurement = validate_success(api.create_test_result(
            factories.material_test_result_payload(lot["id"], "POTENCY", 100.00),
            test_users.QC_ANALYST), 201)
        finished = validate_success(api.create_reagent_lot(
            factories.reagent_lot_payload(product["id"]),
            test_users.PRODUCTION_OPERATOR), 201)

        assert measurement["outcome"] == "PASS"
        assert finished["disposition_status"] == "PLANNED"
        after = validate_success(api.get_material_lot(
            lot["id"], test_users.QC_ANALYST), 200)
        assert after["qualification_status"] == "UNDER_TEST"


class TestRegulatoryAndDistributionClosure:
    """The regulatory file and the distribution surface are closed against each
    other, with complaint intake as the single shared write."""

    def test_the_planner_is_refused_the_design_and_stability_file(self, api):
        """PRD §2.1: "This role owns the design history file, the clearance
        submission, the stability and bridging programmes, and the complaint
        reporting file."
        PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/regulatory_and_distribution_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        planner = test_users.DISTRIBUTION_PLANNER
        product = fixtures.create_product_specification(api)

        _expect_forbidden([
            api.create_design_control_record(
                factories.design_control_record_payload(
                    product["id"], "DESIGN_INPUT", product["version"]), planner),
            api.record_product_clearance(product["id"],
                                         factories.clearance_payload(), planner),
            api.create_stability_study(factories.stability_study_payload(
                product["id"], NON_EXISTENT_UUID), planner),
            api.conclude_stability_study(NON_EXISTENT_UUID, planner),
            api.create_bridging_study(factories.bridging_study_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID),
                planner),
        ])

        after = validate_success(api.get_product_specification(
            product["id"], planner), 200)
        assert after["clearance_status"] == "DESIGN"
        assert after["version"] == product["version"]

    def test_the_planner_is_refused_the_complaint_lifecycle(self, api):
        """PRD §2.1: "This role owns the design history file, the clearance
        submission, the stability and bridging programmes, and the complaint
        reporting file."
        PRD §3.8: "Triage is performed by a `RegulatoryAffairs` user on a complaint
        still in `RECEIVED`, supplying the `severity` as `LOW`, `MEDIUM` or `HIGH`
        and the boolean `malfunction_suspected` conclusion."

        Design: Corner/rbac/regulatory_and_distribution_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        planner = test_users.DISTRIBUTION_PLANNER
        bundle = fixtures.released_reagent_lot(api)
        complaint = fixtures.create_complaint(api, bundle["lot"]["id"], planner)

        _expect_forbidden([
            api.triage_complaint(complaint["id"],
                                 factories.triage_payload("HIGH", True), planner),
            api.file_malfunction_report(
                complaint["id"], factories.malfunction_report_payload(), planner),
            api.close_complaint(complaint["id"], planner),
        ])

        after = validate_success(api.get_complaint(complaint["id"], planner), 200)
        assert after["status"] == "RECEIVED"
        assert after["severity"] is None
        assert after["triaged_by_user_id"] is None

    def test_the_regulatory_role_is_refused_the_distribution_surface(self, api):
        """PRD §2.1: "This role books customer orders, runs the allocation
        waterfall, ships and cancels reservations, and records cold-chain events."
        PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/regulatory_and_distribution_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        regulatory = test_users.REGULATORY_AFFAIRS
        product = fixtures.create_product_specification(api)

        _expect_forbidden([
            api.create_distribution_order(
                factories.distribution_order_payload(product["id"]), regulatory),
            api.allocate_distribution_order(NON_EXISTENT_UUID, regulatory),
            api.ship_allocation(NON_EXISTENT_UUID, regulatory),
            api.cancel_allocation(NON_EXISTENT_UUID, regulatory,
                                  factories.cancel_allocation_payload()),
            api.create_cold_chain_event(
                NON_EXISTENT_UUID,
                factories.cold_chain_event_payload(10.00, 8.0), regulatory),
        ])

        rows, meta = validate_paginated(
            api.list_distribution_orders(regulatory))
        assert rows == []
        assertions.assert_paginated_meta(meta, expected_total=0)

    def test_the_regulatory_role_may_not_decide_the_field_action(self, api):
        """PRD §2.1: "This is the only role that dispositions raw material lots and
        finished lots, moves a lot's commercial-availability dimension, approves
        design-control records and stability protocols, decides bridging studies,
        and decides complaint field actions."
        PRD §3.8: "The **field-action branch** is decided by a `QAReleaser`
        supplying the `field_action` — one of `NONE`, `ADVISORY`, `CORRECTION` or
        `REMOVAL` — and an optional `justification`."

        Design: Corner/rbac/regulatory_and_distribution_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        bundle = fixtures.complaint_on_released_lot(api)
        complaint = bundle["complaint"]

        _expect_forbidden([
            api.decide_field_action(complaint["id"],
                                    factories.field_action_payload("ADVISORY"),
                                    test_users.REGULATORY_AFFAIRS),
            api.decide_field_action(complaint["id"],
                                    factories.field_action_payload("ADVISORY"),
                                    test_users.DISTRIBUTION_PLANNER),
        ])

        after = validate_success(api.get_complaint(
            complaint["id"], test_users.REGULATORY_AFFAIRS), 200)
        assert after["status"] == "TRIAGED"
        assert after["field_action"] is None
        assert after["field_action_decided_by_user_id"] is None

    def test_complaint_intake_is_the_single_shared_write(self, api):
        """PRD §3.8: "Complaints arrive from the field and are booked by either a
        `RegulatoryAffairs` user or a `DistributionPlanner`, who supply the
        `reagent_lot_id` of the implicated finished lot, the intake
        `complaint_code`, the `narrative` describing the reported failure, and
        optionally `device_related_death_or_injury`, which defaults to false and is
        true when the reporter alleges death or serious injury."
        PRD §3.8: "The server stamps `received_at` from the logical clock — this is
        the instant every reporting deadline is measured from — and creates the
        complaint in `status` `RECEIVED` with `severity`, `malfunction_suspected`,
        `reportable`, `report_due_at`, `report_ref`, `reported_at`, `report_late`,
        `field_action`, `field_action_decided_by_user_id`,
        `field_action_decided_at` and `triaged_by_user_id` all null."

        Design: Corner/rbac/regulatory_and_distribution_exclusive_operations_are_mutually_closed_returns_forbidden_role
        """
        bundle = fixtures.released_reagent_lot(api)
        lot_id = bundle["lot"]["id"]

        by_regulatory = validate_success(api.create_complaint(
            factories.complaint_payload(lot_id),
            test_users.REGULATORY_AFFAIRS), 201)
        by_planner = validate_success(api.create_complaint(
            factories.complaint_payload(lot_id),
            test_users.DISTRIBUTION_PLANNER), 201)

        for complaint in (by_regulatory, by_planner):
            assert complaint["status"] == "RECEIVED"
            assert complaint["reagent_lot_id"] == lot_id
            assert complaint["severity"] is None
            assert complaint["reportable"] is None
            assert complaint["report_due_at"] is None
            assert complaint["field_action"] is None
        assert by_regulatory["id"] != by_planner["id"]


class TestUndeclaredRole:
    """A role string outside the declared six is an authorization failure, while a
    missing or empty header is an authentication failure."""

    def test_an_undeclared_role_string_is_forbidden_on_a_read_and_on_a_write(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD §2.1: "Exactly six roles exist, spelled precisely as follows:"

        Design: Corner/rbac/an_undeclared_role_string_is_rejected_as_forbidden_role_not_as_unauthenticated
        """
        undeclared = test_users.headers_for_role("Auditor")

        validate_error(api.list_material_specifications(undeclared),
                       ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        validate_error(
            api.create_material_specification(
                factories.material_specification_payload(), undeclared),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        validate_error(
            api.list_material_specifications(
                test_users.headers_for_role("qcanalyst")),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        validate_error(
            api.list_material_specifications(test_users.headers_for_role("QC")),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_missing_or_empty_headers_are_unauthenticated_not_forbidden(self, api):
        """PRD §2.1: "If either header is absent, or is present but empty, the
        request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401."
        PRD §2.1: "Authentication is checked before authorization, and both are
        checked before the request body is examined at all."

        Design: Corner/rbac/an_undeclared_role_string_is_rejected_as_forbidden_role_not_as_unauthenticated
        """
        for headers in (test_users.NO_AUTH_HEADERS,
                        test_users.MISSING_ROLE_HEADERS,
                        test_users.MISSING_USER_ID_HEADERS,
                        test_users.EMPTY_ROLE_HEADERS,
                        test_users.EMPTY_USER_ID_HEADERS):
            validate_error(api.list_material_specifications(headers),
                           ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
            validate_error(
                api.create_material_specification(
                    factories.material_specification_payload(), headers),
                ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

        assert HTTP_STATUS_CODES[ApiErrorId.ERR_UNAUTHENTICATED.value] == 401
        assert HTTP_STATUS_CODES[ApiErrorId.ERR_FORBIDDEN_ROLE.value] == 403

    def test_a_declared_role_reads_what_the_undeclared_role_could_not_write(self, api):
        """PRD §2.1: "If `X-User-Role` carries a string that is not one of the six
        role names below, or names a role that the target endpoint does not grant,
        the request is rejected with `ERR_FORBIDDEN_ROLE` and HTTP 403."
        PRD §2.1: "Every request to every endpoint — reads included — must carry
        two headers: `X-User-ID`, identifying the acting operator, and
        `X-User-Role`, naming that operator's role."

        Design: Corner/rbac/an_undeclared_role_string_is_rejected_as_forbidden_role_not_as_unauthenticated
        """
        spec = fixtures.create_material_specification(api)
        undeclared = test_users.headers_for_role("SuperUser")

        validate_error(
            api.create_material_specification(
                factories.material_specification_payload(), undeclared),
            ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
        validate_error(api.get_material_specification(spec["id"], undeclared),
                       ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

        rows, meta = validate_paginated(
            api.list_material_specifications(test_users.REGULATORY_AFFAIRS))
        assert _codes_of(rows) == [spec["material_code"]]
        assertions.assert_paginated_meta(meta, expected_total=1)


class TestFieldActionDutySeparation:
    """The releaser who put a lot on the market may not decide the field action on a
    complaint against that same lot."""

    def test_the_lots_releaser_may_not_decide_its_own_field_action(self, api):
        """PRD §2.9: "When a complaint's field action is decided, the acting
        `X-User-ID` must differ from `released_by_user_id` on the implicated
        finished lot."
        PRD §2.9: "Three quality decisions may not be taken by the operator who
        performed the incompatible earlier step, and all three raise
        `ERR_SEGREGATION_OF_DUTIES` with HTTP 403."

        Design: Corner/rbac/segregation_of_duties_blocks_the_lot_releaser_from_deciding_its_field_action
        """
        bundle = fixtures.complaint_on_released_lot(
            api, releaser_headers=test_users.QA_RELEASER)
        assert bundle["lot"]["released_by_user_id"] == \
            test_users.QA_RELEASER_USER_ID

        response = api.decide_field_action(
            bundle["complaint"]["id"],
            factories.field_action_payload("ADVISORY"), test_users.QA_RELEASER)
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        assert HTTP_STATUS_CODES[
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value] == 403

        after = validate_success(api.get_complaint(
            bundle["complaint"]["id"], test_users.REGULATORY_AFFAIRS), 200)
        assert after["status"] == "TRIAGED"
        assert after["field_action"] is None
        assert after["field_action_decided_at"] is None
        assert after["version"] == bundle["complaint"]["version"]

    def test_a_different_releaser_decides_the_same_field_action(self, api):
        """PRD §3.8: "Whichever of the two admitted starting states applies, the
        effect is identical: `field_action`, `field_action_decided_by_user_id` and
        `field_action_decided_at` are stored, `status` becomes
        `FIELD_ACTION_DECIDED`, `version` increases by 1, and any result already
        produced by the reporting branch is preserved intact."
        PRD §2.9: "When a complaint's field action is decided, the acting
        `X-User-ID` must differ from `released_by_user_id` on the implicated
        finished lot."

        Design: Corner/rbac/segregation_of_duties_blocks_the_lot_releaser_from_deciding_its_field_action
        """
        bundle = fixtures.complaint_on_released_lot(
            api, releaser_headers=test_users.QA_RELEASER)
        complaint = bundle["complaint"]

        decided = validate_success(api.decide_field_action(
            complaint["id"], factories.field_action_payload("ADVISORY"),
            test_users.QA_RELEASER_2), 200)

        assert decided["field_action"] == "ADVISORY"
        assert decided["field_action_decided_by_user_id"] == \
            test_users.QA_RELEASER_2_USER_ID
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert decided["version"] == complaint["version"] + 1
        assert decided["field_action_decided_at"] is not None

    def test_the_same_releaser_decides_a_complaint_on_a_lot_it_never_released(self, api):
        """PRD §2.9: "When a complaint's field action is decided, the acting
        `X-User-ID` must differ from `released_by_user_id` on the implicated
        finished lot."
        PRD §3.8: "A `field_action` of `NONE` or `ADVISORY` stops there."

        Design: Corner/rbac/segregation_of_duties_blocks_the_lot_releaser_from_deciding_its_field_action
        """
        bundle = fixtures.filled_reagent_lot(api)
        assertions.assert_absent_or_none(bundle["lot"], "released_by_user_id")

        complaint = fixtures.triaged_complaint(api, bundle["lot"]["id"])
        decided = validate_success(api.decide_field_action(
            complaint["id"], factories.field_action_payload("ADVISORY"),
            test_users.QA_RELEASER), 200)

        assert decided["field_action"] == "ADVISORY"
        assert decided["field_action_decided_by_user_id"] == \
            test_users.QA_RELEASER_USER_ID
        assert decided["status"] == "FIELD_ACTION_DECIDED"

        after = validate_success(api.get_reagent_lot(
            bundle["lot"]["id"], test_users.QA_RELEASER), 200)
        assert after["disposition_status"] == "FILLED"


class TestParentVersionGuards:
    """The two version-guarded writes each reject a stale parent version and accept
    the refreshed one."""

    def test_filing_a_design_record_raises_the_parent_version(self, api):
        """PRD §2.5: "A `POST /design-control-records` request must carry
        `expected_product_specification_version` as a non-optional input field,
        holding the `version` of the parent product specification as the client last
        read it."
        PRD §3.2: "Filing also recomputes the parent's `design_trace_complete` flag
        and increases the parent product specification's `version` by 1, which is
        exactly why the next filer needs a fresh
        `expected_product_specification_version`."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        product = fixtures.create_product_specification(api)
        assert product["version"] == 1

        record = validate_success(api.create_design_control_record(
            factories.design_control_record_payload(product["id"],
                                                    "DESIGN_INPUT", 1),
            test_users.REGULATORY_AFFAIRS), 201)

        assert record["trace_depth"] == 1
        assert record["status"] == "DRAFT"
        after = validate_success(api.get_product_specification(
            product["id"], test_users.REGULATORY_AFFAIRS), 200)
        assert after["version"] == 2

    def test_a_stale_product_specification_version_is_refused(self, api):
        """PRD §2.5: "If that value does not equal the product specification's
        current `version`, the request is rejected with
        `ERR_STALE_PRODUCT_SPEC_VERSION` and HTTP 412."
        PRD §2.5: "A design history file legitimately accumulates many records, so
        nothing in the state machine stops the write; the stale version captures the
        case where another record has just been filed or approved and the writer's
        view of the traceability graph, and of the parent's `design_trace_complete`
        flag, is therefore obsolete."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        product = fixtures.create_product_specification(api)
        first = fixtures.file_design_record(api, product["id"], "DESIGN_INPUT")

        response = api.create_design_control_record(
            factories.design_control_record_payload(
                product["id"], "DESIGN_OUTPUT", 1,
                traces_to_record_id=first["id"]),
            test_users.REGULATORY_AFFAIRS)
        validate_error(response,
                       ApiErrorId.ERR_STALE_PRODUCT_SPEC_VERSION.value, 412)
        assert HTTP_STATUS_CODES[
            ApiErrorId.ERR_STALE_PRODUCT_SPEC_VERSION.value] == 412

        after = validate_success(api.get_product_specification(
            product["id"], test_users.REGULATORY_AFFAIRS), 200)
        assert after["version"] == 2
        rows, meta = validate_paginated(api.list_design_control_records(
            test_users.REGULATORY_AFFAIRS,
            params={"product_specification_id": product["id"]}))
        assert len(rows) == 1
        assertions.assert_paginated_meta(meta, expected_total=1)

    def test_the_refreshed_product_specification_version_is_accepted(self, api):
        """PRD §2.5: "A `POST /design-control-records` request must carry
        `expected_product_specification_version` as a non-optional input field,
        holding the `version` of the parent product specification as the client last
        read it."
        PRD §3.2: "From those links the server computes `trace_depth`: 1 for a
        `DESIGN_INPUT`, and otherwise one more than the `trace_depth` of the record
        named by `traces_to_record_id`."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        product = fixtures.create_product_specification(api)
        first = fixtures.file_design_record(api, product["id"], "DESIGN_INPUT")
        refreshed = fixtures.product_specification_version(api, product["id"])
        assert refreshed == 2

        second = validate_success(api.create_design_control_record(
            factories.design_control_record_payload(
                product["id"], "DESIGN_OUTPUT", refreshed,
                traces_to_record_id=first["id"]),
            test_users.REGULATORY_AFFAIRS), 201)

        assert second["trace_depth"] == 2
        assert second["traces_to_record_id"] == first["id"]
        after = validate_success(api.get_product_specification(
            product["id"], test_users.REGULATORY_AFFAIRS), 200)
        assert after["version"] == 3
        rows, meta = validate_paginated(api.list_design_control_records(
            test_users.REGULATORY_AFFAIRS,
            params={"product_specification_id": product["id"]}))
        assert len(rows) == 2
        assertions.assert_paginated_meta(meta, expected_total=2)

    def test_dispensing_raises_the_finished_lot_version(self, api):
        """PRD §2.5: "A `POST /reagent-lots/{id}/components` request must carry
        `expected_reagent_lot_version` as a non-optional input field, holding the
        `version` of the finished lot as the client last read it."
        PRD §3.3: "A successful dispensing call moves quantity across the raw
        material ledger: the raw lot's `consumed_quantity_units` increases by
        `quantity_used` and its `available_quantity_units` decreases by the same
        amount, keeping `received_quantity_units` equal to the sum of the two."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        setup = fixtures.manufacturing_setup(api, material_types=("ANTIBODY",),
                                             cleared=False)
        material_lot = setup["materials"][0]["lot"]
        received = float(material_lot["received_quantity_units"])
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])
        assert lot["version"] == 1

        component = validate_success(api.add_reagent_lot_component(
            lot["id"],
            factories.lot_component_payload(material_lot["id"], "ANTIBODY", 1,
                                            quantity_used=120.00),
            test_users.PRODUCTION_OPERATOR), 201)

        assert float(component["quantity_used"]) == 120.00
        assert component["status"] == "CONSUMED"
        after_lot = validate_success(api.get_reagent_lot(
            lot["id"], test_users.PRODUCTION_OPERATOR), 200)
        assert after_lot["version"] == 2
        after_material = validate_success(api.get_material_lot(
            material_lot["id"], test_users.PRODUCTION_OPERATOR), 200)
        # 120.00 consumed of the received quantity leaves received - 120.00.
        assert float(after_material["consumed_quantity_units"]) == 120.00
        assert float(after_material["available_quantity_units"]) == received - 120.00

    def test_a_stale_finished_lot_version_is_refused(self, api):
        """PRD §2.5: "If that value does not equal the finished lot's current
        `version`, the request is rejected with `ERR_STALE_REAGENT_LOT_VERSION` and
        HTTP 412."
        PRD §2.5: "A finished lot legitimately accepts many components, so no state
        precondition stands in the way of a second dispensing call; the stale
        version is the only signal available that the writer's picture of the bill
        of materials — and of the raw material quantities already drawn — is out of
        date."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        setup = fixtures.manufacturing_setup(
            api, material_types=("ANTIBODY", "ENZYME"), cleared=False)
        second_material = setup["materials"][1]["lot"]
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])
        fixtures.dispense_component(api, lot["id"],
                                    setup["materials"][0]["lot"]["id"],
                                    "ANTIBODY", quantity_used=120.00,
                                    expected_reagent_lot_version=1)

        response = api.add_reagent_lot_component(
            lot["id"],
            factories.lot_component_payload(second_material["id"], "ENZYME", 1,
                                            quantity_used=50.00),
            test_users.PRODUCTION_OPERATOR)
        validate_error(response,
                       ApiErrorId.ERR_STALE_REAGENT_LOT_VERSION.value, 412)
        assert HTTP_STATUS_CODES[
            ApiErrorId.ERR_STALE_REAGENT_LOT_VERSION.value] == 412

        after_lot = validate_success(api.get_reagent_lot(
            lot["id"], test_users.PRODUCTION_OPERATOR), 200)
        assert after_lot["version"] == 2
        untouched = validate_success(api.get_material_lot(
            second_material["id"], test_users.PRODUCTION_OPERATOR), 200)
        assert float(untouched["consumed_quantity_units"]) == 0.00
        assert float(untouched["available_quantity_units"]) == \
            float(untouched["received_quantity_units"])
        rows, meta = validate_paginated(api.list_reagent_lot_components(
            lot["id"], test_users.PRODUCTION_OPERATOR))
        assert len(rows) == 1
        assertions.assert_paginated_meta(meta, expected_total=1)

    def test_the_refreshed_finished_lot_version_is_accepted(self, api):
        """PRD §2.5: "A `POST /reagent-lots/{id}/components` request must carry
        `expected_reagent_lot_version` as a non-optional input field, holding the
        `version` of the finished lot as the client last read it."
        PRD §3.3: "It also recomputes the finished lot's `bridging_required` flag
        (§3.7), increases the finished lot's `version` by 1, and increases the drawn
        raw material lot's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/both_declared_occ_rules_reject_a_stale_parent_version_and_accept_the_refreshed_one
        """
        setup = fixtures.manufacturing_setup(
            api, material_types=("ANTIBODY", "ENZYME"), cleared=False)
        second_material = setup["materials"][1]["lot"]
        received = float(second_material["received_quantity_units"])
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])
        fixtures.dispense_component(api, lot["id"],
                                    setup["materials"][0]["lot"]["id"],
                                    "ANTIBODY", quantity_used=120.00,
                                    expected_reagent_lot_version=1)
        refreshed = fixtures.reagent_lot_version(api, lot["id"])
        assert refreshed == 2

        component = validate_success(api.add_reagent_lot_component(
            lot["id"],
            factories.lot_component_payload(second_material["id"], "ENZYME",
                                            refreshed, quantity_used=50.00),
            test_users.PRODUCTION_OPERATOR), 201)

        assert component["component_role"] == "ENZYME"
        after_lot = validate_success(api.get_reagent_lot(
            lot["id"], test_users.PRODUCTION_OPERATOR), 200)
        assert after_lot["version"] == 3
        after_material = validate_success(api.get_material_lot(
            second_material["id"], test_users.PRODUCTION_OPERATOR), 200)
        # 50.00 drawn from the second material lot only.
        assert float(after_material["consumed_quantity_units"]) == 50.00
        assert float(after_material["available_quantity_units"]) == received - 50.00
        rows, meta = validate_paginated(api.list_reagent_lot_components(
            lot["id"], test_users.PRODUCTION_OPERATOR))
        assert len(rows) == 2
        assertions.assert_paginated_meta(meta, expected_total=2)


class TestCumulativeColdChainLimit:
    """Cumulative excursion minutes are compared strictly against 240, so exactly
    240.00 is still acceptable and 241.00 rejects."""

    def test_a_shipped_reservation_starts_intact(self, api):
        """PRD §3.9: "Each event re-derives the cumulative picture:
        `cumulative_excursion_minutes` becomes the sum of `excursion_minutes` over
        every cold-chain event ever recorded against this reservation, and
        `max_excursion_temp_c` becomes the largest `max_temp_c` across those events,
        staying null while no event exists."
        PRD §3.9: "Otherwise it is `EXCURSION_ACCEPTABLE` when
        `cumulative_excursion_minutes` is greater than 0, and `INTACT` when it is
        0."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cold_chain_minutes_are_strictly_compared_at_the_two_hundred_forty_minute_limit
        """
        bundle = fixtures.shipped_allocation(api)
        allocation = bundle["allocation"]

        assert allocation["status"] == "SHIPPED"
        assert allocation["cold_chain_status"] == "INTACT"
        assert float(allocation["cumulative_excursion_minutes"]) == 0.00
        assertions.assert_absent_or_none(allocation, "max_excursion_temp_c")
        assert allocation["quarantine_reason"] is None

    def test_a_first_excursion_below_the_limit_is_acceptable(self, api):
        """PRD §3.9: "Otherwise it is `EXCURSION_ACCEPTABLE` when
        `cumulative_excursion_minutes` is greater than 0, and `INTACT` when it is
        0."
        PRD §3.9: "The reservation's `version` increases by 1 on every event."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cold_chain_minutes_are_strictly_compared_at_the_two_hundred_forty_minute_limit
        """
        bundle = fixtures.shipped_allocation(api)
        allocation = bundle["allocation"]

        after = fixtures.record_cold_chain_event(api, allocation["id"],
                                                 100.00, 12.0)

        # A single event of 100.00 minutes: 100.00 <= 240 and 12.0 <= 15.0.
        assert float(after["cumulative_excursion_minutes"]) == 100.00
        assert float(after["max_excursion_temp_c"]) == 12.0
        assert after["cold_chain_status"] == "EXCURSION_ACCEPTABLE"
        assert after["status"] == "SHIPPED"
        assert after["version"] == allocation["version"] + 1

    def test_exactly_two_hundred_forty_cumulative_minutes_is_accepted(self, api):
        """PRD §3.9: "It is `EXCURSION_REJECTED` when `max_excursion_temp_c` is
        strictly greater than 15.0 degrees Celsius **or**
        `cumulative_excursion_minutes` is strictly greater than 240 minutes — four
        hours of accumulated excursion is still acceptable, and so is a peak of
        exactly 15.0 degrees."
        PRD §3.9: "`cumulative_excursion_minutes` is carried at 2 decimal places and
        `max_excursion_temp_c` at 1 decimal place, and both comparisons against
        their limits are strictly greater-than."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cold_chain_minutes_are_strictly_compared_at_the_two_hundred_forty_minute_limit
        """
        bundle = fixtures.shipped_allocation(api)
        allocation_id = bundle["allocation"]["id"]
        shipped_units = int(bundle["allocation"]["allocated_units"])

        fixtures.record_cold_chain_event(api, allocation_id, 100.00, 12.0)
        after = fixtures.record_cold_chain_event(api, allocation_id, 140.00, 15.0)

        # 100.00 + 140.00 = 240.00, which is not strictly greater than 240, and
        # the peak of exactly 15.0 is not strictly greater than 15.0 either.
        assert float(after["cumulative_excursion_minutes"]) == 240.00
        assert float(after["max_excursion_temp_c"]) == 15.0
        assert after["cold_chain_status"] == "EXCURSION_ACCEPTABLE"
        assert after["status"] == "SHIPPED"
        assert after["quarantine_reason"] is None

        lot = validate_success(api.get_reagent_lot(
            bundle["lot"]["id"], test_users.DISTRIBUTION_PLANNER), 200)
        assert int(lot["shipped_units"]) == shipped_units
        assert int(lot["quarantined_units"]) == 0

    def test_one_minute_beyond_the_limit_rejects_and_quarantines(self, api):
        """PRD §3.9: "When the verdict becomes `EXCURSION_REJECTED`, the reservation
        moves from `SHIPPED` to the terminal `QUARANTINED` state with its
        `quarantine_reason` set to indicate a cold-chain excursion, the lot's
        `shipped_units` decreases and its `quarantined_units` increases by that
        reservation's `allocated_units`, and the parent order recomputes its
        `allocated_units` and `shortfall_units`."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cold_chain_minutes_are_strictly_compared_at_the_two_hundred_forty_minute_limit
        """
        bundle = fixtures.shipped_allocation(api)
        allocation_id = bundle["allocation"]["id"]
        reserved_units = int(bundle["allocation"]["allocated_units"])

        fixtures.record_cold_chain_event(api, allocation_id, 100.00, 12.0)
        fixtures.record_cold_chain_event(api, allocation_id, 140.00, 15.0)
        after = fixtures.record_cold_chain_event(api, allocation_id, 1.00, 10.0)

        # 240.00 + 1.00 = 241.00, strictly greater than 240.
        assert float(after["cumulative_excursion_minutes"]) == 241.00
        assert float(after["max_excursion_temp_c"]) == 15.0
        assert after["cold_chain_status"] == "EXCURSION_REJECTED"
        assert after["status"] == "QUARANTINED"
        assert after["quarantine_reason"] is not None

        lot = validate_success(api.get_reagent_lot(
            bundle["lot"]["id"], test_users.DISTRIBUTION_PLANNER), 200)
        assert int(lot["shipped_units"]) == 0
        assert int(lot["quarantined_units"]) == reserved_units
        assert int(lot["filled_units"]) == (int(lot["available_units"])
                                            + int(lot["allocated_units"])
                                            + int(lot["shipped_units"])
                                            + int(lot["quarantined_units"]))

    def test_confirmed_delivery_under_the_limit_delivers_the_reservation(self, api):
        """PRD §3.9: "When `delivery_confirmed` is supplied as true and the
        cumulative verdict is either `INTACT` or `EXCURSION_ACCEPTABLE`, the
        reservation moves from `SHIPPED` to the terminal `DELIVERED` state; there is
        no separate delivery operation, so confirming delivery on a cold-chain event
        is the only route into `DELIVERED`."
        PRD §3.9: "Once every reservation of an order carries `status` `DELIVERED`,
        that order advances from `SHIPPED` to the terminal `CLOSED` state as a
        system cascade."

        Design: Corner/cross_cutting_complexity_layers/cumulative_cold_chain_minutes_are_strictly_compared_at_the_two_hundred_forty_minute_limit
        """
        bundle = fixtures.shipped_allocation(api)
        allocation_id = bundle["allocation"]["id"]

        after = fixtures.record_cold_chain_event(api, allocation_id, 5.00, 8.0,
                                                 delivery_confirmed=True)

        # 5.00 minutes is above 0 but far below the 240-minute limit.
        assert float(after["cumulative_excursion_minutes"]) == 5.00
        assert after["cold_chain_status"] == "EXCURSION_ACCEPTABLE"
        assert after["status"] == "DELIVERED"
        assert after["quarantine_reason"] is None

        order = validate_success(api.get_distribution_order(
            bundle["order"]["id"], test_users.DISTRIBUTION_PLANNER), 200)
        assert order["status"] == "CLOSED"


class TestImmediateVisibility:
    """Every derived field and every ledger move is already visible in the response
    of the call that caused it."""

    def test_the_measurement_response_already_carries_its_own_outcome(self, api):
        """PRD §2.10: "Cascades are **immediate and synchronous**: by the time a
        response is returned, every downstream row the operation touches has already
        been updated, every recomputed counter already reflects the new reality, and
        every touched row has had its `updated_at` refreshed and its `version`
        increased by 1."
        PRD §3.1: "The server stamps `performed_by_user_id` from the acting
        operator's identity and `performed_at` from the logical clock, and it
        computes `outcome` itself — clients never supply it."

        Design: Corner/consistency_model/every_derived_field_and_cross_entity_ledger_move_is_visible_in_the_same_response
        """
        spec = fixtures.create_material_specification(
            api, required_test_codes=["POTENCY"])
        lot = fixtures.create_material_lot(api, spec["id"])

        measurement = validate_success(api.create_test_result(
            factories.material_test_result_payload(lot["id"], "POTENCY", 100.00),
            test_users.QC_ANALYST), 201)

        # 100.00 sits inside the inclusive 90.0 to 110.0 potency window.
        assert measurement["outcome"] == "PASS"
        assert measurement["performed_by_user_id"] == test_users.QC_ANALYST_USER_ID
        assert measurement["performed_at"] is not None
        assertions.assert_event_record_fields(measurement)

        reread = validate_success(api.get_test_result(
            measurement["id"], test_users.QC_ANALYST), 200)
        assert reread["outcome"] == "PASS"

    def test_the_first_measurement_moves_the_lot_without_a_second_call(self, api):
        """PRD §3.1: "The first acceptance measurement on a lot moves it from
        `RECEIVED` to `UNDER_TEST`."
        PRD §2.10: "A caller never has to poll for a cascade to land."

        Design: Corner/consistency_model/every_derived_field_and_cross_entity_ledger_move_is_visible_in_the_same_response
        """
        spec = fixtures.create_material_specification(
            api, required_test_codes=["POTENCY"])
        lot = fixtures.create_material_lot(api, spec["id"])
        assert lot["qualification_status"] == "RECEIVED"
        assert lot["version"] == 1

        fixtures.record_material_measurement(api, lot["id"], "POTENCY", 100.00)

        after = validate_success(api.get_material_lot(
            lot["id"], test_users.QC_ANALYST), 200)
        assert after["qualification_status"] == "UNDER_TEST"
        assert after["version"] == 2

    def test_the_qualify_response_already_carries_the_recomputed_score(self, api):
        """PRD §3.1: "The quotient is multiplied by 100 and the result is rounded
        half-up to two decimal places to give `acceptance_score`, which stays null
        while no required code has any measurement."
        PRD §3.1: "On success the lot moves `UNDER_TEST` to `QUALIFIED`,
        `dispositioned_by_user_id` and `dispositioned_at` are recorded,
        `available_quantity_units` remains `received_quantity_units` minus
        `consumed_quantity_units`, and the lot's `version` increases by 1."

        Design: Corner/consistency_model/every_derived_field_and_cross_entity_ledger_move_is_visible_in_the_same_response
        """
        spec = fixtures.create_material_specification(
            api, required_test_codes=["POTENCY", "PURITY"],
            acceptance_mode="WEIGHTED_SCORE")
        lot = fixtures.create_material_lot(api, spec["id"])
        fixtures.record_material_measurement(api, lot["id"], "POTENCY", 100.00)
        fixtures.record_material_measurement(api, lot["id"], "PURITY", 99.00)

        qualified = validate_success(api.disposition_material_lot(
            lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
            test_users.QA_RELEASER), 200)

        # Potency inside its window scores 1, purity scores 99.00/100 = 0.99:
        # (0.45 * 1 + 0.30 * 0.99) / 0.75 * 100 = 99.60.
        assert float(qualified["acceptance_score"]) == 99.60
        assert qualified["qualification_status"] == "QUALIFIED"
        assert qualified["dispositioned_by_user_id"] == \
            test_users.QA_RELEASER_USER_ID
        assert qualified["dispositioned_at"] is not None

    def test_the_immediate_reread_of_the_qualified_lot_agrees(self, api):
        """PRD §2.10: "Cascades are **immediate and synchronous**: by the time a
        response is returned, every downstream row the operation touches has already
        been updated, every recomputed counter already reflects the new reality, and
        every touched row has had its `updated_at` refreshed and its `version`
        increased by 1."
        PRD §3.1: "Each record also increases the lot's `version` by 1 and, when the
        specification's `acceptance_mode` is `WEIGHTED_SCORE`, recomputes
        `acceptance_score`."

        Design: Corner/consistency_model/every_derived_field_and_cross_entity_ledger_move_is_visible_in_the_same_response
        """
        spec = fixtures.create_material_specification(
            api, required_test_codes=["POTENCY", "PURITY"],
            acceptance_mode="WEIGHTED_SCORE")
        lot = fixtures.create_material_lot(api, spec["id"])
        fixtures.record_material_measurement(api, lot["id"], "POTENCY", 100.00)
        fixtures.record_material_measurement(api, lot["id"], "PURITY", 99.00)
        qualified = validate_success(api.disposition_material_lot(
            lot["id"], factories.material_lot_disposition_payload("QUALIFY"),
            test_users.QA_RELEASER), 200)

        reread = validate_success(api.get_material_lot(
            lot["id"], test_users.QA_RELEASER), 200)

        assert reread["qualification_status"] == "QUALIFIED"
        assert float(reread["acceptance_score"]) == 99.60
        assert reread["version"] == qualified["version"]
        assertions.assert_same_instant(reread["dispositioned_at"],
                                       qualified["dispositioned_at"],
                                       "material_lot.dispositioned_at")
        # Two measurements and one disposition on a lot created at version 1.
        assert reread["version"] == 4

    def test_dispensing_shows_the_raw_ledger_move_in_the_next_read(self, api):
        """PRD §2.8: "The invariant is that `received_quantity_units` always equals
        `available_quantity_units` plus `consumed_quantity_units`."
        PRD §3.3: "A successful dispensing call moves quantity across the raw
        material ledger: the raw lot's `consumed_quantity_units` increases by
        `quantity_used` and its `available_quantity_units` decreases by the same
        amount, keeping `received_quantity_units` equal to the sum of the two."

        Design: Corner/consistency_model/every_derived_field_and_cross_entity_ledger_move_is_visible_in_the_same_response
        """
        setup = fixtures.manufacturing_setup(
            api, material_types=("ANTIBODY",), cleared=False,
            material_lot_overrides={"received_quantity_units": 500.00})
        material_lot_id = setup["materials"][0]["lot"]["id"]
        lot = fixtures.create_reagent_lot(api, setup["product"]["id"])

        fixtures.dispense_component(api, lot["id"], material_lot_id, "ANTIBODY",
                                    quantity_used=120.00)

        after = validate_success(api.get_material_lot(
            material_lot_id, test_users.PRODUCTION_OPERATOR), 200)
        # 500.00 received, 120.00 drawn, so 380.00 remains available.
        assert float(after["consumed_quantity_units"]) == 120.00
        assert float(after["available_quantity_units"]) == 380.00
        assert float(after["received_quantity_units"]) == 500.00

        rows, meta = validate_paginated(api.list_material_lot_components(
            material_lot_id, test_users.PRODUCTION_OPERATOR,
            params={"status": "CONSUMED"}))
        assert len(rows) == 1
        assert float(rows[0]["quantity_used"]) == 120.00
        assertions.assert_paginated_meta(meta, expected_total=1)

    def test_the_triage_response_already_carries_the_derived_deadline(self, api):
        """PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."
        PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it is
        null whenever `reportable` is false."

        Design: Corner/consistency_model/every_derived_field_and_cross_entity_ledger_move_is_visible_in_the_same_response
        """
        bundle = fixtures.filled_reagent_lot(api)
        fixtures.set_clock(api, "2026-08-22T00:00:00.000Z")
        complaint = fixtures.create_complaint(api, bundle["lot"]["id"])
        assertions.assert_same_instant(complaint["received_at"],
                                       "2026-08-22T00:00:00.000Z",
                                       "complaint.received_at")

        triaged = validate_success(api.triage_complaint(
            complaint["id"], factories.triage_payload("HIGH", True),
            test_users.REGULATORY_AFFAIRS), 200)

        assert triaged["reportable"] is True
        # 2026-08-22 advanced by 30 days is 2026-09-21.
        assertions.assert_same_instant(triaged["report_due_at"],
                                       "2026-09-21T00:00:00.000Z",
                                       "complaint.report_due_at")
        reread = validate_success(api.get_complaint(
            complaint["id"], test_users.REGULATORY_AFFAIRS), 200)
        assert reread["reportable"] is True
        assertions.assert_same_instant(reread["report_due_at"],
                                       "2026-09-21T00:00:00.000Z",
                                       "complaint.report_due_at")
