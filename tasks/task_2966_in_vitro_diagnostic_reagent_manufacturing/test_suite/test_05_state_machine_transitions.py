"""State machines: declared start states, refused transitions and the states
that are only ever reached as a system cascade.

Every aggregate in this API owns its own lifecycle and its own state error
identifier, and a finished lot owns two lifecycles at once.  The tests below
drive each machine to a boundary and check both the transition that is allowed
and the one that is refused.
"""
from prd_bench_local_runner.testing import (validate_error, validate_paginated,
                                            validate_success)
from test_helpers import assertions, constants, factories, fixtures
from test_helpers.test_users import (DISTRIBUTION_PLANNER,
                                     DISTRIBUTION_PLANNER_USER_ID,
                                     PRODUCTION_OPERATOR, QA_RELEASER,
                                     QA_RELEASER_2, QA_RELEASER_USER_ID,
                                     QC_ANALYST, REGULATORY_AFFAIRS,
                                     REGULATORY_AFFAIRS_USER_ID)

# The clock instant every timestamp assertion in this file is pinned against.
START_INSTANT = constants.DEFAULT_CLOCK_UTC


class TestDeclaredInitialStates:
    """What each aggregate looks like the instant it is created."""

    def test_material_lot_product_and_finished_lot_start_states(self, api):
        """PRD §3.1: "The lot is created in `qualification_status` `RECEIVED`,
        with `available_quantity_units` initialised to `received_quantity_units`,
        `consumed_quantity_units` initialised to 0, `retest_count` at 0, and
        `first_oos_at`, `acceptance_score`, `dispositioned_by_user_id`,
        `dispositioned_at` and `quarantine_reason` all null."
        PRD §3.2: "Every new specification starts with `clearance_status`
        `DESIGN`, `design_trace_complete` false, and `submission_ref` and
        `cleared_at` null."
        PRD §3.3: "The new lot starts with `disposition_status` `PLANNED` on the
        quality axis and `distribution_status` `WITHHELD` on the availability
        axis, with all five unit counters — `filled_units`, `available_units`,
        `allocated_units`, `shipped_units` and `quarantined_units` — initialised
        to 0, which satisfies the finished-goods ledger of §2.8 trivially."

        Design: Corner/state_machines/every_machine_assigns_its_declared_initial_state_on_create
        """
        spec = fixtures.create_material_specification(api)
        material_lot = fixtures.create_material_lot(api, spec["id"])
        assertions.assert_material_lot(material_lot)
        assert material_lot["qualification_status"] == "RECEIVED"
        assert (float(material_lot["available_quantity_units"])
                == float(material_lot["received_quantity_units"]))
        assert float(material_lot["consumed_quantity_units"]) == 0
        assert material_lot["retest_count"] == 0
        for field in ("first_oos_at", "acceptance_score",
                      "dispositioned_by_user_id", "dispositioned_at",
                      "quarantine_reason"):
            assertions.assert_absent_or_none(material_lot, field, "material lot")
        assertions.assert_material_quantity_conservation(material_lot)

        product = fixtures.create_product_specification(api)
        assertions.assert_product_specification(product)
        assert product["clearance_status"] == "DESIGN"
        assert product["design_trace_complete"] is False
        assertions.assert_absent_or_none(product, "submission_ref", "product")
        assertions.assert_absent_or_none(product, "cleared_at", "product")

        reagent_lot = fixtures.create_reagent_lot(api, product["id"])
        assertions.assert_reagent_lot(reagent_lot)
        assert reagent_lot["disposition_status"] == "PLANNED"
        assert reagent_lot["distribution_status"] == "WITHHELD"
        for counter in ("filled_units", "available_units", "allocated_units",
                        "shipped_units", "quarantined_units"):
            assert reagent_lot[counter] == 0, counter
        assertions.assert_reagent_lot_unit_conservation(reagent_lot)

        persisted_material = validate_success(
            api.get_material_lot(material_lot["id"], QC_ANALYST))
        assert persisted_material["qualification_status"] == "RECEIVED"
        persisted_product = validate_success(
            api.get_product_specification(product["id"], REGULATORY_AFFAIRS))
        assert persisted_product["clearance_status"] == "DESIGN"
        assert persisted_product["design_trace_complete"] is False
        persisted_lot = validate_success(
            api.get_reagent_lot(reagent_lot["id"], PRODUCTION_OPERATOR))
        assert persisted_lot["disposition_status"] == "PLANNED"
        assert persisted_lot["distribution_status"] == "WITHHELD"

    def test_fill_run_and_stability_study_start_states(self, api):
        """PRD §3.4: "New runs are created in `status` `SCHEDULED` with
        `environmental_state` initialised to `CONFORMING`,
        `minor_excursion_count` and `major_excursion_count` at 0, and
        `filled_units`, `started_at`, `ended_at`, `bioburden_cfu_per_ml` and
        `abort_reason` all null."
        PRD §3.6: "New studies start in `status` `PROTOCOL_DRAFT` with
        `timepoint_count` at 0 and `last_conforming_month`,
        `established_shelf_life_months`, `shelf_life_method` and
        `protocol_approved_by_user_id` all null."

        Design: Corner/state_machines/every_machine_assigns_its_declared_initial_state_on_create
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])

        run = fixtures.schedule_fill_run(api, lot["id"])
        assertions.assert_fill_run(run)
        assert run["status"] == "SCHEDULED"
        assert run["environmental_state"] == "CONFORMING"
        assert run["minor_excursion_count"] == 0
        assert run["major_excursion_count"] == 0
        for field in ("filled_units", "started_at", "ended_at",
                      "bioburden_cfu_per_ml", "abort_reason"):
            assertions.assert_absent_or_none(run, field, "fill run")

        study = fixtures.create_stability_study(api, product["id"], lot["id"])
        assertions.assert_stability_study(study)
        assert study["status"] == "PROTOCOL_DRAFT"
        assert study["timepoint_count"] == 0
        for field in ("last_conforming_month", "established_shelf_life_months",
                      "shelf_life_method", "protocol_approved_by_user_id"):
            assertions.assert_absent_or_none(study, field, "stability study")

        persisted_run = validate_success(
            api.get_fill_run(run["id"], PRODUCTION_OPERATOR))
        assert persisted_run["status"] == "SCHEDULED"
        assert persisted_run["environmental_state"] == "CONFORMING"
        persisted_study = validate_success(
            api.get_stability_study(study["id"], QA_RELEASER))
        assert persisted_study["status"] == "PROTOCOL_DRAFT"
        assert persisted_study["timepoint_count"] == 0

    def test_bridging_study_complaint_and_order_start_states(self, api):
        """PRD §3.7: "The study is created in `status` `DRAFT` with
        `equivalence_verdict` `PENDING`, `decided_by_user_id` and `decided_at`
        null, and `mean_bias_pct` and `max_bias_pct` computed immediately from
        whatever data both lots already carry."
        PRD §3.8: "The server stamps `received_at` from the logical clock — this
        is the instant every reporting deadline is measured from — and creates
        the complaint in `status` `RECEIVED` with `severity`,
        `malfunction_suspected`, `reportable`, `report_due_at`, `report_ref`,
        `reported_at`, `report_late`, `field_action`,
        `field_action_decided_by_user_id`, `field_action_decided_at` and
        `triaged_by_user_id` all null."
        PRD §3.9: "Orders are created in `status` `DRAFT` with `allocated_units`
        and `shortfall_units` both 0 and `planner_user_id` stamped from the
        acting operator."

        Design: Corner/state_machines/every_machine_assigns_its_declared_initial_state_on_create
        """
        fixtures.set_clock(api, START_INSTANT)
        material = fixtures.qualified_material(api)
        product = fixtures.create_product_specification(api)
        predicate = fixtures.create_reagent_lot(api, product["id"])
        candidate = fixtures.create_reagent_lot(api, product["id"])

        study = fixtures.create_bridging_study(api, predicate["id"],
                                               candidate["id"],
                                               material["lot"]["id"],
                                               paired_test_codes=["ACTIVITY"])
        assertions.assert_bridging_study(study)
        assert study["status"] == "DRAFT"
        assert study["equivalence_verdict"] == "PENDING"
        assertions.assert_absent_or_none(study, "decided_by_user_id", "bridge")
        assertions.assert_absent_or_none(study, "decided_at", "bridge")

        complaint = fixtures.create_complaint(api, candidate["id"])
        assertions.assert_complaint(complaint)
        assert complaint["status"] == "RECEIVED"
        assertions.assert_same_instant(complaint["received_at"], START_INSTANT,
                                       "received_at")
        for field in ("severity", "malfunction_suspected", "reportable",
                      "report_due_at", "report_ref", "reported_at",
                      "report_late", "field_action",
                      "field_action_decided_by_user_id",
                      "field_action_decided_at", "triaged_by_user_id"):
            assertions.assert_absent_or_none(complaint, field, "complaint")

        order = fixtures.create_distribution_order(api, product["id"],
                                                   requested_units=100)
        assertions.assert_distribution_order(order)
        assert order["status"] == "DRAFT"
        assert order["allocated_units"] == 0
        # Creation pins both counters at 0, whatever `requested_units` asks for.
        assert order["shortfall_units"] == 0
        assert order["planner_user_id"] == DISTRIBUTION_PLANNER_USER_ID

        persisted_study = validate_success(
            api.get_bridging_study(study["id"], QA_RELEASER))
        assert persisted_study["status"] == "DRAFT"
        assert persisted_study["equivalence_verdict"] == "PENDING"
        persisted_complaint = validate_success(
            api.get_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert persisted_complaint["status"] == "RECEIVED"
        persisted_order = validate_success(
            api.get_distribution_order(order["id"], DISTRIBUTION_PLANNER))
        assert persisted_order["status"] == "DRAFT"
        assert persisted_order["allocated_units"] == 0
        assert persisted_order["shortfall_units"] == 0


class TestFillRunStateGuards:
    """The filling machine's own refusals, and what they leave behind."""

    def test_completing_a_scheduled_run_is_refused(self, api):
        """PRD §3.4: "The run must be `RUNNING`, the `filled_units` must be no
        greater than the run's `planned_fill_units` (equality is fine), and at
        least one `BIOBURDEN_BULK` monitoring sample must already exist on the
        run — a run cannot be closed out without bulk bioburden evidence."
        PRD §2.6: "The code is the owning aggregate's own state code —
        `ERR_MATERIAL_LOT_STATE_INVALID`, `ERR_PRODUCT_STATE_INVALID`,
        `ERR_DESIGN_RECORD_STATE_INVALID`, `ERR_REAGENT_LOT_STATE_INVALID`,
        `ERR_FILL_RUN_STATE_INVALID`, `ERR_STABILITY_STUDY_STATE_INVALID`,
        `ERR_BRIDGING_STUDY_STATE_INVALID`, `ERR_COMPLAINT_STATE_INVALID`,
        `ERR_ORDER_STATE_INVALID` or `ERR_ALLOCATION_STATE_INVALID` — all with
        HTTP 409."
        PRD §3.4: "New runs are created in `status` `SCHEDULED` with
        `environmental_state` initialised to `CONFORMING`,
        `minor_excursion_count` and `major_excursion_count` at 0, and
        `filled_units`, `started_at`, `ended_at`, `bioburden_cfu_per_ml` and
        `abort_reason` all null."

        Design: Corner/state_machines/fill_run_complete_from_scheduled_returns_state_invalid
        """
        bundle = fixtures.reagent_lot_with_bom(api)
        run = fixtures.schedule_fill_run(api, bundle["lot"]["id"])
        # Bulk bioburden evidence is admissible while the run is SCHEDULED, so
        # the only unmet condition left is the RUNNING state itself.
        fixtures.record_bioburden_sample(api, run["id"])
        assert run["status"] == "SCHEDULED"

        response = api.complete_fill_run(
            run["id"],
            factories.fill_run_complete_payload(run["planned_fill_units"]),
            PRODUCTION_OPERATOR)
        validate_error(response, "ERR_FILL_RUN_STATE_INVALID", 409)

        persisted_run = validate_success(
            api.get_fill_run(run["id"], PRODUCTION_OPERATOR))
        assert persisted_run["status"] == "SCHEDULED"
        assertions.assert_absent_or_none(persisted_run, "filled_units", "run")
        assertions.assert_absent_or_none(persisted_run, "ended_at", "run")

        persisted_lot = validate_success(
            api.get_reagent_lot(bundle["lot"]["id"], PRODUCTION_OPERATOR))
        assert persisted_lot["disposition_status"] == "PLANNED"
        assert persisted_lot["distribution_status"] == "WITHHELD"
        assert persisted_lot["filled_units"] == 0
        assert persisted_lot["available_units"] == 0

    def test_starting_a_running_run_a_second_time_is_refused(self, api):
        """PRD §3.4: "Starting a run advances the run from `SCHEDULED` to
        `RUNNING` and, on the parent's quality axis, advances
        `disposition_status` from `PLANNED` to `IN_PROCESS`."
        PRD §3.4: "A start against a run that is already `RUNNING`, `COMPLETED`
        or `ABORTED` is refused with `ERR_FILL_RUN_STATE_INVALID`."
        PRD §3.4: "On success `started_at` is stamped from the logical clock and
        the finished lot's `version` increases by 1."

        Design: Corner/state_machines/fill_run_start_twice_returns_state_invalid_on_the_second_call
        """
        bundle = fixtures.reagent_lot_with_bom(api)
        lot_version_before = bundle["lot"]["version"]
        run = fixtures.schedule_fill_run(api, bundle["lot"]["id"])

        fixtures.set_clock(api, START_INSTANT)
        started = fixtures.start_fill_run(api, run["id"])
        assert started["status"] == "RUNNING"
        assertions.assert_same_instant(started["started_at"], START_INSTANT,
                                       "started_at")

        response = api.start_fill_run(run["id"], PRODUCTION_OPERATOR)
        validate_error(response, "ERR_FILL_RUN_STATE_INVALID", 409)

        persisted_run = validate_success(
            api.get_fill_run(run["id"], PRODUCTION_OPERATOR))
        assert persisted_run["status"] == "RUNNING"
        assertions.assert_same_instant(persisted_run["started_at"],
                                       START_INSTANT, "started_at")

        persisted_lot = validate_success(
            api.get_reagent_lot(bundle["lot"]["id"], PRODUCTION_OPERATOR))
        assert persisted_lot["disposition_status"] == "IN_PROCESS"
        assert persisted_lot["distribution_status"] == "WITHHELD"
        # One accepted start, so exactly one version step on the parent lot.
        assert persisted_lot["version"] == lot_version_before + 1


class TestFillRunCompletionCascade:
    """A disqualified run and the auto-rejection its completion fires."""

    def test_a_result_at_twice_the_limit_disqualifies_the_run(self, api):
        """PRD §3.4: "The four monitoring channels each have their own action
        limit, which the server writes onto the sample as `limit_value`: viable
        air is limited to 10 colony-forming units per cubic metre, surface
        sampling to 5 colony-forming units, non-viable particle counting to 3,520
        particles per cubic metre, and bulk bioburden to 10 colony-forming units
        per millilitre."
        PRD §3.4: "`excursion` is true exactly when `result_value` is strictly
        greater than `limit_value`; a result equal to its limit is conforming."
        PRD §3.4: "`excursion_grade` is `MAJOR` when `result_value` is at least
        twice `limit_value`, `MINOR` when the sample is an excursion but has not
        reached twice the limit, and `NONE` when it is not an excursion at all."
        PRD §3.4: "From those counts comes `environmental_state`: `DISQUALIFIED`
        when `major_excursion_count` is at least 1 or `minor_excursion_count` is
        at least 3, otherwise `EXCURSION` when `minor_excursion_count` is at
        least 1, and otherwise `CONFORMING`."

        Design: Corner/state_machines/fill_run_completion_with_a_major_excursion_auto_rejects_the_reagent_lot
        """
        bundle = fixtures.running_fill_run(api)
        run_id = bundle["run"]["id"]

        # Viable air is limited to 10 CFU/m3, so 20.0 is exactly twice the limit:
        # an excursion (20.0 > 10) and MAJOR (20.0 >= 2 x 10).
        sample = fixtures.record_monitoring_sample(api, run_id, "VIABLE_AIR", 20.0)
        assertions.assert_monitoring_sample(sample)
        assert float(sample["limit_value"]) == 10.0
        assert sample["excursion"] is True
        assert sample["excursion_grade"] == "MAJOR"

        persisted_run = validate_success(
            api.get_fill_run(run_id, PRODUCTION_OPERATOR))
        assert persisted_run["status"] == "RUNNING"
        assert persisted_run["major_excursion_count"] == 1
        assert persisted_run["minor_excursion_count"] == 0
        assert persisted_run["environmental_state"] == "DISQUALIFIED"

    def test_completing_a_disqualified_run_auto_rejects_the_lot(self, api):
        """PRD §3.4: "Hop 1: the run's `status` becomes `COMPLETED`,
        `filled_units` and `ended_at` are stored, and `environmental_state` is
        recomputed."
        PRD §3.4: "Hop 2: because the run completed, the finished lot's
        `filled_units` increases by the run's `filled_units`, its
        `available_units` increases by the same amount, `fill_completed_at` is
        stamped from the logical clock if and only if it was still null (so it
        anchors on the **first** completed run of the lot and is never moved by a
        later one), and `disposition_status` becomes `FILLED`."
        PRD §3.4: "Hop 3: because the lot reached `FILLED`, if the completed
        run's `environmental_state` is `DISQUALIFIED` the lot is auto-rejected on
        the spot — `disposition_status` becomes `REJECTED`, `available_units` is
        forced to 0, and `distribution_status` stays `WITHHELD`."
        PRD §2.8: "The invariant is that `received_quantity_units` always equals
        `available_quantity_units` plus `consumed_quantity_units`."

        Design: Corner/state_machines/fill_run_completion_with_a_major_excursion_auto_rejects_the_reagent_lot
        """
        bundle = fixtures.running_fill_run(api)
        run_id = bundle["run"]["id"]
        planned_fill_units = bundle["run"]["planned_fill_units"]
        fixtures.record_bioburden_sample(api, run_id)
        fixtures.record_monitoring_sample(api, run_id, "VIABLE_AIR", 20.0)

        fixtures.set_clock(api, START_INSTANT)
        completed = fixtures.complete_fill_run(api, run_id, planned_fill_units)
        assert completed["status"] == "COMPLETED"
        assert completed["filled_units"] == planned_fill_units
        assert completed["environmental_state"] == "DISQUALIFIED"
        assertions.assert_same_instant(completed["ended_at"], START_INSTANT,
                                       "ended_at")

        lot = validate_success(
            api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
        assert lot["filled_units"] == planned_fill_units
        assert lot["disposition_status"] == "REJECTED"
        assert lot["available_units"] == 0
        assert lot["distribution_status"] == "WITHHELD"
        assertions.assert_same_instant(lot["fill_completed_at"], START_INSTANT,
                                       "fill_completed_at")

        # The dispensing rows stay CONSUMED, so the raw ledger is untouched.
        material_lot = validate_success(
            api.get_material_lot(bundle["materials"][0]["lot"]["id"], QC_ANALYST))
        assertions.assert_material_quantity_conservation(material_lot)
        assert float(material_lot["consumed_quantity_units"]) > 0


class TestMaterialLotStateGuards:
    """A freshly booked-in raw material lot admits no disposition at all."""

    def test_every_disposition_on_a_received_lot_is_refused(self, api):
        """PRD §3.1: "`QUALIFY` requires the lot to be `UNDER_TEST`, requires
        every code in `required_test_codes` to have at least one measurement on
        the lot, and requires the acceptance verdict to be `ACCEPT`."
        PRD §3.1: "`REJECT` is accepted from either `UNDER_TEST` or
        `OOS_INVESTIGATION` and needs nothing beyond that state."
        PRD §3.1: "`INVESTIGATE` is accepted only from `UNDER_TEST` and only when
        at least one measurement on the lot has `outcome` `FAIL`; it moves the lot
        to `OOS_INVESTIGATION` and increases `version` by 1."
        PRD §3.1: "Any disposition against a lot in a state that admits no such
        move — a `QUALIFY` on a `RECEIVED` lot, any disposition on a `REJECTED`
        or `QUARANTINED` lot — is refused with
        `ERR_MATERIAL_LOT_STATE_INVALID`."

        Design: Corner/state_machines/material_lot_disposition_from_received_returns_material_lot_state_invalid
        """
        spec = fixtures.create_material_specification(api)
        lot = fixtures.create_material_lot(api, spec["id"])
        assert lot["qualification_status"] == "RECEIVED"
        version_before = lot["version"]

        for decision in ("QUALIFY", "REJECT", "INVESTIGATE"):
            response = api.disposition_material_lot(
                lot["id"],
                factories.material_lot_disposition_payload(decision),
                QA_RELEASER)
            validate_error(response, "ERR_MATERIAL_LOT_STATE_INVALID", 409)

        persisted = validate_success(api.get_material_lot(lot["id"], QC_ANALYST))
        assert persisted["qualification_status"] == "RECEIVED"
        assert persisted["version"] == version_before
        assert (float(persisted["available_quantity_units"])
                == float(persisted["received_quantity_units"]))
        assertions.assert_absent_or_none(persisted, "dispositioned_by_user_id",
                                         "material lot")
        assertions.assert_absent_or_none(persisted, "dispositioned_at",
                                         "material lot")


class TestProductAndDesignRecordTransitions:
    """Clearance, approval and the supersession cascade of the design file."""

    def test_a_second_clearance_on_a_cleared_product_is_refused(self, api):
        """PRD §3.2: "A `RegulatoryAffairs` user records it by supplying the
        `submission_ref`, and the request is admitted only when the
        specification's `clearance_status` is `DESIGN` — clearance on an already
        `CLEARED` or `WITHDRAWN` product is refused with
        `ERR_PRODUCT_STATE_INVALID` — and only when `design_trace_complete` is
        true, failing which the answer is `ERR_DESIGN_TRACE_INCOMPLETE`."
        PRD §3.2: "On success `clearance_status` becomes `CLEARED`,
        `submission_ref` and `cleared_at` are stored, and `version` increases by
        1."
        PRD §3.2: "A design output therefore always sits at depth 2, and a
        verification or validation always at depth 3."

        Design: Corner/state_machines/product_specification_second_clearance_returns_product_state_invalid
        """
        fixtures.set_clock(api, START_INSTANT)
        product = fixtures.create_product_specification(api)
        records = fixtures.design_history_file(api, product["id"])
        assert records["design_input"]["trace_depth"] == 1
        assert records["design_output"]["trace_depth"] == 2
        assert records["verification"]["trace_depth"] == 3
        assert records["validation"]["trace_depth"] == 3

        version_before = fixtures.product_specification_version(api, product["id"])
        first_payload = factories.clearance_payload()
        cleared = validate_success(api.record_product_clearance(
            product["id"], first_payload, REGULATORY_AFFAIRS))
        assert cleared["clearance_status"] == "CLEARED"
        assert cleared["design_trace_complete"] is True
        assert cleared["submission_ref"] == first_payload["submission_ref"]
        assertions.assert_same_instant(cleared["cleared_at"], START_INSTANT,
                                       "cleared_at")
        assert cleared["version"] == version_before + 1

        response = api.record_product_clearance(
            product["id"], factories.clearance_payload(), REGULATORY_AFFAIRS)
        validate_error(response, "ERR_PRODUCT_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_product_specification(product["id"], REGULATORY_AFFAIRS))
        assert persisted["clearance_status"] == "CLEARED"
        assert persisted["submission_ref"] == first_payload["submission_ref"]
        assertions.assert_same_instant(persisted["cleared_at"], START_INSTANT,
                                       "cleared_at")
        assert persisted["version"] == version_before + 1

    def test_approving_a_record_whose_predecessor_is_draft_is_refused(self, api):
        """PRD §3.2: "When `record_type` is anything other than `DESIGN_INPUT`,
        the record named by `traces_to_record_id` must itself be in `status`
        `APPROVED`, which forces the file to be approved from the bottom of the
        trace upward, one hop at a time."
        PRD §3.2: "First, the record must be in `DRAFT`; a record that is already
        `APPROVED` or has been `SUPERSEDED` cannot be approved, and neither can
        one whose predecessor is not yet `APPROVED` — both are refused with
        `ERR_DESIGN_RECORD_STATE_INVALID`."

        Design: Corner/state_machines/design_record_approve_twice_and_approve_out_of_trace_order_are_rejected
        """
        product = fixtures.create_product_specification(api)
        design_input = fixtures.file_design_record(api, product["id"],
                                                   "DESIGN_INPUT")
        design_output = fixtures.file_design_record(
            api, product["id"], "DESIGN_OUTPUT",
            traces_to_record_id=design_input["id"])
        assert design_input["status"] == "DRAFT"
        assert design_output["status"] == "DRAFT"

        response = api.approve_design_control_record(design_output["id"],
                                                     QA_RELEASER)
        validate_error(response, "ERR_DESIGN_RECORD_STATE_INVALID", 409)

        still_draft = validate_success(
            api.get_design_control_record(design_output["id"], QA_RELEASER))
        assert still_draft["status"] == "DRAFT"
        assertions.assert_absent_or_none(still_draft, "approved_by_user_id",
                                         "design record")
        assertions.assert_absent_or_none(still_draft, "approved_at",
                                         "design record")

        # Bottom-up: once the depth-1 predecessor is APPROVED the same call works.
        approved_input = fixtures.approve_design_record(api, design_input["id"])
        assert approved_input["status"] == "APPROVED"
        approved_output = fixtures.approve_design_record(api, design_output["id"])
        assert approved_output["status"] == "APPROVED"

    def test_approving_an_already_approved_record_is_refused(self, api):
        """PRD §3.2: "Approval of a design-control record belongs to a
        `QAReleaser`, and it moves the record from `DRAFT` to `APPROVED`,
        stamping `approved_by_user_id` and `approved_at`."
        PRD §3.2: "First, the record must be in `DRAFT`; a record that is already
        `APPROVED` or has been `SUPERSEDED` cannot be approved, and neither can
        one whose predecessor is not yet `APPROVED` — both are refused with
        `ERR_DESIGN_RECORD_STATE_INVALID`."
        PRD §3.2: "A successful approval recomputes the parent's
        `design_trace_complete` flag and increases the parent product
        specification's `version` by 1."

        Design: Corner/state_machines/design_record_approve_twice_and_approve_out_of_trace_order_are_rejected
        """
        fixtures.set_clock(api, START_INSTANT)
        product = fixtures.create_product_specification(api)
        design_input = fixtures.file_design_record(api, product["id"],
                                                   "DESIGN_INPUT")

        approved = fixtures.approve_design_record(api, design_input["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == QA_RELEASER_USER_ID
        assertions.assert_same_instant(approved["approved_at"], START_INSTANT,
                                       "approved_at")
        record_version = approved["version"]
        parent_version = fixtures.product_specification_version(api,
                                                                product["id"])

        response = api.approve_design_control_record(design_input["id"],
                                                     QA_RELEASER_2)
        validate_error(response, "ERR_DESIGN_RECORD_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_design_control_record(design_input["id"], QA_RELEASER))
        assert persisted["status"] == "APPROVED"
        assert persisted["approved_by_user_id"] == QA_RELEASER_USER_ID
        assert persisted["version"] == record_version
        assert (fixtures.product_specification_version(api, product["id"])
                == parent_version)

    def test_refiling_the_same_document_ref_supersedes_the_approved_record(self, api):
        """PRD §3.2: "Filing a record has one further effect that catches people
        out: if an `APPROVED` record already exists on the same
        `product_specification_id` with the same `record_type` **and** the same
        `document_ref`, that older record's `status` becomes `SUPERSEDED` — the
        terminal state of this machine — as an immediate system cascade."
        PRD §3.2: "Every new record is created in `status` `DRAFT` with
        `authored_by_user_id` stamped from the filing operator, and
        `approved_by_user_id` and `approved_at` null."
        PRD §3.2: "Filing also recomputes the parent's `design_trace_complete`
        flag and increases the parent product specification's `version` by 1,
        which is exactly why the next filer needs a fresh
        `expected_product_specification_version`."
        PRD §3.2: "Looking only at records on this product specification whose
        `status` is `APPROVED` — `DRAFT` and `SUPERSEDED` records are excluded
        entirely — the flag `design_trace_complete` becomes true when there is at
        least one record with `record_type` `VERIFICATION` at `trace_depth` 3
        **and** at least one record with `record_type` `VALIDATION` at
        `trace_depth` 3."
        PRD §2.10: "Cascades are **immediate and synchronous**: by the time a
        response is returned, every downstream row the operation touches has
        already been updated, every recomputed counter already reflects the new
        reality, and every touched row has had its `updated_at` refreshed and its
        `version` increased by 1."

        Design: Corner/state_machines/design_record_resubmission_supersedes_the_approved_predecessor
        """
        product = fixtures.create_product_specification(api)
        shared_ref = factories.unique_document_ref()
        design_input = fixtures.file_design_record(api, product["id"],
                                                   "DESIGN_INPUT",
                                                   document_ref=shared_ref)
        design_output = fixtures.file_design_record(
            api, product["id"], "DESIGN_OUTPUT",
            traces_to_record_id=design_input["id"])
        approved_input = fixtures.approve_design_record(api, design_input["id"])
        approved_output = fixtures.approve_design_record(api, design_output["id"])
        parent_version_before = fixtures.product_specification_version(
            api, product["id"])

        refiled = fixtures.file_design_record(api, product["id"], "DESIGN_INPUT",
                                              document_ref=shared_ref)
        assertions.assert_design_control_record(refiled)
        assert refiled["status"] == "DRAFT"
        assert refiled["trace_depth"] == 1
        assert refiled["authored_by_user_id"] == REGULATORY_AFFAIRS_USER_ID
        assertions.assert_absent_or_none(refiled, "approved_by_user_id",
                                         "design record")
        assertions.assert_absent_or_none(refiled, "approved_at",
                                         "design record")

        superseded = validate_success(
            api.get_design_control_record(design_input["id"], QA_RELEASER))
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["approved_by_user_id"] == QA_RELEASER_USER_ID
        assert superseded["version"] == approved_input["version"] + 1

        # Only the same record_type and document_ref is superseded.
        untouched = validate_success(
            api.get_design_control_record(design_output["id"], QA_RELEASER))
        assert untouched["status"] == "APPROVED"
        assert untouched["version"] == approved_output["version"]

        parent = validate_success(
            api.get_product_specification(product["id"], REGULATORY_AFFAIRS))
        assert parent["version"] == parent_version_before + 1
        # No APPROVED VERIFICATION and no APPROVED VALIDATION exist at all.
        assert parent["design_trace_complete"] is False

        rows, meta = validate_paginated(api.list_design_control_records(
            QA_RELEASER, {"product_specification_id": product["id"],
                          "record_type": "DESIGN_INPUT"}))
        assert meta["total_count"] == 2
        assert {row["status"] for row in rows} == {"DRAFT", "SUPERSEDED"}


class TestStabilityStudyTransitions:
    """PROTOCOL_DRAFT, APPROVED and the first timepoint that starts the clock."""

    def test_a_timepoint_on_a_protocol_draft_study_is_refused(self, api):
        """PRD §3.6: "Only then may timepoints be pulled; a timepoint against a
        study still in `PROTOCOL_DRAFT` is refused with
        `ERR_STABILITY_STUDY_STATE_INVALID`."
        PRD §3.6: "The first timepoint advances the study from `APPROVED` to
        `IN_PROGRESS`; each subsequent timepoint is a self-loop on `IN_PROGRESS`
        and additionally requires that no measurement with the same
        `stability_study_id`, `month_index` and `test_code` already exists."
        PRD §3.6: "Both hops recompute `timepoint_count` — the count of
        measurements carrying this `stability_study_id` — and
        `last_conforming_month`, and both increase the study's `version` by 1."

        Design: Corner/state_machines/stability_timepoint_on_protocol_draft_returns_stability_state_invalid
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        study = fixtures.create_stability_study(
            api, product["id"], lot["id"], planned_timepoints_months=[0, 3, 6])
        assert study["status"] == "PROTOCOL_DRAFT"

        response = api.create_test_result(
            factories.stability_test_result_payload(study["id"], 0, "ACTIVITY",
                                                    98.0),
            QC_ANALYST)
        validate_error(response, "ERR_STABILITY_STUDY_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_stability_study(study["id"], QA_RELEASER))
        assert persisted["status"] == "PROTOCOL_DRAFT"
        assert persisted["timepoint_count"] == 0
        assertions.assert_absent_or_none(persisted, "last_conforming_month",
                                         "stability study")
        assert persisted["version"] == study["version"]

        rows, meta = validate_paginated(api.list_test_results(
            QC_ANALYST, {"stability_study_id": study["id"]}))
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_first_timepoint_moves_the_study_to_in_progress(self, api):
        """PRD §3.6: "A `QAReleaser` approves the protocol, which moves `status`
        from `PROTOCOL_DRAFT` to `APPROVED`, records
        `protocol_approved_by_user_id`, and increases `version` by 1."
        PRD §3.6: "The server computes `recovery_pct` as `measured_value` divided
        by the study's `baseline_value`, multiplied by 100 and rounded half-up to
        two decimal places, and sets `outcome` to `PASS` when `recovery_pct` is at
        least 90.00 — inclusively — and `FAIL` otherwise."
        PRD §3.6: "The first timepoint advances the study from `APPROVED` to
        `IN_PROGRESS`; each subsequent timepoint is a self-loop on `IN_PROGRESS`
        and additionally requires that no measurement with the same
        `stability_study_id`, `month_index` and `test_code` already exists."
        PRD §3.6: "Both hops recompute `timepoint_count` — the count of
        measurements carrying this `stability_study_id` — and
        `last_conforming_month`, and both increase the study's `version` by 1."
        PRD §3.6: "It is the largest planned month index such that every planned
        index at or below it has at least one recorded timepoint whose
        `recovery_pct` is at least 90.00."

        Design: Corner/state_machines/stability_first_timepoint_moves_the_study_from_approved_to_in_progress
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        study = fixtures.create_stability_study(
            api, product["id"], lot["id"], planned_timepoints_months=[0, 3, 6])
        assert float(study["baseline_value"]) == 100.00

        approved = fixtures.approve_stability_protocol(api, study["id"])
        assert approved["status"] == "APPROVED"
        assert approved["protocol_approved_by_user_id"] == QA_RELEASER_USER_ID
        assert approved["version"] == study["version"] + 1

        # 98.0 / 100.00 * 100 = 98.00, which is at least 90.00, so PASS.
        result = fixtures.record_timepoint(api, study["id"], 0, 98.0)
        assertions.assert_test_result(result)
        assert float(result["recovery_pct"]) == 98.00
        assert result["outcome"] == "PASS"
        assertions.assert_absent_or_none(result, "bias_pct", "timepoint")

        persisted = validate_success(
            api.get_stability_study(study["id"], QA_RELEASER))
        assert persisted["status"] == "IN_PROGRESS"
        assert persisted["timepoint_count"] == 1
        # Month 0 conforms and is the largest planned index whose whole prefix does.
        assert persisted["last_conforming_month"] == 0
        assert persisted["version"] == approved["version"] + 1

    def test_repeating_a_timepoint_key_is_refused_and_the_self_loop_holds(self, api):
        """PRD §3.6: "The `month_index` must be a member of the study's
        `planned_timepoints_months`, otherwise `ERR_TIMEPOINT_NOT_PLANNED` with
        HTTP 422, and the combination of `stability_study_id`, `month_index` and
        `test_code` must not already exist, otherwise `ERR_DUPLICATE_TIMEPOINT`."
        PRD §3.6: "The first timepoint advances the study from `APPROVED` to
        `IN_PROGRESS`; each subsequent timepoint is a self-loop on `IN_PROGRESS`
        and additionally requires that no measurement with the same
        `stability_study_id`, `month_index` and `test_code` already exists."
        PRD §3.6: "Both hops recompute `timepoint_count` — the count of
        measurements carrying this `stability_study_id` — and
        `last_conforming_month`, and both increase the study's `version` by 1."

        Design: Corner/state_machines/stability_first_timepoint_moves_the_study_from_approved_to_in_progress
        """
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        study = fixtures.create_stability_study(
            api, product["id"], lot["id"], planned_timepoints_months=[0, 3, 6])
        fixtures.approve_stability_protocol(api, study["id"])
        fixtures.record_timepoint(api, study["id"], 0, 98.0)
        after_first = validate_success(
            api.get_stability_study(study["id"], QA_RELEASER))
        assert after_first["status"] == "IN_PROGRESS"

        response = api.create_test_result(
            factories.stability_test_result_payload(study["id"], 0, "ACTIVITY",
                                                    97.0),
            QC_ANALYST)
        validate_error(response, "ERR_DUPLICATE_TIMEPOINT", 409)

        unchanged = validate_success(
            api.get_stability_study(study["id"], QA_RELEASER))
        assert unchanged["status"] == "IN_PROGRESS"
        assert unchanged["timepoint_count"] == 1
        assert unchanged["version"] == after_first["version"]

        # A fresh key is a self-loop: still IN_PROGRESS, one more measurement.
        fixtures.record_timepoint(api, study["id"], 3, 98.0)
        looped = validate_success(
            api.get_stability_study(study["id"], QA_RELEASER))
        assert looped["status"] == "IN_PROGRESS"
        assert looped["timepoint_count"] == 2
        assert looped["last_conforming_month"] == 3
        assert looped["version"] == after_first["version"] + 1


def _bridge_over_two_available_lots(api):
    """A predicate lot and a candidate lot both `RELEASED` and `AVAILABLE`, a
    `QUALIFIED` critical raw material lot named as the changed material, and a
    `DRAFT` bridging study over one paired code whose candidate measures 8.00 per
    cent above its predicate.

    Returns ``{"predicate", "candidate", "changed_material", "study"}``.
    """
    setup = fixtures.manufacturing_setup(
        api, product_overrides={"max_reference_bias_pct": 10.0})
    predicate = fixtures.released_reagent_lot(api, setup=setup)["lot"]

    candidate_bundle = fixtures.filled_reagent_lot(api, setup=setup)
    candidate_id = candidate_bundle["lot"]["id"]
    # |108.0 - 100.0| / 100.0 * 100 = 8.00, inside the product's 10.0 bias limit
    # for release but outside the 3.00 mean-bias equivalence threshold.
    fixtures.record_passing_release_tests(api, candidate_id, setup["product"],
                                          measured_value=108.0,
                                          reference_measured_value=100.0)
    candidate = fixtures.disposition_reagent_lot(api, candidate_id, "RELEASE")

    changed_material = fixtures.qualified_material(
        api, spec_overrides={"is_critical": True})["lot"]
    study = fixtures.create_bridging_study(api, predicate["id"], candidate["id"],
                                           changed_material["id"],
                                           paired_test_codes=["ACTIVITY"])
    return {"predicate": predicate, "candidate": candidate,
            "changed_material": changed_material, "study": study}


class TestBridgingStudyDecisions:
    """DRAFT is the only decidable state, and a rejection cascades outward."""

    def test_a_second_decision_on_a_decided_study_is_refused(self, api):
        """PRD §3.7: "Either way the study must be in `DRAFT`; a study that has
        already reached `APPROVED` or `FAILED` is terminal and a further decision
        is refused with `ERR_BRIDGING_STUDY_STATE_INVALID`."
        PRD §3.7: "On success the study's `status` becomes the terminal
        `APPROVED`, `decided_by_user_id` and `decided_at` are recorded, and the
        study's `version` increases by 1."
        PRD §3.7: "Nothing outside the study changes — no field on the candidate
        lot is written, and in particular `bridging_required` is not cleared."
        PRD §3.7: "`equivalence_verdict` becomes `EQUIVALENT` when
        `mean_bias_pct` is at most 3.00 **and** `max_bias_pct` is at most 5.00,
        both boundaries inclusive, and `NOT_EQUIVALENT` when either threshold is
        exceeded."

        Design: Corner/state_machines/bridging_study_second_decision_is_rejected_from_a_terminal_state
        """
        fixtures.set_clock(api, START_INSTANT)
        built = fixtures.bridging_candidate(api)
        study = fixtures.create_bridging_study(
            api, built["predicate"]["id"], built["candidate"]["id"],
            built["changed_material"]["id"], paired_test_codes=["ACTIVITY"])
        # Both lots measured 100.00 on ACTIVITY, so every paired bias is 0.00.
        assert study["equivalence_verdict"] == "EQUIVALENT"

        approved = fixtures.decide_bridging_study(api, study["id"], "APPROVE")
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == QA_RELEASER_USER_ID
        assertions.assert_same_instant(approved["decided_at"], START_INSTANT,
                                       "decided_at")
        assert approved["version"] == study["version"] + 1

        response = api.decide_bridging_study(
            study["id"], factories.bridging_decision_payload("REJECT"),
            QA_RELEASER)
        validate_error(response, "ERR_BRIDGING_STUDY_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_bridging_study(study["id"], QA_RELEASER))
        assert persisted["status"] == "APPROVED"
        assert persisted["equivalence_verdict"] == "EQUIVALENT"
        assert persisted["version"] == approved["version"]

        # An approval touches nothing outside the study, and the refused REJECT
        # fired no cascade of its own.
        material = validate_success(
            api.get_material_lot(built["changed_material"]["id"], QC_ANALYST))
        assert material["qualification_status"] == "QUALIFIED"
        assert float(material["available_quantity_units"]) > 0
        candidate = validate_success(
            api.get_reagent_lot(built["candidate"]["id"], QA_RELEASER))
        assert candidate["disposition_status"] == "UNDER_RELEASE_TEST"
        assert candidate["distribution_status"] == "WITHHELD"

    def test_rejecting_a_bridge_quarantines_the_changed_material_lot(self, api):
        """PRD §3.7: "A `REJECT` decision carries no extra gates beyond the
        `DRAFT` state and fires a three-hop cascade."
        PRD §3.7: "Hop 1: the study's `status` becomes the terminal `FAILED`,
        `decided_by_user_id` and `decided_at` are recorded, and the study's
        `version` increases by 1."
        PRD §3.7: "Hop 2: because the bridge failed, the raw material lot named
        by `changed_material_lot_id` moves from `QUALIFIED` to the terminal
        `QUARANTINED` state, with a `quarantine_reason` recorded and
        `available_quantity_units` forced to 0, and its `version` increases by
        1."

        Design: Corner/state_machines/bridging_study_failure_quarantines_the_changed_material_and_blocks_the_candidate_lot
        """
        fixtures.set_clock(api, START_INSTANT)
        scenario = _bridge_over_two_available_lots(api)
        study = scenario["study"]
        material_before = scenario["changed_material"]
        assert material_before["qualification_status"] == "QUALIFIED"
        # mean 8.00 > 3.00, so the verdict cannot be EQUIVALENT.
        assert study["equivalence_verdict"] == "NOT_EQUIVALENT"

        failed = fixtures.decide_bridging_study(api, study["id"], "REJECT")
        assert failed["status"] == "FAILED"
        assert failed["decided_by_user_id"] == QA_RELEASER_USER_ID
        assertions.assert_same_instant(failed["decided_at"], START_INSTANT,
                                       "decided_at")
        assert failed["version"] == study["version"] + 1

        material = validate_success(
            api.get_material_lot(material_before["id"], QC_ANALYST))
        assert material["qualification_status"] == "QUARANTINED"
        assert float(material["available_quantity_units"]) == 0
        assert material["quarantine_reason"] is not None
        assert material["version"] == material_before["version"] + 1

    def test_rejecting_a_bridge_blocks_the_available_candidate_only(self, api):
        """PRD §3.7: "Hop 2b: because the bridge failed, the candidate finished
        lot's `distribution_status` becomes `BLOCKED` when it is currently
        `AVAILABLE`, with its `version` increased by 1; a candidate that is still
        `WITHHELD` is left as it is, since it was never on the market."
        PRD §2.10: "The two axes evolve independently, have different actors, and
        have different terminal semantics; a single request may advance one axis,
        or both."

        Design: Corner/state_machines/bridging_study_failure_quarantines_the_changed_material_and_blocks_the_candidate_lot
        """
        scenario = _bridge_over_two_available_lots(api)
        candidate_before = scenario["candidate"]
        predicate_before = scenario["predicate"]
        assert candidate_before["disposition_status"] == "RELEASED"
        assert candidate_before["distribution_status"] == "AVAILABLE"

        fixtures.decide_bridging_study(api, scenario["study"]["id"], "REJECT")

        candidate = validate_success(
            api.get_reagent_lot(candidate_before["id"], QA_RELEASER))
        # Only the availability axis moves; the quality axis stays RELEASED.
        assert candidate["disposition_status"] == "RELEASED"
        assert candidate["distribution_status"] == "BLOCKED"
        assert candidate["version"] == candidate_before["version"] + 1

        predicate = validate_success(
            api.get_reagent_lot(predicate_before["id"], QA_RELEASER))
        assert predicate["disposition_status"] == "RELEASED"
        assert predicate["distribution_status"] == "AVAILABLE"
        assert predicate["version"] == predicate_before["version"]


class TestComplaintTerminalState:
    """`CLOSED` admits nothing further, from either branch of the fork."""

    def test_a_closed_non_reportable_complaint_refuses_triage_and_close(self, api):
        """PRD §3.8: "Triage is performed by a `RegulatoryAffairs` user on a
        complaint still in `RECEIVED`, supplying the `severity` as `LOW`,
        `MEDIUM` or `HIGH` and the boolean `malfunction_suspected` conclusion."
        PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."
        PRD §3.8: "`report_due_at` is `received_at` advanced by 5 days when
        `device_related_death_or_injury` is true and by 30 days otherwise, and it
        is null whenever `reportable` is false."
        PRD §3.8: "A `RegulatoryAffairs` user closes the complaint, which is
        admitted while `status` is `TRIAGED`, `MALFUNCTION_REPORTED` or
        `FIELD_ACTION_DECIDED` — a close on a `RECEIVED` or already `CLOSED`
        complaint is refused with `ERR_COMPLAINT_STATE_INVALID`."
        PRD §3.8: "And when `reportable` is true, `reported_at` must not be null,
        so the reporting branch must also have run; a close attempted on a
        reportable complaint whose `reported_at` is still null is refused with
        `ERR_MALFUNCTION_REPORT_PENDING`."

        Design: Corner/state_machines/complaint_closed_is_terminal_against_every_remaining_trigger
        """
        fixtures.set_clock(api, START_INSTANT)
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        complaint = fixtures.create_complaint(api, lot["id"])

        triaged = fixtures.triage_complaint(api, complaint["id"], "LOW", False)
        assert triaged["status"] == "TRIAGED"
        assert triaged["reportable"] is False
        assertions.assert_absent_or_none(triaged, "report_due_at", "complaint")

        decided = fixtures.decide_field_action(api, complaint["id"], "NONE")
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        assert decided["field_action"] == "NONE"

        closed = validate_success(
            api.close_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"
        # Not reportable, so closure is legitimate with reported_at still null.
        assertions.assert_absent_or_none(closed, "reported_at", "complaint")
        assert closed["version"] == decided["version"] + 1

        retriage = api.triage_complaint(
            complaint["id"], factories.triage_payload("HIGH", True),
            REGULATORY_AFFAIRS)
        validate_error(retriage, "ERR_COMPLAINT_STATE_INVALID", 409)
        reclose = api.close_complaint(complaint["id"], REGULATORY_AFFAIRS)
        validate_error(reclose, "ERR_COMPLAINT_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert persisted["status"] == "CLOSED"
        assert persisted["severity"] == "LOW"
        assert persisted["malfunction_suspected"] is False
        assert persisted["field_action"] == "NONE"
        assert persisted["version"] == closed["version"]

    def test_a_closed_complaint_refuses_a_further_field_action(self, api):
        """PRD §3.8: "It requires the complaint's `status` to be either `TRIAGED`
        or `MALFUNCTION_REPORTED`; it requires the acting `X-User-ID` to differ
        from the implicated lot's `released_by_user_id`, per §2.9, on pain of
        `ERR_SEGREGATION_OF_DUTIES`; and a `field_action` of `REMOVAL`
        additionally requires `severity` to be `HIGH`, failing which the request
        is refused with `ERR_FIELD_ACTION_NOT_JUSTIFIED`."
        PRD §3.8: "A `RegulatoryAffairs` user closes the complaint, which is
        admitted while `status` is `TRIAGED`, `MALFUNCTION_REPORTED` or
        `FIELD_ACTION_DECIDED` — a close on a `RECEIVED` or already `CLOSED`
        complaint is refused with `ERR_COMPLAINT_STATE_INVALID`."
        PRD §3.8: "Hop 2: the implicated finished lot, which must be in
        `disposition_status` `RELEASED`, moves to the terminal `RECALLED` state
        and its `distribution_status` becomes `BLOCKED`; its `version` increases
        by 1."

        Design: Corner/state_machines/complaint_closed_is_terminal_against_every_remaining_trigger
        """
        bundle = fixtures.complaint_on_released_lot(api, severity="LOW",
                                                    malfunction_suspected=False)
        complaint = bundle["complaint"]
        lot_before = validate_success(
            api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))

        decided = fixtures.decide_field_action(api, complaint["id"], "NONE")
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        closed = validate_success(
            api.close_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"

        response = api.decide_field_action(
            complaint["id"], factories.field_action_payload("CORRECTION"),
            QA_RELEASER_2)
        validate_error(response, "ERR_COMPLAINT_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert persisted["status"] == "CLOSED"
        assert persisted["field_action"] == "NONE"
        assert persisted["version"] == closed["version"]

        # The refused CORRECTION fired no recall: the lot is untouched.
        lot = validate_success(
            api.get_reagent_lot(bundle["lot"]["id"], QA_RELEASER))
        assert lot["disposition_status"] == "RELEASED"
        assert lot["distribution_status"] == "AVAILABLE"
        assert lot["version"] == lot_before["version"]

    def test_a_closed_reportable_complaint_refuses_a_further_report(self, api):
        """PRD §3.8: "`reportable` is true when `malfunction_suspected` is true
        **and** at least one of the following holds:
        `device_related_death_or_injury` is true, or `severity` is `HIGH`."
        PRD §3.8: "The complaint's `status` becomes `MALFUNCTION_REPORTED` when it
        was `TRIAGED`, and **stays** `FIELD_ACTION_DECIDED` when the other branch
        has already run, so the field-action outcome is never overwritten by the
        report."
        PRD §3.8: "It requires `reportable` to be true and requires the
        complaint's `status` to be either `TRIAGED` or `FIELD_ACTION_DECIDED`; a
        report against a complaint still in `RECEIVED`, or against one already in
        `MALFUNCTION_REPORTED` or `CLOSED`, is refused with
        `ERR_COMPLAINT_STATE_INVALID`."
        PRD §3.8: "On success `status` becomes the terminal `CLOSED` and `version`
        increases by 1."

        Design: Corner/state_machines/complaint_closed_is_terminal_against_every_remaining_trigger
        """
        fixtures.set_clock(api, START_INSTANT)
        product = fixtures.create_product_specification(api)
        lot = fixtures.create_reagent_lot(api, product["id"])
        complaint = fixtures.create_complaint(api, lot["id"])

        triaged = fixtures.triage_complaint(api, complaint["id"], "HIGH", True)
        assert triaged["reportable"] is True

        reported = fixtures.file_malfunction_report(api, complaint["id"])
        assert reported["status"] == "MALFUNCTION_REPORTED"
        first_report_ref = reported["report_ref"]

        decided = fixtures.decide_field_action(api, complaint["id"], "NONE")
        assert decided["status"] == "FIELD_ACTION_DECIDED"
        closed = validate_success(
            api.close_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert closed["status"] == "CLOSED"
        assert closed["version"] == decided["version"] + 1

        response = api.file_malfunction_report(
            complaint["id"], factories.malfunction_report_payload(),
            REGULATORY_AFFAIRS)
        validate_error(response, "ERR_COMPLAINT_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_complaint(complaint["id"], REGULATORY_AFFAIRS))
        assert persisted["status"] == "CLOSED"
        assert persisted["report_ref"] == first_report_ref
        assertions.assert_same_instant(persisted["reported_at"], START_INSTANT,
                                       "reported_at")
        assert persisted["version"] == closed["version"]


class TestDistributionStateTransitions:
    """Order and reservation lifecycles, including the two bubble-ups."""

    def test_a_second_allocation_on_an_allocated_order_is_refused(self, api):
        """PRD §3.9: "Allocation takes no request payload — everything it needs is
        already on the order — and is admitted only when the order's `status` is
        `DRAFT`, so a second allocation on an already `ALLOCATED` order is refused
        with `ERR_ORDER_STATE_INVALID`."
        PRD §3.9: "The order's `allocated_units` becomes the total drawn, its
        `shortfall_units` becomes `requested_units` minus the total drawn but
        never below 0, and its `status` leaves `DRAFT` for `ALLOCATED` when the
        need was fully met and for `PARTIALLY_ALLOCATED` when any need remained —
        the second outcome is reachable only under `FEFO_WITH_SHORTFALL`."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."

        Design: Corner/state_machines/distribution_order_allocate_twice_returns_order_state_invalid
        """
        bundle = fixtures.allocated_order(api, requested_units=200)
        order = bundle["order"]
        assert order["status"] == "ALLOCATED"
        assert order["allocated_units"] == 200
        assert order["shortfall_units"] == 0
        filled_units = bundle["lot"]["filled_units"]

        response = api.allocate_distribution_order(order["id"],
                                                   DISTRIBUTION_PLANNER)
        validate_error(response, "ERR_ORDER_STATE_INVALID", 409)

        rows, meta = validate_paginated(api.list_distribution_order_allocations(
            order["id"], DISTRIBUTION_PLANNER))
        # The refused call drew nothing: still exactly one reservation.
        assert meta["total_count"] == 1
        assert rows[0]["allocated_units"] == 200
        assert rows[0]["sequence_index"] == 1
        assert rows[0]["status"] == "RESERVED"

        persisted_order = validate_success(
            api.get_distribution_order(order["id"], DISTRIBUTION_PLANNER))
        assert persisted_order["status"] == "ALLOCATED"
        assert persisted_order["allocated_units"] == 200
        assert persisted_order["version"] == order["version"]

        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   QA_RELEASER))
        assert lot["allocated_units"] == 200
        assert lot["available_units"] == filled_units - 200
        assert lot["shipped_units"] == 0
        assert lot["quarantined_units"] == 0
        assertions.assert_reagent_lot_unit_conservation(lot)

    def test_shipping_a_cancelled_reservation_is_refused(self, api):
        """PRD §3.9: "It requires the reservation to be `RESERVED` — shipping a
        `CANCELLED` or already-`SHIPPED` row is refused with
        `ERR_ALLOCATION_STATE_INVALID` — requires the drawn lot's
        `distribution_status` to still be `AVAILABLE`, and re-checks shelf life at
        the moment of shipment: the drawn lot's remaining shelf life in whole days
        must be at least the product's `min_shelf_life_days_at_ship`, inclusively,
        otherwise the answer is `ERR_SHELF_LIFE_TOO_SHORT`."
        PRD §3.9: "The reservation moves to the terminal `CANCELLED` state, the
        lot's `allocated_units` decreases and its `available_units` increases by
        exactly that reservation's `allocated_units` — restoring the lot's
        counters to their pre-allocation values with no drift, because cancelled
        reservations count towards none of the four ledger buckets — and the
        reservation's `version` increases by 1."
        PRD §3.9: "The parent order then recomputes its `allocated_units` and
        `shortfall_units`, and where the recomputed `allocated_units` has fallen
        below `requested_units` and the order was `ALLOCATED`, the order drops to
        `PARTIALLY_ALLOCATED` with its `version` increased by 1."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."

        Design: Corner/state_machines/allocation_terminal_state_rejects_ship_and_cold_chain_event
        """
        bundle = fixtures.allocated_order(api, requested_units=200)
        allocation = bundle["allocations"][0]
        filled_units = bundle["lot"]["filled_units"]

        cancelled = fixtures.cancel_allocation(api, allocation["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == allocation["version"] + 1

        response = api.ship_allocation(allocation["id"], DISTRIBUTION_PLANNER)
        validate_error(response, "ERR_ALLOCATION_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_allocation(allocation["id"], DISTRIBUTION_PLANNER))
        assert persisted["status"] == "CANCELLED"
        assertions.assert_absent_or_none(persisted, "shipped_at", "reservation")
        assert persisted["version"] == cancelled["version"]

        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   QA_RELEASER))
        assert lot["allocated_units"] == 0
        assert lot["shipped_units"] == 0
        assert lot["available_units"] == filled_units
        assertions.assert_reagent_lot_unit_conservation(lot)

        order = validate_success(
            api.get_distribution_order(bundle["order"]["id"],
                                       DISTRIBUTION_PLANNER))
        assert order["status"] == "PARTIALLY_ALLOCATED"
        assert order["allocated_units"] == 0
        assert order["shortfall_units"] == 200

    def test_a_cold_chain_event_on_a_cancelled_reservation_is_refused(self, api):
        """PRD §3.9: "The reservation must be in `status` `SHIPPED`; a cold-chain
        event against a `RESERVED` row is refused with
        `ERR_ALLOCATION_STATE_INVALID`."
        PRD §3.9: "The reservation moves to the terminal `CANCELLED` state, the
        lot's `allocated_units` decreases and its `available_units` increases by
        exactly that reservation's `allocated_units` — restoring the lot's
        counters to their pre-allocation values with no drift, because cancelled
        reservations count towards none of the four ledger buckets — and the
        reservation's `version` increases by 1."
        PRD §3.9: "Each event re-derives the cumulative picture:
        `cumulative_excursion_minutes` becomes the sum of `excursion_minutes` over
        every cold-chain event ever recorded against this reservation, and
        `max_excursion_temp_c` becomes the largest `max_temp_c` across those
        events, staying null while no event exists."
        PRD §3.9: "Otherwise it is `EXCURSION_ACCEPTABLE` when
        `cumulative_excursion_minutes` is greater than 0, and `INTACT` when it is
        0."

        Design: Corner/state_machines/allocation_terminal_state_rejects_ship_and_cold_chain_event
        """
        bundle = fixtures.allocated_order(api, requested_units=200)
        allocation = bundle["allocations"][0]
        cancelled = fixtures.cancel_allocation(api, allocation["id"])
        assert cancelled["status"] == "CANCELLED"

        response = api.create_cold_chain_event(
            allocation["id"], factories.cold_chain_event_payload(30.0, 9.0),
            DISTRIBUTION_PLANNER)
        validate_error(response, "ERR_ALLOCATION_STATE_INVALID", 409)

        persisted = validate_success(
            api.get_allocation(allocation["id"], DISTRIBUTION_PLANNER))
        assert persisted["status"] == "CANCELLED"
        # No event was ever recorded, so the cumulative picture is untouched.
        assert float(persisted["cumulative_excursion_minutes"]) == 0
        assertions.assert_absent_or_none(persisted, "max_excursion_temp_c",
                                         "reservation")
        assert persisted["cold_chain_status"] == "INTACT"
        assert persisted["version"] == cancelled["version"]

    def test_shipping_the_last_reserved_row_advances_only_its_own_order(self, api):
        """PRD §3.9: "On success `shipped_at` is stored, the lot's
        `allocated_units` decreases and its `shipped_units` increases by that
        reservation's `allocated_units`, and the reservation's `version` increases
        by 1."
        PRD §3.9: "When no reservation of the parent order is left in `status`
        `RESERVED` after the call, the order advances from `ALLOCATED` or
        `PARTIALLY_ALLOCATED` to `SHIPPED` and its `version` increases by 1."
        PRD §2.8: "The invariant is that `filled_units` always equals
        `available_units` plus `allocated_units` plus `shipped_units` plus
        `quarantined_units`."

        Design: Corner/state_machines/distribution_order_bubbles_up_to_shipped_then_closed_as_its_allocations_finish
        """
        fixtures.set_clock(api, START_INSTANT)
        bundle = fixtures.allocated_order(api, requested_units=200)
        first_order = bundle["order"]
        filled_units = bundle["lot"]["filled_units"]

        second_order = fixtures.create_distribution_order(
            api, bundle["product"]["id"], requested_units=100)
        second_order = fixtures.allocate_order(api, second_order["id"])
        assert second_order["status"] == "ALLOCATED"
        assert second_order["allocated_units"] == 100

        allocation = bundle["allocations"][0]
        shipped = fixtures.ship_allocation(api, allocation["id"])
        assert shipped["status"] == "SHIPPED"
        assertions.assert_same_instant(shipped["shipped_at"], START_INSTANT,
                                       "shipped_at")
        assert shipped["version"] == allocation["version"] + 1

        persisted_first = validate_success(
            api.get_distribution_order(first_order["id"], DISTRIBUTION_PLANNER))
        assert persisted_first["status"] == "SHIPPED"
        assert persisted_first["version"] == first_order["version"] + 1

        # The second order still holds a RESERVED row, so it does not bubble up.
        persisted_second = validate_success(
            api.get_distribution_order(second_order["id"], DISTRIBUTION_PLANNER))
        assert persisted_second["status"] == "ALLOCATED"
        assert persisted_second["version"] == second_order["version"]

        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   QA_RELEASER))
        assert lot["shipped_units"] == 200
        assert lot["allocated_units"] == 100
        assert lot["available_units"] == filled_units - 300
        assertions.assert_reagent_lot_unit_conservation(lot)

    def test_confirming_delivery_closes_the_order(self, api):
        """PRD §3.9: "When `delivery_confirmed` is supplied as true and the
        cumulative verdict is either `INTACT` or `EXCURSION_ACCEPTABLE`, the
        reservation moves from `SHIPPED` to the terminal `DELIVERED` state; there
        is no separate delivery operation, so confirming delivery on a cold-chain
        event is the only route into `DELIVERED`."
        PRD §3.9: "Once every reservation of an order carries `status`
        `DELIVERED`, that order advances from `SHIPPED` to the terminal `CLOSED`
        state as a system cascade."
        PRD §3.9: "Otherwise it is `EXCURSION_ACCEPTABLE` when
        `cumulative_excursion_minutes` is greater than 0, and `INTACT` when it is
        0."
        PRD §2.8: "On a finished lot, `allocated_units` is the sum of
        `allocated_units` over its reservations whose `status` is `RESERVED`;
        `shipped_units` is the same sum over reservations whose `status` is
        `SHIPPED` or `DELIVERED`; `quarantined_units` is the same sum over
        reservations whose `status` is `QUARANTINED`; and `available_units` is
        `filled_units` minus `allocated_units` minus `shipped_units` minus
        `quarantined_units`."
        PRD §2.10: "Cascades are **immediate and synchronous**: by the time a
        response is returned, every downstream row the operation touches has
        already been updated, every recomputed counter already reflects the new
        reality, and every touched row has had its `updated_at` refreshed and its
        `version` increased by 1."

        Design: Corner/state_machines/distribution_order_bubbles_up_to_shipped_then_closed_as_its_allocations_finish
        """
        bundle = fixtures.shipped_allocation(api, requested_units=200)
        allocation = bundle["allocation"]
        order_after_ship = bundle["order"]
        assert allocation["status"] == "SHIPPED"
        assert order_after_ship["status"] == "SHIPPED"
        filled_units = bundle["lot"]["filled_units"]

        # Zero excursion minutes keeps the cumulative verdict INTACT, which is
        # what makes the confirmed delivery admissible.
        fixtures.record_cold_chain_event(api, allocation["id"], 0.0, 8.0,
                                         delivery_confirmed=True)

        persisted_allocation = validate_success(
            api.get_allocation(allocation["id"], DISTRIBUTION_PLANNER))
        assert persisted_allocation["status"] == "DELIVERED"
        assert float(persisted_allocation["cumulative_excursion_minutes"]) == 0
        assert float(persisted_allocation["max_excursion_temp_c"]) == 8.0
        assert persisted_allocation["cold_chain_status"] == "INTACT"

        order = validate_success(
            api.get_distribution_order(order_after_ship["id"],
                                       DISTRIBUTION_PLANNER))
        assert order["status"] == "CLOSED"
        assert order["version"] == order_after_ship["version"] + 1

        lot = validate_success(api.get_reagent_lot(bundle["lot"]["id"],
                                                   QA_RELEASER))
        # A DELIVERED reservation still counts in the shipped bucket.
        assert lot["shipped_units"] == 200
        assert lot["allocated_units"] == 0
        assert lot["available_units"] == filled_units - 200
        assertions.assert_reagent_lot_unit_conservation(lot)
