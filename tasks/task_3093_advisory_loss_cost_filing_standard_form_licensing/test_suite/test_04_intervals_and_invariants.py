"""Interval semantics and compensating invariants (PRD §2.10, §3.1-§3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_finding,
    begin_edit,
    create_variant_payload,
    dispose,
    make_agreement,
    make_effective_filing,
    make_form_with_variants,
    make_insurer,
    make_adoption,
    make_submission,
    set_clock,
    validate_error,
    validate_success,
    make_insurer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


class TestVariantHalfOpenWindows:
    """Half-open usability windows: touching is allowed; true overlap rejects."""

    def _setup_two_touching_variants(self, api):
        form, variants = make_form_with_variants([
            {"state_code": "CW", "effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2026-07-01T00:00:00Z"},
            {"state_code": "CW", "effective_from": "2026-07-01T00:00:00Z",
             "effective_to": None},
        ])
        return form, variants

    def _setup_overlapping_variants(self, api):
        form, variants = make_form_with_variants([
            {"state_code": "CW", "effective_from": "2026-01-01T00:00:00Z",
             "effective_to": "2026-07-01T00:00:00Z"},
            {"state_code": "CW", "effective_from": "2026-06-30T00:00:00Z",
             "effective_to": "2026-12-01T00:00:00Z"},
        ])
        return form, variants

    def test_touching_half_open_windows_both_clear(self, api):
        """PRD §3.5: "The conflict test uses the half-open semantics of §2.10:
        two variants conflict when the first's `effective_from` is strictly
        before the second's `effective_to` (or the second is open-ended) and
        the second's `effective_from` is strictly before the first's
        `effective_to` (or the first is open-ended); merely touching windows,
        where one variant's `effective_to` equals the other's
        `effective_from`, do not conflict."

        Design: Difficulty/resource_temporal_overlap/variant_half_open_windows_touching_at_boundary_do_not_overlap
        """
        _form, (v1, v2) = self._setup_two_touching_variants(api)
        cleared1 = validate_success(api.clear_variant(v1["id"], ACTUARY))
        cleared2 = validate_success(api.clear_variant(v2["id"], ACTUARY))
        assert cleared1["review_status"] == "CLEARED"
        assert cleared2["review_status"] == "CLEARED"

    def test_truly_overlapping_window_rejected_with_overlap_error(self, api):
        """PRD §3.5: "A conflict rejects the clearing with
        `ERR_VARIANT_WINDOW_OVERLAP` (HTTP 422)."
        PRD §2.10: "Variant usability windows are **half-open**: a variant is
        usable from `effective_from` up to but not including `effective_to`,
        and an open-ended variant has `effective_to` unset."

        Design: Difficulty/resource_temporal_overlap/variant_half_open_windows_touching_at_boundary_do_not_overlap
        """
        _form, (v1, v2) = self._setup_overlapping_variants(api)
        validate_success(api.clear_variant(v1["id"], ACTUARY))
        resp = api.clear_variant(v2["id"], ACTUARY)
        validate_error(resp, ApiErrorId.ERR_VARIANT_WINDOW_OVERLAP)
        after = validate_success(api.get_variant(v2["id"], ADMIN))
        assert after["review_status"] == "PENDING"


class TestLicenseClosedWindowBoundary:
    """Closed license windows: a same-day window covers exactly that day."""

    def _setup_two_insurers(self, api):
        ins_a = make_insurer()
        ins_b = make_insurer()
        # Single-day closed window [2026-10-02, 2026-10-02] for A.
        make_agreement(ins_a["id"], coverage_start="2026-10-02T00:00:00Z",
                       coverage_end="2026-10-02T00:00:00Z", royalty_rate_bps=100)
        # Window for B that ends the day before the clock position.
        make_agreement(ins_b["id"], coverage_start="2026-01-01T00:00:00Z",
                       coverage_end="2026-10-01T00:00:00Z", royalty_rate_bps=100)
        filing, _dept = make_effective_filing(
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
        )
        # Clock now sits at 2026-10-02 after finalize.
        ad_a = make_adoption(ins_a["id"], filing, multiplier_pct=110)
        ad_b = make_adoption(ins_b["id"], filing, multiplier_pct=110)
        return ins_a, ins_b, filing, ad_a, ad_b

    def test_single_day_closed_window_covers_its_own_end_date(self, api):
        """PRD §2.10: "License coverage windows are **closed**: a license
        covers a date from `coverage_start` through `coverage_end` inclusive,
        so a window whose start and end are the same day covers exactly that
        one day."
        PRD §3.4: "the insurer must hold a license agreement in `ACTIVE`
        status whose closed coverage window contains the logical-clock date —
        meaning the date is on or after `coverage_start` and on or before
        `coverage_end`, with a same-day window covering exactly that day —
        else the authorization is rejected with `ERR_LICENSE_NOT_COVERING`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/license_closed_window_single_day_and_boundary_coverage
        """
        _a, _b, _filing, ad_a, _ad_b = self._setup_two_insurers(api)
        adoption = validate_success(api.authorize_adoption(ad_a["id"], ADMIN))
        assert adoption["adoption_status"] == "AUTHORIZED"
        assert adoption["authorized_premium_cents"] == 132000

    def test_day_after_window_end_rejects_with_license_not_covering(self, api):
        """PRD §3.4: "the insurer must hold a license agreement in `ACTIVE`
        status whose closed coverage window contains the logical-clock date —
        meaning the date is on or after `coverage_start` and on or before
        `coverage_end`, with a same-day window covering exactly that day —
        else the authorization is rejected with `ERR_LICENSE_NOT_COVERING`
        (HTTP 422)."
        PRD §2.10: "License coverage windows are **closed**: a license covers
        a date from `coverage_start` through `coverage_end` inclusive, so a
        window whose start and end are the same day covers exactly that one
        day."
        PRD §3.5: "when the logical clock is later than `coverage_end`, the
        `agreement_status` transitions from `ACTIVE` to `LAPSED` upon the next
        read of the agreement or the next adoption authorization that consults
        it — and every `PENDING` adoption of that insurer is withdrawn as a
        consequence, marked with the reason `LICENCE_LAPSED`."

        Design: Difficulty/resource_temporal_overlap/license_closed_window_single_day_and_boundary_coverage
        """
        _a, _b, _filing, _ad_a, ad_b = self._setup_two_insurers(api)
        resp = api.authorize_adoption(ad_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_COVERING)
        # The authorization attempt consults the lapsed agreement, so the
        # lazy-lapse cascade withdraws the insurer's PENDING adoption.
        adoption = validate_success(api.get_adoption(ad_b["id"], ADMIN))
        assert adoption["adoption_status"] == "WITHDRAWN"


class TestFilingChainCardinalityInvariant:
    """Exactly one live node per filing-code chain across objection +
    resubmission."""

    def _setup_resubmission(self, api):
        from test_helpers import create_filing_payload, make_objected_filing
        objected, _dept, _obj = make_objected_filing()
        resp = api.create_filing(
            create_filing_payload(
                trend_selection="EXPONENTIAL_LEAST_SQUARES",
                effective_date="2027-03-01T00:00:00Z",
                supersedes_filing_id=objected["id"],
                expected_superseded_version=objected["version"],
            ),
            ADMIN,
        )
        new_filing = validate_success(resp, expected_status=201)
        return objected, new_filing

    def test_chain_has_exactly_one_live_node_after_resubmission(self, api):
        """PRD §3.3: "On success the new filing is created in `DRAFT` with
        `filing_version` equal to the superseded filing's version number plus
        1, while the superseded filing itself transitions from `OBJECTED` to
        `WITHDRAWN` (terminal) with its `version` incremented by 1."
        PRD §3.3: "An `OBJECTED` filing is answered by resubmission, and the
        cycle lives on the version chain rather than on the row."

        Design: Difficulty/compensating_invariant/objection_resubmission_conserves_filing_code_chain_cardinality
        """
        from test_helpers import validate_paginated
        objected, new_filing = self._setup_resubmission(api)
        rows, meta = validate_paginated(
            api.list_filings(ADMIN, params={"filing_status": "DRAFT"})
        )
        assert len(rows) == 1
        assert meta["total_count"] == 1
        assert rows[0]["id"] == new_filing["id"]
        assert rows[0]["filing_code"] == new_filing["filing_code"] == objected["filing_code"]

    def test_compensated_node_withdrawn_and_versions_increase(self, api):
        """PRD §3.3: "On success the new filing is created in `DRAFT` with
        `filing_version` equal to the superseded filing's version number plus
        1, while the superseded filing itself transitions from `OBJECTED` to
        `WITHDRAWN` (terminal) with its `version` incremented by 1."

        Design: Difficulty/compensating_invariant/objection_resubmission_conserves_filing_code_chain_cardinality
        """
        objected, new_filing = self._setup_resubmission(api)
        superseded = validate_success(api.get_filing(objected["id"], ADMIN))
        assert superseded["filing_status"] == "WITHDRAWN"
        assert new_filing["filing_version"] == 2
        assert new_filing["supersedes_filing_id"] == objected["id"]


class TestSuspendReinstateConservesQualityScore:
    """Suspend + reinstate flips status but never touches the quality ledger."""

    def _setup_insurer_scored_9750(self, api):
        from test_helpers import make_active_plan
        insurer = make_insurer()
        plan = make_active_plan()
        sub = make_submission(insurer["id"], plan["id"])
        begin_edit(sub["id"])
        add_finding(sub["id"], severity="ERROR", edit_code="E-900")
        add_finding(sub["id"], severity="WARNING", edit_code="W-900")
        dispose(sub["id"])
        return insurer

    def test_quality_score_unchanged_across_suspend_reinstate(self, api):
        """PRD §3.2: "That score is recomputed after every statistical
        submission disposition, per §3.2." (§3.1: "a perfect statistical
        reporting quality: `quality_score_bps` starts at 10000, expressed in
        basis points on a 0 to 10000 scale. That score is recomputed after
        every statistical submission disposition, per §3.2.")
        PRD §3.1: "Suspending an insurer moves `insurer_status` from `ACTIVE`
        to `SUSPENDED`, increments the insurer's `version`, and has an
        immediate side effect: any attempt by that insurer to create a
        statistical submission is rejected with `ERR_INSURER_SUSPENDED` while
        the suspension stands."

        Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_insurer_quality_score
        """
        insurer = self._setup_insurer_scored_9750(api)
        scored = validate_success(api.get_insurer(insurer["id"], ADMIN))
        assert scored["quality_score_bps"] == 9750
        validate_success(api.suspend_insurer(insurer["id"], ADMIN))
        validate_success(api.reinstate_insurer(insurer["id"], ADMIN))
        after = validate_success(api.get_insurer(insurer["id"], ADMIN))
        assert after["quality_score_bps"] == 9750

    def test_round_trip_restores_active_and_advances_version_exactly(self, api):
        """PRD §3.1: "Reinstatement returns a `SUSPENDED` insurer to
        `ACTIVE`."
        PRD §3.1: "Suspension, reinstatement, and withdrawal each increment
        the insurer's `version` by 1 and refresh `updated_at`."
        PRD §2.5: "`version`, an integer starting at creation that increments
        by exactly 1 on every mutation of that resource."

        Design: Difficulty/compensating_invariant/suspend_reinstate_conserves_insurer_quality_score
        """
        insurer = self._setup_insurer_scored_9750(api)
        # version: 1 create, 2 disposition, then suspend/reinstate each +1.
        validate_success(api.suspend_insurer(insurer["id"], ADMIN))
        validate_success(api.reinstate_insurer(insurer["id"], ADMIN))
        after = validate_success(api.get_insurer(insurer["id"], ADMIN))
        assert after["insurer_status"] == "ACTIVE"
        assert after["version"] == 4
