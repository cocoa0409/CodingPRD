"""State machines: valid hops, preconditions, cascades, terminal lockdown."""

import pytest

from test_helpers import (
    TECH_THIRD_USER_ID,
    ApiErrorId,
    assert_buckets,
    assert_instant_equals,
    factories,
    fixtures as fx,
    make_facility_headers,
    make_tech_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestHousingAdvancesBothDimensions:
    """One call, one transition on each of the sire's two dimensions."""

    @staticmethod
    def _facility_and_contracted_bull(api, code="F-SM-01"):
        facility = fx.register_facility(
            api, code=code, housing_capacity=2, bench_capacity=1
        )
        assert facility["resident_sire_count"] == 0
        sire = fx.register_sire(
            api,
            registration_code="REG-SM1",
            birth_date="2022-02-02",
            acquisition_cost_cents=800000,
        )
        assert sire["version"] == 1
        contracted = fx.contract_sire(api, sire["id"], contract_price_cents=800000)
        assert contracted["acquisition_status"] == "CONTRACTED"
        assert contracted["collection_status"] == "NOT_HOUSED"
        assert contracted["version"] == 2
        return facility, contracted

    def test_the_house_call_derives_the_isolation_end_and_the_resident_count(self, api):
        """Housing is the one operation that moves both dimensions in a single
        call: `CONTRACTED -> RESIDENT` on the acquisition dimension and
        `NOT_HOUSED -> ISOLATION` on the collection dimension. ... computes
        `isolation_ends_at` as the logical clock plus `isolation_days` multiplied
        by 86400 seconds.

        Design: Corner/state_machines/house_call_advances_both_dimensions_and_sets_isolation_end
        """
        facility, contracted = self._facility_and_contracted_bull(api)

        housed = validate_success(
            api.house_sire(
                contracted["id"],
                factories.house_payload(facility["id"], 30),
                make_facility_headers(facility["id"]),
            ),
            200,
        )
        assert housed["acquisition_status"] == "RESIDENT"
        assert housed["collection_status"] == "ISOLATION"
        assert housed["housing_facility_id"] == facility["id"]
        assert housed["isolation_days_applied"] == 30
        assert_instant_equals(housed["isolation_ends_at"], "2026-08-31T00:00:00.000Z")
        assert housed["version"] == 3

        assert fx.read_facility(api, facility["id"])["resident_sire_count"] == 1

    def test_housing_a_bull_who_was_never_contracted_is_refused(self, api):
        """Each of the three acquisition moves demands its own source state —
        contracting requires `PROSPECT`, housing requires `CONTRACTED`, retiring
        requires `RESIDENT` — so a repeated call fails on the second attempt with
        `ERR_SIRE_ACQUISITION_STATE`.

        Design: Corner/state_machines/house_call_advances_both_dimensions_and_sets_isolation_end
        """
        facility, _ = self._facility_and_contracted_bull(api)
        prospect = fx.register_sire(
            api,
            registration_code="REG-SM1B",
            birth_date="2022-03-03",
            acquisition_cost_cents=800000,
        )
        assert prospect["acquisition_status"] == "PROSPECT"

        validate_error(
            api.house_sire(
                prospect["id"],
                factories.house_payload(facility["id"], 30),
                make_facility_headers(facility["id"]),
            ),
            ApiErrorId.ERR_SIRE_ACQUISITION_STATE.value,
            409,
        )

        untouched = fx.read_sire(api, prospect["id"])
        assert untouched["acquisition_status"] == "PROSPECT"
        assert untouched["collection_status"] == "NOT_HOUSED"
        assert untouched["housing_facility_id"] is None
        assert untouched["version"] == 1
        assert fx.read_facility(api, facility["id"])["resident_sire_count"] == 0


class TestCollectionClearanceBoundary:
    """The isolation gate is a clock comparison with a closed boundary."""

    ONE_DAY_EARLY = "2026-08-30T00:00:00Z"
    EXACT_BOUNDARY = "2026-08-31T00:00:00Z"

    @staticmethod
    def _bull_in_isolation(api, *, code="F-SM-02", grant_health=True):
        facility = fx.register_facility(
            api, code=code, housing_capacity=2, bench_capacity=1
        )
        sire = fx.register_sire(api, registration_code="REG-SM2")
        fx.contract_sire(api, sire["id"])
        housed = fx.house_sire(api, sire["id"], facility["id"], 30)
        assert_instant_equals(housed["isolation_ends_at"], "2026-08-31T00:00:00.000Z")
        if grant_health:
            fx.grant_base_health_currency(api, sire["id"], facility["id"])
        return facility, housed

    def test_one_day_early_is_refused_and_the_exact_instant_succeeds(self, api):
        """It has three preconditions: the bull's `collection_status` is
        `ISOLATION`, the logical clock has reached `isolation_ends_at` — the
        boundary is inclusive, so clearance exactly at that instant succeeds, and
        anything earlier is `ERR_ISOLATION_INCOMPLETE`.

        Design: Corner/state_machines/collection_clearance_before_isolation_ends_is_refused
        """
        _facility, housed = self._bull_in_isolation(api)
        fx.advance_clock(api, self.ONE_DAY_EARLY)

        validate_error(
            api.clear_sire_for_collection(
                housed["id"], factories.clearance_payload(), fx.VET
            ),
            ApiErrorId.ERR_ISOLATION_INCOMPLETE.value,
            422,
        )
        assert fx.read_sire(api, housed["id"])["collection_status"] == "ISOLATION"

        fx.advance_clock(api, self.EXACT_BOUNDARY)
        cleared = validate_success(
            api.clear_sire_for_collection(
                housed["id"], factories.clearance_payload(), fx.VET
            ),
            200,
        )
        assert cleared["collection_status"] == "ELIGIBLE"
        assert cleared["suspension_reason"] is None

    def test_the_health_precondition_is_independent_of_the_clock(self, api):
        """... and his health is current across the four base assays, failing
        which the answer is `ERR_HEALTH_TESTS_NOT_CURRENT`.

        Design: Corner/state_machines/collection_clearance_before_isolation_ends_is_refused
        """
        facility, housed = self._bull_in_isolation(api, grant_health=False)
        for test_type in ("IBR", "BVD", "BLUETONGUE"):
            fx.negative_test(api, housed["id"], facility["id"], test_type)
        pending = fx.order_health_test(api, housed["id"], facility["id"], "TRICHOMONIASIS")
        assert pending["result"] == "PENDING"

        fx.advance_clock(api, self.EXACT_BOUNDARY)
        validate_error(
            api.clear_sire_for_collection(
                housed["id"], factories.clearance_payload(), fx.VET
            ),
            ApiErrorId.ERR_HEALTH_TESTS_NOT_CURRENT.value,
            422,
        )
        assert fx.read_sire(api, housed["id"])["collection_status"] == "ISOLATION"


class TestEjaculateQcSideEffects:
    """One QC call writes five fields, and one of them gates release later."""

    WINDOW_START = "2026-09-01T08:00:00Z"
    WINDOW_END = "2026-09-01T10:00:00Z"

    @classmethod
    def _pending_qc_ejaculate(cls, api):
        context = fx.collected_ejaculate(
            api,
            start_at=cls.WINDOW_START,
            end_at=cls.WINDOW_END,
            collection_clock=cls.WINDOW_START,
            facility_overrides={
                "code": "F-SM-05",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
        )
        assert context["ejaculate"]["qc_status"] == "PENDING_QC"
        assert context["ejaculate"]["total_doses_theoretical"] == 480
        return context

    def test_the_accepted_verdict_writes_every_promised_field(self, api):
        """Both branches store those two measurements, stamp `qc_decided_at` from
        the logical clock, and record the acting `X-User-ID` as
        `evaluated_by_user_id`.

        Design: Corner/state_machines/ejaculate_qc_evaluation_writes_every_declared_side_effect
        """
        context = self._pending_qc_ejaculate(api)

        evaluated = validate_success(
            api.evaluate_ejaculate_qc(
                context["ejaculate"]["id"],
                factories.qc_evaluation_payload("ACCEPTED", 55.0, 82.0),
                fx.TECH,
            ),
            200,
        )
        assert evaluated["qc_status"] == "ACCEPTED"
        assert evaluated["post_thaw_motility_pct"] == pytest.approx(55.0, abs=0.01)
        assert evaluated["morphology_normal_pct"] == pytest.approx(82.0, abs=0.01)
        assert evaluated["evaluated_by_user_id"] == fx.TECH["X-User-ID"]
        assert_instant_equals(evaluated["qc_decided_at"], "2026-09-01T08:00:00.000Z")

    def test_the_stored_evaluator_bars_that_same_technician_from_releasing(self, api):
        """Release is also the first segregation-of-duties barrier: the releasing
        `X-User-ID` must differ from the `evaluated_by_user_id` recorded on the
        lot's parent ejaculate, and the same individual attempting both roles is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

        Design: Corner/state_machines/ejaculate_qc_evaluation_writes_every_declared_side_effect
        """
        context = self._pending_qc_ejaculate(api)
        fx.evaluate_qc(api, context["ejaculate"]["id"], "ACCEPTED", 55.0, 82.0, fx.TECH)
        lot = fx.cut_lot(api, context["ejaculate"]["id"], "CONVENTIONAL", 200, 250000)

        validate_error(
            api.release_straw_lot(lot["id"], factories.lot_release_payload(), fx.TECH),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
            403,
        )
        assert fx.read_lot(api, lot["id"])["distribution_status"] == "QUARANTINE"

        released = fx.release_lot(api, lot["id"], fx.TECH_ALT)
        assert released["distribution_status"] == "RELEASED"
        assert released["released_by_user_id"] == fx.TECH_ALT["X-User-ID"]

    def test_a_sub_threshold_acceptance_is_refused_outright(self, api):
        """An `ACCEPTED` verdict, however, is only permitted when
        `post_thaw_motility_pct` is at least 35.0 and `morphology_normal_pct` is
        at least 70.0; a verdict of `ACCEPTED` accompanied by sub-threshold
        figures is refused outright with `ERR_QC_BELOW_THRESHOLD` rather than
        silently downgraded to a rejection.

        Design: Corner/state_machines/ejaculate_qc_evaluation_writes_every_declared_side_effect
        """
        context = self._pending_qc_ejaculate(api)
        ejaculate_id = context["ejaculate"]["id"]

        validate_error(
            api.evaluate_ejaculate_qc(
                ejaculate_id,
                factories.qc_evaluation_payload("ACCEPTED", 34.9, 82.0),
                fx.TECH,
            ),
            ApiErrorId.ERR_QC_BELOW_THRESHOLD.value,
            422,
        )
        validate_error(
            api.evaluate_ejaculate_qc(
                ejaculate_id,
                factories.qc_evaluation_payload("ACCEPTED", 55.0, 69.9),
                fx.TECH,
            ),
            ApiErrorId.ERR_QC_BELOW_THRESHOLD.value,
            422,
        )

        untouched = fx.read_ejaculate(api, ejaculate_id)
        assert untouched["qc_status"] == "PENDING_QC"
        assert untouched["post_thaw_motility_pct"] is None
        assert untouched["evaluated_by_user_id"] is None


class TestBookingTerminalStates:
    """COMPLETED, CANCELLED and VOIDED accept no further transition."""

    FIRST_START = "2026-09-01T08:00:00Z"
    FIRST_END = "2026-09-01T10:00:00Z"
    LATER_START = "2026-09-20T08:00:00Z"
    LATER_END = "2026-09-20T10:00:00Z"

    @classmethod
    def _one_completed_and_one_cancelled_booking(cls, api):
        context = fx.collected_ejaculate(
            api,
            start_at=cls.FIRST_START,
            end_at=cls.FIRST_END,
            collection_clock=cls.FIRST_START,
            facility_overrides={
                "code": "F-SM-03",
                "housing_capacity": 2,
                "bench_capacity": 2,
            },
            registration_code="REG-SM3",
        )
        assert context["booking"]["status"] == "COMPLETED"
        later = fx.book_collection(
            api,
            context["sire"]["id"],
            context["facility"]["id"],
            cls.LATER_START,
            cls.LATER_END,
        )
        cancelled = validate_success(
            api.cancel_booking(
                later["id"],
                factories.booking_cancel_payload(cancel_reason="OPERATOR_ERROR"),
                context["facility_headers"],
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        context["cancelled_booking"] = cancelled
        return context

    def test_a_completed_booking_cannot_be_cancelled(self, api):
        """Either way, a booking that is no longer `SCHEDULED` accepts no further
        transition and reports `ERR_BOOKING_STATE`.

        Design: Corner/state_machines/booking_transitions_from_terminal_states_are_rejected
        """
        context = self._one_completed_and_one_cancelled_booking(api)
        completed = context["booking"]

        validate_error(
            api.cancel_booking(
                completed["id"],
                factories.booking_cancel_payload(cancel_reason="OPERATOR_ERROR"),
                context["facility_headers"],
            ),
            ApiErrorId.ERR_BOOKING_STATE.value,
            409,
        )

        unchanged = fx.read_booking(api, completed["id"])
        assert unchanged["status"] == "COMPLETED"
        assert unchanged["cancel_reason"] is None

    def test_a_cancelled_booking_can_be_neither_completed_nor_cancelled_again(self, api):
        """`SCHEDULED -> CANCELLED` is operator-initiated: the manager or a
        director supplies a free-text `cancel_reason`, the row mints nothing, and
        the freed slot returns to both the rest-buffer and bench-overlap
        calculations.

        Design: Corner/state_machines/booking_transitions_from_terminal_states_are_rejected
        """
        context = self._one_completed_and_one_cancelled_booking(api)
        cancelled_id = context["cancelled_booking"]["id"]

        validate_error(
            api.complete_booking(
                cancelled_id,
                factories.booking_complete_payload(),
                context["facility_headers"],
            ),
            ApiErrorId.ERR_BOOKING_STATE.value,
            409,
        )
        validate_error(
            api.cancel_booking(
                cancelled_id,
                factories.booking_cancel_payload(cancel_reason="DUPLICATE_ENTRY"),
                context["facility_headers"],
            ),
            ApiErrorId.ERR_BOOKING_STATE.value,
            409,
        )

        _, meta = validate_paginated(
            api.list_ejaculates(fx.TECH, {"booking_id": cancelled_id})
        )
        assert meta["total_count"] == 0
        assert fx.read_sire(api, context["sire"]["id"])["collection_count"] == 1


class TestDeclaredInitialStates:
    """Each entity's first observable status is its declared initial state."""

    def test_four_entities_open_where_the_specification_says_they_open(self, api):
        """A new lot copies `sire_id` from its ejaculate ... and enters
        `distribution_status` `QUARANTINE`. ... `version` is an integer that
        starts at 1 on creation.

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        facility = fx.register_facility(
            api, code="F-IS-01", housing_capacity=2, bench_capacity=1
        )
        distributor = fx.register_distributor(
            api, name="D-IS", country_code="US", credit_limit_cents=5000000
        )
        tank = fx.register_tank(
            api, distributor["id"], serial="TK-IS", capacity_straws=300
        )
        sire = fx.register_sire(
            api,
            registration_code="REG-IS",
            breed="ANGUS",
            birth_date="2022-05-05",
            acquisition_cost_cents=400000,
        )

        evaluation = validate_success(
            api.file_genomic_evaluation(
                sire["id"],
                factories.genomic_evaluation_payload(
                    sire["version"],
                    milk_kg=700,
                    fat_kg=30,
                    protein_kg=24,
                    somatic_cell_score=2.95,
                    fertility_pct=1.0,
                    longevity_months=1.0,
                    reliability_pct=60,
                    progeny_daughter_count=0,
                    effective_at="2026-07-15T00:00:00Z",
                ),
                fx.DIRECTOR,
            ),
            201,
        )
        assert evaluation["status"] == "DRAFT"
        assert evaluation["published_at"] is None

        assert fx.read_facility(api, facility["id"])["approval_status"] == "APPROVED"
        assert fx.read_tank(api, tank["id"])["tank_status"] == "IN_SERVICE"
        stored = fx.read_sire(api, sire["id"])
        assert stored["acquisition_status"] == "PROSPECT"
        assert stored["collection_status"] == "NOT_HOUSED"

    def test_a_draft_proof_leaves_the_bull_s_published_snapshot_alone(self, api):
        """... a figure that is 0 for as long as the row remains a draft.

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        sire = fx.register_sire(
            api,
            registration_code="REG-IS",
            breed="ANGUS",
            birth_date="2022-05-05",
            acquisition_cost_cents=400000,
        )
        fx.file_evaluation(
            api,
            sire["id"],
            milk_kg=700,
            fat_kg=30,
            protein_kg=24,
            somatic_cell_score=2.95,
            fertility_pct=1.0,
            longevity_months=1.0,
            reliability_pct=60,
            progeny_daughter_count=0,
            effective_at="2026-07-15T00:00:00Z",
        )

        stored = fx.read_sire(api, sire["id"])
        assert stored["published_composite_index"] == pytest.approx(0.00, abs=0.01)
        assert stored["published_production_index"] == pytest.approx(0.00, abs=0.01)
        assert stored["published_health_index"] == pytest.approx(0.00, abs=0.01)
        assert stored["published_evaluation_effective_at"] is None

        _, meta = validate_paginated(
            api.list_genomic_evaluations(
                fx.DIRECTOR, {"sire_id": sire["id"], "status": "DRAFT"}
            )
        )
        assert meta["total_count"] == 1


class TestRetirementLocksBothDimensions:
    """One retire call lands RETIRED and WITHDRAWN, and nothing moves after."""

    LATER_START = "2026-09-25T08:00:00Z"
    LATER_END = "2026-09-25T10:00:00Z"

    @staticmethod
    def _bull_with_released_stock(api):
        context = fx.released_lot(
            api,
            facility_overrides={
                "code": "F-SM-04",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            registration_code="REG-SM4",
            straw_count=200,
            processing_cost_cents=250000,
        )
        assert fx.read_facility(api, context["facility"]["id"])["resident_sire_count"] == 1
        return context

    def test_retirement_moves_both_dimensions_and_shuts_the_acquisition_one(self, api):
        """Commercial retirement, recorded with a `retirement_reason`, advances
        `RESIDENT -> RETIRED`. It also advances `collection_status` to `WITHDRAWN`
        on the same row ... The `housing_facility_id` itself is retained for audit
        rather than cleared, and existing straw inventory cut from this bull stays
        sellable.

        Design: Corner/state_machines/retired_and_withdrawn_sire_accepts_no_further_transition
        """
        context = self._bull_with_released_stock(api)
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]

        retired = validate_success(
            api.retire_sire(
                sire_id, factories.retire_payload(retirement_reason="AGE"), fx.DIRECTOR
            ),
            200,
        )
        assert retired["acquisition_status"] == "RETIRED"
        assert retired["collection_status"] == "WITHDRAWN"
        assert retired["housing_facility_id"] == facility_id
        assert fx.read_facility(api, facility_id)["resident_sire_count"] == 0

        validate_error(
            api.retire_sire(
                sire_id, factories.retire_payload(retirement_reason="AGE"), fx.DIRECTOR
            ),
            ApiErrorId.ERR_SIRE_ACQUISITION_STATE.value,
            409,
        )
        validate_error(
            api.house_sire(
                sire_id, factories.house_payload(facility_id, 30), fx.DIRECTOR
            ),
            ApiErrorId.ERR_SIRE_ACQUISITION_STATE.value,
            409,
        )

        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["distribution_status"] == "RELEASED"
        assert_buckets(lot, 200, 0, 0, 0, 0)

    def test_the_collection_dimension_refuses_every_move_out_of_withdrawn(self, api):
        """A move to `WITHDRAWN` is terminal on the collection dimension and
        leaves `acquisition_status` alone. Any move the dimension does not permit
        — ... or any move out of `WITHDRAWN` — is refused with
        `ERR_SIRE_COLLECTION_STATE`.

        Design: Corner/state_machines/retired_and_withdrawn_sire_accepts_no_further_transition
        """
        context = self._bull_with_released_stock(api)
        sire_id = context["sire"]["id"]
        fx.read_sire(api, sire_id)
        validate_success(
            api.retire_sire(
                sire_id, factories.retire_payload(retirement_reason="SOLD"), fx.DIRECTOR
            ),
            200,
        )

        for target in ("ELIGIBLE", "SUSPENDED"):
            validate_error(
                api.set_sire_collection_status(
                    sire_id, factories.collection_status_payload(target), fx.VET
                ),
                ApiErrorId.ERR_SIRE_COLLECTION_STATE.value,
                409,
            )

        validate_error(
            api.create_booking(
                factories.booking_payload(
                    sire_id, context["facility"]["id"], self.LATER_START, self.LATER_END
                ),
                context["facility_headers"],
            ),
            ApiErrorId.ERR_SIRE_COLLECTION_STATE.value,
            409,
        )
        assert fx.read_sire(api, sire_id)["collection_status"] == "WITHDRAWN"


class TestSecondReleaseIsAnError:
    """Repeating a successful transition is refused, not silently absorbed."""

    @staticmethod
    def _released_lot_cut_by_tech_one(api):
        context = fx.quarantine_lot(
            api,
            facility_overrides={
                "code": "F-SM-06",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            straw_count=200,
            processing_cost_cents=250000,
        )
        assert context["ejaculate"]["evaluated_by_user_id"] == fx.TECH["X-User-ID"]
        context["lot"] = fx.release_lot(api, context["lot"]["id"], fx.TECH_ALT)
        assert context["lot"]["distribution_status"] == "RELEASED"
        assert context["lot"]["released_by_user_id"] == fx.TECH_ALT["X-User-ID"]
        return context

    def test_the_state_rule_answers_ahead_of_the_segregation_rule(self, api):
        """Releasing a lot for distribution takes an optional `release_note` and
        requires `distribution_status` to be `QUARANTINE`; a release or rejection
        attempted on any other status is `ERR_LOT_STATE`.

        Design: Corner/state_machines/second_release_of_the_same_lot_returns_lot_state
        """
        context = self._released_lot_cut_by_tech_one(api)
        lot = context["lot"]

        validate_error(
            api.release_straw_lot(
                lot["id"],
                factories.lot_release_payload(),
                make_tech_headers(TECH_THIRD_USER_ID),
            ),
            ApiErrorId.ERR_LOT_STATE.value,
            409,
        )
        validate_error(
            api.release_straw_lot(lot["id"], factories.lot_release_payload(), fx.TECH),
            ApiErrorId.ERR_LOT_STATE.value,
            409,
        )

        unchanged = fx.read_lot(api, lot["id"])
        assert unchanged["released_by_user_id"] == fx.TECH_ALT["X-User-ID"]
        assert unchanged["version"] == lot["version"]

    def test_rejection_after_release_is_refused_too(self, api):
        """Condemning a lot is the sibling branch. It takes a `rejected_reason`,
        requires `QUARANTINE`.

        Design: Corner/state_machines/second_release_of_the_same_lot_returns_lot_state
        """
        context = self._released_lot_cut_by_tech_one(api)
        lot = context["lot"]

        validate_error(
            api.reject_straw_lot(lot["id"], factories.lot_reject_payload(), fx.TECH),
            ApiErrorId.ERR_LOT_STATE.value,
            409,
        )

        unchanged = fx.read_lot(api, lot["id"])
        assert unchanged["distribution_status"] == "RELEASED"
        assert_buckets(unchanged, 200, 0, 0, 0, 0)
        assert unchanged["version"] == lot["version"]


class TestResidentCountTracksHousingAndRetirement:
    """resident_sire_count is derived from the rows, not a client-set counter."""

    @staticmethod
    def _two_housed_bulls(api):
        facility = fx.register_facility(
            api, code="F-LS-01", housing_capacity=3, bench_capacity=1
        )
        housed = []
        for code, birth in (("REG-LS1", "2022-01-01"), ("REG-LS2", "2022-06-01")):
            sire = fx.register_sire(
                api,
                registration_code=code,
                breed="ANGUS",
                birth_date=birth,
                acquisition_cost_cents=300000,
            )
            fx.contract_sire(api, sire["id"], contract_price_cents=300000)
            housed.append(fx.house_sire(api, sire["id"], facility["id"], 21))
        assert fx.read_facility(api, facility["id"])["resident_sire_count"] == 2
        return facility, housed

    @staticmethod
    def _contract_another(api, code, birth="2021-09-09"):
        sire = fx.register_sire(
            api,
            registration_code=code,
            breed="ANGUS",
            birth_date=birth,
            acquisition_cost_cents=300000,
        )
        fx.contract_sire(api, sire["id"], contract_price_cents=300000)
        return sire

    def test_the_count_falls_on_retirement_and_reconciles_with_the_rows(self, api):
        """The target facility's `resident_sire_count` is then recomputed as the
        number of bulls whose `housing_facility_id` is that facility and whose
        `acquisition_status` is `RESIDENT`.

        Design: Corner/state_machines/facility_retire_keeps_resident_count_in_step
        """
        facility, housed = self._two_housed_bulls(api)

        validate_success(
            api.retire_sire(
                housed[0]["id"],
                factories.retire_payload(retirement_reason="SOLD"),
                fx.DIRECTOR,
            ),
            200,
        )
        assert fx.read_facility(api, facility["id"])["resident_sire_count"] == 1

        _, resident = validate_paginated(
            api.list_sires(
                fx.DIRECTOR,
                {
                    "housing_facility_id": facility["id"],
                    "acquisition_status": "RESIDENT",
                },
            )
        )
        assert resident["total_count"] == 1
        _, retired = validate_paginated(
            api.list_sires(
                fx.DIRECTOR,
                {"housing_facility_id": facility["id"], "acquisition_status": "RETIRED"},
            )
        )
        assert retired["total_count"] == 1

    def test_the_capacity_rule_reads_the_derived_count(self, api):
        """And the facility must have room: housing may not push
        `resident_sire_count` above the facility's `housing_capacity`. Every
        resident already there is individually legal — it is the newcomer that
        breaks the cap — and the refusal is `ERR_FACILITY_AT_CAPACITY`.

        Design: Corner/state_machines/facility_retire_keeps_resident_count_in_step
        """
        facility, _housed = self._two_housed_bulls(api)

        third = self._contract_another(api, "REG-LS3")
        fx.house_sire(api, third["id"], facility["id"], 21)
        assert fx.read_facility(api, facility["id"])["resident_sire_count"] == 3

        fourth = self._contract_another(api, "REG-LS4", "2021-10-10")
        validate_error(
            api.house_sire(
                fourth["id"], factories.house_payload(facility["id"], 21), fx.DIRECTOR
            ),
            ApiErrorId.ERR_FACILITY_AT_CAPACITY.value,
            422,
        )
        assert fx.read_facility(api, facility["id"])["resident_sire_count"] == 3
        assert fx.read_sire(api, fourth["id"])["acquisition_status"] == "CONTRACTED"


class TestFacilitySuspensionSparesTerminalBookings:
    """The cascade is conditional on the child booking's own state."""

    DONE_START = "2026-09-01T08:00:00Z"
    DONE_END = "2026-09-01T10:00:00Z"
    CANC_START = "2026-09-08T08:00:00Z"
    CANC_END = "2026-09-08T10:00:00Z"
    FUT_START = "2026-09-20T08:00:00Z"
    FUT_END = "2026-09-20T10:00:00Z"
    SUSPENSION_CLOCK = "2026-09-10T00:00:00Z"
    FRESH_START = "2026-09-15T08:00:00Z"
    FRESH_END = "2026-09-15T10:00:00Z"

    @classmethod
    def _three_bookings_in_three_states(cls, api):
        context = fx.collected_ejaculate(
            api,
            start_at=cls.DONE_START,
            end_at=cls.DONE_END,
            collection_clock=cls.DONE_START,
            facility_overrides={
                "code": "F-CC-01",
                "housing_capacity": 2,
                "bench_capacity": 2,
            },
            registration_code="REG-CC1",
        )
        sire_id = context["sire"]["id"]
        facility_id = context["facility"]["id"]

        to_cancel = fx.book_collection(
            api, sire_id, facility_id, cls.CANC_START, cls.CANC_END
        )
        context["cancelled"] = validate_success(
            api.cancel_booking(
                to_cancel["id"],
                factories.booking_cancel_payload(cancel_reason="HERD_OWNER_DEFERRED"),
                context["facility_headers"],
            ),
            200,
        )
        context["future"] = fx.book_collection(
            api, sire_id, facility_id, cls.FUT_START, cls.FUT_END
        )
        assert context["future"]["status"] == "SCHEDULED"
        fx.advance_clock(api, cls.SUSPENSION_CLOCK)
        return context

    def test_only_the_scheduled_booking_is_voided(self, api):
        """The `APPROVED -> SUSPENDED` move stores that reason and then runs a
        two-hop cascade: every bull whose `housing_facility_id` is this facility
        and whose `collection_status` is `ELIGIBLE` becomes `SUSPENDED` with
        `suspension_reason` `FACILITY_SUSPENDED`, and — caused by that first hop —
        each of those bulls' `SCHEDULED` bookings whose `start_at` is at or after
        the logical clock become `VOIDED` with `cancel_reason`
        `FACILITY_SUSPENDED`.

        Design: Corner/state_machines/facility_suspension_voids_only_non_terminal_bookings
        """
        context = self._three_bookings_in_three_states(api)

        fx.suspend_facility(api, context["facility"]["id"], "REGULATOR_HOLD")

        voided = fx.read_booking(api, context["future"]["id"])
        assert voided["status"] == "VOIDED"
        assert voided["cancel_reason"] == "FACILITY_SUSPENDED"

        completed = fx.read_booking(api, context["booking"]["id"])
        assert completed["status"] == "COMPLETED"
        assert_instant_equals(completed["completed_at"], "2026-09-01T08:00:00.000Z")
        assert completed["cancel_reason"] is None

        cancelled = fx.read_booking(api, context["cancelled"]["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "HERD_OWNER_DEFERRED"

        sire = fx.read_sire(api, context["sire"]["id"])
        assert sire["collection_status"] == "SUSPENDED"
        assert sire["suspension_reason"] == "FACILITY_SUSPENDED"

    def test_reinstating_the_site_undoes_nothing_by_itself(self, api):
        """The reverse move, `SUSPENDED -> APPROVED`, clears `suspension_reason`
        and bumps `version`, and does nothing else: it restores neither the
        suspended bulls nor the voided bookings, each of which needs its own
        explicit reinstatement.

        Design: Corner/state_machines/facility_suspension_voids_only_non_terminal_bookings
        """
        context = self._three_bookings_in_three_states(api)
        facility_id = context["facility"]["id"]
        sire_id = context["sire"]["id"]
        fx.suspend_facility(api, facility_id, "REGULATOR_HOLD")

        reapproved = fx.approve_facility(api, facility_id)
        assert reapproved["approval_status"] == "APPROVED"
        assert reapproved["suspension_reason"] is None
        assert fx.read_booking(api, context["future"]["id"])["status"] == "VOIDED"
        assert fx.read_sire(api, sire_id)["collection_status"] == "SUSPENDED"

        reinstated = validate_success(
            api.set_sire_collection_status(
                sire_id, factories.collection_status_payload("ELIGIBLE"), fx.VET
            ),
            200,
        )
        assert reinstated["collection_status"] == "ELIGIBLE"
        assert reinstated["suspension_reason"] is None

        fresh = fx.book_collection(
            api, sire_id, facility_id, self.FRESH_START, self.FRESH_END
        )
        assert fresh["status"] == "SCHEDULED"


class TestLotDepletesWhenEveryBucketEmpties:
    """The lot's terminal status is derived from its children's dose movements."""

    @staticmethod
    def _whole_lot_out_on_consignment(api):
        context = fx.received_consignment(
            api,
            facility_overrides={
                "code": "F-BU-01",
                "housing_capacity": 2,
                "bench_capacity": 1,
            },
            straw_count=100,
            processing_cost_cents=125000,
            distributor_overrides={"name": "D-BU", "credit_limit_cents": 100000000},
            tank_overrides={"serial": "TK-BU", "capacity_straws": 300},
            doses=100,
            unit_price_cents=4000,
        )
        lot = fx.read_lot(api, context["lot"]["id"])
        assert lot["unit_book_value_cents"] == 1250
        assert lot["distribution_status"] == "RELEASED"
        assert_buckets(lot, 0, 0, 100, 0, 0)
        assert fx.plant_value(api) == 125000
        return context

    def test_the_last_dose_movement_flips_the_lot_and_empties_the_valuation(self, api):
        """One further lot transition is never operator-driven. `RELEASED ->
        DEPLETED` fires automatically after any ledger mutation that leaves
        `doses_available`, `doses_reserved` and `doses_consigned` all at 0 ... A
        depleted lot leaves the plant inventory aggregate.

        Design: Corner/state_machines/straw_lot_becomes_depleted_when_every_dose_bucket_empties
        """
        context = self._whole_lot_out_on_consignment(api)

        fx.report_usage(
            api,
            context["transfer"]["id"],
            context["distributor"]["id"],
            doses_used=100,
            doses_returned=0,
        )

        depleted = fx.read_lot(api, context["lot"]["id"])
        assert depleted["distribution_status"] == "DEPLETED"
        assert_buckets(depleted, 0, 0, 0, 100, 0)
        assert depleted["straw_count"] == 100

        valuation = fx.read_valuation(api)
        assert valuation["plant_inventory_value_cents"] == 0
        assert valuation["quarantine_value_cents"] == 0
        assert valuation["released_value_cents"] == 0
        assert valuation["lot_count"] == 0

    def test_a_depleted_lot_is_terminal_and_the_settlement_stands(self, api):
        """`QUARANTINE`, `REJECTED` and `DEPLETED` lots cannot be consigned, and
        the refusal is `ERR_LOT_NOT_RELEASED`.

        Design: Corner/state_machines/straw_lot_becomes_depleted_when_every_dose_bucket_empties
        """
        context = self._whole_lot_out_on_consignment(api)

        reconciled = fx.report_usage(
            api,
            context["transfer"]["id"],
            context["distributor"]["id"],
            doses_used=100,
            doses_returned=0,
        )
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["gross_cents"] == 400000
        assert reconciled["service_fee_cents"] == 0
        assert reconciled["rebate_cents"] == 0
        assert reconciled["settlement_total_cents"] == 400000

        depleted = fx.read_lot(api, context["lot"]["id"])
        validate_error(
            api.request_consignment_transfer(
                depleted["id"],
                factories.consignment_request_payload(
                    context["distributor"]["id"],
                    context["tank"]["id"],
                    depleted["version"],
                    doses=1,
                    unit_price_cents=4000,
                ),
                fx.DIRECTOR,
            ),
            ApiErrorId.ERR_LOT_NOT_RELEASED.value,
            409,
        )
        assert fx.read_lot(api, depleted["id"])["distribution_status"] == "DEPLETED"
