"""Route adjustments: consultation gate, segregation of duties, effective cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjustment_in_state,
    evaluation_consulted,
    evaluation_in_data_collection,
    get_adjustment,
    get_evaluation,
    get_point,
    get_route,
    get_success_data,
    list_sequence_entries,
    make_postmaster_headers,
    make_supervisor_headers,
    reset_clock,
    set_clock,
    setup_route_with_active_points,
    setup_unit_with_route,
    submit_counts_payload,
    validate_error,
    validate_success,
    create_point,
    activate_point,
    create_route,
    create_carrier,
)

SUP = TEST_USERS["supervisor_headers"]
PM = TEST_USERS["postmaster_headers"]
AMS = TEST_USERS["ams_headers"]

COUNTS = dict(letters_count_total=3600, flats_count_total=900, parcels_count_total=40,
              actual_street_minutes_total=2160, office_minutes_total=1440)


def _consulted_ctx(**kwargs):
    return evaluation_consulted(outcome="CONCURRED", counts=COUNTS, **kwargs)


class TestAdjustmentConsultationGate:

    def test_submit_blocked_until_evaluation_consulted(self, api):
        """PRD §3.7: "Submitting moves the adjustment `DRAFT → SUBMITTED`; it
        requires the parent evaluation to be `CONSULTED` (otherwise
        `ERR_CROSS_ENTITY_STATE`)".

        Design: Difficulty/cross_entity_state_dependency/adjustment_submit_gated_on_evaluation_consulted
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="MINI_SURVEY")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        get_success_data(api.submit_counts(unit_id, route_id, ev,
                                           submit_counts_payload(**COUNTS), SUP))
        # DRAFT adjustment creatable while merely CONSULTATION_SCHEDULED.
        adj = get_success_data(api.create_adjustment(
            unit_id, route_id, ev,
            {"proposed_evaluated_minutes": 545, "points_transferred_out": [],
             "effective_date": "2026-09-10"}, SUP))
        resp = api.submit_adjustment(unit_id, route_id, ev, adj["id"],
                                     make_supervisor_headers("sup-maria"))
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE)
        after = get_adjustment(unit_id, route_id, ev, adj["id"])
        assert after["status"] == "DRAFT"

    def test_submit_succeeds_once_evaluation_consulted(self, api):
        """PRD §3.7: "Submitting moves the adjustment `DRAFT → SUBMITTED`; it
        requires the parent evaluation to be `CONSULTED` (otherwise
        `ERR_CROSS_ENTITY_STATE`) and records the acting supervisor's `X-User-ID`
        as `submitter_user_id`".

        Design: Difficulty/cross_entity_state_dependency/adjustment_submit_gated_on_evaluation_consulted
        """
        reset_clock()
        ctx = _consulted_ctx(kind="MINI_SURVEY")
        ctx = adjustment_in_state(ctx, state="SUBMITTED",
                                  effective_date="2026-09-10")
        adj = get_adjustment(ctx["unit"]["id"], ctx["route"]["id"],
                             ctx["evaluation"]["id"], ctx["adjustment"]["id"])
        assert adj["status"] == "SUBMITTED"
        assert adj["submitter_user_id"] == "sup-maria"


class TestSegregationOfDuties:

    def test_priority_pair_segregation_beats_temporal(self, api):
        """PRD §2.9: "then universal-service-obligation safety (422), then
        segregation of duties (403), then cross-entity state gates
        (`ERR_CROSS_ENTITY_STATE`, 409), then temporal windows
        (`ERR_TEMPORAL_WINDOW`, 422)".
        PRD §2.6: "A matching approver is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_before_temporal_window_on_approve
        """
        reset_clock()
        ctx = _consulted_ctx(kind="FULL_COUNT")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        adj = get_success_data(api.create_adjustment(
            unit_id, route_id, ev,
            {"proposed_evaluated_minutes": 545, "points_transferred_out": [],
             "effective_date": "2026-09-03"}, SUP))
        get_success_data(api.submit_adjustment(
            unit_id, route_id, ev, adj["id"], make_supervisor_headers("sup-maria")))
        # Approver == submitter AND effective_date too soon: segregation wins.
        resp = api.approve_adjustment(unit_id, route_id, ev, adj["id"],
                                      make_postmaster_headers("sup-maria"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = get_adjustment(unit_id, route_id, ev, adj["id"])
        assert after["status"] == "SUBMITTED"

    def test_approve_by_different_postmaster_succeeds(self, api):
        """PRD §2.6: "only a `Postmaster` may approve or reject it; and the
        approving `X-User-ID` must differ from the `submitter_user_id` recorded at
        submission."
        PRD §3.7: "On approval the approver's id is recorded as `approver_user_id`
        and the route bubbles up `UNDER_EVALUATION → UNDER_ADJUSTMENT`."

        Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_before_temporal_window_on_approve
        """
        reset_clock()
        ctx = _consulted_ctx(kind="FULL_COUNT")
        ctx = adjustment_in_state(ctx, state="APPROVED",
                                  effective_date="2026-09-08")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        adj = get_adjustment(unit_id, route_id, ev, ctx["adjustment"]["id"])
        assert adj["status"] == "APPROVED"
        route = get_route(unit_id, route_id)
        assert route["status"] == "UNDER_ADJUSTMENT"

    def test_supervisor_submit_then_postmaster_approve_records_both_ids(self, api):
        """PRD §2.6: "The two identifiers are recorded on the adjustment for
        audit."
        PRD §3.7: "On approval the approver's id is recorded as `approver_user_id`
        and the route bubbles up `UNDER_EVALUATION → UNDER_ADJUSTMENT`."

        Design: Corner/rbac/supervisor_submit_then_postmaster_approve_completes_chain
        """
        reset_clock()
        ctx = _consulted_ctx(kind="MINI_SURVEY")
        ctx = adjustment_in_state(ctx, state="APPROVED",
                                  effective_date="2026-09-10")
        adj = get_adjustment(ctx["unit"]["id"], ctx["route"]["id"],
                             ctx["evaluation"]["id"], ctx["adjustment"]["id"])
        assert adj["status"] == "APPROVED"
        assert adj["submitter_user_id"] == "sup-maria"
        assert adj["approver_user_id"] == "pm-owens"
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["status"] == "UNDER_ADJUSTMENT"


class TestEffectiveCascade:

    def _two_route_ctx(self, api):
        """Unit with routes A (two active points) and B; APPROVED adjustment on A
        transferring its second point to B, effective 2026-09-08."""
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        car_b = create_carrier(unit_id)
        route_b = create_route(unit_id, car_b["id"])
        ctx["route_b"] = route_b
        ev = ctx.get("evaluation")
        return ctx

    def test_effective_cascades_through_points_sequences_evaluation(self, api):
        """PRD §3.7: "when the logical clock reaches the `effective_date`, the full
        adoption cascade fires atomically. The route's `current_evaluated_minutes`
        becomes the adjustment's `proposed_evaluated_minutes`,
        `under_evaluation_since` clears, the parent evaluation closes as
        `CLOSED_ADOPTED`, every transfer in `points_transferred_out` is applied —
        each point's `active_route_id` moves to its new route, both donor and
        receiving routes have their `active_delivery_point_count` recomputed, and
        both routes' sequence entries renumber per the cascade order in §3.5 — and
        the route returns `UNDER_ADJUSTMENT → STANDARD`".

        Design: Difficulty/transitive_cascade/adjustment_effective_cascades_through_points_sequences_evaluation
        """
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        route_a = ctx["route"]
        p1, p2 = ctx["points"]
        car_b = create_carrier(unit_id)
        route_b = create_route(unit_id, car_b["id"])
        # Walk route A's evaluation to CONSULTED.
        ctx = evaluation_consulted(ctx, outcome="CONCURRED", counts=COUNTS,
                                   kind="FULL_COUNT")
        ctx = adjustment_in_state(
            ctx, state="APPROVED", proposed_minutes=545,
            transfers=[{"delivery_point_id": p2["id"], "to_route_id": route_b["id"]}],
            effective_date="2026-09-08")
        set_clock("2026-09-08T00:00:00Z")
        adj = get_adjustment(unit_id, route_a["id"], ctx["evaluation"]["id"],
                             ctx["adjustment"]["id"])
        assert adj["status"] == "EFFECTIVE"
        ra = get_route(unit_id, route_a["id"])
        assert ra["status"] == "STANDARD"
        assert ra["current_evaluated_minutes"] == 545
        assert ra["active_delivery_point_count"] == 1
        p2_after = get_point(unit_id, p2["id"])
        assert p2_after["active_route_id"] == route_b["id"]
        rb = get_route(unit_id, route_b["id"])
        assert rb["active_delivery_point_count"] == 1
        entries_a = list_sequence_entries(unit_id, route_a["id"])
        assert len(entries_a) == 1
        assert entries_a[0]["line_of_travel_order"] == 1
        entries_b = list_sequence_entries(unit_id, route_b["id"])
        assert len(entries_b) == 1
        assert entries_b[0]["line_of_travel_order"] == 1
        assert entries_b[0]["delivery_point_id"] == p2["id"]
        ev = get_evaluation(unit_id, route_a["id"], ctx["evaluation"]["id"])
        assert ev["status"] == "CLOSED_ADOPTED"

    def test_point_transfer_preserves_unit_wide_active_point_count(self, api):
        """PRD §3.7: "each point's `active_route_id` moves to its new route, both
        donor and receiving routes have their `active_delivery_point_count`
        recomputed".

        Design: Difficulty/compensating_invariant/point_transfer_preserves_unit_wide_active_point_count
        """
        reset_clock()
        ctx = setup_route_with_active_points(2)
        unit_id = ctx["unit"]["id"]
        route_a = ctx["route"]
        p1, p2 = ctx["points"]
        car_b = create_carrier(unit_id)
        route_b = create_route(unit_id, car_b["id"])
        assert get_route(unit_id, route_a["id"])["active_delivery_point_count"] == 2
        assert get_route(unit_id, route_b["id"])["active_delivery_point_count"] == 0
        ctx = evaluation_consulted(ctx, outcome="CONCURRED", counts=COUNTS,
                                   kind="MINI_SURVEY")
        ctx = adjustment_in_state(
            ctx, state="APPROVED", proposed_minutes=545,
            transfers=[{"delivery_point_id": p2["id"], "to_route_id": route_b["id"]}],
            effective_date="2026-09-08")
        set_clock("2026-09-08T00:00:00Z")
        ra = get_route(unit_id, route_a["id"])
        rb = get_route(unit_id, route_b["id"])
        assert ra["active_delivery_point_count"] == 1
        assert rb["active_delivery_point_count"] == 1
        assert ra["active_delivery_point_count"] + rb["active_delivery_point_count"] == 2
        p1_after = get_point(unit_id, p1["id"])
        p2_after = get_point(unit_id, p2["id"])
        assert p1_after["active_route_id"] == route_a["id"]
        assert p2_after["active_route_id"] == route_b["id"]


class TestDeferredAction:

    def test_approved_adjustment_sits_until_effective_date(self, api):
        """PRD §3.7: "Until that cascade fires, an approved adjustment sits in
        `APPROVED` and the route remains under adjustment".

        Design: Corner/cross_cutting_layers/scheduled_adjustment_effective_date_deferred_action
        """
        reset_clock()
        ctx = _consulted_ctx(kind="MINI_SURVEY")
        ctx = adjustment_in_state(ctx, state="APPROVED", proposed_minutes=545,
                                  effective_date="2026-09-08")
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        set_clock("2026-09-05T00:00:00Z")
        route_mid = get_route(unit_id, route_id)
        assert route_mid["status"] == "UNDER_ADJUSTMENT"
        assert route_mid["current_evaluated_minutes"] == 480
        set_clock("2026-09-08T00:00:00Z")
        route_end = get_route(unit_id, route_id)
        assert route_end["status"] == "STANDARD"
        assert route_end["current_evaluated_minutes"] == 545
        adj = get_adjustment(unit_id, route_id, ctx["evaluation"]["id"],
                             ctx["adjustment"]["id"])
        assert adj["status"] == "EFFECTIVE"
        ev = get_evaluation(unit_id, route_id, ctx["evaluation"]["id"])
        assert ev["status"] == "CLOSED_ADOPTED"
