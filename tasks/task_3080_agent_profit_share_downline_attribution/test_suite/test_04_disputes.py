"""Sponsorship disputes: lifecycle cycle, evidence and filer validations, the
90-day window, the sponsor-cycle guard, and the appeal counter."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_center,
    enroll_agent,
    file_dispute,
    get_agent,
    get_success_data,
    setup_center_with_mca,
    setup_dispute_fixture,
    setup_filed_dispute,
    setup_resolved_upheld_dispute,
    setup_under_review_dispute,
    validate_error,
    validate_success,
    create_dispute_payload,
)
from test_helpers import TEST_USERS, make_agent_headers

PA = TEST_USERS["platform_admin_headers"]
RD = TEST_USERS["regional_director_headers"]


class TestDisputeCycle:
    def test_full_appeal_cycle_traversal(self, api):
        """PRD §3.4: "A successful appeal moves the dispute from RESOLVED_UPHELD
        or RESOLVED_OVERTURNED to REOPENED and increments appeal_count by one;
        opening review then moves REOPENED back to UNDER_REVIEW for a fresh
        adjudication."

        Design: Difficulty/non_linear_state_machine/dispute_resolve_appeal_reopen_cycle
        """
        ctx = setup_resolved_upheld_dispute()
        dsp = ctx["dispute"]
        appealed = validate_success(api.appeal_dispute(
            dsp["id"], {"reason": "New evidence"}, make_agent_headers(ctx["r1"]["id"])), 200)
        assert appealed["status"] == "REOPENED"
        assert appealed["appeal_count"] == 1
        reviewing = validate_success(api.open_dispute_review(dsp["id"], RD), 200)
        assert reviewing["status"] == "UNDER_REVIEW"
        resolved = validate_success(api.resolve_dispute(dsp["id"], {"outcome": "OVERTURNED"}, RD), 200)
        assert resolved["status"] == "RESOLVED_OVERTURNED", (
            "the dispute traversed RESOLVED_UPHELD -> REOPENED -> UNDER_REVIEW -> RESOLVED_OVERTURNED"
        )
        assert resolved["appeal_count"] == 1

    def test_overturn_repoints_sponsor_to_filer(self, api):
        """PRD §3.4: "RESOLVED_OVERTURNED is not terminal — see the appeal path
        below — but it fires a large cascade immediately: the sponsored agent's
        sponsor_agent_id is re-pointed to the filer and that agent's version
        incremented"

        Design: Difficulty/non_linear_state_machine/dispute_resolve_appeal_reopen_cycle
        """
        ctx = setup_resolved_upheld_dispute()
        dsp = ctx["dispute"]
        validate_success(api.appeal_dispute(
            dsp["id"], {"reason": "New evidence"}, make_agent_headers(ctx["r1"]["id"])), 200)
        validate_success(api.open_dispute_review(dsp["id"], RD), 200)
        validate_success(api.resolve_dispute(dsp["id"], {"outcome": "OVERTURNED"}, RD), 200)
        s2 = get_agent(ctx["s2"]["id"])
        assert s2["sponsor_agent_id"] == ctx["r1"]["id"], (
            f"after OVERTURNED the sponsor is re-pointed to the filer, got {s2['sponsor_agent_id']}"
        )


class TestDisputeWindow:
    def test_deadline_is_inclusive(self, api):
        """PRD §3.4: "The dispute is accepted only within a window:
        window_deadline is computed as the sponsored agent's join_date plus ninety
        days, and filing is accepted when filed_at falls on or before that deadline
        — the boundary is inclusive."

        Design: Difficulty/boundary_precision_check/dispute_window_day_90_inclusive
        """
        ctx = setup_dispute_fixture()
        validate_success(api.set_clock("2026-11-30T00:00:00Z", PA), 200)
        dispute = file_dispute(ctx["r1"]["id"], ctx["s2"]["id"], ctx["att"]["id"],
                               reason="at the deadline")
        assert dispute["status"] == "FILED"
        assert dispute["window_deadline"].startswith("2026-11-30"), (
            f"join_date + 90 days, got {dispute['window_deadline']}"
        )
        assert dispute["filed_at"].startswith("2026-11-30")

    def test_filing_one_second_after_deadline_rejected(self, api):
        """PRD §3.4: "The dispute is accepted only within a window:
        window_deadline is computed as the sponsored agent's join_date plus ninety
        days, and filing is accepted when filed_at falls on or before that deadline
        — the boundary is inclusive. A filing after the deadline is rejected with
        ERR_DISPUTE_WINDOW_EXPIRED (HTTP 422)."
        PRD §3.4: "the filer must be neither the sponsored agent themself nor the
        current sponsor of record (else ERR_DISPUTE_NOT_ACTIONABLE, HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/dispute_rolling_window_membership_semantics
        """
        ctx = setup_dispute_fixture()
        validate_success(api.set_clock("2026-11-30T00:00:01Z", PA), 200)
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"],
                                   reason="one second late"),
            make_agent_headers(ctx["r1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)

    def test_filing_exactly_at_deadline_is_in_window(self, api):
        """PRD §3.4: "The dispute is accepted only within a window:
        window_deadline is computed as the sponsored agent's join_date plus ninety
        days, and filing is accepted when filed_at falls on or before that deadline
        — the boundary is inclusive. A filing after the deadline is rejected with
        ERR_DISPUTE_WINDOW_EXPIRED (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/dispute_rolling_window_membership_semantics
        """
        ctx = setup_dispute_fixture()
        validate_success(api.set_clock("2026-11-30T00:00:00Z", PA), 200)
        dispute = file_dispute(ctx["r1"]["id"], ctx["s2"]["id"], ctx["att"]["id"],
                               reason="exactly at the deadline")
        assert dispute["status"] == "FILED", (
            "the rolling window's end instant is inside the window"
        )

    def test_filing_one_day_late_rejected(self, api):
        """PRD §3.4: "A filing after the deadline is rejected with
        ERR_DISPUTE_WINDOW_EXPIRED (HTTP 422)."
        PRD §3.4: "the filer must be neither the sponsored agent themself nor the
        current sponsor of record (else ERR_DISPUTE_NOT_ACTIONABLE, HTTP 422)."

        Design: Difficulty/boundary_precision_check/dispute_window_day_90_inclusive
        """
        ctx = setup_dispute_fixture()
        validate_success(api.set_clock("2026-11-30T00:00:00Z", PA), 200)
        file_dispute(ctx["r1"]["id"], ctx["s2"]["id"], ctx["att"]["id"],
                     reason="at the deadline")
        validate_success(api.set_clock("2026-12-01T00:00:00Z", PA), 200)
        # mca is not the sponsored agent and not a sponsor of record candidate
        # here, so the window check is the rejecting rule.
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"], reason="one day late"),
            make_agent_headers(ctx["mca"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)


    def test_window_checked_before_filer_actionability(self, api):
        """PRD §2.5: "When a request violates multiple rules, exactly one error
        is returned, chosen by the following global priority order. Authentication
        comes first (missing or unrecognized headers, ERR_UNAUTHENTICATED), then
        role authorization (ERR_FORBIDDEN), then path-parameter existence checks
        evaluated left-to-right along the URL hierarchy (each with its
        resource-specific not-found error), then existence of body-referenced
        identifiers, then field well-formedness (ERR_VALIDATION), then state
        eligibility for the requested transition (ERR_INVALID_STATE), then the
        business rules in their documented order: temporal windows, referential
        constraints, business constraints, fiscal positivity, segregation of
        duties, and finally the optimistic-concurrency stale-version check
        (ERR_STALE_AGENT_VERSION), which is evaluated last."
        PRD §3.4: "A filing after the deadline is rejected with
        ERR_DISPUTE_WINDOW_EXPIRED (HTTP 422)."
        PRD §3.4: "the filer must be neither the sponsored agent themself nor the
        current sponsor of record (else ERR_DISPUTE_NOT_ACTIONABLE, HTTP 422)."

        Design: Difficulty/boundary_precision_check/dispute_window_day_90_inclusive
        """
        ctx = setup_dispute_fixture()
        validate_success(api.set_clock("2026-12-15T00:00:00Z", PA), 200)
        # The filer (mca) is also the current sponsor of record, so two rules
        # fail; the temporal window rule is documented ahead of the referential
        # actionability rule.
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"],
                                   reason="late self dispute"),
            make_agent_headers(ctx["mca"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)


class TestDisputeValidations:
    def test_evidence_must_attest_the_filer(self, api):
        """PRD §3.4: "the evidence document must be a SPONSOR_ATTESTATION
        belonging to the sponsored agent whose attested_sponsor_agent_id equals
        the filer (else ERR_EVIDENCE_INVALID)"

        Design: Corner/validations/dispute_evidence_not_attesting_filer_rejected
        """
        # s2's attestation names mca (the recorded sponsor), not the filer r1.
        ctx = setup_dispute_fixture(attest_sponsor="mca")
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"], reason="wrong attestee"),
            make_agent_headers(ctx["r1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_INVALID)

    def test_current_sponsor_cannot_dispute_own_attribution(self, api):
        """PRD §3.4: "the filer must be neither the sponsored agent themself nor
        the current sponsor of record (else ERR_DISPUTE_NOT_ACTIONABLE, HTTP 422)."

        Design: Corner/validations/dispute_by_current_sponsor_not_actionable
        """
        ctx = setup_dispute_fixture(attest_sponsor="mca")
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"], reason="self dispute"),
            make_agent_headers(ctx["mca"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_NOT_ACTIONABLE)

    def test_appeal_exhausted_after_single_appeal(self, api):
        """PRD §3.4: "The appellant must be the original filer — X-User-ID
        compared to filer_agent_id, else ERR_FORBIDDEN — and appeal_count must
        still be zero, else ERR_APPEAL_EXHAUSTED (HTTP 422), since at most one
        appeal is permitted."

        Design: Corner/validations/appeal_exhausted_after_single_appeal
        """
        ctx = setup_resolved_upheld_dispute()
        dsp = ctx["dispute"]
        validate_success(api.appeal_dispute(
            dsp["id"], {"reason": "appeal one"}, make_agent_headers(ctx["r1"]["id"])), 200)
        validate_success(api.open_dispute_review(dsp["id"], RD), 200)
        validate_success(api.resolve_dispute(dsp["id"], {"outcome": "UPHELD"}, RD), 200)
        resp = api.appeal_dispute(
            dsp["id"], {"reason": "appeal two"}, make_agent_headers(ctx["r1"]["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_EXHAUSTED)


class TestSponsorCycleOnOverturn:
    def _setup_descendant_claim(self, api):
        ctx = setup_center_with_mca()
        center, mca = ctx["center"], ctx["mca"]
        s1 = enroll_agent(center["id"], sponsor_id=mca["id"])
        d1 = enroll_agent(center["id"], sponsor_id=s1["id"])
        # A second attestation on s1 naming her own descendant d1.
        att2 = get_success_data(api.create_onboarding_document(
            s1["id"],
            {"document_type": "SPONSOR_ATTESTATION", "document_ref": "doc-s1-att2",
             "attested_sponsor_agent_id": d1["id"]},
            PA,
        ))
        dsp = file_dispute(d1["id"], s1["id"], att2["id"], reason="d1 claims sponsorship")
        validate_success(api.open_dispute_review(dsp["id"], RD), 200)
        return {"center": center, "mca": mca, "s1": s1, "d1": d1, "dsp": dsp}

    def test_overturn_to_descendant_rejected(self, api):
        """PRD §3.3: "the new sponsor chain must neither be the enrollee themself
        nor loop back through the enrollee (else ERR_SPONSOR_CYCLE, HTTP 422)."

        Design: Corner/validations/sponsor_cycle_on_overturn_rejected
        """
        ctx = self._setup_descendant_claim(api)
        resp = api.resolve_dispute(ctx["dsp"]["id"], {"outcome": "OVERTURNED"}, RD)
        validate_error(resp, ApiErrorId.ERR_SPONSOR_CYCLE)

    def test_cycle_rejection_leaves_tree_untouched(self, api):
        """PRD §3.3: "the new sponsor chain must neither be the enrollee themself
        nor loop back through the enrollee (else ERR_SPONSOR_CYCLE, HTTP 422)."
        PRD §3.4: "RESOLVED_UPHELD and DISMISSED are terminal: the recorded sponsor
        stands and no tree mutation occurs."

        Design: Corner/validations/sponsor_cycle_on_overturn_rejected
        """
        ctx = self._setup_descendant_claim(api)
        validate_error(
            api.resolve_dispute(ctx["dsp"]["id"], {"outcome": "OVERTURNED"}, RD),
            ApiErrorId.ERR_SPONSOR_CYCLE,
        )
        dispute = get_success_data(api.get_dispute(ctx["dsp"]["id"], PA))
        assert dispute["status"] == "UNDER_REVIEW"
        s1 = get_agent(ctx["s1"]["id"])
        assert s1["sponsor_agent_id"] == ctx["mca"]["id"], (
            "no tree mutation occurs when the overturn is rejected"
        )


class TestBodyForeignKeyExistence:
    def test_missing_sponsored_agent_and_document(self, api):
        """PRD §2.5: "Each resource class has its own not-found error identifier —
        ERR_MARKET_CENTER_NOT_FOUND, ERR_AGENT_NOT_FOUND, ERR_PERIOD_NOT_FOUND,
        ERR_DISPUTE_NOT_FOUND, ERR_DOCUMENT_NOT_FOUND, ERR_COMMISSION_EVENT_NOT_FOUND,
        ERR_TRANSFER_NOT_FOUND, ERR_RESOLUTION_NOT_FOUND, and
        ERR_DISTRIBUTION_NOT_FOUND — all carrying HTTP 404, and the same
        per-resource identifiers apply when a body field references a nonexistent
        resource."
        PRD §2.5: "When a request violates multiple rules, exactly one error is
        returned, chosen by the following global priority order. Authentication
        comes first (missing or unrecognized headers, ERR_UNAUTHENTICATED), then
        role authorization (ERR_FORBIDDEN), then path-parameter existence checks
        evaluated left-to-right along the URL hierarchy (each with its
        resource-specific not-found error), then existence of body-referenced
        identifiers, then field well-formedness (ERR_VALIDATION), then state
        eligibility for the requested transition (ERR_INVALID_STATE), then the
        business rules in their documented order: temporal windows, referential
        constraints, business constraints, fiscal positivity, segregation of
        duties, and finally the optimistic-concurrency stale-version check
        (ERR_STALE_AGENT_VERSION), which is evaluated last."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_dispute_filing
        """
        ctx = setup_center_with_mca()
        validate_success(api.set_clock("2026-12-15T00:00:00Z", PA), 200)
        resp = api.create_dispute(
            create_dispute_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                                   reason="late and bogus"),
            make_agent_headers(ctx["mca"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGENT_NOT_FOUND)

    def test_late_filing_against_existing_agent_window_fires(self, api):
        """PRD §2.5: "When a request violates multiple rules, exactly one error
        is returned, chosen by the following global priority order. Authentication
        comes first (missing or unrecognized headers, ERR_UNAUTHENTICATED), then
        role authorization (ERR_FORBIDDEN), then path-parameter existence checks
        evaluated left-to-right along the URL hierarchy (each with its
        resource-specific not-found error), then existence of body-referenced
        identifiers, then field well-formedness (ERR_VALIDATION), then state
        eligibility for the requested transition (ERR_INVALID_STATE), then the
        business rules in their documented order: temporal windows, referential
        constraints, business constraints, fiscal positivity, segregation of
        duties, and finally the optimistic-concurrency stale-version check
        (ERR_STALE_AGENT_VERSION), which is evaluated last."
        PRD §3.4: "A filing after the deadline is rejected with
        ERR_DISPUTE_WINDOW_EXPIRED (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_temporal_on_dispute_filing
        """
        ctx = setup_dispute_fixture()
        validate_success(api.set_clock("2026-12-15T00:00:00Z", PA), 200)
        # Contrast leg of the pair: the sponsored agent exists, so the temporal
        # window rule is the one that rejects the filing.
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], ctx["att"]["id"], reason="too late"),
            make_agent_headers(ctx["r1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)

    def test_missing_evidence_document_returns_document_not_found(self, api):
        """PRD §2.5: "Each resource class has its own not-found error identifier —
        ERR_MARKET_CENTER_NOT_FOUND, ERR_AGENT_NOT_FOUND, ERR_PERIOD_NOT_FOUND,
        ERR_DISPUTE_NOT_FOUND, ERR_DOCUMENT_NOT_FOUND, ERR_COMMISSION_EVENT_NOT_FOUND,
        ERR_TRANSFER_NOT_FOUND, ERR_RESOLUTION_NOT_FOUND, and
        ERR_DISTRIBUTION_NOT_FOUND — all carrying HTTP 404, and the same
        per-resource identifiers apply when a body field references a nonexistent
        resource."

        Design: Corner/errors/dispute_with_missing_evidence_returns_document_not_found
        """
        ctx = setup_dispute_fixture()
        resp = api.create_dispute(
            create_dispute_payload(ctx["s2"]["id"], NON_EXISTENT_UUID, reason="bogus doc"),
            make_agent_headers(ctx["r1"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_FOUND)


class TestLogicalClock:
    def test_default_clock_and_set_current_utc(self, api):
        """PRD §2.8: "The server keeps a logical clock used for all time-gated
        business rules: dispute filing deadlines, transfer effectiveness, receipt
        timestamps, and vesting windows. At startup the clock reads
        2026-09-01T00:00:00Z, and the server must never fall back to wall-clock
        time. A PlatformAdmin advances the clock through a dedicated test-driving
        capability that accepts a to_iso8601 timestamp and returns the new
        current_utc; time-gated rules are re-evaluated lazily on the next read or
        write rather than by an eager sweep."
        PRD §3.4: "The dispute is accepted only within a window: window_deadline
        is computed as the sponsored agent's join_date plus ninety days, and
        filing is accepted when filed_at falls on or before that deadline — the
        boundary is inclusive."

        Design: Corner/endpoints/clock_default_and_set_current_utc
        """
        ctx = setup_dispute_fixture()
        # No set_current_utc call: the filed dispute must stamp the default clock.
        dispute = file_dispute(ctx["r1"]["id"], ctx["s2"]["id"], ctx["att"]["id"],
                               reason="default clock probe")
        assert dispute["filed_at"].startswith("2026-09-01T00:00:00"), (
            f"filed_at comes from the server default clock, got {dispute['filed_at']}"
        )
        assert dispute["window_deadline"].startswith("2026-11-30"), (
            f"join_date + 90 days, got {dispute['window_deadline']}"
        )
        echoed = validate_success(api.set_clock("2026-10-01T00:00:00Z", PA), 200)
        assert echoed["current_utc"].startswith("2026-10-01T00:00:00"), (
            f"set_current_utc echoes the new time, got {echoed['current_utc']}"
        )
