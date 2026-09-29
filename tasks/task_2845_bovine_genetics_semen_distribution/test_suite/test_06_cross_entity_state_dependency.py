"""Operations refused because of the state of a third row the caller never named."""

import pytest

from test_helpers import (
    VET_ALT_USER_ID,
    ApiErrorId,
    factories,
    fixtures as fx,
    make_facility_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBookingBlockedByTargetFacilitySuspension:
    """The booking row is faultless; the target facility is not APPROVED."""

    WINDOW_START = "2026-09-20T08:00:00Z"
    WINDOW_END = "2026-09-20T10:00:00Z"

    @staticmethod
    def _eligible_bull_and_a_suspended_annex(api):
        context = fx.eligible_sire(
            api,
            facility_overrides={
                "code": "F-IA-12",
                "housing_capacity": 4,
                "bench_capacity": 2,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
        )
        annex = fx.register_facility(
            api,
            code="F-IA-13",
            name="Cedar Valley Annex",
            housing_capacity=4,
            bench_capacity=2,
        )
        assert annex["approval_status"] == "APPROVED"
        context["annex"] = fx.suspend_facility(
            api, annex["id"], suspension_reason="LN2_SUPPLY_FAILURE"
        )
        return context

    def test_the_suspended_bench_refuses_a_booking_for_a_bull_housed_elsewhere(self, api):
        """The facility's `approval_status` must be `APPROVED`, or
        `ERR_FACILITY_SUSPENDED`.

        Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_target_facility_suspension
        """
        context = self._eligible_bull_and_a_suspended_annex(api)
        annex = context["annex"]
        assert annex["approval_status"] == "SUSPENDED"
        assert annex["suspension_reason"] == "LN2_SUPPLY_FAILURE"

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], annex["id"], self.WINDOW_START, self.WINDOW_END
                ),
                make_facility_headers(annex["id"]),
            ),
            ApiErrorId.ERR_FACILITY_SUSPENDED.value,
            409,
        )

        assert fx.read_sire(api, context["sire"]["id"])["collection_status"] == "ELIGIBLE"
        rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"facility_id": annex["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_reinstating_the_annex_hands_the_refusal_to_the_next_rule(self, api):
        """He must actually live there — his `housing_facility_id` must equal the
        booking's `facility_id` — or `ERR_SIRE_NOT_AT_FACILITY`.

        Design: Difficulty/cross_entity_state_dependency/booking_blocked_by_target_facility_suspension
        """
        context = self._eligible_bull_and_a_suspended_annex(api)
        annex = context["annex"]

        reinstated = fx.approve_facility(api, annex["id"])
        assert reinstated["approval_status"] == "APPROVED"
        assert reinstated["suspension_reason"] is None

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], annex["id"], self.WINDOW_START, self.WINDOW_END
                ),
                make_facility_headers(annex["id"]),
            ),
            ApiErrorId.ERR_SIRE_NOT_AT_FACILITY.value,
            422,
        )

        home = context["facility"]
        booked = validate_success(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], home["id"], self.WINDOW_START, self.WINDOW_END
                ),
                make_facility_headers(home["id"]),
            ),
            201,
        )
        assert booked["status"] == "SCHEDULED"
        assert booked["facility_id"] == home["id"]


class TestConsignmentReceiveBlockedByTankOutOfService:
    """The shipment is in flight; its destination tank boiled dry en route."""

    EMPTY_TANK_CLOCK = "2026-10-28T08:00:00Z"

    @classmethod
    def _in_transit_into_a_tank_that_boils_dry(cls, api):
        context = fx.received_consignment(
            api,
            facility_overrides={
                "code": "F-IA-18",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            straw_count=300,
            processing_cost_cents=375000,
            distributor_overrides={"name": "D-GOLF", "credit_limit_cents": 100000000},
            tank_overrides={
                "serial": "TK-G",
                "capacity_straws": 500,
                "service_interval_days": 60,
                "initial_fill_pct": 95.0,
            },
            doses=40,
            unit_price_cents=4000,
            stop_after="IN_TRANSIT",
        )
        sweep = fx.advance_clock(api, cls.EMPTY_TANK_CLOCK)
        assert context["tank"]["id"] in sweep["out_of_service_tank_ids"]
        return context

    def test_an_empty_tank_can_receive_nothing_at_all(self, api):
        """`SERVICE_DUE → OUT_OF_SERVICE` fires on a clock move when the recomputed
        level reaches exactly 0, and the tank can then receive nothing at all.

        Design: Difficulty/cross_entity_state_dependency/consignment_receive_blocked_by_tank_out_of_service
        """
        context = self._in_transit_into_a_tank_that_boils_dry(api)
        tank = fx.read_tank(api, context["tank"]["id"])
        assert tank["ln2_level_pct"] == pytest.approx(0.0, abs=0.05)
        assert tank["tank_status"] == "OUT_OF_SERVICE"
        assert context["transfer"]["status"] == "IN_TRANSIT"

        validate_error(
            api.receive_consignment_transfer(
                context["transfer"]["id"],
                factories.transfer_receive_payload(),
                context["distributor_headers"],
            ),
            ApiErrorId.ERR_TANK_OUT_OF_SERVICE.value,
            409,
        )

        assert fx.read_transfer(api, context["transfer"]["id"])["status"] == "IN_TRANSIT"
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["doses_reserved"] == 40
        assert lot["doses_consigned"] == 0
        distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert distributor["consignment_value_cents"] == 0

    def test_refilling_the_tank_lets_the_same_arrival_through(self, api):
        """`IN_TRANSIT → RECEIVED` moves `doses` out of the lot's `doses_reserved`
        and into `doses_consigned`, stamps `received_at` from the logical clock,
        sets `carried_value_cents` to the transfer's `doses_on_hand` multiplied by
        the lot's `unit_book_value_cents`.

        Design: Difficulty/cross_entity_state_dependency/consignment_receive_blocked_by_tank_out_of_service
        """
        context = self._in_transit_into_a_tank_that_boils_dry(api)
        refilled = fx.service_tank(
            api,
            context["tank"]["id"],
            fill_pct=95.0,
            headers=context["distributor_headers"],
        )
        assert refilled["tank_status"] == "IN_SERVICE"

        received = fx.receive_transfer(
            api, context["transfer"]["id"], context["distributor"]["id"]
        )
        assert received["status"] == "RECEIVED"
        assert received["doses_on_hand"] == 40
        assert received["carried_value_cents"] == 50000

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["doses_reserved"] == 0
        assert lot["doses_consigned"] == 40
        distributor = fx.read_distributor(api, context["distributor"]["id"])
        assert distributor["consignment_value_cents"] == 50000


class TestCertificateIssueBlockedByLapsedCountryTest:
    """The dossier passed the same rule set at submit; one assay lapsed since."""

    COLLECTION_START = "2026-09-01T08:00:00Z"
    COLLECTION_END = "2026-09-01T10:00:00Z"
    IBR_LAPSE_CLOCK = "2026-09-10T00:00:00Z"

    @classmethod
    def _submitted_certificate_then_lapse(cls, api):
        requirement = fx.register_country_requirement(
            api,
            country_code="CA",
            required_test_types=["BLUETONGUE", "IBR"],
            max_test_age_days=60,
            min_isolation_days=21,
            sexed_semen_allowed=True,
            embryo_allowed=False,
        )
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-IA-14",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            per_type_validity_days={"IBR": 40},
            start_at=cls.COLLECTION_START,
            end_at=cls.COLLECTION_END,
            collection_clock=cls.COLLECTION_START,
            product_line="CONVENTIONAL",
            straw_count=200,
            processing_cost_cents=250000,
        )
        context["country_requirement"] = requirement
        context["certificate"] = fx.submitted_certificate(
            api, context["sire"]["id"], context["lot"]["id"], requirement["id"]
        )
        assert context["certificate"]["status"] == "SUBMITTED"
        assert context["certificate"]["submission_round"] == 1

        sweep = fx.advance_clock(api, cls.IBR_LAPSE_CLOCK)
        assert context["health_tests"]["IBR"]["id"] in sweep["expired_health_test_ids"]
        return context

    def test_a_lapsed_required_assay_stops_the_signature(self, api):
        """Then, for every `test_type` in the destination's `required_test_types`,
        there must exist a `HealthTest` for the certificate's `sire_id` of that
        type whose `result` is `NEGATIVE`, whose `valid_until` is strictly later
        than the logical clock... If any required type has no such row, issuance
        fails with `ERR_COUNTRY_TEST_MISSING`.

        Design: Difficulty/cross_entity_state_dependency/certificate_issue_blocked_by_lapsed_country_health_test
        """
        context = self._submitted_certificate_then_lapse(api)
        lapsed = fx.read_health_test(api, context["health_tests"]["IBR"]["id"])
        assert lapsed["result"] == "EXPIRED"
        still_good = fx.read_health_test(api, context["health_tests"]["BLUETONGUE"]["id"])
        assert still_good["result"] == "NEGATIVE"
        assert still_good["valid_until"] == "2027-08-01T00:00:00.000Z"

        validate_error(
            api.issue_export_certificate(
                context["certificate"]["id"],
                factories.certificate_issue_payload(),
                fx.VET_ALT,
            ),
            ApiErrorId.ERR_COUNTRY_TEST_MISSING.value,
            422,
        )

        untouched = fx.read_certificate(api, context["certificate"]["id"])
        assert untouched["status"] == "SUBMITTED"
        assert untouched["issued_by_user_id"] is None
        assert untouched["expires_at"] is None

    def test_a_replacement_assay_lets_the_identical_signature_through(self, api):
        """On success the row stores `issued_by_user_id` from the acting header and
        `issued_at` from the logical clock, and sets `expires_at` to the
        **earliest** `valid_until` among the chosen satisfying tests.

        Design: Difficulty/cross_entity_state_dependency/certificate_issue_blocked_by_lapsed_country_health_test
        """
        context = self._submitted_certificate_then_lapse(api)
        replacement = fx.negative_test(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            "IBR",
            sample_date="2026-09-10",
            validity_days=365,
        )
        assert replacement["result"] == "NEGATIVE"
        assert replacement["retest_of_test_id"] is None

        issued = fx.issue_certificate(api, context["certificate"]["id"])
        assert issued["status"] == "ISSUED"
        assert issued["issued_by_user_id"] == VET_ALT_USER_ID
        assert issued["expires_at"] == "2027-08-01T00:00:00.000Z"
