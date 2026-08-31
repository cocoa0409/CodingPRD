"""Product gas: energy content, spec analysis, attachment, injection, the
pipeline meter true-up and the terminal states."""

from test_helpers import (
    ApiErrorId,
    approx_2dp,
    approx_4dp,
    assert_injection_batch,
    create_injection_batch_payload,
    fixtures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import BASE_CLOCK_UTC


class TestEnergyContent:
    def test_three_hour_block_rounds_each_hour_before_the_hours_are_summed(
        self, api, operator_headers
    ):
        """PRD §3.7: "Then, walking the submitted hourly volumes in index order, each
        hour's energy is that hour's volume multiplied by the methane fraction multiplied
        by the heating value of 1.0122 MMBtu per thousand standard cubic feet of methane,
        and **that per-hour product is rounded half up to two decimal places before
        anything else happens**. Only then are the already-rounded hourly figures summed,
        and the sum is rounded half up to two decimal places again to give
        `gross_mmbtu`."
        PRD §3.7: "Three hours of 115.0 thousand standard cubic feet at 97.4 percent
        methane give 340.14 under the pinned order and 340.13 under sum-then-round, and
        the pinned order is the specification."
        PRD §3.7: "A new batch opens in `status` `DRAFT` with `metered_mmbtu` and
        `nomination_id` null, `spec_failure_reason` `NONE`, and `void_reason` null."

        Design: Difficulty/combinatorial_formula/gross_mmbtu_round_each_hour_then_sum_mode_b
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])

        batch = validate_success(
            api.create_injection_batch(
                create_injection_batch_payload(
                    plant["id"],
                    interval_start="2026-08-10T02:00:00Z",
                    interval_end="2026-08-10T05:00:00Z",
                    hourly_volumes_mscf=[115.0, 115.0, 115.0],
                    methane_pct=97.4,
                ),
                operator_headers,
            ),
            201,
        )
        assert_injection_batch(batch)
        assert batch["gross_mmbtu"] == approx_2dp(340.14)
        assert batch["gross_mmbtu"] != approx_2dp(340.13), (
            "sum-then-round would have produced 340.13"
        )
        assert batch["status"] == "DRAFT"
        assert batch["metered_mmbtu"] is None
        assert batch["nomination_id"] is None
        assert batch["spec_failure_reason"] == "NONE"
        assert batch["void_reason"] is None

    def test_two_hour_block_rounds_the_opposite_way_from_sum_then_round(
        self, api, operator_headers
    ):
        """PRD §3.7: "Energy content is computed once, at creation, and frozen on the row
        thereafter. First the methane fraction is taken as `methane_pct` divided by 100."
        PRD §3.7: "The order is load-bearing and is not an implementation detail: summing
        the unrounded hourly products and rounding once at the end produces a different
        number."

        Design: Difficulty/combinatorial_formula/gross_mmbtu_round_each_hour_then_sum_mode_b
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])

        batch = validate_success(
            api.create_injection_batch(
                create_injection_batch_payload(
                    plant["id"],
                    interval_start="2026-08-10T06:00:00Z",
                    interval_end="2026-08-10T08:00:00Z",
                    hourly_volumes_mscf=[40.0, 40.0],
                    methane_pct=97.0,
                    co2_pct=1.5,
                ),
                operator_headers,
            ),
            201,
        )
        # 40.0 * 0.97 * 1.0122 = 39.27336 -> 39.27 per hour, 78.54 in total.
        assert batch["gross_mmbtu"] == approx_2dp(78.54)
        assert batch["gross_mmbtu"] != approx_2dp(78.55), (
            "sum-then-round would have produced 78.55 — the two blocks disagree in "
            "opposite directions"
        )

    def test_hourly_volume_count_must_match_the_interval_hours(
        self, api, operator_headers
    ):
        """PRD §3.7: "The interval must span a whole number of hours and the array must
        hold exactly that many entries; a mismatch in either direction is refused with
        `ERR_BATCH_INTERVAL_MISMATCH`."

        Design: Corner/validations/hourly_volume_count_not_matching_interval_hours_is_rejected
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])

        validate_error(
            api.create_injection_batch(
                create_injection_batch_payload(
                    plant["id"],
                    interval_start="2026-08-10T02:00:00Z",
                    interval_end="2026-08-10T05:00:00Z",
                    hourly_volumes_mscf=[115.0, 115.0],
                ),
                operator_headers,
            ),
            ApiErrorId.ERR_BATCH_INTERVAL_MISMATCH.value,
        )

        _, meta = validate_paginated(
            api.list_injection_batches(
                operator_headers,
                params={"plant_id": plant["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 0


class TestSpecAnalysisGating:
    def test_analysis_is_refused_while_the_plant_is_still_starting_up(
        self, api, operator_headers
    ):
        """PRD §3.7: "Submitting a batch for analysis takes `DRAFT → PENDING_ANALYSIS`
        and requires the plant's `process_mode` to be `UPGRADING`; a batch under a plant
        that is starting up, flaring, down or decommissioned is refused with
        `ERR_PLANT_NOT_UPGRADING`, and that specific refusal takes precedence over the
        generic invalid-transition code because the batch's own state check has already
        passed."

        Design: Difficulty/cross_entity_state_dependency/batch_analysis_gated_on_processing_plant_process_mode
        """
        context = fixtures.setup_site_with_wellfield()
        plant_id = context["plant"]["id"]
        assert fixtures.read_plant(plant_id)["process_mode"] == "STARTUP"
        batch = fixtures.create_batch(plant_id)

        error = validate_error(
            api.set_injection_batch_status(
                batch["id"], {"to_status": "PENDING_ANALYSIS"}, operator_headers
            ),
            ApiErrorId.ERR_PLANT_NOT_UPGRADING.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_TRANSITION.value

        assert fixtures.read_injection_batch(batch["id"])["status"] == "DRAFT"

    def test_the_same_analysis_call_lands_on_spec_once_the_plant_reaches_upgrading(
        self, api, operator_headers
    ):
        """PRD §3.7: "The analysis then runs inside the same request, and the batch never
        rests in `PENDING_ANALYSIS`: the server compares the batch against the plant's
        specification and lands it on `ON_SPEC` or `OFF_SPEC` before responding."
        PRD §3.7: "The batch is on spec when its `methane_pct` is at least the plant's
        `spec_min_methane_pct`, its `oxygen_pct` is no greater than
        `spec_max_oxygen_pct`, and its `co2_pct` is no greater than `spec_max_co2_pct`;
        in that case `spec_failure_reason` is set to `NONE` and nothing else changes."

        Design: Difficulty/cross_entity_state_dependency/batch_analysis_gated_on_processing_plant_process_mode
        """
        context = fixtures.setup_site_with_wellfield()
        plant_id = context["plant"]["id"]
        batch = fixtures.create_batch(plant_id)

        validate_error(
            api.set_injection_batch_status(
                batch["id"], {"to_status": "PENDING_ANALYSIS"}, operator_headers
            ),
            ApiErrorId.ERR_PLANT_NOT_UPGRADING.value,
        )

        upgrading = fixtures.set_plant_mode(plant_id, process_mode="UPGRADING")
        assert upgrading["process_mode"] == "UPGRADING"

        analysed = validate_success(
            api.set_injection_batch_status(
                batch["id"], {"to_status": "PENDING_ANALYSIS"}, operator_headers
            )
        )
        assert analysed["status"] == "ON_SPEC", (
            "nothing about the batch changed between the two calls — only the plant"
        )
        assert analysed["spec_failure_reason"] == "NONE"
        assert analysed["gross_mmbtu"] == approx_2dp(340.14)


class TestAttachmentRejectionOrder:
    def test_plant_off_spec_is_reported_ahead_of_the_nomination_volume_overflow(
        self, api, scheduler_headers
    ):
        """PRD §2.5: "Checks run in a fixed ascending priority order and the **first**
        failing check decides the response."
        PRD §2.5: "**Process-safety and permit gates (priority 90).** These guard plant
        status changes, well status changes, injection batch status changes, condensate
        haul recording, and compliance report status changes."
        PRD §2.5: "**Capacity and quota (priority 130).** A nomination exceeding its
        contract's maximum daily quantity reports `ERR_CONTRACT_MDQ_EXCEEDED` (422); a
        nomination exceeding the pooled receipt-point hourly rate reports
        `ERR_RECEIPT_POINT_CAPACITY_EXCEEDED` (409); and attaching a batch that would push
        a nomination past its nominated volume reports `ERR_NOMINATION_VOLUME_EXCEEDED`
        (422)."
        PRD §3.7: "The plant's `process_mode` must be `UPGRADING`, or
        `ERR_PLANT_NOT_UPGRADING`, and its `spec_status` must be `ON_SPEC`, or
        `ERR_PLANT_OFF_SPEC`."

        Design: Difficulty/priority_pair_validation_conflict/plant_off_spec_safety_beats_nomination_volume_fiscal
        """
        context = fixtures.setup_commercial_desk(
            nomination_overrides={"nominated_dth": 100.0}
        )
        batch = fixtures.create_batch(context["plant"]["id"])
        fixtures.analyse_batch(batch["id"])
        fixtures.setup_off_spec_plant(context=context)

        error = validate_error(
            api.set_injection_batch_status(
                batch["id"],
                {"to_status": "NOMINATED", "nomination_id": context["nomination"]["id"]},
                scheduler_headers,
            ),
            ApiErrorId.ERR_PLANT_OFF_SPEC.value,
        )
        assert error["error_id"] != ApiErrorId.ERR_NOMINATION_VOLUME_EXCEEDED.value, (
            "340.14 MMBtu does not fit a 100.0 dth nomination either, but the "
            "process-safety rung sits above the capacity rung"
        )

    def test_refused_attachment_leaves_the_batch_and_the_nomination_untouched(
        self, api, scheduler_headers
    ):
        """PRD §3.7: "On success, the batch's `nomination_id` is set, the nomination's
        `committed_dth` rises by the batch's `gross_mmbtu`, and a nomination sitting in
        `CONFIRMED` advances to `SCHEDULED`."
        PRD §3.7: "The plant's `process_mode` must be `UPGRADING`, or
        `ERR_PLANT_NOT_UPGRADING`, and its `spec_status` must be `ON_SPEC`, or
        `ERR_PLANT_OFF_SPEC`."

        Design: Difficulty/priority_pair_validation_conflict/plant_off_spec_safety_beats_nomination_volume_fiscal
        """
        context = fixtures.setup_commercial_desk(
            nomination_overrides={"nominated_dth": 100.0}
        )
        batch = fixtures.create_batch(context["plant"]["id"])
        fixtures.analyse_batch(batch["id"])
        fixtures.setup_off_spec_plant(context=context)

        validate_error(
            api.set_injection_batch_status(
                batch["id"],
                {"to_status": "NOMINATED", "nomination_id": context["nomination"]["id"]},
                scheduler_headers,
            ),
            ApiErrorId.ERR_PLANT_OFF_SPEC.value,
        )

        unchanged_batch = fixtures.read_injection_batch(batch["id"])
        assert unchanged_batch["status"] == "ON_SPEC"
        assert unchanged_batch["nomination_id"] is None

        unchanged_nomination = fixtures.read_nomination(context["nomination"]["id"])
        assert unchanged_nomination["status"] == "CONFIRMED"
        assert unchanged_nomination["committed_dth"] == approx_2dp(0.0)

    def test_attaching_a_batch_larger_than_the_nomination_is_refused(
        self, api, scheduler_headers
    ):
        """PRD §3.7: "Finally, the nomination's existing `committed_dth` plus this
        batch's `gross_mmbtu` must not exceed the nomination's `nominated_dth`, or the
        attachment is refused with `ERR_NOMINATION_VOLUME_EXCEEDED`."

        Design: Corner/errors/attaching_a_batch_larger_than_the_nomination_is_rejected
        """
        context = fixtures.setup_commercial_desk(
            nomination_overrides={"nominated_dth": 100.0}
        )
        batch = fixtures.create_batch(context["plant"]["id"])
        analysed = fixtures.analyse_batch(batch["id"])
        assert analysed["status"] == "ON_SPEC"
        assert fixtures.read_plant(context["plant"]["id"])["spec_status"] == "ON_SPEC", (
            "no safety rule can fire first here"
        )

        validate_error(
            api.set_injection_batch_status(
                batch["id"],
                {"to_status": "NOMINATED", "nomination_id": context["nomination"]["id"]},
                scheduler_headers,
            ),
            ApiErrorId.ERR_NOMINATION_VOLUME_EXCEEDED.value,
        )

        unchanged_batch = fixtures.read_injection_batch(batch["id"])
        assert unchanged_batch["status"] == "ON_SPEC"
        assert unchanged_batch["nomination_id"] is None

        unchanged_nomination = fixtures.read_nomination(context["nomination"]["id"])
        assert unchanged_nomination["committed_dth"] == approx_2dp(0.0)
        assert unchanged_nomination["status"] == "CONFIRMED"


class TestInjectionAndTrueUp:
    def test_injection_delivers_the_nomination_at_the_inclusive_boundary(
        self, api, operator_headers
    ):
        """PRD §3.7: "Injection is where the energy ledger finally moves: the site's
        `energy_produced_mmbtu` and `energy_injected_mmbtu` each rise by the batch's
        `gross_mmbtu`, the nomination's `delivered_dth` rises by the same figure, and the
        offtake contract's `delivered_dth_mtd` rises by it too. If that push takes the
        nomination's `delivered_dth` to or beyond its `nominated_dth`, the nomination
        advances from `SCHEDULED` to `DELIVERED`."

        Design: Corner/state_machines/nomination_auto_delivers_when_delivered_dth_reaches_nominated_dth
        """
        context = fixtures.setup_nominated_batch(
            nomination_overrides={"nominated_dth": 340.14}
        )
        nomination_id = context["nomination"]["id"]

        injected = validate_success(
            api.set_injection_batch_status(
                context["batch"]["id"], {"to_status": "INJECTED"}, operator_headers
            )
        )
        assert injected["status"] == "INJECTED"

        nomination = fixtures.read_nomination(nomination_id)
        assert nomination["hourly_rate_dth"] == approx_4dp(14.1725)
        assert nomination["delivered_dth"] == approx_2dp(340.14)
        assert nomination["committed_dth"] == approx_2dp(340.14)
        assert nomination["status"] == "DELIVERED", (
            "delivered_dth landing exactly on nominated_dth is enough"
        )

        contract = fixtures.read_contract(context["contract"]["id"])
        assert contract["delivered_dth_mtd"] == approx_2dp(340.14)

        site = fixtures.read_site(context["site"]["id"])
        assert site["energy_injected_mmbtu"] == approx_2dp(340.14)
        assert site["energy_produced_mmbtu"] == approx_2dp(340.14)

    def test_meter_trueup_writes_the_metered_volume_and_nothing_else(
        self, api, scheduler_headers
    ):
        """PRD §3.7: "The true-up is deliberately inert: it does **not** alter
        `gross_mmbtu`, does not move the site energy ledger, and does not restate any
        attribute batch already generated. Its only effect is to make `metered_mmbtu`
        non-null, and that is the sole route by which a settled-metered environmental
        attribute batch can ever be generated."
        PRD §2.3: "Injection batches filter on `plant_id`, `nomination_id` and `status`."

        Design: Corner/endpoints/meter_trueup_action_sets_metered_only_and_leaves_ledger_untouched
        """
        context = fixtures.setup_injected_batch()
        batch_id = context["batch"]["id"]
        nomination_id = context["nomination"]["id"]

        trued_up = validate_success(
            api.meter_trueup(batch_id, {"metered_mmbtu": 352.40}, scheduler_headers)
        )
        assert trued_up["metered_mmbtu"] == approx_2dp(352.40)
        assert trued_up["gross_mmbtu"] == approx_2dp(340.14)
        assert trued_up["status"] == "INJECTED"

        site = fixtures.read_site(context["site"]["id"])
        assert site["energy_injected_mmbtu"] == approx_2dp(340.14)
        assert site["energy_produced_mmbtu"] == approx_2dp(340.14)
        assert fixtures.read_nomination(nomination_id)["delivered_dth"] == approx_2dp(
            340.14
        )

        rows, meta = validate_paginated(
            api.list_injection_batches(
                scheduler_headers,
                params={"nomination_id": nomination_id, "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == batch_id

    def test_a_voided_batch_is_terminal_and_refuses_re_analysis(
        self, api, operator_headers
    ):
        """PRD §3.7: "Voiding a batch that never entered any bucket, meaning one still in
        `DRAFT`, `ON_SPEC` or `OFF_SPEC`, moves no ledger at all. `INJECTED`,
        `DIVERTED_TO_FLARE` and `VOIDED` are terminal."
        PRD §2.5: "**State legality (priority 80).** The target resource sits in a state
        from which the requested transition is declared, or `ERR_INVALID_TRANSITION` with
        HTTP 409."

        Design: Corner/state_machines/voided_injection_batch_is_terminal_and_rejects_reanalysis
        """
        set_clock(BASE_CLOCK_UTC)
        site = fixtures.create_site()
        plant = fixtures.create_plant(site["id"])
        batch = fixtures.create_batch(plant["id"])

        voided = validate_success(
            api.set_injection_batch_status(
                batch["id"],
                {
                    "to_status": "VOIDED",
                    "void_reason": "Duplicate hour block entered by the operator",
                },
                operator_headers,
            )
        )
        assert voided["status"] == "VOIDED"

        validate_error(
            api.set_injection_batch_status(
                batch["id"], {"to_status": "PENDING_ANALYSIS"}, operator_headers
            ),
            ApiErrorId.ERR_INVALID_TRANSITION.value,
        )

        unchanged = fixtures.read_injection_batch(batch["id"])
        assert unchanged["status"] == "VOIDED"
        assert unchanged["void_reason"] == "Duplicate hour block entered by the operator"
        assert fixtures.read_site(site["id"])["energy_produced_mmbtu"] == approx_2dp(0.0)
