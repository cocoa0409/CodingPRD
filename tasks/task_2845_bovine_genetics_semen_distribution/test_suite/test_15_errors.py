"""The error catalogue exercised code by code: each family, its own trigger."""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    ROLE_LAB_TECHNICIAN,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_STAFF_VETERINARIAN,
    assert_buckets,
    assert_instant_equals,
    expected_theoretical_doses,
    factories,
    fixtures as fx,
    headers_without_role,
    headers_without_user_id,
    make_distributor_headers,
    make_facility_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInputShapeAndHeaderCodes:
    """The 400 family: four shape defects under one code, the header under another."""

    def test_every_shape_defect_reports_the_same_validation_code(self, api):
        """Every non-optional field in the operation's input list must be present
        and non-null; unknown body keys are ignored rather than rejected. All three
        shape bands report `ERR_VALIDATION` (HTTP 400).

        Design: Corner/errors/input_shape_and_header_codes_are_rejected
        """
        context = fx.collected_ejaculate(api, registration_code="REG-BAD")
        partner = fx.register_distributor(api, name="D-BAD")
        ejaculate_id = context["ejaculate"]["id"]

        # The missing-field arm: birth_date carries no default.
        validate_error(
            api.create_sire(
                factories.sire_payload(
                    registration_code="REG-NOBIRTH", birth_date=factories.OMIT
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        _rows, meta = validate_paginated(api.list_sires(fx.DIRECTOR))
        assert meta["total_count"] == 1

        # The closed-enum arm: a verdict outside the set is not a state error.
        validate_error(
            api.evaluate_ejaculate_qc(
                ejaculate_id, factories.qc_evaluation_payload("MAYBE"), fx.TECH
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        assert fx.read_ejaculate(api, ejaculate_id)["qc_status"] == "PENDING_QC"

        # The numeric-bound arm: a percentage must sit within 0 to 100.
        validate_error(
            api.create_tank(
                factories.tank_payload(
                    partner["id"], serial="TK-OVERFILL", initial_fill_pct=140.0
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        brimming = validate_success(
            api.create_tank(
                factories.tank_payload(
                    partner["id"], serial="TK-BRIM", initial_fill_pct=100.0
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert brimming["ln2_level_pct"] == pytest.approx(100.0, abs=0.01)
        assert brimming["tank_status"] == "IN_SERVICE"

        # The instant arm: a date is not an ISO 8601 UTC timestamp.
        validate_error(
            api.set_clock_raw({"current_utc": "2026-09-01"}, fx.DIRECTOR),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        assert fx.read_tank(api, brimming["id"])["ln2_level_pct"] == pytest.approx(
            100.0, abs=0.01
        )

    def test_three_of_the_four_stamped_operations_demand_an_operator_id(self, api):
        """Four operations additionally require `X-User-ID` to be present and
        non-empty, because each one stamps an operator identity that a later barrier
        will read: recording a health-test result, recording an ejaculate quality
        verdict, releasing a straw lot, and issuing an export certificate.

        Design: Corner/errors/input_shape_and_header_codes_are_rejected
        """
        context = fx.collected_ejaculate(api, registration_code="REG-ID")
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        ejaculate_id = context["ejaculate"]["id"]
        pending = fx.order_health_test(api, sire_id, facility_id, test_type="EBL")

        validate_error(
            api.record_health_test_result(
                pending["id"],
                factories.health_test_result_payload(),
                headers_without_user_id(ROLE_STAFF_VETERINARIAN),
            ),
            ApiErrorId.ERR_USER_ID_REQUIRED.value,
            400,
        )
        assert fx.read_health_test(api, pending["id"])["result"] == "PENDING"

        validate_error(
            api.evaluate_ejaculate_qc(
                ejaculate_id,
                factories.qc_evaluation_payload(),
                headers_without_user_id(ROLE_LAB_TECHNICIAN),
            ),
            ApiErrorId.ERR_USER_ID_REQUIRED.value,
            400,
        )
        assert fx.read_ejaculate(api, ejaculate_id)["qc_status"] == "PENDING_QC"

        # Straws may only be cut from an ACCEPTED ejaculate, so record the verdict
        # properly before reaching for the lot's own stamped operation.
        context = fx.accepted_ejaculate(api, context)
        context = fx.quarantine_lot(api, context, straw_count=100)
        lot_id = context["lot"]["id"]
        validate_error(
            api.release_straw_lot(
                lot_id,
                factories.lot_release_payload(),
                headers_without_user_id(ROLE_LAB_TECHNICIAN),
            ),
            ApiErrorId.ERR_USER_ID_REQUIRED.value,
            400,
        )
        lot = fx.read_lot(api, lot_id)
        assert lot["distribution_status"] == "QUARANTINE"
        assert lot["released_by_user_id"] is None

    def test_issuance_demands_it_while_an_untracked_move_does_not(self, api):
        """On those four, an absent or empty `X-User-ID` yields
        `ERR_USER_ID_REQUIRED` (HTTP 400).

        Design: Corner/errors/input_shape_and_header_codes_are_rejected
        """
        requirement = fx.register_country_requirement(
            api, country_code="CA", max_test_age_days=60, min_isolation_days=21
        )
        context = fx.released_lot(
            api,
            registration_code="REG-SIGN",
            facility_overrides={"code": "F-SIGN", "approved_export_countries": ["CA"]},
            straw_count=100,
            processing_cost_cents=125000,
        )
        certificate = fx.submitted_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )

        validate_error(
            api.issue_export_certificate(
                certificate["id"],
                factories.certificate_issue_payload(),
                headers_without_user_id(ROLE_STAFF_VETERINARIAN),
            ),
            ApiErrorId.ERR_USER_ID_REQUIRED.value,
            400,
        )
        held = fx.read_certificate(api, certificate["id"])
        assert held["status"] == "SUBMITTED"
        assert held["issued_by_user_id"] is None

        # Contracting stamps no operator identity, so the header is not demanded.
        spare = fx.register_sire(api, registration_code="REG-UNTRACKED")
        contracted = validate_success(
            api.contract_sire(
                spare["id"],
                factories.contract_payload(),
                headers_without_user_id(ROLE_PROGRAM_DIRECTOR),
            ),
            200,
        )
        assert contracted["acquisition_status"] == "CONTRACTED"


class TestRoleScopeAndDutyCodes:
    """Five separate 403s: one about roles, two about ownership, two about history."""

    def test_a_role_outside_the_authorised_list_is_forbidden(self, api):
        """If `X-User-Role` is missing, or names a role that is not authorised for
        the addressed operation, the request fails with `ERR_UNAUTHORIZED`
        (HTTP 403).

        Design: Corner/errors/role_scope_and_duty_codes_are_forbidden
        """
        partner = fx.register_distributor(api, name="D-NOSEE")

        validate_error(
            api.get_inventory_valuation(fx.ADVISOR),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.get_inventory_valuation(make_distributor_headers(partner["id"])),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.get_inventory_valuation(headers_without_role()),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )

        # Both listed roles read the same aggregate.
        by_director = validate_success(api.get_inventory_valuation(fx.DIRECTOR), 200)
        by_technician = validate_success(api.get_inventory_valuation(fx.TECH), 200)
        assert by_director["plant_inventory_value_cents"] == 0
        assert by_director["lot_count"] == 0
        assert by_technician == by_director

    def test_a_partner_may_not_reach_another_partners_network(self, api):
        """Any mismatch on a `Distributor`-role call under consignment transfers,
        tanks or customer herds is rejected with `ERR_DISTRIBUTOR_SCOPE`
        (HTTP 403).

        Design: Corner/errors/role_scope_and_duty_codes_are_forbidden
        """
        context = fx.received_consignment(
            api,
            stop_after="IN_TRANSIT",
            doses=20,
            registration_code="REG-SCOPE",
            facility_overrides={"code": "F-SCOPE"},
            straw_count=100,
            processing_cost_cents=125000,
            distributor_overrides={"name": "D-A"},
            tank_overrides={"serial": "TK-A1"},
        )
        intruder = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-B"},
            tank_overrides={"serial": "TK-B1"},
        )
        herd = fx.register_customer_herd(
            api, context["distributor"]["id"], herd_name="H-A"
        )
        intruder_headers = intruder["distributor_headers"]

        validate_error(
            api.receive_consignment_transfer(
                context["transfer"]["id"],
                factories.transfer_receive_payload(),
                intruder_headers,
            ),
            ApiErrorId.ERR_DISTRIBUTOR_SCOPE.value,
            403,
        )
        validate_error(
            api.service_tank(
                context["tank"]["id"], factories.tank_service_payload(), intruder_headers
            ),
            ApiErrorId.ERR_DISTRIBUTOR_SCOPE.value,
            403,
        )
        validate_error(
            api.get_customer_herd(herd["id"], intruder_headers),
            ApiErrorId.ERR_DISTRIBUTOR_SCOPE.value,
            403,
        )
        assert fx.read_transfer(api, context["transfer"]["id"])["status"] == "IN_TRANSIT"

        # The owning partner's own id passes the same three calls' scope check.
        received = fx.receive_transfer(
            api, context["transfer"]["id"], context["distributor"]["id"]
        )
        assert received["status"] == "RECEIVED"

    def test_a_facility_manager_may_not_reach_another_bench(self, api):
        """A violation is rejected with `ERR_FACILITY_SCOPE` (HTTP 403), and that
        check governs booking creation, booking completion, booking cancellation and
        facility approval-status changes.

        Design: Corner/errors/role_scope_and_duty_codes_are_forbidden
        """
        context = fx.eligible_sire(
            api, registration_code="REG-BENCH", facility_overrides={"code": "F-1"}
        )
        home_id = context["facility"]["id"]
        other = fx.register_facility(api, code="F-2")
        booking = fx.book_collection(api, context["sire"]["id"], home_id)
        fx.advance_clock(api, fx.CLOCK_AT_COLLECTION)
        payload = factories.booking_complete_payload()

        validate_error(
            api.complete_booking(booking["id"], payload, make_facility_headers(other["id"])),
            ApiErrorId.ERR_FACILITY_SCOPE.value,
            403,
        )
        validate_error(
            api.cancel_booking(
                booking["id"],
                factories.booking_cancel_payload(),
                make_facility_headers(other["id"]),
            ),
            ApiErrorId.ERR_FACILITY_SCOPE.value,
            403,
        )
        validate_error(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"],
                    home_id,
                    "2026-09-14T08:00:00Z",
                    "2026-09-14T10:00:00Z",
                ),
                make_facility_headers(other["id"]),
            ),
            ApiErrorId.ERR_FACILITY_SCOPE.value,
            403,
        )
        assert fx.read_booking(api, booking["id"])["status"] == "SCHEDULED"

        completed = validate_success(
            api.complete_booking(booking["id"], payload, make_facility_headers(home_id)),
            200,
        )
        assert completed["status"] == "COMPLETED"

    def test_both_duty_barriers_read_the_operator_history(self, api):
        """Release is also the first segregation-of-duties barrier: the releasing
        `X-User-ID` must differ from the `evaluated_by_user_id` recorded on the lot's
        parent ejaculate, and the same individual attempting both roles is refused
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A veterinarian who resulted this
        bull's assays may not sign his paperwork, and the attempt is refused with
        `ERR_CERTIFIER_TESTED_SIRE` (HTTP 403).

        Design: Corner/errors/role_scope_and_duty_codes_are_forbidden
        """
        requirement = fx.register_country_requirement(
            api, country_code="CA", max_test_age_days=60, min_isolation_days=21
        )
        context = fx.quarantine_lot(
            api,
            registration_code="REG-DUTY",
            facility_overrides={"code": "F-DUTY", "approved_export_countries": ["CA"]},
            straw_count=100,
            processing_cost_cents=125000,
        )
        lot_id = context["lot"]["id"]
        assert context["ejaculate"]["evaluated_by_user_id"] is not None

        validate_error(
            api.release_straw_lot(lot_id, factories.lot_release_payload(), fx.TECH),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert fx.read_lot(api, lot_id)["distribution_status"] == "QUARANTINE"
        released = fx.release_lot(api, lot_id)
        assert released["distribution_status"] == "RELEASED"

        certificate = fx.submitted_certificate(
            api, context["sire"]["id"], lot_id, requirement["id"]
        )
        validate_error(
            api.issue_export_certificate(
                certificate["id"], factories.certificate_issue_payload(), fx.VET
            ),
            ApiErrorId.ERR_CERTIFIER_TESTED_SIRE.value,
            403,
        )
        assert fx.read_certificate(api, certificate["id"])["status"] == "SUBMITTED"
        issued = fx.issue_certificate(api, certificate["id"])
        assert issued["status"] == "ISSUED"


class TestIdentityUniquenessAndVersionCodes:
    """One 404 for every reference, one 409 per registry, two 412s for two pins."""

    def test_one_not_found_code_serves_paths_and_body_keys(self, api):
        """Path segments are resolved strictly left to right: if the parent id names
        no stored row, the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)
        without the child id ever being examined.

        Design: Corner/errors/identity_uniqueness_and_version_codes_are_rejected
        """
        context = fx.eligible_sire(
            api, registration_code="REG-REF", facility_overrides={"code": "F-REF"}
        )
        facility_id = context["facility"]["id"]
        missing = ApiErrorId.ERR_RESOURCE_NOT_FOUND.value

        # Path ids, across four different entity types.
        validate_error(api.get_sire(NON_EXISTENT_UUID, fx.DIRECTOR), missing, 404)
        validate_error(api.get_facility(NON_EXISTENT_UUID, fx.DIRECTOR), missing, 404)
        validate_error(
            api.get_country_requirement(NON_EXISTENT_UUID, fx.COORDINATOR), missing, 404
        )
        validate_error(api.get_straw_lot(NON_EXISTENT_UUID, fx.TECH), missing, 404)
        validate_error(
            api.order_health_test(
                NON_EXISTENT_UUID, factories.health_test_payload(facility_id), fx.VET
            ),
            missing,
            404,
        )

        # Body foreign keys, resolved after the path and before any business rule.
        validate_error(
            api.create_tank(
                factories.tank_payload(NON_EXISTENT_UUID, serial="TK-ORPHAN"), fx.DIRECTOR
            ),
            missing,
            404,
        )
        validate_error(
            api.create_booking(
                factories.booking_payload(NON_EXISTENT_UUID, facility_id),
                make_facility_headers(facility_id),
            ),
            missing,
            404,
        )
        _tanks, tank_meta = validate_paginated(api.list_tanks(fx.DIRECTOR))
        assert tank_meta["total_count"] == 0

    def test_each_natural_key_collision_answers_with_one_duplicate_code(self, api):
        """The registration code must be unique across every bull ever registered; a
        collision is refused with `ERR_DUPLICATE_CODE`.

        Design: Corner/errors/identity_uniqueness_and_version_codes_are_rejected
        """
        facility = fx.register_facility(api, code="F-DUP")
        sire = fx.register_sire(api, registration_code="REG-DUP")
        partner = fx.register_distributor(api, name="D-DUP")
        tank = fx.register_tank(api, partner["id"], serial="TK-DUP", capacity_straws=500)
        requirement = fx.register_country_requirement(api, country_code="CA")
        duplicate = ApiErrorId.ERR_DUPLICATE_CODE.value

        validate_error(
            api.create_facility(
                factories.facility_payload(code="F-DUP", country_code="CA"), fx.DIRECTOR
            ),
            duplicate,
            409,
        )
        validate_error(
            api.create_sire(
                factories.sire_payload(registration_code="REG-DUP", breed="JERSEY"),
                fx.DIRECTOR,
            ),
            duplicate,
            409,
        )
        validate_error(
            api.create_tank(
                factories.tank_payload(partner["id"], serial="TK-DUP", capacity_straws=99),
                fx.DIRECTOR,
            ),
            duplicate,
            409,
        )
        validate_error(
            api.create_country_requirement(
                factories.country_requirement_payload(
                    country_code="CA", max_test_age_days=10
                ),
                fx.COORDINATOR,
            ),
            duplicate,
            409,
        )

        # Not one of the four refusals overwrote the row that owns the key.
        assert fx.read_facility(api, facility["id"])["country_code"] == "US"
        assert fx.read_sire(api, sire["id"])["breed"] == "HOLSTEIN"
        assert fx.read_tank(api, tank["id"])["capacity_straws"] == 500
        held = validate_success(
            api.get_country_requirement(requirement["id"], fx.COORDINATOR), 200
        )
        assert held["max_test_age_days"] == 400

    def test_a_second_pending_assay_of_one_type_is_refused(self, api):
        """A bull may not carry two `PENDING` tests of the same `test_type` at once —
        the outstanding one must be resulted first, or the order is refused with
        `ERR_DUPLICATE_PENDING_TEST`.

        Design: Corner/errors/identity_uniqueness_and_version_codes_are_rejected
        """
        facility = fx.register_facility(api, code="F-PEND")
        sire = fx.register_sire(api, registration_code="REG-PEND")
        fx.contract_sire(api, sire["id"])
        fx.house_sire(api, sire["id"], facility["id"])
        pending = fx.order_health_test(api, sire["id"], facility["id"], test_type="IBR")
        assert pending["result"] == "PENDING"

        validate_error(
            api.order_health_test(
                sire["id"], factories.health_test_payload(facility["id"], "IBR"), fx.VET
            ),
            ApiErrorId.ERR_DUPLICATE_PENDING_TEST.value,
            409,
        )
        rows, meta = validate_paginated(
            api.list_health_tests(fx.VET, {"sire_id": sire["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == pending["id"]

        # A different type is orderable while that one is outstanding.
        other = fx.order_health_test(
            api, sire["id"], facility["id"], test_type="BLUETONGUE"
        )
        assert other["result"] == "PENDING"
        # And the type reopens once the outstanding row is resulted.
        fx.result_health_test(api, pending["id"], "NEGATIVE")
        again = fx.order_health_test(api, sire["id"], facility["id"], test_type="IBR")
        assert again["result"] == "PENDING"
        _all_rows, all_meta = validate_paginated(
            api.list_health_tests(fx.VET, {"sire_id": sire["id"]})
        )
        assert all_meta["total_count"] == 3

    def test_both_pins_are_precondition_only(self, api):
        """Fifth, version pinning. `expected_sire_version` and
        `expected_straw_lot_version` are compared after existence and uniqueness but
        **before any state precondition**, so a stale version on a request that is
        also illegal on state grounds still returns 412 rather than 409.

        Design: Corner/errors/identity_uniqueness_and_version_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-PIN",
            facility_overrides={"code": "F-PIN"},
            straw_count=100,
            processing_cost_cents=125000,
        )
        sire_id = context["sire"]["id"]
        lot_id = context["lot"]["id"]
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-PIN"},
            tank_overrides={"serial": "TK-PIN"},
        )
        sire_version = fx.read_sire(api, sire_id)["version"]
        lot_version = fx.read_lot(api, lot_id)["version"]

        validate_error(
            api.file_genomic_evaluation(
                sire_id,
                factories.genomic_evaluation_payload(sire_version - 1),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_STALE_SIRE_VERSION.value,
            412,
        )
        _drafts, draft_meta = validate_paginated(
            api.list_genomic_evaluations(fx.DIRECTOR, {"sire_id": sire_id})
        )
        assert draft_meta["total_count"] == 0

        validate_error(
            api.request_consignment_transfer(
                lot_id,
                factories.consignment_request_payload(
                    partner["distributor"]["id"], partner["tank"]["id"], lot_version - 1, 10
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_STALE_STRAW_LOT_VERSION.value,
            412,
        )
        assert_buckets(fx.read_lot(api, lot_id), 100, 0, 0, 0, 0)

        # Re-reading the parent and retrying the identical body succeeds.
        draft = validate_success(
            api.file_genomic_evaluation(
                sire_id, factories.genomic_evaluation_payload(sire_version), fx.DIRECTOR
            ),
            201,
        )
        assert draft["status"] == "DRAFT"
        transfer = validate_success(
            api.request_consignment_transfer(
                lot_id,
                factories.consignment_request_payload(
                    partner["distributor"]["id"], partner["tank"]["id"], lot_version, 10
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert transfer["status"] == "REQUESTED"


class TestSireFacilityAndBookingStateCodes:
    """Two dimensions, two codes; the site and the slot keep their own."""

    def test_the_acquisition_dimension_keeps_its_own_code(self, api):
        """Each of the three acquisition moves demands its own source state —
        contracting requires `PROSPECT`, housing requires `CONTRACTED`, retiring
        requires `RESIDENT` — so a repeated call fails on the second attempt with
        `ERR_SIRE_ACQUISITION_STATE`.

        Design: Corner/errors/sire_facility_and_booking_state_codes_are_rejected
        """
        facility = fx.register_facility(api, code="F-AQ")
        sire = fx.register_sire(api, registration_code="REG-PS")
        acquisition = ApiErrorId.ERR_SIRE_ACQUISITION_STATE.value

        validate_error(
            api.retire_sire(sire["id"], factories.retire_payload(), fx.DIRECTOR),
            acquisition,
            409,
        )
        validate_error(
            api.house_sire(
                sire["id"], factories.house_payload(facility["id"]), fx.DIRECTOR
            ),
            acquisition,
            409,
        )
        prospect = fx.read_sire(api, sire["id"])
        assert prospect["acquisition_status"] == "PROSPECT"
        assert prospect["collection_status"] == "NOT_HOUSED"
        assert prospect["version"] == 1
        assert prospect["housing_facility_id"] is None

        fx.contract_sire(api, sire["id"])
        validate_error(
            api.contract_sire(sire["id"], factories.contract_payload(700000), fx.DIRECTOR),
            acquisition,
            409,
        )
        contracted = fx.read_sire(api, sire["id"])
        assert contracted["acquisition_status"] == "CONTRACTED"
        assert contracted["contract_price_cents"] == 655000
        assert contracted["version"] == 2

    def test_the_collection_dimension_keeps_its_own_code(self, api):
        """Any move the dimension does not permit — clearance outside `ISOLATION`,
        suspension outside `ELIGIBLE`, reinstatement outside `SUSPENDED`, or any move
        out of `WITHDRAWN` — is refused with `ERR_SIRE_COLLECTION_STATE`.

        Design: Corner/errors/sire_facility_and_booking_state_codes_are_rejected
        """
        facility = fx.register_facility(api, code="F-CL")
        sire = fx.register_sire(api, registration_code="REG-CL")
        collection = ApiErrorId.ERR_SIRE_COLLECTION_STATE.value

        # NOT_HOUSED: neither clearance nor suspension nor reinstatement is legal.
        validate_error(
            api.clear_sire_for_collection(sire["id"], factories.clearance_payload(), fx.VET),
            collection,
            409,
        )
        validate_error(
            api.set_sire_collection_status(
                sire["id"], factories.collection_status_payload("SUSPENDED"), fx.VET
            ),
            collection,
            409,
        )
        validate_error(
            api.set_sire_collection_status(
                sire["id"], factories.collection_status_payload("ELIGIBLE"), fx.VET
            ),
            collection,
            409,
        )
        assert fx.read_sire(api, sire["id"])["collection_status"] == "NOT_HOUSED"

        # ISOLATION is not ELIGIBLE either, so the bench refuses the booking.
        fx.contract_sire(api, sire["id"])
        fx.house_sire(api, sire["id"], facility["id"])
        fx.grant_base_health_currency(api, sire["id"], facility["id"])
        validate_error(
            api.create_booking(
                factories.booking_payload(sire["id"], facility["id"]),
                make_facility_headers(facility["id"]),
            ),
            collection,
            409,
        )
        _rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_site_and_the_slot_keep_theirs(self, api):
        """The facility's `approval_status` must be `APPROVED`; a suspended facility
        can neither house a bull nor accept a new booking nor back an export
        submission, and each such attempt reports `ERR_FACILITY_SUSPENDED`.

        Design: Corner/errors/sire_facility_and_booking_state_codes_are_rejected
        """
        context = fx.eligible_sire(
            api, registration_code="REG-SITE", facility_overrides={"code": "F-OK"}
        )
        facility_id = context["facility"]["id"]
        booking = fx.book_collection(api, context["sire"]["id"], facility_id)
        fx.advance_clock(api, fx.CLOCK_AT_COLLECTION)
        completed = fx.complete_collection(api, booking["id"], facility_id)
        assert completed["status"] == "COMPLETED"
        booking_state = ApiErrorId.ERR_BOOKING_STATE.value

        # A booking that is no longer SCHEDULED accepts no further transition.
        validate_error(
            api.cancel_booking(
                booking["id"],
                factories.booking_cancel_payload(),
                make_facility_headers(facility_id),
            ),
            booking_state,
            409,
        )
        validate_error(
            api.complete_booking(
                booking["id"],
                factories.booking_complete_payload(),
                make_facility_headers(facility_id),
            ),
            booking_state,
            409,
        )
        held = fx.read_booking(api, booking["id"])
        assert held["status"] == "COMPLETED"
        assert held["cancel_reason"] is None
        assert_instant_equals(held["completed_at"], "2026-09-10T08:00:00.000Z")

        # A suspended site refuses both the newcomer and the next slot.
        suspended = fx.suspend_facility(api, facility_id)
        assert suspended["approval_status"] == "SUSPENDED"
        newcomer = fx.register_sire(api, registration_code="REG-LATE")
        fx.contract_sire(api, newcomer["id"])
        facility_suspended = ApiErrorId.ERR_FACILITY_SUSPENDED.value
        validate_error(
            api.house_sire(
                newcomer["id"], factories.house_payload(facility_id), fx.DIRECTOR
            ),
            facility_suspended,
            409,
        )
        # The suspension already dragged this site's own resident to SUSPENDED, and
        # PRD 3.4 checks the bull's collection status before the site's approval
        # status, so the booking has to come from a bull who is still ELIGIBLE.
        annexe = fx.eligible_sire(
            api,
            registration_code="REG-ANNEXE",
            facility_overrides={"code": "F-ANNEXE"},
            isolation_days=0,
            clearance_clock=None,
        )
        assert annexe["sire"]["collection_status"] == "ELIGIBLE"
        validate_error(
            api.create_booking(
                factories.booking_payload(
                    annexe["sire"]["id"],
                    facility_id,
                    "2026-09-20T08:00:00Z",
                    "2026-09-20T10:00:00Z",
                ),
                make_facility_headers(facility_id),
            ),
            facility_suspended,
            409,
        )
        assert fx.read_sire(api, newcomer["id"])["acquisition_status"] == "CONTRACTED"


class TestProductionChainStateCodes:
    """The lot answers two different questions with two different codes."""

    def test_the_ejaculate_gate_keeps_one_code(self, api):
        """Cutting a lot requires the parent ejaculate to be `ACCEPTED` — a
        `PENDING_QC` or `REJECTED` parent yields `ERR_EJACULATE_STATE`.

        Design: Corner/errors/production_chain_state_codes_are_rejected
        """
        context = fx.collected_ejaculate(
            api, registration_code="REG-EJ", facility_overrides={"code": "F-EJ"}
        )
        ejaculate_id = context["ejaculate"]["id"]
        ejaculate_state = ApiErrorId.ERR_EJACULATE_STATE.value

        validate_error(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 100, 50000),
                fx.TECH,
            ),
            ejaculate_state,
            409,
        )
        _rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 0

        accepted = fx.evaluate_qc(api, ejaculate_id)
        assert accepted["qc_status"] == "ACCEPTED"
        validate_error(
            api.evaluate_ejaculate_qc(
                ejaculate_id, factories.qc_evaluation_payload(), fx.TECH
            ),
            ejaculate_state,
            409,
        )
        assert fx.read_ejaculate(api, ejaculate_id)["qc_status"] == "ACCEPTED"
        lot = fx.cut_lot(api, ejaculate_id, straw_count=100, processing_cost_cents=50000)
        assert lot["distribution_status"] == "QUARANTINE"

    def test_the_lot_keeps_two_codes_for_two_questions(self, api):
        """`ERR_LOT_NOT_RELEASED`, evaluated **before** the tank-ownership rule so a
        request that is wrong on both counts reports the lot-state error.

        Design: Corner/errors/production_chain_state_codes_are_rejected
        """
        context = fx.accepted_ejaculate(
            api, registration_code="REG-LOT", facility_overrides={"code": "F-LOT"}
        )
        ejaculate_id = context["ejaculate"]["id"]
        quarantined = fx.cut_lot(
            api, ejaculate_id, straw_count=100, processing_cost_cents=125000
        )
        released = fx.release_lot(
            api,
            fx.cut_lot(api, ejaculate_id, straw_count=100, processing_cost_cents=125000)[
                "id"
            ],
        )
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-LOT"},
            tank_overrides={"serial": "TK-LOT"},
        )
        lot_state = ApiErrorId.ERR_LOT_STATE.value

        # The QC gate's own code, on a lot that has already passed it.
        validate_error(
            api.release_straw_lot(
                released["id"], factories.lot_release_payload(), fx.TECH_ALT
            ),
            lot_state,
            409,
        )
        validate_error(
            api.reject_straw_lot(released["id"], factories.lot_reject_payload(), fx.TECH),
            lot_state,
            409,
        )
        assert fx.read_lot(api, released["id"])["distribution_status"] == "RELEASED"

        # Distribution readiness is a different question and a different code.
        validate_error(
            api.request_consignment_transfer(
                quarantined["id"],
                factories.consignment_request_payload(
                    partner["distributor"]["id"],
                    partner["tank"]["id"],
                    quarantined["version"],
                    10,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_LOT_NOT_RELEASED.value,
            409,
        )
        transfer = fx.request_consignment(
            api,
            released["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=10,
        )
        assert transfer["status"] == "REQUESTED"

        # The quarantine lot still accepts exactly one verdict, once.
        condemned = fx.reject_lot(api, quarantined["id"])
        assert condemned["distribution_status"] == "REJECTED"
        validate_error(
            api.release_straw_lot(
                quarantined["id"], factories.lot_release_payload(), fx.TECH_ALT
            ),
            lot_state,
            409,
        )

    def test_the_evaluation_keeps_one_code_across_two_endpoints(self, api):
        """Publication is the director's `DRAFT → PUBLISHED` move, optionally
        annotated with a `publication_note`; the same operation reinstates a
        `SUPERSEDED` row, and an evaluation that is neither `DRAFT` nor `SUPERSEDED`
        reports `ERR_EVALUATION_STATE`.

        Design: Corner/errors/production_chain_state_codes_are_rejected
        """
        sire = fx.register_sire(api, registration_code="REG-EV")
        incumbent = fx.published_proof(api, sire["id"])
        candidate = fx.file_evaluation(
            api, sire["id"], effective_at="2026-09-01T00:00:00Z"
        )
        evaluation_state = ApiErrorId.ERR_EVALUATION_STATE.value

        validate_error(
            api.publish_genomic_evaluation(
                incumbent["id"], factories.publish_payload(), fx.DIRECTOR
            ),
            evaluation_state,
            409,
        )
        validate_error(
            api.rollback_genomic_evaluation(
                candidate["id"], factories.rollback_payload(), fx.DIRECTOR
            ),
            evaluation_state,
            409,
        )
        assert fx.read_evaluation(api, incumbent["id"])["status"] == "PUBLISHED"
        assert fx.read_evaluation(api, candidate["id"])["status"] == "DRAFT"

        # A withdrawn proof is terminal, so neither endpoint accepts it again.
        published = fx.publish_evaluation(api, candidate["id"])
        assert published["status"] == "PUBLISHED"
        assert fx.read_evaluation(api, incumbent["id"])["status"] == "SUPERSEDED"
        withdrawn = fx.rollback_evaluation(api, published["id"])
        assert withdrawn["status"] == "ROLLED_BACK"
        validate_error(
            api.publish_genomic_evaluation(
                published["id"], factories.publish_payload(), fx.DIRECTOR
            ),
            evaluation_state,
            409,
        )
        validate_error(
            api.rollback_genomic_evaluation(
                published["id"], factories.rollback_payload(), fx.DIRECTOR
            ),
            evaluation_state,
            409,
        )
        assert fx.read_evaluation(api, incumbent["id"])["status"] == "PUBLISHED"


class TestDistributionChainStateCodes:
    """Two long machines, one code each, plus a code from a derived field."""

    def test_the_certificate_collapses_its_wrong_state_refusals(self, api):
        """The certificate must be in `DRAFT` or in `REJECTED`; any other source
        state is `ERR_CERTIFICATE_STATE`.

        Design: Corner/errors/distribution_chain_state_codes_are_rejected
        """
        requirement = fx.register_country_requirement(
            api, country_code="CA", max_test_age_days=60, min_isolation_days=21
        )
        context = fx.released_lot(
            api,
            registration_code="REG-CD",
            facility_overrides={"code": "F-CD", "approved_export_countries": ["CA"]},
            straw_count=100,
            processing_cost_cents=125000,
        )
        draft = fx.draft_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )
        certificate_state = ApiErrorId.ERR_CERTIFICATE_STATE.value

        # Issue, reject and revoke all demand a state the draft has not reached.
        validate_error(
            api.issue_export_certificate(
                draft["id"], factories.certificate_issue_payload(), fx.VET_ALT
            ),
            certificate_state,
            409,
        )
        validate_error(
            api.reject_export_certificate(
                draft["id"], factories.certificate_reject_payload(), fx.VET
            ),
            certificate_state,
            409,
        )
        validate_error(
            api.revoke_export_certificate(
                draft["id"], factories.certificate_revoke_payload(), fx.DIRECTOR
            ),
            certificate_state,
            409,
        )
        held = fx.read_certificate(api, draft["id"])
        assert held["status"] == "DRAFT"
        assert held["submission_round"] == 0

        submitted = fx.submit_certificate(api, draft["id"])
        assert submitted["submission_round"] == 1
        validate_error(
            api.submit_export_certificate(
                draft["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            certificate_state,
            409,
        )
        issued = fx.issue_certificate(api, draft["id"])
        assert issued["status"] == "ISSUED"
        validate_error(
            api.issue_export_certificate(
                draft["id"], factories.certificate_issue_payload(), fx.VET_ALT
            ),
            certificate_state,
            409,
        )
        assert fx.read_certificate(api, draft["id"])["submission_round"] == 1

    def test_the_transfer_collapses_its_wrong_state_refusals(self, api):
        """Any transition attempted from the wrong source state — approving or
        rejecting outside `REQUESTED`, dispatching outside `APPROVED`, receiving
        outside `IN_TRANSIT`, or reporting usage or returning outside `RECEIVED` —
        reports `ERR_TRANSFER_STATE`.

        Design: Corner/errors/distribution_chain_state_codes_are_rejected
        """
        context = fx.received_consignment(
            api,
            stop_after="REQUESTED",
            doses=20,
            registration_code="REG-TS",
            facility_overrides={"code": "F-TS"},
            straw_count=100,
            processing_cost_cents=125000,
            distributor_overrides={"name": "D-TS"},
            tank_overrides={"serial": "TK-TS"},
        )
        transfer_id = context["transfer"]["id"]
        partner_headers = make_distributor_headers(context["distributor"]["id"])
        transfer_state = ApiErrorId.ERR_TRANSFER_STATE.value

        # REQUESTED accepts approval and rejection, nothing further downstream.
        validate_error(
            api.dispatch_consignment_transfer(
                transfer_id, factories.transfer_dispatch_payload(), fx.DIRECTOR
            ),
            transfer_state,
            409,
        )
        validate_error(
            api.receive_consignment_transfer(
                transfer_id, factories.transfer_receive_payload(), partner_headers
            ),
            transfer_state,
            409,
        )
        validate_error(
            api.report_consignment_usage(
                transfer_id, factories.report_usage_payload(20), partner_headers
            ),
            transfer_state,
            409,
        )
        validate_error(
            api.return_consignment_transfer(
                transfer_id, factories.transfer_return_payload(), partner_headers
            ),
            transfer_state,
            409,
        )
        assert fx.read_transfer(api, transfer_id)["status"] == "REQUESTED"

        approved = fx.approve_transfer(api, transfer_id)
        assert approved["status"] == "APPROVED"
        validate_error(
            api.approve_consignment_transfer(
                transfer_id, factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            transfer_state,
            409,
        )
        validate_error(
            api.reject_consignment_transfer(
                transfer_id, factories.transfer_reject_payload(), fx.DIRECTOR
            ),
            transfer_state,
            409,
        )

        fx.dispatch_transfer(api, transfer_id)
        validate_error(
            api.report_consignment_usage(
                transfer_id, factories.report_usage_payload(20), partner_headers
            ),
            transfer_state,
            409,
        )
        validate_error(
            api.return_consignment_transfer(
                transfer_id, factories.transfer_return_payload(), partner_headers
            ),
            transfer_state,
            409,
        )
        assert fx.read_transfer(api, transfer_id)["status"] == "IN_TRANSIT"

    def test_a_derived_out_of_service_tank_stalls_the_shipment(self, api):
        """The tank's `tank_status` must be `IN_SERVICE`; a `SERVICE_DUE` tank stalls
        the shipment until it is filled, and an `OUT_OF_SERVICE` tank reports
        `ERR_TANK_OUT_OF_SERVICE`.

        Design: Corner/errors/distribution_chain_state_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-TD",
            facility_overrides={"code": "F-TD"},
            straw_count=100,
            processing_cost_cents=125000,
        )
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-DEAD"},
            tank_overrides={"serial": "TK-DEAD", "initial_fill_pct": 40.0},
        )
        transfer = fx.request_consignment(
            api,
            context["lot"]["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=20,
        )
        fx.approve_transfer(api, transfer["id"])

        # Twenty whole days at 2.0 points a day take a 40.0 fill to exactly 0.
        sweep = fx.advance_clock(api, "2026-10-01T00:00:00Z")
        assert partner["tank"]["id"] in sweep["out_of_service_tank_ids"]
        dead = fx.read_tank(api, partner["tank"]["id"])
        assert dead["ln2_level_pct"] == pytest.approx(0.0, abs=0.01)
        assert dead["tank_status"] == "OUT_OF_SERVICE"

        validate_error(
            api.dispatch_consignment_transfer(
                transfer["id"], factories.transfer_dispatch_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_TANK_OUT_OF_SERVICE.value,
            409,
        )
        stalled = fx.read_transfer(api, transfer["id"])
        assert stalled["status"] == "APPROVED"
        assert stalled["tank_service_count_at_dispatch"] is None

        # Refilling closes the cycle from either direction.
        serviced = fx.service_tank(
            api, partner["tank"]["id"], 90.0, partner["distributor_headers"]
        )
        assert serviced["ln2_level_pct"] == pytest.approx(90.0, abs=0.01)
        assert serviced["tank_status"] == "IN_SERVICE"
        assert serviced["service_count"] == 1
        dispatched = fx.dispatch_transfer(api, transfer["id"])
        assert dispatched["status"] == "IN_TRANSIT"
        assert dispatched["tank_service_count_at_dispatch"] == 1


class TestHealthCurrencyAndQcGateCodes:
    """The 422 band where a barrier reads a date rather than a status."""

    ISOLATION_28_ENDS = "2026-08-29T00:00:00Z"

    def test_isolation_and_currency_are_two_separate_boundaries(self, api):
        """It has three preconditions: the bull's `collection_status` is `ISOLATION`,
        the logical clock has reached `isolation_ends_at` — the boundary is inclusive,
        so clearance exactly at that instant succeeds, and anything earlier is
        `ERR_ISOLATION_INCOMPLETE` — and his health is current across the four base
        assays, failing which the answer is `ERR_HEALTH_TESTS_NOT_CURRENT`.

        Design: Corner/errors/health_currency_and_qc_gate_codes_are_rejected
        """
        facility = fx.register_facility(api, code="F-ISO", housing_capacity=4)
        early = fx.register_sire(api, registration_code="REG-ISO")
        fx.contract_sire(api, early["id"])
        housed = fx.house_sire(api, early["id"], facility["id"], 28)
        assert_instant_equals(housed["isolation_ends_at"], self.ISOLATION_28_ENDS)
        fx.grant_base_health_currency(api, early["id"], facility["id"])

        # Currency is satisfied, so only the isolation clock can refuse.
        validate_error(
            api.clear_sire_for_collection(
                early["id"], factories.clearance_payload(), fx.VET
            ),
            ApiErrorId.ERR_ISOLATION_INCOMPLETE.value,
            422,
        )
        assert fx.read_sire(api, early["id"])["collection_status"] == "ISOLATION"

        lapsing = fx.register_sire(api, registration_code="REG-LAPSE")
        fx.contract_sire(api, lapsing["id"])
        fx.house_sire(api, lapsing["id"], facility["id"], 28)
        short_assays = fx.grant_base_health_currency(
            api, lapsing["id"], facility["id"], validity_days=28
        )
        assert_instant_equals(
            short_assays["IBR"]["valid_until"], self.ISOLATION_28_ENDS
        )

        # At the shared boundary isolation is served but currency has lapsed.
        fx.advance_clock(api, self.ISOLATION_28_ENDS)
        cleared = validate_success(
            api.clear_sire_for_collection(
                early["id"], factories.clearance_payload(), fx.VET
            ),
            200,
        )
        assert cleared["collection_status"] == "ELIGIBLE"
        assert cleared["suspension_reason"] is None
        validate_error(
            api.clear_sire_for_collection(
                lapsing["id"], factories.clearance_payload(), fx.VET
            ),
            ApiErrorId.ERR_HEALTH_TESTS_NOT_CURRENT.value,
            422,
        )
        stuck = fx.read_sire(api, lapsing["id"])
        assert stuck["collection_status"] == "ISOLATION"
        assert fx.read_health_test(api, short_assays["IBR"]["id"])["result"] == "EXPIRED"

    def test_a_stale_sample_date_blocks_the_signature(self, api):
        """Then, for every `test_type` in the destination's `required_test_types`,
        there must exist a `HealthTest` for the certificate's `sire_id` of that type
        whose `result` is `NEGATIVE`, whose `valid_until` is strictly later than the
        logical clock, and whose age — the logical clock minus its `sample_date` — is
        no greater than the destination's `max_test_age_days` multiplied by 86400
        seconds.

        Design: Corner/errors/health_currency_and_qc_gate_codes_are_rejected
        """
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR"],
            max_test_age_days=30,
            min_isolation_days=21,
        )
        context = fx.released_lot(
            api,
            registration_code="REG-AGE",
            facility_overrides={"code": "F-AGE", "approved_export_countries": ["CA"]},
            straw_count=100,
            processing_cost_cents=125000,
        )
        certificate = fx.submitted_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )

        # The base assays are current but were sampled forty days before signing.
        validate_error(
            api.issue_export_certificate(
                certificate["id"], factories.certificate_issue_payload(), fx.VET_ALT
            ),
            ApiErrorId.ERR_COUNTRY_TEST_MISSING.value,
            422,
        )
        held = fx.read_certificate(api, certificate["id"])
        assert held["status"] == "SUBMITTED"
        assert held["issued_at"] is None
        assert held["expires_at"] is None

        fresh = fx.negative_test(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            "IBR",
            sample_date="2026-09-10",
            validity_days=365,
        )
        assert_instant_equals(fresh["valid_until"], "2027-09-10T00:00:00Z")
        issued = fx.issue_certificate(api, certificate["id"])
        assert issued["status"] == "ISSUED"
        assert_instant_equals(issued["expires_at"], "2027-09-10T00:00:00Z")

    def test_the_quality_thresholds_refuse_rather_than_downgrade(self, api):
        """An `ACCEPTED` verdict, however, is only permitted when
        `post_thaw_motility_pct` is at least 35.0 and `morphology_normal_pct` is at
        least 70.0; a verdict of `ACCEPTED` accompanied by sub-threshold figures is
        refused outright with `ERR_QC_BELOW_THRESHOLD` rather than silently
        downgraded to a rejection.

        Design: Corner/errors/health_currency_and_qc_gate_codes_are_rejected
        """
        context = fx.collected_ejaculate(
            api, registration_code="REG-QC", facility_overrides={"code": "F-QC"}
        )
        weak_id = context["ejaculate"]["id"]
        below = ApiErrorId.ERR_QC_BELOW_THRESHOLD.value

        # Each measurement fails on its own account.
        validate_error(
            api.evaluate_ejaculate_qc(
                weak_id, factories.qc_evaluation_payload("ACCEPTED", 34.9, 70.0), fx.TECH
            ),
            below,
            422,
        )
        validate_error(
            api.evaluate_ejaculate_qc(
                weak_id, factories.qc_evaluation_payload("ACCEPTED", 35.0, 69.9), fx.TECH
            ),
            below,
            422,
        )
        untouched = fx.read_ejaculate(api, weak_id)
        assert untouched["qc_status"] == "PENDING_QC"
        assert untouched["evaluated_by_user_id"] is None
        assert untouched["qc_decided_at"] is None

        # A rejection carries no threshold at all.
        rejected = fx.evaluate_qc(api, weak_id, "REJECTED", 34.9, 69.9)
        assert rejected["qc_status"] == "REJECTED"
        assert rejected["post_thaw_motility_pct"] == pytest.approx(34.9, abs=0.01)

        # Both boundaries are inclusive on a second collection.
        second_start = "2026-09-12T10:00:00Z"
        booking = fx.book_collection(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            second_start,
            "2026-09-12T12:00:00Z",
        )
        fx.advance_clock(api, second_start)
        fx.complete_collection(api, booking["id"], context["facility"]["id"])
        borderline = fx.discover_ejaculate(api, booking["id"])
        accepted = fx.evaluate_qc(api, borderline["id"], "ACCEPTED", 35.0, 70.0)
        assert accepted["qc_status"] == "ACCEPTED"

    def test_the_assay_order_reads_two_dates_of_its_own(self, api):
        """That target must belong to the same bull, be of the same `test_type`, and
        carry a `result` of either `POSITIVE` or `INCONCLUSIVE`; anything else —
        another bull's test, another type, or a test that is still `PENDING`,
        `NEGATIVE` or `EXPIRED` — is rejected with `ERR_INVALID_RETEST_TARGET`.

        Design: Corner/errors/health_currency_and_qc_gate_codes_are_rejected
        """
        facility = fx.register_facility(api, code="F-ORD")
        sire = fx.register_sire(api, registration_code="REG-ORD")
        settled = fx.negative_test(api, sire["id"], facility["id"], "IBR")
        assert settled["result"] == "NEGATIVE"

        validate_error(
            api.order_health_test(
                sire["id"],
                factories.health_test_payload(
                    facility["id"],
                    "IBR",
                    fx.BASE_SAMPLE_DATE,
                    365,
                    retest_of_test_id=settled["id"],
                ),
                fx.VET,
            ),
            ApiErrorId.ERR_INVALID_RETEST_TARGET.value,
            422,
        )

        # The clock stands at the start of the epoch, so tomorrow is the future.
        validate_error(
            api.order_health_test(
                sire["id"],
                factories.health_test_payload(facility["id"], "EBL", "2026-08-02", 365),
                fx.VET,
            ),
            ApiErrorId.ERR_SAMPLE_DATE_FUTURE.value,
            422,
        )
        sampled_today = validate_success(
            api.order_health_test(
                sire["id"],
                factories.health_test_payload(facility["id"], "EBL", "2026-08-01", 365),
                fx.VET,
            ),
            201,
        )
        assert sampled_today["result"] == "PENDING"
        assert sampled_today["valid_until"] is None


class TestCrossReferenceCoherenceCodes:
    """Codes about a relationship between two rows that each exist on their own."""

    def test_a_fabricated_site_is_absent_while_a_real_one_is_merely_wrong(self, api):
        """He must actually live there — his `housing_facility_id` must equal the
        booking's `facility_id` — or `ERR_SIRE_NOT_AT_FACILITY`, and that referential
        check is evaluated *before* the rest-buffer rule, so a booking that is at the
        wrong site and inside the rest window reports the wrong-site error.

        Design: Corner/errors/cross_reference_coherence_codes_are_rejected
        """
        context = fx.eligible_sire(
            api, registration_code="REG-XR", facility_overrides={"code": "F-H"}
        )
        sire_id = context["sire"]["id"]
        elsewhere = fx.register_facility(api, code="F-OTHER")

        # Existence precedes coherence: an unknown facility is a 404, not a 422.
        validate_error(
            api.create_booking(
                factories.booking_payload(sire_id, NON_EXISTENT_UUID),
                make_facility_headers(NON_EXISTENT_UUID),
            ),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_booking(
                factories.booking_payload(sire_id, elsewhere["id"]),
                make_facility_headers(elsewhere["id"]),
            ),
            ApiErrorId.ERR_SIRE_NOT_AT_FACILITY.value,
            422,
        )
        _rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire_id})
        )
        assert meta["total_count"] == 0

        booked = fx.book_collection(api, sire_id, context["facility"]["id"])
        assert booked["status"] == "SCHEDULED"
        assert fx.read_sire(api, sire_id)["housing_facility_id"] == context["facility"]["id"]

    def test_a_tank_belonging_to_another_partner_is_refused(self, api):
        """The `tank_id` must belong to the named `distributor_id`, or the request is
        refused with `ERR_TANK_NOT_OWNED_BY_DISTRIBUTOR`.

        Design: Corner/errors/cross_reference_coherence_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-TN",
            facility_overrides={"code": "F-TN"},
            straw_count=100,
            processing_cost_cents=125000,
        )
        lot = context["lot"]
        first = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-1"},
            tank_overrides={"serial": "TK-1"},
        )
        second = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-2"},
            tank_overrides={"serial": "TK-2"},
        )

        validate_error(
            api.request_consignment_transfer(
                lot["id"],
                factories.consignment_request_payload(
                    first["distributor"]["id"], second["tank"]["id"], lot["version"], 10
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_TANK_NOT_OWNED_BY_DISTRIBUTOR.value,
            422,
        )
        assert_buckets(fx.read_lot(api, lot["id"]), 100, 0, 0, 0, 0)

        owned = fx.request_consignment(
            api, lot["id"], first["distributor"]["id"], first["tank"]["id"], doses=10
        )
        assert owned["status"] == "REQUESTED"

    def test_a_certificate_must_cover_this_bull_and_this_lot(self, api):
        """The lot and the bull must agree: the lot named by `straw_lot_id` must have
        the same `sire_id` as the certificate, or the draft is refused with
        `ERR_LOT_SIRE_MISMATCH`.

        Design: Corner/errors/cross_reference_coherence_codes_are_rejected
        """
        requirement = fx.register_country_requirement(
            api, country_code="CA", max_test_age_days=60, min_isolation_days=21
        )
        context = fx.released_lot(
            api,
            registration_code="REG-XR",
            facility_overrides={"code": "F-XR", "approved_export_countries": ["CA"]},
            straw_count=100,
            processing_cost_cents=125000,
        )
        sire_id = context["sire"]["id"]
        shipped = context["lot"]
        sibling = fx.release_lot(
            api,
            fx.cut_lot(
                api,
                context["ejaculate"]["id"],
                straw_count=100,
                processing_cost_cents=125000,
            )["id"],
        )
        stranger = fx.register_sire(api, registration_code="REG-YR")
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-CA", "country_code": "CA"},
            tank_overrides={"serial": "TK-CA"},
        )
        not_applicable = ApiErrorId.ERR_CERTIFICATE_NOT_APPLICABLE.value

        # A document about another bull cannot be drafted against this lot at all.
        validate_error(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    stranger["id"], shipped["id"], requirement["id"]
                ),
                fx.COORDINATOR,
            ),
            ApiErrorId.ERR_LOT_SIRE_MISMATCH.value,
            422,
        )

        # The cited document is checked on three counts: status, lot and presence.
        wrong_lot = fx.draft_certificate(api, sire_id, sibling["id"], requirement["id"])
        version = fx.read_lot(api, shipped["id"])["version"]
        for payload in (
            factories.consignment_request_payload(
                partner["distributor"]["id"],
                partner["tank"]["id"],
                version,
                10,
                export_certificate_id=wrong_lot["id"],
            ),
            factories.consignment_request_payload(
                partner["distributor"]["id"], partner["tank"]["id"], version, 10
            ),
        ):
            validate_error(
                api.request_consignment_transfer(shipped["id"], payload, fx.DIRECTOR),
                not_applicable,
                422,
            )
        fx.submit_certificate(api, wrong_lot["id"])
        assert fx.issue_certificate(api, wrong_lot["id"])["status"] == "ISSUED"
        validate_error(
            api.request_consignment_transfer(
                shipped["id"],
                factories.consignment_request_payload(
                    partner["distributor"]["id"],
                    partner["tank"]["id"],
                    version,
                    10,
                    export_certificate_id=wrong_lot["id"],
                ),
                fx.DIRECTOR,
            ),
            not_applicable,
            422,
        )
        _rows, meta = validate_paginated(
            api.list_consignment_transfers(fx.DIRECTOR, {"straw_lot_id": shipped["id"]})
        )
        assert meta["total_count"] == 0

        covered = fx.draft_certificate(api, sire_id, shipped["id"], requirement["id"])
        fx.submit_certificate(api, covered["id"])
        fx.issue_certificate(api, covered["id"])
        matched = fx.request_consignment(
            api,
            shipped["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=10,
            export_certificate_id=covered["id"],
        )
        fx.approve_transfer(api, matched["id"])
        assert fx.dispatch_transfer(api, matched["id"])["status"] == "IN_TRANSIT"

    def test_an_edge_that_would_close_a_loop_is_refused(self, api):
        """Neither `sire_id` nor `dam_sire_id` may equal the bull's own `id`, and no
        edge may close a cycle in the pedigree graph; either fault is refused with
        `ERR_PEDIGREE_CYCLE`.

        Design: Corner/errors/cross_reference_coherence_codes_are_rejected
        """
        root = fx.register_sire(api, registration_code="REG-P1")
        middle = fx.register_sire(api, registration_code="REG-P2", sire_id=root["id"])
        leaf = fx.register_sire(api, registration_code="REG-P3", sire_id=middle["id"])
        assert leaf["pedigree_depth"] == 2
        cycle = ApiErrorId.ERR_PEDIGREE_CYCLE.value

        validate_error(
            api.amend_sire_pedigree(
                root["id"], factories.pedigree_payload(sire_id=leaf["id"]), fx.DIRECTOR
            ),
            cycle,
            422,
        )
        validate_error(
            api.amend_sire_pedigree(
                root["id"], factories.pedigree_payload(sire_id=root["id"]), fx.DIRECTOR
            ),
            cycle,
            422,
        )
        validate_error(
            api.amend_sire_pedigree(
                root["id"],
                factories.pedigree_payload(dam_sire_id=root["id"]),
                fx.DIRECTOR,
            ),
            cycle,
            422,
        )
        untouched = fx.read_sire(api, root["id"])
        assert untouched["sire_id"] is None
        assert untouched["dam_sire_id"] is None
        assert untouched["pedigree_depth"] == 0
        assert untouched["version"] == 1

        # An edge that opens no loop is ordinary registry work.
        amended = validate_success(
            api.amend_sire_pedigree(
                leaf["id"], factories.pedigree_payload(sire_id=root["id"]), fx.DIRECTOR
            ),
            200,
        )
        assert amended["sire_id"] == root["id"]
        assert amended["pedigree_depth"] == 1
        assert amended["version"] == 2


def _also_eligible_at(api, facility_id: str, registration_code: str):
    """A second bull cleared at the current clock, his isolation served on arrival."""
    bull = fx.register_sire(api, registration_code=registration_code)
    fx.contract_sire(api, bull["id"])
    fx.house_sire(api, bull["id"], facility_id, 0)
    fx.grant_base_health_currency(api, bull["id"], facility_id)
    return validate_success(
        api.clear_sire_for_collection(bull["id"], factories.clearance_payload(), fx.VET),
        200,
    )


class TestTemporalWindowAndClockCodes:
    """Four codes reading the same logical clock from four different sides."""

    HOLD = "2026-09-01T00:00:00Z"

    def test_the_clock_refuses_its_own_current_value(self, api):
        """A new value must be strictly later than the stored one; an equal or
        earlier value is refused with `ERR_CLOCK_REWIND` (HTTP 422).

        Design: Corner/errors/temporal_window_and_clock_codes_are_rejected
        """
        fx.advance_clock(api, self.HOLD)
        rewind = ApiErrorId.ERR_CLOCK_REWIND.value

        validate_error(api.set_clock(self.HOLD, fx.DIRECTOR), rewind, 422)
        validate_error(api.set_clock("2026-08-31T23:59:59Z", fx.DIRECTOR), rewind, 422)

        # One second of forward motion is motion enough.
        moved = validate_success(api.set_clock("2026-09-01T00:00:01Z", fx.DIRECTOR), 200)
        assert_instant_equals(moved["current_utc"], "2026-09-01T00:00:01Z")

    def test_a_malformed_or_backdated_window_is_refused(self, api):
        """The window itself must be well-formed and future-dated, with `start_at`
        strictly before `end_at` and `start_at` at or after the logical clock, or
        `ERR_INVALID_WINDOW`.

        Design: Corner/errors/temporal_window_and_clock_codes_are_rejected
        """
        context = fx.eligible_sire(
            api, registration_code="REG-TW", facility_overrides={"code": "F-TW"}
        )
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        headers = context["facility_headers"]
        invalid = ApiErrorId.ERR_INVALID_WINDOW.value

        for start_at, end_at in (
            ("2026-09-12T10:00:00Z", "2026-09-12T08:00:00Z"),
            ("2026-09-12T08:00:00Z", "2026-09-12T08:00:00Z"),
            ("2026-08-30T08:00:00Z", "2026-08-30T10:00:00Z"),
        ):
            validate_error(
                api.create_booking(
                    factories.booking_payload(sire_id, facility_id, start_at, end_at),
                    headers,
                ),
                invalid,
                422,
            )
        _rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire_id})
        )
        assert meta["total_count"] == 0

        wellformed = fx.book_collection(
            api, sire_id, facility_id, "2026-09-12T08:00:00Z", "2026-09-12T10:00:00Z"
        )
        assert wellformed["status"] == "SCHEDULED"

    def test_completion_before_the_window_opens_is_refused(self, api):
        """Completion is refused before the window opens: the logical clock must have
        reached `start_at`, or the answer is `ERR_BOOKING_NOT_STARTED`.

        Design: Corner/errors/temporal_window_and_clock_codes_are_rejected
        """
        context = fx.eligible_sire(
            api, registration_code="REG-NS", facility_overrides={"code": "F-NS"}
        )
        facility_id = context["facility"]["id"]
        booking = fx.book_collection(api, context["sire"]["id"], facility_id)

        validate_error(
            api.complete_booking(
                booking["id"],
                factories.booking_complete_payload(),
                context["facility_headers"],
            ),
            ApiErrorId.ERR_BOOKING_NOT_STARTED.value,
            422,
        )
        waiting = fx.read_booking(api, booking["id"])
        assert waiting["status"] == "SCHEDULED"
        assert waiting["completed_at"] is None

        fx.advance_clock(api, fx.BOOKING_START)
        completed = fx.complete_collection(api, booking["id"], facility_id)
        assert completed["status"] == "COMPLETED"
        assert_instant_equals(completed["completed_at"], fx.BOOKING_START)

    def test_the_rest_buffer_is_closed_on_both_sides_and_per_bull(self, api):
        """A new window's `start_at` must be at least 48 hours after the `end_at` of
        the bull's most recent `SCHEDULED` or `COMPLETED` booking, and at least 48
        hours before the `start_at` of his next one. Both boundaries are closed, so a
        gap of exactly 48 hours is permitted; anything tighter is
        `ERR_SIRE_REST_BUFFER`.

        Design: Corner/errors/temporal_window_and_clock_codes_are_rejected
        """
        context = fx.eligible_sire(
            api, registration_code="REG-RB", facility_overrides={"code": "F-RB"}
        )
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        headers = context["facility_headers"]
        anchor = fx.book_collection(api, sire_id, facility_id)
        buffer_code = ApiErrorId.ERR_SIRE_REST_BUFFER.value

        # Forty-seven hours after the anchor's end, and forty-seven before its start.
        for start_at, end_at in (
            ("2026-09-12T09:00:00Z", "2026-09-12T11:00:00Z"),
            ("2026-09-08T09:00:00Z", "2026-09-08T11:00:00Z"),
        ):
            validate_error(
                api.create_booking(
                    factories.booking_payload(sire_id, facility_id, start_at, end_at),
                    headers,
                ),
                buffer_code,
                422,
            )
        _rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire_id})
        )
        assert meta["total_count"] == 1

        # Exactly forty-eight hours clear on either side is permitted.
        earlier = fx.book_collection(
            api, sire_id, facility_id, "2026-09-08T08:00:00Z", "2026-09-08T10:00:00Z"
        )
        later = fx.book_collection(
            api, sire_id, facility_id, "2026-09-12T10:00:00Z", "2026-09-12T12:00:00Z"
        )
        assert earlier["status"] == "SCHEDULED"
        assert later["status"] == "SCHEDULED"

        # The buffer belongs to the animal, so a stablemate may take the same slot.
        stablemate = _also_eligible_at(api, facility_id, "REG-RB2")
        shared = fx.book_collection(api, stablemate["id"], facility_id)
        assert_instant_equals(shared["start_at"], anchor["start_at"])
        assert shared["status"] == "SCHEDULED"


class TestCapacityAndQuantityCodes:
    """Five aggregate limits over five populations, each inclusive of its limit."""

    def test_the_newcomer_is_the_one_who_breaks_the_housing_cap(self, api):
        """And the facility must have room: housing may not push `resident_sire_count`
        above the facility's `housing_capacity`. Every resident already there is
        individually legal — it is the newcomer that breaks the cap — and the refusal
        is `ERR_FACILITY_AT_CAPACITY`.

        Design: Corner/errors/capacity_and_quantity_codes_are_rejected
        """
        cramped = fx.register_facility(api, code="F-FULL", housing_capacity=1)
        roomier = fx.register_facility(api, code="F-ROOM", housing_capacity=2)
        resident = fx.register_sire(api, registration_code="REG-F1")
        fx.contract_sire(api, resident["id"])
        fx.house_sire(api, resident["id"], cramped["id"])
        newcomer = fx.register_sire(api, registration_code="REG-F2")
        fx.contract_sire(api, newcomer["id"])

        validate_error(
            api.house_sire(
                newcomer["id"], factories.house_payload(cramped["id"]), fx.DIRECTOR
            ),
            ApiErrorId.ERR_FACILITY_AT_CAPACITY.value,
            422,
        )
        assert fx.read_facility(api, cramped["id"])["resident_sire_count"] == 1
        waiting = fx.read_sire(api, newcomer["id"])
        assert waiting["acquisition_status"] == "CONTRACTED"
        assert waiting["collection_status"] == "NOT_HOUSED"
        assert waiting["housing_facility_id"] is None

        # The identical call lands wherever the cap has room for one more.
        housed = fx.house_sire(api, newcomer["id"], roomier["id"])
        assert housed["housing_facility_id"] == roomier["id"]
        assert fx.read_facility(api, roomier["id"])["resident_sire_count"] == 1

    def test_overlap_fills_the_bench_while_adjacency_does_not(self, api):
        """Adjacency is explicitly not overlap: a previous booking whose `end_at`
        equals the new `start_at` does not count.

        Design: Corner/errors/capacity_and_quantity_codes_are_rejected
        """
        context = fx.eligible_sire(
            api,
            registration_code="REG-B1",
            facility_overrides={
                "code": "F-BENCH",
                "housing_capacity": 4,
                "bench_capacity": 1,
            },
        )
        facility_id = context["facility"]["id"]
        headers = context["facility_headers"]
        fx.book_collection(api, context["sire"]["id"], facility_id)
        stablemate = _also_eligible_at(api, facility_id, "REG-B2")

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    stablemate["id"],
                    facility_id,
                    "2026-09-10T09:00:00Z",
                    "2026-09-10T11:00:00Z",
                ),
                headers,
            ),
            ApiErrorId.ERR_BENCH_CAPACITY_EXCEEDED.value,
            422,
        )
        adjacent = fx.book_collection(
            api,
            stablemate["id"],
            facility_id,
            "2026-09-10T10:00:00Z",
            "2026-09-10T12:00:00Z",
        )
        assert adjacent["status"] == "SCHEDULED"
        _rows, meta = validate_paginated(
            api.list_bookings(headers, {"facility_id": facility_id})
        )
        assert meta["total_count"] == 2

    def test_the_dose_ceiling_is_aggregate_across_the_ejaculates_lots(self, api):
        """The dose ceiling is aggregate, not per-lot: the sum of `straw_count` across
        every lot already cut from this ejaculate, including the row being created,
        must not exceed the ejaculate's `total_doses_theoretical`, or the request is
        refused with `ERR_DOSE_CAP_EXCEEDED`.

        Design: Corner/errors/capacity_and_quantity_codes_are_rejected
        """
        context = fx.accepted_ejaculate(
            api, registration_code="REG-CAP", facility_overrides={"code": "F-CAP"}
        )
        ejaculate_id = context["ejaculate"]["id"]
        assert context["ejaculate"]["total_doses_theoretical"] == (
            expected_theoretical_doses(6.0, 1200)
        )
        first = fx.cut_lot(
            api, ejaculate_id, straw_count=400, processing_cost_cents=400000
        )
        assert first["straw_count"] == 400

        validate_error(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 81, 80000),
                fx.TECH,
            ),
            ApiErrorId.ERR_DOSE_CAP_EXCEEDED.value,
            422,
        )
        _rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 1

        # Eighty straws land exactly on the ceiling of 480.
        second = fx.cut_lot(
            api, ejaculate_id, straw_count=80, processing_cost_cents=80000
        )
        assert second["straw_count"] == 80

    def test_the_dose_ledger_refuses_both_over_draw_and_short_settlement(self, api):
        """The two figures must account for the whole consignment: `doses_used` plus
        `doses_returned` must equal the transfer's `doses`, and a sum that exceeds or
        falls short of that total is refused with `ERR_INSUFFICIENT_DOSES`.

        Design: Corner/errors/capacity_and_quantity_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-DS",
            facility_overrides={"code": "F-DS"},
            straw_count=50,
            processing_cost_cents=75000,
        )
        lot = context["lot"]
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-DS"},
            tank_overrides={"serial": "TK-DS"},
        )
        insufficient = ApiErrorId.ERR_INSUFFICIENT_DOSES.value

        validate_error(
            api.request_consignment_transfer(
                lot["id"],
                factories.consignment_request_payload(
                    partner["distributor"]["id"],
                    partner["tank"]["id"],
                    lot["version"],
                    51,
                ),
                fx.DIRECTOR,
            ),
            insufficient,
            422,
        )
        assert_buckets(fx.read_lot(api, lot["id"]), 50, 0, 0, 0, 0)

        context.update(partner)
        transfer = fx.received_consignment(api, context, doses=50)["transfer"]
        for payload in (
            factories.report_usage_payload(49),
            factories.report_usage_payload(50, doses_returned=1),
        ):
            validate_error(
                api.report_consignment_usage(
                    transfer["id"], payload, partner["distributor_headers"]
                ),
                insufficient,
                422,
            )
        assert fx.read_transfer(api, transfer["id"])["status"] == "RECEIVED"

        reconciled = fx.report_usage(
            api, transfer["id"], partner["distributor"]["id"], 30, doses_returned=20
        )
        assert reconciled["status"] == "RECONCILED"
        assert_buckets(fx.read_lot(api, lot["id"]), 20, 0, 0, 30, 0)

    def test_the_tank_is_measured_again_when_the_doses_actually_move(self, api):
        """Dispatch snapshots `tank_service_count_at_dispatch` from the tank's current
        `service_count` — the baseline for the eventual service fee — re-derives the
        tank's `straws_on_hand`, since the doses now count against tank capacity, and
        re-checks that capacity, reporting `ERR_TANK_CAPACITY_EXCEEDED` if the tank
        would be overfilled.

        Design: Corner/errors/capacity_and_quantity_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-TC",
            facility_overrides={"code": "F-TC"},
            straw_count=200,
            processing_cost_cents=250000,
        )
        lot = context["lot"]
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-TC"},
            tank_overrides={"serial": "TK-CAP", "capacity_straws": 60},
        )
        overfilled = ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED.value

        # Sixty-one straws never fit, and approval says so first.
        greedy = fx.request_consignment(
            api,
            lot["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=61,
        )
        validate_error(
            api.approve_consignment_transfer(
                greedy["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            overfilled,
            422,
        )
        assert fx.read_transfer(api, greedy["id"])["status"] == "REQUESTED"

        # Two forty-dose shipments each clear approval against an empty tank.
        first = fx.request_consignment(
            api, lot["id"], partner["distributor"]["id"], partner["tank"]["id"], doses=40
        )
        fx.approve_transfer(api, first["id"])
        second = fx.request_consignment(
            api, lot["id"], partner["distributor"]["id"], partner["tank"]["id"], doses=40
        )
        fx.approve_transfer(api, second["id"])
        assert fx.read_tank(api, partner["tank"]["id"])["straws_on_hand"] == 0

        dispatched = fx.dispatch_transfer(api, first["id"])
        assert dispatched["tank_service_count_at_dispatch"] == 0
        assert fx.read_tank(api, partner["tank"]["id"])["straws_on_hand"] == 40
        validate_error(
            api.dispatch_consignment_transfer(
                second["id"], factories.transfer_dispatch_payload(), fx.DIRECTOR
            ),
            overfilled,
            422,
        )
        stalled = fx.read_transfer(api, second["id"])
        assert stalled["status"] == "APPROVED"
        assert stalled["tank_service_count_at_dispatch"] is None
        assert_buckets(fx.read_lot(api, lot["id"]), 120, 80, 0, 0, 0)


class TestExportEligibilityCodes:
    """The product line is policed twice, by two codes, at two different times."""

    def test_the_purity_field_is_conditional_on_the_product_line(self, api):
        """Sorted-sperm purity is conditional on the product line: a `SEXED` lot must
        supply `sexing_purity_pct` within 50.0 to 99.9, while a `CONVENTIONAL` or
        `EMBRYO` lot must omit it entirely — a value supplied on a non-sexed lot is an
        error rather than an ignored key, and either fault reports
        `ERR_PRODUCT_LINE_FIELDS`.

        Design: Corner/errors/export_eligibility_codes_are_rejected
        """
        context = fx.accepted_ejaculate(
            api, registration_code="REG-PL", facility_overrides={"code": "F-PL"}
        )
        ejaculate_id = context["ejaculate"]["id"]
        fields = ApiErrorId.ERR_PRODUCT_LINE_FIELDS.value

        for payload in (
            factories.straw_lot_payload("SEXED", 100, 60000),
            factories.straw_lot_payload("SEXED", 100, 60000, sexing_purity_pct=49.9),
            factories.straw_lot_payload(
                "CONVENTIONAL", 100, 60000, sexing_purity_pct=90.0
            ),
            factories.straw_lot_payload("EMBRYO", 100, 60000, sexing_purity_pct=90.0),
        ):
            validate_error(api.cut_straw_lot(ejaculate_id, payload, fx.TECH), fields, 422)
        _rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 0

        sorted_lot = fx.cut_lot(
            api,
            ejaculate_id,
            "SEXED",
            100,
            60000,
            sexing_purity_pct=90.0,
        )
        assert sorted_lot["sexing_purity_pct"] == pytest.approx(90.0, abs=0.01)
        plain = fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 100, 60000)
        assert plain["sexing_purity_pct"] is None

    def test_submission_enforces_the_destinations_whole_rule_set(self, api):
        """Submitting the certificate to the destination authority, optionally
        annotated with a `submission_note`, is where the destination's whole rule set
        is enforced at once.

        Design: Corner/errors/export_eligibility_codes_are_rejected
        """
        unapproved = fx.register_country_requirement(
            api, country_code="AU", max_test_age_days=60, min_isolation_days=21
        )
        strict = fx.register_country_requirement(
            api,
            country_code="CA",
            max_test_age_days=60,
            min_isolation_days=30,
            sexed_semen_allowed=False,
            embryo_allowed=True,
        )
        lenient = fx.register_country_requirement(
            api, country_code="MX", max_test_age_days=60, min_isolation_days=21
        )
        context = fx.accepted_ejaculate(
            api,
            registration_code="REG-EX",
            facility_overrides={
                "code": "F-CA",
                "approved_export_countries": ["CA", "MX"],
            },
            isolation_days=21,
        )
        sire_id = context["sire"]["id"]
        plain = fx.cut_lot(
            api, context["ejaculate"]["id"], straw_count=100, processing_cost_cents=125000
        )
        sorted_lot = fx.cut_lot(
            api,
            context["ejaculate"]["id"],
            "SEXED",
            100,
            125000,
            sexing_purity_pct=90.0,
        )
        assert fx.read_sire(api, sire_id)["isolation_days_applied"] == 21

        # One refusal per rule, each leaving the paperwork exactly where it was.
        for lot_id, requirement_id, error_id in (
            (plain["id"], unapproved["id"], ApiErrorId.ERR_DESTINATION_NOT_APPROVED.value),
            (sorted_lot["id"], strict["id"], ApiErrorId.ERR_PRODUCT_NOT_PERMITTED.value),
            (plain["id"], strict["id"], ApiErrorId.ERR_ISOLATION_TOO_SHORT.value),
        ):
            certificate = fx.draft_certificate(api, sire_id, lot_id, requirement_id)
            validate_error(
                api.submit_export_certificate(
                    certificate["id"], factories.certificate_submit_payload(), fx.COORDINATOR
                ),
                error_id,
                422,
            )
            held = fx.read_certificate(api, certificate["id"])
            assert held["status"] == "DRAFT"
            assert held["submission_round"] == 0

        # Twenty-one served days satisfy a twenty-one day minimum inclusively.
        welcome = fx.draft_certificate(api, sire_id, plain["id"], lenient["id"])
        submitted = fx.submit_certificate(api, welcome["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_round"] == 1

    def test_the_third_rejection_closes_the_paperwork(self, api):
        """Its `submission_round` must be strictly below 3 at the moment of
        submission, because a certificate may enter `SUBMITTED` at most three times; a
        fourth attempt is refused with `ERR_RESUBMISSION_LIMIT`.

        Design: Corner/errors/export_eligibility_codes_are_rejected
        """
        requirement = fx.register_country_requirement(
            api, country_code="MX", max_test_age_days=60, min_isolation_days=21
        )
        context = fx.released_lot(
            api,
            registration_code="REG-RS",
            facility_overrides={"code": "F-RS", "approved_export_countries": ["MX"]},
            straw_count=100,
            processing_cost_cents=125000,
        )
        certificate = fx.draft_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )

        for expected_round in (1, 2, 3):
            submitted = fx.submit_certificate(api, certificate["id"])
            assert submitted["submission_round"] == expected_round
            refused = fx.reject_certificate(api, certificate["id"])
            assert refused["status"] == "REJECTED"
            assert refused["submission_round"] == expected_round

        validate_error(
            api.submit_export_certificate(
                certificate["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            ApiErrorId.ERR_RESUBMISSION_LIMIT.value,
            422,
        )
        closed = fx.read_certificate(api, certificate["id"])
        assert closed["status"] == "REJECTED"
        assert closed["submission_round"] == 3
        assert closed["issued_at"] is None


class TestCommercialAndAdvisoryCodes:
    """The three codes raised by commercial policy rather than physical state."""

    def test_an_empty_candidate_pool_mints_nothing(self, api):
        """When that count is 0 — whether because of residency, collection status, a
        missing published proof, missing releasable stock of the requested line, the
        exclusion list, base-sire identity or an inbreeding figure above the herd's
        ceiling — the request is refused with `ERR_NO_ELIGIBLE_SIRE` and no
        recommendation row is created at all.

        Design: Corner/errors/commercial_and_advisory_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-CM",
            facility_overrides={"code": "F-CM"},
            straw_count=100,
            processing_cost_cents=125000,
        )
        sire_id = context["sire"]["id"]
        partner = fx.register_distributor(api, name="D-CM")
        herd = fx.register_customer_herd(api, partner["id"], herd_name="H-NONE")
        empty_pool = ApiErrorId.ERR_NO_ELIGIBLE_SIRE.value

        # Releasable stock is not enough: the bull carries no published proof.
        assert fx.read_sire(api, sire_id)["published_evaluation_effective_at"] is None
        validate_error(
            api.request_mating_recommendation(
                herd["id"], factories.mating_recommendation_payload(), fx.ADVISOR
            ),
            empty_pool,
            422,
        )
        _rows, meta = validate_paginated(
            api.list_mating_recommendations(fx.ADVISOR, {"customer_herd_id": herd["id"]})
        )
        assert meta["total_count"] == 0
        assert fx.read_herd(api, herd["id"])["recommendation_count"] == 0

        fx.published_proof(api, sire_id)
        proposed = fx.request_recommendation(api, herd["id"])
        assert proposed["status"] == "PROPOSED"
        assert proposed["recommended_sire_id"] == sire_id
        assert proposed["candidate_pool_size"] == 1

        # Refusing that one bull empties the pool again.
        validate_error(
            api.request_mating_recommendation(
                herd["id"],
                factories.mating_recommendation_payload(
                    excluded_sire_ids=[sire_id]
                ),
                fx.ADVISOR,
            ),
            empty_pool,
            422,
        )
        assert fx.read_herd(api, herd["id"])["recommendation_count"] == 1

    def test_a_disabled_partner_is_refused_at_approval(self, api):
        """The consignee's `consignment_enabled` must be true, or
        `ERR_CONSIGNMENT_DISABLED` — a false flag blocks approval whatever the
        partner's exposure.

        Design: Corner/errors/commercial_and_advisory_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-OFF",
            facility_overrides={"code": "F-OFF"},
            straw_count=100,
            processing_cost_cents=125000,
        )
        lot = context["lot"]
        blocked = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-OFF", "consignment_enabled": False},
            tank_overrides={"serial": "TK-OFF"},
        )
        allowed = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-ON"},
            tank_overrides={"serial": "TK-ON"},
        )
        assert blocked["distributor"]["consignment_enabled"] is False

        # The request itself is accepted; the switch is read one hop later.
        refused = fx.request_consignment(
            api, lot["id"], blocked["distributor"]["id"], blocked["tank"]["id"], doses=10
        )
        assert refused["status"] == "REQUESTED"
        validate_error(
            api.approve_consignment_transfer(
                refused["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_CONSIGNMENT_DISABLED.value,
            422,
        )
        assert fx.read_transfer(api, refused["id"])["status"] == "REQUESTED"
        assert_buckets(fx.read_lot(api, lot["id"]), 100, 0, 0, 0, 0)

        cleared = fx.request_consignment(
            api, lot["id"], allowed["distributor"]["id"], allowed["tank"]["id"], doses=10
        )
        assert fx.approve_transfer(api, cleared["id"])["status"] == "APPROVED"
        assert_buckets(fx.read_lot(api, lot["id"]), 90, 10, 0, 0, 0)

    def test_the_credit_projection_reads_the_book_value_inclusively(self, api):
        """The comparison is inclusive, so a projection landing exactly on the limit is
        approved, and a projection above it is refused with
        `ERR_CREDIT_LIMIT_EXCEEDED`.

        Design: Corner/errors/commercial_and_advisory_codes_are_rejected
        """
        context = fx.released_lot(
            api,
            registration_code="REG-CR",
            facility_overrides={"code": "F-CR"},
            straw_count=100,
            processing_cost_cents=400000,
        )
        lot = context["lot"]
        assert lot["unit_book_value_cents"] == 4000
        assert lot["valuation_basis"] == "STANDARD_COST"
        tight = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-TIGHT", "credit_limit_cents": 100000},
            tank_overrides={"serial": "TK-TIGHT"},
        )
        assert tight["distributor"]["consignment_value_cents"] == 0
        assert tight["distributor"]["outstanding_balance_cents"] == 0

        # Twenty-six doses project 104000 cents of exposure against a 100000 limit.
        over = fx.request_consignment(
            api,
            lot["id"],
            tight["distributor"]["id"],
            tight["tank"]["id"],
            doses=26,
            unit_price_cents=1,
        )
        validate_error(
            api.approve_consignment_transfer(
                over["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value,
            422,
        )
        assert fx.read_transfer(api, over["id"])["status"] == "REQUESTED"
        assert_buckets(fx.read_lot(api, lot["id"]), 100, 0, 0, 0, 0)

        # Twenty-five doses land exactly on it, whatever the agreed sale price.
        exact = fx.request_consignment(
            api,
            lot["id"],
            tight["distributor"]["id"],
            tight["tank"]["id"],
            doses=25,
            unit_price_cents=9000,
        )
        approved = fx.approve_transfer(api, exact["id"])
        assert approved["status"] == "APPROVED"
        assert_buckets(fx.read_lot(api, lot["id"]), 75, 25, 0, 0, 0)
