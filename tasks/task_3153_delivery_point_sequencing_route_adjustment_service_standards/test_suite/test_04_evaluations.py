"""Route evaluation: modeled street time, consultation, re-collection loop."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    evaluation_consulted,
    evaluation_in_data_collection,
    get_evaluation,
    get_route,
    get_success_data,
    open_evaluation,
    reset_clock,
    setup_unit_with_route,
    submit_counts_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]
PM = TEST_USERS["postmaster_headers"]

COUNTS_3600 = dict(letters_count_total=3600, flats_count_total=900,
                   parcels_count_total=40, actual_street_minutes_total=2160,
                   office_minutes_total=1440)


class TestModeledStreetTime:

    def test_disputed_outcome_floors_street_time_at_modeled(self, api):
        """PRD §3.6: "when the outcome is `DISPUTED`, the adopted street time is
        the smaller of `actual_street_minutes_total` and
        `modeled_street_minutes_total` — a carrier-favorable floor".
        PRD §3.6: "The evaluated daily minutes are then the office minutes plus the
        adopted street minutes, divided by six, rounded half-up to a whole number."

        Design: Difficulty/dual_variant_calc/evaluation_street_time_actual_vs_disputed_floor
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="FULL_COUNT")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        get_success_data(api.submit_counts(unit_id, route_id, ev,
                                           submit_counts_payload(**COUNTS_3600), SUP))
        data = get_success_data(api.record_consultation(
            unit_id, route_id, ev, {"consultation_outcome": "DISPUTED"}, SUP))
        assert data["modeled_street_minutes_total"] == 358
        assert data["evaluated_daily_minutes"] == 300
        assert data["consultation_outcome"] == "DISPUTED"

    def test_concurred_outcome_adopts_actual_street_time(self, api):
        """PRD §3.6: "when the outcome is `CONCURRED` or `WAIVED`, the actual
        street time is adopted as-is."

        Design: Difficulty/dual_variant_calc/evaluation_street_time_actual_vs_disputed_floor
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="FULL_COUNT")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        get_success_data(api.submit_counts(unit_id, route_id, ev,
                                           submit_counts_payload(**COUNTS_3600), SUP))
        data = get_success_data(api.record_consultation(
            unit_id, route_id, ev, {"consultation_outcome": "CONCURRED"}, SUP))
        assert data["modeled_street_minutes_total"] == 358
        assert data["evaluated_daily_minutes"] == 600
        assert data["consultation_outcome"] == "CONCURRED"

    def test_tier_boundary_downturn_below_threshold(self, api):
        """PRD §3.6: "when letters plus flats reach at least 12000 the tier is 2;
        otherwise when they reach at least 6000 the tier is 1; otherwise the tier
        is 0 — larger volumes amortize fixed street cost."
        PRD §3.6: "The tier maps to a factor of 1.00, 0.97, or 0.94 respectively."

        Design: Difficulty/combinatorial_formula/modeled_street_time_tier_boundary_downturn
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="MINI_SURVEY")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        data = get_success_data(api.submit_counts(
            unit_id, route_id, ev,
            submit_counts_payload(letters_count_total=5000, flats_count_total=999,
                                  parcels_count_total=40,
                                  actual_street_minutes_total=1500,
                                  office_minutes_total=1200), SUP))
        # 5999 pieces → tier 0 (factor 1.00)
        assert data["modeled_street_minutes_total"] == 435

    def test_tier_boundary_downturn_at_threshold(self, api):
        """PRD §3.6: "otherwise when they reach at least 6000 the tier is 1" —
        exactly 6000 pieces flips the factor to 0.97 and the modeled time
        DECREASES despite strictly more mail.

        Design: Difficulty/combinatorial_formula/modeled_street_time_tier_boundary_downturn
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="MINI_SURVEY")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        data = get_success_data(api.submit_counts(
            unit_id, route_id, ev,
            submit_counts_payload(letters_count_total=5000, flats_count_total=1000,
                                  parcels_count_total=40,
                                  actual_street_minutes_total=1500,
                                  office_minutes_total=1200), SUP))
        # 6000 pieces → tier 1 (factor 0.97)
        assert data["modeled_street_minutes_total"] == 422

    def test_nested_rounding_order_pinned(self, api):
        """PRD §3.6: "The rounding order is fixed: each division rounds to two
        decimals first, then the weighted sum forms, then the final integer
        rounding; reordering into sum-then-round yields a different integer and is
        incorrect."

        Design: Difficulty/combinatorial_formula/modeled_street_time_nested_rounding_order_pinned
        """
        reset_clock()
        ctx = evaluation_in_data_collection(kind="SPECIAL_INSPECTION")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        data = get_success_data(api.submit_counts(
            unit_id, route_id, ev,
            submit_counts_payload(letters_count_total=3033, flats_count_total=901,
                                  parcels_count_total=40,
                                  actual_street_minutes_total=1000,
                                  office_minutes_total=800), SUP))
        # 168.50 + 112.63 casing; 56.20 pull-down; base 100.0; tier 0.
        # round_half_up((100.0 + 231.53*0.62 + 56.20), 0) == 331
        assert data["modeled_street_minutes_total"] == 331


class TestEvaluationLifecycle:

    def test_recollection_cycle_fires_once(self, api):
        """PRD §3.6: "The loop may fire at most once per evaluation: it requires
        the outcome to be `DISPUTED` and `recollection_used` still false, and
        firing it sets `recollection_used` true and zeroes the count inputs for
        re-entry. A second attempt, or an attempt without a disputed outcome, is
        rejected with `ERR_RECOLLECTION_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/evaluation_recollection_cycle_fires_once
        """
        reset_clock()
        ctx = evaluation_consulted(outcome="DISPUTED", counts=COUNTS_3600,
                                   kind="FULL_COUNT")
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        first = get_success_data(api.order_recollection(unit_id, route_id, ev, PM))
        assert first["status"] == "DATA_COLLECTION"
        assert first["recollection_used"] is True
        assert first["letters_count_total"] == 0
        assert first["office_minutes_total"] == 0
        # Re-collect, consult DISPUTED again — cycle closes.
        get_success_data(api.submit_counts(
            unit_id, route_id, ev,
            submit_counts_payload(letters_count_total=3700, flats_count_total=950,
                                  parcels_count_total=42,
                                  actual_street_minutes_total=2100,
                                  office_minutes_total=1400), SUP))
        again = get_success_data(api.record_consultation(
            unit_id, route_id, ev, {"consultation_outcome": "DISPUTED"}, SUP))
        assert again["status"] == "CONSULTED"
        # Second loop attempt is exhausted.
        resp = api.order_recollection(unit_id, route_id, ev, PM)
        validate_error(resp, ApiErrorId.ERR_RECOLLECTION_EXHAUSTED)

    def test_recollection_requires_disputed_outcome(self, api):
        """PRD §3.6: "it requires the outcome to be `DISPUTED` and
        `recollection_used` still false, and firing it sets `recollection_used`
        true and zeroes the count inputs for re-entry."
        PRD §3.6: "A second attempt, or an attempt without a disputed outcome, is
        rejected with `ERR_RECOLLECTION_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/evaluation_recollection_cycle_fires_once
        """
        reset_clock()
        ctx = evaluation_consulted(outcome="CONCURRED", counts=COUNTS_3600)
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        resp = api.order_recollection(unit_id, route_id, ev, PM)
        validate_error(resp, ApiErrorId.ERR_RECOLLECTION_EXHAUSTED)

    def test_close_rejected_bubbles_route_back_to_standard(self, api):
        """PRD §3.6: "the supervisor may close the evaluation `CONSULTED →
        CLOSED_REJECTED`, but only when no adjustment for this evaluation sits in
        `DRAFT`, `SUBMITTED`, or `APPROVED`; the route then bubbles back up to
        `STANDARD` with `under_evaluation_since` cleared".

        Design: Corner/state_machines/evaluation_rejected_bubbles_route_back_to_standard
        """
        reset_clock()
        ctx = evaluation_consulted(outcome="WAIVED", counts=COUNTS_3600)
        unit_id, route_id, ev = (ctx["unit"]["id"], ctx["route"]["id"],
                                 ctx["evaluation"]["id"])
        data = get_success_data(api.close_rejected(unit_id, route_id, ev, SUP))
        assert data["status"] == "CLOSED_REJECTED"
        route = get_route(unit_id, route_id)
        assert route["status"] == "STANDARD"
        assert route["under_evaluation_since"] is None
        assert route["current_evaluated_minutes"] == 480

    def test_second_evaluation_create_rejected_while_one_open(self, api):
        """PRD §3.6: "no other evaluation for the route may be open (one whose
        status is neither `CLOSED_ADOPTED` nor `CLOSED_REJECTED` blocks creation)"
        and "The route must be `STANDARD` — otherwise `ERR_CROSS_ENTITY_STATE`
        (HTTP 409)".

        Design: Corner/state_machines/second_evaluation_create_rejected_while_one_open
        """
        reset_clock()
        ctx = setup_unit_with_route()
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        open_evaluation(unit_id, route_id, kind="MINI_SURVEY")
        route = get_route(unit_id, route_id)
        resp = api.create_evaluation(
            unit_id, route_id,
            {"evaluation_kind": "FULL_COUNT", "count_week_start": "2026-09-26",
             "expected_route_version": route["version"]}, SUP)
        validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE,
                                        ApiErrorId.ERR_CROSS_ENTITY_STATE])
        rows = get_success_data(api.list_evaluations(unit_id, route_id, SUP,
                                                     params={"limit": 100}))
        assert len(rows) == 1

    def test_full_count_begin_count_requires_saturday_start(self, api):
        """PRD §3.6: "`count_week_start` naming the first day of the six-day mail
        count (count weeks always run Saturday through Friday, so the date must be
        a Saturday)".
        PRD §3.6: "violations are rejected with `ERR_TEMPORAL_WINDOW` (HTTP 422)".

        Design: Corner/validations/full_count_lead_time_and_saturday_start
        """
        reset_clock()
        ctx = setup_unit_with_route()
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        # 2026-09-15 is a Tuesday, 14 days out — lead time satisfied, weekday not.
        ev = open_evaluation(unit_id, route_id, kind="FULL_COUNT",
                             count_week_start="2026-09-15")
        resp = api.begin_count(unit_id, route_id, ev["id"], SUP)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)
        ev_after = get_evaluation(unit_id, route_id, ev["id"])
        assert ev_after["status"] == "INITIATED"
