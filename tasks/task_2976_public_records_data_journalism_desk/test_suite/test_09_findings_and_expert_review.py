"""Findings, expert review and the verification partition (PRD S3.7, S3.8).

Everything here turns on three PRD rules that are easy to get backwards:

* the finding-count partition of PRD S3.7 is conserved by a verification
  revocation, which moves one unit between buckets and deliberately leaves
  ``finding_count`` alone;
* the two assignment gates of PRD S3.8 run conflict-of-interest *before*
  aggregate capacity, so a candidate that violates both sees the conflict; and
* an assignment window is a **closed** interval, so windows that merely touch at
  an endpoint overlap -- the opposite of the half-open enclave rule.
"""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_ASSIGNMENT_NOT_OWNED,
    ERR_INVALID_RUN_STATE,
    ERR_REVIEWER_CAPACITY_EXCEEDED,
    ERR_REVIEWER_CONFLICT_OF_INTEREST,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_field_absent_or_null,
    assert_instant_equals,
    assert_partition_counts,
    assert_version_is,
    validate_created,
    validate_error,
    validate_ok,
    validate_paginated_page,
)
from test_helpers.test_users import (
    editor_headers,
    expert_reviewer_headers,
    peer_reviewer_headers,
    reporter_headers,
)
from test_helpers import test_users as U

# --------------------------------------------------------------------------
# Private reads and world builders (this module owns them; nothing is shared)
# --------------------------------------------------------------------------


def _read_reviewer(api, reviewer_id: str) -> Dict[str, Any]:
    """GET /records-desk/expert-reviewers/{id} (PRD S4)."""
    return validate_ok(api.get_expert_reviewer(reviewer_id, editor_headers()))


def _read_assignment(api, assignment_id: str) -> Dict[str, Any]:
    """GET /records-desk/review-assignments/{id} (PRD S4)."""
    return validate_ok(api.get_review_assignment(assignment_id, editor_headers()))


def _confirm(api, assignment_id: str, reviewer_id: str, rationale: str) -> Dict[str, Any]:
    """Return a ``CONFIRMED`` verdict as the assignment's own reviewer."""
    return validate_ok(
        api.submit_verdict(
            assignment_id,
            F.verdict_payload(C.VERDICT_CONFIRMED, rationale=rationale),
            expert_reviewer_headers(reviewer_id),
        )
    )


def _revocation_world(api) -> Dict[str, Any]:
    """Two confirmed findings on a locked investigation, plus one live assignment.

    The investigation reaches ``FINDINGS_LOCKED`` with its current run approved
    and cost-allocated, and a further assignment on the first finding is left in
    ``ASSIGNED`` so the revocation cascade has both a ``COMPLETED`` and an
    ``ASSIGNED`` row to release.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(api)
    request = X.released_request(api, desk["id"], agency["id"])
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_FULL_DATA_RELEASE
    )
    dataset = X.clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=500,
        field_specs=[{"field_name": "closure_reason", "reidentification_risk": 2}],
    )
    run = X.create_run(
        api, investigation["id"], compute_cost_cents=5000, labor_hours=1.0
    )
    validate_ok(api.allocate_cost(run["id"], reporter_headers()))
    validate_ok(
        api.submit_peer_review(
            run["id"],
            F.peer_review_payload(C.REVIEW_APPROVED),
            peer_reviewer_headers(),
        )
    )
    first = X.doc_matched_finding(
        api,
        investigation["id"],
        run["id"],
        matched_page=7,
        claim_text="A fifth of repair orders were closed with no repair record.",
    )
    second = X.doc_matched_finding(
        api,
        investigation["id"],
        run["id"],
        matched_page=9,
        claim_text="Closure reasons were entered in bulk on a single day.",
    )
    reviewer = X.create_reviewer(api)
    first_assignment = X.assign_review(
        api,
        reviewer["id"],
        first["id"],
        "2026-09-01T00:00:00Z",
        "2026-09-05T00:00:00Z",
    )
    _confirm(
        api,
        first_assignment["id"],
        reviewer["id"],
        "Consistent with the closure logs I reviewed.",
    )
    second_assignment = X.assign_review(
        api,
        reviewer["id"],
        second["id"],
        "2026-09-01T00:00:00Z",
        "2026-09-05T00:00:00Z",
    )
    _confirm(
        api,
        second_assignment["id"],
        reviewer["id"],
        "The bulk-entry pattern is unmistakable.",
    )
    X.lock_findings(api, investigation["id"])
    extra_assignment = X.assign_review(
        api,
        reviewer["id"],
        first["id"],
        "2026-09-10T00:00:00Z",
        "2026-09-12T00:00:00Z",
    )
    return {
        "desk": desk,
        "agency": agency,
        "request": request,
        "investigation": investigation,
        "dataset": dataset,
        "run": run,
        "first": first,
        "second": second,
        "reviewer": reviewer,
        "first_assignment": first_assignment,
        "second_assignment": second_assignment,
        "extra_assignment": extra_assignment,
    }


def _revoke(api, finding_id: str) -> Dict[str, Any]:
    """Revoke a finding's verification as the ``ManagingEditor`` (PRD S3.8)."""
    return validate_ok(
        api.revoke_verification(
            finding_id,
            F.verification_revocation_payload(
                reason="The cited page did not support the claim as written."
            ),
            editor_headers(),
        )
    )


def _conflict_world(api) -> Dict[str, Any]:
    """A reviewer at capacity who is also conflicted on the second agency.

    Two investigations are built on two different agencies so one candidate
    assignment can violate the conflict gate and the capacity gate at once while
    a control candidate violates only the capacity gate.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    clean_agency = X.create_agency(api)
    conflicted_agency = X.create_agency(
        api,
        name="City Building Department",
        jurisdiction_code="CA-CITY",
        deadline_basis=C.CALENDAR_DAYS,
        tolling_allowed=False,
        appeal_venue=C.VENUE_INTERNAL,
        appeal_decision_days=15,
        search_fee_cents_per_hour=4000,
        page_fee_cents=20,
        max_waiver_cents=8000,
        holiday_dates=[],
    )
    clean_request = X.submitted_request(api, desk["id"], clean_agency["id"])
    conflicted_request = X.submitted_request(
        api,
        desk["id"],
        conflicted_agency["id"],
        subject_summary="Building permit approvals",
        estimated_page_count=80,
        public_interest_score=60,
    )
    clean_investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY
    )
    conflicted_investigation = X.create_investigation(
        api,
        desk["id"],
        C.MODE_METHODOLOGY_ONLY,
        headline="Permits fast-tracked for donors",
    )
    X.register_dataset(api, clean_request["id"], clean_investigation["id"])
    X.register_dataset(
        api, conflicted_request["id"], conflicted_investigation["id"]
    )
    clean_run = X.create_run(
        api, clean_investigation["id"], compute_cost_cents=1000, labor_hours=1.0
    )
    conflicted_run = X.create_run(
        api,
        conflicted_investigation["id"],
        compute_cost_cents=1000,
        labor_hours=1.0,
    )
    clean_findings = [
        X.create_finding(
            api,
            clean_investigation["id"],
            clean_run["id"],
            claim_text=f"Finding {index} on the housing data.",
        )
        for index in ("one", "two", "three")
    ]
    conflicted_finding = X.create_finding(
        api,
        conflicted_investigation["id"],
        conflicted_run["id"],
        claim_text="Finding one on the permit data.",
    )
    reviewer = X.create_reviewer(
        api, conflict_of_interest_agency_ids=[conflicted_agency["id"]]
    )
    first_assignment = X.assign_review(
        api,
        reviewer["id"],
        clean_findings[0]["id"],
        "2026-09-01T00:00:00Z",
        "2026-09-05T00:00:00Z",
    )
    second_assignment = X.assign_review(
        api,
        reviewer["id"],
        clean_findings[1]["id"],
        "2026-09-03T00:00:00Z",
        "2026-09-07T00:00:00Z",
    )
    return {
        "reviewer": reviewer,
        "clean_findings": clean_findings,
        "conflicted_finding": conflicted_finding,
        "first_assignment": first_assignment,
        "second_assignment": second_assignment,
    }


def _capacity_world(api):
    """One reviewer at ``max_concurrent_assignments`` 2 with two overlapping windows.

    The two existing windows are exactly the ones PRD S3.8's worked example uses:
    ``[2026-09-01, 2026-09-05]`` and ``[2026-09-03, 2026-09-07]``.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(api)
    request = X.submitted_request(api, desk["id"], agency["id"])
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY
    )
    X.register_dataset(api, request["id"], investigation["id"])
    run = X.create_run(
        api, investigation["id"], compute_cost_cents=1000, labor_hours=1.0
    )
    findings = [
        X.create_finding(
            api, investigation["id"], run["id"], claim_text=f"Finding {label}."
        )
        for label in ("one", "two", "three")
    ]
    reviewer = X.create_reviewer(api)
    first_assignment = X.assign_review(
        api,
        reviewer["id"],
        findings[0]["id"],
        "2026-09-01T00:00:00Z",
        "2026-09-05T00:00:00Z",
    )
    second_assignment = X.assign_review(
        api,
        reviewer["id"],
        findings[1]["id"],
        "2026-09-03T00:00:00Z",
        "2026-09-07T00:00:00Z",
    )
    return {
        "reviewer": reviewer,
        "findings": findings,
        "first_assignment": first_assignment,
        "second_assignment": second_assignment,
    }


class TestVerificationRevocationPreservesTheFindingCountPartition:
    """The revocation cascade of PRD S3.8 as a conserved four-way partition."""

    def test_hop_one_unverifies_the_finding_and_hop_three_reopens_analysis(
        self, api
    ):
        """Revoking clears the match and knocks the locked investigation back.

        PRD S3.8: "**Hop one:** the finding returns to `UNVERIFIED`,
        `matched_page` and `sme_verdict_rationale` are cleared to null, and the
        finding's unit moves out of whichever bucket held it and back into
        `unverified_finding_count`; `finding_count` itself is deliberately **not**
        changed, so the partition identity still holds."

        Design: Difficulty/compensating_invariant/verification_revocation_preserves_the_finding_count_partition
        """
        world = _revocation_world(api)
        before = X.read_investigation(api, world["investigation"]["id"])
        assert before["status"] == C.INV_FINDINGS_LOCKED
        assert before["sme_confirmed_finding_count"] == 2
        assert (
            _read_reviewer(api, world["reviewer"]["id"])["active_assignment_count"]
            == 1
        )

        revoked = _revoke(api, world["first"]["id"])
        assert revoked["verification_status"] == C.FIND_UNVERIFIED
        assert_field_absent_or_null(revoked, "matched_page", "revoked finding")
        assert_field_absent_or_null(
            revoked, "sme_verdict_rationale", "revoked finding"
        )

        investigation = X.read_investigation(api, world["investigation"]["id"])
        assert investigation["analysis_readiness"] == C.READINESS_NOT_READY
        assert investigation["status"] == C.INV_ANALYSIS

    def test_hop_two_releases_both_assignments_but_decrements_once(self, api):
        """Only the formerly ``ASSIGNED`` row gives capacity back.

        PRD S3.8: "**Hop two:** because the finding is unverified again, every
        assignment on that finding in `ASSIGNED` or `COMPLETED` status moves to
        `RELEASED`, with `verdict` and `rationale` cleared, and the reviewer's
        `active_assignment_count` decrements once for each formerly `ASSIGNED`
        row."

        Design: Difficulty/compensating_invariant/verification_revocation_preserves_the_finding_count_partition
        """
        world = _revocation_world(api)
        _revoke(api, world["first"]["id"])

        completed_then_released = _read_assignment(
            api, world["first_assignment"]["id"]
        )
        assert completed_then_released["status"] == C.ASSIGN_RELEASED
        assert_field_absent_or_null(
            completed_then_released, "verdict", "released assignment"
        )
        assert_field_absent_or_null(
            completed_then_released, "rationale", "released assignment"
        )

        assigned_then_released = _read_assignment(
            api, world["extra_assignment"]["id"]
        )
        assert assigned_then_released["status"] == C.ASSIGN_RELEASED
        assert (
            _read_reviewer(api, world["reviewer"]["id"])["active_assignment_count"]
            == 0
        )

    def test_the_partition_still_sums_to_the_unchanged_finding_count(self, api):
        """One unit moves buckets while ``finding_count`` stays at 2.

        PRD S3.7: "The investigation maintains a **partition invariant** that
        must hold after every mutation: `finding_count` equals the sum of
        `unverified_finding_count`, `doc_matched_finding_count`,
        `sme_confirmed_finding_count` and `sme_disputed_finding_count`."

        Design: Difficulty/compensating_invariant/verification_revocation_preserves_the_finding_count_partition
        """
        world = _revocation_world(api)
        _revoke(api, world["first"]["id"])

        investigation = X.read_investigation(api, world["investigation"]["id"])
        assert_partition_counts(investigation, 2, 1, 0, 1, 0)

    def test_the_sibling_finding_and_the_allocated_run_are_untouched(self, api):
        """The compensation is partial: f2's verdict and the ledger both survive.

        PRD S3.8: "`RELEASED` is terminal for an assignment: a released
        assignment is never revived, and a fresh assignment must be made if the
        finding is to be expert-reviewed again."

        Design: Difficulty/compensating_invariant/verification_revocation_preserves_the_finding_count_partition
        """
        world = _revocation_world(api)
        _revoke(api, world["first"]["id"])

        sibling = X.read_finding(api, world["second"]["id"])
        assert sibling["verification_status"] == C.FIND_SME_CONFIRMED
        assert sibling["matched_page"] == 9

        sibling_assignment = _read_assignment(api, world["second_assignment"]["id"])
        assert sibling_assignment["status"] == C.ASSIGN_COMPLETED
        assert sibling_assignment["verdict"] == C.VERDICT_CONFIRMED

        run = X.read_run(api, world["run"]["id"])
        assert run["code_review_status"] == C.REVIEW_APPROVED
        assert run["cost_allocation_status"] == C.ALLOC_ALLOCATED
        assert run["allocated_total_cents"] == 11500
        assert X.read_dataset(api, world["dataset"]["id"])["allocated_cost_cents"] == 11500


class TestReviewerConflictOutranksReviewerCapacity:
    """The two assignment gates of PRD S3.8, in their declared order."""

    def test_a_candidate_violating_both_gates_reports_the_conflict(self, api):
        """Conflict of interest answers even though capacity is also exhausted.

        PRD S3.8: "**Conflict of interest is checked first.** An expert may not
        review a finding whose investigation draws on agency data they are
        conflicted with: if any dataset of the finding's investigation was
        acquired under a records request whose `agency_id` appears in the
        reviewer's `conflict_of_interest_agency_ids`, the assignment is refused
        with `ERR_REVIEWER_CONFLICT_OF_INTEREST`."

        Design: Difficulty/priority_pair_validation_conflict/reviewer_conflict_priority_150_beats_capacity_priority_200
        """
        world = _conflict_world(api)
        response = api.create_review_assignment(
            F.review_assignment_payload(
                world["reviewer"]["id"],
                world["conflicted_finding"]["id"],
                "2026-09-04T00:00:00Z",
                "2026-09-06T00:00:00Z",
            ),
            editor_headers(),
        )
        validate_error(response, ERR_REVIEWER_CONFLICT_OF_INTEREST)
        assert (
            _read_reviewer(api, world["reviewer"]["id"])["active_assignment_count"]
            == 2
        )

    def test_the_non_conflicted_control_reports_the_capacity_refusal(self, api):
        """The same window on a clean investigation reaches the capacity gate.

        PRD S3.8: "The system counts how many of the reviewer's existing
        assignments in `ASSIGNED` status overlap the candidate window; if that
        count plus one is strictly greater than the reviewer's
        `max_concurrent_assignments`, the assignment is refused with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/reviewer_conflict_priority_150_beats_capacity_priority_200
        """
        world = _conflict_world(api)
        response = api.create_review_assignment(
            F.review_assignment_payload(
                world["reviewer"]["id"],
                world["clean_findings"][2]["id"],
                "2026-09-04T00:00:00Z",
                "2026-09-06T00:00:00Z",
            ),
            editor_headers(),
        )
        validate_error(response, ERR_REVIEWER_CAPACITY_EXCEEDED)
        assert (
            _read_reviewer(api, world["reviewer"]["id"])["active_assignment_count"]
            == 2
        )

    def test_neither_refusal_moved_an_assignment_or_a_finding(self, api):
        """Both refusals are total: no row, no counter and no bucket moved.

        PRD S3.8: "A successful assignment opens in `ASSIGNED` with `verdict` and
        `rationale` null, and increments the reviewer's `active_assignment_count`
        and `version` by 1."

        Design: Difficulty/priority_pair_validation_conflict/reviewer_conflict_priority_150_beats_capacity_priority_200
        """
        world = _conflict_world(api)
        validate_error(
            api.create_review_assignment(
                F.review_assignment_payload(
                    world["reviewer"]["id"],
                    world["conflicted_finding"]["id"],
                    "2026-09-04T00:00:00Z",
                    "2026-09-06T00:00:00Z",
                ),
                editor_headers(),
            ),
            ERR_REVIEWER_CONFLICT_OF_INTEREST,
        )
        validate_error(
            api.create_review_assignment(
                F.review_assignment_payload(
                    world["reviewer"]["id"],
                    world["clean_findings"][2]["id"],
                    "2026-09-04T00:00:00Z",
                    "2026-09-06T00:00:00Z",
                ),
                editor_headers(),
            ),
            ERR_REVIEWER_CAPACITY_EXCEEDED,
        )

        assert (
            _read_assignment(api, world["first_assignment"]["id"])["status"]
            == C.ASSIGN_ASSIGNED
        )
        assert (
            _read_assignment(api, world["second_assignment"]["id"])["status"]
            == C.ASSIGN_ASSIGNED
        )
        assert (
            X.read_finding(api, world["conflicted_finding"]["id"])[
                "verification_status"
            ]
            == C.FIND_UNVERIFIED
        )
        assert (
            X.read_finding(api, world["clean_findings"][2]["id"])[
                "verification_status"
            ]
            == C.FIND_UNVERIFIED
        )


class TestReviewerClosedWindowAggregateCapacity:
    """PRD S3.8's touching-endpoint worked example, to the millisecond."""

    def test_a_candidate_starting_at_an_existing_window_end_still_overlaps(
        self, api
    ):
        """The closed endpoint counts, so the overlap count is two and it refuses.

        PRD S3.8: "a candidate window from `2026-09-05T00:00:00Z` to
        `2026-09-06T00:00:00Z` overlaps both -- the first only by the touching
        closed endpoint -- giving a count of two, and two plus one exceeds two, so
        it is refused".

        Design: Difficulty/resource_temporal_overlap/reviewer_closed_window_aggregate_capacity_at_the_touching_endpoint
        """
        world = _capacity_world(api)
        response = api.create_review_assignment(
            F.review_assignment_payload(
                world["reviewer"]["id"],
                world["findings"][2]["id"],
                "2026-09-05T00:00:00Z",
                "2026-09-06T00:00:00Z",
            ),
            editor_headers(),
        )
        validate_error(response, ERR_REVIEWER_CAPACITY_EXCEEDED)
        assert (
            _read_reviewer(api, world["reviewer"]["id"])["active_assignment_count"]
            == 2
        )

    def test_nudging_the_start_by_one_millisecond_is_accepted(self, api):
        """One millisecond later only the second window overlaps.

        PRD S3.8: "nudging the candidate start forward by a single millisecond to
        `2026-09-05T00:00:00.001Z` overlaps only the second, giving one, and one
        plus one does not exceed two, so it is accepted".

        Design: Difficulty/resource_temporal_overlap/reviewer_closed_window_aggregate_capacity_at_the_touching_endpoint
        """
        world = _capacity_world(api)
        created = validate_created(
            api.create_review_assignment(
                F.review_assignment_payload(
                    world["reviewer"]["id"],
                    world["findings"][2]["id"],
                    "2026-09-05T00:00:00.001Z",
                    "2026-09-06T00:00:00Z",
                ),
                editor_headers(),
            )
        )
        assert created["status"] == C.ASSIGN_ASSIGNED
        assert_field_absent_or_null(created, "verdict", "new assignment")
        assert_instant_equals(
            created["window_start"],
            "2026-09-05T00:00:00.001Z",
            "nudged window_start",
        )

    def test_the_ceiling_bounds_overlap_not_the_reviewers_total(self, api):
        """Three live assignments coexist under a ceiling of two.

        PRD S3.8: "An assignment occupies the **closed** interval running from
        `window_start` to `window_end` with **both endpoints inclusive**, and two
        assignments overlap when the first one's start is at or before the second
        one's end and the second one's start is at or before the first one's end
        -- so windows that merely touch at an endpoint do overlap."

        Design: Difficulty/resource_temporal_overlap/reviewer_closed_window_aggregate_capacity_at_the_touching_endpoint
        """
        world = _capacity_world(api)
        validate_created(
            api.create_review_assignment(
                F.review_assignment_payload(
                    world["reviewer"]["id"],
                    world["findings"][2]["id"],
                    "2026-09-05T00:00:00.001Z",
                    "2026-09-06T00:00:00Z",
                ),
                editor_headers(),
            )
        )
        reviewer = _read_reviewer(api, world["reviewer"]["id"])
        assert reviewer["active_assignment_count"] == 3
        assert reviewer["max_concurrent_assignments"] == 2
        assert (
            _read_assignment(api, world["first_assignment"]["id"])["status"]
            == C.ASSIGN_ASSIGNED
        )
        assert (
            _read_assignment(api, world["second_assignment"]["id"])["status"]
            == C.ASSIGN_ASSIGNED
        )


def _two_finding_world(api, matched_pages=None):
    """One investigation, one run and two findings, optionally document-matched."""
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api, retention_policy_days=365)
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Side effect probe"
    )
    run = X.create_run(
        api, investigation["id"], compute_cost_cents=1000, labor_hours=1.0
    )
    if matched_pages is None:
        findings = [
            X.create_finding(
                api, investigation["id"], run["id"], claim_text=f"Finding {label}."
            )
            for label in ("one", "two")
        ]
    else:
        findings = [
            X.doc_matched_finding(
                api,
                investigation["id"],
                run["id"],
                matched_page=page,
                claim_text=f"Finding {label}.",
            )
            for page, label in zip(matched_pages, ("one", "two"))
        ]
    return {
        "desk": desk,
        "investigation": investigation,
        "run": run,
        "findings": findings,
    }


class TestDocumentMatchAppliesEverySideEffect:
    """The ``UNVERIFIED -> DOC_MATCHED`` transition of PRD S3.8."""

    def test_the_match_records_the_reference_and_advances_the_finding(self, api):
        """The matched document reference, page and version all land together.

        PRD S3.8: "Matching a finding records the `source_document_ref` (1 to 200
        non-blank characters) identifying the document the claim was checked
        against and the `matched_page` it was found on, and drives `UNVERIFIED ->
        DOC_MATCHED`."

        Design: Corner/state_machines/document_match_applies_every_declared_side_effect_of_the_transition
        """
        world = _two_finding_world(api)
        matched = validate_ok(
            api.match_document(
                world["findings"][0]["id"],
                F.document_match_payload(
                    7, source_document_ref="BOX-14/DOC-0231"
                ),
                reporter_headers(),
            )
        )
        assert matched["verification_status"] == C.FIND_DOC_MATCHED
        assert matched["source_document_ref"] == "BOX-14/DOC-0231"
        assert matched["matched_page"] == 7
        assert_version_is(matched, 2, "matched finding")

    def test_the_investigation_moves_one_unit_and_bumps_its_version(self, api):
        """The unit leaves ``unverified`` for ``doc_matched`` and readiness holds off.

        PRD S3.8: "The finding's unit moves out of `unverified_finding_count` and
        into `doc_matched_finding_count`, readiness is recomputed, and the
        finding's and investigation's `version` each increment by 1."

        Design: Corner/state_machines/document_match_applies_every_declared_side_effect_of_the_transition
        """
        world = _two_finding_world(api)
        before = X.read_investigation(api, world["investigation"]["id"])
        validate_ok(
            api.match_document(
                world["findings"][0]["id"],
                F.document_match_payload(
                    7, source_document_ref="BOX-14/DOC-0231"
                ),
                reporter_headers(),
            )
        )
        after = X.read_investigation(api, world["investigation"]["id"])
        assert_partition_counts(after, 2, 1, 1, 0, 0)
        assert after["analysis_readiness"] == C.READINESS_NOT_READY
        assert_version_is(after, before["version"] + 1, "investigation")

    def test_the_sibling_finding_and_the_run_are_left_alone(self, api):
        """The transition touches exactly one finding and no run at all.

        PRD S3.8: "Every finding begins life with `verification_status` at
        `UNVERIFIED`, `matched_page` and `sme_verdict_rationale` null".

        Design: Corner/state_machines/document_match_applies_every_declared_side_effect_of_the_transition
        """
        world = _two_finding_world(api)
        validate_ok(
            api.match_document(
                world["findings"][0]["id"],
                F.document_match_payload(
                    7, source_document_ref="BOX-14/DOC-0231"
                ),
                reporter_headers(),
            )
        )
        sibling = X.read_finding(api, world["findings"][1]["id"])
        assert sibling["verification_status"] == C.FIND_UNVERIFIED
        assert_field_absent_or_null(sibling, "matched_page", "sibling finding")
        assert_version_is(sibling, 1, "sibling finding")
        assert (
            X.read_run(api, world["run"]["id"])["code_review_status"]
            == C.REVIEW_PENDING
        )


def _verdict_world(api):
    """Two document-matched findings, both assigned to one reviewer."""
    world = _two_finding_world(api, matched_pages=(2, 5))
    reviewer = X.create_reviewer(api)
    world["reviewer"] = reviewer
    world["assignments"] = [
        X.assign_review(
            api,
            reviewer["id"],
            finding["id"],
            "2026-09-01T00:00:00Z",
            "2026-09-10T00:00:00Z",
        )
        for finding in world["findings"]
    ]
    return world


_VERDICT_RATIONALE = "Both tables reconcile with the certified source pages."


class TestExpertVerdictAdjustsThreeEntitiesTogether:
    """One verdict moves the assignment, the finding and the investigation."""

    def test_the_verdict_completes_the_assignment_and_copies_the_rationale(
        self, api
    ):
        """The rationale is stored on the assignment and copied onto the finding.

        PRD S3.8: "`CONFIRMED` drives the finding `DOC_MATCHED -> SME_CONFIRMED`,
        moves its unit from `doc_matched_finding_count` to
        `sme_confirmed_finding_count`, and copies the `rationale` into the
        finding's `sme_verdict_rationale`".

        Design: Corner/state_machines/expert_verdict_adjusts_the_finding_the_reviewer_and_the_investigation_together
        """
        world = _verdict_world(api)
        completed = _confirm(
            api,
            world["assignments"][0]["id"],
            world["reviewer"]["id"],
            _VERDICT_RATIONALE,
        )
        assert completed["status"] == C.ASSIGN_COMPLETED
        assert completed["verdict"] == C.VERDICT_CONFIRMED
        assert completed["rationale"] == _VERDICT_RATIONALE

        finding = X.read_finding(api, world["findings"][0]["id"])
        assert finding["verification_status"] == C.FIND_SME_CONFIRMED
        assert finding["sme_verdict_rationale"] == _VERDICT_RATIONALE

    def test_completing_an_assignment_frees_real_window_capacity(self, api):
        """The decrement is genuine: a third overlapping window is admitted.

        PRD S3.8: "Recording the verdict moves the assignment `ASSIGNED ->
        COMPLETED`, stores the `verdict` and `rationale`, and decrements the
        reviewer's `active_assignment_count` by 1, freeing window capacity."

        Design: Corner/state_machines/expert_verdict_adjusts_the_finding_the_reviewer_and_the_investigation_together
        """
        world = _verdict_world(api)
        _confirm(
            api,
            world["assignments"][0]["id"],
            world["reviewer"]["id"],
            _VERDICT_RATIONALE,
        )
        assert (
            _read_reviewer(api, world["reviewer"]["id"])["active_assignment_count"]
            == 1
        )
        replacement = validate_created(
            api.create_review_assignment(
                F.review_assignment_payload(
                    world["reviewer"]["id"],
                    world["findings"][0]["id"],
                    "2026-09-01T00:00:00Z",
                    "2026-09-10T00:00:00Z",
                ),
                editor_headers(),
            )
        )
        assert replacement["status"] == C.ASSIGN_ASSIGNED

    def test_the_investigation_partition_moves_and_the_sibling_waits(self, api):
        """One confirmed and one still merely matched keeps readiness off.

        PRD S3.7: "`analysis_readiness` is `READY` when **all seven** of the
        following hold: a current run exists; that current run's
        `code_review_status` is `APPROVED`; its `cost_allocation_status` is
        `ALLOCATED`; `sme_confirmed_finding_count` is at least 1;
        `sme_disputed_finding_count` is 0; `unverified_finding_count` is 0; and
        `doc_matched_finding_count` is 0."

        Design: Corner/state_machines/expert_verdict_adjusts_the_finding_the_reviewer_and_the_investigation_together
        """
        world = _verdict_world(api)
        _confirm(
            api,
            world["assignments"][0]["id"],
            world["reviewer"]["id"],
            _VERDICT_RATIONALE,
        )
        investigation = X.read_investigation(api, world["investigation"]["id"])
        assert_partition_counts(investigation, 2, 0, 1, 1, 0)
        assert investigation["analysis_readiness"] == C.READINESS_NOT_READY
        assert (
            _read_assignment(api, world["assignments"][1]["id"])["status"]
            == C.ASSIGN_ASSIGNED
        )


def _junction_world(api):
    """Two reviewers and two findings, ready to be wired three ways."""
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    investigation = X.create_investigation(
        api, desk["id"], C.MODE_METHODOLOGY_ONLY, headline="Junction probe"
    )
    run = X.create_run(
        api, investigation["id"], compute_cost_cents=1000, labor_hours=1.0
    )
    findings = [
        X.create_finding(
            api, investigation["id"], run["id"], claim_text=f"Finding {label}."
        )
        for label in ("one", "two")
    ]
    first_reviewer = X.create_reviewer(api)
    second_reviewer = X.create_reviewer(
        api,
        name="Dr. Beto Cruz",
        affiliation="City Policy Institute",
        expertise_code="STATISTICS",
        max_concurrent_assignments=F.OMIT,
    )
    return {
        "investigation": investigation,
        "findings": findings,
        "first_reviewer": first_reviewer,
        "second_reviewer": second_reviewer,
    }


def _wire_junction(api, world):
    """Assign f1 and f2 to reviewer one, then f1 to reviewer two as well."""
    return [
        validate_created(
            api.create_review_assignment(
                F.review_assignment_payload(
                    reviewer["id"],
                    finding["id"],
                    "2026-09-01T00:00:00Z",
                    "2026-09-05T00:00:00Z",
                ),
                editor_headers(),
            )
        )
        for reviewer, finding in (
            (world["first_reviewer"], world["findings"][0]),
            (world["first_reviewer"], world["findings"][1]),
            (world["second_reviewer"], world["findings"][0]),
        )
    ]


class TestReviewAssignmentJunctionTraversesBothWays:
    """``ReviewAssignment`` is the many-to-many join of PRD S3.8."""

    def test_all_three_assignments_open_in_assigned_with_no_verdict(self, api):
        """The second assignment fits because one overlap plus one is not over two.

        PRD S3.8: "A successful assignment opens in `ASSIGNED` with `verdict` and
        `rationale` null, and increments the reviewer's `active_assignment_count`
        and `version` by 1."

        Design: Corner/entities/review_assignment_junction_links_reviewers_and_findings_both_ways
        """
        world = _junction_world(api)
        for assignment in _wire_junction(api, world):
            assert assignment["status"] == C.ASSIGN_ASSIGNED
            assert_field_absent_or_null(assignment, "verdict", "new assignment")
            assert_field_absent_or_null(assignment, "rationale", "new assignment")

    def test_the_junction_is_filterable_from_either_side(self, api):
        """One reviewer sees two findings; one finding sees two reviewers.

        PRD S4: "List review assignments, filterable by `reviewer_id`,
        `finding_id` and `status`."

        Design: Corner/entities/review_assignment_junction_links_reviewers_and_findings_both_ways
        """
        world = _junction_world(api)
        first, second, third = _wire_junction(api, world)

        by_reviewer, reviewer_meta = validate_paginated_page(
            api.list_review_assignments(
                editor_headers(), {"reviewer_id": world["first_reviewer"]["id"]}
            )
        )
        assert reviewer_meta["total_count"] == 2
        assert {row["id"] for row in by_reviewer} == {first["id"], second["id"]}

        by_finding, finding_meta = validate_paginated_page(
            api.list_review_assignments(
                editor_headers(), {"finding_id": world["findings"][0]["id"]}
            )
        )
        assert finding_meta["total_count"] == 2
        assert {row["id"] for row in by_finding} == {first["id"], third["id"]}

    def test_each_reviewer_counts_only_its_own_assignments(self, api):
        """Two live rows for one reviewer, one for the other, no bucket moved.

        PRD S3.8: "Every finding begins life with `verification_status` at
        `UNVERIFIED`, `matched_page` and `sme_verdict_rationale` null, and the
        investigation's `finding_count` and `unverified_finding_count` each
        increment by 1".

        Design: Corner/entities/review_assignment_junction_links_reviewers_and_findings_both_ways
        """
        world = _junction_world(api)
        _wire_junction(api, world)

        assert (
            _read_reviewer(api, world["first_reviewer"]["id"])[
                "active_assignment_count"
            ]
            == 2
        )
        assert (
            _read_reviewer(api, world["second_reviewer"]["id"])[
                "active_assignment_count"
            ]
            == 1
        )
        investigation = X.read_investigation(api, world["investigation"]["id"])
        assert investigation["finding_count"] == 2
        assert investigation["unverified_finding_count"] == 2


def _identity_world(api):
    """An allocated run authored by ``rep-001`` and an assignment held by one expert.

    ``expertise_code`` is ``STATISTICS``: PRD S3.8 admits only ``HOUSING``,
    ``PUBLIC_HEALTH``, ``POLICING``, ``PROCUREMENT`` and ``STATISTICS``.
    """
    X.set_clock(api, C.STD_CLOCK)
    desk = X.create_desk(api)
    agency = X.create_agency(
        api,
        name="City Payroll Office",
        jurisdiction_code="CA-PAY",
        tolling_allowed=False,
        appeal_venue=C.VENUE_INTERNAL,
        appeal_decision_days=15,
        holiday_dates=F.OMIT,
    )
    request = X.released_request(
        api,
        desk["id"],
        agency["id"],
        subject_summary="Payroll ghost shifts",
        estimated_page_count=50,
        waiver_requested=False,
        public_interest_score=60,
    )
    investigation = X.create_investigation(
        api,
        desk["id"],
        C.MODE_METHODOLOGY_ONLY,
        headline="Ghost shifts in the payroll file",
    )
    X.clean_locked_dataset(
        api,
        request["id"],
        investigation["id"],
        record_count=400,
        field_specs=[{"field_name": "shift_code", "reidentification_risk": 2}],
        sensitivity_tier="RESTRICTED",
    )
    run = X.create_run(
        api,
        investigation["id"],
        compute_cost_cents=5000,
        labor_hours=1.0,
        headers=reporter_headers(),
    )
    validate_ok(api.allocate_cost(run["id"], reporter_headers()))
    finding = X.doc_matched_finding(
        api,
        investigation["id"],
        run["id"],
        matched_page=4,
        claim_text="Shifts were paid with no clock-in record.",
    )
    first_reviewer = X.create_reviewer(
        api,
        affiliation="Public Payroll Institute",
        expertise_code="STATISTICS",
    )
    second_reviewer = X.create_reviewer(
        api,
        name="Dr. Ivan Petrov",
        affiliation="Municipal Finance Lab",
        expertise_code="STATISTICS",
    )
    assignment = X.assign_review(
        api,
        first_reviewer["id"],
        finding["id"],
        "2026-08-05T00:00:00Z",
        "2026-08-10T00:00:00Z",
    )
    return {
        "run": run,
        "finding": finding,
        "first_reviewer": first_reviewer,
        "second_reviewer": second_reviewer,
        "assignment": assignment,
    }


class TestPeerReviewAndVerdictAreBoundToIdentities:
    """Holding the role is not enough: PRD S2.1 compares the caller's own id."""

    def test_the_author_cannot_peer_review_their_own_run(self, api):
        """The ``PeerReviewer`` role is allowed; the author's identity is not.

        PRD S2.1: "a peer review submitted by the same `X-User-ID` that is
        recorded as the run's `authored_by_user_id` is refused with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even though the caller holds the
        `PeerReviewer` role."

        Design: Corner/rbac/peer_review_and_verdict_are_bound_to_identities_not_just_to_roles
        """
        world = _identity_world(api)
        response = api.submit_peer_review(
            world["run"]["id"],
            F.peer_review_payload(
                C.REVIEW_APPROVED,
                peer_review_note="Self-approval attempt by the author.",
            ),
            peer_reviewer_headers(U.REPORTER_ID),
        )
        validate_error(response, ERR_SEGREGATION_OF_DUTIES)

        run = X.read_run(api, world["run"]["id"])
        assert run["code_review_status"] == C.REVIEW_PENDING
        assert run["review_cycle_count"] == 0
        assert_field_absent_or_null(run, "reviewed_by_user_id", "unreviewed run")

    def test_a_different_peer_approves_and_a_second_peer_is_then_refused(
        self, api
    ):
        """The approving identity is recorded, and an approved run closes.

        PRD S3.7: "Either decision increments `review_cycle_count` by 1 and
        records `peer_review_note` and `reviewed_by_user_id` from `X-User-ID`;
        both decisions leave `cost_allocation_status` completely untouched".

        Design: Corner/rbac/peer_review_and_verdict_are_bound_to_identities_not_just_to_roles
        """
        world = _identity_world(api)
        approved = validate_ok(
            api.submit_peer_review(
                world["run"]["id"],
                F.peer_review_payload(
                    C.REVIEW_APPROVED,
                    peer_review_note="Reproduced from the pinned digest.",
                ),
                peer_reviewer_headers(U.PEER_REVIEWER_ID),
            )
        )
        assert approved["code_review_status"] == C.REVIEW_APPROVED
        assert approved["review_cycle_count"] == 1
        assert approved["reviewed_by_user_id"] == U.PEER_REVIEWER_ID
        assert approved["cost_allocation_status"] == C.ALLOC_ALLOCATED

        validate_error(
            api.submit_peer_review(
                world["run"]["id"],
                F.peer_review_payload(
                    C.REVIEW_CHANGES_REQUESTED,
                    peer_review_note="Second reviewer attempts to reopen.",
                ),
                peer_reviewer_headers(U.PEER_REVIEWER_ALT_ID),
            ),
            ERR_INVALID_RUN_STATE,
        )
        run = X.read_run(api, world["run"]["id"])
        assert run["code_review_status"] == C.REVIEW_APPROVED
        assert run["review_cycle_count"] == 1
        assert run["reviewed_by_user_id"] == U.PEER_REVIEWER_ID

    def test_only_the_named_reviewer_may_return_the_verdict(self, api):
        """The second expert holds the role but not this assignment.

        PRD S3.8: "a caller whose `X-User-ID` is not the assignment's
        `reviewer_id` is refused with `ERR_ASSIGNMENT_NOT_OWNED`, ahead of any
        state check."

        Design: Corner/rbac/peer_review_and_verdict_are_bound_to_identities_not_just_to_roles
        """
        world = _identity_world(api)
        response = api.submit_verdict(
            world["assignment"]["id"],
            F.verdict_payload(
                C.VERDICT_CONFIRMED, rationale="Verdict from the wrong reviewer."
            ),
            expert_reviewer_headers(world["second_reviewer"]["id"]),
        )
        validate_error(response, ERR_ASSIGNMENT_NOT_OWNED)

        assignment = _read_assignment(api, world["assignment"]["id"])
        assert assignment["status"] == C.ASSIGN_ASSIGNED
        assert_field_absent_or_null(assignment, "verdict", "unowned assignment")
        assert (
            X.read_finding(api, world["finding"]["id"])["verification_status"]
            == C.FIND_DOC_MATCHED
        )

    def test_the_named_reviewer_succeeds_and_the_other_row_never_moved(self, api):
        """The refused verdict touched no counter on the refused caller's own row.

        PRD S3.8: "Recording the verdict moves the assignment `ASSIGNED ->
        COMPLETED`, stores the `verdict` and `rationale`, and decrements the
        reviewer's `active_assignment_count` by 1, freeing window capacity."

        Design: Corner/rbac/peer_review_and_verdict_are_bound_to_identities_not_just_to_roles
        """
        world = _identity_world(api)
        validate_error(
            api.submit_verdict(
                world["assignment"]["id"],
                F.verdict_payload(
                    C.VERDICT_CONFIRMED,
                    rationale="Verdict from the wrong reviewer.",
                ),
                expert_reviewer_headers(world["second_reviewer"]["id"]),
            ),
            ERR_ASSIGNMENT_NOT_OWNED,
        )
        completed = _confirm(
            api,
            world["assignment"]["id"],
            world["first_reviewer"]["id"],
            "Matches the clock-in extracts.",
        )
        assert completed["status"] == C.ASSIGN_COMPLETED
        assert (
            X.read_finding(api, world["finding"]["id"])["verification_status"]
            == C.FIND_SME_CONFIRMED
        )
        assert (
            _read_reviewer(api, world["first_reviewer"]["id"])[
                "active_assignment_count"
            ]
            == 0
        )

        untouched = _read_reviewer(api, world["second_reviewer"]["id"])
        assert untouched["active_assignment_count"] == 0
        assert_version_is(untouched, 1, "refused reviewer")
