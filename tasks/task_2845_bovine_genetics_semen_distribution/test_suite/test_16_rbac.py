"""Seven roles, each read as an authority list and as an ownership test."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    ROLE_BREEDING_ADVISOR,
    ROLE_DISTRIBUTOR,
    ROLE_EXPORT_COORDINATOR,
    ROLE_FACILITY_MANAGER,
    ROLE_LAB_TECHNICIAN,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_STAFF_VETERINARIAN,
    TECH_ALT_USER_ID,
    VET_ALT_USER_ID,
    assert_instant_equals,
    factories,
    fixtures as fx,
    headers_without_role,
    headers_without_user_id,
    make_distributor_headers,
    make_facility_headers,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNAUTHORIZED = ApiErrorId.ERR_UNAUTHORIZED.value


class TestProgramDirectorAuthority:
    """The registries and the commercial gates, and nothing operational."""

    def test_the_director_drives_the_clock_the_registries_and_the_gates(self, api):
        """Sets the server's logical clock, which every temporal rule in this domain
        reads.

        Design: Corner/rbac/program_director_holds_the_clock_and_the_commercial_gates
        """
        moved = fx.advance_clock(api, "2026-08-02T00:00:00Z")
        assert_instant_equals(moved["current_utc"], "2026-08-02T00:00:00Z")

        facility = fx.register_facility(api, code="F-PD")
        assert fx.suspend_facility(api, facility["id"])["approval_status"] == "SUSPENDED"
        assert fx.approve_facility(api, facility["id"])["approval_status"] == "APPROVED"
        requirement = validate_success(
            api.create_country_requirement(
                factories.country_requirement_payload(country_code="CA"), fx.DIRECTOR
            ),
            201,
        )
        assert requirement["country_code"] == "CA"

        sire = fx.register_sire(api, registration_code="REG-PD")
        fx.contract_sire(api, sire["id"])
        housed = fx.house_sire(api, sire["id"], facility["id"])
        assert housed["acquisition_status"] == "RESIDENT"
        proof = fx.published_proof(api, sire["id"])
        assert proof["status"] == "PUBLISHED"
        assert fx.rollback_evaluation(api, proof["id"])["status"] == "ROLLED_BACK"
        ancestor = fx.register_sire(
            api, registration_code="REG-PD-ANC", acquisition_cost_cents=0
        )
        amended = validate_success(
            api.amend_sire_pedigree(
                sire["id"],
                factories.pedigree_payload(sire_id=ancestor["id"]),
                fx.DIRECTOR,
            ),
            200,
        )
        assert amended["pedigree_depth"] == 1
        retired = validate_success(
            api.retire_sire(sire["id"], factories.retire_payload(), fx.DIRECTOR), 200
        )
        assert retired["acquisition_status"] == "RETIRED"

        # The field network and the plant's own book value are his too.
        partner = fx.distributor_with_tank(api, tank_overrides={"serial": "TK-PD"})
        assert fx.service_tank(api, partner["tank"]["id"], 96.0)["service_count"] == 1
        assert fx.read_valuation(api)["lot_count"] == 0

    def test_the_director_is_shut_out_of_every_operational_speciality(self, api):
        """If `X-User-Role` is missing, or names a role that is not authorised for the
        addressed operation, the request fails with `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/rbac/program_director_holds_the_clock_and_the_commercial_gates
        """
        refusals = (
            api.create_booking(
                factories.booking_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID),
                fx.DIRECTOR,
            ),
            api.order_health_test(
                NON_EXISTENT_UUID,
                factories.health_test_payload(NON_EXISTENT_UUID),
                fx.DIRECTOR,
            ),
            api.evaluate_ejaculate_qc(
                NON_EXISTENT_UUID, factories.qc_evaluation_payload(), fx.DIRECTOR
            ),
            api.cut_straw_lot(
                NON_EXISTENT_UUID, factories.straw_lot_payload(), fx.DIRECTOR
            ),
            api.release_straw_lot(
                NON_EXISTENT_UUID, factories.lot_release_payload(), fx.DIRECTOR
            ),
            api.create_export_certificate(
                factories.export_certificate_payload(
                    NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                fx.DIRECTOR,
            ),
            api.submit_export_certificate(
                NON_EXISTENT_UUID, factories.certificate_submit_payload(), fx.DIRECTOR
            ),
            api.issue_export_certificate(
                NON_EXISTENT_UUID, factories.certificate_issue_payload(), fx.DIRECTOR
            ),
            api.request_mating_recommendation(
                NON_EXISTENT_UUID,
                factories.mating_recommendation_payload(),
                fx.DIRECTOR,
            ),
            api.receive_consignment_transfer(
                NON_EXISTENT_UUID, factories.transfer_receive_payload(), fx.DIRECTOR
            ),
        )
        for response in refusals:
            validate_error(response, UNAUTHORIZED, 403)


class TestFacilityManagerScope:
    """A role whose identity is a facility row, so authority is ownership."""

    def test_the_bench_belongs_to_the_facility_the_header_names(self, api):
        """Concretely, a `FacilityManager` may only address a `CollectionBooking`
        whose `facility_id` equals its own `X-User-ID`, may only create a booking
        whose body `facility_id` equals its own `X-User-ID`, and may only house a sire
        into the facility its `X-User-ID` identifies.

        Design: Corner/rbac/facility_manager_is_scoped_to_its_own_bench
        """
        context = fx.eligible_sire(
            api, registration_code="REG-FM", facility_overrides={"code": "F-1"}
        )
        mine = context["facility"]["id"]
        theirs = fx.register_facility(api, code="F-2")["id"]
        owner = make_facility_headers(mine)
        intruder = make_facility_headers(theirs)
        scope = ApiErrorId.ERR_FACILITY_SCOPE.value

        booked = validate_success(
            api.create_booking(factories.booking_payload(context["sire"]["id"], mine), owner),
            201,
        )
        newcomer = fx.register_sire(api, registration_code="REG-FM2")
        fx.contract_sire(api, newcomer["id"])
        housed = validate_success(
            api.house_sire(newcomer["id"], factories.house_payload(mine), owner), 200
        )
        assert housed["housing_facility_id"] == mine

        # The same calls, the same role, a different facility in the header.
        validate_error(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], mine, "2026-09-20T08:00:00Z", "2026-09-20T10:00:00Z"
                ),
                intruder,
            ),
            scope,
            403,
        )
        validate_error(
            api.complete_booking(
                booked["id"], factories.booking_complete_payload(), intruder
            ),
            scope,
            403,
        )
        validate_error(
            api.cancel_booking(booked["id"], factories.booking_cancel_payload(), intruder),
            scope,
            403,
        )
        assert fx.read_booking(api, booked["id"])["status"] == "SCHEDULED"

        fx.advance_clock(api, fx.BOOKING_START)
        completed = validate_success(
            api.complete_booking(
                booked["id"], factories.booking_complete_payload(), owner
            ),
            200,
        )
        assert completed["status"] == "COMPLETED"

    def test_the_managers_reads_are_narrower_than_the_directors(self, api):
        """Lists ejaculates; booking_id and sire_id each reach a parent's children (the
        only discovery channel for a cascade-created ejaculate).

        Design: Corner/rbac/facility_manager_is_scoped_to_its_own_bench
        """
        context = fx.collected_ejaculate(
            api, registration_code="REG-FR", facility_overrides={"code": "F-FR"}
        )
        headers = context["facility_headers"]

        validate_success(api.get_booking(context["booking"]["id"], headers), 200)
        validate_success(api.get_facility(context["facility"]["id"], headers), 200)
        rows, meta = validate_paginated(
            api.list_ejaculates(headers, {"sire_id": context["sire"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == context["ejaculate"]["id"]
        validate_paginated(api.list_health_tests(headers, {"sire_id": context["sire"]["id"]}))

        # Inventory, value and the field network are not his to read.
        validate_error(api.list_straw_lots(headers), UNAUTHORIZED, 403)
        validate_error(api.get_inventory_valuation(headers), UNAUTHORIZED, 403)
        validate_error(api.list_tanks(headers), UNAUTHORIZED, 403)

        # Nor are the specialists' writes.
        validate_error(
            api.evaluate_ejaculate_qc(
                context["ejaculate"]["id"], factories.qc_evaluation_payload(), headers
            ),
            UNAUTHORIZED,
            403,
        )
        validate_error(
            api.order_health_test(
                context["sire"]["id"],
                factories.health_test_payload(context["facility"]["id"]),
                headers,
            ),
            UNAUTHORIZED,
            403,
        )
        validate_error(
            api.release_straw_lot(
                NON_EXISTENT_UUID, factories.lot_release_payload(), headers
            ),
            UNAUTHORIZED,
            403,
        )
        validate_error(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    context["sire"]["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID
                ),
                headers,
            ),
            UNAUTHORIZED,
            403,
        )


class TestStaffVeterinarianAuthority:
    """Health and the signature, but never the drafting of the paperwork."""

    def test_the_vet_orders_results_clears_suspends_and_signs(self, api):
        """The `StaffVeterinarian` is the herd-health authority: ordering and resulting
        health tests, clearing bulls for collection, suspending and reinstating them,
        and signing export certificates.

        Design: Corner/rbac/staff_veterinarian_owns_health_and_the_signature
        """
        context = fx.released_lot(
            api, registration_code="REG-VT", facility_overrides={"code": "F-VT"}
        )
        sire_id = context["sire"]["id"]
        assert context["sire"]["collection_status"] == "ELIGIBLE"

        ordered = validate_success(
            api.order_health_test(
                sire_id,
                factories.health_test_payload(context["facility"]["id"], test_type="IBR"),
                fx.VET,
            ),
            201,
        )
        assert ordered["result"] == "PENDING"
        resulted = validate_success(
            api.record_health_test_result(
                ordered["id"], factories.health_test_result_payload("NEGATIVE"), fx.VET
            ),
            200,
        )
        assert resulted["result"] == "NEGATIVE"

        # The signature and the two shared verdicts on the same document.
        requirement = fx.register_country_requirement(api)
        certificate = fx.submitted_certificate(
            api, sire_id, context["lot"]["id"], requirement["id"]
        )
        rejected = validate_success(
            api.reject_export_certificate(
                certificate["id"], factories.certificate_reject_payload(), fx.VET
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        assert fx.submit_certificate(api, certificate["id"])["status"] == "SUBMITTED"
        issued = validate_success(
            api.issue_export_certificate(
                certificate["id"], factories.certificate_issue_payload(), fx.VET_ALT
            ),
            200,
        )
        assert issued["status"] == "ISSUED"
        revoked = validate_success(
            api.revoke_export_certificate(
                certificate["id"], factories.certificate_revoke_payload(), fx.VET
            ),
            200,
        )
        assert revoked["status"] == "REVOKED"

        # Collection status is the vet's too, in both directions.
        suspended = validate_success(
            api.set_sire_collection_status(
                sire_id, factories.collection_status_payload("SUSPENDED"), fx.VET
            ),
            200,
        )
        assert suspended["collection_status"] == "SUSPENDED"
        reinstated = validate_success(
            api.set_sire_collection_status(
                sire_id, factories.collection_status_payload("ELIGIBLE"), fx.VET
            ),
            200,
        )
        assert reinstated["collection_status"] == "ELIGIBLE"

    def test_the_vet_may_sign_a_certificate_it_may_neither_draft_nor_submit(self, api):
        """The `ExportCoordinator` handles regulatory affairs — maintaining destination
        rule sets, drafting certificates and submitting them to authorities — but may
        never sign one, because issuance belongs to a veterinarian.

        Design: Corner/rbac/staff_veterinarian_owns_health_and_the_signature
        """
        context = fx.released_lot(
            api, registration_code="REG-VD", facility_overrides={"code": "F-VD"}
        )
        requirement = fx.register_country_requirement(api)
        draft = fx.draft_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )

        # Drafting and submitting are the coordinator's, even for this exact document.
        validate_error(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    context["sire"]["id"], context["lot"]["id"], requirement["id"]
                ),
                fx.VET,
            ),
            UNAUTHORIZED,
            403,
        )
        validate_error(
            api.submit_export_certificate(
                draft["id"], factories.certificate_submit_payload(), fx.VET
            ),
            UNAUTHORIZED,
            403,
        )
        assert fx.read_certificate(api, draft["id"])["status"] == "DRAFT"

        refusals = (
            api.evaluate_ejaculate_qc(
                context["ejaculate"]["id"], factories.qc_evaluation_payload(), fx.VET
            ),
            api.release_straw_lot(
                context["lot"]["id"], factories.lot_release_payload(), fx.VET
            ),
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], context["facility"]["id"]
                ),
                fx.VET,
            ),
            api.cut_straw_lot(
                context["ejaculate"]["id"], factories.straw_lot_payload(), fx.VET
            ),
            api.create_sire(factories.sire_payload(registration_code="REG-VX"), fx.VET),
            api.publish_genomic_evaluation(
                NON_EXISTENT_UUID, factories.publish_payload(), fx.VET
            ),
            api.list_straw_lots(fx.VET),
            api.get_inventory_valuation(fx.VET),
        )
        for response in refusals:
            validate_error(response, UNAUTHORIZED, 403)


class TestLabTechnicianAuthority:
    """The processing chain end to end, and the value report shared with the director."""

    def test_the_technician_evaluates_cuts_releases_condemns_and_reads_value(self, api):
        """A `LabTechnician` works in the processing laboratory: quality-evaluating
        ejaculates, cutting straw lots, and releasing or condemning them.

        Design: Corner/rbac/lab_technician_owns_processing_and_release
        """
        context = fx.quarantine_lot(
            api, registration_code="REG-LT", straw_count=120, processing_cost_cents=48000
        )
        assert context["ejaculate"]["qc_status"] == "ACCEPTED"
        assert context["lot"]["distribution_status"] == "QUARANTINE"

        released = validate_success(
            api.release_straw_lot(
                context["lot"]["id"], factories.lot_release_payload(), fx.TECH_ALT
            ),
            200,
        )
        assert released["distribution_status"] == "RELEASED"
        sibling = fx.cut_lot(
            api, context["ejaculate"]["id"], straw_count=10, processing_cost_cents=10000
        )
        condemned = validate_success(
            api.reject_straw_lot(sibling["id"], factories.lot_reject_payload(), fx.TECH),
            200,
        )
        assert condemned["distribution_status"] == "REJECTED"

        # The plant's book value is a director-level report deliberately shared here.
        valuation = validate_success(api.get_inventory_valuation(fx.TECH), 200)
        assert valuation["lot_count"] == 1
        assert valuation["released_value_cents"] == released["unit_book_value_cents"] * 120
        validate_success(api.get_ejaculate(context["ejaculate"]["id"], fx.TECH), 200)
        validate_success(api.get_straw_lot(context["lot"]["id"], fx.TECH), 200)
        validate_success(api.get_sire(context["sire"]["id"], fx.TECH), 200)

    def test_the_technician_sees_inventory_value_but_not_the_field_network(self, api):
        """Reads one tank with its decayed ln2_level_pct and derived tank_status.

        Design: Corner/rbac/lab_technician_owns_processing_and_release
        """
        context = fx.released_lot(api, registration_code="REG-LN")
        partner = fx.distributor_with_tank(api, tank_overrides={"serial": "TK-LN"})

        validate_error(
            api.request_consignment_transfer(
                context["lot"]["id"],
                factories.consignment_request_payload(
                    partner["distributor"]["id"],
                    partner["tank"]["id"],
                    context["lot"]["version"],
                ),
                fx.TECH,
            ),
            UNAUTHORIZED,
            403,
        )
        refusals = (
            api.issue_export_certificate(
                NON_EXISTENT_UUID, factories.certificate_issue_payload(), fx.TECH
            ),
            api.order_health_test(
                context["sire"]["id"],
                factories.health_test_payload(context["facility"]["id"]),
                fx.TECH,
            ),
            api.publish_genomic_evaluation(
                NON_EXISTENT_UUID, factories.publish_payload(), fx.TECH
            ),
            api.list_tanks(fx.TECH),
            api.get_tank(partner["tank"]["id"], fx.TECH),
            api.list_consignment_transfers(fx.TECH),
            api.get_facility(context["facility"]["id"], fx.TECH),
            api.list_health_tests(fx.TECH),
        )
        for response in refusals:
            validate_error(response, UNAUTHORIZED, 403)


class TestExportCoordinatorAuthority:
    """The two write steps that precede the signature, and nothing from it onward."""

    def test_the_coordinator_maintains_rule_sets_drafts_and_submits(self, api):
        """An `ExportCoordinator` drafts a certificate binding exactly three things:
        the `sire_id` whose health status the document attests, the `straw_lot_id` it
        covers — one certificate covers one lot — and the `country_requirement_id`
        naming the destination rule set to apply.

        Design: Corner/rbac/export_coordinator_drafts_but_never_signs
        """
        context = fx.released_lot(
            api, registration_code="REG-EC", facility_overrides={"code": "F-EC"}
        )
        requirement = validate_success(
            api.create_country_requirement(
                factories.country_requirement_payload(
                    country_code="CA",
                    required_test_types=["IBR"],
                    max_test_age_days=400,
                    min_isolation_days=30,
                ),
                fx.COORDINATOR,
            ),
            201,
        )
        assert requirement["country_code"] == "CA"

        draft = validate_success(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    context["sire"]["id"], context["lot"]["id"], requirement["id"]
                ),
                fx.COORDINATOR,
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        submitted = validate_success(
            api.submit_export_certificate(
                draft["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            200,
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_round"] == 1

        # Its reads run the whole export path.
        validate_success(api.get_facility(context["facility"]["id"], fx.COORDINATOR), 200)
        validate_paginated(api.list_sires(fx.COORDINATOR))
        validate_paginated(api.list_health_tests(fx.COORDINATOR))
        validate_paginated(api.list_straw_lots(fx.COORDINATOR))
        validate_paginated(api.list_export_certificates(fx.COORDINATOR))
        validate_paginated(api.list_consignment_transfers(fx.COORDINATOR))

    def test_the_coordinator_is_refused_every_step_from_the_signature_onward(self, api):
        """Signs a SUBMITTED certificate.

        Design: Corner/rbac/export_coordinator_drafts_but_never_signs
        """
        context = fx.released_lot(
            api, registration_code="REG-ES", facility_overrides={"code": "F-ES"}
        )
        requirement = fx.register_country_requirement(api)
        certificate = fx.submitted_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )
        partner = fx.distributor_with_tank(api, tank_overrides={"serial": "TK-ES"})
        transfer = fx.request_consignment(
            api,
            context["lot"]["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=10,
        )

        refusals = (
            api.issue_export_certificate(
                certificate["id"], factories.certificate_issue_payload(), fx.COORDINATOR
            ),
            api.reject_export_certificate(
                certificate["id"], factories.certificate_reject_payload(), fx.COORDINATOR
            ),
            api.revoke_export_certificate(
                certificate["id"], factories.certificate_revoke_payload(), fx.COORDINATOR
            ),
            api.create_sire(
                factories.sire_payload(registration_code="REG-EX"), fx.COORDINATOR
            ),
            api.release_straw_lot(
                context["lot"]["id"], factories.lot_release_payload(), fx.COORDINATOR
            ),
            api.approve_consignment_transfer(
                transfer["id"], factories.transfer_approve_payload(), fx.COORDINATOR
            ),
            api.list_tanks(fx.COORDINATOR),
            api.get_inventory_valuation(fx.COORDINATOR),
        )
        for response in refusals:
            validate_error(response, UNAUTHORIZED, 403)
        assert fx.read_certificate(api, certificate["id"])["status"] == "SUBMITTED"
        assert fx.read_transfer(api, transfer["id"])["status"] == "REQUESTED"


class TestDistributorScope:
    """Four entity types, all scope-checked against the same distributor id."""

    def test_the_partner_acts_across_its_own_network(self, api):
        """A `Distributor` is a field distribution partner that receives consignments
        into its own tanks, services them with liquid nitrogen, reports usage, returns
        unused stock and registers customer herds.

        Design: Corner/rbac/distributor_acts_only_inside_its_own_network
        """
        context = fx.received_consignment(
            api,
            stop_after="IN_TRANSIT",
            doses=40,
            registration_code="REG-DA",
            distributor_overrides={"name": "D-A"},
            tank_overrides={"serial": "TK-A"},
        )
        partner_id = context["distributor"]["id"]
        headers = context["distributor_headers"]

        received = validate_success(
            api.receive_consignment_transfer(
                context["transfer"]["id"], factories.transfer_receive_payload(), headers
            ),
            200,
        )
        assert received["status"] == "RECEIVED"
        reported = validate_success(
            api.report_consignment_usage(
                context["transfer"]["id"],
                factories.report_usage_payload(30, doses_returned=10),
                headers,
            ),
            200,
        )
        assert reported["doses_used"] == 30
        assert reported["doses_returned"] == 10

        # The shared field operations, all addressed to its own rows.
        second_tank = validate_success(
            api.create_tank(
                factories.tank_payload(partner_id, serial="TK-A2"), headers
            ),
            201,
        )
        assert fx.service_tank(api, context["tank"]["id"], 96.0, headers)["service_count"] == 1
        follow_on = validate_success(
            api.request_consignment_transfer(
                context["lot"]["id"],
                factories.consignment_request_payload(
                    partner_id,
                    second_tank["id"],
                    fx.read_lot(api, context["lot"]["id"])["version"],
                    doses=20,
                ),
                headers,
            ),
            201,
        )
        fx.approve_transfer(api, follow_on["id"])
        fx.dispatch_transfer(api, follow_on["id"])
        fx.receive_transfer(api, follow_on["id"], partner_id)
        returned = validate_success(
            api.return_consignment_transfer(
                follow_on["id"], factories.transfer_return_payload(), headers
            ),
            200,
        )
        assert returned["status"] == "RETURNED"

        # Customer-facing rows, and the decision it shares with the advisor.
        herd = validate_success(
            api.create_customer_herd(factories.customer_herd_payload(partner_id), headers),
            201,
        )
        fx.published_proof(api, context["sire"]["id"])
        recommendation = fx.request_recommendation(api, herd["id"])
        decided = validate_success(
            api.decide_mating_recommendation(
                recommendation["id"], factories.decision_payload("ACCEPTED"), headers
            ),
            200,
        )
        assert decided["status"] == "ACCEPTED"

    def test_role_and_scope_are_separate_checks_in_a_fixed_order(self, api):
        """Any mismatch on a `Distributor`-role call under consignment transfers, tanks
        or customer herds is rejected with `ERR_DISTRIBUTOR_SCOPE` (HTTP 403).

        Design: Corner/rbac/distributor_acts_only_inside_its_own_network
        """
        context = fx.received_consignment(
            api,
            stop_after="IN_TRANSIT",
            registration_code="REG-DS",
            distributor_overrides={"name": "D-A"},
            tank_overrides={"serial": "TK-A"},
        )
        mine = context["distributor_headers"]
        stranger = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-B"},
            tank_overrides={"serial": "TK-B"},
        )
        theirs = stranger["distributor_headers"]
        scope = ApiErrorId.ERR_DISTRIBUTOR_SCOPE.value

        herd = fx.register_customer_herd(api, context["distributor"]["id"])
        fx.published_proof(api, context["sire"]["id"])
        recommendation = fx.request_recommendation(api, herd["id"])
        for response, expected in (
            (
                api.receive_consignment_transfer(
                    context["transfer"]["id"],
                    factories.transfer_receive_payload(),
                    theirs,
                ),
                scope,
            ),
            (
                api.service_tank(
                    context["tank"]["id"], factories.tank_service_payload(96.0), theirs
                ),
                scope,
            ),
            (api.get_customer_herd(herd["id"], theirs), scope),
            (
                api.decide_mating_recommendation(
                    recommendation["id"], factories.decision_payload(), theirs
                ),
                scope,
            ),
        ):
            validate_error(response, expected, 403)
        assert fx.read_transfer(api, context["transfer"]["id"])["status"] == "IN_TRANSIT"

        # The commercial gates and the registry stay closed to the owning partner too.
        owner_refusals = (
            api.approve_consignment_transfer(
                context["transfer"]["id"], factories.transfer_approve_payload(), mine
            ),
            api.dispatch_consignment_transfer(
                context["transfer"]["id"], factories.transfer_dispatch_payload(), mine
            ),
            api.get_sire(context["sire"]["id"], mine),
            api.get_inventory_valuation(mine),
        )
        for response in owner_refusals:
            validate_error(response, UNAUTHORIZED, 403)

        # Role membership is tested before ownership, so a stranger on an endpoint the
        # role does not hold gets the role code and never the scope code.
        validate_error(
            api.approve_consignment_transfer(
                context["transfer"]["id"], factories.transfer_approve_payload(), theirs
            ),
            UNAUTHORIZED,
            403,
        )


class TestBreedingAdvisorAuthority:
    """The heaviest calculation in the domain, and no authority over its inputs."""

    def test_the_advisor_asks_the_selector_and_records_the_decision(self, api):
        """A `BreedingAdvisor` is the customer-facing programme adviser who asks the
        selector engine for mating recommendations and records the customer's decision,
        with no authority over inventory, health or certification.

        Design: Corner/rbac/breeding_advisor_advises_without_inventory_authority
        """
        context = fx.released_lot(api, registration_code="REG-BA")
        fx.published_proof(api, context["sire"]["id"])
        partner = fx.register_distributor(api, name="D-BA")

        herd = validate_success(
            api.create_customer_herd(
                factories.customer_herd_payload(
                    partner["id"], herd_name="H-BA", max_inbreeding_pct=6.25
                ),
                fx.ADVISOR,
            ),
            201,
        )
        recommendation = validate_success(
            api.request_mating_recommendation(
                herd["id"],
                factories.mating_recommendation_payload(
                    dam_ref="DAM-BA-1", doses_requested=8
                ),
                fx.ADVISOR,
            ),
            201,
        )
        assert recommendation["status"] == "PROPOSED"
        assert recommendation["recommended_sire_id"] == context["sire"]["id"]
        decided = validate_success(
            api.decide_mating_recommendation(
                recommendation["id"], factories.decision_payload("ACCEPTED"), fx.ADVISOR
            ),
            200,
        )
        assert decided["status"] == "ACCEPTED"

        validate_paginated(api.list_sires(fx.ADVISOR))
        validate_paginated(api.list_straw_lots(fx.ADVISOR))
        validate_paginated(api.list_genomic_evaluations(fx.ADVISOR))
        validate_paginated(api.list_customer_herds(fx.ADVISOR))
        validate_paginated(api.list_mating_recommendations(fx.ADVISOR))

        # The role is opaque, so one advisor serves every partner's herds.
        elsewhere = fx.register_distributor(api, name="D-BB")
        second = validate_success(
            api.create_customer_herd(
                factories.customer_herd_payload(elsewhere["id"], herd_name="H-BB"),
                fx.ADVISOR,
            ),
            201,
        )
        across = fx.request_recommendation(api, second["id"], dam_ref="DAM-BA-2")
        assert across["status"] == "PROPOSED"
        assert (
            fx.decide_recommendation(api, across["id"], "WITHDRAWN")["status"]
            == "WITHDRAWN"
        )

    def test_the_advisor_holds_no_authority_over_the_rows_it_selects_from(self, api):
        """When `X-User-Role` is `ProgramDirector`, `StaffVeterinarian`,
        `LabTechnician`, `ExportCoordinator` or `BreedingAdvisor`, `X-User-ID` is an
        opaque operator identifier not tied to any persisted entity.

        Design: Corner/rbac/breeding_advisor_advises_without_inventory_authority
        """
        context = fx.released_lot(api, registration_code="REG-BD")
        partner = fx.distributor_with_tank(api, tank_overrides={"serial": "TK-BD"})
        requirement = fx.register_country_requirement(api)

        refusals = (
            api.request_consignment_transfer(
                context["lot"]["id"],
                factories.consignment_request_payload(
                    partner["distributor"]["id"],
                    partner["tank"]["id"],
                    context["lot"]["version"],
                ),
                fx.ADVISOR,
            ),
            api.release_straw_lot(
                context["lot"]["id"], factories.lot_release_payload(), fx.ADVISOR
            ),
            api.order_health_test(
                context["sire"]["id"],
                factories.health_test_payload(context["facility"]["id"]),
                fx.ADVISOR,
            ),
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], context["facility"]["id"]
                ),
                fx.ADVISOR,
            ),
            api.create_export_certificate(
                factories.export_certificate_payload(
                    context["sire"]["id"], context["lot"]["id"], requirement["id"]
                ),
                fx.ADVISOR,
            ),
            api.submit_export_certificate(
                NON_EXISTENT_UUID, factories.certificate_submit_payload(), fx.ADVISOR
            ),
            api.issue_export_certificate(
                NON_EXISTENT_UUID, factories.certificate_issue_payload(), fx.ADVISOR
            ),
            api.get_inventory_valuation(fx.ADVISOR),
            api.list_tanks(fx.ADVISOR),
            api.list_consignment_transfers(fx.ADVISOR),
        )
        for response in refusals:
            validate_error(response, UNAUTHORIZED, 403)


class TestExclusiveOperationsClosedToOtherRoles:
    """The denial matrix, and the band the role check sits in."""

    def test_the_role_check_precedes_existence_and_version_pinning(self, api):
        """Third, existence: path ids left to right, then body foreign keys
        (`ERR_RESOURCE_NOT_FOUND`).

        Design: Corner/rbac/every_exclusive_operation_is_closed_to_the_other_six_roles
        """
        fx.advance_clock(api, "2026-09-01T00:00:00Z")
        sire = fx.register_sire(api, registration_code="REG-PR")
        not_found = ApiErrorId.ERR_RESOURCE_NOT_FOUND.value

        # A wrong role on a fabricated id answers the role code, never the 404.
        validate_error(
            api.file_genomic_evaluation(
                NON_EXISTENT_UUID, factories.genomic_evaluation_payload(1), fx.ADVISOR
            ),
            UNAUTHORIZED,
            403,
        )
        # The owning role on the same fabricated id does reach the lookup.
        validate_error(
            api.file_genomic_evaluation(
                NON_EXISTENT_UUID, factories.genomic_evaluation_payload(1), fx.DIRECTOR
            ),
            not_found,
            404,
        )
        # A wrong role with a stale pin answers the role code, never the 412.
        validate_error(
            api.file_genomic_evaluation(
                sire["id"], factories.genomic_evaluation_payload(99), fx.ADVISOR
            ),
            UNAUTHORIZED,
            403,
        )
        # An absent role header and an unrecognised role string are the same code.
        validate_error(
            api.file_genomic_evaluation(
                sire["id"],
                factories.genomic_evaluation_payload(sire["version"]),
                headers_without_role(),
            ),
            UNAUTHORIZED,
            403,
        )
        validate_error(
            api.file_genomic_evaluation(
                sire["id"],
                factories.genomic_evaluation_payload(sire["version"]),
                make_headers("Auditor", "aud-1"),
            ),
            UNAUTHORIZED,
            403,
        )

        # No denial wrote anything.
        assert fx.read_sire(api, sire["id"])["version"] == sire["version"]
        _rows, meta = validate_paginated(
            api.list_genomic_evaluations(fx.DIRECTOR, {"sire_id": sire["id"]})
        )
        assert meta["total_count"] == 0

    def test_each_exclusive_family_refuses_the_six_roles_that_do_not_own_it(self, api):
        """If `X-User-Role` is missing, or names a role that is not authorised for the
        addressed operation, the request fails with `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/rbac/every_exclusive_operation_is_closed_to_the_other_six_roles
        """

        def publish_a_proof(headers):
            return api.publish_genomic_evaluation(
                NON_EXISTENT_UUID, factories.publish_payload(), headers
            )

        def book_a_bench_slot(headers):
            return api.create_booking(
                factories.booking_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), headers
            )

        def result_an_assay(headers):
            return api.record_health_test_result(
                NON_EXISTENT_UUID, factories.health_test_result_payload(), headers
            )

        def record_a_qc_verdict(headers):
            return api.evaluate_ejaculate_qc(
                NON_EXISTENT_UUID, factories.qc_evaluation_payload(), headers
            )

        def submit_a_certificate(headers):
            return api.submit_export_certificate(
                NON_EXISTENT_UUID, factories.certificate_submit_payload(), headers
            )

        def receive_a_consignment(headers):
            return api.receive_consignment_transfer(
                NON_EXISTENT_UUID, factories.transfer_receive_payload(), headers
            )

        def ask_for_a_mating(headers):
            return api.request_mating_recommendation(
                NON_EXISTENT_UUID, factories.mating_recommendation_payload(), headers
            )

        every_role = {
            ROLE_PROGRAM_DIRECTOR: fx.DIRECTOR,
            ROLE_FACILITY_MANAGER: make_facility_headers(NON_EXISTENT_UUID),
            ROLE_STAFF_VETERINARIAN: fx.VET,
            ROLE_LAB_TECHNICIAN: fx.TECH,
            ROLE_EXPORT_COORDINATOR: fx.COORDINATOR,
            ROLE_DISTRIBUTOR: make_distributor_headers(NON_EXISTENT_UUID),
            ROLE_BREEDING_ADVISOR: fx.ADVISOR,
        }
        matrix = (
            (ROLE_PROGRAM_DIRECTOR, publish_a_proof),
            (ROLE_FACILITY_MANAGER, book_a_bench_slot),
            (ROLE_STAFF_VETERINARIAN, result_an_assay),
            (ROLE_LAB_TECHNICIAN, record_a_qc_verdict),
            (ROLE_EXPORT_COORDINATOR, submit_a_certificate),
            (ROLE_DISTRIBUTOR, receive_a_consignment),
            (ROLE_BREEDING_ADVISOR, ask_for_a_mating),
        )
        for owner, call in matrix:
            for role, headers in every_role.items():
                if role == owner:
                    continue
                validate_error(call(headers), UNAUTHORIZED, 403)

        # The five opaque owners reach the lookup on the same fabricated ids.
        not_found = ApiErrorId.ERR_RESOURCE_NOT_FOUND.value
        for call, headers in (
            (publish_a_proof, fx.DIRECTOR),
            (result_an_assay, fx.VET),
            (record_a_qc_verdict, fx.TECH),
            (submit_a_certificate, fx.COORDINATOR),
            (ask_for_a_mating, fx.ADVISOR),
        ):
            validate_error(call(headers), not_found, 404)


class TestSharedOperationsAdmitTheirPair:
    """Shared operations are pairwise, never open."""

    def test_each_shared_operation_admits_exactly_the_two_roles_named(self, api):
        """Requests a consignment of doses from a RELEASED lot into a distributor's
        tank.

        Design: Corner/rbac/shared_operations_admit_exactly_their_declared_roles
        """
        context = fx.released_lot(api, registration_code="REG-SH")
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-SH"},
            tank_overrides={"serial": "TK-SH"},
        )
        partner_id = partner["distributor"]["id"]
        tank_id = partner["tank"]["id"]
        partner_headers = partner["distributor_headers"]
        outsiders = (
            fx.VET,
            fx.TECH,
            fx.COORDINATOR,
            fx.ADVISOR,
            make_facility_headers(NON_EXISTENT_UUID),
        )

        for headers in outsiders:
            validate_error(
                api.request_consignment_transfer(
                    context["lot"]["id"],
                    factories.consignment_request_payload(
                        partner_id, tank_id, context["lot"]["version"], doses=10
                    ),
                    headers,
                ),
                UNAUTHORIZED,
                403,
            )
        assert fx.request_consignment(
            api, context["lot"]["id"], partner_id, tank_id, doses=10
        )["status"] == "REQUESTED"
        as_partner = validate_success(
            api.request_consignment_transfer(
                context["lot"]["id"],
                factories.consignment_request_payload(
                    partner_id,
                    tank_id,
                    fx.read_lot(api, context["lot"]["id"])["version"],
                    doses=10,
                ),
                partner_headers,
            ),
            201,
        )
        assert as_partner["status"] == "REQUESTED"

        # The field network: the same pair again.
        for headers in outsiders:
            validate_error(
                api.create_tank(
                    factories.tank_payload(partner_id, serial="TK-NO"), headers
                ),
                UNAUTHORIZED,
                403,
            )
            validate_error(
                api.service_tank(tank_id, factories.tank_service_payload(96.0), headers),
                UNAUTHORIZED,
                403,
            )
        validate_success(
            api.create_tank(
                factories.tank_payload(partner_id, serial="TK-DIR"), fx.DIRECTOR
            ),
            201,
        )
        assert fx.service_tank(api, tank_id, 96.0)["service_count"] == 1

        # The valuation read: director and technician, and nobody else.
        validate_success(api.get_inventory_valuation(fx.DIRECTOR), 200)
        validate_success(api.get_inventory_valuation(fx.TECH), 200)
        for headers in (
            fx.VET,
            fx.COORDINATOR,
            fx.ADVISOR,
            make_facility_headers(NON_EXISTENT_UUID),
            partner_headers,
        ):
            validate_error(api.get_inventory_valuation(headers), UNAUTHORIZED, 403)

        # Customer-facing rows: advisor and partner, and not the director.
        validate_success(
            api.create_customer_herd(
                factories.customer_herd_payload(partner_id, herd_name="H-PART"),
                partner_headers,
            ),
            201,
        )
        herd = validate_success(
            api.create_customer_herd(
                factories.customer_herd_payload(partner_id, herd_name="H-ADV"),
                fx.ADVISOR,
            ),
            201,
        )
        validate_error(
            api.create_customer_herd(
                factories.customer_herd_payload(partner_id, herd_name="H-DIR"),
                fx.DIRECTOR,
            ),
            UNAUTHORIZED,
            403,
        )
        fx.published_proof(api, context["sire"]["id"])
        recommendation = fx.request_recommendation(api, herd["id"])
        validate_error(
            api.decide_mating_recommendation(
                recommendation["id"], factories.decision_payload(), fx.DIRECTOR
            ),
            UNAUTHORIZED,
            403,
        )
        decided = validate_success(
            api.decide_mating_recommendation(
                recommendation["id"], factories.decision_payload("ACCEPTED"), partner_headers
            ),
            200,
        )
        assert decided["status"] == "ACCEPTED"

    def test_sharing_one_step_does_not_leak_the_neighbouring_step(self, api):
        """Approves a REQUESTED consignment.

        Design: Corner/rbac/shared_operations_admit_exactly_their_declared_roles
        """
        context = fx.received_consignment(
            api,
            stop_after="REQUESTED",
            registration_code="REG-SL",
            distributor_overrides={"name": "D-SL"},
            tank_overrides={"serial": "TK-SL"},
        )
        transfer_id = context["transfer"]["id"]
        partner_headers = context["distributor_headers"]

        # The partner requested this consignment and still cannot gate it.
        validate_error(
            api.approve_consignment_transfer(
                transfer_id, factories.transfer_approve_payload(), partner_headers
            ),
            UNAUTHORIZED,
            403,
        )
        assert fx.approve_transfer(api, transfer_id)["status"] == "APPROVED"
        validate_error(
            api.dispatch_consignment_transfer(
                transfer_id, factories.transfer_dispatch_payload(), partner_headers
            ),
            UNAUTHORIZED,
            403,
        )
        assert fx.dispatch_transfer(api, transfer_id)["status"] == "IN_TRANSIT"

        # The manager owns booking creation outright but shares its cancellation.
        eligible = fx.eligible_sire(
            api,
            registration_code="REG-SL2",
            facility_overrides={"code": "F-SL"},
            isolation_days=0,
            clearance_clock=None,
        )
        validate_error(
            api.create_booking(
                factories.booking_payload(
                    eligible["sire"]["id"],
                    eligible["facility"]["id"],
                    "2026-09-20T08:00:00Z",
                    "2026-09-20T10:00:00Z",
                ),
                fx.DIRECTOR,
            ),
            UNAUTHORIZED,
            403,
        )
        booking = fx.book_collection(
            api,
            eligible["sire"]["id"],
            eligible["facility"]["id"],
            "2026-09-20T08:00:00Z",
            "2026-09-20T10:00:00Z",
        )
        cancelled = validate_success(
            api.cancel_booking(
                booking["id"], factories.booking_cancel_payload(), fx.DIRECTOR
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

        # Housing admits the same pair as cancellation.
        newcomer = fx.register_sire(api, registration_code="REG-SL3")
        fx.contract_sire(api, newcomer["id"])
        housed = fx.house_sire(api, newcomer["id"], eligible["facility"]["id"], 0)
        assert housed["housing_facility_id"] == eligible["facility"]["id"]


class TestDutySeparationBars:
    """Two barriers that read recorded operator identities, not roles."""

    def test_the_evaluating_technician_may_condemn_a_lot_but_never_release_it(self, api):
        """Release is also the first segregation-of-duties barrier: the releasing
        `X-User-ID` must differ from the `evaluated_by_user_id` recorded on the lot's
        parent ejaculate, and the same individual attempting both roles is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/rbac/lot_release_is_barred_to_the_technician_who_evaluated_the_ejaculate
        """
        first = fx.collected_ejaculate(
            api, registration_code="REG-D1", facility_overrides={"code": "F-D1"}
        )
        evaluated = fx.evaluate_qc(api, first["ejaculate"]["id"], "ACCEPTED", headers=fx.TECH)
        assert evaluated["qc_status"] == "ACCEPTED"
        lot = fx.cut_lot(
            api,
            first["ejaculate"]["id"],
            straw_count=120,
            processing_cost_cents=48000,
            headers=fx.TECH,
        )
        assert lot["distribution_status"] == "QUARANTINE"

        validate_error(
            api.release_straw_lot(lot["id"], factories.lot_release_payload(), fx.TECH),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert fx.read_lot(api, lot["id"])["distribution_status"] == "QUARANTINE"

        # Condemnation is not barred, so the rule separates approval from approval.
        sibling = fx.cut_lot(
            api,
            first["ejaculate"]["id"],
            straw_count=10,
            processing_cost_cents=10000,
            headers=fx.TECH,
        )
        condemned = validate_success(
            api.reject_straw_lot(sibling["id"], factories.lot_reject_payload(), fx.TECH),
            200,
        )
        assert condemned["distribution_status"] == "REJECTED"

        released = validate_success(
            api.release_straw_lot(lot["id"], factories.lot_release_payload(), fx.TECH_ALT),
            200,
        )
        assert released["distribution_status"] == "RELEASED"
        assert released["released_by_user_id"] == TECH_ALT_USER_ID

        # The bar is per ejaculate: another evaluator frees the first technician.
        second = fx.collected_ejaculate(
            api,
            registration_code="REG-D2",
            facility_overrides={"code": "F-D2"},
            isolation_days=0,
            clearance_clock=None,
            start_at="2026-09-20T08:00:00Z",
            end_at="2026-09-20T10:00:00Z",
            collection_clock="2026-09-20T08:00:00Z",
        )
        fx.evaluate_qc(api, second["ejaculate"]["id"], "ACCEPTED", headers=fx.TECH_ALT)
        other_lot = fx.cut_lot(
            api,
            second["ejaculate"]["id"],
            straw_count=60,
            processing_cost_cents=24000,
            headers=fx.TECH_ALT,
        )
        crossed = validate_success(
            api.release_straw_lot(
                other_lot["id"], factories.lot_release_payload(), fx.TECH
            ),
            200,
        )
        assert crossed["distribution_status"] == "RELEASED"

        # State outranks duty: the refusal on a RELEASED lot is the state code.
        validate_error(
            api.release_straw_lot(lot["id"], factories.lot_release_payload(), fx.TECH),
            ApiErrorId.ERR_LOT_STATE.value,
            409,
        )

    def test_the_signing_vet_must_never_have_resulted_that_bulls_assays(self, api):
        """The second segregation-of-duties barrier bites here: the signing `X-User-ID`
        must not appear as the `recorded_by_user_id` on any `HealthTest` belonging to
        the certificate's bull.

        Design: Corner/rbac/certificate_signature_is_barred_to_the_vet_who_resulted_the_tests
        """
        context = fx.released_lot(
            api, registration_code="REG-SG", facility_overrides={"code": "F-SG"}
        )
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR"],
            max_test_age_days=400,
            min_isolation_days=30,
        )
        draft = fx.draft_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )

        # State outranks duty: a DRAFT answers the state code, not the 403.
        validate_error(
            api.issue_export_certificate(
                draft["id"], factories.certificate_issue_payload(), fx.VET
            ),
            ApiErrorId.ERR_CERTIFICATE_STATE.value,
            409,
        )
        assert fx.submit_certificate(api, draft["id"])["status"] == "SUBMITTED"

        # The operator header is mandatory here, and it is read before the barrier.
        validate_error(
            api.issue_export_certificate(
                draft["id"],
                factories.certificate_issue_payload(),
                headers_without_user_id(ROLE_STAFF_VETERINARIAN),
            ),
            ApiErrorId.ERR_USER_ID_REQUIRED.value,
            400,
        )
        validate_error(
            api.issue_export_certificate(
                draft["id"], factories.certificate_issue_payload(), fx.VET
            ),
            ApiErrorId.ERR_CERTIFIER_TESTED_SIRE.value,
            403,
        )
        issued = validate_success(
            api.issue_export_certificate(
                draft["id"], factories.certificate_issue_payload(), fx.VET_ALT
            ),
            200,
        )
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == VET_ALT_USER_ID
        assert issued["expires_at"] is not None

        # The disqualifying history is per bull: another vet's bull is signable.
        elsewhere = fx.released_lot(
            api,
            registration_code="REG-SG2",
            facility_overrides={"code": "F-SG2"},
            vet_headers=fx.VET_ALT,
            clearance_clock="2026-10-11T00:00:00Z",
            start_at="2026-10-12T08:00:00Z",
            end_at="2026-10-12T10:00:00Z",
            collection_clock="2026-10-12T08:00:00Z",
        )
        second = fx.submitted_certificate(
            api,
            elsewhere["sire"]["id"],
            elsewhere["lot"]["id"],
            requirement["id"],
        )
        countersigned = validate_success(
            api.issue_export_certificate(
                second["id"], factories.certificate_issue_payload(), fx.VET
            ),
            200,
        )
        assert countersigned["status"] == "ISSUED"
