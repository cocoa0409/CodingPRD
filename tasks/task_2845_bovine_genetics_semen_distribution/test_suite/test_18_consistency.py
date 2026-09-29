"""Every write is complete when it returns, and every derived read is live."""

import pytest

from test_helpers import (
    ApiErrorId,
    assert_common_fields,
    assert_instant_equals,
    assert_row_unchanged,
    expected_ln2_level_pct,
    expected_market_unit_value_cents,
    expected_standard_unit_value_cents,
    factories,
    fixtures as fx,
    validate_error,
    validate_success,
)


class TestWritesAreVisibleInTheirOwnResponse:
    """The heaviest write in the system is also the proof of immediacy."""

    LOT_STRAWS = 100
    LOT_COST_CENTS = 50000
    PUBLICATION_CLOCK = "2026-09-15T00:00:00Z"

    def test_the_publication_response_already_carries_all_four_hops(self, api):
        """revaluation_delta_cents is a difference of two plant valuations.

        PRD 3.6: the evaluation's "`revaluation_delta_cents` records the plant
        inventory value immediately after hop 2 minus the plant inventory value
        immediately before it — a figure that is 0 for as long as the row
        remains a draft."
        PRD 2.4: "`updated_at` is the ISO 8601 UTC instant of the row's most
        recent mutation", so a response that serialised before its own cascade
        would be self-contradictory.

        Design: Corner/consistency model/every_accepted_write_is_fully_visible_in_its_own_response
        """
        context = fx.released_lot(
            api,
            registration_code="REG-IM",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        fx.advance_clock(api, self.PUBLICATION_CLOCK)
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )
        value_before = fx.plant_value(api)
        assert value_before == standard_unit * self.LOT_STRAWS

        draft = fx.file_evaluation(api, context["sire"]["id"])
        assert draft["status"] == "DRAFT"
        assert draft["revaluation_delta_cents"] == 0

        published = fx.publish_evaluation(api, draft["id"])
        market_unit = expected_market_unit_value_cents(
            published["composite_index"], "CONVENTIONAL"
        )
        assert published["status"] == "PUBLISHED"
        assert_instant_equals(published["published_at"], self.PUBLICATION_CLOCK)
        assert published["revaluation_delta_cents"] == (
            market_unit * self.LOT_STRAWS - value_before
        )

        reread = fx.read_evaluation(api, published["id"])
        assert reread["status"] == published["status"]
        assert reread["revaluation_delta_cents"] == published["revaluation_delta_cents"]
        assert_instant_equals(reread["published_at"], published["published_at"])

        bull = fx.read_sire(api, context["sire"]["id"])
        assert bull["published_composite_index"] == pytest.approx(
            published["composite_index"], abs=0.01
        )
        assert_instant_equals(
            bull["published_evaluation_effective_at"], published["effective_at"]
        )

        assert fx.plant_value(api) == value_before + published["revaluation_delta_cents"]
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == market_unit
        assert lot["valuation_basis"] == "MARKET_REVALUED"
        assert lot["pre_revaluation_unit_value_cents"] == standard_unit

    def test_a_creation_response_already_carries_what_its_by_id_read_returns(self, api):
        """The same immediacy holds for the smallest writes in the system.

        PRD 2.4: "`version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation of that row."
        PRD 3.8: a tank read "also exposes `straws_on_hand`, the sum of the
        still-outstanding doses across the tank's `IN_TRANSIT` and `RECEIVED`
        consignments."

        Design: Corner/consistency model/every_accepted_write_is_fully_visible_in_its_own_response
        """
        partner = validate_success(
            api.create_distributor(
                factories.distributor_payload(name="D-IM"), fx.DIRECTOR
            ),
            201,
        )
        assert_common_fields(partner)
        assert partner["version"] == 1
        assert partner["consignment_value_cents"] == 0
        assert partner["outstanding_balance_cents"] == 0
        assert partner["cumulative_doses_used"] == 0
        for field, value in partner.items():
            assert fx.read_distributor(api, partner["id"])[field] == value

        tank = validate_success(
            api.create_tank(
                factories.tank_payload(partner["id"], serial="TK-IM"), fx.DIRECTOR
            ),
            201,
        )
        assert_common_fields(tank)
        assert tank["straws_on_hand"] == 0
        assert tank["tank_status"] == "IN_SERVICE"
        for field, value in tank.items():
            assert fx.read_tank(api, tank["id"])[field] == value

        context = fx.quarantine_lot(
            api,
            registration_code="REG-IM3",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        released = fx.release_lot(api, context["lot"]["id"])
        assert released["distribution_status"] == "RELEASED"
        assert released["released_by_user_id"] is not None
        assert released["version"] == context["lot"]["version"] + 1
        for field, value in released.items():
            assert fx.read_lot(api, released["id"])[field] == value


class TestDerivedReadsRecomputeWithNoLag:
    """Clock-derived figures move with nothing but the clock."""

    LOT_STRAWS = 100
    LOT_COST_CENTS = 50000
    TEN_DAYS_ON = "2026-08-11T00:00:00Z"
    ELAPSED_DAYS = 10

    def test_the_tank_level_follows_the_clock_with_no_write_to_the_tank(self, api):
        """A cached derivation would be visibly stale even though no row was written.

        PRD 3.8: "The current `ln2_level_pct` is then `last_service_fill_pct`
        minus 2.0 percentage points for each elapsed whole day, with a floor of
        0: the level never goes negative."
        PRD 3.8: "All three figures are re-derived for every tank on each clock
        move and on every tank read, so a tank's posture is always a function of
        the current clock rather than of a stored decision."

        Design: Corner/consistency model/derived_reads_recompute_from_current_state_with_no_lag
        """
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-LAG"},
            tank_overrides={"serial": "TK-LAG"},
        )
        at_creation = fx.read_tank(api, partner["tank"]["id"])
        fill = at_creation["last_service_fill_pct"]
        assert at_creation["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(fill, 0), abs=0.01
        )
        assert at_creation["tank_status"] == "IN_SERVICE"

        fx.advance_clock(api, self.TEN_DAYS_ON)
        after_ten_days = fx.read_tank(api, partner["tank"]["id"])
        assert after_ten_days["ln2_level_pct"] == pytest.approx(
            expected_ln2_level_pct(fill, self.ELAPSED_DAYS), abs=0.01
        )
        assert after_ten_days["last_service_fill_pct"] == pytest.approx(fill, abs=0.01)
        assert_instant_equals(
            after_ten_days["last_service_at"], at_creation["last_service_at"]
        )
        assert after_ten_days["service_count"] == at_creation["service_count"]

        read_again = fx.read_tank(api, partner["tank"]["id"])
        assert read_again["ln2_level_pct"] == pytest.approx(
            after_ten_days["ln2_level_pct"], abs=0.01
        )
        assert read_again["tank_status"] == after_ten_days["tank_status"]

    def test_the_valuation_answers_the_next_request_and_a_refusal_moves_nothing(self, api):
        """One release shows immediately; one refusal shows nowhere.

        PRD 3.5: "`quarantine_value_cents` is that same sum restricted to lots
        in `QUARANTINE`, `released_value_cents` the same sum restricted to lots
        in `RELEASED`".
        PRD 3.8: "The requested `doses` must not exceed the lot's
        `doses_available`, or `ERR_INSUFFICIENT_DOSES`."

        Design: Corner/consistency model/derived_reads_recompute_from_current_state_with_no_lag
        """
        context = fx.quarantine_lot(
            api,
            registration_code="REG-LAG2",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )
        while_quarantined = fx.read_valuation(api)
        assert (
            while_quarantined["quarantine_value_cents"]
            == standard_unit * self.LOT_STRAWS
        )
        assert while_quarantined["released_value_cents"] == 0

        released = fx.release_lot(api, context["lot"]["id"])
        once_released = fx.read_valuation(api)
        assert once_released["quarantine_value_cents"] == 0
        assert once_released["released_value_cents"] == standard_unit * self.LOT_STRAWS
        assert (
            once_released["plant_inventory_value_cents"]
            == while_quarantined["plant_inventory_value_cents"]
        )

        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-LAG2"},
            tank_overrides={"serial": "TK-LAG2"},
        )
        beyond_the_shelf = api.request_consignment_transfer(
            released["id"],
            factories.consignment_request_payload(
                partner["distributor"]["id"],
                partner["tank"]["id"],
                released["version"],
                self.LOT_STRAWS + 1,
            ),
            fx.DIRECTOR,
        )
        validate_error(
            beyond_the_shelf, ApiErrorId.ERR_INSUFFICIENT_DOSES.value, 422
        )

        unmoved = fx.read_valuation(api)
        for figure in (
            "plant_inventory_value_cents",
            "quarantine_value_cents",
            "released_value_cents",
            "lot_count",
        ):
            assert unmoved[figure] == once_released[figure]
        assert_row_unchanged(
            released,
            fx.read_lot(api, released["id"]),
            "unit_book_value_cents",
            "distribution_status",
            "doses_available",
        )
        exposure = fx.read_distributor(api, partner["distributor"]["id"])
        assert exposure["consignment_value_cents"] == 0
        assert exposure["outstanding_balance_cents"] == 0
        assert exposure["cumulative_doses_used"] == 0


class TestNothingIsDeferred:
    """The only two multi-row sweeps are ordinary synchronous client calls."""

    LOT_STRAWS = 100
    LOT_COST_CENTS = 50000
    BASE_VALIDITY_DAYS = 45
    SWEEP_CLOCK = "2026-09-15T00:00:00Z"
    FUTURE_WINDOW_START = "2026-09-20T08:00:00Z"
    FUTURE_WINDOW_END = "2026-09-20T10:00:00Z"
    SHORT_SERVICE_INTERVAL_DAYS = 10

    def test_compensation_is_an_explicit_call_that_is_complete_when_it_returns(self, api):
        """Nothing withdraws a proof on its own, and the withdrawal has its own gates.

        PRD 3.6: "Compensating hop 2 restores every lot revalued by the
        withdrawn publication: `unit_book_value_cents` is set back to
        `pre_revaluation_unit_value_cents` verbatim, `valuation_basis` is set
        back to the basis that stored value came from, and
        `pre_revaluation_unit_value_cents` is cleared to null."
        PRD 3.6: "rolling back anything not currently `PUBLISHED` reports
        `ERR_EVALUATION_STATE`."

        Design: Corner/consistency model/no_step_is_deferred_and_compensation_is_an_explicit_call
        """
        context = fx.released_lot(
            api,
            registration_code="REG-NB",
            straw_count=self.LOT_STRAWS,
            processing_cost_cents=self.LOT_COST_CENTS,
        )
        standard_unit = expected_standard_unit_value_cents(
            self.LOT_COST_CENTS, self.LOT_STRAWS
        )
        published = fx.published_proof(api, context["sire"]["id"])
        market_unit = expected_market_unit_value_cents(
            published["composite_index"], "CONVENTIONAL"
        )
        assert fx.read_lot(api, context["lot"]["id"])["unit_book_value_cents"] == market_unit
        assert fx.plant_value(api) == market_unit * self.LOT_STRAWS

        withdrawn = fx.rollback_evaluation(api, published["id"])
        assert withdrawn["status"] == "ROLLED_BACK"
        restored = fx.read_lot(api, context["lot"]["id"])
        assert restored["unit_book_value_cents"] == standard_unit
        assert restored["valuation_basis"] == "STANDARD_COST"
        assert restored["pre_revaluation_unit_value_cents"] is None
        assert fx.plant_value(api) == standard_unit * self.LOT_STRAWS

        bull = fx.read_sire(api, context["sire"]["id"])
        assert bull["published_composite_index"] == pytest.approx(0.0, abs=0.01)
        assert bull["published_evaluation_effective_at"] is None
        assert bull["progeny_daughter_count"] == 0

        a_second_withdrawal = api.rollback_genomic_evaluation(
            published["id"], factories.rollback_payload(), fx.DIRECTOR
        )
        validate_error(
            a_second_withdrawal, ApiErrorId.ERR_EVALUATION_STATE.value, 409
        )
        without_its_reason = api.rollback_genomic_evaluation(
            published["id"], {}, fx.DIRECTOR
        )
        validate_error(without_its_reason, ApiErrorId.ERR_VALIDATION.value, 400)
        by_the_wrong_role = api.rollback_genomic_evaluation(
            published["id"], factories.rollback_payload(), fx.TECH
        )
        validate_error(by_the_wrong_role, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    def test_the_clock_sweep_reports_its_own_work_and_every_row_reads_new(self, api):
        """The sweep is synchronous: no 202, no job handle, no half-swept state.

        PRD 2.5: "The response body reports what the sweep touched, as
        `current_utc` alongside four id arrays — `expired_health_test_ids`,
        `suspended_sire_ids`, `voided_booking_ids` — plus `service_due_tank_ids`
        and `out_of_service_tank_ids` naming the tanks that landed in each of
        those two postures."
        PRD 2.5: "every sire that thereby loses coverage of at least one of the
        four base required assays, and whose `collection_status` is `ELIGIBLE`,
        moves to `SUSPENDED` with `suspension_reason` set to
        `REQUIRED_TEST_EXPIRED`."

        Design: Corner/consistency model/no_step_is_deferred_and_compensation_is_an_explicit_call
        """
        context = fx.eligible_sire(
            api,
            registration_code="REG-NB2",
            validity_days=self.BASE_VALIDITY_DAYS,
        )
        assay_ids = sorted(row["id"] for row in context["health_tests"].values())
        booking = fx.book_collection(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            self.FUTURE_WINDOW_START,
            self.FUTURE_WINDOW_END,
        )
        assert booking["status"] == "SCHEDULED"
        partner = fx.distributor_with_tank(
            api,
            distributor_overrides={"name": "D-NB"},
            tank_overrides={
                "serial": "TK-NB",
                "service_interval_days": self.SHORT_SERVICE_INTERVAL_DAYS,
            },
        )

        sweep = validate_success(api.set_clock(self.SWEEP_CLOCK, fx.DIRECTOR), 200)
        assert_instant_equals(sweep["current_utc"], self.SWEEP_CLOCK)
        assert sorted(sweep["expired_health_test_ids"]) == assay_ids
        assert sweep["suspended_sire_ids"] == [context["sire"]["id"]]
        assert sweep["voided_booking_ids"] == [booking["id"]]
        assert partner["tank"]["id"] in sweep["service_due_tank_ids"]
        assert sweep["out_of_service_tank_ids"] == []
        assert "job_id" not in sweep

        for assay_id in sweep["expired_health_test_ids"]:
            assert fx.read_health_test(api, assay_id)["result"] == "EXPIRED"
        suspended = fx.read_sire(api, context["sire"]["id"])
        assert suspended["collection_status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "REQUIRED_TEST_EXPIRED"
        assert fx.read_booking(api, booking["id"])["status"] == "VOIDED"
        assert fx.read_tank(api, partner["tank"]["id"])["tank_status"] == "SERVICE_DUE"
