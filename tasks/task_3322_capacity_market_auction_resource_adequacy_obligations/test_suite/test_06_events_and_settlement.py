"""Emergency events, performance assessments, tiered non-performance charges,
redistribution, and settlement conservation (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    begin_assessment,
    declare_event,
    finalize_assessments,
    get_success_data,
    list_event_assessments,
    list_event_entries,
    record_actual,
    setup_cleared_year_single_resource,
    setup_cleared_year_two_resources,
    setup_forecast_locked_year,
    validate_error,
)

ADMIN = TEST_USERS["market_admin_headers"]
OPS = TEST_USERS["settlement_ops_headers"]


class TestBeginAssessmentGating:
    def test_begin_assessment_requires_cleared_year(self, api):
        """PRD §3.6: "Beginning assessment moves the event `DECLARED` →
        `ASSESSING` and requires the delivery year to be `CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/emergency_assessment_requires_delivery_year_cleared
        """
        dy, zone, forecast = setup_forecast_locked_year()
        ev = declare_event(dy["id"])
        resp = api.begin_assessment(ev["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        ev_after = get_success_data(api.get_emergency_event(ev["id"], ADMIN))
        assert ev_after["status"] == "DECLARED"

    def test_begin_assessment_after_clearing_creates_draft_assessments(self, api):
        """PRD §3.6: "On entry to `ASSESSING`, the system creates a `DRAFT`
        **PerformanceAssessment** for every commitment of the delivery year in
        `ACTIVE` or `SETTLED` status whose resource type matches the event
        scope."

        Design: Difficulty/cross_entity_state_dependency/emergency_assessment_requires_delivery_year_cleared
        """
        ctx = setup_cleared_year_single_resource()
        ev = declare_event(ctx["dy"]["id"])
        ev = begin_assessment(ev["id"])
        assert ev["status"] == "ASSESSING"
        assessments = list_event_assessments(ev["id"])
        assert len(assessments) == 1
        assert assessments[0]["status"] == "DRAFT"
        assert assessments[0]["commitment_id"] == ctx["commitment"]["id"]


class TestEventOverlapAdjacency:
    def _setup_event_assessing(self, api):
        ctx = setup_cleared_year_single_resource()
        ev1 = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                            end="2029-06-10T15:00:00Z")
        ev1 = begin_assessment(ev1["id"])
        return ctx, ev1

    def test_adjacent_event_may_enter_assessing(self, api):
        """PRD §3.6: "no other event of the same delivery year in `DECLARED`,
        `ASSESSING`, or `ASSESSED` may have a half-open interval that overlaps
        this event's interval — adjacent events, where one ends exactly when
        the other begins, are allowed"

        Design: Difficulty/resource_temporal_overlap/emergency_pai_half_open_adjacency
        """
        ctx, ev1 = self._setup_event_assessing(api)
        ev2 = declare_event(ctx["dy"]["id"], start="2029-06-10T15:00:00Z",
                            end="2029-06-10T17:00:00Z")
        ev2 = get_success_data(api.begin_assessment(ev2["id"], ADMIN))
        assert ev2["status"] == "ASSESSING"

    def test_overlapping_event_rejected_at_begin_assessment(self, api):
        """PRD §3.6: "a violation is rejected with `ERR_EVENT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/emergency_pai_half_open_adjacency
        """
        ctx, ev1 = self._setup_event_assessing(api)
        ev3 = declare_event(ctx["dy"]["id"], start="2029-06-10T14:00:00Z",
                            end="2029-06-10T16:00:00Z")
        resp = api.begin_assessment(ev3["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_EVENT_OVERLAP, expected_status=409)
        ev3_after = get_success_data(api.get_emergency_event(ev3["id"], ADMIN))
        assert ev3_after["status"] == "DECLARED"


class TestEventTimeRange:
    def test_event_outside_planning_period_rejected(self, api):
        """PRD §3.6: "Both endpoints of the window must fall within the
        delivery year's planning period; violations are rejected with
        `ERR_INVALID_TIME_RANGE`."

        Design: Corner/validations/err_invalid_time_range_event_outside_delivery_year
        """
        ctx = setup_cleared_year_single_resource()
        resp = api.create_emergency_event(
            {
                "delivery_year_id": ctx["dy"]["id"],
                "event_start": "2029-05-31T13:00:00Z",
                "event_end": "2029-05-31T15:00:00Z",
                "event_type": "EMERGENCY_ACTION",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE, expected_status=422)


class TestChargeTierBoundary:
    def test_ratio_exactly_point_six_takes_tier_one(self, api):
        """PRD §3.6: "When the unrounded ratio of actual to expected is at
        least 0.60, the non-performance charge is the shortfall times the base
        rate times H times 1.0" and "the daily base rate is the commitment's
        clearing price divided by the 24 hours of a day."

        Design: Difficulty/boundary_precision_check/charge_tier_boundary_ratio_exactly_point_six
        """
        ctx = setup_cleared_year_single_resource(offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        a1 = list_event_assessments(ev["id"])[0]
        record_actual(a1["id"], 10.0, 6.0)
        finalize_assessments(ev["id"])
        a1_after = get_success_data(api.get_assessment(a1["id"], ADMIN))
        assert a1_after["performance_ratio"] == pytest.approx(0.6, abs=1e-9)
        # shortfall 4 * (100/24) * 4h * 1.0 = 66.6667 -> -66.67
        assert a1_after["charge_or_credit_dollars"] == pytest.approx(-66.67, abs=1e-9)

    def test_ratio_point_five_nine_falls_into_tier_two(self, api):
        """PRD §3.6: "when the ratio is at least 0.30 but below 0.60 the
        multiplier is 1.5; below 0.30 it is 2.0 — with the tier chosen on the
        unrounded quotient."

        Design: Difficulty/boundary_precision_check/charge_tier_boundary_ratio_exactly_point_six
        """
        ctx = setup_cleared_year_single_resource(offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        a1 = list_event_assessments(ev["id"])[0]
        record_actual(a1["id"], 10.0, 5.9)
        finalize_assessments(ev["id"])
        a1_after = get_success_data(api.get_assessment(a1["id"], ADMIN))
        assert a1_after["performance_ratio"] == pytest.approx(0.59, abs=1e-9)
        # shortfall 4.1 * (100/24) * 4h * 1.5 = 102.50 -> -102.50
        assert a1_after["charge_or_credit_dollars"] == pytest.approx(-102.5, abs=1e-9)


class TestNestedRoundingOrder:
    def test_final_amount_rounded_only_at_the_end(self, api):
        """PRD §3.6: "The settlement amount is the bonus minus the charge,
        rounded to 2 decimal places round half up — negative means the owner
        owes the pool, positive means a credit" and "When the unrounded ratio
        of actual to expected is at least 0.60, the non-performance charge is
        the shortfall times the base rate times H times 1.0".

        Design: Difficulty/combinatorial_formula/nonperformance_charge_nested_rounding_order
        """
        ctx = setup_cleared_year_single_resource(offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        a1 = list_event_assessments(ev["id"])[0]
        record_actual(a1["id"], 10.0, 8.0)
        finalize_assessments(ev["id"])
        a1_after = get_success_data(api.get_assessment(a1["id"], ADMIN))
        assert a1_after["performance_ratio"] == pytest.approx(0.8, abs=1e-9)
        assert a1_after["charge_or_credit_dollars"] == pytest.approx(-33.33, abs=1e-9)

    def test_finalization_posts_charge_entry(self, api):
        """PRD §3.6: "Finalization posts a `CHARGE` or `BONUS`
        **SettlementEntry** for each assessment"

        Design: Difficulty/combinatorial_formula/nonperformance_charge_nested_rounding_order
        """
        ctx = setup_cleared_year_single_resource(offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        a1 = list_event_assessments(ev["id"])[0]
        record_actual(a1["id"], 10.0, 8.0)
        finalize_assessments(ev["id"])
        entries = list_event_entries(ev["id"])
        charges = [e for e in entries if e["commitment_id"] == ctx["commitment"]["id"]]
        assert len(charges) == 1
        assert charges[0]["entry_type"] == "CHARGE"
        assert charges[0]["amount_dollars"] == pytest.approx(-33.33, abs=1e-9)


class TestTierLadder:
    def test_tier_two_and_tier_three_charges_on_one_event(self, api):
        """PRD §3.6: "when the ratio is at least 0.30 but below 0.60 the
        multiplier is 1.5; below 0.30 it is 2.0 — with the tier chosen on the
        unrounded quotient."

        Design: Corner/calculations/nonperformance_tier2_and_tier3_multipliers
        """
        ctx = setup_cleared_year_two_resources(offer_mw=10.0, offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        assessments = list_event_assessments(ev["id"])
        assert len(assessments) == 2
        a1, a2 = assessments[0], assessments[1]
        record_actual(a1["id"], 10.0, 4.0)
        record_actual(a2["id"], 10.0, 2.0)
        finalize_assessments(ev["id"])
        a1_after = get_success_data(api.get_assessment(a1["id"], ADMIN))
        a2_after = get_success_data(api.get_assessment(a2["id"], ADMIN))
        # r=0.4 -> tier 1.5x: 6 * (100/24) * 4 * 1.5 = 150.00
        assert a1_after["charge_or_credit_dollars"] == pytest.approx(-150.0, abs=1e-9)
        # r=0.2 -> tier 2.0x: 8 * (100/24) * 4 * 2.0 = 266.6667 -> -266.67
        assert a2_after["charge_or_credit_dollars"] == pytest.approx(-266.67, abs=1e-9)


def _setup_assessed_event_two_commitments(api):
    """Two commitments (10 MW @ 70.00 each offer); one event H=2 finalized with
    a full performer (10/10) and a non-performer (10/2)."""
    ctx = setup_cleared_year_two_resources(offer_mw=10.0, offer_price=70.0)
    ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                       end="2029-06-10T15:00:00Z")
    ev = begin_assessment(ev["id"])
    assessments = list_event_assessments(ev["id"])
    assert len(assessments) == 2
    by_commitment = {a["commitment_id"]: a for a in assessments}
    a_full = by_commitment[ctx["c1"]["id"]]
    a_short = by_commitment[ctx["c2"]["id"]]
    record_actual(a_full["id"], 10.0, 10.0)
    record_actual(a_short["id"], 10.0, 2.0)
    finalize_assessments(ev["id"])
    return ctx, ev, a_full, a_short


class TestThreeHopCascade:
    def test_finalize_posts_charge_and_recomputes_scores(self, api):
        """PRD §3.6: "Finalization posts a `CHARGE` or `BONUS`
        **SettlementEntry** for each assessment, stamps each assessment's
        `assessed_mwh` as its `expected_mw` times H, and recomputes each
        affected commitment's `cumulative_performance_score` as the weighted
        average of `performance_ratio` across all of that commitment's
        `FINALIZED` assessments, weighted by `assessed_mwh` and rounded to 4
        decimal places round half up."

        Design: Difficulty/transitive_cascade/finalize_assessments_three_hop_charge_to_redistribution
        """
        ctx, ev, a_full, a_short = _setup_assessed_event_two_commitments(api)
        a_short_after = get_success_data(api.get_assessment(a_short["id"], ADMIN))
        # r = 0.2 < 0.30 -> 2.0x: 8 * (70/24) * 2 * 2.0 = 93.3333 -> -93.33
        assert a_short_after["charge_or_credit_dollars"] == pytest.approx(-93.33, abs=1e-9)
        entries = list_event_entries(ev["id"])
        charge = [e for e in entries
                  if e["commitment_id"] == ctx["c2"]["id"] and e["entry_type"] == "CHARGE"]
        assert len(charge) == 1
        assert charge[0]["amount_dollars"] == pytest.approx(-93.33, abs=1e-9)

        c1 = get_success_data(api.get_commitment(ctx["c1"]["id"], ADMIN))
        c2 = get_success_data(api.get_commitment(ctx["c2"]["id"], ADMIN))
        assert c1["cumulative_performance_score"] == pytest.approx(1.0, abs=1e-9)
        assert c2["cumulative_performance_score"] == pytest.approx(0.2, abs=1e-9)

    def test_settle_posts_redistribution_and_closes_event(self, api):
        """PRD §3.8: "the pool is distributed pro-rata among the full
        performers — the `FINALIZED` assessments whose `performance_ratio` is
        at least 1.0000 — weighted by `assessed_mwh`" and "One
        `REDISTRIBUTION` **SettlementEntry** is posted per performer
        commitment, and each `ASSESSED` event then moves to `SETTLED`."

        Design: Difficulty/transitive_cascade/finalize_assessments_three_hop_charge_to_redistribution
        """
        ctx, ev, a_full, a_short = _setup_assessed_event_two_commitments(api)
        get_success_data(api.settle_delivery_year(ctx["dy"]["id"], OPS))
        entries = list_event_entries(ev["id"])
        redist = [e for e in entries
                  if e["entry_type"] == "REDISTRIBUTION"
                  and e["commitment_id"] == ctx["c1"]["id"]]
        assert len(redist) == 1
        assert redist[0]["amount_dollars"] == pytest.approx(93.33, abs=1e-9)
        ev_after = get_success_data(api.get_emergency_event(ev["id"], ADMIN))
        assert ev_after["status"] == "SETTLED"
        c1 = get_success_data(api.get_commitment(ctx["c1"]["id"], ADMIN))
        assert c1["status"] == "SETTLED"


class TestSettlementConservation:
    def test_event_entries_sum_to_zero_after_settle(self, api):
        """PRD §3.8: "Shares are rounded to 2 decimal places round half up in
        ascending order of assessment `created_at`, and the last performer in
        that order receives the pool minus the sum of all prior rounded shares,
        so the rounding remainder is absorbed rather than lost or double-paid."

        Design: Difficulty/compensating_invariant/settle_conserves_settlement_dollars_across_entries
        """
        ctx, ev, a_full, a_short = _setup_assessed_event_two_commitments(api)
        get_success_data(api.settle_delivery_year(ctx["dy"]["id"], OPS))
        entries = list_event_entries(ev["id"])
        total = sum(e["amount_dollars"] for e in entries)
        assert total == pytest.approx(0.0, abs=1e-9), \
            "Charges collected must equal redistribution paid out"
        amounts = sorted(e["amount_dollars"] for e in entries)
        assert amounts[0] == pytest.approx(-93.33, abs=1e-9)
        assert amounts[-1] == pytest.approx(93.33, abs=1e-9)

    def test_settle_advances_delivery_year(self, api):
        """PRD §3.8: "a `SettlementOps` operator settles the year, moving it
        `CLEARED` → `SETTLED`."

        Design: Difficulty/compensating_invariant/settle_conserves_settlement_dollars_across_entries
        """
        ctx, ev, a_full, a_short = _setup_assessed_event_two_commitments(api)
        settled = get_success_data(api.settle_delivery_year(ctx["dy"]["id"], OPS))
        assert settled["status"] == "SETTLED"


class TestDefaultThreshold:
    def test_default_requires_two_finalized_assessments(self, api):
        """PRD §3.5: "only when its `cumulative_performance_score` is below
        0.40 and at least two `FINALIZED` performance assessments exist for it;
        otherwise the attempt fails with `ERR_DEFAULT_THRESHOLD_NOT_MET`."

        Design: Corner/validations/err_default_threshold_not_met
        """
        ctx = setup_cleared_year_single_resource(offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        a1 = list_event_assessments(ev["id"])[0]
        record_actual(a1["id"], 10.0, 2.0)
        finalize_assessments(ev["id"])
        # Score after one assessment is 0.2 < 0.40, but only one FINALIZED
        # assessment exists.
        resp = api.default_commitment(ctx["commitment"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_DEFAULT_THRESHOLD_NOT_MET,
                       expected_status=422)
        c_after = get_success_data(api.get_commitment(ctx["commitment"]["id"], ADMIN))
        assert c_after["status"] == "ACTIVE"


class TestSettlementEntryImmutability:
    def test_ledger_entries_carry_no_version_or_updated_at(self, api):
        """PRD §2.4: "Two ledger-style resources are the exception: a
        PerformanceAssessment and a SettlementEntry carry only `id` and
        `created_at` — both `updated_at` and `version` are absent from them,
        because they are append-only records."

        Design: Corner/entities/settlement_entry_immutable_no_update_endpoint
        """
        ctx = setup_cleared_year_single_resource(offer_price=100.0)
        ev = declare_event(ctx["dy"]["id"], start="2029-06-10T13:00:00Z",
                           end="2029-06-10T17:00:00Z")
        ev = begin_assessment(ev["id"])
        a1 = list_event_assessments(ev["id"])[0]
        record_actual(a1["id"], 10.0, 8.0)
        finalize_assessments(ev["id"])
        entries = get_success_data(
            api.list_settlement_entries(
                ADMIN, params={"commitment_id": ctx["commitment"]["id"]},
            )
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == "CHARGE"
        assert entry["amount_dollars"] == pytest.approx(-33.33, abs=1e-9)
        assert "version" not in entry
        assert "updated_at" not in entry
