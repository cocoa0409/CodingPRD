"""Entity surface: creation envelopes, reads, listings, defaults and shape rules."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    OMIT,
    ApiErrorId,
    assert_common_fields,
    assert_envelope_meta,
    assert_instant_equals,
    assert_three_fractional_digits,
    expected_theoretical_doses,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFacilityCreationEnvelope:
    """The create response is the whole contract: envelope, inputs, system fields."""

    def test_a_new_facility_opens_approved_with_no_residents(self, api):
        """A new facility opens with `approval_status` at `APPROVED`,
        `suspension_reason` null and `resident_sire_count` at 0.

        Design: Corner/entities/facility_create_returns_envelope_and_declared_defaults
        """
        response = api.create_facility(
            factories.facility_payload(
                code="F-CR-01",
                country_code="US",
                housing_capacity=6,
                bench_capacity=2,
                approved_export_countries=["CA", "MX"],
            ),
            fx.DIRECTOR,
        )
        body = response.json()
        assert_envelope_meta(body)
        assert body["response_type"] == "object"

        facility = validate_success(response, 201)
        assert facility["code"] == "F-CR-01"
        assert facility["country_code"] == "US"
        assert facility["housing_capacity"] == 6
        assert facility["bench_capacity"] == 2
        assert facility["approved_export_countries"] == ["CA", "MX"]
        assert facility["approval_status"] == "APPROVED"
        assert facility["suspension_reason"] is None
        assert facility["resident_sire_count"] == 0
        assert facility["version"] == 1

        assert_common_fields(facility)
        assert_three_fractional_digits(facility["created_at"])
        assert_three_fractional_digits(facility["updated_at"])
        assert_instant_equals(facility["created_at"], facility["updated_at"])


class TestSireByIdRead:
    """A by-id read returns exactly what registration stored."""

    def test_a_freshly_registered_bull_reads_back_prospect_and_not_housed(self, api):
        """`acquisition_status` tracks commercial ownership and starts at
        `PROSPECT`, walking `PROSPECT -> CONTRACTED -> RESIDENT -> RETIRED`, with
        `RETIRED` terminal. `collection_status` tracks health and collection
        eligibility and starts at `NOT_HOUSED`.

        Design: Corner/entities/sire_get_by_id_returns_the_stored_row
        """
        created = fx.register_sire(
            api,
            registration_code="REG-R1",
            breed="JERSEY",
            birth_date="2021-11-02",
            acquisition_cost_cents=750000,
        )

        response = api.get_sire(created["id"], fx.DIRECTOR)
        assert response.json()["response_type"] == "object"
        sire = validate_success(response, 200)

        assert sire["id"] == created["id"]
        assert sire["registration_code"] == "REG-R1"
        assert sire["breed"] == "JERSEY"
        assert sire["birth_date"] == "2021-11-02"
        assert sire["acquisition_cost_cents"] == 750000
        assert sire["acquisition_status"] == "PROSPECT"
        assert sire["collection_status"] == "NOT_HOUSED"
        assert sire["housing_facility_id"] is None
        assert sire["contract_price_cents"] is None
        assert sire["published_production_index"] == pytest.approx(0.00, abs=0.001)
        assert sire["published_health_index"] == pytest.approx(0.00, abs=0.001)
        assert sire["published_composite_index"] == pytest.approx(0.00, abs=0.001)
        assert sire["published_evaluation_effective_at"] is None
        assert sire["progeny_daughter_count"] == 0
        assert sire["pedigree_depth"] == 0
        assert sire["collection_count"] == 0
        assert sire["version"] == 1


class TestSireListing:
    """total_count counts the filtered set; has_more looks past the window."""

    @staticmethod
    def _three_bulls(api):
        first = fx.register_sire(
            api, registration_code="REG-L1", breed="ANGUS", birth_date="2021-01-01",
            acquisition_cost_cents=100000,
        )
        second = fx.register_sire(
            api, registration_code="REG-L2", breed="ANGUS", birth_date="2021-02-01",
            acquisition_cost_cents=100000,
        )
        third = fx.register_sire(
            api, registration_code="REG-L3", breed="HOLSTEIN", birth_date="2021-03-01",
            acquisition_cost_cents=100000,
        )
        return first, second, third

    def test_the_breed_filter_narrows_the_count_and_the_window_walks_it(self, api):
        """`total_count` is the number of rows matching the filters before the page
        window is applied, and `has_more` is true when rows remain beyond the
        current window.

        Design: Corner/entities/sires_list_paginates_and_filters_by_breed
        """
        first, second, third = self._three_bulls(api)

        response = api.list_sires(fx.DIRECTOR, {"breed": "ANGUS", "limit": 1, "offset": 0})
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
        assert meta["total_count"] == 2
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api.list_sires(fx.DIRECTOR, {"breed": "ANGUS", "limit": 1, "offset": 1})
        )
        assert [row["id"] for row in rows] == [second["id"]]
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        rows, meta = validate_paginated(api.list_sires(fx.DIRECTOR))
        assert len(rows) == 3
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert [row["id"] for row in rows] == [first["id"], second["id"], third["id"]]

    def test_a_limit_above_one_hundred_is_a_request_shape_error(self, api):
        """`limit` defaults to 10 when omitted, may not be smaller than 1, and may
        not be larger than 100. A value outside those bounds is a request-shape
        error, not a silently clamped value.

        Design: Corner/entities/sires_list_paginates_and_filters_by_breed
        """
        self._three_bulls(api)

        validate_error(
            api.list_sires(fx.DIRECTOR, {"limit": 101}),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        validate_error(
            api.list_sires(fx.DIRECTOR, {"limit": 0}),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        validate_error(
            api.list_sires(fx.DIRECTOR, {"offset": -1}),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )


class TestUnknownIdIsNotFound:
    """A well-formed UUID matching no row is a 404, not an empty 200."""

    def test_the_same_code_answers_for_every_entity_type(self, api):
        """The same code covers every entity type; there is no per-type variant.

        Design: Corner/entities/sire_get_with_unknown_id_returns_not_found
        """
        fx.register_sire(
            api, registration_code="REG-N1", breed="ANGUS", birth_date="2021-01-01",
            acquisition_cost_cents=100000,
        )

        response = api.get_sire(NON_EXISTENT_UUID, fx.DIRECTOR)
        validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value, 404)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"] != ""
        assert_envelope_meta(body)

        validate_error(
            api.get_tank(NON_EXISTENT_UUID, fx.DIRECTOR),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.get_straw_lot(NON_EXISTENT_UUID, fx.DIRECTOR),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )


class TestRequiredSireInputs:
    """Every non-optional input must be present and non-null."""

    def test_a_missing_registration_code_is_rejected_before_anything_else(self, api):
        """Every non-optional field in the operation's input list must be present
        and non-null.

        Design: Corner/entities/sire_create_missing_required_field_returns_validation
        """
        validate_error(
            api.create_sire(
                factories.sire_payload(
                    registration_code=OMIT,
                    breed="ANGUS",
                    birth_date="2021-01-01",
                    acquisition_cost_cents=100000,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        validate_error(
            api.create_sire(
                factories.sire_payload(registration_code=None), fx.DIRECTOR
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )

        _, meta = validate_paginated(api.list_sires(fx.DIRECTOR))
        assert meta["total_count"] == 0

    def test_each_remaining_required_input_behaves_identically(self, api):
        """A `ProgramDirector` brings a bull into the system by registering him with
        a breed-association `registration_code` of 1 to 32 characters, a `breed`
        drawn from `HOLSTEIN`, `JERSEY` or `ANGUS`, a calendar `birth_date` in
        `YYYY-MM-DD` form, and the cash `acquisition_cost_cents` paid for the
        animal.

        Design: Corner/entities/sire_create_missing_required_field_returns_validation
        """
        for field in ("breed", "birth_date", "acquisition_cost_cents"):
            validate_error(
                api.create_sire(
                    factories.sire_payload(registration_code="REG-M1", **{field: OMIT}),
                    fx.DIRECTOR,
                ),
                ApiErrorId.ERR_VALIDATION.value,
                400,
            )

        accepted = validate_success(
            api.create_sire(
                factories.sire_payload(
                    registration_code="REG-M1", sire_id=OMIT, dam_sire_id=OMIT
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert accepted["registration_code"] == "REG-M1"
        assert accepted["pedigree_depth"] == 0


class TestOptionalInputDefaults:
    """Omitted optional inputs take their declared values, not null."""

    def test_a_facility_without_export_countries_opens_with_an_empty_list(self, api):
        """An optional `approved_export_countries` array — empty when omitted —
        lists the two-letter destination codes this site is cleared to export
        semen to.

        Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
        """
        facility = fx.register_facility(
            api,
            code="F-DEF-01",
            country_code="US",
            housing_capacity=2,
            bench_capacity=1,
            approved_export_countries=OMIT,
        )
        assert facility["approved_export_countries"] == []
        assert fx.read_facility(api, facility["id"])["approved_export_countries"] == []

    def test_a_tank_derives_its_whole_posture_from_the_declared_defaults(self, api):
        """An optional `service_interval_days` defaulting to 60 ... An optional
        `initial_fill_pct` defaults to 95.0. At creation `last_service_at` is
        stamped from the logical clock, `last_service_fill_pct` is set to the
        initial fill, `service_count` is 0 and `tank_status` is `IN_SERVICE`.

        Design: Corner/entities/optional_inputs_fall_back_to_declared_defaults
        """
        distributor = fx.register_distributor(
            api, name="D-DEF", country_code="US", credit_limit_cents=5000000
        )
        tank = validate_success(
            api.create_tank(
                factories.tank_payload(
                    distributor["id"], serial="TK-DEF", capacity_straws=400
                ),
                fx.DIRECTOR,
            ),
            201,
        )

        assert tank["service_interval_days"] == 60
        assert tank["last_service_fill_pct"] == pytest.approx(95.0, abs=0.05)
        assert_instant_equals(tank["last_service_at"], "2026-08-01T00:00:00.000Z")
        assert tank["ln2_level_pct"] == pytest.approx(95.0, abs=0.05)
        assert_instant_equals(tank["next_service_due_at"], "2026-09-30T00:00:00.000Z")
        assert tank["service_count"] == 0
        assert tank["straws_on_hand"] == 0
        assert tank["tank_status"] == "IN_SERVICE"
        assert tank["assigned_technician_name"] is None
        assert tank["technician_cert_expiry_at"] is None


class TestEjaculateTheoreticalDoses:
    """The yield is a floored quotient and it caps every lot ever cut."""

    WINDOW_START = "2026-09-01T08:00:00Z"
    WINDOW_END = "2026-09-01T10:00:00Z"
    COLLECTION = {"volume_ml": 5.5, "concentration_m_per_ml": 1150, "motility_pct": 68.0}

    @classmethod
    def _collected(cls, api):
        return fx.collected_ejaculate(
            api,
            start_at=cls.WINDOW_START,
            end_at=cls.WINDOW_END,
            collection_clock=cls.WINDOW_START,
            **cls.COLLECTION,
        )

    def test_the_quotient_is_floored_rather_than_rounded(self, api):
        """Its `total_doses_theoretical` is the volume in millilitres multiplied by
        the concentration in millions per millilitre, divided by the 15 million
        sperm cells that make up one insemination dose, with the quotient floored
        to a whole number of doses.

        Design: Corner/entities/ejaculate_theoretical_doses_computed_with_floor_not_rounding
        """
        context = self._collected(api)
        booking = context["booking"]
        assert booking["status"] == "COMPLETED"
        assert_instant_equals(booking["completed_at"], "2026-09-01T08:00:00.000Z")

        rows, meta = validate_paginated(
            api.list_ejaculates(fx.TECH, {"booking_id": booking["id"]})
        )
        assert meta["total_count"] == 1
        ejaculate = rows[0]
        assert ejaculate["qc_status"] == "PENDING_QC"
        assert ejaculate["total_doses_theoretical"] == 421
        assert ejaculate["total_doses_theoretical"] == expected_theoretical_doses(5.5, 1150)
        assert ejaculate["volume_ml"] == pytest.approx(5.5, abs=0.001)
        assert ejaculate["concentration_m_per_ml"] == pytest.approx(1150, abs=0.001)
        assert ejaculate["motility_pct"] == pytest.approx(68.0, abs=0.001)
        assert ejaculate["post_thaw_motility_pct"] is None
        assert ejaculate["morphology_normal_pct"] is None
        assert ejaculate["evaluated_by_user_id"] is None
        assert ejaculate["qc_decided_at"] is None

        assert fx.read_sire(api, context["sire"]["id"])["collection_count"] == 1

    def test_one_straw_above_the_floored_ceiling_is_refused(self, api):
        """The dose ceiling is aggregate, not per-lot: the sum of `straw_count`
        across every lot already cut from this ejaculate, including the row being
        created, must not exceed the ejaculate's `total_doses_theoretical`, or the
        request is refused with `ERR_DOSE_CAP_EXCEEDED`.

        Design: Corner/entities/ejaculate_theoretical_doses_computed_with_floor_not_rounding
        """
        context = fx.accepted_ejaculate(api, self._collected(api))
        ejaculate_id = context["ejaculate"]["id"]

        validate_error(
            api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload("CONVENTIONAL", 422, 250000),
                fx.TECH,
            ),
            ApiErrorId.ERR_DOSE_CAP_EXCEEDED.value,
            422,
        )

        lot = fx.cut_lot(api, ejaculate_id, "CONVENTIONAL", 421, 250000)
        assert lot["straw_count"] == 421
        assert lot["doses_available"] == 421


class TestClientSuppliedSystemFieldsAreIgnored:
    """Unknown body keys are ignored and system fields are minted server-side."""

    CLIENT_ID = "11111111-1111-4111-8111-111111111111"

    def test_a_client_cannot_dictate_the_id_the_version_or_the_status(self, api):
        """Every non-optional field in the operation's input list must be present
        and non-null; unknown body keys are ignored rather than rejected.

        Design: Corner/entities/facility_create_with_client_supplied_system_fields_input_ignored
        """
        facility = validate_success(
            api.create_facility(
                factories.facility_payload(
                    code="F-SYS-01",
                    country_code="US",
                    housing_capacity=3,
                    bench_capacity=1,
                    id=self.CLIENT_ID,
                    version=99,
                    approval_status="SUSPENDED",
                    resident_sire_count=7,
                ),
                fx.DIRECTOR,
            ),
            201,
        )

        assert facility["id"] != self.CLIENT_ID
        assert facility["version"] == 1
        assert facility["approval_status"] == "APPROVED"
        assert facility["resident_sire_count"] == 0
        assert_three_fractional_digits(facility["created_at"])
        assert_instant_equals(facility["created_at"], facility["updated_at"])


class TestEnumAndRangeConstraints:
    """Closed sets and numeric bounds are shape errors, and they come first."""

    @staticmethod
    def _bull_in_isolation(api):
        facility = fx.register_facility(
            api, code="F-TC-01", housing_capacity=2, bench_capacity=1
        )
        sire = fx.register_sire(api, registration_code="REG-TC")
        fx.contract_sire(api, sire["id"])
        housed = fx.house_sire(api, sire["id"], facility["id"])
        assert housed["collection_status"] == "ISOLATION"
        return facility, housed

    def test_an_unknown_assay_type_is_refused_and_writes_nothing(self, api):
        """Then every supplied field must parse to its declared type, and every
        enum-typed field must be a member of its declared set — `breed`,
        `product_line`, `test_type`, `result`, `requested_product_line` and
        `valuation_basis` are all closed sets.

        Design: Corner/entities/enum_and_range_constraints_rejected_at_priority_two_and_three
        """
        facility, sire = self._bull_in_isolation(api)

        validate_error(
            api.order_health_test(
                sire["id"],
                factories.health_test_payload(facility["id"], "RABIES", "2026-08-01", 365),
                fx.VET,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        _, meta = validate_paginated(
            api.list_health_tests(fx.VET, {"sire_id": sire["id"]})
        )
        assert meta["total_count"] == 0

        validate_error(
            api.create_sire(
                factories.sire_payload(registration_code="REG-TC-2", breed="WAGYU"),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )

    def test_range_bounds_and_the_shape_band_outrank_existence(self, api):
        """The shape rules outrank existence, and all three shape bands report
        `ERR_VALIDATION` (HTTP 400).

        Design: Corner/entities/enum_and_range_constraints_rejected_at_priority_two_and_three
        """
        facility, sire = self._bull_in_isolation(api)

        validate_error(
            api.create_facility(
                factories.facility_payload(code="F-TC-Z", housing_capacity=0), fx.DIRECTOR
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        validate_error(
            api.create_facility(
                factories.facility_payload(code="F-TC-Y", country_code="USA"), fx.DIRECTOR
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )
        validate_error(
            api.order_health_test(
                sire["id"],
                factories.health_test_payload(facility["id"], "IBR", "2026-08-01", -1),
                fx.VET,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )

        validate_error(
            api.order_health_test(
                NON_EXISTENT_UUID,
                factories.health_test_payload(facility["id"], "RABIES", "2026-08-01", 365),
                fx.VET,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )


class TestBookingWindowWellFormedAndFutureDated:
    """start_at strictly before end_at, and never behind the logical clock."""

    CLOCK = "2026-09-01T00:00:00Z"

    @classmethod
    def _eligible_bull_with_an_empty_diary(cls, api):
        context = fx.eligible_sire(
            api,
            registration_code="REG-TW",
            facility_overrides={
                "code": "F-TC-02",
                "housing_capacity": 2,
                "bench_capacity": 2,
            },
        )
        assert context["sire"]["collection_status"] == "ELIGIBLE"
        fx.advance_clock(api, cls.CLOCK)
        return context

    def test_three_malformed_windows_are_refused_and_the_closed_boundary_is_not(self, api):
        """The window itself must be well-formed and future-dated, with `start_at`
        strictly before `end_at` and `start_at` at or after the logical clock, or
        `ERR_INVALID_WINDOW`.

        Design: Corner/entities/booking_window_must_be_well_formed_and_future_dated
        """
        context = self._eligible_bull_with_an_empty_diary(api)
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]
        headers = context["facility_headers"]

        for start_at, end_at in (
            ("2026-09-10T10:00:00Z", "2026-09-10T10:00:00Z"),
            ("2026-09-10T12:00:00Z", "2026-09-10T10:00:00Z"),
            ("2026-08-31T23:59:59Z", "2026-09-01T02:00:00Z"),
        ):
            validate_error(
                api.create_booking(
                    factories.booking_payload(sire_id, facility_id, start_at, end_at),
                    headers,
                ),
                ApiErrorId.ERR_INVALID_WINDOW.value,
                422,
            )

        accepted = validate_success(
            api.create_booking(
                factories.booking_payload(
                    sire_id, facility_id, self.CLOCK, "2026-09-01T02:00:00Z"
                ),
                headers,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"
        assert_instant_equals(accepted["start_at"], "2026-09-01T00:00:00.000Z")
        assert_instant_equals(accepted["end_at"], "2026-09-01T02:00:00.000Z")
        assert accepted["cancel_reason"] is None
        assert accepted["completed_at"] is None
        assert accepted["collected_by_ref"] is None

        rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire_id})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == accepted["id"]


class TestUnresolvableForeignKeys:
    """Both FK surfaces answer 404: the path segment and the body reference."""

    @staticmethod
    def _bull_in_isolation(api):
        facility = fx.register_facility(
            api, code="F-FK-01", housing_capacity=2, bench_capacity=1
        )
        sire = fx.register_sire(api, registration_code="REG-FK")
        fx.contract_sire(api, sire["id"])
        housed = fx.house_sire(api, sire["id"], facility["id"])
        assert housed["collection_status"] == "ISOLATION"
        return facility, housed

    def test_a_body_reference_and_a_path_segment_both_answer_not_found(self, api):
        """Then existence: every `{id}` path segment must resolve to an existing
        row, and every foreign key in the body must resolve, both reported as
        `ERR_RESOURCE_NOT_FOUND` (HTTP 404), the path segment being checked before
        the body references.

        Design: Corner/entities/unknown_path_and_body_foreign_keys_return_not_found
        """
        facility, sire = self._bull_in_isolation(api)

        validate_error(
            api.order_health_test(
                sire["id"],
                factories.health_test_payload(
                    NON_EXISTENT_UUID, "IBR", "2026-08-01", 365
                ),
                fx.VET,
            ),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.order_health_test(
                NON_EXISTENT_UUID,
                factories.health_test_payload(facility["id"], "IBR", "2026-08-01", 365),
                fx.VET,
            ),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )
        validate_error(
            api.create_tank(
                factories.tank_payload(NON_EXISTENT_UUID, serial="TK-FK"), fx.DIRECTOR
            ),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )

        _, meta = validate_paginated(
            api.list_health_tests(fx.VET, {"sire_id": sire["id"]})
        )
        assert meta["total_count"] == 0


class TestPedigreeAmendmentCycle:
    """The self-referential pedigree has to stay a directed acyclic graph."""

    @staticmethod
    def _three_bulls(api):
        p1 = fx.register_sire(
            api,
            registration_code="REG-P1",
            birth_date="2019-01-01",
            acquisition_cost_cents=0,
        )
        p2 = fx.register_sire(
            api,
            registration_code="REG-P2",
            birth_date="2022-01-01",
            sire_id=p1["id"],
            acquisition_cost_cents=0,
        )
        p3 = fx.register_sire(
            api,
            registration_code="REG-P3",
            birth_date="2018-01-01",
            acquisition_cost_cents=0,
        )
        assert p1["pedigree_depth"] == 0
        assert p2["pedigree_depth"] == 1
        return p1, p2, p3

    def test_a_two_hop_cycle_and_a_self_edge_are_both_refused(self, api):
        """Neither proposed parent may be the bull himself, and neither may be a
        descendant of the bull, because the pedigree graph must remain acyclic; a
        proposal that would close a cycle is refused with `ERR_PEDIGREE_CYCLE`.

        Design: Corner/entities/pedigree_amendment_that_closes_a_cycle_is_rejected
        """
        p1, p2, _p3 = self._three_bulls(api)

        validate_error(
            api.amend_sire_pedigree(
                p1["id"], factories.pedigree_payload(sire_id=p2["id"]), fx.DIRECTOR
            ),
            ApiErrorId.ERR_PEDIGREE_CYCLE.value,
            422,
        )
        validate_error(
            api.amend_sire_pedigree(
                p1["id"], factories.pedigree_payload(sire_id=p1["id"]), fx.DIRECTOR
            ),
            ApiErrorId.ERR_PEDIGREE_CYCLE.value,
            422,
        )

        untouched = fx.read_sire(api, p1["id"])
        assert untouched["sire_id"] is None
        assert untouched["version"] == p1["version"]
        assert untouched["pedigree_depth"] == 0

    def test_an_acyclic_amendment_lands_and_the_ancestry_filter_follows_it(self, api):
        """A successful amendment stores the new parentage, recomputes
        `pedigree_depth` and bumps `version` by 1.

        Design: Corner/entities/pedigree_amendment_that_closes_a_cycle_is_rejected
        """
        p1, p2, p3 = self._three_bulls(api)

        amended = validate_success(
            api.amend_sire_pedigree(
                p2["id"], factories.pedigree_payload(sire_id=p3["id"]), fx.DIRECTOR
            ),
            200,
        )
        assert amended["sire_id"] == p3["id"]
        assert amended["pedigree_depth"] == 1
        assert amended["version"] == p2["version"] + 1

        _, by_new_parent = validate_paginated(
            api.list_sires(fx.DIRECTOR, {"sire_id": p3["id"]})
        )
        assert by_new_parent["total_count"] == 1
        _, by_old_parent = validate_paginated(
            api.list_sires(fx.DIRECTOR, {"sire_id": p1["id"]})
        )
        assert by_old_parent["total_count"] == 0
