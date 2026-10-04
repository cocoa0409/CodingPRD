"""Quality operations: dual quality-score variants, degradation cascades,
return-to-service gating, capacity boundaries, and dispatch resolution."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_line_conservation_invariant,
    create_approved_market,
    create_certified_auditorium,
    create_confirmed_slot,
    create_draft_statement,
    create_operating_auditorium,
    create_qa_alert_payload,
    create_signed_agreement,
    create_validated_report,
    get_statement_line,
    get_success_data,
    raise_critical_alert,
    resolve_alert_via_dispatch,
    set_clock,
    setup_confirmed_slot_scenario,
    validate_error,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
PCM = TEST_USERS["contract_manager_headers"]
FE = TEST_USERS["field_engineer_headers"]
RS = TEST_USERS["release_scheduler_headers"]
BOA = TEST_USERS["box_office_analyst_headers"]


class TestQualityScoreVariants:
    def _operating_auditorium(self, api):
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        return create_operating_auditorium(agreement["id"])

    def test_arithmetic_and_recency_variants_diverge(self, api):
        """PRD §3.8: "the two values differ for identical input sets whenever
        the alert population is not uniformly aged." and "The arithmetic
        variant, surfaced as `quality_score_arithmetic`, is the flat
        severity-weighted mean: the sum of severity weights divided by the
        count of alerts, using 1 in place of the count when there are no
        alerts. The recency variant, surfaced as `quality_score_recency`,
        weights each alert by linear decay: the alert's age in whole days is
        the floor of the elapsed seconds between `raised_at` and the logical
        clock divided by 86,400, clamped to the range 0 through 29; the
        recency weight is 1 minus the age in days divided by 30, so an alert
        raised today weighs 1.0 and an alert 29 days old weighs
        one-thirtieth."

        Design: Difficulty/dual_variant_calc/auditorium_quality_score_arithmetic_vs_recency_diverge
        """
        auditorium = self._operating_auditorium(api)
        # Alert 1 raised at logical 2026-09-01; alert 2 at 2026-09-11; read at
        # 2026-09-21. Ages: 20 days (weight 1 - 20/30 = 1/3) and 10 days
        # (weight 2/3). WARNING weight is 3 for both.
        get_success_data(api.create_qa_alert(
            create_qa_alert_payload(auditorium_id=auditorium["id"],
                                    alert_code="SOUND_DRIFT",
                                    severity="WARNING"), FE))
        set_clock("2026-09-11T00:00:00Z")
        get_success_data(api.create_qa_alert(
            create_qa_alert_payload(auditorium_id=auditorium["id"],
                                    alert_code="LAMP_DEGRADED",
                                    severity="WARNING"), FE))
        set_clock("2026-09-21T00:00:00Z")
        fetched = validate_success(api.get_auditorium(auditorium["id"], FE))
        assert fetched["quality_score_arithmetic"] == pytest.approx(3.0, abs=1e-4)
        # Recency: (3 * 1/3 + 3 * 2/3) / 2 = 1.5
        assert fetched["quality_score_recency"] == pytest.approx(1.5, abs=1e-3)
        assert fetched["quality_score_arithmetic"] != \
            fetched["quality_score_recency"]

    def test_uniformly_aged_alerts_make_variants_coincide(self, api):
        """PRD §3.8: "the two values differ for identical input sets whenever
        the alert population is not uniformly aged." — the contrapositive
        observable: a single alert (trivially uniform) yields identical
        variants. Severity weights are fixed — "`INFO` counts 1, `WARNING`
        counts 3, `CRITICAL` counts 10."

        Design: Difficulty/dual_variant_calc/auditorium_quality_score_arithmetic_vs_recency_diverge
        """
        auditorium = self._operating_auditorium(api)
        # Single CRITICAL alert raised at the current clock (age 0,
        # weight 1.0). The alert degrades the auditorium, which does not
        # affect the score inputs.
        get_success_data(api.create_qa_alert(
            create_qa_alert_payload(auditorium_id=auditorium["id"],
                                    alert_code="PROJECTOR_TEMP",
                                    severity="CRITICAL"), FE))
        fetched = validate_success(api.get_auditorium(auditorium["id"], FE))
        assert fetched["quality_score_arithmetic"] == pytest.approx(10.0, abs=1e-4)
        assert fetched["quality_score_recency"] == pytest.approx(10.0, abs=1e-4)


class TestCriticalAlertCascade:
    def test_critical_alert_degrades_and_suspends_and_releases_capacity(
        self, api
    ):
        """PRD §3.7: "If the severity is `CRITICAL` and the auditorium is
        `OPERATING`, the auditorium immediately degrades to `DEGRADED`, firing
        the full cascade of §2.8: every currently-running `CONFIRMED` slot on
        the auditorium — one whose `slot_start_date` is on or before the
        logical clock and whose `slot_end_date` is strictly after it — moves
        to `SUSPENDED`, each suspended slot's committed screen-seconds are
        subtracted from its window's `committed_premium_screen_seconds`, and
        every covering statement recomputes."

        Design: Difficulty/transitive_cascade/qa_critical_alert_cascades_auditorium_degraded_slots_suspended_window_capacity_and_statement
        """
        ctx = setup_confirmed_slot_scenario()
        create_draft_statement(ctx["agreement"]["id"], ctx["window"]["id"])
        set_clock("2026-09-08T00:00:00Z")  # slot is active now
        alert = raise_critical_alert(ctx["auditorium"]["id"])
        assert alert["status"] == "RAISED"
        auditorium = validate_success(
            api.get_auditorium(ctx["auditorium"]["id"], FE))
        assert auditorium["status"] == "DEGRADED"
        slot = validate_success(api.get_screen_slot(ctx["slot"]["id"], RS))
        assert slot["status"] == "SUSPENDED"
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], RS))
        assert window["committed_premium_screen_seconds"] == 0

    def test_critical_alert_recomputes_covering_statement(self, api):
        """PRD §2.8: "any RevenueShareStatement covering those slots
        recomputes its `statement_lines`, `provisional_total_cents`, and
        `final_total_cents`."

        Design: Difficulty/transitive_cascade/qa_critical_alert_cascades_auditorium_degraded_slots_suspended_window_capacity_and_statement
        """
        ctx = setup_confirmed_slot_scenario()
        create_validated_report(
            ctx["slot"]["id"], reported_date="2026-09-07T00:00:00Z",
            gross_receipts_cents=1000000, admissions=100)
        statement = create_draft_statement(ctx["agreement"]["id"],
                                           ctx["window"]["id"])
        before = validate_success(api.get_statement(statement["id"], BOA))
        line_before = get_statement_line(before, ctx["slot"]["id"])
        assert line_before["gross_reported_cents"] == 1000000
        set_clock("2026-09-08T00:00:00Z")
        raise_critical_alert(ctx["auditorium"]["id"])
        after = validate_success(api.get_statement(statement["id"], BOA))
        # The slot is now SUSPENDED: the final share input set is limited to
        # CONFIRMED/HELD_OVER/PULLED slots, so the recompute must not keep
        # the stale CONFIRMED-era line untouched — the statement reflects the
        # cascade.
        assert after["final_total_cents"] == 0, (
            "suspended slots leave the final share input set, so the "
            "recomputed final total drops to zero"
        )


class TestWindowCapacityConservation:
    def test_capacity_released_then_restored_exactly(self, api):
        """PRD §2.10: "Committed seconds are added on confirmation, subtracted
        on pulls and on degradation-driven suspensions, and restored when a
        suspended slot returns to `CONFIRMED`."
        PRD §3.7: "On success, every `SUSPENDED` slot on the auditorium
        returns to `CONFIRMED`, each restored slot's committed screen-seconds
        are added back to its window's committed total."

        Design: Difficulty/compensating_invariant/window_capacity_conserved_through_suspend_and_restore
        """
        ctx = setup_confirmed_slot_scenario()
        window_before = validate_success(
            api.get_release_window(ctx["window"]["id"], RS))
        assert window_before["committed_premium_screen_seconds"] == 84000
        set_clock("2026-09-08T00:00:00Z")
        alert = raise_critical_alert(ctx["auditorium"]["id"])
        window_mid = validate_success(
            api.get_release_window(ctx["window"]["id"], RS))
        assert window_mid["committed_premium_screen_seconds"] == 0
        resolve_alert_via_dispatch(alert["id"], ctx["auditorium"]["id"])
        get_success_data(
            api.return_auditorium_to_service(ctx["auditorium"]["id"], FE))
        window_after = validate_success(
            api.get_release_window(ctx["window"]["id"], RS))
        assert window_after["committed_premium_screen_seconds"] == 84000
        assert window_after["committed_premium_screen_seconds"] == \
            window_before["committed_premium_screen_seconds"]

    def test_suspended_slot_returns_to_confirmed_on_restore(self, api):
        """PRD §3.7: "On success, every `SUSPENDED` slot on the auditorium
        returns to `CONFIRMED`."

        Design: Difficulty/compensating_invariant/window_capacity_conserved_through_suspend_and_restore
        """
        ctx = setup_confirmed_slot_scenario()
        set_clock("2026-09-08T00:00:00Z")
        alert = raise_critical_alert(ctx["auditorium"]["id"])
        slot_mid = validate_success(api.get_screen_slot(ctx["slot"]["id"], RS))
        assert slot_mid["status"] == "SUSPENDED"
        resolve_alert_via_dispatch(alert["id"], ctx["auditorium"]["id"])
        get_success_data(
            api.return_auditorium_to_service(ctx["auditorium"]["id"], FE))
        slot_after = validate_success(
            api.get_screen_slot(ctx["slot"]["id"], RS))
        assert slot_after["status"] == "CONFIRMED"


class TestMarketCapacityBoundary:
    def test_open_at_exact_cap_rejected(self, api):
        """PRD §2.10: "Opening an auditorium is allowed only while the cap
        strictly exceeds the current count of `OPERATING` auditoriums in the
        market; a market at its cap rejects further openings with
        `ERR_MARKET_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/market_capacity_at_exact_cap_admits_next_open_fails
        """
        set_clock()
        market = create_approved_market(screen_capacity_cap=1)
        agreement = create_signed_agreement(market["id"])
        create_operating_auditorium(agreement["id"], auditorium_label="S1")
        # Second auditorium driven to CERTIFIED (stopped before open).
        aud_2 = create_certified_auditorium(agreement["id"],
                                            auditorium_label="S2")
        resp = api.open_auditorium(aud_2["id"], PCM)
        validate_error(resp, ApiErrorId.ERR_MARKET_CAPACITY_EXCEEDED,
                       expected_status=409)
        market_after = validate_success(api.get_market(market["id"], PCM))
        assert market_after["opened_screen_count"] == 1

    def test_open_below_cap_succeeds_and_increments(self, api):
        """PRD §2.10: "The `opened_screen_count` increments on each opening
        and decrements on each decommissioning of an `OPERATING` auditorium."

        Design: Difficulty/boundary_precision_check/market_capacity_at_exact_cap_admits_next_open_fails
        """
        set_clock()
        market = create_approved_market(screen_capacity_cap=2)
        agreement = create_signed_agreement(market["id"])
        create_operating_auditorium(agreement["id"], auditorium_label="S1")
        create_operating_auditorium(agreement["id"], auditorium_label="S2")
        market_after = validate_success(api.get_market(market["id"], PCM))
        assert market_after["opened_screen_count"] == 2


class TestReturnToServiceGating:
    def test_unresolved_critical_alert_blocks_return(self, api):
        """PRD §3.7: "Returning a degraded auditorium to service — `DEGRADED →
        OPERATING`, by a `FieldEngineer` — is gated on safety: every
        `CRITICAL` alert on the auditorium must be `RESOLVED`; any unresolved
        critical alert rejects the transition with
        `ERR_UNRESOLVED_CRITICAL_ALERTS`."
        PRD §2.9: "(8) safety and quality gates
        (`ERR_UNRESOLVED_CRITICAL_ALERTS`, `ERR_FILMMAKER_SIGNOFF_MISSING`,
        `ERR_CANNOT_DEFER_CRITICAL`); (9) capacity and fiscal limits."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_return_to_service
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        raise_critical_alert(auditorium["id"])  # auditorium now DEGRADED
        resp = api.return_auditorium_to_service(auditorium["id"], FE)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_CRITICAL_ALERTS,
                       expected_status=409)
        fetched = validate_success(api.get_auditorium(auditorium["id"], FE))
        assert fetched["status"] == "DEGRADED"

    def test_return_succeeds_once_critical_alerts_resolved(self, api):
        """PRD §3.7: "every `CRITICAL` alert on the auditorium must be
        `RESOLVED`" before return-to-service succeeds, and "On success, every
        `SUSPENDED` slot on the auditorium returns to `CONFIRMED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_fiscal_on_return_to_service
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        alert = raise_critical_alert(auditorium["id"])
        resolve_alert_via_dispatch(alert["id"], auditorium["id"])
        resp = api.return_auditorium_to_service(auditorium["id"], FE)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "OPERATING"


class TestDispatchResolutionCascade:
    def test_dispatch_completion_resolves_alert_and_restores_auditorium(
        self, api
    ):
        """PRD §3.7: "On completion, the parent alert resolves if no other
        non-terminal dispatches remain against it." and "when every dispatch
        for the alert is `COMPLETE`, the alert auto-advances to the terminal
        `RESOLVED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_alert_resolution_restores_auditorium_via_dispatch
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        alert = raise_critical_alert(auditorium["id"])
        get_success_data(api.acknowledge_alert(alert["id"], FE))
        dispatch = get_success_data(api.create_tech_dispatch(
            {"qa_alert_id": alert["id"], "auditorium_id": auditorium["id"],
             "scheduled_visit_date": "2026-09-02T00:00:00Z",
             "tech_specialty": "PROJECTION"}, FE))
        get_success_data(api.mark_dispatch_en_route(dispatch["id"], FE))
        get_success_data(api.mark_dispatch_on_site(dispatch["id"], FE))
        resp = api.complete_dispatch(
            dispatch["id"],
            {"resolution_notes": "replaced lamp and recalibrated"}, FE)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMPLETE"
        alert_after = validate_success(api.get_qa_alert(alert["id"], FE))
        assert alert_after["status"] == "RESOLVED"
        restore = api.return_auditorium_to_service(auditorium["id"], FE)
        assert validate_success(restore, expected_status=200)["status"] == \
            "OPERATING"


class TestDeferCritical:
    def test_defer_critical_rejected(self, api):
        """PRD §3.7: "deferral is forbidden for `CRITICAL` alerts from either
        `RAISED` or `ACKNOWLEDGED`, rejected with
        `ERR_CANNOT_DEFER_CRITICAL`."

        Design: Corner/errors/defer_critical_alert_returns_cannot_defer_critical
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        alert = raise_critical_alert(auditorium["id"])
        resp = api.defer_alert(alert["id"], FE)
        validate_error(resp, ApiErrorId.ERR_CANNOT_DEFER_CRITICAL,
                       expected_status=409)

    def test_defer_non_critical_allowed(self, api):
        """PRD §3.7: "non-critical alerts may be deferred from either state
        into the terminal `DEFERRED` state."

        Design: Corner/errors/defer_critical_alert_returns_cannot_defer_critical
        """
        set_clock()
        market = create_approved_market()
        agreement = create_signed_agreement(market["id"])
        auditorium = create_operating_auditorium(agreement["id"])
        alert = get_success_data(api.create_qa_alert(
            create_qa_alert_payload(auditorium_id=auditorium["id"],
                                    alert_code="SOUND_DRIFT",
                                    severity="WARNING"), FE))
        resp = api.defer_alert(alert["id"], FE)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "DEFERRED"
