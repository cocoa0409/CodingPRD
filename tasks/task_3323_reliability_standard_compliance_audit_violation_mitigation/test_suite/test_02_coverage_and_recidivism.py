"""Coverage computation: interval union, multi-standard averaging, reject
recompute, engagement cancel cascade, recidivism cap."""
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    create_appeal_payload,
    create_engagement_payload,
    create_evidence_payload,
    create_registration_payload,
    create_violation,
    create_violation_payload,
    get_success_data,
    make_officer_headers,
    set_clock,
    validate_success,
)

AUD = TEST_USERS["auditor_headers"]
RER = TEST_USERS["regional_reviewer_headers"]
RC = TEST_USERS["registration_coordinator_headers"]


def _register(functions, name, enrollment=None):
    payload = create_registration_payload(legal_name=name, registration_functions=functions)
    if enrollment is not None:
        payload["enrollment_self_logging"] = enrollment
    return get_success_data(api_client.create_registration(payload, RC))


class TestEvidenceGapZeroAdjacentIntervalsMerge:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "GenCo Adj")
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"], standard_ids=["STD-GO-001"],
                                      period_start="2026-01-01T00:00:00Z",
                                      period_end="2026-03-31T00:00:00Z"), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        officer = make_officer_headers(e1["id"])
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-02-01T00:00:00Z"), officer))
        a2 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], coverage_start="2026-02-01T00:00:00Z",
                                    coverage_end="2026-03-01T00:00:00Z"), officer))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        get_success_data(api_client.accept_evidence(a2["id"], AUD))
        return eng

    def test_adjacent_windows_merge_continuous(self):
        """PRD §3.2: "treating each window as a half-open interval that includes
        its start and excludes its end, merging overlapping windows into their
        union and merging adjacent windows whose gap is exactly zero" —
        [01-01,02-01) and [02-01,03-01) cover 59 of 89 days.

        Design: Difficulty/resource_temporal_overlap/evidence_gap_zero_adjacent_intervals_merge
        """
        eng = self._setup()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert data["coverage_fraction"] == pytest.approx(0.6629, abs=0.00005)

    def test_adjacent_merge_does_not_double_count_boundary(self):
        """PRD §3.2: "treating each window as a half-open interval that includes
        its start and excludes its end" — a closed-interval reading would add a
        boundary day and diverge from 59/89.

        Design: Difficulty/resource_temporal_overlap/evidence_gap_zero_adjacent_intervals_merge
        """
        eng = self._setup()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert data["coverage_fraction"] < 0.68
        assert data["coverage_fraction"] == pytest.approx(59 / 89, abs=0.00005)


class TestCoverageRejectReducesFraction:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "Cov Co")
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"], standard_ids=["STD-GO-001"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"]), make_officer_headers(e1["id"])))
        return eng, a1

    def test_submitted_artifact_counts_full_coverage(self):
        """PRD §3.2: "the covered period is computed by collecting the coverage
        windows of that engagement's artifacts for that standard whose status is
        SUBMITTED or ACCEPTED" — a SUBMITTED artifact covering the whole period
        yields coverage_fraction 1.0000.

        Design: Corner/calculations/coverage_reject_reduces_fraction
        """
        eng, a1 = self._setup()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert data["coverage_fraction"] == pytest.approx(1.0, abs=0.00005)

    def test_rejecting_only_artifact_drops_coverage_to_zero(self):
        """PRD §3.2: "Every accept or reject recomputes the engagement's
        coverage_fraction" — after rejecting the only artifact, no
        SUBMITTED/ACCEPTED window remains, so coverage falls to 0.0000.

        Design: Corner/calculations/coverage_reject_reduces_fraction
        """
        eng, a1 = self._setup()
        get_success_data(api_client.reject_evidence(a1["id"], AUD))
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert data["coverage_fraction"] == pytest.approx(0.0, abs=0.00005)


class TestCoverageMultiStandardAverage:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "MultiStd Co")
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"],
                                      standard_ids=["STD-GO-001", "STD-GO-002"],
                                      period_start="2026-01-01T00:00:00Z",
                                      period_end="2026-04-11T00:00:00Z"), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-GO-001",
                                    coverage_start="2026-01-01T00:00:00Z",
                                    coverage_end="2026-02-20T00:00:00Z"),
            make_officer_headers(e1["id"])))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        return eng

    def test_average_across_standards(self):
        """PRD §3.2: "The engagement's coverage_fraction is then the average
        across all in-scope standards of each standard's covered period divided
        by the full monitored period length" — one standard half covered and one
        uncovered averages to 0.2500.

        Design: Corner/calculations/coverage_multi_standard_average
        """
        eng = self._setup()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert data["coverage_fraction"] == pytest.approx(0.25, abs=0.00005)

    def test_uncovered_standard_contributes_zero_not_omitted(self):
        """PRD §3.2: "The engagement's coverage_fraction is then the average
        across all in-scope standards" — the uncovered standard contributes 0 to
        the average rather than being dropped from the denominator (which would
        give 0.5).

        Design: Corner/calculations/coverage_multi_standard_average
        """
        eng = self._setup()
        data = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert data["coverage_fraction"] == pytest.approx(0.25, abs=0.00005)
        assert data["coverage_fraction"] != pytest.approx(0.5, abs=0.0001)


class TestEngagementCancelCascadeRejectsEvidenceAndRecomputes:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["GO"], "GenCo Cancel")
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"], engagement_type="SPOT_CHECK",
                                      standard_ids=["STD-GO-001"]), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"]), make_officer_headers(e1["id"])))
        return e1, eng, a1

    def test_cancel_rejects_submitted_evidence(self):
        """PRD §3.2: "cancelling cascades to the evidence already on file,
        moving every still-SUBMITTED artifact of that engagement to REJECTED and
        recomputing the coverage fraction accordingly."

        Design: Difficulty/transitive_cascade/engagement_cancel_cascade_rejects_evidence_and_recomputes
        """
        e1, eng, a1 = self._setup()
        get_success_data(api_client.cancel_engagement(eng["id"], AUD))
        art = validate_success(api_client.get_evidence(a1["id"], AUD))
        assert art["status"] == "REJECTED"

    def test_cancel_recomputes_coverage_to_zero(self):
        """PRD §3.2: "moving every still-SUBMITTED artifact of that engagement
        to REJECTED and recomputing the coverage fraction accordingly" — with
        the only artifact cascade-rejected, coverage recomputes to 0.0000.

        Design: Difficulty/transitive_cascade/engagement_cancel_cascade_rejects_evidence_and_recomputes
        """
        e1, eng, a1 = self._setup()
        before = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert before["coverage_fraction"] == pytest.approx(1.0, abs=0.00005)
        get_success_data(api_client.cancel_engagement(eng["id"], AUD))
        after = validate_success(api_client.get_engagement(eng["id"], AUD))
        assert after["coverage_fraction"] == pytest.approx(0.0, abs=0.00005)
        assert after["status"] == "CANCELLED"


class TestRecidivismCapAtFivePriors:
    def _setup(self):
        set_clock("2026-09-01T00:00:00Z")
        e1 = _register(["TOP"], "Recid Co")
        officer = make_officer_headers(e1["id"])
        # Six prior violations closed via granted appeals (fast path).
        for i in range(6):
            # Route through the PRD-legal fixture so the SPOT_CHECK source
            # carries a COMPLETED engagement reference (PRD §3.4).
            v = create_violation(
                e1["id"], standard_id="STD-TOP-001", source_type="SPOT_CHECK",
                violation_start=f"2026-01-{2*i+1:02d}T00:00:00Z",
                violation_end=f"2026-01-{2*i+2:02d}T00:00:00Z",
                violation_risk_factor="MINIMAL", severity_level="LOWER")
            ap = get_success_data(api_client.create_appeal(
                v["id"], create_appeal_payload(v["version"]), officer))
            get_success_data(api_client.grant_appeal(ap["id"], RER))
        # Full-coverage completed engagement.
        eng = get_success_data(api_client.create_engagement(
            create_engagement_payload(e1["id"], standard_ids=["STD-TOP-001"],
                                      period_start="2026-06-01T00:00:00Z",
                                      period_end="2026-06-30T00:00:00Z"), AUD))
        get_success_data(api_client.start_engagement(eng["id"], AUD))
        a1 = get_success_data(api_client.create_evidence(
            create_evidence_payload(eng["id"], standard_id="STD-TOP-001",
                                    coverage_start="2026-06-01T00:00:00Z",
                                    coverage_end="2026-06-30T00:00:00Z"), officer))
        get_success_data(api_client.accept_evidence(a1["id"], AUD))
        eng = get_success_data(api_client.complete_engagement(eng["id"], AUD))
        return e1, eng

    def test_recidivism_capped_at_five(self):
        """PRD §3.4: "the server counts the entity's other violations that are
        CLOSED with a non-null final_penalty, caps that count at five, and
        multiplies the running factor by one plus one tenth times the capped
        count" — six priors still cap the term at 1 + 0.1*5 = 1.5.

        Design: Corner/calculations/recidivism_cap_at_five_priors
        """
        e1, eng = self._setup()
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TOP-001", source_type="AUDIT",
                violation_start="2026-06-10T00:00:00Z",
                violation_end="2026-06-11T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="MODERATE",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["proposed_penalty"] == pytest.approx(37500.00, abs=0.005)

    def test_uncapped_would_exceed_capped_amount(self):
        """PRD §3.4: "caps that count at five" — an uncapped term for six priors
        would give 25000 * 1.6 = 40000.00; the capped result must be 37500.00.

        Design: Corner/calculations/recidivism_cap_at_five_priors
        """
        e1, eng = self._setup()
        resp = api_client.create_violation(
            create_violation_payload(
                e1["id"], standard_id="STD-TOP-001", source_type="AUDIT",
                violation_start="2026-06-10T00:00:00Z",
                violation_end="2026-06-11T00:00:00Z",
                violation_risk_factor="SERIOUS", severity_level="MODERATE",
                source_engagement_id=eng["id"]), AUD)
        data = validate_success(resp, expected_status=201)
        assert data["proposed_penalty"] == pytest.approx(37500.00, abs=0.005)
        assert data["proposed_penalty"] != pytest.approx(40000.00, abs=0.01)
