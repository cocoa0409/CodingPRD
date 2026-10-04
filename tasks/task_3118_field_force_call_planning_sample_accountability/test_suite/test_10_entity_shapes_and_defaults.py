"""Entity shapes: creation defaults, retrieval round-trips, listing
pagination, not-found behavior, required fields, server-owned defaults, and
computed fields.

Queue B — corner design section ``entities``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_field_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COMPLIANCE_HEADERS,
    make_district_manager_headers,
)


class TestRegionCreation:
    def test_region_create_returns_defaults_and_system_fields(self, api):
        """PRD section 3.1: "A Region is created with a unique business region_code
        (for example, NE-01) and a display name, and begins life with status ACTIVE."
        PRD section 2.4: "The id is a server-minted UUID string with no type prefix.
        created_at and updated_at are ISO 8601 UTC timestamps rendered with three
        fractional digits ... version is a system-managed integer beginning at 1."

        Design: Corner/entities/region_create_returns_201_with_defaults_and_system_fields
        """
        response = api.create_region(
            {"region_code": "PNW-01", "name": "Pacific Northwest"},
            headers=ADMIN_HEADERS,
        )
        data = validate_success(response, expected_status=201)
        assert data["status"] == "ACTIVE"
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestProductRetrieval:
    def test_product_get_round_trips_configuration(self, api):
        """PRD section 3.2: "A Product is registered with a unique ndc_code, a
        brand_name, a controlled boolean marking DEA-scheduled products, a
        per_visit_max_units regulatory cap per prescriber visit, an
        annual_max_units_per_prescriber cap across all representatives for the
        calendar year, and a storage band bounded by storage_temp_min_c and
        storage_temp_max_c."

        Design: Corner/entities/product_get_round_trips_storage_band_and_caps
        """
        product = fx.create_product(
            api,
            ndc_code="0006-0100",
            brand_name="Metabolex",
            controlled=True,
            per_visit_max_units=3,
            annual_max_units_per_prescriber=30,
            storage_temp_min_c=-20.0,
            storage_temp_max_c=-10.0,
        )
        data = get_success_data(
            api.get_product(
                product["id"], headers=make_field_rep_headers("any-rep-id")
            )
        )
        assert data["controlled"] is True
        assert data["per_visit_max_units"] == 3
        assert data["storage_temp_min_c"] == -20.0
        assert data["storage_temp_max_c"] == -10.0


class TestPrescriberListing:
    def _create_three_prescribers(self, api):
        for n in range(1, 4):
            fx.create_prescriber(
                api,
                npi_number="200000000{0}".format(n),
                full_name="Dr. {0}".format(n),
                state_license_number="S-{0}".format(n),
            )

    def test_prescriber_list_paginates(self, api):
        """PRD section 2.3: "List endpoints accept two query parameters, limit and
        offset. limit is the maximum number of items returned; it defaults to 10 when
        omitted, accepts a minimum of 1, and is capped at a maximum of 100. offset is
        the number of items skipped before the first returned item; it defaults to 0.
        ... The meta object on list responses carries the pagination fields limit,
        offset, total_count, and has_more."

        Design: Corner/entities/prescriber_list_paginates_with_total_count_and_has_more
        """
        self._create_three_prescribers(api)
        rows, meta = validate_paginated(
            api.list_prescribers(
                headers=COMPLIANCE_HEADERS, params={"limit": 2, "offset": 0}
            )
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        rows2, meta2 = validate_paginated(
            api.list_prescribers(
                headers=COMPLIANCE_HEADERS, params={"limit": 2, "offset": 2}
            )
        )
        assert len(rows2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_prescriber_list_filter_by_eligibility_status(self, api):
        """PRD section 4: "List endpoints support optional filtering query parameters
        as natural for their resource: status, region_id, territory_id,
        manager_rep_id, eligibility_status, product_id, lot_id, representative_id,
        counter_rep_id, prescriber_id, target_list_entry_id, call_plan_id,
        call_status, reconciliation_status, from_rep_id, to_rep_id, severity, and
        session_id are accepted on the list endpoints where those concepts apply."

        Design: Corner/entities/prescriber_list_paginates_with_total_count_and_has_more
        """
        self._create_three_prescribers(api)
        rows, meta = validate_paginated(
            api.list_prescribers(
                headers=COMPLIANCE_HEADERS,
                params={"eligibility_status": "PENDING_REVIEW"},
            )
        )
        assert len(rows) == 3
        assert meta["total_count"] == 3


class TestTerritoryNotFound:
    def test_unknown_territory_id_returns_not_found(self, api):
        """PRD section 2.6: "each path segment's resource must exist before the next
        is resolved, and the first missing identifier yields ERR_NOT_FOUND (HTTP
        404)."

        Design: Corner/entities/territory_get_unknown_id_returns_not_found
        """
        response = api.get_territory(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers=ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_NOT_FOUND)


class TestTerritoryRequiredFields:
    def test_missing_cycle_dates_rejected(self, api):
        """PRD section 2.6: "request-body well-formedness — required fields present,
        enum values within their declared sets, quantity at least 1 where a quantity
        is supplied, and documentation_note at least 20 characters where supplied —
        producing ERR_INVALID_REQUEST."

        Design: Corner/entities/territory_create_missing_budget_returns_invalid_request
        """
        region = fx.create_region(api)
        response = api.create_territory(
            region["id"],
            {"territory_code": "TX1", "name": "No Dates"},
            headers=ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


class TestPrescriberDefaultStatus:
    def test_fresh_prescriber_is_pending_review(self, api):
        """PRD section 3.2: "New prescribers begin with eligibility_status
        PENDING_REVIEW."

        Design: Corner/entities/prescriber_status_input_ignored_defaults_to_pending_review
        """
        response = api.create_prescriber(
            {
                "npi_number": "2100000001",
                "full_name": "Dr. Default",
                "state_license_number": "S-9",
                "specialty_code": "207Q00000X",
                "eligibility_status": "ELIGIBLE",
            },
            headers=ADMIN_HEADERS,
        )
        data = validate_success(response, expected_status=201)
        assert data["eligibility_status"] == "PENDING_REVIEW"


class TestTargetEntryComputedFields:
    def test_planned_calls_derived_from_tier(self, api):
        """PRD section 3.3: "The tier — one of A, B, or C — drives the planned call
        cadence: the system derives planned_calls_per_cycle as 12 for tier A, 6 for
        tier B, and 2 for tier C. ... its progress counters delivered_calls and
        delivered_sample_units both begin at zero."

        Design: Corner/entities/target_entry_planned_calls_input_ignored_tier_mapping_applies
        """
        region, territory, manager = fx.setup_manager_territory(api, budget=100)
        prescriber = fx.create_prescriber(api)
        product = fx.create_product(api)
        response = api.create_target_list_entry(
            territory["id"],
            {
                "prescriber_id": prescriber["id"],
                "product_id": product["id"],
                "tier": "B",
                "planned_sample_units": 30,
                "planned_calls_per_cycle": 99,
            },
            headers=make_district_manager_headers(manager["id"]),
        )
        data = validate_success(response, expected_status=201)
        assert data["planned_calls_per_cycle"] == 6
        assert data["delivered_calls"] == 0
        assert data["delivered_sample_units"] == 0


class TestExcursionSeverityComputed:
    def test_severity_computed_at_creation(self, api):
        """PRD section 3.7: "Severity is computed at creation." and "Otherwise
        severity is MAJOR if the distance is strictly greater than 2.0 degrees and at
        most 5.0 degrees, or if the distance is at most 2.0 degrees and the excursion
        lasted strictly more than 30 minutes."

        Design: Corner/entities/excursion_severity_input_ignored_computed_at_creation
        """
        region = fx.create_region(api)
        territory = fx.create_territory(api, region["id"])
        rep = fx.create_representative(api, territory["id"])
        product = fx.create_product(api)
        response = api.create_temperature_excursion(
            {
                "product_id": product["id"],
                "location_type": "VEHICLE",
                "observed_temp_c": 9.5,
                "excursion_minutes": 45,
                "severity": "MINOR",
            },
            headers=make_field_rep_headers(rep["id"]),
        )
        data = validate_success(response, expected_status=201)
        assert data["severity"] == "MAJOR"
        assert data["status"] == "REPORTED"


class TestEnumValidation:
    def test_unknown_tier_rejected(self, api):
        """PRD section 3.3: "The tier — one of A, B, or C" and PRD section 2.6:
        "enum values within their declared sets ... producing ERR_INVALID_REQUEST."

        Design: Corner/entities/enum_validation_rejects_unknown_tier_and_reason_code
        """
        region, territory, manager = fx.setup_manager_territory(api, budget=100)
        prescriber = fx.create_prescriber(api)
        product = fx.create_product(api)
        response = api.create_target_list_entry(
            territory["id"],
            {
                "prescriber_id": prescriber["id"],
                "product_id": product["id"],
                "tier": "D",
                "planned_sample_units": 10,
            },
            headers=make_district_manager_headers(manager["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
