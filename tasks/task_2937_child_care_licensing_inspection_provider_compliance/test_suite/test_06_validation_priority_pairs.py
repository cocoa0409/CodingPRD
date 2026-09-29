"""Requests that break two rules at once, where only the earlier rule may be
reported (PRD §1.5 validation order).

Each pair is then separated: the earlier violation is repaired or stepped over,
the payload is otherwise unchanged, and the later rule surfaces on its own.
"""

from test_helpers import (
    CODE_RATIO,
    DEFAULT_LOGICAL_CLOCK,
    assert_instant,
    assert_score,
    factories as f,
    fixtures as fx,
    make_applicant_headers,
    make_inspector_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

def _uncleared_provider_with_a_scheduled_initial_visit(api):
    """Fernwood Center: a director with no checks at all, so clearance_complete is
    false, and an INITIAL visit still SCHEDULED."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Fernwood Center",
        site_address="10 Fernwood Dr",
        program_type="CENTER",
        requested_capacity=20,
    )
    director = fx.attach_staff(
        api,
        provider["id"],
        full_name="Dana Director",
        member_type="DIRECTOR",
        qualified_age_groups=["PRESCHOOL"],
        role_title="Center Director",
    )
    inspection = fx.schedule_visit(
        api,
        provider["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="INITIAL",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
    )
    return {
        "provider_id": provider["id"],
        "director": director,
        "inspection": inspection,
        "ada": ada,
    }


class TestInspectionStateBeatsClearanceIncomplete:
    """§1.5: "Business rules are evaluated after all state checks"."""

    def test_a_scheduled_initial_visit_reports_the_state_error_not_the_clearance_gap(
        self, api
    ):
        """Finalizing a SCHEDULED visit at a provider whose clearance is
        incomplete breaks both rules, and only the state rule may be reported.

        PRD §1.5: "State preconditions follow, in this internal order: the
        provider's application dimension, then the provider's licence dimension,
        then the inspection, the violation, the complaint, the corrective action
        plan, the enforcement action, the amendment, the incident report, the
        posting, the background check, and finally whether a referenced inspection
        is of the required type. Business rules are evaluated after all state
        checks, in three groups: safety and regulatory rules first, then temporal
        rules, then non-temporal constraint rules and referential-agreement rules,
        and last of all the capacity and fiscal rules."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_inspection_state_beats_clearance_incomplete
        """
        ctx = _uncleared_provider_with_a_scheduled_initial_visit(api)
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["clearance_complete"] is False

        validate_error(
            api.finalize_inspection(
                ctx["inspection"]["id"], headers=supervisor_headers()
            ),
            "ERR_INVALID_INSPECTION_STATE",
            409,
        )

        still = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert still["status"] == "SCHEDULED"
        assert still["finalized_at"] is None

    def test_the_same_clearance_gap_surfaces_once_the_visit_reaches_pending_review(
        self, api
    ):
        """With the state rule satisfied and nothing else changed, the finalize
        call reports the clearance gap instead.

        PRD §3.4: "A supervisor finalizes a `PENDING_REVIEW` inspection; when the
        type is `INITIAL` the provider's `clearance_complete` must be true, or the
        call is `ERR_CLEARANCE_INCOMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_inspection_state_beats_clearance_incomplete
        """
        ctx = _uncleared_provider_with_a_scheduled_initial_visit(api)
        inspector = make_inspector_headers(ctx["ada"]["id"])
        validate_success(
            api.start_inspection(ctx["inspection"]["id"], headers=inspector)
        )
        validate_success(
            api.submit_for_review(
                ctx["inspection"]["id"], "PASS", ["PRESCHOOL"], headers=inspector
            )
        )

        validate_error(
            api.finalize_inspection(
                ctx["inspection"]["id"], headers=supervisor_headers()
            ),
            "ERR_CLEARANCE_INCOMPLETE",
            409,
        )

        still = validate_success(
            api.get_inspection(ctx["inspection"]["id"], headers=supervisor_headers())
        )
        assert still["status"] == "PENDING_REVIEW"
        assert still["finalized_at"] is None
        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["clearance_complete"] is False

    def test_clearing_the_two_required_checks_lets_the_same_call_through(self, api):
        """Once both required checks are CLEARED the third attempt finalizes a
        perfect visit, and the application dimension stays in DRAFT because the
        pass edge only leaves CHECKS_CLEARED.

        PRD §3.4: "When an `INITIAL` inspection finalizes with outcome `FAIL` the
        application status stays at `CHECKS_CLEARED` and the inspection still
        finalizes normally."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_inspection_state_beats_clearance_incomplete
        """
        ctx = _uncleared_provider_with_a_scheduled_initial_visit(api)
        inspector = make_inspector_headers(ctx["ada"]["id"])
        validate_success(
            api.start_inspection(ctx["inspection"]["id"], headers=inspector)
        )
        validate_success(
            api.submit_for_review(
                ctx["inspection"]["id"], "PASS", ["PRESCHOOL"], headers=inspector
            )
        )
        fx.clear_person(api, ctx["director"]["id"])

        cleared = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert cleared["clearance_complete"] is True

        finalized = validate_success(
            api.finalize_inspection(
                ctx["inspection"]["id"], headers=supervisor_headers()
            )
        )
        assert finalized["status"] == "FINALIZED"
        assert finalized["outcome"] == "PASS"
        assert finalized["violation_count"] == 0
        assert_score(finalized["raw_deduction_points"], 0.00, "raw_deduction_points")
        assert_score(
            finalized["final_compliance_score"], 100.00, "final_compliance_score"
        )

        provider = validate_success(
            api.get_provider(ctx["provider_id"], headers=supervisor_headers())
        )
        assert provider["application_status"] == "DRAFT", (
            "the pass edge runs CHECKS_CLEARED -> INITIAL_INSPECTION_PASSED and "
            "cannot fire from DRAFT"
        )


def _inspector_booked_from_nine_to_eleven(api):
    """One PRESCHOOL-only inspector holding a 09:00-11:00 visit at provider A, and
    a second provider B, so the provider-visit buffer can never be the answer."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider_a = fx.create_provider(
        api,
        legal_name="Provider A Center",
        site_address="21 A Street",
        program_type="CENTER",
        requested_capacity=20,
    )
    provider_b = fx.create_provider(
        api,
        legal_name="Provider B Center",
        site_address="22 B Street",
        program_type="CENTER",
        requested_capacity=20,
    )
    first = fx.schedule_visit(
        api,
        provider_a["id"],
        ada["id"],
        "2026-08-05T09:00:00Z",
        inspection_type="FOLLOW_UP",
        target_age_groups=["PRESCHOOL"],
        duration_minutes=120,
    )
    return {"ada": ada, "a_id": provider_a["id"], "b_id": provider_b["id"], "first": first}


def _request_visit(api, ctx, scheduled_for, target_age_groups):
    return api.create_inspection(
        f.inspection_payload(
            ctx["b_id"],
            ctx["ada"]["id"],
            inspection_type="FOLLOW_UP",
            scheduled_for=scheduled_for,
            target_age_groups=target_age_groups,
            duration_minutes=120,
        ),
        headers=supervisor_headers(),
    )


class TestDoubleBookingBeatsUncertifiedAgeGroup:
    """§1.5: "when scheduling a visit the two window-conflict checks are
    evaluated *before* the inspector-certification check"."""

    def test_an_overlapping_request_for_an_uncertified_band_reports_the_clash(
        self, api
    ):
        """A 10:00 start inside the standing 09:00-11:00 window also names INFANT,
        which the inspector cannot cover, and the temporal rule must win.

        PRD §1.5: "Two consequences of that ordering are worth stating explicitly
        because they are easy to get wrong: on an amendment decision the
        unresolved-critical-violation safety check is evaluated *before* the
        capacity-ceiling fiscal check, and when scheduling a visit the two
        window-conflict checks are evaluated *before* the inspector-certification
        check."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_double_booking_beats_uncertified_age_group
        """
        ctx = _inspector_booked_from_nine_to_eleven(api)
        assert_instant(
            ctx["first"]["visit_window_end"],
            "2026-08-05T11:00:00Z",
            "visit_window_end",
        )

        validate_error(
            _request_visit(api, ctx, "2026-08-05T10:00:00Z", ["PRESCHOOL", "INFANT"]),
            "ERR_INSPECTOR_DOUBLE_BOOKED",
            409,
        )

    def test_starting_exactly_at_the_window_end_leaves_only_the_certification_rule(
        self, api
    ):
        """The window is half-open, so an 11:00 start does not clash and the same
        uncertified band is reported instead.

        PRD §3.4: "The **inspector's** window is half-open — it includes its start
        instant and excludes its end instant — so two visits for the same inspector
        conflict only when their half-open windows genuinely overlap. Back-to-back
        visits, where one ends at the exact instant the next begins, do **not**
        conflict."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_double_booking_beats_uncertified_age_group
        """
        ctx = _inspector_booked_from_nine_to_eleven(api)

        validate_error(
            _request_visit(api, ctx, "2026-08-05T11:00:00Z", ["PRESCHOOL", "INFANT"]),
            "ERR_INSPECTOR_NOT_CERTIFIED_FOR_AGE_GROUP",
            409,
        )

    def test_dropping_the_uncertified_band_schedules_the_second_visit(self, api):
        """With both rules satisfied the 11:00 visit is created, and neither
        refusal left a row behind.

        PRD §3.4: "the two window-conflict checks are evaluated *before* the
        inspector-certification check."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_double_booking_beats_uncertified_age_group
        """
        ctx = _inspector_booked_from_nine_to_eleven(api)
        validate_error(
            _request_visit(api, ctx, "2026-08-05T10:00:00Z", ["PRESCHOOL", "INFANT"]),
            "ERR_INSPECTOR_DOUBLE_BOOKED",
            409,
        )
        validate_error(
            _request_visit(api, ctx, "2026-08-05T11:00:00Z", ["PRESCHOOL", "INFANT"]),
            "ERR_INSPECTOR_NOT_CERTIFIED_FOR_AGE_GROUP",
            409,
        )

        second = validate_success(
            _request_visit(api, ctx, "2026-08-05T11:00:00Z", ["PRESCHOOL"]), 201
        )
        assert second["status"] == "SCHEDULED"
        assert_instant(
            second["visit_window_end"], "2026-08-05T13:00:00Z", "visit_window_end"
        )

        rows, meta = validate_paginated(
            api.list_inspections(
                inspector_id=ctx["ada"]["id"], headers=supervisor_headers()
            )
        )
        assert meta["total_count"] == 2, (
            "a refused scheduling request must not create a row, so only the two "
            f"accepted visits exist; got {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {ctx["first"]["id"], second["id"]}


def _two_finalized_sibling_visits(api, catalog):
    """Glenpark Center with two finalized COMPLAINT visits, on 2026-08-05 and
    2026-08-06, each carrying exactly one RA-201/PRESCHOOL finding.

    Both finalize while the clock is still parked at 2026-08-01T00:00:00Z, so both
    plan windows close at 2026-08-11T00:00:00Z.
    """
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    ada = fx.register_inspector(
        api,
        full_name="Ada Inspector",
        certified_age_groups=["PRESCHOOL"],
        max_daily_visits=3,
    )
    provider = fx.create_provider(
        api,
        legal_name="Glenpark Center",
        site_address="31 Glenpark Ave",
        program_type="CENTER",
        requested_capacity=20,
    )
    visits = []
    for day, text in (("05", "First ratio report."), ("06", "Second ratio report.")):
        complaint = fx.intake_complaint(
            api,
            provider["id"],
            intake_channel="PHONE",
            allegation_category="RATIO",
            affected_age_group="PRESCHOOL",
            narrative=text,
            anonymous=True,
        )
        visits.append(
            fx.run_visit(
                api,
                provider["id"],
                ada["id"],
                f"2026-08-{day}T09:00:00Z",
                inspection_type="COMPLAINT",
                target_age_groups=["PRESCHOOL"],
                duration_minutes=120,
                complaint_id=complaint["id"],
                catalog=catalog,
                citations=[
                    {
                        "code": CODE_RATIO,
                        "primary_age_group": "PRESCHOOL",
                        "narrative": f"Preschool room over ratio: {text}",
                    }
                ],
                outcome="CONDITIONAL_PASS",
            )
        )
    return {
        "provider_id": provider["id"],
        "first": visits[0]["inspection"],
        "second": visits[1]["inspection"],
        "v1": visits[0]["violations"][0],
        "v2": visits[1]["violations"][0],
    }


def _submit_plan(api, ctx, violation_ids):
    return api.create_cap(
        f.cap_payload(
            ctx["first"]["id"],
            violation_ids,
            ctx["first"]["version"],
            narrative="Remediation plan for the ratio finding.",
            proposed_completion_date="2026-08-20",
        ),
        headers=make_applicant_headers(ctx["provider_id"]),
    )


class TestCapWindowClosedBeatsViolationInspectionMismatch:
    """§1.5: "temporal rules, then non-temporal constraint rules and
    referential-agreement rules"."""

    def test_a_late_plan_naming_a_sibling_visits_finding_reports_the_closed_window(
        self, api, catalog
    ):
        """One second past the ten-day edge the submission is refused on time, not
        on the foreign violation it also lists.

        PRD §3.6: "The submission window is bounded: the current instant must be at
        or before the inspection's `finalized_at` plus 10 days, with the upper edge
        **inclusive**. Submitting exactly at the ten-day instant succeeds; one
        second later is `ERR_CAP_WINDOW_CLOSED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_cap_window_closed_beats_violation_inspection_mismatch
        """
        ctx = _two_finalized_sibling_visits(api, catalog)
        assert_instant(
            ctx["first"]["finalized_at"], DEFAULT_LOGICAL_CLOCK, "finalized_at"
        )
        assert ctx["v2"]["inspection_id"] == ctx["second"]["id"]

        fx.set_clock(api, "2026-08-11T00:00:01Z")
        validate_error(
            _submit_plan(api, ctx, [ctx["v2"]["id"]]), "ERR_CAP_WINDOW_CLOSED", 409
        )

        rows, meta = validate_paginated(
            api.list_caps(
                inspection_id=ctx["first"]["id"], headers=supervisor_headers()
            )
        )
        assert meta["total_count"] == 0, f"a refused submission stores nothing: {rows!r}"

    def test_at_the_inclusive_edge_the_referential_rule_surfaces_alone(
        self, api, catalog
    ):
        """One second earlier, on the inclusive edge, the identical payload is
        refused because the listed finding belongs to the sibling visit.

        PRD §3.6: "`violation_ids` must be a non-empty list without duplicates,
        every element must be a violation whose `inspection_id` equals the plan's
        inspection and whose status is not `VACATED`, and that inspection must
        belong to the same provider as the plan; a mismatch is
        `ERR_VIOLATION_INSPECTION_MISMATCH` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_cap_window_closed_beats_violation_inspection_mismatch
        """
        ctx = _two_finalized_sibling_visits(api, catalog)
        fx.set_clock(api, "2026-08-11T00:00:00Z")

        validate_error(
            _submit_plan(api, ctx, [ctx["v2"]["id"]]),
            "ERR_VIOLATION_INSPECTION_MISMATCH",
            422,
        )

        unchanged = validate_success(
            api.get_inspection(ctx["first"]["id"], headers=supervisor_headers())
        )
        assert unchanged["version"] == ctx["first"]["version"], (
            "a refused plan submission must not advance the inspection revision"
        )

    def test_the_plan_that_names_its_own_finding_is_accepted_at_the_edge(
        self, api, catalog
    ):
        """At the same instant, listing the first visit's own finding creates the
        plan at cycle 1 with a due date ten days out for a serious finding.

        PRD §3.6: "The plan's own deadline, `due_at`, is the current instant plus
        the **minimum** correction allowance across the violations the plan covers —
        that is, the tightest of the 3, 10, 30 and 45 day allowances implied by those
        violations' effective severities."

        Design: Difficulty/priority_pair_validation_conflict/priority_pair_cap_window_closed_beats_violation_inspection_mismatch
        """
        ctx = _two_finalized_sibling_visits(api, catalog)
        fx.set_clock(api, "2026-08-11T00:00:00Z")
        validate_error(
            _submit_plan(api, ctx, [ctx["v2"]["id"]]),
            "ERR_VIOLATION_INSPECTION_MISMATCH",
            422,
        )

        plan = validate_success(_submit_plan(api, ctx, [ctx["v1"]["id"]]), 201)

        assert plan["status"] == "SUBMITTED"
        assert plan["review_cycle_count"] == 1
        assert plan["inspection_id"] == ctx["first"]["id"]
        assert plan["violation_ids"] == [ctx["v1"]["id"]]
        assert_instant(plan["due_at"], "2026-08-21T00:00:00Z", "due_at")
