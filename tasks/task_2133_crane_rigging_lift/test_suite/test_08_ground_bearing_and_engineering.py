"""The two ground-bearing variants, the engineering revision cycle, and the
permit gate that stands between an approved plan and the field."""

import pytest

from test_helpers import (
    ApiErrorId,
    LIFT_DIRECTOR,
    approve_permit,
    build_critical_world,
    decide_review,
    make_engineer_headers,
    open_permit,
    read_plan,
    read_review,
    resubmit_review,
    setup_configured_plan,
    setup_critical_plan_under_review,
    setup_stamped_critical_plan,
    submit_permit,
    validate_error,
    validate_success,
)


class TestGroundBearingVariants:
    """Difficulty rule: dual_variant_calc."""

    def test_configure_writes_the_provisional_survey_bearing_figures(self, api):
        """PRD 3.5: "Under the **`PROVISIONAL_SURVEY`** variant — written at configure
        time, before any engineering stamp — the machine is assumed to be sitting
        level with all four outriggers sharing the vertical load equally and with no
        dynamic amplification, so the plan's `per_outrigger_load_lb` is that total
        divided by four, rounded half up to two decimal places, and `bearing_variant`
        is set to `PROVISIONAL_SURVEY`."
        PRD 3.5: "The plan's `bearing_pressure_psf` is `per_outrigger_load_lb` divided
        by the crane's `outrigger_pad_area_sqft` — the bearing area of a single float
        — rounded half up to two decimal places."
        PRD 3.5: "When matting is required, the plan's `mat_area_required_sqft` is
        `per_outrigger_load_lb` divided by the site's `soil_bearing_capacity_psf`,
        rounded **up** to the next whole square foot, and its `mat_count` is four
        times the number of standard mat panels needed to cover that area, where one
        standard panel covers 32 square feet and a partial panel counts as a whole
        one — four, because every outrigger needs the same treatment."

        Design: Difficulty/dual_variant_calc/ground_bearing_provisional_survey_vs_final_engineered
        """
        world = build_critical_world()
        ctx = setup_configured_plan(
            world, plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0}
        )
        plan = ctx["plan"]

        assert plan["bearing_variant"] == "PROVISIONAL_SURVEY"
        assert plan["per_outrigger_load_lb"] == pytest.approx(90_875.00, abs=0.005)
        assert plan["bearing_pressure_psf"] == pytest.approx(2_271.88, abs=0.005)
        assert plan["matting_required"] is True
        assert plan["mat_area_required_sqft"] == 46
        assert plan["mat_count"] == 8

    def test_stamp_overwrites_the_plan_with_the_final_engineered_variant(self, api):
        """PRD 3.5: "Under the **`FINAL_ENGINEERED`** variant — written when an
        engineering review on the plan reaches `STAMPED` — the engineer assumes
        instead that the governing outrigger carries sixty hundredths of the *whole*
        vertical load and applies a dynamic and impact factor of 1.10 on top, so
        `per_outrigger_load_lb` is the total vertical load multiplied by sixty
        hundredths and then by 1.10, rounded half up to two decimal places, and
        `bearing_variant` is set to `FINAL_ENGINEERED`."
        PRD 3.6: "The engineered results are written twice: onto the review itself as
        `final_bearing_pressure_psf` and `final_mat_count`, and onto the plan, where
        they overwrite `bearing_variant`, `per_outrigger_load_lb`,
        `bearing_pressure_psf`, `matting_required`, `mat_area_required_sqft` and
        `mat_count` in place."
        PRD 3.6: "In the same request the plan advances `PENDING_ENGINEERING →
        APPROVED` — no lift director sign-off is needed on a critical lift, because
        the stamp *is* the sign-off — and the plan's `version` increments alongside
        the review's."

        Design: Difficulty/dual_variant_calc/ground_bearing_provisional_survey_vs_final_engineered
        """
        world = build_critical_world()
        ctx = setup_stamped_critical_plan(
            world, plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0}
        )
        review = ctx["review"]
        plan = ctx["plan"]

        assert review["final_bearing_pressure_psf"] == pytest.approx(5_997.75, abs=0.005)
        assert review["final_mat_count"] == 16
        assert review["status"] == "STAMPED"
        assert review["stamped_by_personnel_id"] == world["eng_b_id"]

        assert plan["bearing_variant"] == "FINAL_ENGINEERED"
        assert plan["per_outrigger_load_lb"] == pytest.approx(239_910.00, abs=0.005)
        assert plan["bearing_pressure_psf"] == pytest.approx(5_997.75, abs=0.005)
        assert plan["mat_count"] == 16
        assert plan["plan_status"] == "APPROVED"


class TestEngineeringRevisionCycle:
    """Difficulty rule: non_linear_state_machine."""

    def test_each_resubmission_returns_the_review_to_under_review_and_bumps_the_round(self, api):
        """PRD 3.6: "`REQUEST_CHANGES` moves the review `UNDER_REVIEW →
        CHANGES_REQUESTED` and records the supplied `note` as `change_request_note`,
        leaving the owning plan exactly where it is."
        PRD 3.6: "When changes have been requested, the original author — and only
        the author — resubmits with fresh `analysis_notes`, which moves the review
        `CHANGES_REQUESTED → UNDER_REVIEW` and increments `revision_round` by one."

        Design: Difficulty/non_linear_state_machine/engineering_review_revision_cycle_terminates_at_round_three
        """
        world = build_critical_world()
        ctx = setup_critical_plan_under_review(
            world, plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0}
        )
        assert ctx["review"]["revision_round"] == 1

        changed = decide_review(world, ctx["review_id"], "REQUEST_CHANGES",
                                "tighten the outrigger reactions")
        assert changed["status"] == "CHANGES_REQUESTED"

        round_two = resubmit_review(world, ctx["review_id"], "rev 2 analysis")
        assert round_two["revision_round"] == 2
        assert round_two["status"] == "UNDER_REVIEW"

        decide_review(world, ctx["review_id"], "REQUEST_CHANGES", "mat layout still unclear")
        round_three = resubmit_review(world, ctx["review_id"], "rev 3 analysis")
        assert round_three["revision_round"] == 3
        assert round_three["status"] == "UNDER_REVIEW"

    def test_fourth_resubmission_fails_yet_persists_the_review_as_rejected(self, api):
        """PRD 3.6: "That cycle may repeat while `revision_round` is below 3."
        PRD 3.6: "A resubmission attempted while `revision_round` already stands at 3
        is a hard stop with an unusual shape: the request **fails** with
        `ERR_REVISION_LIMIT_EXCEEDED` at HTTP 409, and yet the review is still
        persisted as `REJECTED` with `decision_note` recording that the revision
        limit was exceeded, and its `version` still increments."
        PRD 3.6: "`REJECT` moves the review `UNDER_REVIEW → REJECTED`, which is
        terminal, and records the supplied `note` as `decision_note`. The plan stays
        at `PENDING_ENGINEERING` and can only progress by way of a fresh review or a
        re-configuration."

        Design: Difficulty/non_linear_state_machine/engineering_review_revision_cycle_terminates_at_round_three
        """
        world = build_critical_world()
        ctx = setup_critical_plan_under_review(
            world, plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0}
        )
        for notes in ("rev 2 analysis", "rev 3 analysis"):
            decide_review(world, ctx["review_id"], "REQUEST_CHANGES", "needs another pass")
            resubmit_review(world, ctx["review_id"], notes)
        decide_review(world, ctx["review_id"], "REQUEST_CHANGES", "third pass still short")

        resp = api.resubmit_engineering_review(
            ctx["review_id"], {"analysis_notes": "rev 4 analysis"},
            make_engineer_headers(world["eng_a_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED.value, 409)

        review = read_review(ctx["review_id"])
        assert review["status"] == "REJECTED"
        assert review["revision_round"] == 3
        assert read_plan(ctx["plan_id"])["plan_status"] == "PENDING_ENGINEERING"


class TestReleaseGatedOnPermitApproval:
    """Difficulty rule: cross_entity_state_dependency."""

    @staticmethod
    def _approved_plan_with_submitted_permit(world):
        ctx = setup_stamped_critical_plan(
            world,
            plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0,
                            "road_closure_requested": True},
        )
        permit = open_permit(ctx["plan_id"], "ROAD_CLOSURE", world=world)
        submitted = submit_permit(permit["id"])
        ctx["permit"] = submitted
        ctx["permit_id"] = permit["id"]
        return ctx

    def test_release_blocked_while_the_only_permit_is_merely_submitted(self, api):
        """PRD 3.4: "The plan's `escort_required` becomes true when the assigned
        crane's `class_tons` is greater than or equal to 200 tons, and is false while
        no crane is assigned. The plan's `permit_required` is true when
        `road_closure_requested` is true **or** `escort_required` is true, and false
        otherwise."
        PRD 3.8: "If the plan's `permit_required` is true, at least one permit on the
        plan must stand at `APPROVED`, or the release fails with
        `ERR_PERMIT_NOT_APPROVED`; a plan whose `permit_required` is false skips this
        check entirely."

        Design: Difficulty/cross_entity_state_dependency/lift_plan_release_gated_on_permit_reaching_approved
        """
        world = build_critical_world()
        ctx = self._approved_plan_with_submitted_permit(world)

        assert ctx["plan"]["permit_required"] is True
        assert ctx["plan"]["escort_required"] is True
        assert ctx["permit"]["status"] == "SUBMITTED"

        validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                       ApiErrorId.ERR_PERMIT_NOT_APPROVED.value, 409)
        assert read_plan(ctx["plan_id"])["plan_status"] == "APPROVED"

    def test_identical_release_succeeds_once_the_permit_is_recorded_approved(self, api):
        """PRD 3.7: "An approval moves the permit `SUBMITTED → APPROVED`, stamps
        `decision_at` with the logical clock and stores the `agency_reference`."
        PRD 3.8: "Release is the last gate before iron moves, and it is where every
        certification, permit, gear and credit condition is finally tested. It too
        takes no payload, and moves the plan `APPROVED → RELEASED` only if all of the
        following hold."

        Design: Difficulty/cross_entity_state_dependency/lift_plan_release_gated_on_permit_reaching_approved
        """
        world = build_critical_world()
        ctx = self._approved_plan_with_submitted_permit(world)

        validate_error(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                       ApiErrorId.ERR_PERMIT_NOT_APPROVED.value, 409)

        granted = approve_permit(ctx["permit_id"], "NJB-2026-1188")
        assert granted["status"] == "APPROVED"

        released = validate_success(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR))
        assert released["plan_status"] == "RELEASED", (
            "the identical release call must succeed once the permit reaches APPROVED"
        )
