"""Penalty pricing: proposed vs final variants, compound factors, precision."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_engagement_payload,
    create_evidence_payload,
    create_milestone_payload,
    create_mitigation_plan_payload,
    create_registration_payload,
    create_violation,
    create_violation_payload,
    get_success_data,
    make_officer_headers,
    set_clock,
    validate_paginated,
    validate_success,
)

AUD = TEST_USERS["auditor_headers"]


def _register(functions, name):
    return get_success_data(api_client.create_registration(
        create_registration_payload(legal_name=name, registration_functions=functions),
        TEST_USERS["registration_coordinator_headers"],
    ))


def _engagement(entity_id, std, pstart, pend):
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(entity_id, standard_ids=[std],
                                  period_start=pstart, period_end=pend), AUD))


def _walk_mitigation_to_complete(entity_id, violation_id, plan_id):
    get_success_data(api_client.approve_plan(plan_id, AUD))
    m = get_success_data(api_client.create_milestone(
        plan_id, create_milestone_payload(title="Install new relay",
                                          due_date="2026-10-01T00:00:00Z"),
        make_officer_headers(entity_id)))
    get_success_data(api_client.complete_milestone(m["id"], make_officer_headers(entity_id)))
    get_success_data(api_client.complete_mitigation(violation_id, make_officer_headers(entity_id)))


class TestPenaltyProposedVsFinalStaleViolation:
    def _setup_stale_violation(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "GenCo One")
        eng = _engagement(e1["id"], "STD-GO-001", "2025-01-01T00:00:00Z",
                          "2025-06-30T00:00:00Z")
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        get_success_data(api_client.complete_engagement(eng["id"], AUD))
        v = get_success_data(api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-GO-001", source_type="AUDIT",
                violation_start="2025-02-01T00:00:00Z",
                violation_end="2025-03-01T00:00:00Z",
                violation_risk_factor="MODERATE", severity_level="SEVERE",
                source_engagement_id=eng["id"]), AUD))
        plan = get_success_data(api_client.create_mitigation_plan(
            v["id"], create_mitigation_plan_payload(v["version"], description="Fix relay settings"),
            make_officer_headers(e1["id"])))
        _walk_mitigation_to_complete(e1["id"], v["id"], plan["id"])
        return e1, v, plan

    def test_proposed_penalty_at_open_undiscounted(self):
        """PRD §3.4: "The base amount is read from a fixed table keyed by risk
        factor: one thousand for MINIMAL, five thousand for MODERATE, and
        twenty-five thousand for SERIOUS. A compound adjustment factor then
        starts at one and is multiplied step by step: doubled when the severity
        is SEVERE" — MODERATE/SEVERE audit with no gap aggravation (the source
        engagement's coverage_fraction is 0.0 < 0.8 applies; see paired test)
        prices proposed_penalty at OPEN.

        Design: Difficulty/dual_variant_calc/penalty_proposed_vs_final_stale_violation
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "GenCo One")
        eng = _engagement(e1["id"], "STD-GO-001", "2025-01-01T00:00:00Z",
                          "2025-06-30T00:00:00Z")
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        get_success_data(api_client.complete_engagement(eng["id"], AUD))
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-GO-001", source_type="AUDIT",
                violation_start="2025-02-01T00:00:00Z",
                violation_end="2025-03-01T00:00:00Z",
                violation_risk_factor="MODERATE", severity_level="SEVERE",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        # base 5000 * SEVERE 2.0 * gap aggravation 1.25 (coverage 0.0 < 0.8) = 12500.00
        assert data["proposed_penalty"] == pytest.approx(12500.00, abs=0.005)
        assert data["status"] == "OPEN"
        assert data["final_penalty"] is None

    def test_final_penalty_stale_discount_at_closure(self):
        """PRD §3.4: "The final_penalty stays null until the violation reaches
        CLOSED, at which point the same computation runs again with one
        difference: if the violation's violation_end lies more than 365 days
        before the closure time, the base amount is first discounted by ten
        percent — nine tenths of the tabulated base, rounded half-up to 2
        decimal places — before the factor steps apply."

        Design: Difficulty/dual_variant_calc/penalty_proposed_vs_final_stale_violation
        """
        e1, v, plan = self._setup_stale_violation()
        get_success_data(api_client.verify_plan(plan["id"], AUD))
        closed = validate_success(api_client.get_violation(v["id"], AUD))
        # stale: base 5000*0.9=4500.00, factor 2.0 * 1.25 (gap) = 2.5 => 11250.00
        assert closed["status"] == "CLOSED"
        assert closed["proposed_penalty"] == pytest.approx(12500.00, abs=0.005)
        assert closed["final_penalty"] == pytest.approx(11250.00, abs=0.005)


class TestCoverageFractionUnionVsNaiveSum:
    def _setup_overlapping_coverage(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "GenCo Two")
        eng = _engagement(e1["id"], "STD-GO-001", "2026-01-01T00:00:00Z",
                          "2026-06-30T00:00:00Z")
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        officer = make_officer_headers(e1["id"])
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-GO-001",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-03-01T00:00:00Z"), officer))
        a2 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-GO-001",
                                    coverage_start="2026-01-15T00:00:00Z",
                                    coverage_end="2026-03-15T00:00:00Z"), officer))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        get_success_data(api_client.accept_evidence(a2["id"], AUD))
        return eng

    def test_overlapping_windows_union_not_sum(self):
        """PRD §3.2: "the covered period is computed by collecting the coverage
        windows of that engagement's artifacts for that standard whose status is
        SUBMITTED or ACCEPTED, treating each window as a half-open interval that
        includes its start and excludes its end, merging overlapping windows
        into their union and merging adjacent windows whose gap is exactly zero,
        then intersecting each merged interval with the engagement's monitored
        period — clipping it at period_start and period_end — and summing the
        surviving lengths in integer seconds."

        Design: Difficulty/dual_variant_calc/coverage_fraction_union_vs_naive_sum
        """
        eng = self._setup_overlapping_coverage()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        # union [01-01, 03-15) = 73 days; period [01-01, 06-30) = 180 days
        assert data["coverage_fraction"] == pytest.approx(0.4056, abs=0.00005)

    def test_coverage_fraction_rounded_four_dp(self):
        """PRD §3.2: "The engagement's coverage_fraction is then the average
        across all in-scope standards of each standard's covered period divided
        by the full monitored period length, rounded half-up to 4 decimal
        places."

        Design: Difficulty/dual_variant_calc/coverage_fraction_union_vs_naive_sum
        """
        eng = self._setup_overlapping_coverage()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert round(data["coverage_fraction"], 4) == data["coverage_fraction"]
        assert 0.0 < data["coverage_fraction"] < 1.0


class TestPenaltyCompoundFactorNonlinearInteraction:
    def _setup_gap_engagement(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["TO"], "TransCo One")
        eng = _engagement(e1["id"], "STD-TO-001", "2026-01-01T00:00:00Z",
                          "2026-04-01T00:00:00Z")
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-TO-001",
                                    artifact_kind="MAINTENANCE_RECORD",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-01-28T00:00:00Z"),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        eng = get_success_data(api_client.complete_engagement(eng["id"], AUD))
        return e1, eng

    def test_compound_severity_and_gap_aggravation(self):
        """PRD §3.4: "multiplied by one and a half when the severity is HIGH ...
        and multiplied by 1.25 when the violation references a source engagement
        whose coverage_fraction is below 0.8 — an evidence-coverage gap
        aggravates the penalty because thin coverage undermines confidence in
        the monitored period."

        Design: Difficulty/combinatorial_formula/penalty_compound_factor_nonlinear_interaction
        """
        e1, eng = self._setup_gap_engagement()
        assert eng["coverage_fraction"] == pytest.approx(0.3, abs=0.00005)
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TO-001", source_type="AUDIT",
                violation_start="2026-02-01T00:00:00Z",
                violation_end="2026-02-10T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="HIGH",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        # 25000 * (1.5 * 1.25) = 46875.00
        assert data["proposed_penalty"] == pytest.approx(46875.00, abs=0.005)

    def test_severe_branch_not_applied_when_high(self):
        """PRD §3.4: "doubled when the severity is SEVERE, multiplied by one and
        a half when the severity is HIGH" — the two branches are exclusive; a
        HIGH severity must not also take the SEVERE branch (which would give
        25000*2*1.5*1.25 = 93750).

        Design: Difficulty/combinatorial_formula/penalty_compound_factor_nonlinear_interaction
        """
        e1, eng = self._setup_gap_engagement()
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TO-001", source_type="AUDIT",
                violation_start="2026-02-01T00:00:00Z",
                violation_end="2026-02-10T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="HIGH",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["proposed_penalty"] != pytest.approx(93750.00, abs=0.005)
        assert data["proposed_penalty"] == pytest.approx(46875.00, abs=0.005)


class TestPenaltyFactorPrecisionWithRecidivism:
    def _setup_three_priors(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["TOP"], "TopOp One")
        officer = make_officer_headers(e1["id"])
        for i, day in enumerate(("05", "15", "25")):
            # Route through the PRD-legal fixture so the SPOT_CHECK source
            # carries a COMPLETED source engagement (PRD §3.4 source integrity).
            v = create_violation(
                e1["id"], standard_id="STD-TOP-001", source_type="SPOT_CHECK",
                violation_start=f"2026-01-{day}T00:00:00Z",
                violation_end=f"2026-01-{day}T12:00:00Z",
                violation_risk_factor="MINIMAL", severity_level="LOWER")
            plan = get_success_data(api_client.create_mitigation_plan(
                v["id"], create_mitigation_plan_payload(v["version"], description=f"fix {i}"),
                officer))
            get_success_data(api_client.approve_plan(plan["id"], AUD))
            m = get_success_data(api_client.create_milestone(
                plan["id"], create_milestone_payload(title=f"m{i}",
                                                     due_date="2026-10-01T00:00:00Z"), officer))
            get_success_data(api_client.complete_milestone(m["id"], officer))
            get_success_data(api_client.complete_mitigation(v["id"], officer))
            get_success_data(api_client.verify_plan(plan["id"], AUD))
        # Full-coverage completed engagement (no gap aggravation).
        eng = _engagement(e1["id"], "STD-TOP-001", "2026-06-01T00:00:00Z",
                          "2026-06-30T00:00:00Z")
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-TOP-001",
                                    coverage_start="2026-06-01T00:00:00Z",
                                    coverage_end="2026-06-30T00:00:00Z"), officer))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        eng = get_success_data(api_client.complete_engagement(eng["id"], AUD))
        return e1, eng

    def test_recidivism_three_priors_factor_1_3(self):
        """PRD §3.4: "the server counts the entity's other violations that are
        CLOSED with a non-null final_penalty, caps that count at five, and
        multiplies the running factor by one plus one tenth times the capped
        count. The factor is then rounded half-even to 4 decimal places, and
        the amount is the base times the factor, rounded half-up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/penalty_factor_precision_half_even_then_half_up
        """
        e1, eng = self._setup_three_priors()
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TOP-001", source_type="AUDIT",
                violation_start="2026-06-10T00:00:00Z",
                violation_end="2026-06-12T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="LOWER",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        # factor = 1.0 * (1 + 0.1*3) = 1.3000; amount = 25000 * 1.3 = 32500.00
        assert data["proposed_penalty"] == pytest.approx(32500.00, abs=0.005)

    def test_full_coverage_excludes_gap_aggravation(self):
        """PRD §3.4: "multiplied by 1.25 when the violation references a source
        engagement whose coverage_fraction is below 0.8" — a full-coverage
        engagement (1.0000) must NOT aggravate; only recidivism applies.

        Design: Difficulty/combinatorial_formula/penalty_factor_precision_half_even_then_half_up
        """
        e1, eng = self._setup_three_priors()
        assert eng["coverage_fraction"] == pytest.approx(1.0, abs=0.00005)
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TOP-001", source_type="AUDIT",
                violation_start="2026-06-10T00:00:00Z",
                violation_end="2026-06-12T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="LOWER",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["proposed_penalty"] == pytest.approx(32500.00, abs=0.005)
        assert data["proposed_penalty"] != pytest.approx(32500.00 * 1.25, abs=0.01)


class TestCoverageGapThresholdExactEquality:
    def _setup_eighty_percent(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["TO"], "TransCo Edge")
        eng = _engagement(e1["id"], "STD-TO-001", "2026-01-01T00:00:00Z",
                          "2026-04-11T00:00:00Z")
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-TO-001",
                                    artifact_kind="MAINTENANCE_RECORD",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-03-22T00:00:00Z"),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        eng = get_success_data(api_client.complete_engagement(eng["id"], AUD))
        return e1, eng

    def test_exactly_0800_no_gap_aggravation(self):
        """PRD §3.4: "multiplied by 1.25 when the violation references a source
        engagement whose coverage_fraction is below 0.8" — at exactly 0.8000 the
        strict-below comparison does not fire, so SERIOUS/HIGH prices at
        25000 * 1.5 = 37500.00.

        Design: Difficulty/boundary_precision_check/coverage_gap_threshold_exact_equality
        """
        e1, eng = self._setup_eighty_percent()
        assert eng["coverage_fraction"] == pytest.approx(0.8, abs=0.00005)
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TO-001", source_type="AUDIT",
                violation_start="2026-02-01T00:00:00Z",
                violation_end="2026-02-02T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="HIGH",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["proposed_penalty"] == pytest.approx(37500.00, abs=0.005)

    def test_just_below_0800_applies_gap_aggravation(self):
        """PRD §3.4: "multiplied by 1.25 when the violation references a source
        engagement whose coverage_fraction is below 0.8" — a coverage fraction
        strictly below the threshold does aggravate.

        Design: Difficulty/boundary_precision_check/coverage_gap_threshold_exact_equality
        """
        e1, eng = self._setup_eighty_percent()
        # Add nothing more; 0.8 exactly is the setup. Instead build a 79/100 case.
        set_clock("2026-09-01T00:00:00Z")
        e2 = _register(["TO"], "TransCo Edge 79")
        eng2 = _engagement(e2["id"], "STD-TO-001", "2026-01-01T00:00:00Z",
                           "2026-04-11T00:00:00Z")
        get_success_data(api_client.start_engagement(eng2["id"], AUD))
        a = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng2["id"], standard_id="STD-TO-001",
                                    artifact_kind="MAINTENANCE_RECORD",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-03-21T00:00:00Z"),
            make_officer_headers(e2["id"])))
        get_success_data(api_client.accept_evidence(a["id"], AUD))
        eng2 = get_success_data(api_client.complete_engagement(eng2["id"], AUD))
        assert eng2["coverage_fraction"] == pytest.approx(0.79, abs=0.00005)
        resp = api_client.create_violation(
            create_violation_payload(
                e2["id"], standard_id="STD-TO-001", source_type="AUDIT",
                violation_start="2026-02-01T00:00:00Z",
                violation_end="2026-02-02T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="HIGH",
                source_engagement_id=eng2["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["proposed_penalty"] == pytest.approx(46875.00, abs=0.005)


class TestSelfLogSourceDiscountApplied:
    def test_self_log_escalation_pricing(self):
        """PRD §3.4: "multiplied by 0.4 when it came in through the self-logging
        program" — a MODERATE/LOWER violation created by self-log escalation
        prices at 5000 * 0.4 = 2000.00. PRD §3.6: "Any other risk/severity
        combination creates the violation in OPEN and increments the entity's
        open_violation_count by one."

        Design: Corner/calculations/self_log_source_discount_applied
        """
        set_clock("2026-09-01T00:00:00Z")
        e1 = get_success_data(api_client.create_registration(
            create_registration_payload(legal_name="SelfLogDisc Co",
                                        registration_functions=["GO"],
                                        enrollment_self_logging=True),
            TEST_USERS["registration_coordinator_headers"]))
        period = get_success_data(api_client.create_review_period(AUD))
        entry = get_success_data(api_client.create_self_log_entry(
            {"entity_id": e1["id"], "standard_id": "STD-GO-001",
             "exception_note": "x", "period_id": period["id"]},
            make_officer_headers(e1["id"])))
        get_success_data(api_client.start_review_period(period["id"], AUD))
        get_success_data(api_client.review_self_log_entry(
            entry["id"], {"outcome": "ESCALATED", "violation_risk_factor": "MODERATE",
                          "severity_level": "LOWER"}, AUD))
        resp = api_client.list_violations(AUD, params={"entity_id": e1["id"]})
        rows, meta = validate_paginated(resp)
        assert len(rows) == 1
        assert rows[0]["proposed_penalty"] == pytest.approx(2000.00, abs=0.005)
        assert rows[0]["status"] == "OPEN"
