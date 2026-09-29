"""Input rules: outcome agreement, temporal edges, aggregates and conditionals.

Every case pairs the refusal with the neighbouring request that is accepted, so a
rule that is merely absent fails as loudly as one that is too wide.
"""

from test_helpers import (
    CODE_NUTRITION,
    CODE_SUPERVISION,
    DEFAULT_LOGICAL_CLOCK,
    admin_headers,
    assert_instant,
    assert_score,
    factories as f,
    fixtures as fx,
    intake_headers,
    make_inspector_headers,
    supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PRESCHOOL_ONLY = ["PRESCHOOL"]
VISIT_INSTANT = "2026-08-05T09:00:00Z"


def _in_progress_visit_with_one_citation(api, catalog, code, narrative):
    """An IN_PROGRESS ANNUAL visit at VISIT_INSTANT carrying one PRESCHOOL citation."""
    fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
    provider = fx.create_provider(api, requested_capacity=10)
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
        catalog[code],
        primary_age_group="PRESCHOOL",
        narrative=narrative,
    )
    return provider, inspector, inspection, violation


class TestOutcomeMustAgreeWithWhatWasCited:
    """§3.4: "the outcome must agree with what was actually cited"."""

    def test_a_pass_over_a_standing_critical_finding_is_refused(self, api, catalog):
        """PASS is impossible while a CRITICAL citation stands; the identical call
        with FAIL is accepted, and the refusal moved nothing.

        PRD §3.4: "the outcome **must** be `FAIL` when at least one violation of
        this inspection has effective severity `CRITICAL` and a status other than
        `VACATED` ... Any other pairing is `ERR_OUTCOME_SEVERITY_MISMATCH` (HTTP
        409)."

        Design: Corner/validations/val_violation_to_error_pass_outcome_with_critical_citation
        """
        _provider, inspector, inspection, violation = _in_progress_visit_with_one_citation(
            api, catalog, CODE_SUPERVISION, "Children unsupervised at the sink."
        )

        validate_error(
            api.submit_for_review(
                inspection["id"],
                "PASS",
                PRESCHOOL_ONLY,
                headers=make_inspector_headers(inspector["id"]),
            ),
            "ERR_OUTCOME_SEVERITY_MISMATCH",
            409,
        )
        refused = validate_success(
            api.get_inspection(inspection["id"], headers=admin_headers())
        )
        assert refused["status"] == "IN_PROGRESS"
        assert refused["submitted_at"] is None

        accepted = validate_success(
            api.submit_for_review(
                inspection["id"],
                "FAIL",
                PRESCHOOL_ONLY,
                headers=make_inspector_headers(inspector["id"]),
            )
        )
        assert accepted["status"] == "PENDING_REVIEW"
        assert accepted["outcome"] == "FAIL"

        after = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert after["status"] == "CITED", "submit-for-review does not move citations"

    def test_a_conditional_pass_over_one_minor_finding_satisfies_both_branches(
        self, api, catalog
    ):
        """With a single MINOR citation neither branch of the rule fires, so
        CONDITIONAL_PASS is accepted and the visit finalizes at 99.00.

        PRD §3.4: "Between those two poles the choice is free: with non-critical
        violations cited and none vacated away, `PASS`, `CONDITIONAL_PASS` and
        `FAIL` are all acceptable."

        Design: Corner/validations/val_satisfaction_to_pass_conditional_pass_with_only_a_minor
        """
        provider, inspector, inspection, violation = _in_progress_visit_with_one_citation(
            api, catalog, CODE_NUTRITION, "Menu board blank."
        )

        submitted = validate_success(
            api.submit_for_review(
                inspection["id"],
                "CONDITIONAL_PASS",
                PRESCHOOL_ONLY,
                headers=make_inspector_headers(inspector["id"]),
            )
        )
        assert submitted["status"] == "PENDING_REVIEW"

        finalized = fx.finalize_visit(api, inspection["id"])
        assert_score(finalized["final_compliance_score"], 99.00, "final")
        assert_score(finalized["preliminary_compliance_score"], 99.00, "preliminary")
        assert finalized["cap_required"] is True
        assert finalized["violation_count"] == 1

        after = validate_success(
            api.get_violation(violation["id"], headers=admin_headers())
        )
        assert after["status"] == "CORRECTION_PENDING"
        reloaded = validate_success(
            api.get_provider(provider["id"], headers=admin_headers())
        )
        assert reloaded["critical_open_count"] == 0


class TestTheScheduleClockEdgeIsStrict:
    """§3.4: "`scheduled_for` must be strictly after the logical clock"."""

    def test_the_clock_instant_itself_is_in_the_past_but_one_second_later_is_not(
        self, api
    ):
        """Yesterday and the current instant are both ERR_SCHEDULE_IN_PAST; one
        second after the clock is accepted, and only that request counted.

        PRD §3.4: "`scheduled_for` must be strictly after the logical clock, and a
        start exactly at the clock is refused with `ERR_SCHEDULE_IN_PAST` (HTTP
        422)"

        Design: Corner/validations/val_temporal_validation_schedule_at_the_clock_instant_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)
        inspector = fx.register_inspector(api, certified_age_groups=PRESCHOOL_ONLY)
        fx.set_clock(api, VISIT_INSTANT)

        def attempt(scheduled_for):
            return api.create_inspection(
                f.inspection_payload(
                    provider["id"],
                    inspector["id"],
                    inspection_type="ANNUAL",
                    scheduled_for=scheduled_for,
                    target_age_groups=PRESCHOOL_ONLY,
                ),
                headers=supervisor_headers(),
            )

        validate_error(attempt("2026-08-04T09:00:00Z"), "ERR_SCHEDULE_IN_PAST", 422)
        validate_error(attempt(VISIT_INSTANT), "ERR_SCHEDULE_IN_PAST", 422)

        created = validate_success(attempt("2026-08-05T09:00:01Z"), 201)
        assert_instant(created["scheduled_for"], "2026-08-05T09:00:01Z", "scheduled_for")
        assert_instant(
            created["visit_window_end"], "2026-08-05T11:00:01Z", "visit_window_end"
        )

        after = validate_success(
            api.get_inspector(inspector["id"], headers=admin_headers())
        )
        assert after["scheduled_visit_count"] == 1, "only the accepted request counted"


class TestTheAnonymityRuleIsConditional:
    """§3.7: "an `anonymous` complaint requires `complainant_name` to be omitted or
    null"."""

    def test_a_name_is_refused_only_when_the_complaint_is_anonymous(self, api):
        """Name-with-anonymous is refused, anonymous alone is stored with a null
        name, and the identical name is accepted once anonymous is false.

        PRD §3.7: "Two input rules bind at intake: an `anonymous` complaint requires
        `complainant_name` to be omitted or null, and supplying both is
        `ERR_INVALID_REQUEST`"

        Design: Corner/validations/val_conditional_validation_anonymous_complaint_with_a_name_rejected
        """
        fx.set_clock(api, DEFAULT_LOGICAL_CLOCK)
        provider = fx.create_provider(api, requested_capacity=10)

        def intake(**kwargs):
            return api.create_complaint(
                f.complaint_payload(
                    provider["id"],
                    intake_channel="PHONE",
                    allegation_category="RECORDS",
                    affected_age_group="SCHOOL_AGE",
                    narrative="Records missing.",
                    **kwargs,
                ),
                headers=intake_headers(),
            )

        validate_error(
            intake(anonymous=True, complainant_name="Jo Vega"), "ERR_INVALID_REQUEST", 400
        )

        anonymous = validate_success(intake(anonymous=True), 201)
        assert anonymous["anonymous"] is True
        assert anonymous["complainant_name"] is None

        named = validate_success(
            intake(anonymous=False, complainant_name="Jo Vega"), 201
        )
        assert named["anonymous"] is False
        assert named["complainant_name"] == "Jo Vega"

        for complaint, label in ((anonymous, "anonymous"), (named, "named")):
            assert complaint["priority"] == "P3", label
            assert_instant(
                complaint["investigation_due_at"],
                "2026-09-30T00:00:00Z",
                f"{label} investigation_due_at",
            )

        _rows, meta = validate_paginated(
            api.list_complaints(headers=admin_headers(), provider_id=provider["id"])
        )
        assert meta["total_count"] == 2
