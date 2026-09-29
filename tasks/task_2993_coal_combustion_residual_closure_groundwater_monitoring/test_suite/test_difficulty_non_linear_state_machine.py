"""Lifecycles that revisit states: a monitoring cycle and a certification diamond."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLOSURE_STATE_CLOSURE_PLANNED,
    EVAL_STATUS_ASD_ACCEPTED,
    EVAL_VERDICT_NO_SSI_ALTERNATE_SOURCE,
    EVAL_VERDICT_SSI,
    FREQUENCY_QUARTERLY,
    FREQUENCY_SEMIANNUAL,
    METHOD_CLOSURE_IN_PLACE,
    PHASE_ASSESSMENT,
    PHASE_DETECTION,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_COST_CERTIFIED,
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_ENGINEERING_CERTIFIED,
    PLAN_STATUS_FULLY_CERTIFIED,
    POSTURE_COMPLIANT,
    POSTURE_RESTRICTED,
)
from test_helpers.test_users import REGULATOR_HEADERS

CERTIFICATION_FIELDS = (
    "engineering_certified_by",
    "engineering_certified_on",
    "design_narrative",
    "cost_certified_by",
    "cost_certified_on",
    "cost_basis_note",
)


def read_plan(api, plan_id):
    return get_success_data(api.get_closure_plan(plan_id, REGULATOR_HEADERS))


def case_engineering_certified_plan(api):
    """A drafted plan with only the engineering half of the diamond signed."""
    world = fixtures.seed_unit(api, "IMP-0006")
    fixtures.file_stability(api, world, "2026-07-15")
    plan = fixtures.draft_plan(api, world, "CP-0003")
    get_success_data(
        api.certify_plan_engineering(
            plan["id"],
            factories.engineering_certification_payload(
                "2026-08-01",
                design_narrative="Composite cap with 24-inch protective layer and perimeter toe drain regrade",
            ),
            world["geotech_headers"],
        )
    )
    world["plan_id"] = plan["id"]
    return world


def test_the_assessment_leg_of_the_cycle_pulls_the_next_sampling_date_forward(api):
    """Escalation stamps the entry date and re-derives the schedule at 91 days.

    PRD: Second, because that verdict is an increase, the program advances `DETECTION` -> `ASSESSMENT`, stamps `assessment_entered_on` with the current date, escalates `sampling_frequency` to `QUARTERLY`, and re-derives `next_sampling_due_date` at the shorter 91-day interval.
    PRD: Third, because the phase became `ASSESSMENT`, the owning unit's `ssi_notice_due_date` is set to the evaluation's `determined_on` plus 30 days - creating a public-notification obligation - and the unit's `compliance_posture` is recomputed, which lands on `RESTRICTED`.
    Design: Difficulty/non_linear_state_machine/program_phase_cycles_detection_assessment_detection
    """
    world = fixtures.seed_ssi_escalation(api, "IMP-0005", "EV-1")
    assert world["evaluation"]["verdict"] == EVAL_VERDICT_SSI

    program = fixtures.read_program(api, world["program_id"])
    unit = fixtures.read_unit(api, world["unit_id"])

    assert program["phase"] == PHASE_ASSESSMENT
    assert program["sampling_frequency"] == FREQUENCY_QUARTERLY
    a.assert_date(program["assessment_entered_on"], "2026-08-01", "assessment_entered_on")
    # 2026-06-15, the latest validated round, advanced by the 91-day cadence.
    a.assert_date(program["next_sampling_due_date"], "2026-09-14", "next_sampling_due_date")
    a.assert_date(unit["ssi_notice_due_date"], "2026-08-31", "ssi_notice_due_date")
    assert unit["compliance_posture"] == POSTURE_RESTRICTED


def test_an_accepted_demonstration_returns_the_program_to_a_detection_it_has_already_left(api):
    """The second DETECTION visit clears the entry date and swings the schedule back.

    PRD: An acceptance moves `ASD_UNDER_REVIEW` -> `ASD_ACCEPTED`, which is terminal for the evaluation, and rewrites the `verdict` to `NO_SSI_ALTERNATE_SOURCE`; that value is reachable in no other way.
    PRD: Acceptance also unwinds the escalation: the program returns to `DETECTION` with `sampling_frequency` back to `SEMIANNUAL` and `assessment_entered_on` cleared to null
    PRD: Because the phase returned to `DETECTION`, the unit's `ssi_notice_due_date` is cleared to null and its `compliance_posture` is recomputed
    Design: Difficulty/non_linear_state_machine/program_phase_cycles_detection_assessment_detection
    """
    world = fixtures.seed_ssi_escalation(api, "IMP-0005", "EV-1")
    escalated = fixtures.read_program(api, world["program_id"])
    assert escalated["phase"] == PHASE_ASSESSMENT

    evaluation = fixtures.accept_asd(
        api,
        world,
        world["evaluation_id"],
        world["hydro_id"],
        submitted_on="2026-08-01",
        decided_on="2026-08-01",
    )

    assert evaluation["status"] == EVAL_STATUS_ASD_ACCEPTED
    assert evaluation["verdict"] == EVAL_VERDICT_NO_SSI_ALTERNATE_SOURCE
    a.assert_date(evaluation["asd_decided_on"], "2026-08-01", "asd_decided_on")

    program = fixtures.read_program(api, world["program_id"])
    assert program["phase"] == PHASE_DETECTION
    assert program["sampling_frequency"] == FREQUENCY_SEMIANNUAL
    assert program["assessment_entered_on"] is None
    # The same last round, now read at the restored 182-day cadence.
    a.assert_date(program["next_sampling_due_date"], "2026-12-14", "next_sampling_due_date")

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["ssi_notice_due_date"] is None
    assert unit["compliance_posture"] == POSTURE_COMPLIANT


def test_approval_is_refused_while_only_one_arm_of_the_diamond_is_signed(api):
    """A half-certified plan is not approvable and is left untouched by the attempt.

    PRD: A `Regulator` approves a `FULLY_CERTIFIED` plan by supplying `approved_on` and the `permit_reference` from the permit record.
    PRD: 22. The closure plan's `status` admits the operation, else `ERR_INVALID_PLAN_STATE`.
    Design: Difficulty/non_linear_state_machine/closure_plan_fork_join_and_return_to_draft_clears_both_branches
    """
    world = case_engineering_certified_plan(api)
    assert read_plan(api, world["plan_id"])["status"] == PLAN_STATUS_ENGINEERING_CERTIFIED

    response = api.approve_closure_plan(
        world["plan_id"],
        factories.approve_plan_payload("2026-08-01", "PERMIT-2026-A"),
        REGULATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.INVALID_PLAN_STATE.value)
    unchanged = read_plan(api, world["plan_id"])
    assert unchanged["status"] == PLAN_STATUS_ENGINEERING_CERTIFIED
    assert unchanged["return_count"] == 0


def test_the_join_is_reached_by_both_edges_and_the_return_rewinds_it(api):
    """One plan passes DRAFT twice and closes the join from each branch in turn.

    PRD: From `DRAFT`, the engineering signature takes the plan `DRAFT` -> `ENGINEERING_CERTIFIED` and the cost signature takes it `DRAFT` -> `COST_CERTIFIED`. From there the remaining signature closes the join: the cost signature completes `ENGINEERING_CERTIFIED` -> `FULLY_CERTIFIED` and the engineering signature completes `COST_CERTIFIED` -> `FULLY_CERTIFIED`.
    PRD: Returning to draft is admitted as `ENGINEERING_CERTIFIED` -> `DRAFT`, `COST_CERTIFIED` -> `DRAFT` and `FULLY_CERTIFIED` -> `DRAFT`, takes no payload, and in all three cases clears **both** halves ... sets the status to `DRAFT`, and increments `return_count` by 1.
    Design: Difficulty/non_linear_state_machine/closure_plan_fork_join_and_return_to_draft_clears_both_branches
    """
    world = case_engineering_certified_plan(api)
    plan_id = world["plan_id"]

    joined = get_success_data(
        api.certify_plan_cost(
            plan_id,
            factories.cost_certification_payload(
                "2026-08-01",
                cost_basis_note="Unit-price bid tabulation, 2026 dollars, 3 percent discount basis",
            ),
            world["civil_headers"],
        )
    )
    assert joined["status"] == PLAN_STATUS_FULLY_CERTIFIED

    returned = get_success_data(api.return_plan_to_draft(plan_id, {}, REGULATOR_HEADERS))
    assert returned["status"] == PLAN_STATUS_DRAFT
    assert returned["return_count"] == 1
    for field in CERTIFICATION_FIELDS:
        assert returned[field] is None, f"{field} should be cleared by the return, got {returned[field]!r}"

    cost_first = get_success_data(
        api.certify_plan_cost(
            plan_id,
            factories.cost_certification_payload(
                "2026-08-01", cost_basis_note="Re-issued cost basis after regulator return"
            ),
            world["civil_headers"],
        )
    )
    assert cost_first["status"] == PLAN_STATUS_COST_CERTIFIED

    rejoined = get_success_data(
        api.certify_plan_engineering(
            plan_id,
            factories.engineering_certification_payload(
                "2026-08-01", design_narrative="Re-issued design narrative after regulator return"
            ),
            world["geotech_headers"],
        )
    )
    assert rejoined["status"] == PLAN_STATUS_FULLY_CERTIFIED
    assert rejoined["engineering_certified_by"] == world["geotech_id"]
    assert rejoined["cost_certified_by"] == world["civil_id"]
    assert rejoined["return_count"] == 1


def test_the_reworked_plan_approves_on_its_second_pass_through_the_diamond(api):
    """Approval after the rewind stores the new permit and moves the unit forward.

    PRD: On success the plan moves `FULLY_CERTIFIED` -> `APPROVED` with `approved_on` and `permit_reference` stored, and a second effect follows from it: the unit's `closure_state` advances `ACTIVE` -> `CLOSURE_PLANNED`, the unit's `closure_plan_posting_due_date` is set to `approved_on` plus 60 days, creating a public-posting obligation, and the unit's `compliance_posture` is recomputed.
    Design: Difficulty/non_linear_state_machine/closure_plan_fork_join_and_return_to_draft_clears_both_branches
    """
    world = case_engineering_certified_plan(api)
    plan_id = world["plan_id"]
    get_success_data(
        api.certify_plan_cost(
            plan_id, factories.cost_certification_payload("2026-08-01"), world["civil_headers"]
        )
    )
    get_success_data(api.return_plan_to_draft(plan_id, {}, REGULATOR_HEADERS))
    fixtures.certify_plan_both_halves(api, world, plan_id, "2026-08-01")

    approved = fixtures.approve_plan(api, plan_id, "2026-08-01", "PERMIT-2026-B")

    assert approved["status"] == PLAN_STATUS_APPROVED
    assert approved["permit_reference"] == "PERMIT-2026-B"
    assert approved["return_count"] == 1
    assert approved["recommended_method"] == METHOD_CLOSURE_IN_PLACE
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["closure_state"] == CLOSURE_STATE_CLOSURE_PLANNED
    a.assert_date(
        unit["closure_plan_posting_due_date"], "2026-09-30", "closure_plan_posting_due_date"
    )
