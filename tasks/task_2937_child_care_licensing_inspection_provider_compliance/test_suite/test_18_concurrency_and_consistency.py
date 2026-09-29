"""Optimistic concurrency on the two guarded writes, and immediate consistency.

Both guards protect a write whose own success advances the very counter it read,
so each case shows the stale attempt refused, the re-read, and the retry landing.
"""

from test_helpers import (
    CODE_RATIO,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_point_ledger,
    assert_points,
    assert_score,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PRESCHOOL_ONLY = ["PRESCHOOL"]
VISIT_INSTANT = "2026-08-10T09:00:00Z"


class TestTheAmendmentGuardReadsTheProviderRevision:
    """§3.9: "the very version the client just supplied is stale for its next
    request"."""

    def test_a_staff_attachment_invalidates_the_version_an_amendment_was_built_on(
        self, api
    ):
        """Attaching a person silently advances the provider, so the amendment built
        on the earlier read is refused before any supersede can happen, and the
        re-read version carries the identical request through.

        PRD §3.9: "As with plans, superseding happens only after the concurrency
        guard passes. Creation stamps `submitted_at`, leaves `decided_at`,
        `decision_rationale` and `pre_move_inspection_id` null, and increments the
        provider's `version`"

        Design: Corner/cross_cutting_complexity_layers/occ_amendment_create_carries_a_stale_provider_version
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        applicant = make_applicant_headers(provider["id"])
        first_read = validate_success(
            api.get_provider(provider["id"], headers=applicant)
        )
        assert first_read["version"] == 1

        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        second_read = validate_success(
            api.get_provider(provider["id"], headers=applicant)
        )
        assert second_read["version"] == 2, (
            "the attachment recomputed clearance_complete and advanced the row"
        )

        stale = f.amendment_payload(
            provider["id"],
            "DIRECTOR_CHANGE",
            expected_provider_version=first_read["version"],
            new_director_staff_member_id=director["id"],
        )
        validate_error(
            api.create_amendment(stale, headers=applicant),
            "ERR_STALE_PROVIDER_VERSION",
            412,
        )
        _rows, meta = validate_paginated(
            api.list_amendments(headers=applicant, provider_id=provider["id"])
        )
        assert meta["total_count"] == 0, "the refused create wrote no amendment"
        after_refusal = validate_success(
            api.get_provider(provider["id"], headers=applicant)
        )
        assert after_refusal["version"] == second_read["version"], (
            "a refused write never advances the row it guards"
        )

        accepted = validate_success(
            api.create_amendment(
                f.amendment_payload(
                    provider["id"],
                    "DIRECTOR_CHANGE",
                    expected_provider_version=second_read["version"],
                    new_director_staff_member_id=director["id"],
                ),
                headers=applicant,
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED"
        assert accepted["requires_inspection"] is False, "a director change needs no visit"
        assert accepted["effective_capacity_delta"] == 0
        assert accepted["decided_at"] is None
        assert accepted["pre_move_inspection_id"] is None
        assert_instant(accepted["submitted_at"], DEFAULT_LOGICAL_CLOCK, "submitted_at")

        final_read = validate_success(
            api.get_provider(provider["id"], headers=applicant)
        )
        assert final_read["version"] == second_read["version"] + 1, (
            "the accepted create bumps the provider once more"
        )


class TestThePlanGuardReadsTheInspectionRevision:
    """§3.6: "a stale submission supersedes nothing"."""

    def test_the_first_plan_invalidates_the_version_the_second_was_built_on(
        self, api, catalog
    ):
        """Submitting a plan is itself a write on the parent visit, so the revised
        plan carrying the pre-plan version is refused, and only the re-read version
        lets it land and supersede its predecessor.

        PRD §3.6: "A successful creation also increments the inspection's `version`,
        which means a client holding the version it just used cannot immediately
        reuse it."

        Design: Corner/cross_cutting_complexity_layers/occ_cap_submission_carries_a_stale_inspection_version
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        applicant = make_applicant_headers(provider["id"])
        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        fx.clear_person(api, director["id"])
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_RATIO],
            primary_age_group="PRESCHOOL",
            narrative="One aide for fourteen preschoolers.",
        )
        fx.submit_findings(api, inspection["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY)
        finalized = fx.finalize_visit(api, inspection["id"])
        assert finalized["cap_required"] is True
        cited = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert cited["status"] == "CORRECTION_PENDING"
        assert_instant(
            cited["correction_due_date"], "2026-08-20T09:00:00Z", "correction_due_date"
        )
        version_before_plans = finalized["version"]

        first_plan = validate_success(
            api.create_cap(
                f.cap_payload(
                    inspection["id"],
                    [violation["id"]],
                    expected_inspection_version=version_before_plans,
                    narrative="Hire one additional preschool aide.",
                    proposed_completion_date="2026-08-18",
                ),
                headers=applicant,
            ),
            201,
        )
        assert first_plan["status"] == "SUBMITTED"
        assert first_plan["review_cycle_count"] == 1
        assert first_plan["provider_id"] == provider["id"]
        assert_instant(first_plan["due_at"], "2026-08-20T09:00:00Z", "due_at")

        revised = f.cap_payload(
            inspection["id"],
            [violation["id"]],
            expected_inspection_version=version_before_plans,
            narrative="Revised plan: reassign the floating aide.",
            proposed_completion_date="2026-08-19",
        )
        validate_error(
            api.create_cap(revised, headers=applicant),
            "ERR_STALE_INSPECTION_VERSION",
            412,
        )
        _rows, meta = validate_paginated(
            api.list_caps(headers=applicant, inspection_id=inspection["id"])
        )
        assert meta["total_count"] == 1, "the stale submission created nothing"
        untouched = validate_success(
            api.get_cap(first_plan["id"], headers=applicant)
        )
        assert untouched["status"] == "SUBMITTED", "a stale submission supersedes nothing"

        reread = validate_success(
            api.get_inspection(inspection["id"], headers=applicant)
        )
        assert reread["version"] == version_before_plans + 1

        second_plan = validate_success(
            api.create_cap(
                f.cap_payload(
                    inspection["id"],
                    [violation["id"]],
                    expected_inspection_version=reread["version"],
                    narrative="Revised plan: reassign the floating aide.",
                    proposed_completion_date="2026-08-19",
                ),
                headers=applicant,
            ),
            201,
        )
        assert second_plan["status"] == "SUBMITTED"
        assert second_plan["review_cycle_count"] == 1
        superseded = validate_success(
            api.get_cap(first_plan["id"], headers=applicant)
        )
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == first_plan["version"] + 1
        after = validate_success(
            api.get_inspection(inspection["id"], headers=applicant)
        )
        assert after["version"] == reread["version"] + 1


class TestOneWriteSettlesEveryRowItTouches:
    """§2.10: "no deferred jobs and no eventual consistency"."""

    def test_the_finalize_body_agrees_with_every_later_read(self, api, catalog):
        """Finalization recomputes scores on the visit, a deadline on the citation
        and five counters on the provider, and all of them are already settled in
        the response body — the following reads only confirm them.

        PRD §3.4: "`preliminary_compliance_score` is computed and **frozen
        forever**; `final_compliance_score` and `raw_deduction_points` are computed;
        the provider's `open_violation_points`, `resolved_violation_points`,
        `lifetime_violation_points`, `critical_open_count` and
        `critical_violation_count_24mo` are recomputed; the provider's `risk_score`
        and `risk_tier` are recomputed under the enforcement-review weighting"

        Design: Corner/consistency_model/consistency_immediate_finalize_response_already_carries_every_derivation
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        director = fx.attach_staff(
            api,
            provider["id"],
            full_name="Dana Reed",
            member_type="DIRECTOR",
            date_of_birth="1985-04-02",
            qualified_age_groups=PRESCHOOL_ONLY,
            role_title="Director",
        )
        fx.clear_person(api, director["id"])
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        inspection = fx.schedule_visit(
            api,
            provider["id"],
            inspector["id"],
            VISIT_INSTANT,
            inspection_type="ANNUAL",
            target_age_groups=PRESCHOOL_ONLY,
        )
        fx.set_clock(api, VISIT_INSTANT)
        fx.start_visit(api, inspection["id"], inspector["id"])
        violation = fx.cite(
            api,
            inspection["id"],
            inspector["id"],
            catalog[CODE_SUPERVISION],
            primary_age_group="PRESCHOOL",
            narrative="Nap room left unattended for twenty minutes.",
        )
        assert_points(violation["assessed_points"], 15, "assessed_points")
        pending = fx.submit_findings(
            api, inspection["id"], inspector["id"], "FAIL", PRESCHOOL_ONLY
        )
        assert pending["status"] == "PENDING_REVIEW"

        finalized = validate_success(
            api.finalize_inspection(inspection["id"], headers=supervisor_headers())
        )
        assert_score(finalized["raw_deduction_points"], 15.00, "raw_deduction_points")
        assert_score(finalized["preliminary_compliance_score"], 85.00, "preliminary")
        assert_score(finalized["final_compliance_score"], 85.00, "final")
        assert finalized["violation_count"] == 1
        assert finalized["cap_required"] is True, (
            "the same body already says a plan is owed"
        )
        assert_instant(finalized["finalized_at"], VISIT_INSTANT, "finalized_at")

        reread = validate_success(
            api.get_inspection(inspection["id"], headers=supervisor_headers())
        )
        assert_score(
            reread["final_compliance_score"],
            finalized["final_compliance_score"],
            "final on re-read",
        )
        assert_score(
            reread["preliminary_compliance_score"],
            finalized["preliminary_compliance_score"],
            "preliminary on re-read",
        )
        assert reread["violation_count"] == finalized["violation_count"]

        settled_violation = validate_success(
            api.get_violation(violation["id"], headers=supervisor_headers())
        )
        assert settled_violation["status"] == "CORRECTION_PENDING", (
            "the cited row settled inside the finalize request"
        )
        assert_instant(
            settled_violation["correction_due_date"],
            "2026-08-13T09:00:00Z",
            "correction_due_date",
        )

        settled_provider = validate_success(
            api.get_provider(provider["id"], headers=supervisor_headers())
        )
        assert_point_ledger(settled_provider, 15, 0, 15)
        assert settled_provider["critical_open_count"] == 1
        assert settled_provider["critical_violation_count_24mo"] == 1
        assert_score(settled_provider["risk_score"], 25.00, "risk_score")
        assert settled_provider["risk_tier"] == "MODERATE", (
            "15 open points plus the flat 10 for a recent critical bands at MODERATE"
        )
