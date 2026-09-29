"""Rule bands in action: uniqueness, authorisation, pinning, temporal and capacity."""

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_buckets,
    assert_instant_equals,
    factories,
    fixtures as fx,
    headers_without_role,
    make_distributor_headers,
    make_facility_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUniqueCodesAcrossRegistries:
    """Four registries, one collision code, and the shape band still first."""

    @staticmethod
    def _one_row_in_each_registry(api):
        facility = fx.register_facility(
            api, code="F-UQ-01", country_code="US", housing_capacity=4, bench_capacity=2
        )
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR", "BVD"],
            max_test_age_days=30,
            min_isolation_days=21,
            sexed_semen_allowed=True,
            embryo_allowed=False,
        )
        sire = fx.register_sire(api, registration_code="REG-UQ")
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-UQ"},
            tank_overrides={"serial": "TK-UQ"},
        )
        return {
            "facility": facility,
            "requirement": requirement,
            "sire": sire,
            **partner,
        }

    def test_each_registry_refuses_its_own_repeated_code(self, api):
        """Fourth, uniqueness: the code-collision family (`ERR_DUPLICATE_CODE`),
        then the outstanding-pending-test rule (`ERR_DUPLICATE_PENDING_TEST`).

        Design: Corner/validations/unique_codes_are_enforced_on_all_four_registries
        """
        context = self._one_row_in_each_registry(api)

        # A differing country_code and differing capacities do not make it a
        # distinct facility: the code alone is the identity.
        validate_error(
            api.create_facility(
                factories.facility_payload(
                    code="F-UQ-01", country_code="MX", housing_capacity=9, bench_capacity=3
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )
        untouched = fx.read_facility(api, context["facility"]["id"])
        assert untouched["country_code"] == "US"
        assert untouched["housing_capacity"] == 4
        assert untouched["version"] == 1

        validate_error(
            api.create_country_requirement(
                factories.country_requirement_payload(country_code="CA"), fx.COORDINATOR
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )
        validate_error(
            api.create_sire(
                factories.sire_payload(registration_code="REG-UQ", breed="JERSEY"),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )
        validate_error(
            api.create_tank(
                factories.tank_payload(
                    context["distributor"]["id"], serial="TK-UQ", capacity_straws=300
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_DUPLICATE_CODE.value,
            409,
        )

    def test_shape_outranks_uniqueness_and_codes_do_not_leak_across_entities(self, api):
        """All three shape bands report `ERR_VALIDATION` (HTTP 400). ... A tank
        carries the manufacturer `serial`, unique across all tanks and refused with
        `ERR_DUPLICATE_CODE` on collision.

        Design: Corner/validations/unique_codes_are_enforced_on_all_four_registries
        """
        context = self._one_row_in_each_registry(api)

        # Duplicated code *and* a missing required field: the 400 answers first.
        validate_error(
            api.create_facility(
                factories.facility_payload(
                    code="F-UQ-01", bench_capacity=factories.OMIT
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )

        # The facility's code is no obstacle to a tank wearing the same string.
        borrowed = validate_success(
            api.create_tank(
                factories.tank_payload(context["distributor"]["id"], serial="F-UQ-01"),
                fx.DIRECTOR,
            ),
            201,
        )
        assert borrowed["serial"] == "F-UQ-01"
        assert borrowed["version"] == 1


class TestFullyCompliantBookingCreation:
    """The positive control: every booking rule silent at once."""

    WINDOW_START = "2026-09-10T08:00:00Z"
    WINDOW_END = "2026-09-10T10:00:00Z"

    @staticmethod
    def _two_resident_bulls(api, *, second_isolation_days=30):
        facility = fx.register_facility(
            api, code="F-OK", housing_capacity=2, bench_capacity=2
        )
        bulls = []
        for code, isolation_days in (
            ("REG-OK", 30),
            ("REG-OK2", second_isolation_days),
        ):
            sire = fx.register_sire(api, registration_code=code)
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"], isolation_days)
            fx.grant_base_health_currency(api, sire["id"], facility["id"])
            bulls.append(sire)

        fx.advance_clock(api, fx.CLOCK_ISOLATION_SERVED)
        cleared = [
            validate_success(
                api.clear_sire_for_collection(
                    sire["id"], factories.clearance_payload(), fx.VET
                ),
                200,
            )
            for sire in bulls
        ]
        return facility, cleared

    def test_the_compliant_window_is_scheduled_and_discoverable(self, api):
        """A booking names the `sire_id` to be collected, the `facility_id` owning
        the bench, and a half-open window from an inclusive `start_at` to an
        exclusive `end_at`, and is created with `status` `SCHEDULED`,
        `cancel_reason`, `completed_at` and `collected_by_ref` all null.

        Design: Corner/validations/fully_compliant_booking_creation_passes_every_rule
        """
        facility, cleared = self._two_resident_bulls(api)
        sire = cleared[0]
        assert sire["collection_status"] == "ELIGIBLE"
        assert sire["housing_facility_id"] == facility["id"]
        ibr_rows, _ibr_meta = validate_paginated(
            api.list_health_tests(fx.VET, {"sire_id": sire["id"], "test_type": "IBR"})
        )
        assert ibr_rows[0]["result"] == "NEGATIVE"
        assert_instant_equals(ibr_rows[0]["valid_until"], fx.BASE_VALID_UNTIL)

        booking = validate_success(
            api.create_booking(
                factories.booking_payload(
                    sire["id"], facility["id"], self.WINDOW_START, self.WINDOW_END
                ),
                make_facility_headers(facility["id"]),
            ),
            201,
        )

        assert booking["status"] == "SCHEDULED"
        assert booking["sire_id"] == sire["id"]
        assert booking["facility_id"] == facility["id"]
        assert booking["version"] == 1
        assert_instant_equals(booking["start_at"], "2026-09-10T08:00:00.000Z")
        assert_instant_equals(booking["end_at"], "2026-09-10T10:00:00.000Z")
        assert booking["completed_at"] is None
        assert booking["cancel_reason"] is None
        assert booking["collected_by_ref"] is None

        by_sire, sire_meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": sire["id"]})
        )
        assert sire_meta["total_count"] == 1
        assert by_sire[0]["id"] == booking["id"]
        by_facility, facility_meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"facility_id": facility["id"]})
        )
        assert facility_meta["total_count"] == 1
        assert by_facility[0]["id"] == booking["id"]

    def test_the_second_bull_takes_the_same_slot_because_the_bench_has_room(self, api):
        """Count the `SCHEDULED` bookings at that facility whose half-open windows
        overlap the requested one; that count plus one must not exceed the
        facility's `bench_capacity`.

        Design: Corner/validations/fully_compliant_booking_creation_passes_every_rule
        """
        facility, cleared = self._two_resident_bulls(api)

        first = fx.book_collection(
            api, cleared[0]["id"], facility["id"], self.WINDOW_START, self.WINDOW_END
        )
        second = fx.book_collection(
            api, cleared[1]["id"], facility["id"], self.WINDOW_START, self.WINDOW_END
        )

        assert second["status"] == "SCHEDULED"
        assert second["id"] != first["id"]
        _rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"facility_id": facility["id"]})
        )
        assert meta["total_count"] == 2


class TestRoleCheckPrecedesExistenceAndState:
    """An unauthorised caller learns nothing about the row behind the id."""

    @staticmethod
    def _a_prospect_bull_and_a_partner(api):
        sire = fx.register_sire(
            api,
            registration_code="REG-AUTH",
            breed="ANGUS",
            birth_date="2022-04-04",
            acquisition_cost_cents=200000,
        )
        assert sire["acquisition_status"] == "PROSPECT"
        assert sire["collection_status"] == "NOT_HOUSED"
        distributor = fx.register_distributor(
            api, name="D-AUTH", credit_limit_cents=100000
        )
        return sire, make_distributor_headers(distributor["id"])

    def test_the_same_forbidden_answer_covers_a_real_and_a_fabricated_id(self, api):
        """Second, authorisation: the role check (`ERR_UNAUTHORIZED`) ... Third,
        existence: path ids left to right, then body foreign keys
        (`ERR_RESOURCE_NOT_FOUND`).

        Design: Corner/validations/role_check_is_unauthorized_before_existence_and_state
        """
        sire, partner_headers = self._a_prospect_bull_and_a_partner(api)

        validate_error(
            api.get_sire(NON_EXISTENT_UUID, partner_headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.get_sire(sire["id"], partner_headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        # A PROSPECT bull cannot be retired, but the state rule never runs.
        validate_error(
            api.retire_sire(sire["id"], factories.retire_payload(), partner_headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        assert fx.read_sire(api, sire["id"])["acquisition_status"] == "PROSPECT"

    def test_a_missing_role_header_is_forbidden_while_shape_still_answers_first(self, api):
        """If `X-User-Role` is missing, or names a role that is not authorised for
        the addressed operation, the request fails with `ERR_UNAUTHORIZED` (HTTP 403).

        Design: Corner/validations/role_check_is_unauthorized_before_existence_and_state
        """
        sire, partner_headers = self._a_prospect_bull_and_a_partner(api)

        validate_error(
            api.get_sire(sire["id"], headers_without_role()),
            ApiErrorId.ERR_UNAUTHORIZED.value,
            403,
        )
        # Wrong role and an empty body: the shape band answers before the role.
        validate_error(
            api.create_sire({}, partner_headers),
            ApiErrorId.ERR_VALIDATION.value,
            400,
        )


class TestStaleLotVersionOutranksLotState:
    """A pin one revision behind answers before the lot's own posture."""

    @staticmethod
    def _a_revalued_quarantine_lot(api):
        context = fx.quarantine_lot(
            api,
            registration_code="REG-OCC",
            facility_overrides={"code": "F-OCC"},
            straw_count=100,
            processing_cost_cents=250000,
        )
        assert context["lot"]["distribution_status"] == "QUARANTINE"
        assert context["lot"]["unit_book_value_cents"] == 2500
        assert context["lot"]["valuation_basis"] == "STANDARD_COST"
        assert context["lot"]["pre_revaluation_unit_value_cents"] is None
        stale_version = context["lot"]["version"]
        assert stale_version == 1

        fx.published_proof(api, context["sire"]["id"])
        context["lot"] = fx.read_lot(api, context["lot"]["id"])
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-OCC", "credit_limit_cents": 10000000},
            tank_overrides={"serial": "TK-OCC"},
        )
        return {**context, **partner, "stale_version": stale_version}

    def test_the_stale_pin_answers_before_the_quarantine_state(self, api):
        """Fifth, the optimistic-concurrency pin: a supplied `expected_*_version`
        that no longer matches the stored `version` fails with the entity's stale
        error (HTTP 412) before any state precondition is evaluated.

        Design: Corner/validations/stale_lot_version_outranks_the_lot_state_precondition
        """
        context = self._a_revalued_quarantine_lot(api)
        lot = context["lot"]

        # Publication revalued the QUARANTINE lot, so the caller's pin of 1 is behind.
        assert lot["version"] == 2
        assert lot["valuation_basis"] == "MARKET_REVALUED"
        assert lot["pre_revaluation_unit_value_cents"] == 2500

        validate_error(
            api.request_consignment_transfer(
                lot["id"],
                factories.consignment_request_payload(
                    context["distributor"]["id"],
                    context["tank"]["id"],
                    context["stale_version"],
                    doses=10,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_STALE_STRAW_LOT_VERSION.value,
            412,
        )

        # Refreshing the pin lets the state precondition speak.
        validate_error(
            api.request_consignment_transfer(
                lot["id"],
                factories.consignment_request_payload(
                    context["distributor"]["id"],
                    context["tank"]["id"],
                    lot["version"],
                    doses=10,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_LOT_NOT_RELEASED.value,
            409,
        )

        _rows, meta = validate_paginated(
            api.list_consignment_transfers(fx.DIRECTOR, {"straw_lot_id": lot["id"]})
        )
        assert meta["total_count"] == 0
        assert_buckets(fx.read_lot(api, lot["id"]), 100, 0, 0, 0, 0)

    def test_existence_still_outranks_the_pin(self, api):
        """Third, existence: path ids left to right, then body foreign keys
        (`ERR_RESOURCE_NOT_FOUND`).

        Design: Corner/validations/stale_lot_version_outranks_the_lot_state_precondition
        """
        context = self._a_revalued_quarantine_lot(api)

        validate_error(
            api.request_consignment_transfer(
                NON_EXISTENT_UUID,
                factories.consignment_request_payload(
                    context["distributor"]["id"],
                    context["tank"]["id"],
                    context["stale_version"],
                    doses=10,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
            404,
        )


class TestCrossBorderCertificateMatching:
    """The certificate must be ISSUED and must name this very lot."""

    @staticmethod
    def _two_lots_one_certificate(api):
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
        )
        context = fx.accepted_ejaculate(
            api,
            registration_code="REG-XB",
            facility_overrides={"code": "F-XB", "approved_export_countries": ["CA"]},
        )
        lots = []
        for _ in range(2):
            cut = fx.cut_lot(api, context["ejaculate"]["id"], "CONVENTIONAL", 100, 125000)
            lots.append(fx.release_lot(api, cut["id"]))

        issued = fx.issued_certificate(
            api, context["sire"]["id"], lots[1]["id"], requirement["id"]
        )
        assert issued["status"] == "ISSUED"
        assert issued["destination_country_code"] == "CA"
        draft = fx.draft_certificate(
            api, context["sire"]["id"], lots[0]["id"], requirement["id"]
        )
        assert draft["status"] == "DRAFT"

        cross_border = fx.distributor_with_tank(
            api,
            distributor_overrides={
                "name": "D-CA",
                "country_code": "CA",
                "credit_limit_cents": 10000000,
            },
            tank_overrides={"serial": "TK-CA"},
        )
        return {
            **context,
            "lots": lots,
            "issued": issued,
            "draft": draft,
            "cross_border": cross_border,
        }

    @staticmethod
    def _ship(api, lot, partner, **overrides):
        return api.request_consignment_transfer(
            lot["id"],
            factories.consignment_request_payload(
                partner["distributor"]["id"],
                partner["tank"]["id"],
                fx.read_lot(api, lot["id"])["version"],
                doses=10,
                **overrides,
            ),
            fx.DIRECTOR,
        )

    def test_the_wrong_lot_a_missing_citation_and_a_draft_all_fail_alike(self, api):
        """When a certificate is cited, it must genuinely cover this shipment: its
        `sire_id` must equal the lot's `sire_id`, its `straw_lot_id` must equal the
        lot being shipped, and its `status` must be `ISSUED`; a cross-border shipment
        that cites no certificate, or cites one failing any of those tests, reports
        `ERR_CERTIFICATE_NOT_APPLICABLE`.

        Design: Corner/validations/cross_border_transfer_requires_an_issued_matching_certificate
        """
        context = self._two_lots_one_certificate(api)
        first, second = context["lots"]
        partner = context["cross_border"]

        # Same bull, wrong lot.
        validate_error(
            self._ship(
                api, first, partner, export_certificate_id=context["issued"]["id"]
            ),
            ApiErrorId.ERR_CERTIFICATE_NOT_APPLICABLE.value,
            422,
        )
        # No citation at all, to a CA consignee.
        validate_error(
            self._ship(api, first, partner),
            ApiErrorId.ERR_CERTIFICATE_NOT_APPLICABLE.value,
            422,
        )
        # Right lot, wrong status.
        validate_error(
            self._ship(api, first, partner, export_certificate_id=context["draft"]["id"]),
            ApiErrorId.ERR_CERTIFICATE_NOT_APPLICABLE.value,
            422,
        )
        assert second["distribution_status"] == "RELEASED"

    def test_the_matching_pair_ships_and_the_domestic_lane_needs_nothing(self, api):
        """The plant itself sits in the country `US`; whenever a partner's
        `country_code` differs from `US`, every dispatch to that partner requires an
        issued export certificate, and when it equals `US` the shipment is domestic.

        Design: Corner/validations/cross_border_transfer_requires_an_issued_matching_certificate
        """
        context = self._two_lots_one_certificate(api)
        first, second = context["lots"]

        covered = validate_success(
            self._ship(
                api,
                second,
                context["cross_border"],
                export_certificate_id=context["issued"]["id"],
            ),
            201,
        )
        assert covered["status"] == "REQUESTED"
        assert covered["export_certificate_id"] == context["issued"]["id"]

        domestic = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-US", "credit_limit_cents": 10000000},
            tank_overrides={"serial": "TK-US"},
        )
        uncovered = validate_success(self._ship(api, first, domestic), 201)
        assert uncovered["status"] == "REQUESTED"
        assert uncovered["export_certificate_id"] is None


class TestFutureDatedOperationsAgainstTheClock:
    """Three temporal rules, one logical clock, no wall time anywhere."""

    LATE_CLOCK = "2026-09-10T08:00:00Z"

    def test_a_booking_cannot_be_completed_before_its_window_opens(self, api):
        """Completion is refused before the window opens: the logical clock must be
        at or after `start_at`, or `ERR_BOOKING_NOT_STARTED`.

        Design: Corner/validations/future_dated_operations_are_refused_against_the_logical_clock
        """
        context = fx.eligible_sire(
            api, registration_code="REG-TM", facility_overrides={"code": "F-TM"}
        )
        facility_id = context["facility"]["id"]
        booking = fx.book_collection(api, context["sire"]["id"], facility_id)

        validate_error(
            api.complete_booking(
                booking["id"],
                factories.booking_complete_payload(),
                make_facility_headers(facility_id),
            ),
            ApiErrorId.ERR_BOOKING_NOT_STARTED.value,
            422,
        )
        assert fx.read_booking(api, booking["id"])["status"] == "SCHEDULED"
        _rows, meta = validate_paginated(
            api.list_ejaculates(fx.TECH, {"booking_id": booking["id"]})
        )
        assert meta["total_count"] == 0

        # The boundary is inclusive: the opening instant is enough.
        fx.advance_clock(api, self.LATE_CLOCK)
        completed = fx.complete_collection(api, booking["id"], facility_id)
        assert completed["status"] == "COMPLETED"
        assert_instant_equals(completed["completed_at"], "2026-09-10T08:00:00.000Z")

    def test_a_sample_date_may_not_lead_the_clock(self, api):
        """A sample cannot be dated in the future: `sample_date` must not be after
        the logical clock, or `ERR_SAMPLE_DATE_FUTURE`.

        Design: Corner/validations/future_dated_operations_are_refused_against_the_logical_clock
        """
        context = fx.eligible_sire(
            api, registration_code="REG-TM", facility_overrides={"code": "F-TM"}
        )
        fx.advance_clock(api, self.LATE_CLOCK)

        validate_error(
            api.order_health_test(
                context["sire"]["id"],
                factories.health_test_payload(
                    context["facility"]["id"], "IBR", sample_date="2026-09-15"
                ),
                fx.VET,
            ),
            ApiErrorId.ERR_SAMPLE_DATE_FUTURE.value,
            422,
        )

        today = validate_success(
            api.order_health_test(
                context["sire"]["id"],
                factories.health_test_payload(
                    context["facility"]["id"], "IBR", sample_date="2026-09-10"
                ),
                fx.VET,
            ),
            201,
        )
        assert today["result"] == "PENDING"
        assert today["sample_date"] == "2026-09-10"

    def test_a_refused_clock_move_changes_nothing(self, api):
        """The clock is strictly monotonic: an instant equal to or earlier than the
        stored one is refused with `ERR_CLOCK_REWIND`.

        Design: Corner/validations/future_dated_operations_are_refused_against_the_logical_clock
        """
        context = fx.eligible_sire(
            api, registration_code="REG-TM", facility_overrides={"code": "F-TM"}
        )
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-TM"},
            tank_overrides={"serial": "TK-TM"},
        )
        fx.advance_clock(api, self.LATE_CLOCK)
        # Ten whole days at 2.0 points each, from the 95.0 the tank opened with.
        before = fx.read_tank(api, partner["tank"]["id"])
        assert before["ln2_level_pct"] == pytest.approx(75.0, abs=0.01)
        assert before["tank_status"] == "IN_SERVICE"

        validate_error(
            api.set_clock(self.LATE_CLOCK, fx.DIRECTOR),
            ApiErrorId.ERR_CLOCK_REWIND.value,
            422,
        )
        validate_error(
            api.set_clock("2026-09-09T23:59:59Z", fx.DIRECTOR),
            ApiErrorId.ERR_CLOCK_REWIND.value,
            422,
        )

        after = fx.read_tank(api, partner["tank"]["id"])
        assert after["ln2_level_pct"] == pytest.approx(75.0, abs=0.01)
        assert after["tank_status"] == "IN_SERVICE"
        assert after["service_count"] == 0
        still_eligible = fx.read_sire(api, context["sire"]["id"])
        assert still_eligible["collection_status"] == "ELIGIBLE"
        assert still_eligible["suspension_reason"] is None
        for test in context["health_tests"].values():
            assert fx.read_health_test(api, test["id"])["result"] == "NEGATIVE"


class TestTankCapacityAggregate:
    """Each dispatch fits; the running sum over open transfers does not."""

    @staticmethod
    def _two_approved_transfers(api):
        context = fx.released_lot(
            api,
            registration_code="REG-CAP",
            facility_overrides={"code": "F-CAP"},
            straw_count=200,
            processing_cost_cents=250000,
        )
        assert context["lot"]["unit_book_value_cents"] == 1250
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-CAP", "credit_limit_cents": 100000000},
            tank_overrides={"serial": "TK-CAP", "capacity_straws": 150},
        )
        approved = []
        for _ in range(2):
            requested = fx.request_consignment(
                api,
                context["lot"]["id"],
                partner["distributor"]["id"],
                partner["tank"]["id"],
                doses=100,
                unit_price_cents=4000,
            )
            approved.append(fx.approve_transfer(api, requested["id"]))
        # Approval reserves doses but puts nothing on the shelf yet.
        assert fx.read_tank(api, partner["tank"]["id"])["straws_on_hand"] == 0
        first = fx.dispatch_transfer(api, approved[0]["id"])
        return {**context, **partner, "first": first, "second": approved[1]}

    def test_the_second_dispatch_overfills_the_shelf(self, api):
        """Dispatch snapshots `tank_service_count_at_dispatch` ... re-derives the
        tank's `straws_on_hand`, since the doses now count against tank capacity,
        and re-checks that capacity, reporting `ERR_TANK_CAPACITY_EXCEEDED` if the
        tank would be overfilled.

        Design: Corner/validations/tank_capacity_is_an_aggregate_over_open_transfers
        """
        context = self._two_approved_transfers(api)
        tank = fx.read_tank(api, context["tank"]["id"])
        assert tank["straws_on_hand"] == 100
        assert tank["capacity_straws"] == 150
        assert context["first"]["status"] == "IN_TRANSIT"

        validate_error(
            api.dispatch_consignment_transfer(
                context["second"]["id"], factories.transfer_dispatch_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_TANK_CAPACITY_EXCEEDED.value,
            422,
        )

        refused = fx.read_transfer(api, context["second"]["id"])
        assert refused["status"] == "APPROVED"
        assert refused["tank_service_count_at_dispatch"] is None
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 0, 200, 0, 0, 0)
        assert fx.read_tank(api, context["tank"]["id"])["straws_on_hand"] == 100

    def test_closing_a_consignment_frees_the_shelf_for_the_refused_one(self, api):
        """A tank read also exposes `straws_on_hand`, the sum of the
        still-outstanding doses across the tank's `IN_TRANSIT` and `RECEIVED`
        consignments.

        Design: Corner/validations/tank_capacity_is_an_aggregate_over_open_transfers
        """
        context = self._two_approved_transfers(api)
        distributor_id = context["distributor"]["id"]

        received = fx.receive_transfer(api, context["first"]["id"], distributor_id)
        assert received["status"] == "RECEIVED"
        assert fx.read_tank(api, context["tank"]["id"])["straws_on_hand"] == 100

        reconciled = fx.report_usage(api, context["first"]["id"], distributor_id, 100)
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["doses_on_hand"] == 0
        assert fx.read_tank(api, context["tank"]["id"])["straws_on_hand"] == 0

        dispatched = fx.dispatch_transfer(api, context["second"]["id"])
        assert dispatched["status"] == "IN_TRANSIT"
        assert dispatched["tank_service_count_at_dispatch"] == 0
        assert fx.read_tank(api, context["tank"]["id"])["straws_on_hand"] == 100
        assert_buckets(fx.read_lot(api, context["lot"]["id"]), 0, 100, 0, 100, 0)


class TestProductLineFieldsAndDestinationFlags:
    """Purity belongs to SEXED alone, and the flags gate submission only."""

    @staticmethod
    def _an_accepted_ejaculate(api):
        context = fx.accepted_ejaculate(
            api,
            registration_code="REG-PL",
            facility_overrides={"code": "F-PL", "approved_export_countries": ["CA", "MX"]},
        )
        assert context["ejaculate"]["total_doses_theoretical"] == 480
        return context

    @classmethod
    def _lots_of_every_product_line(cls, api):
        context = cls._an_accepted_ejaculate(api)
        canada = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
            sexed_semen_allowed=False,
            embryo_allowed=True,
        )
        mexico = fx.register_country_requirement(
            api,
            country_code="MX",
            required_test_types=["IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
            sexed_semen_allowed=True,
            embryo_allowed=True,
        )
        lots = {
            "CONVENTIONAL": fx.cut_lot(
                api, context["ejaculate"]["id"], "CONVENTIONAL", 100, 250000
            ),
            "SEXED": fx.cut_lot(
                api,
                context["ejaculate"]["id"],
                "SEXED",
                100,
                250000,
                sexing_purity_pct=90.0,
            ),
            "EMBRYO": fx.cut_lot(api, context["ejaculate"]["id"], "EMBRYO", 100, 250000),
        }
        return {**context, "canada": canada, "mexico": mexico, "lots": lots}

    def test_purity_is_required_for_sexed_and_forbidden_elsewhere(self, api):
        """Sorted-sperm purity is conditional on the product line: a `SEXED` lot must
        supply `sexing_purity_pct` within 50.0 to 99.9, while a `CONVENTIONAL` or
        `EMBRYO` lot must omit it entirely — a value supplied on a non-sexed lot is
        an error rather than an ignored key, and either fault reports
        `ERR_PRODUCT_LINE_FIELDS`.

        Design: Corner/validations/product_line_fields_and_destination_flags_are_conditional
        """
        context = self._an_accepted_ejaculate(api)
        ejaculate_id = context["ejaculate"]["id"]

        def cut(product_line, **overrides):
            return api.cut_straw_lot(
                ejaculate_id,
                factories.straw_lot_payload(product_line, 100, 250000, **overrides),
                fx.TECH,
            )

        validate_error(
            cut("CONVENTIONAL", sexing_purity_pct=90.0),
            ApiErrorId.ERR_PRODUCT_LINE_FIELDS.value,
            422,
        )
        validate_error(cut("SEXED"), ApiErrorId.ERR_PRODUCT_LINE_FIELDS.value, 422)
        validate_error(
            cut("EMBRYO", sexing_purity_pct=90.0),
            ApiErrorId.ERR_PRODUCT_LINE_FIELDS.value,
            422,
        )
        validate_error(
            cut("SEXED", sexing_purity_pct=49.9),
            ApiErrorId.ERR_PRODUCT_LINE_FIELDS.value,
            422,
        )

        low = validate_success(cut("SEXED", sexing_purity_pct=50.0), 201)
        assert low["sexing_purity_pct"] == pytest.approx(50.0, abs=0.01)
        high = validate_success(cut("SEXED", sexing_purity_pct=99.9), 201)
        assert high["sexing_purity_pct"] == pytest.approx(99.9, abs=0.01)
        _rows, meta = validate_paginated(
            api.list_straw_lots(fx.TECH, {"ejaculate_id": ejaculate_id})
        )
        assert meta["total_count"] == 2

    def test_the_sexed_flag_gates_submission_only(self, api):
        """The lot's `product_line` must be permitted by the destination's flags — a
        `SEXED` lot requires `sexed_semen_allowed` to be true ... and a violation
        reports `ERR_PRODUCT_NOT_PERMITTED`.

        Design: Corner/validations/product_line_fields_and_destination_flags_are_conditional
        """
        context = self._lots_of_every_product_line(api)
        sire_id = context["sire"]["id"]
        sexed = context["lots"]["SEXED"]

        refused = fx.draft_certificate(api, sire_id, sexed["id"], context["canada"]["id"])
        assert refused["destination_country_code"] == "CA"
        validate_error(
            api.submit_export_certificate(
                refused["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            ApiErrorId.ERR_PRODUCT_NOT_PERMITTED.value,
            422,
        )
        still_draft = fx.read_certificate(api, refused["id"])
        assert still_draft["status"] == "DRAFT"
        assert still_draft["submission_round"] == 0

        # The same lot, a destination that allows sorted semen.
        permitted = fx.submitted_certificate(
            api, sire_id, sexed["id"], context["mexico"]["id"]
        )
        assert permitted["status"] == "SUBMITTED"
        assert permitted["submission_round"] == 1

    def test_the_two_flags_are_read_independently(self, api):
        """... while a `CONVENTIONAL` lot is gated by neither ... and an `EMBRYO` lot
        requires `embryo_allowed` to be true.

        Design: Corner/validations/product_line_fields_and_destination_flags_are_conditional
        """
        context = self._lots_of_every_product_line(api)
        sire_id = context["sire"]["id"]
        canada = context["canada"]["id"]

        conventional = fx.submitted_certificate(
            api, sire_id, context["lots"]["CONVENTIONAL"]["id"], canada
        )
        assert conventional["status"] == "SUBMITTED"
        assert conventional["submission_round"] == 1

        embryo = fx.submitted_certificate(
            api, sire_id, context["lots"]["EMBRYO"]["id"], canada
        )
        assert embryo["status"] == "SUBMITTED"
        assert embryo["submission_round"] == 1


class TestDestinationApprovalResolvesOriginFacility:
    """Certificate to lot to ejaculate to booking to facility, then the rules."""

    @staticmethod
    def _two_bulls_and_their_lots(api):
        facility = fx.register_facility(
            api,
            code="F-CAS",
            housing_capacity=2,
            bench_capacity=2,
            approved_export_countries=["CA"],
        )
        canada = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
        )
        mexico = fx.register_country_requirement(
            api,
            country_code="MX",
            required_test_types=["IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
        )

        bulls = []
        for code, isolation_days in (("REG-CAS", 30), ("REG-CAS-14", 14)):
            sire = fx.register_sire(api, registration_code=code)
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"], isolation_days)
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
        bookings = [
            fx.book_collection(api, sire["id"], facility["id"]) for sire in bulls
        ]
        fx.advance_clock(api, fx.CLOCK_AT_COLLECTION)

        lots = []
        for booking in bookings:
            fx.complete_collection(api, booking["id"], facility["id"])
            ejaculate = fx.discover_ejaculate(api, booking["id"])
            fx.evaluate_qc(api, ejaculate["id"])
            cut = fx.cut_lot(api, ejaculate["id"], "CONVENTIONAL", 100, 125000)
            lots.append(fx.release_lot(api, cut["id"]))

        assert fx.read_sire(api, bulls[0]["id"])["isolation_days_applied"] == 30
        assert fx.read_sire(api, bulls[1]["id"])["isolation_days_applied"] == 14
        return {
            "facility": facility,
            "canada": canada,
            "mexico": mexico,
            "bulls": bulls,
            "lots": lots,
        }

    def test_the_destination_must_sit_in_the_collecting_sites_approved_list(self, api):
        """That facility's `approved_export_countries` must contain the certificate's
        `destination_country_code`, failing which `ERR_DESTINATION_NOT_APPROVED`.

        Design: Corner/validations/destination_approval_resolves_the_lot_to_its_origin_facility
        """
        context = self._two_bulls_and_their_lots(api)
        sire_id = context["bulls"][0]["id"]
        lot = context["lots"][0]

        refused = fx.draft_certificate(api, sire_id, lot["id"], context["mexico"]["id"])
        assert refused["submission_round"] == 0
        validate_error(
            api.submit_export_certificate(
                refused["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            ApiErrorId.ERR_DESTINATION_NOT_APPROVED.value,
            422,
        )
        # A refused submission consumes no part of the three-round budget.
        stalled = fx.read_certificate(api, refused["id"])
        assert stalled["status"] == "DRAFT"
        assert stalled["submission_round"] == 0

        approved_destination = fx.submitted_certificate(
            api, sire_id, lot["id"], context["canada"]["id"]
        )
        assert approved_destination["status"] == "SUBMITTED"
        assert approved_destination["submission_round"] == 1

        # US is always permitted, whatever the site's export list says.
        domestic = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-CAS", "credit_limit_cents": 10000000},
            tank_overrides={"serial": "TK-CAS"},
        )
        shipped = validate_success(
            api.request_consignment_transfer(
                lot["id"],
                factories.consignment_request_payload(
                    domestic["distributor"]["id"],
                    domestic["tank"]["id"],
                    fx.read_lot(api, lot["id"])["version"],
                    doses=10,
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert shipped["status"] == "REQUESTED"

    def test_a_suspended_origin_site_wins_over_the_destination_rule(self, api):
        """The facility that housed the bull must still be `APPROVED`, failing which
        `ERR_FACILITY_SUSPENDED`, and that facility's `approved_export_countries`
        must contain the certificate's `destination_country_code`.

        Design: Corner/validations/destination_approval_resolves_the_lot_to_its_origin_facility
        """
        context = self._two_bulls_and_their_lots(api)
        certificate = fx.draft_certificate(
            api,
            context["bulls"][0]["id"],
            context["lots"][0]["id"],
            context["canada"]["id"],
        )

        suspended = fx.suspend_facility(api, context["facility"]["id"])
        assert suspended["approval_status"] == "SUSPENDED"

        validate_error(
            api.submit_export_certificate(
                certificate["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            ApiErrorId.ERR_FACILITY_SUSPENDED.value,
            409,
        )
        assert fx.read_certificate(api, certificate["id"])["submission_round"] == 0

    def test_a_short_quarantine_is_caught_after_the_destination(self, api):
        """The bull's `isolation_days_applied` must be at least the destination's
        `min_isolation_days`, with the boundary inclusive so that exactly the minimum
        passes, and a shortfall reports `ERR_ISOLATION_TOO_SHORT`.

        Design: Corner/validations/destination_approval_resolves_the_lot_to_its_origin_facility
        """
        context = self._two_bulls_and_their_lots(api)
        short_bull = context["bulls"][1]
        certificate = fx.draft_certificate(
            api, short_bull["id"], context["lots"][1]["id"], context["canada"]["id"]
        )

        validate_error(
            api.submit_export_certificate(
                certificate["id"], factories.certificate_submit_payload(), fx.COORDINATOR
            ),
            ApiErrorId.ERR_ISOLATION_TOO_SHORT.value,
            422,
        )
        assert fx.read_certificate(api, certificate["id"])["status"] == "DRAFT"


class TestPendingTestUniquenessAndRetestTargets:
    """One outstanding assay per type, and retests that must match their target."""

    @staticmethod
    def _a_bull_with_a_mixed_test_history(api):
        facility = fx.register_facility(api, code="F-HT", housing_capacity=2)
        bulls = []
        for code in ("REG-HT", "REG-HT2"):
            sire = fx.register_sire(api, registration_code=code)
            fx.contract_sire(api, sire["id"])
            fx.house_sire(api, sire["id"], facility["id"])
            bulls.append(sire)

        pending_ibr = fx.order_health_test(api, bulls[0]["id"], facility["id"], "IBR")
        assert pending_ibr["result"] == "PENDING"
        assert pending_ibr["valid_until"] is None
        negative_bvd = fx.negative_test(api, bulls[0]["id"], facility["id"], "BVD")
        positive_bluetongue = fx.result_health_test(
            api,
            fx.order_health_test(api, bulls[0]["id"], facility["id"], "BLUETONGUE")["id"],
            "POSITIVE",
        )
        stranger_positive_bvd = fx.result_health_test(
            api,
            fx.order_health_test(api, bulls[1]["id"], facility["id"], "BVD")["id"],
            "POSITIVE",
        )
        # A positive assay only suspends an ELIGIBLE bull; these two are in ISOLATION.
        assert fx.read_sire(api, bulls[0]["id"])["collection_status"] == "ISOLATION"
        return {
            "facility": facility,
            "bulls": bulls,
            "pending_ibr": pending_ibr,
            "negative_bvd": negative_bvd,
            "positive_bluetongue": positive_bluetongue,
            "stranger_positive_bvd": stranger_positive_bvd,
        }

    def test_only_one_pending_assay_of_a_type_may_be_outstanding(self, api):
        """A bull may not carry two `PENDING` tests of the same `test_type` at once —
        the outstanding one must be resulted first, or the order is refused with
        `ERR_DUPLICATE_PENDING_TEST`.

        Design: Corner/validations/pending_test_uniqueness_and_retest_targets_are_enforced
        """
        context = self._a_bull_with_a_mixed_test_history(api)
        sire_id = context["bulls"][0]["id"]
        facility_id = context["facility"]["id"]

        validate_error(
            api.order_health_test(
                sire_id, factories.health_test_payload(facility_id, "IBR"), fx.VET
            ),
            ApiErrorId.ERR_DUPLICATE_PENDING_TEST.value,
            409,
        )
        _rows, meta = validate_paginated(
            api.list_health_tests(fx.VET, {"sire_id": sire_id, "test_type": "IBR"})
        )
        assert meta["total_count"] == 1

        # The rule is per type, so another assay may be outstanding beside it.
        other_type = fx.order_health_test(api, sire_id, facility_id, "TRICHOMONIASIS")
        assert other_type["result"] == "PENDING"

        # Resulting the outstanding row frees the type again.
        fx.result_health_test(api, context["pending_ibr"]["id"], "INCONCLUSIVE")
        replacement = fx.order_health_test(api, sire_id, facility_id, "IBR")
        assert replacement["result"] == "PENDING"

    def test_a_retest_target_must_be_the_same_bulls_ambiguous_row_of_that_type(self, api):
        """That target must belong to the same bull, be of the same `test_type`, and
        carry a `result` of either `POSITIVE` or `INCONCLUSIVE`; anything else —
        another bull's test, another type, or a test that is still `PENDING`,
        `NEGATIVE` or `EXPIRED` — is rejected with `ERR_INVALID_RETEST_TARGET`.

        Design: Corner/validations/pending_test_uniqueness_and_retest_targets_are_enforced
        """
        context = self._a_bull_with_a_mixed_test_history(api)
        sire_id = context["bulls"][0]["id"]
        facility_id = context["facility"]["id"]

        def retest(test_type, target_id):
            return api.order_health_test(
                sire_id,
                factories.health_test_payload(
                    facility_id, test_type, retest_of_test_id=target_id
                ),
                fx.VET,
            )

        # A settled NEGATIVE row is nothing to re-run.
        validate_error(
            retest("BVD", context["negative_bvd"]["id"]),
            ApiErrorId.ERR_INVALID_RETEST_TARGET.value,
            422,
        )
        # The right bull and a positive target, but the wrong assay type.
        validate_error(
            retest("BVD", context["positive_bluetongue"]["id"]),
            ApiErrorId.ERR_INVALID_RETEST_TARGET.value,
            422,
        )
        # The right type and a positive target, but another bull's row.
        validate_error(
            retest("BVD", context["stranger_positive_bvd"]["id"]),
            ApiErrorId.ERR_INVALID_RETEST_TARGET.value,
            422,
        )
        # A PENDING target is no better -- but PRD 2.10 puts the outstanding-pending
        # rule in band four and the retest-target rule in the referential band, so a
        # same-type PENDING target answers with the earlier of the two codes.
        validate_error(
            retest("IBR", context["pending_ibr"]["id"]),
            ApiErrorId.ERR_DUPLICATE_PENDING_TEST.value,
            409,
        )

    def test_the_matching_retest_is_filed_against_its_own_positive_row(self, api):
        """When an earlier assay came back ambiguous, the follow-up sample is filed
        with `retest_of_test_id` pointing at the row it re-runs. ... Tests are listed
        and filtered by ... `retest_of_test_id`, the last of which reaches every
        retest descended from a given ambiguous result.

        Design: Corner/validations/pending_test_uniqueness_and_retest_targets_are_enforced
        """
        context = self._a_bull_with_a_mixed_test_history(api)
        target = context["positive_bluetongue"]
        assert target["result"] == "POSITIVE"

        follow_up = fx.order_health_test(
            api,
            context["bulls"][0]["id"],
            context["facility"]["id"],
            "BLUETONGUE",
            retest_of_test_id=target["id"],
        )
        assert follow_up["result"] == "PENDING"
        assert follow_up["retest_of_test_id"] == target["id"]

        descendants, meta = validate_paginated(
            api.list_health_tests(fx.VET, {"retest_of_test_id": target["id"]})
        )
        assert meta["total_count"] == 1
        assert descendants[0]["id"] == follow_up["id"]
