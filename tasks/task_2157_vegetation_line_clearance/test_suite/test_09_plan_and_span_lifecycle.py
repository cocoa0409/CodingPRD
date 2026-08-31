"""Work plans, spans, mapping, release, completion and the cancellation cascade."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, assert_work_order, file_production,
    new_booking, new_crew, new_prescription, new_work_order, read_booking,
    read_circuit, read_crew, read_line, read_plan, read_prescription, read_span,
    release_plan, release_span, setup_circuit, setup_completed_span,
    setup_completed_span_with_draft_line, setup_in_progress_span,
    setup_plan_with_mapped_span, setup_released_span, start_span,
    validate_error, validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
FORESTER = TEST_USERS["forester_headers"]


class TestSpanCreationAndMapping:

    def test_a_new_span_starts_on_both_dimensions_and_refreshes_the_plan(self, api):
        """PRD §3.3: "A new span sits at `execution_status` `PLANNED` and `billing_status`
        `NOT_BILLABLE`, and its creation immediately refreshes the owning plan's
        `planned_unit_count`."
        PRD §3.3: "The denominator, written back to the plan's `planned_unit_count`, is the sum
        of `planned_unit_count` over every span of the plan whose `execution_status` is not
        `CANCELLED` — cancelled spans leave the denominator entirely."

        Design: Corner/state_machines/corner_work_order_initial_states_on_both_dimensions
        """
        world = setup_circuit()
        from test_helpers import new_work_plan
        plan = new_work_plan(world["circuit"]["id"])

        resp = api.create_work_order({
            "work_plan_id": plan["id"], "span_miles": 2.5,
            "billing_method": "UNIT_PRICE", "planned_unit_count": 200}, PLANNER)
        span = validate_success(resp, 201)

        assert_work_order(span)
        assert span["execution_status"] == "PLANNED"
        assert span["billing_status"] == "NOT_BILLABLE"
        assert span["actual_units_completed"] == 0
        assert span["refusal_blocked_unit_count"] == 0
        assert read_plan(plan["id"])["planned_unit_count"] == 200

    def test_span_creation_without_the_billing_method_fails_validation(self, api):
        """PRD §3.3: "A `ContractorPlanner` creates each one against a `work_plan_id`,
        declaring the `span_miles` it covers (greater than zero), the `billing_method` the
        contract uses for it — either `UNIT_PRICE` or `TIME_AND_MATERIALS` — and the
        `planned_unit_count` of trim units, meaning trees or poles, budgeted for it (zero or
        more)."
        PRD §2.9: "Shape and value validation: required body fields present, enum values drawn
        from their declared sets, numeric fields inside their declared ranges, dates and
        datetimes well formed, and uniqueness respected on `circuit_code` across circuits,
        `crew_code` across crews, `event_code` across storm events, and `premise_code` within
        one span's notifications. Any of these fails with `ERR_VALIDATION` (400)."

        Design: Corner/entities/corner_work_order_create_missing_required_returns_invalid_request
        """
        world = setup_circuit()
        from test_helpers import new_work_plan
        plan = new_work_plan(world["circuit"]["id"])

        resp = api.create_work_order({
            "work_plan_id": plan["id"], "span_miles": 2.5,
            "planned_unit_count": 200}, PLANNER)

        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
        assert resp.status_code == 400
        _, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"work_plan_id": plan["id"]}))
        assert meta["total_count"] == 0
        assert read_plan(plan["id"])["planned_unit_count"] == 0

    def test_span_creation_against_an_unknown_plan_is_not_found(self, api):
        """PRD §2.5: "The same rule and the same codes govern foreign keys supplied in a
        request body. A body naming a circuit, span, booking, crew, permit or notification that
        does not exist fails with that entity's not-found code before any business rule touches
        the request."

        Design: Corner/entities/corner_work_order_create_unknown_plan_returns_not_found
        """
        new_prescription(activate=False)

        resp = api.create_work_order({
            "work_plan_id": "00000000-0000-4000-8000-000000000000", "span_miles": 2.5,
            "billing_method": "UNIT_PRICE", "planned_unit_count": 200}, PLANNER)

        validate_error(resp, ApiErrorId.ERR_WORK_PLAN_NOT_FOUND.value)
        assert resp.status_code == 404

    def test_mapping_below_the_prescribed_clearance_is_rejected(self, api):
        """PRD §3.3: "It also enforces the prescription: the supplied `clearance_radius_ft`
        must be at least the `clearance_radius_ft` of the prescription resolved onto the plan's
        circuit. A narrower cut is rejected with `ERR_CLEARANCE_BELOW_PRESCRIPTION` (HTTP 422);
        an equal radius is acceptable."

        Design: Corner/validations/corner_map_clearance_below_prescription_is_rejected
        """
        world = setup_circuit(prescription_clearance_ft=10)
        from test_helpers import new_work_plan
        plan = new_work_plan(world["circuit"]["id"])
        span = new_work_order(plan["id"])

        resp = api.map_work_order(span["id"], {"clearance_radius_ft": 8}, PLANNER)

        validate_error(resp, ApiErrorId.ERR_CLEARANCE_BELOW_PRESCRIPTION.value)
        assert resp.status_code == 422
        assert read_span(span["id"])["execution_status"] == "PLANNED"


class TestPlanAndSpanTransitionGuards:

    def test_a_plan_with_no_mapped_span_cannot_be_released(self, api):
        """PRD §3.3: "A plan may be released only from `DRAFT`, and only if at least one of its
        spans is sitting at `MAPPED`; a plan with no mapped span is rejected with
        `ERR_EMPTY_WORK_PLAN` (HTTP 422)."

        Design: Corner/state_machines/corner_work_plan_release_without_mapped_span_returns_empty_work_plan
        """
        world = setup_circuit()
        from test_helpers import new_work_plan
        plan = new_work_plan(world["circuit"]["id"])
        new_work_order(plan["id"])

        resp = api.release_work_plan(plan["id"], PLANNER)

        validate_error(resp, ApiErrorId.ERR_EMPTY_WORK_PLAN.value)
        assert resp.status_code == 422
        assert read_plan(plan["id"])["status"] == "DRAFT"
        assert read_circuit(world["circuit"]["id"])["trim_status"] == "NOT_SCHEDULED"

    def test_starting_a_span_that_was_never_released_is_not_declared(self, api):
        """PRD §3.3: "Starting a released span moves it `RELEASED → IN_PROGRESS` and requires
        at least one booking on that span sitting at `SCHEDULED`."
        PRD §2.9: "10. The target resource is in a state from which the requested transition is
        declared — `ERR_INVALID_STATE` (409). This applies to every transition endpoint."

        Design: Corner/state_machines/corner_work_order_start_from_mapped_returns_invalid_state
        """
        world = setup_plan_with_mapped_span()
        release_plan(world["plan"]["id"])

        resp = api.start_work_order(world["span"]["id"], PLANNER)

        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert resp.status_code == 409
        assert read_span(world["span"]["id"])["execution_status"] == "MAPPED"


class TestPrescriptionSupersessionBlocksRelease:

    @staticmethod
    def _released_plan_whose_prescription_was_superseded():
        world = setup_plan_with_mapped_span()
        release_plan(world["plan"]["id"])
        world["newer_prescription"] = new_prescription(
            voltage_class="DISTRIBUTION_12KV", growth_zone="RAPID", base_cycle_years=3,
            clearance_radius_ft=10, effective_from="2026-06-01")
        return world

    def test_span_release_is_blocked_while_the_resolved_prescription_is_superseded(self, api):
        """PRD §3.3: "Two things must hold: the plan itself must already be in `RELEASED` or
        `IN_PROGRESS`, and the prescription that the plan's circuit currently resolves to must
        still be in `ACTIVE`. If a newer prescription has since superseded it, span release
        fails with `ERR_PRESCRIPTION_NOT_ACTIVE` (HTTP 409) — the fix is for the forester to
        re-resolve the circuit first, which is precisely why prescription activation does not
        cascade onto circuits automatically."

        Design: Difficulty/cross_entity_state_dependency/work_order_release_blocked_by_superseded_prescription
        """
        world = self._released_plan_whose_prescription_was_superseded()

        resp = api.release_work_order(world["span"]["id"], PLANNER)

        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_ACTIVE.value)
        assert resp.status_code == 409
        assert read_prescription(world["prescription"]["id"])["status"] == "SUPERSEDED"
        assert read_prescription(world["newer_prescription"]["id"])["status"] == "ACTIVE"
        assert read_span(world["span"]["id"])["execution_status"] == "MAPPED"

    def test_re_resolving_the_circuit_recomputes_the_cycle_and_unblocks_release(self, api):
        """PRD §3.1: "Otherwise the candidates are ranked by `effective_from` descending — the
        latest effective date wins — and ties on `effective_from` are broken by `created_at`
        descending, so the most recently authored of two equally effective prescriptions is
        chosen."
        PRD §3.2: "This computation is re-run in four situations: when a circuit is registered,
        when a forester re-resolves its prescription, when an outage record changes the
        circuit's `reliability_tier`, and when a work plan reaches completion."

        Design: Difficulty/cross_entity_state_dependency/work_order_release_blocked_by_superseded_prescription
        """
        world = self._released_plan_whose_prescription_was_superseded()
        api.release_work_order(world["span"]["id"], PLANNER)

        resolved = validate_success(
            api.resolve_circuit_prescription(world["circuit"]["id"], FORESTER), 200)

        assert resolved["prescription_id"] == world["newer_prescription"]["id"]
        assert resolved["cycle_months"] == 27, "3 years * 12 * 0.75 (RAPID) * 1.00 = 27"
        assert resolved["next_trim_due_on"] == "2026-06-15"

        retry = validate_success(api.release_work_order(world["span"]["id"], PLANNER), 200)
        assert retry["execution_status"] == "RELEASED"


class TestCompletionAndCascades:

    def test_starting_a_span_settles_every_downstream_record_in_the_same_request(self, api):
        """PRD §3.3: "The start does three further things: every `SCHEDULED` booking on the
        span moves `SCHEDULED → ACTIVE`, the plan moves `RELEASED → IN_PROGRESS` if it was
        still merely released, and through that plan transition the circuit's `trim_status`
        moves `SCHEDULED → ACTIVE_CYCLE`."
        PRD §2.10: "Every such cascade is synchronous and immediate: by the time the response
        is written, every downstream record has already been updated, its `updated_at`
        refreshed and its `version` incremented."

        Design: Corner/consistency_model/corner_cascade_effects_are_visible_in_the_same_request
        """
        world = setup_released_span()
        crew = new_crew(crew_code="CRW-1")
        booking = new_booking(world["span"]["id"], crew["id"])

        started = validate_success(api.start_work_order(world["span"]["id"], PLANNER), 200)

        assert started["execution_status"] == "IN_PROGRESS"
        assert read_booking(booking["id"])["status"] == "ACTIVE"
        assert read_crew(crew["id"])["status"] == "ASSIGNED"
        plan = read_plan(world["plan"]["id"])
        assert plan["status"] == "IN_PROGRESS"
        assert plan["production_pct"] == pytest.approx(0.00, abs=0.001)
        assert read_circuit(world["circuit"]["id"])["trim_status"] == "ACTIVE_CYCLE"

    def test_completing_the_last_span_bubbles_the_plan_and_re_anchors_the_circuit(self, api):
        """PRD §3.3: "If every span of the plan is now in `COMPLETED` or `CANCELLED` and at
        least one is `COMPLETED`, the plan moves `IN_PROGRESS → COMPLETED`; that plan
        completion pushes the circuit's `trim_status` `ACTIVE_CYCLE → CYCLE_COMPLETE`, sets the
        circuit's `last_trim_completed_on` to the UTC date part of the logical clock,
        recomputes the circuit's `cycle_months` and `next_trim_due_on` from that new anchor,
        and increments the circuit's `version` by 1."
        PRD §3.3: "On success the span moves `IN_PROGRESS → COMPLETED`, its `completed_at` is
        stamped from the logical clock, its `billing_status` moves `NOT_BILLABLE → BILLABLE`,
        and every booking on the span still in `SCHEDULED` or `ACTIVE` is moved to `RELEASED`,
        with each freed crew returning `ASSIGNED → AVAILABLE` provided it holds no other
        booking in `SCHEDULED` or `ACTIVE`."

        Design: Corner/state_machines/corner_last_span_completion_bubbles_plan_and_circuit
        """
        world = setup_in_progress_span()
        file_production(world["booking"]["id"], world["crew"]["id"], work_date="2026-08-03",
                        units_trimmed=180, labor_hours=8, equipment_hours=6, disposal_tons=1)

        completed = validate_success(api.complete_work_order(world["span"]["id"], PLANNER), 200)

        assert completed["execution_status"] == "COMPLETED"
        assert completed["billing_status"] == "BILLABLE"
        plan = read_plan(world["plan"]["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["production_pct"] == pytest.approx(90.00, abs=0.001)
        circuit = read_circuit(world["circuit"]["id"])
        assert circuit["trim_status"] == "CYCLE_COMPLETE"
        assert circuit["last_trim_completed_on"] == "2026-08-01"
        assert circuit["cycle_months"] == 36
        assert circuit["next_trim_due_on"] == "2029-08-01"
        assert read_booking(world["booking"]["id"])["status"] == "RELEASED"
        assert read_crew(world["crew"]["id"])["status"] == "AVAILABLE"


class TestPlanCancellationCascade:

    def test_cancelling_the_plan_cancels_live_spans_frees_crews_and_voids_drafts(self, api):
        """PRD §3.3: "A `UtilityForester` may cancel the whole plan from `DRAFT`, `RELEASED`,
        `IN_PROGRESS` or `SUSPENDED`, and the cascade is identical whichever of those four
        states the plan was in: every span of the plan whose `execution_status` is not already
        `COMPLETED` or `CANCELLED` moves to `CANCELLED`, each of those spans releases its
        `SCHEDULED` and `ACTIVE` bookings and returns those crews to `AVAILABLE`, every `DRAFT`
        billing line on those spans moves `DRAFT → VOID`, the plan's `planned_unit_count` and
        `committed_cents` are both recomputed, and the circuit's `trim_status` returns to
        `NOT_SCHEDULED`."

        Design: Corner/state_machines/corner_work_plan_cancel_cascades_span_booking_and_draft_line
        """
        world = setup_completed_span_with_draft_line(
            extra_spans=[{"span_miles": 1.0, "billing_method": "UNIT_PRICE",
                          "planned_unit_count": 50}])
        live = world["extra_spans"][0]
        release_span(live["id"])
        live_booking = new_booking(live["id"], world["crew"]["id"],
                                   start_at="2026-08-05T08:00:00Z",
                                   end_at="2026-08-05T16:00:00Z")
        start_span(live["id"])

        cancelled = validate_success(api.cancel_work_plan(
            world["plan"]["id"], FORESTER, {"reason": "budget pulled"}), 200)

        assert cancelled["status"] == "CANCELLED"
        assert read_span(live["id"])["execution_status"] == "CANCELLED"
        assert read_span(world["span"]["id"])["execution_status"] == "COMPLETED", \
            "a span already in a terminal execution state is untouched"
        assert read_booking(live_booking["id"])["status"] == "RELEASED"
        assert read_crew(world["crew"]["id"])["status"] == "AVAILABLE"
        assert read_line(world["line"]["id"])["status"] == "VOID"
        plan = read_plan(world["plan"]["id"])
        assert plan["committed_cents"] == 0
        assert plan["planned_unit_count"] == 200, "the cancelled span leaves the denominator"
        assert read_circuit(world["circuit"]["id"])["trim_status"] == "NOT_SCHEDULED"

    def test_span_list_filters_by_execution_status(self, api):
        """PRD §3.8: "Spans can be listed filtered by `parent_work_order_id` to find remainder
        children and by `storm_event_id` to find spans attributed to a storm, alongside
        `work_plan_id`, `execution_status` and `billing_status`."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more`
        inside `meta`, where `total_count` is the number of records matching the request's
        filters before the page window is applied, and `has_more` is true exactly when records
        matching the filters remain beyond the current page."

        Design: Corner/endpoints/corner_work_orders_list_filters_by_execution_status
        """
        world = setup_completed_span()
        new_work_order(world["plan"]["id"], span_miles=1.0, billing_method="UNIT_PRICE",
                       planned_unit_count=50)

        rows, meta = validate_paginated(api.list_work_orders(
            PLANNER, params={"work_plan_id": world["plan"]["id"],
                             "execution_status": "COMPLETED"}))

        assert meta["total_count"] == 1
        assert rows[0]["id"] == world["span"]["id"]
        _, unfiltered = validate_paginated(api.list_work_orders(
            PLANNER, params={"work_plan_id": world["plan"]["id"]}))
        assert unfiltered["total_count"] == 2
