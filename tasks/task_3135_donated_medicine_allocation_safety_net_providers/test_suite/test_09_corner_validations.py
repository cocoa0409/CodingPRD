"""Corner tests: validation rules — auth, roles, ownership, OCC, and the
business-safety guards."""

from prd_bench_local_runner.testing import (
    build_user_headers,
    get_success_data,
    validate_error,
)

from test_helpers import (
    ALLOCATION_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    EMERGENCY_MANAGER_HEADERS,
    LOGISTICS_COORDINATOR_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    QA_PHARMACIST_HEADERS,
    ApiErrorId as E,
)
from test_helpers import fixtures
from test_helpers.factories import create_lot_payload
from test_helpers.test_users import (
    make_compliance_officer_headers,
    make_site_coordinator_headers,
)


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must present two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying
        the role under which the user is acting. A request missing either header,
        or presenting a malformed value, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/missing_x_user_role_header_returns_unauthenticated
        """
        fixtures.set_clock(api)
        resp = api.list_sites(headers={})
        validate_error(resp, E.ERR_UNAUTHENTICATED, 401)


class TestRoleAuthorization:
    def test_site_coordinator_cannot_release_lot(self, api):
        """PRD §2.1: "Once authenticated, the server consults the role matrix; if
        the named role is not permitted to invoke the targeted endpoint, the
        request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authentication
        precedes authorization in evaluation order."
        PRD §4: "POST `/medicine-relief/lots/{lot_id}/release` — QAPharmacist."

        Design: Corner/validations/wrong_role_for_endpoint_returns_forbidden_role
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_lot(api, donor["id"], ndc_code="N1", quantity_received=10)
        resp = api.release_lot(
            lot["id"], make_site_coordinator_headers("00000000-0000-0000-0000-000000000001")
        )
        validate_error(resp, E.ERR_FORBIDDEN_ROLE, 403)
        lot_after = fixtures.get_lot(api, lot["id"])
        assert lot_after["lot_posture"] == "QUARANTINED"


class TestOwnership:
    def test_coordinator_cannot_cancel_another_sites_request(self, api):
        """PRD §3.4: "The requesting `SiteCoordinator` may cancel their own
        request from either `SUBMITTED` or `UNDER_REVIEW`, again only while no
        `FINALIZED` decision exists; the server compares the request's
        `requested_by_user_id` to `X-User-ID` and rejects a mismatch with
        `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

        Design: Corner/validations/site_coordinator_cannot_cancel_another_sites_request
        """
        fixtures.set_clock(api)
        site_a = fixtures.create_site(api, organization_name="SA")
        site_b = fixtures.create_site(api, organization_name="SB")
        request = fixtures.create_request(api, site_b["id"], quantity_requested=5, ndc_code="N1")
        resp = api.cancel_allocation_request(
            request["id"], make_site_coordinator_headers(site_a["id"])
        )
        validate_error(resp, E.ERR_FORBIDDEN_OWNERSHIP, 403)
        request_after = fixtures.get_request(api, request["id"])
        assert request_after["status"] == "SUBMITTED"


class TestDonorNotActive:
    def test_intake_from_suspended_donor_rejected(self, api):
        """PRD §3.1: "A donor may later be moved to `SUSPENDED` (which blocks new
        lot intake and quarantined-lot release with `ERR_DONOR_NOT_ACTIVE`, HTTP
        409) or permanently to `DEACTIVATED`."

        Design: Corner/validations/intake_lot_from_suspended_donor_returns_donor_not_active
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        get_success_data(api.suspend_donor(donor["id"], PLATFORM_ADMIN_HEADERS))
        resp = api.create_lot(
            create_lot_payload(donor["id"], ndc_code="N1", quantity_received=10),
            QA_PHARMACIST_HEADERS,
        )
        validate_error(resp, E.ERR_DONOR_NOT_ACTIVE, 409)


class TestControlledDonorUnregistered:
    def test_controlled_intake_without_donor_dea_rejected(self, api):
        """PRD §2.9: "**Controlled products** (a `ProductLot` whose
        `product_class` is `CONTROLLED`) may be accepted only from a
        `ManufacturerDonor` whose `dea_registration_no` is non-empty, and may be
        allocated only to a `RecipientSite` whose `has_dea_registration` is true;
        violations surface as `ERR_CONTROLLED_DONOR_UNREGISTERED` (at intake or
        release) or `ERR_CONTROLLED_SITE_NOT_AUTHORIZED` (at decision
        finalization), both HTTP 422."

        Design: Corner/validations/controlled_lot_intake_without_donor_dea_returns_controlled_donor_unregistered
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)  # no dea_registration_no
        resp = api.create_lot(
            create_lot_payload(
                donor["id"],
                ndc_code="N1",
                product_name="Morphine",
                product_class="CONTROLLED",
                dosage_form="VIAL",
                unit_of_measure="VIAL",
                quantity_received=10,
                unit_acquisition_value_usd=5.00,
                unit_wholesale_value_usd=8.00,
            ),
            QA_PHARMACIST_HEADERS,
        )
        validate_error(resp, E.ERR_CONTROLLED_DONOR_UNREGISTERED, 422)


class TestInternationalQualifyRequiresImportLicense:
    def test_international_site_without_import_license_rejected(self, api):
        """PRD §3.3: "Moving a `PENDING_REVIEW` site to `QUALIFIED` requires at
        least one active license (otherwise `ERR_NO_VERIFIED_LICENSE`, HTTP 422)
        and, for sites whose `country_code` is not `US`, additionally requires
        that the site hold a `VERIFIED` `IMPORT` license whose expiry is strictly
        after the current logical clock (otherwise `ERR_IMPORT_LICENSE_MISSING`,
        HTTP 422)."

        Design: Corner/validations/international_site_qualify_without_import_license_returns_import_license_missing
        """
        fixtures.set_clock(api)
        site = fixtures.create_site(
            api, organization_name="HT", country_code="HT", underserved_index=0.9
        )
        fixtures.create_verified_license(
            api, site["id"], license_type="PHARMACY", issuing_authority="HT MSPP",
            license_number="L-P",
        )
        resp = api.qualify_site(site["id"], COMPLIANCE_OFFICER_HEADERS)
        validate_error(resp, E.ERR_IMPORT_LICENSE_MISSING, 422)
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["qualification_status"] == "PENDING_REVIEW"


class TestQuantityBounds:
    def test_lines_exceeding_requested_quantity_rejected(self, api):
        """PRD §3.5: "The sum of line quantities must be strictly greater than
        zero and must not exceed the request's `quantity_requested`; violations
        surface as `ERR_QUANTITY_INVALID` (HTTP 422)."

        Design: Corner/validations/decision_finalize_overrequest_quantity_returns_quantity_invalid
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(api, donor["id"], ndc_code="N1")
        site = fixtures.setup_qualified_site(api)
        request = fixtures.create_request(api, site["id"], quantity_requested=5, ndc_code="N1")
        fixtures.begin_review(api, request["id"])
        # The sum rule is stated in the draft-creation paragraph of PRD §3.5, so
        # a line sum above quantity_requested is rejected when the draft is
        # created. (The same rule is re-checked at finalization per the ordered
        # guard list.)
        resp = api.create_allocation_decision(
            {
                "request_id": request["id"],
                "rationale": "over-request lines",
                "lines": [{"lot_id": lot["id"], "quantity": 10}],
            },
            ALLOCATION_OFFICER_HEADERS,
        )
        validate_error(resp, E.ERR_QUANTITY_INVALID, 422)


class TestSegregationOfDuties:
    def test_reviewer_matching_submitter_rejected(self, api):
        """PRD §3.11: "Review of a `SUBMITTED` report belongs to a
        `ComplianceOfficer`, and segregation of duties is enforced strictly: the
        reviewing officer's user id must differ from the report's
        `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)
        on either accept or reject."

        Design: Corner/validations/distribution_report_accepted_by_submitter_violates_segregation_of_duties
        """
        fixtures.set_clock(api)
        world = fixtures.setup_delivered_shipment(api, quantity_requested=10, lot_quantity=100)
        site_id = world["site"]["id"]
        report = fixtures.create_report(
            api, site_id, world["shipment"]["id"],
            units_distributed=5, patients_reached=5, wastage_units=0,
        )
        fixtures.submit_report(api, report["id"], site_id)
        # A ComplianceOfficer whose user id equals the submitter's (the site id).
        resp = api.accept_distribution_report(
            report["id"], make_compliance_officer_headers(site_id)
        )
        validate_error(resp, E.ERR_SEGREGATION_OF_DUTIES, 403)
        report_after = fixtures.get_report(api, report["id"])
        assert report_after["status"] == "SUBMITTED"


class TestDecisionFinalizeStaleVersion:
    def test_stale_expected_request_version_rejected(self, api):
        """PRD §2.6: "Finalizing an allocation decision requires the request body
        to include `expected_request_version`, carrying the client's
        last-observed `version` of the target `AllocationRequest`. If the
        request's current `version` no longer matches — because another writer
        has advanced the request since the client last read it — the finalize is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/decision_finalize_with_stale_request_version_returns_stale_version
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(api, donor["id"], ndc_code="N1")
        site = fixtures.setup_qualified_site(api)
        request = fixtures.create_request(api, site["id"], quantity_requested=5, ndc_code="N1")
        stale_version = request["version"]  # 1 at creation
        fixtures.begin_review(api, request["id"])  # bumps version to 2
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": 5}]
        )
        resp = api.finalize_decision(
            decision["id"], {"expected_request_version": stale_version},
            ALLOCATION_OFFICER_HEADERS,
        )
        validate_error(resp, E.ERR_STALE_VERSION, 412)
        decision_after = fixtures.get_decision(api, decision["id"])
        assert decision_after["status"] == "DRAFT"


class TestSiteSuspendStaleVersion:
    def test_stale_expected_site_version_rejected(self, api):
        """PRD §2.6: "Suspension of a recipient site requires the request body to
        include `expected_site_version`, carrying the client's last-observed
        `version` of the target `RecipientSite`; a mismatch is likewise rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/site_suspend_with_stale_site_version_returns_stale_version
        """
        fixtures.set_clock(api)
        site = fixtures.setup_qualified_site(api)
        # A version that can never match: PRD §2 pins `version` to start at 1
        # and increment on every mutation, so 0 is always a mismatch. (The PRD
        # does not state that verifying a license bumps the site's version, so
        # the test cannot manufacture staleness that way.)
        stale_version = 0
        resp = api.suspend_site(
            site["id"], {"expected_site_version": stale_version}, COMPLIANCE_OFFICER_HEADERS
        )
        validate_error(resp, E.ERR_STALE_VERSION, 412)
        site_after = fixtures.get_site(api, site["id"])
        assert site_after["qualification_status"] == "QUALIFIED"


class TestModuleOutOfRegion:
    def test_out_of_region_module_rejected(self, api):
        """PRD §3.9: "Reserving a module for an event requires the module to be
        `AVAILABLE`, the target event to be `ACTIVE` (otherwise
        `ERR_EMERGENCY_NOT_ACTIVE`), and either the module's
        `holding_country_code` to appear in the event's `affected_country_codes`
        or the event's `severity` to be at least 4 — otherwise
        `ERR_MODULE_OUT_OF_REGION` (HTTP 422)."

        Design: Corner/validations/emergency_reserve_module_out_of_region_returns_module_out_of_region
        """
        fixtures.set_clock(api)
        event = fixtures.create_active_event(
            api, event_name="EV", severity=2, affected_country_codes=["HT"]
        )
        module = fixtures.create_module(
            api, module_code="MOD-US", intended_use="PRIMARY_CARE", holding_country_code="US"
        )
        resp = api.reserve_module(
            module["id"], {"event_id": event["id"]}, EMERGENCY_MANAGER_HEADERS
        )
        validate_error(resp, E.ERR_MODULE_OUT_OF_REGION, 422)
        module_after = fixtures.get_module(api, module["id"])
        assert module_after["status"] == "AVAILABLE"


class TestReserveAgainstNonActiveEvent:
    def test_reserve_against_declared_event_rejected(self, api):
        """PRD §3.9: "Reserving a module for an event requires the module to be
        `AVAILABLE`, the target event to be `ACTIVE` (otherwise
        `ERR_EMERGENCY_NOT_ACTIVE`), and either the module's
        `holding_country_code` to appear in the event's `affected_country_codes`
        or the event's `severity` to be at least 4 — otherwise
        `ERR_MODULE_OUT_OF_REGION` (HTTP 422)."

        Design: Corner/validations/reserve_module_against_non_active_event_returns_emergency_not_active
        """
        fixtures.set_clock(api)
        event = fixtures.create_event(
            api, event_name="EV", severity=3, affected_country_codes=["HT"]
        )
        module = fixtures.create_module(
            api, module_code="MOD-HT", intended_use="PRIMARY_CARE", holding_country_code="HT"
        )
        resp = api.reserve_module(
            module["id"], {"event_id": event["id"]}, EMERGENCY_MANAGER_HEADERS
        )
        validate_error(resp, E.ERR_EMERGENCY_NOT_ACTIVE, 409)


class TestColdChainPackRequired:
    def test_cold_chain_pack_without_cold_shipper_rejected(self, api):
        """PRD §2.9: "**Cold-chain products** (a lot whose `product_class` is
        `COLD_CHAIN`, surfaced as the derived boolean `requires_cold_chain`) may
        be allocated only to a site whose `cold_storage_capacity_l` is greater
        than zero — otherwise `ERR_COLD_CHAIN_INADEQUATE` (HTTP 422) — and any
        shipment containing such a lot must be packed with a validated cold
        shipper, with `packed_with_cold_shipper` set to true; otherwise
        `ERR_COLD_CHAIN_PACK_REQUIRED` (HTTP 422) at pack completion."

        Design: Corner/validations/cold_chain_shipment_pack_without_cold_shipper_returns_pack_required
        """
        fixtures.set_clock(api)
        donor = fixtures.create_donor(api)
        lot = fixtures.create_and_release_lot(
            api, donor["id"], ndc_code="N1", product_name="Insulin",
            product_class="COLD_CHAIN", dosage_form="VIAL", unit_of_measure="VIAL",
            quantity_received=100, storage_temp_min_c=2, storage_temp_max_c=8,
            unit_acquisition_value_usd=5.00, unit_wholesale_value_usd=8.00,
        )
        site = fixtures.setup_qualified_site(api, site_type="FQHC", cold_storage_capacity_l=100)
        request = fixtures.create_request(api, site["id"], quantity_requested=1, ndc_code="N1")
        fixtures.begin_review(api, request["id"])
        current = fixtures.get_request(api, request["id"])
        decision = fixtures.create_draft_decision(
            api, request["id"], [{"lot_id": lot["id"], "quantity": 1}]
        )
        fixtures.finalize_decision(api, decision["id"], current["version"])
        shipment = fixtures.create_shipment_for_decision(
            api, decision["id"], packed_with_cold_shipper=False
        )
        resp = api.pack_complete(shipment["id"], LOGISTICS_COORDINATOR_HEADERS)
        validate_error(resp, E.ERR_COLD_CHAIN_PACK_REQUIRED, 422)
        shipment_after = fixtures.get_shipment(api, shipment["id"])
        assert shipment_after["status"] == "PACKING"
