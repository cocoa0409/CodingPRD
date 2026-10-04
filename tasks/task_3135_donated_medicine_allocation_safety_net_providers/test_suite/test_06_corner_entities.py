"""Corner tests: entity creation, retrieval, defaults, computed fields, and
request-shape validation."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    QA_PHARMACIST_HEADERS,
    ApiErrorId as E,
    assert_lot_quantity_conservation,
    assert_manufacturer_donor,
    assert_product_lot,
    assert_recipient_site,
)
from test_helpers import fixtures
from test_helpers.factories import create_allocation_request_payload, create_lot_payload
from test_helpers.test_users import make_site_coordinator_headers


class TestDonorCreation:
    def test_create_returns_declared_fields_and_active_status(self, api):
        """PRD §3.1: "A `PlatformAdmin` registers a `ManufacturerDonor` by
        supplying the organization's `legal_name`, the two-letter ISO
        `country_code` of the donating entity, a `tax_id` used on valuation and
        donation reports, and — when the donor intends to contribute controlled
        substances — a `dea_registration_no`. New donors enter with `status` set
        to `ACTIVE` and `version` at 1."

        Design: Corner/entities/manufacturer_donor_create_returns_all_declared_fields_and_active_status
        """
        fixtures.set_clock(api)
        resp = api.create_donor(
            {
                "legal_name": "Meridian Pharma",
                "country_code": "US",
                "tax_id": "12-3456789",
                "dea_registration_no": "BM1234567",
            },
            PLATFORM_ADMIN_HEADERS,
        )
        donor = validate_success(resp, 201)
        assert_manufacturer_donor(donor)
        assert donor["legal_name"] == "Meridian Pharma"
        assert donor["status"] == "ACTIVE"
        assert donor["version"] == 1
        assert resp.json()["meta"].get("api_request_id")
        assert resp.json()["meta"].get("api_request_timestamp")


class TestProductLotRetrieval:
    def test_get_returns_stored_record_with_computed_fields(self, api):
        """PRD §3.1: "Every lot enters in `QUARANTINED` posture:
        `quantity_quarantined` is initialized to `quantity_received`,
        `quantity_available` remains zero, and `intake_recorded_at` is stamped
        from the logical clock."
        PRD §3.1: "The booleans `requires_cold_chain` and `is_controlled` are
        derived from `product_class` — the former true exactly when the class is
        `COLD_CHAIN`, the latter true exactly when the class is `CONTROLLED`."

        Design: Corner/entities/product_lot_get_returns_stored_record_with_computed_fields
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_lot(
            api,
            donor["id"],
            ndc_code="N1",
            product_name="Insulin Glargine",
            product_class="COLD_CHAIN",
            dosage_form="VIAL",
            unit_of_measure="VIAL",
            quantity_received=200,
            expiration_date="2027-03-31T00:00:00Z",
            storage_temp_min_c=2,
            storage_temp_max_c=8,
            restricted_use_conditions=["hospital-only"],
            unit_acquisition_value_usd=12.50,
            unit_wholesale_value_usd=18.00,
        )
        fetched = validate_success(api.get_lot(lot["id"], QA_PHARMACIST_HEADERS))
        assert_product_lot(fetched)
        assert fetched["lot_posture"] == "QUARANTINED"
        assert fetched["quantity_received"] == 200
        assert fetched["quantity_quarantined"] == 200
        assert fetched["quantity_available"] == 0
        assert fetched["requires_cold_chain"] is True
        assert fetched["is_controlled"] is False
        assert fetched["restricted_use_conditions"] == ["hospital-only"]


class TestSitesListPaginationAndFilters:
    def _setup_three_sites(self, api):
        fixtures.set_clock(api)
        s1 = fixtures.create_site(api, organization_name="S1", site_type="FREE_CLINIC",
                                  country_code="US")
        s2 = fixtures.setup_qualified_site(
            api, organization_name="S2", site_type="FQHC", country_code="US",
            cold_storage_capacity_l=200, monthly_patient_volume=500,
            underserved_index=0.7,
        )
        s3 = fixtures.create_site(api, organization_name="S3",
                                  site_type="RURAL_HEALTH_CENTER", country_code="HT",
                                  cold_storage_capacity_l=0, monthly_patient_volume=50,
                                  underserved_index=0.9)
        return s1, s2, s3

    def test_limit_two_returns_first_page(self, api):
        """PRD §2.3: "The `limit` parameter sets the page size: it defaults to
        10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets
        how many records to skip and defaults to 0. The `meta` object of a
        paginated list response carries `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/sites_list_paginates_and_filters
        """
        self._setup_three_sites(api)
        resp = api.list_sites(COMPLIANCE_OFFICER_HEADERS, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        resp2 = api.list_sites(COMPLIANCE_OFFICER_HEADERS, params={"limit": 2, "offset": 2})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_filter_by_qualification_status_and_country(self, api):
        """PRD §3.3: "New sites enter with `qualification_status` set to
        `PENDING_REVIEW`."
        PRD §2.3: "The `limit` parameter sets the page size: it defaults to 10,
        with a minimum of 1 and a maximum of 100."

        Design: Corner/entities/sites_list_paginates_and_filters
        """
        _, s2, s3 = self._setup_three_sites(api)
        pending, meta_p = validate_paginated(
            api.list_sites(COMPLIANCE_OFFICER_HEADERS, params={"qualification_status": "PENDING_REVIEW"})
        )
        assert len(pending) == 2
        assert all(s["qualification_status"] == "PENDING_REVIEW" for s in pending)
        qualified, _ = validate_paginated(
            api.list_sites(COMPLIANCE_OFFICER_HEADERS, params={"qualification_status": "QUALIFIED"})
        )
        assert [s["id"] for s in qualified] == [s2["id"]]
        ht, _ = validate_paginated(
            api.list_sites(COMPLIANCE_OFFICER_HEADERS, params={"country_code": "HT"})
        )
        assert [s["id"] for s in ht] == [s3["id"]]


class TestLicenseNotFound:
    def test_unknown_license_id_returns_not_found(self, api):
        """PRD §2.10: "Where an operation references multiple resources — for
        example, a shipment scoped to a decision scoped to a request scoped to a
        site — the server validates identifiers in left-to-right order, returning
        `ERR_NOT_FOUND` (HTTP 404) for the first id that does not resolve."

        Design: Corner/entities/license_get_unknown_id_returns_not_found
        """
        fixtures.set_clock(api)
        resp = api.get_license(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS)
        validate_error(resp, E.ERR_NOT_FOUND, 404)


class TestAllocationRequestRequiredFields:
    def test_missing_quantity_requested_returns_invalid_request(self, api):
        """PRD §3.4: "A `SiteCoordinator` submits an `AllocationRequest` naming
        the requesting `site_id`, the desired product's `ndc_code`, the
        `quantity_requested` (a positive integer), a free-text
        `justification_text`, and — when the request responds to a declared
        emergency — an `emergency_event_id`."
        PRD §2.7: "Finally come referential checks: (22) malformed-request
        rejection with `ERR_INVALID_REQUEST`, (23) emergency-event reference
        validity with `ERR_EMERGENCY_NOT_ACTIVE`, (24) temperature-band
        compatibility with `ERR_INCOMPATIBLE_TEMPERATURE_BANDS`, (25) cold-chain
        packing with `ERR_COLD_CHAIN_PACK_REQUIRED`, and (26) customs clearance
        at dispatch with `ERR_CUSTOMS_NOT_CLEARED`."

        Design: Corner/entities/allocation_request_create_missing_required_field_returns_invalid_request
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        payload = create_allocation_request_payload(site["id"])
        del payload["quantity_requested"]
        resp = api.create_allocation_request(payload, make_site_coordinator_headers(site["id"]))
        validate_error(resp, E.ERR_INVALID_REQUEST, 400)


class TestSiteDefaults:
    def test_new_site_active_license_count_zero_and_qualified_at_null(self, api):
        """PRD §3.3: "New sites enter with `qualification_status` set to
        `PENDING_REVIEW`."
        PRD §3.3: "Each of these transitions recomputes the site's
        `active_license_count` — the count of the site's licenses in `VERIFIED`
        status whose `expires_on` is after the current logical clock."

        Design: Corner/entities/recipient_site_active_license_count_defaults_to_zero
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        assert_recipient_site(site)
        assert site["active_license_count"] == 0
        assert site.get("qualified_at") is None
        assert site["qualification_status"] == "PENDING_REVIEW"


class TestLotComputedQuantitiesAfterAllocation:
    def test_finalize_moves_available_to_committed(self, api):
        """PRD §2.8: "Every `ProductLot` maintains five quantity counters:
        `quantity_received` (fixed at intake), `quantity_quarantined`,
        `quantity_committed`, `quantity_shipped`, and `quantity_expired`. The
        system derives `quantity_available` as the received count minus the
        quarantined, committed, shipped, and expired counts."
        PRD §3.5: "Every line moves to `RESERVED`, its quantity is added to its
        lot's `quantity_committed`, and each line's `reservation_expires_at` is
        set from `decided_at` plus a TTL: seventy-two hours for ordinary
        requests, shortened to twenty-four hours when the request's
        `emergency_event_id` references an `EmergencyEvent` in `ACTIVE` status."

        Design: Corner/entities/lot_quantity_available_computed_after_release_and_partial_allocation
        """
        fixtures.set_clock(api)
        world = fixtures.setup_finalized_decision(api, quantity_requested=30, lot_quantity=100)
        lot = fixtures.get_lot(api, world["lot"]["id"])
        assert lot["quantity_committed"] == 30
        assert lot["quantity_available"] == 70
        assert lot["quantity_shipped"] == 0
        assert lot["quantity_expired"] == 0
        assert_lot_quantity_conservation(lot)


class TestServerGeneratedCommonFields:
    def test_id_and_version_are_server_controlled(self, api):
        """PRD §2.5: "`id` — a server-minted UUID with no type prefix."
        PRD §2.5: "`version` — an integer starting at 1 that increments by 1 on
        every mutation. This is the field consulted by the optimistic concurrency
        checks described in §2.6."

        Design: Corner/entities/common_fields_server_generated_id_and_timestamps_ignore_client_input
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(api)
        assert is_valid_uuid(site["id"])
        assert site["version"] == 1
        assert is_iso8601_timestamp(site["created_at"])
        assert is_iso8601_timestamp(site["updated_at"])


class TestLotEnumValidation:
    def test_invalid_product_class_rejected(self, api):
        """PRD §3.1: "Lot intake is performed by a `PlatformAdmin` or
        `QAPharmacist` via a payload naming the `donor_id`, the product's
        `ndc_code` and `product_name`, its `product_class` (one of `STANDARD`,
        `COLD_CHAIN`, `CONTROLLED`, `RESTRICTED_USE`), its `dosage_form` (one of
        `TABLET`, `CAPSULE`, `VIAL`, `AMPOULE`, `SYRUP`, `CREAM`, `DEVICE`), the
        `unit_of_measure` (`UNIT`, `VIAL`, `PACK`, or `BOX`), the
        `quantity_received`, the manufacturer-stamped `expiration_date`, the
        storage band `storage_temp_min_c` and `storage_temp_max_c` in Celsius,
        any `restricted_use_conditions` as a free-form list (for example
        hospital-only or not-for-retail), and the two per-unit valuation
        references `unit_acquisition_value_usd` and `unit_wholesale_value_usd`."
        PRD §2.7: "Finally come referential checks: (22) malformed-request
        rejection with `ERR_INVALID_REQUEST`, (23) emergency-event reference
        validity with `ERR_EMERGENCY_NOT_ACTIVE`, (24) temperature-band
        compatibility with `ERR_INCOMPATIBLE_TEMPERATURE_BANDS`, (25) cold-chain
        packing with `ERR_COLD_CHAIN_PACK_REQUIRED`, and (26) customs clearance
        at dispatch with `ERR_CUSTOMS_NOT_CLEARED`."

        Design: Corner/entities/product_lot_invalid_product_class_returns_invalid_request
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        payload = create_lot_payload(donor["id"], product_class="BIOHAZARD")
        resp = api.create_lot(payload, QA_PHARMACIST_HEADERS)
        validate_error(resp, E.ERR_INVALID_REQUEST, 400)


class TestLicenseForeignKey:
    def test_license_for_unknown_site_rejected(self, api):
        """PRD §2.7: "The order is: (1) authentication of the `X-User-ID` /
        `X-User-Role` headers, rejected with `ERR_UNAUTHENTICATED`; (2) role
        authorization, rejected with `ERR_FORBIDDEN_ROLE`; (3) existence of every
        resource id referenced in path or body, rejected with `ERR_NOT_FOUND`;
        (4) ownership on the ownership-guarded endpoints, rejected with
        `ERR_FORBIDDEN_OWNERSHIP`; (5) state-machine permissibility, rejected
        with `ERR_INVALID_STATE`; (6) the OCC check on decision finalization,
        rejected with `ERR_STALE_VERSION`; (7) the OCC check on site suspension,
        also rejected with `ERR_STALE_VERSION`."

        Design: Corner/entities/license_site_fk_reference_must_resolve
        """
        fixtures.set_clock(api)
        resp = api.create_license(
            {
                "site_id": NON_EXISTENT_UUID,
                "license_type": "PHARMACY",
                "issuing_authority": "TX BoP",
                "license_number": "L-X",
                "expires_on": "2027-12-31T00:00:00Z",
            },
            COMPLIANCE_OFFICER_HEADERS,
        )
        validate_error(resp, E.ERR_NOT_FOUND, 404)
