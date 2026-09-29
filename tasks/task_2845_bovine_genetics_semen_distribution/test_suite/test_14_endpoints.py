"""Endpoint surfaces: what a create stores, what an action moves, what a read derives."""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_buckets,
    assert_instant_equals,
    expected_ln2_level_pct,
    expected_theoretical_doses,
    factories,
    fixtures as fx,
    make_facility_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCountryRequirementRoundTrip:
    """A create-and-read registry keyed on the country code."""

    MEXICO = {
        "country_code": "MX",
        "required_test_types": ["IBR", "BVD", "TRICHOMONIASIS"],
        "max_test_age_days": 45,
        "min_isolation_days": 28,
        "sexed_semen_allowed": True,
        "embryo_allowed": False,
    }

    def test_the_by_id_read_returns_exactly_what_creation_stored(self, api):
        """A `ProgramDirector` or `ExportCoordinator` declares one country's rule set
        with a two-uppercase-letter `country_code` ... a non-empty
        `required_test_types` array drawn from the six assay types the system
        understands, a `max_test_age_days` of at least 1 ... a `min_isolation_days`
        of at least 0 ... and two booleans, `sexed_semen_allowed` and
        `embryo_allowed`.

        Design: Corner/endpoints/country_requirement_create_read_and_list_round_trip
        """
        created = validate_success(
            api.create_country_requirement(
                factories.country_requirement_payload(**self.MEXICO), fx.COORDINATOR
            ),
            201,
        )

        assert created["country_code"] == "MX"
        assert created["max_test_age_days"] == 45
        assert created["min_isolation_days"] == 28
        assert created["sexed_semen_allowed"] is True
        assert created["embryo_allowed"] is False
        assert created["version"] == 1
        # Order preserved as supplied, and never expanded to the four base types.
        assert created["required_test_types"] == ["IBR", "BVD", "TRICHOMONIASIS"]

        for headers in (fx.VET, fx.DIRECTOR, fx.COORDINATOR):
            read = validate_success(
                api.get_country_requirement(created["id"], headers), 200
            )
            assert read["required_test_types"] == ["IBR", "BVD", "TRICHOMONIASIS"]
            assert read["max_test_age_days"] == 45
            assert read["min_isolation_days"] == 28
            assert read["sexed_semen_allowed"] is True
            assert read["embryo_allowed"] is False
            assert read["id"] == created["id"]
            assert read["version"] == 1

    def test_the_country_code_is_the_natural_key_and_the_create_is_shared(self, api):
        """... with a two-uppercase-letter `country_code` that must be unique across
        all rule sets — a collision reports `ERR_DUPLICATE_CODE`.

        Design: Corner/endpoints/country_requirement_create_read_and_list_round_trip
        """
        validate_success(
            api.create_country_requirement(
                factories.country_requirement_payload(**self.MEXICO), fx.COORDINATOR
            ),
            201,
        )
        # The same operation is open to the director.
        by_director = validate_success(
            api.create_country_requirement(
                factories.country_requirement_payload(country_code="BR"), fx.DIRECTOR
            ),
            201,
        )
        assert by_director["country_code"] == "BR"

        validate_error(
            api.create_country_requirement(
                factories.country_requirement_payload(
                    country_code="MX", required_test_types=["BLUETONGUE"]
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )
        validate_error(
            api.get_country_requirement(NON_EXISTENT_UUID, fx.COORDINATOR),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )


class TestContractAction:
    """One action, one dimension: the collection side never stirs."""

    @staticmethod
    def _a_prospect_bull(api):
        sire = fx.register_sire(
            api,
            registration_code="REG-CT",
            breed="HOLSTEIN",
            birth_date="2022-02-14",
            acquisition_cost_cents=600000,
        )
        assert sire["acquisition_status"] == "PROSPECT"
        assert sire["collection_status"] == "NOT_HOUSED"
        assert sire["version"] == 1
        return sire

    def test_contracting_advances_only_the_acquisition_dimension(self, api):
        """Signing the acquisition contract advances the animal
        `PROSPECT → CONTRACTED` on the acquisition dimension only, storing the
        negotiated `contract_price_cents` on the row; `collection_status` is
        untouched and remains `NOT_HOUSED`.

        Design: Corner/endpoints/contract_action_moves_only_the_acquisition_dimension
        """
        sire = self._a_prospect_bull(api)

        contracted = validate_success(
            api.contract_sire(
                sire["id"], factories.contract_payload(655000), fx.DIRECTOR
            ),
            200,
        )

        assert contracted["acquisition_status"] == "CONTRACTED"
        assert contracted["contract_price_cents"] == 655000
        assert contracted["collection_status"] == "NOT_HOUSED"
        assert contracted["housing_facility_id"] is None
        assert contracted["isolation_ends_at"] is None
        # The contract price is a second figure, not an overwrite of the first.
        assert contracted["acquisition_cost_cents"] == 600000
        assert contracted["version"] == 2
        assert contracted["published_composite_index"] == pytest.approx(0.00, abs=0.01)
        assert contracted["published_evaluation_effective_at"] is None

    def test_neither_dimension_accepts_a_repeat_or_a_skipped_step(self, api):
        """Each of the three acquisition moves demands its own source state —
        contracting requires `PROSPECT`, housing requires `CONTRACTED`, retiring
        requires `RESIDENT` — so a repeated call fails on the second attempt with
        `ERR_SIRE_ACQUISITION_STATE`.

        Design: Corner/endpoints/contract_action_moves_only_the_acquisition_dimension
        """
        sire = self._a_prospect_bull(api)
        fx.contract_sire(api, sire["id"], contract_price_cents=655000)

        validate_error(
            api.contract_sire(
                sire["id"], factories.contract_payload(700000), fx.DIRECTOR
            ),
            ApiErrorId.ERR_SIRE_ACQUISITION_STATE.value,
            409,
        )
        unchanged = fx.read_sire(api, sire["id"])
        assert unchanged["contract_price_cents"] == 655000
        assert unchanged["version"] == 2

        # The collection dimension never left NOT_HOUSED, so clearance is unreachable.
        validate_error(
            api.clear_sire_for_collection(
                sire["id"], factories.clearance_payload(), fx.VET
            ),
            ApiErrorId.ERR_SIRE_COLLECTION_STATE.value,
            409,
        )


class TestTankRead:
    """Four derived figures from one by-id read, none of them a stored input."""

    READ_CLOCK = "2026-09-30T08:00:00Z"

    @staticmethod
    def _a_tank_holding_one_dispatched_consignment(api):
        context = fx.released_lot(
            api,
            registration_code="REG-TK",
            facility_overrides={"code": "F-TK"},
            straw_count=200,
            processing_cost_cents=250000,
        )
        assert context["lot"]["unit_book_value_cents"] == 1250
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-TK", "credit_limit_cents": 100000000},
            tank_overrides={"serial": "TK-RD", "capacity_straws": 500},
        )
        transfer = fx.request_consignment(
            api,
            context["lot"]["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=100,
            unit_price_cents=4000,
        )
        fx.approve_transfer(api, transfer["id"])
        transfer = fx.dispatch_transfer(api, transfer["id"])
        assert transfer["status"] == "IN_TRANSIT"
        return {**context, **partner, "transfer": transfer}

    def test_the_read_derives_level_status_due_date_and_stock(self, api):
        """All three figures are re-derived for every tank on each clock move and on
        every tank read, so a tank's posture is always a function of the current
        clock rather than of a stored decision.

        Design: Corner/endpoints/tank_read_returns_derived_level_status_and_straws_on_hand
        """
        context = self._a_tank_holding_one_dispatched_consignment(api)
        # The tank was registered at the collection clock, 2026-09-10T08:00:00Z.
        fx.advance_clock(api, self.READ_CLOCK)

        tank = fx.read_tank(api, context["tank"]["id"])
        assert tank["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(95.0, 20), abs=0.01
        )
        assert tank["ln2_level_pct"] == pytest.approx(55.0, abs=0.01)
        assert tank["tank_status"] == "IN_SERVICE"
        assert_instant_equals(
            tank["next_service_due_at"], "2026-11-09T08:00:00.000Z"
        )
        assert tank["straws_on_hand"] == 100
        assert tank["capacity_straws"] == 500
        assert tank["service_count"] == 0
        assert tank["last_service_fill_pct"] == pytest.approx(95.0, abs=0.01)

    def test_the_stock_figure_tracks_the_transfers_while_the_level_does_not(self, api):
        """A tank read also exposes `straws_on_hand`, the sum of the
        still-outstanding doses across the tank's `IN_TRANSIT` and `RECEIVED`
        consignments.

        Design: Corner/endpoints/tank_read_returns_derived_level_status_and_straws_on_hand
        """
        context = self._a_tank_holding_one_dispatched_consignment(api)
        fx.advance_clock(api, self.READ_CLOCK)
        distributor_id = context["distributor"]["id"]

        fx.receive_transfer(api, context["transfer"]["id"], distributor_id)
        assert fx.read_tank(api, context["tank"]["id"])["straws_on_hand"] == 100

        fx.report_usage(api, context["transfer"]["id"], distributor_id, 100)
        settled = fx.read_tank(api, context["tank"]["id"])
        assert settled["straws_on_hand"] == 0
        assert settled["ln2_level_pct"] == pytest.approx(55.0, abs=0.01)
        assert settled["tank_status"] == "IN_SERVICE"


class TestCertificateCreationLinks:
    """Three foreign keys in one call, and one coherence rule between two of them."""

    @staticmethod
    def _two_bulls_each_with_a_released_lot(api):
        facility = fx.register_facility(
            api,
            code="F-LK",
            housing_capacity=2,
            bench_capacity=2,
            approved_export_countries=["CA"],
        )
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR"],
            max_test_age_days=30,
            min_isolation_days=21,
        )
        bulls = []
        for code in ("REG-LK1", "REG-LK2"):
            sire = fx.register_sire(api, registration_code=code)
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"])
            fx.grant_base_health_currency(api, sire["id"], facility["id"])
            bulls.append(sire)

        fx.advance_clock(api, fx.CLOCK_ISOLATION_SERVED)
        for sire in bulls:
            validate_success(
                api.clear_sire_for_collection(
                    sire["id"], factories.clearance_payload(), fx.VET
                ),
                200,
            )
        bookings = [fx.book_collection(api, sire["id"], facility["id"]) for sire in bulls]
        fx.advance_clock(api, fx.CLOCK_AT_COLLECTION)

        lots = []
        for booking in bookings:
            fx.complete_collection(api, booking["id"], facility["id"])
            ejaculate = fx.discover_ejaculate(api, booking["id"])
            fx.evaluate_qc(api, ejaculate["id"])
            cut = fx.cut_lot(api, ejaculate["id"], "CONVENTIONAL", 100, 125000)
            lots.append(fx.release_lot(api, cut["id"]))

        assert lots[0]["sire_id"] == bulls[0]["id"]
        assert lots[1]["sire_id"] == bulls[1]["id"]
        return {"facility": facility, "requirement": requirement, "bulls": bulls, "lots": lots}

    def test_a_lot_of_another_bull_cannot_be_certified(self, api):
        """The lot and the bull must agree: the lot named by `straw_lot_id` must have
        the same `sire_id` as the certificate, or the draft is refused with
        `ERR_LOT_SIRE_MISMATCH`.

        Design: Corner/endpoints/certificate_creation_links_sire_lot_and_destination
        """
        context = self._two_bulls_each_with_a_released_lot(api)
        first_bull = context["bulls"][0]
        other_lot = context["lots"][1]

        validate_error(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    first_bull["id"], other_lot["id"], context["requirement"]["id"]
                ),
                fx.COORDINATOR,
            ),
            ApiErrorId.ERR_LOT_SIRE_MISMATCH.value,
            422,
        )
        _rows, meta = validate_paginated(
            api.list_export_certificates(fx.COORDINATOR, {"sire_id": first_bull["id"]})
        )
        assert meta["total_count"] == 0

        # An unknown foreign key is answered in the existence band, before coherence.
        validate_error(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    first_bull["id"], other_lot["id"], NON_EXISTENT_UUID
                ),
                fx.COORDINATOR,
            ),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )

    def test_the_coherent_link_opens_a_draft_reachable_from_all_three_parents(self, api):
        """On creation the row enters `status` `DRAFT` with `submission_round` at 0,
        `rejection_reason`, `issued_by_user_id`, `issued_at`, `expires_at` and
        `revocation_reason` all null, and `destination_country_code` copied verbatim
        from the referenced rule set's `country_code`.

        Design: Corner/endpoints/certificate_creation_links_sire_lot_and_destination
        """
        context = self._two_bulls_each_with_a_released_lot(api)
        bull = context["bulls"][0]
        lot = context["lots"][0]
        requirement = context["requirement"]

        certificate = validate_success(
            api.create_export_certificate(
                factories.export_certificate_payload(
                    bull["id"], lot["id"], requirement["id"]
                ),
                fx.COORDINATOR,
            ),
            201,
        )

        assert certificate["status"] == "DRAFT"
        assert certificate["submission_round"] == 0
        assert certificate["destination_country_code"] == "CA"
        assert certificate["version"] == 1
        for field in (
            "rejection_reason",
            "issued_by_user_id",
            "issued_at",
            "expires_at",
            "revocation_reason",
        ):
            assert certificate[field] is None, field

        for query in (
            {"sire_id": bull["id"]},
            {"straw_lot_id": lot["id"]},
            {"country_requirement_id": requirement["id"]},
        ):
            rows, meta = validate_paginated(
                api.list_export_certificates(fx.COORDINATOR, query)
            )
            assert meta["total_count"] == 1, query
            assert rows[0]["id"] == certificate["id"]


class TestTransferApprovalConsignmentFlag:
    """A feature switch read at approval and nowhere else."""

    EXPIRY_CLOCK = "2027-08-01T00:00:00Z"

    @staticmethod
    def _a_request_against_a_partner(api, *, distributor_overrides, tank_serial):
        context = fx.released_lot(
            api,
            registration_code="REG-FL",
            facility_overrides={"code": "F-FL"},
            straw_count=200,
            processing_cost_cents=250000,
        )
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides=distributor_overrides,
            tank_overrides={"serial": tank_serial, "capacity_straws": 500},
        )
        transfer = fx.request_consignment(
            api,
            context["lot"]["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=20,
            unit_price_cents=4000,
        )
        # The flag is not read at request time.
        assert transfer["status"] == "REQUESTED"
        assert transfer["approved_by_user_id"] is None
        return {**context, **partner, "transfer": transfer}

    def test_a_disabled_partner_is_refused_however_large_its_credit_line(self, api):
        """The consignee's `consignment_enabled` must be true, or
        `ERR_CONSIGNMENT_DISABLED` — a false flag blocks approval whatever the
        partner's exposure.

        Design: Corner/endpoints/transfer_approval_is_conditional_on_the_consignment_flag
        """
        context = self._a_request_against_a_partner(
            api,
            distributor_overrides={
                "name": "D-OFF",
                "credit_limit_cents": 100000000,
                "consignment_enabled": False,
            },
            tank_serial="TK-OFF",
        )

        validate_error(
            api.approve_consignment_transfer(
                context["transfer"]["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_CONSIGNMENT_DISABLED.value,
            422,
        )
        refused = fx.read_transfer(api, context["transfer"]["id"])
        assert refused["status"] == "REQUESTED"
        assert refused["approved_by_user_id"] is None
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 200, 0, 0, 0, 0)

        # Health currency sits earlier in the priority order than the flag.
        sweep = fx.advance_clock(api, self.EXPIRY_CLOCK)
        assert len(sweep["expired_health_test_ids"]) == 4
        validate_error(
            api.approve_consignment_transfer(
                context["transfer"]["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_HEALTH_TESTS_NOT_CURRENT.value,
            422,
        )

    def test_the_flag_defaults_to_enabled_and_then_approval_moves_the_doses(self, api):
        """An optional `consignment_enabled` flag defaults to true and acts as a hard
        feature switch.

        Design: Corner/endpoints/transfer_approval_is_conditional_on_the_consignment_flag
        """
        context = self._a_request_against_a_partner(
            api,
            distributor_overrides={"name": "D-ON", "credit_limit_cents": 100000000},
            tank_serial="TK-ON",
        )
        assert context["distributor"]["consignment_enabled"] is True

        approved = fx.approve_transfer(api, context["transfer"]["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] is not None
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 180, 20, 0, 0, 0)


class TestClockAdvanceSweep:
    """One call, five id arrays, and only the rows that actually moved.""" 

    SWEEP_CLOCK = "2026-09-15T00:00:00Z"
    EARLY_WINDOW = ("2026-09-01T08:00:00Z", "2026-09-01T10:00:00Z")
    FUTURE_WINDOW = ("2026-09-20T08:00:00Z", "2026-09-20T10:00:00Z")

    @classmethod
    def _two_bulls_two_bookings_and_a_draining_tank(cls, api):
        # Registered while the clock still stands at its 2026-08-01 default.
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-SW"},
            tank_overrides={"serial": "TK-SW", "capacity_straws": 500},
        )
        facility = fx.register_facility(
            api, code="F-SW", housing_capacity=2, bench_capacity=2
        )
        bulls = []
        tests = []
        for code, per_type in (("REG-SW1", {"IBR": 45}), ("REG-SW2", None)):
            sire = fx.register_sire(api, registration_code=code)
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"])
            tests.append(
                fx.grant_base_health_currency(
                    api, sire["id"], facility["id"], per_type_validity_days=per_type
                )
            )
            bulls.append(sire)
        # 2026-08-01 plus 45 days: the short IBR lapses exactly at the sweep clock.
        assert_instant_equals(tests[0]["IBR"]["valid_until"], "2026-09-15T00:00:00.000Z")
        assert_instant_equals(tests[1]["IBR"]["valid_until"], fx.BASE_VALID_UNTIL)

        fx.advance_clock(api, fx.CLOCK_ISOLATION_SERVED)
        for sire in bulls:
            validate_success(
                api.clear_sire_for_collection(
                    sire["id"], factories.clearance_payload(), fx.VET
                ),
                200,
            )
        early = fx.book_collection(api, bulls[0]["id"], facility["id"], *cls.EARLY_WINDOW)
        fx.advance_clock(api, cls.EARLY_WINDOW[0])
        early = fx.complete_collection(api, early["id"], facility["id"])
        assert early["status"] == "COMPLETED"
        future = fx.book_collection(
            api, bulls[0]["id"], facility["id"], *cls.FUTURE_WINDOW
        )
        return {
            **partner,
            "facility": facility,
            "bulls": bulls,
            "tests": tests,
            "early": early,
            "future": future,
        }

    def test_the_sweep_names_exactly_the_rows_it_moved(self, api):
        """The response body reports what the sweep touched, as `current_utc`
        alongside four id arrays — `expired_health_test_ids`, `suspended_sire_ids`,
        `voided_booking_ids` — plus `service_due_tank_ids` and
        `out_of_service_tank_ids` naming the tanks that landed in each of those two
        postures.

        Design: Corner/endpoints/clock_advance_sweeps_every_affected_row_and_reports_the_ids
        """
        context = self._two_bulls_two_bookings_and_a_draining_tank(api)
        lapsing = context["tests"][0]["IBR"]
        first, second = context["bulls"]

        sweep = fx.advance_clock(api, self.SWEEP_CLOCK)

        assert_instant_equals(sweep["current_utc"], "2026-09-15T00:00:00.000Z")
        assert lapsing["id"] in sweep["expired_health_test_ids"]
        assert fx.read_health_test(api, lapsing["id"])["result"] == "EXPIRED"
        assert first["id"] in sweep["suspended_sire_ids"]
        assert second["id"] not in sweep["suspended_sire_ids"]
        assert context["future"]["id"] in sweep["voided_booking_ids"]
        assert context["early"]["id"] not in sweep["voided_booking_ids"]
        # 45 whole days of boil-off leave the tank at or below the 25.0 threshold.
        assert context["tank"]["id"] in sweep["service_due_tank_ids"]
        assert sweep["out_of_service_tank_ids"] == []

    def test_the_rows_themselves_carry_the_sweeps_consequences(self, api):
        """Second, every sire that thereby loses coverage of at least one of the four
        base required assays, and whose `collection_status` is `ELIGIBLE`, moves to
        `SUSPENDED` with `suspension_reason` set to `REQUIRED_TEST_EXPIRED`. Third,
        each of those suspended sires' `SCHEDULED` bookings whose `start_at` lies
        after the new clock become `VOIDED`.

        Design: Corner/endpoints/clock_advance_sweeps_every_affected_row_and_reports_the_ids
        """
        context = self._two_bulls_two_bookings_and_a_draining_tank(api)
        first, second = context["bulls"]

        fx.advance_clock(api, self.SWEEP_CLOCK)

        suspended = fx.read_sire(api, first["id"])
        assert suspended["collection_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "REQUIRED_TEST_EXPIRED"
        untouched = fx.read_sire(api, second["id"])
        assert untouched["collection_status"] == "ELIGIBLE"
        assert untouched["suspension_reason"] is None

        assert fx.read_booking(api, context["future"]["id"])["status"] == "VOIDED"
        completed = fx.read_booking(api, context["early"]["id"])
        assert completed["status"] == "COMPLETED"
        assert completed["cancel_reason"] is None

        tank = fx.read_tank(api, context["tank"]["id"])
        assert tank["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(95.0, 45), abs=0.01
        )
        assert tank["ln2_level_pct"] == pytest.approx(5.0, abs=0.01)
        assert tank["tank_status"] == "SERVICE_DUE"


class TestCompletionCascade:
    """The minted child is absent from the response that minted it."""

    def test_the_ejaculate_is_reachable_only_through_the_filtered_list(self, api):
        """That ejaculate is not returned in the completion response — it is
        discovered only by listing ejaculates filtered by `booking_id`, which
        alongside `sire_id` and `qc_status` is the sole discovery channel for a
        cascade-created row.

        Design: Corner/endpoints/completion_cascade_creates_an_ejaculate_reachable_only_by_list
        """
        context = fx.eligible_sire(
            api, registration_code="REG-CC", facility_overrides={"code": "F-CC"}
        )
        facility_id = context["facility"]["id"]
        assert fx.read_sire(api, context["sire"]["id"])["collection_count"] == 0
        booking = fx.book_collection(api, context["sire"]["id"], facility_id)
        fx.advance_clock(api, fx.CLOCK_AT_COLLECTION)

        completed = validate_success(
            api.complete_booking(
                booking["id"],
                factories.booking_complete_payload(
                    5.5, 1150, 68.0, collected_by_ref="TECH-7"
                ),
                make_facility_headers(facility_id),
            ),
            200,
        )

        assert completed["status"] == "COMPLETED"
        assert_instant_equals(completed["completed_at"], "2026-09-10T08:00:00.000Z")
        assert completed["collected_by_ref"] == "TECH-7"
        assert [key for key in completed if "ejaculate" in key] == []

        rows, meta = validate_paginated(
            api.list_ejaculates(fx.TECH, {"booking_id": booking["id"]})
        )
        assert meta["total_count"] == 1
        ejaculate = rows[0]
        assert ejaculate["qc_status"] == "PENDING_QC"
        assert ejaculate["sire_id"] == context["sire"]["id"]
        assert ejaculate["volume_ml"] == pytest.approx(5.5, abs=0.01)
        assert ejaculate["concentration_m_per_ml"] == pytest.approx(1150, abs=0.01)
        assert ejaculate["motility_pct"] == pytest.approx(68.0, abs=0.01)
        # floor(5.5 * 1150 / 15) == floor(421.66...), never rounded up to 422.
        assert ejaculate["total_doses_theoretical"] == expected_theoretical_doses(5.5, 1150)
        assert ejaculate["total_doses_theoretical"] == 421
        for field in (
            "post_thaw_motility_pct",
            "morphology_normal_pct",
            "evaluated_by_user_id",
            "qc_decided_at",
        ):
            assert ejaculate[field] is None, field
        assert fx.read_sire(api, context["sire"]["id"])["collection_count"] == 1

    def test_a_second_completion_mints_nothing(self, api):
        """Either way, a booking that is no longer `SCHEDULED` accepts no further
        transition and reports `ERR_BOOKING_STATE`.

        Design: Corner/endpoints/completion_cascade_creates_an_ejaculate_reachable_only_by_list
        """
        context = fx.collected_ejaculate(
            api, registration_code="REG-CC", facility_overrides={"code": "F-CC"}
        )
        booking_id = context["booking"]["id"]

        validate_error(
            api.complete_booking(
                booking_id,
                factories.booking_complete_payload(),
                make_facility_headers(context["facility"]["id"]),
            ),
            ApiErrorId.ERR_BOOKING_STATE.value,
            409,
        )
        _rows, meta = validate_paginated(
            api.list_ejaculates(fx.TECH, {"booking_id": booking_id})
        )
        assert meta["total_count"] == 1
        by_sire, sire_meta = validate_paginated(
            api.list_ejaculates(fx.TECH, {"sire_id": context["sire"]["id"]})
        )
        assert sire_meta["total_count"] == 1
        assert by_sire[0]["id"] == context["ejaculate"]["id"]


class TestRecommendationDecision:
    """One endpoint, two answers, and only one of them touches the ledger."""

    @staticmethod
    def _two_proposals_against_one_lot(api, proposals=2):
        context = fx.released_lot(
            api,
            registration_code="REG-DEC",
            facility_overrides={"code": "F-DEC"},
            straw_count=150,
            processing_cost_cents=150000,
        )
        fx.published_proof(api, context["sire"]["id"])
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-DEC", "credit_limit_cents": 100000000},
            tank_overrides={"serial": "TK-DEC", "capacity_straws": 500},
        )
        herd = fx.register_customer_herd(
            api, partner["distributor"]["id"], herd_name="H-DEC"
        )
        assert herd["recommendation_count"] == 0
        recommendations = [
            fx.request_recommendation(
                api, herd["id"], dam_ref=f"COW-{index}", doses_requested=10
            )
            for index in range(proposals)
        ]
        for proposal in recommendations:
            assert proposal["status"] == "PROPOSED"
            assert proposal["doses_committed"] == 0
            assert proposal["straw_lot_id"] == context["lot"]["id"]
        assert fx.read_herd(api, herd["id"])["recommendation_count"] == proposals
        return {**context, **partner, "herd": herd, "recommendations": recommendations}

    def test_acceptance_reserves_the_doses_and_bumps_the_lot(self, api):
        """It sets `doses_committed` to `doses_requested`, stamps `decided_at` from
        the logical clock, moves `doses_requested` out of the lot's `doses_available`
        and into its `doses_reserved`, and increments the lot's `version` by 1.

        Design: Corner/endpoints/recommendation_decision_reserves_doses_only_when_accepted
        """
        context = self._two_proposals_against_one_lot(api)
        lot_before = fx.read_lot(api, context["lot"]["id"])

        accepted = fx.decide_recommendation(
            api, context["recommendations"][0]["id"], "ACCEPTED"
        )

        assert accepted["status"] == "ACCEPTED"
        assert accepted["doses_committed"] == 10
        assert_instant_equals(accepted["decided_at"], "2026-09-10T08:00:00.000Z")
        lot_after = fx.read_lot(api, context["lot"]["id"])
        assert_buckets(lot_after, 140, 10, 0, 0, 0)
        assert lot_after["straw_count"] == 150
        assert lot_after["version"] == lot_before["version"] + 1
        # An acceptance leaves the herd's counter alone.
        assert fx.read_herd(api, context["herd"]["id"])["recommendation_count"] == 2

    def test_withdrawal_moves_no_dose_and_decrements_the_counter(self, api):
        """`PROPOSED → WITHDRAWN` likewise requires the recommendation to be
        `PROPOSED`, stamps `decided_at` from the logical clock, leaves
        `doses_committed` at 0, touches the lot ledger not at all, and decrements the
        herd's `recommendation_count`.

        Design: Corner/endpoints/recommendation_decision_reserves_doses_only_when_accepted
        """
        context = self._two_proposals_against_one_lot(api)
        fx.decide_recommendation(api, context["recommendations"][0]["id"], "ACCEPTED")

        withdrawn = fx.decide_recommendation(
            api, context["recommendations"][1]["id"], "WITHDRAWN"
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["doses_committed"] == 0
        assert_instant_equals(withdrawn["decided_at"], "2026-09-10T08:00:00.000Z")
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 140, 10, 0, 0, 0)
        assert fx.read_herd(api, context["herd"]["id"])["recommendation_count"] == 1
        # The accepted sibling kept its own commitment through the withdrawal.
        accepted = fx.read_recommendation(api, context["recommendations"][0]["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["doses_committed"] == 10

    def test_stock_is_rechecked_at_decision_time(self, api):
        """`PROPOSED → ACCEPTED` requires the recommendation to still be `PROPOSED`,
        the selected lot to still be `RELEASED`, and that lot's `doses_available` to
        be at least `doses_requested`, failing which `ERR_INSUFFICIENT_DOSES`.

        Design: Corner/endpoints/recommendation_decision_reserves_doses_only_when_accepted
        """
        context = self._two_proposals_against_one_lot(api)
        proposal = context["recommendations"][1]

        # A consignment takes almost the whole shelf after the proposal was frozen.
        transfer = fx.request_consignment(
            api,
            context["lot"]["id"],
            context["distributor"]["id"],
            context["tank"]["id"],
            doses=145,
            unit_price_cents=4000,
        )
        fx.approve_transfer(api, transfer["id"])
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 5, 145, 0, 0, 0)

        validate_error(
            api.decide_mating_recommendation(
                proposal["id"], factories.decision_payload("ACCEPTED"), fx.ADVISOR
            ),
            ApiErrorId.ERR_INSUFFICIENT_DOSES.value,
            422,
        )
        assert fx.read_recommendation(api, proposal["id"])["status"] == "PROPOSED"
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 5, 145, 0, 0, 0)
