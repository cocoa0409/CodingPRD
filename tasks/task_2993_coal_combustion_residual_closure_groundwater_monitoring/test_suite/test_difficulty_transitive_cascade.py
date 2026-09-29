"""Single writes whose effects travel three and four aggregates deep."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import fixtures
from test_helpers.constants import (
    AGREEMENT_STATUS_ACTIVE,
    AGREEMENT_STATUS_SUSPENDED,
    CAP_ADEQUATE,
    CAP_CRITERION_EROSION,
    CAP_CRITERION_SETTLEMENT,
    CAP_CRITERION_VEGETATION,
    CAP_DEFICIENT,
    CLOSURE_STATE_POST_CLOSURE_CARE,
    DOC_SHA256_ALT,
    DOC_URI_ALT,
    EVAL_VERDICT_SSI,
    FREQUENCY_QUARTERLY,
    FREQUENCY_SEMIANNUAL,
    INSPECTION_VERDICT_DEFICIENT,
    PHASE_ASSESSMENT,
    POSTING_CLOSURE_PLAN,
    POSTING_STABILITY_ASSESSMENT,
    POSTURE_COMPLIANT,
    POSTURE_RESTRICTED,
    POSTURE_WATCH,
)
from test_helpers.test_users import UTILITY_ADMIN_HEADERS


def read_agreement(api, agreement_id):
    return get_success_data(api.get_reuse_agreement(agreement_id, UTILITY_ADMIN_HEADERS))


def case_unit_with_an_active_agreement(api):
    """An SSI-ready unit that is also shipping ash under an ACTIVE agreement."""
    world = fixtures.seed_ssi_ready(api, "IMP-0007")
    fixtures.seed_active_agreement(
        api,
        world,
        "AGR-0001",
        "2026-08-01",
        commitment_start_on="2026-01-01",
        commitment_end_on="2026-12-31",
    )
    return world


def case_unit_in_post_closure_care(api):
    """A unit carried to POST_CLOSURE_CARE with a care clock that started 2027-01-15.

    Both public obligations are posted on the day they arise, so the unit never
    freezes on an overdue posting and the cap dimension is the only thing that
    later changes.
    """
    world = fixtures.seed_unit(api, "IMP-0008")
    fixtures.file_stability(api, world, "2026-07-15")
    fixtures.post_document(api, world, POSTING_STABILITY_ASSESSMENT, "2026-08-01")
    plan = fixtures.draft_plan(api, world, "CP-0004")
    fixtures.certify_plan_both_halves(api, world, plan["id"], "2026-08-01")
    fixtures.approve_plan(api, plan["id"], "2026-08-01", "PERMIT-2026-C")
    fixtures.post_document(
        api,
        world,
        POSTING_CLOSURE_PLAN,
        "2026-08-01",
        document_uri=DOC_URI_ALT,
        document_sha256=DOC_SHA256_ALT,
    )
    fixtures.begin_closure(api, world["unit_id"], "2026-08-01")
    fixtures.set_clock(api, "2027-01-15T00:00:00Z")
    fixtures.complete_closure(api, world, "2027-01-15")
    world["plan_id"] = plan["id"]
    return world


def test_one_evaluation_reaches_the_program_and_then_the_unit(api):
    """The first three hops of the chain fire from a single evaluation POST.

    PRD: An `SSI` or `SSL_EXCEEDANCE` verdict issued while the program is in `DETECTION` sets off a chain of four linked effects, and each one is caused by the one before it. First, the evaluation is stored with its verdict. Second, because that verdict is an increase, the program advances `DETECTION` -> `ASSESSMENT`, stamps `assessment_entered_on` with the current date, escalates `sampling_frequency` to `QUARTERLY`, and re-derives `next_sampling_due_date` at the shorter 91-day interval. Third, because the phase became `ASSESSMENT`, the owning unit's `ssi_notice_due_date` is set to the evaluation's `determined_on` plus 30 days - creating a public-notification obligation - and the unit's `compliance_posture` is recomputed, which lands on `RESTRICTED`.
    Design: Difficulty/transitive_cascade/ssi_cascade_depth_four_suspends_active_reuse_agreement
    """
    world = case_unit_with_an_active_agreement(api)
    assert fixtures.read_unit(api, world["unit_id"])["compliance_posture"] == POSTURE_COMPLIANT

    evaluation = fixtures.issue_evaluation(api, world, "EV-1")

    assert evaluation["verdict"] == EVAL_VERDICT_SSI
    a.assert_date(evaluation["determined_on"], "2026-08-01", "determined_on")
    a.assert_four_dp(evaluation["background_upper_limit"], 0.6961, "background_upper_limit")

    program = fixtures.read_program(api, world["program_id"])
    assert program["phase"] == PHASE_ASSESSMENT
    a.assert_date(program["assessment_entered_on"], "2026-08-01", "assessment_entered_on")
    assert program["sampling_frequency"] == FREQUENCY_QUARTERLY
    a.assert_date(program["next_sampling_due_date"], "2026-09-14", "next_sampling_due_date")

    unit = fixtures.read_unit(api, world["unit_id"])
    a.assert_date(unit["ssi_notice_due_date"], "2026-08-31", "ssi_notice_due_date")
    assert unit["compliance_posture"] == POSTURE_RESTRICTED
    # The notice is due at the end of the month, so it is pending and not late.
    assert unit["overdue_posting_types"] == []


def test_the_fourth_hop_suspends_the_active_agreement_the_evaluation_never_named(api):
    """The agreement moves because the posture moved, not because ash did.

    PRD: Fourth, because the unit's posture became `RESTRICTED`, every beneficial reuse agreement of that unit whose status is `ACTIVE` moves to `SUSPENDED` with `suspended_on` set to the current date, halting ash movement off the site.
    Design: Difficulty/transitive_cascade/ssi_cascade_depth_four_suspends_active_reuse_agreement
    """
    world = case_unit_with_an_active_agreement(api)
    assert read_agreement(api, world["agreement_id"])["status"] == AGREEMENT_STATUS_ACTIVE

    fixtures.issue_evaluation(api, world, "EV-1")

    agreement = read_agreement(api, world["agreement_id"])
    assert agreement["status"] == AGREEMENT_STATUS_SUSPENDED
    a.assert_date(agreement["suspended_on"], "2026-08-01", "suspended_on")
    assert agreement["shipped_tons_total"] == 0


def test_a_deficient_inspection_flips_the_cap_dimension_and_sets_a_repair_deadline(api):
    """The first two hops: the observation is written and the cap state follows it.

    PRD: Three criteria are tested and the failing ones are collected into `deficient_criteria` in a fixed order - `EROSION` first, then `SETTLEMENT`, then `VEGETATION` - regardless of which failed worst or which was measured first.
    PRD: A `DEFICIENT` verdict drives the cap dimension `ADEQUATE` -> `DEFICIENT`, or `DEFICIENT` -> `DEFICIENT` as a self-loop when the cap was already deficient, and sets `cap_repair_due_date` to `inspected_on` plus 60 days.
    Design: Difficulty/transitive_cascade/cap_deficiency_cascade_extends_care_and_escalates_sampling
    """
    world = case_unit_in_post_closure_care(api)
    before = fixtures.read_unit(api, world["unit_id"])
    assert before["cap_integrity_state"] == CAP_ADEQUATE
    a.assert_date(before["post_closure_care_end_date"], "2057-01-15", "post_closure_care_end_date")

    fixtures.set_clock(api, "2027-02-10T00:00:00Z")
    inspection = fixtures.file_cap_inspection(
        api,
        world,
        "2027-02-10",
        deficient=True,
        settlement_inches=8.00,
        vegetation_cover_pct=55.00,
        note="Rill erosion on the south slope with local settlement basin",
    )

    assert inspection["verdict"] == INSPECTION_VERDICT_DEFICIENT
    assert inspection["deficient_criteria"] == [
        CAP_CRITERION_EROSION,
        CAP_CRITERION_SETTLEMENT,
        CAP_CRITERION_VEGETATION,
    ]
    a.assert_append_only(inspection)

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["cap_integrity_state"] == CAP_DEFICIENT
    a.assert_date(unit["cap_repair_due_date"], "2027-04-11", "cap_repair_due_date")


def test_the_cap_state_change_extends_the_care_clock_and_escalates_sampling(api):
    """The third hop crosses into the care period and the monitoring program.

    PRD: That state change then causes a further hop that the inspection itself does not: because the cap became - or remained - deficient, `deficiency_extension_months` increases by another 12 months up to the 60-month cap, `post_closure_care_end_date` is recomputed from the new allowance, and the unit's monitoring program has its `sampling_frequency` escalated to `QUARTERLY`.
    PRD: a unit with an unrepaired cap sits at `WATCH` while the current date is on or before `cap_repair_due_date`
    Design: Difficulty/transitive_cascade/cap_deficiency_cascade_extends_care_and_escalates_sampling
    """
    world = case_unit_in_post_closure_care(api)
    assert fixtures.read_program(api, world["program_id"])["sampling_frequency"] == FREQUENCY_SEMIANNUAL

    fixtures.set_clock(api, "2027-02-10T00:00:00Z")
    fixtures.file_cap_inspection(
        api,
        world,
        "2027-02-10",
        deficient=True,
        settlement_inches=8.00,
        vegetation_cover_pct=55.00,
    )

    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["deficiency_extension_months"] == 12
    a.assert_date(unit["post_closure_care_end_date"], "2058-01-15", "post_closure_care_end_date")
    # The cap dimension moved; the closure dimension is a separate axis.
    assert unit["closure_state"] == CLOSURE_STATE_POST_CLOSURE_CARE
    assert unit["compliance_posture"] == POSTURE_WATCH
    assert fixtures.read_program(api, world["program_id"])["sampling_frequency"] == FREQUENCY_QUARTERLY
