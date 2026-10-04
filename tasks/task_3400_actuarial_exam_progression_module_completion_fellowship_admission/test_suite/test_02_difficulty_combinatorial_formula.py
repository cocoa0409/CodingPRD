"""Difficulty queue — combinatorial formulas.

Pinned rounding order in the registration fee (PRD §3.3), the CPD requirement
with admission-year proration and the carryover cap (PRD §3.8), and the
two-phase track completion percentage (PRD §3.5).
"""
import pytest

from test_helpers import (
    CLOCK_ASA_ADMIT_JULY,
    CLOCK_LATE_FEE_TIER,
    CLOCK_2027_SCORING,
    CLOCK_2027_WINDOW_OPEN,
    CPD_ATTESTED_LOW,
    CPD_CARRYOVER_OVER_CAP,
    CPD_CARRYOVER_SMALL,
    CPD_CYCLE_YEAR,
    FEE_EARLY_CENTS,
    FEE_LATE_CENTS,
    FEE_PINNED_ROUNDING_BASE,
    FEE_PINNED_ROUNDING_CENTS,
    FEE_PINNED_ROUNDING_SURCHARGE,
    PCT_AFTER_ALL_NONCAPSTONE,
    PCT_AFTER_ONE_MODULE,
    PCT_AFTER_PROJECT,
    PCT_COMPLETED,
    RAW_SCORE_AT_MARK,
    SUBMIT_SCORE_PASS,
    WINDOW_2027_CODE,
    WINDOW_2027_DEADLINE,
    WINDOW_2027_OPENS,
    WINDOW_2027_TESTING_ENDS,
    WINDOW_2027_TESTING_STARTS,
    apply_for_credential,
    approve_all_vee_topics,
    attempt_and_submit,
    get_enrollment,
    make_active_exam,
    make_candidate,
    make_cpd,
    make_window,
    propose_ratify_publish,
    record_score,
    register,
    set_clock,
    setup_associate,
    setup_capstone_eligible,
    setup_enrollment,
    setup_open_window,
    setup_project_decided,
)


def test_registration_fee_processing_rounded_once_on_subtotal(api):
    """PRD §3.3: "The rounding order is pinned: the processing component is
    computed once on the summed subtotal and rounded half-up before being
    added — rounding each component's share of the processing separately and
    summing afterward is not the rule and can differ by one cent."

    Design: Difficulty/combinatorial_formula/registration_fee_rounding_order_pinned
    """
    ctx = setup_open_window(api, register_clock=CLOCK_LATE_FEE_TIER,
                            base_fee_cents=FEE_PINNED_ROUNDING_BASE,
                            late_surcharge_cents=FEE_PINNED_ROUNDING_SURCHARGE)
    candidate = make_candidate(api)
    registration = register(api, ctx["window"]["id"], candidate)
    # Late tier: 20160 + 10160 + round_half_up(30320 * 0.015) = 30320 + 455.
    assert registration["fee_charged_cents"] == FEE_PINNED_ROUNDING_CENTS
    # The per-component order (30774) is expressly not the rule.
    assert registration["fee_charged_cents"] != 30774
    assert registration["logistics_status"] == "REGISTERED"


def test_registration_fee_early_and_late_tiers(api):
    """PRD §3.3: "Registering at or after the point fourteen days before the
    `registration_deadline` is late; the fee's subtotal is the window's
    `base_fee_cents` plus, only when late, its `late_surcharge_cents`. A
    processing component of one and a half percent of that subtotal, rounded
    half-up to a whole cent, is then added to produce the charge."

    Design: Difficulty/combinatorial_formula/registration_fee_rounding_order_pinned
    """
    ctx = setup_open_window(api)
    early_candidate = make_candidate(api)
    late_candidate = make_candidate(api)
    early = register(api, ctx["window"]["id"], early_candidate)
    # Early: 30000 + round_half_up(30000 * 0.015) = 30000 + 450.
    assert early["fee_charged_cents"] == FEE_EARLY_CENTS
    set_clock(api, CLOCK_LATE_FEE_TIER)
    late = register(api, ctx["window"]["id"], late_candidate)
    # Late: 37500 + round_half_up(37500 * 0.015) = 37500 + 563.
    assert late["fee_charged_cents"] == FEE_LATE_CENTS


def test_cpd_required_hours_full_year_cycle(api):
    """PRD §3.8: "in any other year the base is the full thirty hours."
    PRD §3.8: "the requirement is the base minus the smaller of
    `carryover_hours` and ten, never below zero."

    Design: Difficulty/combinatorial_formula/cpd_required_hours_proration_carryover_gate
    """
    outcome = setup_associate(api)
    candidate = outcome["candidate"]
    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_LOW,
                           carryover_hours=CPD_CARRYOVER_OVER_CAP)
    # Admitted 2026; cycle 2027 is a full year: 30 - min(12, 10) == 20.
    assert attestation["required_hours"] == 20
    assert attestation["status"] == "ATTESTED"


def test_cpd_required_hours_prorated_admission_year(api):
    """PRD §3.8: "when the candidate's `associate_admitted_at` falls within the
    attested cycle year, the base is thirty multiplied by the number of months
    remaining in that year — counted as thirteen minus the admission month, so
    the admission month itself counts in full — divided by twelve and rounded
    up to a whole hour."

    Design: Difficulty/combinatorial_formula/cpd_required_hours_proration_carryover_gate
    """
    _, exam = make_active_exam(api)
    window = make_window(api, exam["id"], window_code=WINDOW_2027_CODE,
                         registration_opens_at=WINDOW_2027_OPENS,
                         registration_deadline=WINDOW_2027_DEADLINE,
                         testing_starts_at=WINDOW_2027_TESTING_STARTS,
                         testing_ends_at=WINDOW_2027_TESTING_ENDS)
    candidate = make_candidate(api)
    set_clock(api, CLOCK_2027_WINDOW_OPEN)
    registration = register(api, window["id"], candidate)
    set_clock(api, CLOCK_2027_SCORING)
    record_score(api, registration["id"], RAW_SCORE_AT_MARK)
    propose_ratify_publish(api, window["id"])
    approve_all_vee_topics(api, candidate)
    set_clock(api, CLOCK_ASA_ADMIT_JULY)
    outcome = apply_for_credential(api, candidate, "ASA")
    assert outcome["application"]["status"] == "APPROVED"
    assert outcome["candidate"]["membership_tier"] == "ASSOCIATE"
    assert outcome["candidate"]["associate_admitted_at"].startswith("2027-07-15")

    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_LOW,
                           carryover_hours=CPD_CARRYOVER_SMALL)
    # Admission month 7 -> ceil(30 * 6 / 12) = 15; 15 - min(3, 10) == 12.
    assert attestation["required_hours"] == 12


def test_completion_pct_module_milestones(api):
    """PRD §3.5: "the reported percentage is computed as one hundred times a
    weighted sum — two for each passed non-capstone module, three more if the
    capstone module is passed, and two more if the project assessment is
    passed — divided by the weighted whole of two per non-capstone module in
    the track plus three for the capstone plus two for the project, with the
    result rounded half-up to two decimal places."
    PRD §3.5: "When every non-capstone module of the track has been passed, the
    enrollment transitions `ENROLLED` → `CAPSTONE_ELIGIBLE`."

    Design: Difficulty/combinatorial_formula/track_completion_pct_two_phase_evaluation
    """
    candidate = setup_associate(api)["candidate"]
    ctx = setup_enrollment(api, candidate)
    enrollment = ctx["enrollment"]
    module1, module2 = ctx["modules"][0], ctx["modules"][1]

    attempt_and_submit(api, candidate, enrollment, module1)
    enrollment = get_enrollment(api, candidate)
    # round_half_up(100 * 2 / 9, 2); the gate has not opened yet.
    assert enrollment["completion_pct"] == pytest.approx(PCT_AFTER_ONE_MODULE, abs=0.005)
    assert enrollment["modules_passed_count"] == 1
    assert enrollment["status"] == "ENROLLED"

    attempt_and_submit(api, candidate, enrollment, module2)
    enrollment = get_enrollment(api, candidate)
    # round_half_up(100 * 4 / 9, 2); phase-1 gate reads non-capstone passes only.
    assert enrollment["completion_pct"] == pytest.approx(PCT_AFTER_ALL_NONCAPSTONE, abs=0.005)
    assert enrollment["modules_passed_count"] == 2
    assert enrollment["status"] == "CAPSTONE_ELIGIBLE"


def test_completion_pct_project_and_capstone_milestones(api):
    """PRD §3.5: "The percentage's evaluation order is pinned so the capstone
    gate never depends on a figure that itself includes the capstone."
    PRD §3.5: "when the capstone module itself is passed while the enrollment
    is `CAPSTONE_ELIGIBLE`, the enrollment transitions to `COMPLETED`."

    Design: Difficulty/combinatorial_formula/track_completion_pct_two_phase_evaluation
    """
    ctx = setup_capstone_eligible(api)
    candidate, enrollment, modules = ctx["candidate"], ctx["enrollment"], ctx["modules"]

    project = setup_project_decided(api, candidate, enrollment)
    assert project["status"] == "DECIDED"
    assert project["final_score"] == 77
    assert project["result"] == "PASS"
    enrollment = get_enrollment(api, candidate)
    # round_half_up(100 * (4 + 2) / 9, 2) with the project weight in.
    assert enrollment["completion_pct"] == pytest.approx(PCT_AFTER_PROJECT, abs=0.005)

    capstone = [m for m in modules if m["is_capstone"]][0]
    attempt_and_submit(api, candidate, enrollment, capstone, score=SUBMIT_SCORE_PASS)
    enrollment = get_enrollment(api, candidate)
    # (2*2 + 3 + 2) / 9 == 1 -> 100.0; the capstone pass completes the track.
    assert enrollment["completion_pct"] == pytest.approx(PCT_COMPLETED, abs=0.005)
    assert enrollment["status"] == "COMPLETED"
