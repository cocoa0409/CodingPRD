"""Pairs of rules that a single request violates at once, and which one answers."""

import pytest

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures as fx,
    make_facility_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestLotStateOutranksTankOwnership:
    """A consignment request wrong on both counts reports the lot state."""

    @staticmethod
    def _quarantine_lot_and_two_partners(api):
        context = fx.quarantine_lot(
            api,
            facility_overrides={
                "code": "F-IA-09",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            sire_overrides={
                "breed": "ANGUS",
                "birth_date": "2022-06-01",
                "acquisition_cost_cents": 900000,
            },
            product_line="CONVENTIONAL",
            straw_count=200,
            processing_cost_cents=250000,
        )
        context["alpha"] = fx.register_distributor(
            api, name="D-ALPHA", country_code="US", credit_limit_cents=100000000
        )
        context["beta"] = fx.register_distributor(
            api, name="D-BETA", country_code="US"
        )
        context["beta_tank"] = fx.register_tank(
            api, context["beta"]["id"], serial="TK-B", capacity_straws=500
        )
        return context

    def test_a_quarantine_lot_answers_before_the_tank_owner_is_checked(self, api):
        """The lot's `distribution_status` must be `RELEASED`: `QUARANTINE`,
        `REJECTED` and `DEPLETED` lots cannot be consigned, and the refusal is
        `ERR_LOT_NOT_RELEASED`, evaluated **before** the tank-ownership rule so a
        request that is wrong on both counts reports the lot-state error.

        Design: Difficulty/priority_pair_validation_conflict/lot_state_outranks_tank_ownership_on_transfer_create
        """
        context = self._quarantine_lot_and_two_partners(api)
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["distribution_status"] == "QUARANTINE"

        validate_error(
            api.request_consignment_transfer(
                lot["id"],
                factories.consignment_request_payload(
                    context["alpha"]["id"],
                    context["beta_tank"]["id"],
                    lot["version"],
                    doses=150,
                    unit_price_cents=4000,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_LOT_NOT_RELEASED.value,
            409,
        )

        rows, meta = validate_paginated(
            api.list_consignment_transfers(fx.DIRECTOR, {"straw_lot_id": lot["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_tank_ownership_answers_once_the_lot_is_released(self, api):
        """The destination tank must belong to the named consignee — its
        `distributor_id` must equal the body's `distributor_id` — or
        `ERR_TANK_NOT_OWNED_BY_DISTRIBUTOR`.

        Design: Difficulty/priority_pair_validation_conflict/lot_state_outranks_tank_ownership_on_transfer_create
        """
        context = self._quarantine_lot_and_two_partners(api)
        fx.release_lot(api, context["lot"]["id"])
        released = fx.read_lot(api, context["lot"]["id"])
        assert released["distribution_status"] == "RELEASED"

        validate_error(
            api.request_consignment_transfer(
                released["id"],
                factories.consignment_request_payload(
                    context["alpha"]["id"],
                    context["beta_tank"]["id"],
                    released["version"],
                    doses=150,
                    unit_price_cents=4000,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_TANK_NOT_OWNED_BY_DISTRIBUTOR.value,
            422,
        )

        own_tank = fx.register_tank(
            api, context["alpha"]["id"], serial="TK-A", capacity_straws=500
        )
        accepted = validate_success(
            api.request_consignment_transfer(
                released["id"],
                factories.consignment_request_payload(
                    context["alpha"]["id"],
                    own_tank["id"],
                    released["version"],
                    doses=150,
                    unit_price_cents=4000,
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert accepted["status"] == "REQUESTED"


class TestHealthCurrencyOutranksCreditLimit:
    """A consignment both health-blocked and over the limit answers on health."""

    BLUETONGUE_LAPSE_CLOCK = "2026-09-15T00:00:00Z"

    @classmethod
    def _requested_consignment_then_lapse(cls, api):
        """150 doses at 1250 cents a straw against a 100000 cent credit limit."""
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-IA-07",
                "housing_capacity": 2,
                "bench_capacity": 1,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
            per_type_validity_days={"BLUETONGUE": 45},
            straw_count=200,
            processing_cost_cents=250000,
        )
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-TIGHT", "credit_limit_cents": 100000},
            tank_overrides={"serial": "TK-A", "capacity_straws": 500},
        )
        context.update(partner)
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == 1250
        context["transfer"] = fx.request_consignment(
            api,
            lot["id"],
            partner["distributor"]["id"],
            partner["tank"]["id"],
            doses=150,
            unit_price_cents=1250,
        )
        sweep = fx.advance_clock(api, cls.BLUETONGUE_LAPSE_CLOCK)
        assert context["health_tests"]["BLUETONGUE"]["id"] in sweep["expired_health_test_ids"]
        return context

    def test_the_health_failure_answers_before_the_credit_projection(self, api):
        """A consignment approval blocked on health currency reports
        `ERR_HEALTH_TESTS_NOT_CURRENT` even when the projected exposure also
        breaks the credit limit.

        Design: Difficulty/priority_pair_validation_conflict/health_safety_outranks_credit_limit_on_transfer_approve
        """
        context = self._requested_consignment_then_lapse(api)
        transfer = context["transfer"]

        validate_error(
            api.approve_consignment_transfer(
                transfer["id"], factories.transfer_approve_payload(), fx.DIRECTOR
            ),
            ApiErrorId.ERR_HEALTH_TESTS_NOT_CURRENT.value,
            422,
        )

        unchanged = fx.read_transfer(api, transfer["id"])
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["approved_by_user_id"] is None

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["doses_available"] == 200
        assert lot["doses_reserved"] == 0

    def test_the_credit_gate_answers_once_health_currency_is_restored(self, api):
        """The projection adds the requested `doses` multiplied by the lot's
        `unit_book_value_cents`, and approval is permitted only when that
        projected figure is at most `credit_limit_cents`. The comparison is
        inclusive, so a projection landing exactly on the limit is approved, and
        a projection above it is refused with `ERR_CREDIT_LIMIT_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/health_safety_outranks_credit_limit_on_transfer_approve
        """
        context = self._requested_consignment_then_lapse(api)
        fx.negative_test(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            "BLUETONGUE",
            sample_date="2026-09-15",
            validity_days=365,
        )

        validate_error(
            api.approve_consignment_transfer(
                context["transfer"]["id"],
                factories.transfer_approve_payload(),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value,
            422,
        )

        exact = fx.request_consignment(
            api,
            context["lot"]["id"],
            context["distributor"]["id"],
            context["tank"]["id"],
            doses=80,
            unit_price_cents=1250,
        )
        approved = fx.approve_transfer(api, exact["id"])
        assert approved["status"] == "APPROVED"

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["doses_available"] == 120
        assert lot["doses_reserved"] == 80


class TestFacilityResidencyOutranksRestBuffer:
    """A booking at the wrong site inside the rest window reports the wrong site."""

    FIRST_START = "2026-09-01T08:00:00Z"
    FIRST_END = "2026-09-01T10:00:00Z"
    TIGHT_START = "2026-09-02T10:00:00Z"
    TIGHT_END = "2026-09-02T12:00:00Z"
    SPACED_START = "2026-09-03T10:00:00Z"
    SPACED_END = "2026-09-03T12:00:00Z"

    @classmethod
    def _bull_with_one_completed_booking(cls, api):
        context = fx.collected_ejaculate(
            api,
            start_at=cls.FIRST_START,
            end_at=cls.FIRST_END,
            collection_clock=cls.FIRST_START,
            facility_overrides={
                "code": "F-IA-10",
                "housing_capacity": 2,
                "bench_capacity": 2,
                "approved_export_countries": ["CA"],
            },
            registration_code="REG-B",
        )
        fx.advance_clock(api, cls.FIRST_END)
        context["other_facility"] = fx.register_facility(
            api,
            code="F-IA-11",
            name="Cedar Valley Annex",
            housing_capacity=2,
            bench_capacity=2,
        )
        return context

    def test_the_wrong_site_answers_before_the_rest_window(self, api):
        """He must actually live there — his `housing_facility_id` must equal the
        booking's `facility_id` — or `ERR_SIRE_NOT_AT_FACILITY`, and that
        referential check is evaluated *before* the rest-buffer rule, so a
        booking that is at the wrong site and inside the rest window reports the
        wrong-site error.

        Design: Difficulty/priority_pair_validation_conflict/facility_residency_outranks_rest_buffer_on_booking_create
        """
        context = self._bull_with_one_completed_booking(api)
        elsewhere = context["other_facility"]

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], elsewhere["id"], self.TIGHT_START, self.TIGHT_END
                ),
                make_facility_headers(elsewhere["id"]),
            ),
            ApiErrorId.ERR_SIRE_NOT_AT_FACILITY.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_bookings(fx.DIRECTOR, {"sire_id": context["sire"]["id"]})
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == context["booking"]["id"]

    def test_the_rest_window_answers_at_the_bull_s_own_site(self, api):
        """A new window's `start_at` must be at least 48 hours after the `end_at`
        of the bull's most recent `SCHEDULED` or `COMPLETED` booking, and at
        least 48 hours before the `start_at` of his next one. Both boundaries are
        closed, so a gap of exactly 48 hours is permitted; anything tighter is
        `ERR_SIRE_REST_BUFFER`.

        Design: Difficulty/priority_pair_validation_conflict/facility_residency_outranks_rest_buffer_on_booking_create
        """
        context = self._bull_with_one_completed_booking(api)
        home = context["facility"]

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], home["id"], self.TIGHT_START, self.TIGHT_END
                ),
                make_facility_headers(home["id"]),
            ),
            ApiErrorId.ERR_SIRE_REST_BUFFER.value,
            422,
        )

        spaced = validate_success(
            api.create_booking(
                factories.booking_payload(
                    context["sire"]["id"], home["id"], self.SPACED_START, self.SPACED_END
                ),
                make_facility_headers(home["id"]),
            ),
            201,
        )
        assert spaced["status"] == "SCHEDULED"
        assert spaced["start_at"] == "2026-09-03T10:00:00.000Z"
