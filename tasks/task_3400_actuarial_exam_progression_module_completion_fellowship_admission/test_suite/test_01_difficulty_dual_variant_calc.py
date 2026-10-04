"""Difficulty queue — dual-variant calculations.

Exam scoring carries a provisional (projected) variant and an official variant
(PRD §3.3); CPD compliance carries a self-reported (attested) variant and an
evidence-backed (verified) variant (PRD §3.8). Each pair can diverge on the
same underlying record.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_SCORING,
    CPD_ATTESTED_COMPLIANT,
    CPD_CARRYOVER_OVER_CAP,
    CPD_CYCLE_YEAR,
    CPD_VERIFY_SHORTFALL,
    EXAM_COMMITTEE,
    PASS_MARK_PROPOSED,
    PASS_MARK_RATIFIED,
    RAW_SCORE_PROJECTED_PASS,
    REGISTRAR,
    SCALED_PROJECTED_PASS,
    create_pass_mark_setting_payload,
    get_success_data,
    get_window,
    make_cpd,
    ratify_pass_mark_payload,
    record_score,
    set_clock,
    setup_associate,
    setup_registered,
    validate_success,
    verify_cpd,
)


def _projection_scenario(api):
    """Window with one SAT registration scored raw 37 (scaled 6.2) and a
    PROPOSED pass mark of 6.0."""
    ctx = setup_registered(api, num_candidates=1)
    candidate = ctx["candidates"][0]
    window = ctx["window"]
    registration = ctx["registrations"][0]
    set_clock(api, CLOCK_SCORING)
    scored = record_score(api, registration["id"], RAW_SCORE_PROJECTED_PASS)
    fresh_window = get_window(api, window["id"])
    setting = get_success_data(api.create_pass_mark_setting(
        window["id"],
        create_pass_mark_setting_payload(PASS_MARK_PROPOSED, fresh_window["version"]),
        EXAM_COMMITTEE))
    return {
        "candidate": candidate,
        "window": fresh_window,
        "registration": scored,
        "setting": setting,
    }


def _registrations(api, candidate):
    return get_success_data(api.list_candidate_registrations(candidate["id"], REGISTRAR))


def test_projected_result_passes_under_proposed_mark(api):
    """PRD §3.3: "Alongside it the provisional `projected_result` refreshes —
    `PASS` when the scaled score is at least the current projection mark,
    `FAIL` otherwise — where the projection mark is the `ratified_mark` of the
    window's latest non-`SUPERSEDED` pass-mark setting when that setting is
    `RATIFIED`, and its `proposed_mark` otherwise."
    PRD §3.3: "The `scaled_score` is then derived: the raw score is divided by
    sixty, multiplied by ten, and rounded half-up to one decimal place."

    Design: Difficulty/dual_variant_calc/score_projection_diverges_from_official_result
    """
    sc = _projection_scenario(api)
    assert sc["registration"]["scaled_score"] == pytest.approx(SCALED_PROJECTED_PASS, abs=1e-6)
    row = _registrations(api, sc["candidate"])[0]
    assert row["grading_status"] == "PENDING"
    # Projected variant reads the PROPOSED mark 6.0: scaled 6.2 >= 6.0 -> PASS.
    assert row["projected_result"] == "PASS"


def test_official_result_fails_under_ratified_mark_after_publish(api):
    """PRD §3.3: "On publication the setting becomes `PUBLISHED`, the window
    transitions `SCORING` → `RESULTS_PUBLISHED`, and every `SAT` registration
    of the window is graded at once — its official `result` is set to `PASS`
    when its `scaled_score` is at least the `ratified_mark` (equality passes)
    and to `FAIL` otherwise, and its `grading_status` moves `PENDING` →
    `RELEASED`."
    PRD §3.3: "The `projected_result` is null whenever the registration's
    `grading_status` is `RELEASED` or when no pass mark or raw score exists
    yet."

    Design: Difficulty/dual_variant_calc/score_projection_diverges_from_official_result
    """
    sc = _projection_scenario(api)
    ratified = get_success_data(api.ratify_pass_mark(
        sc["setting"]["id"], ratify_pass_mark_payload(PASS_MARK_RATIFIED), EXAM_COMMITTEE))
    assert ratified["ratified_mark"] == pytest.approx(PASS_MARK_RATIFIED, abs=1e-6)
    published = get_success_data(api.publish_pass_mark(sc["setting"]["id"], EXAM_COMMITTEE))
    assert published["status"] == "PUBLISHED"

    window = get_window(api, sc["window"]["id"])
    assert window["status"] == "RESULTS_PUBLISHED"
    row = _registrations(api, sc["candidate"])[0]
    # Official variant reads the ratified mark 6.5: the SAME scaled 6.2 fails.
    assert row["result"] == "FAIL"
    assert row["grading_status"] == "RELEASED"
    assert row["projected_result"] is None


def test_cpd_carryover_capped_and_attested_status_unchanged(api):
    """PRD §3.8: "Carryover then reduces the requirement, but only up to a cap
    of ten hours: the requirement is the base minus the smaller of
    `carryover_hours` and ten, never below zero."
    PRD §3.8: "between creation and the first verification the self-reported
    `attested_hours` serve as a provisional standing against the requirement
    without ever changing the attestation's status."

    Design: Difficulty/dual_variant_calc/cpd_attested_vs_verified_compliance_diverge
    """
    outcome = setup_associate(api)
    candidate = outcome["candidate"]
    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_COMPLIANT,
                           carryover_hours=CPD_CARRYOVER_OVER_CAP)
    # Full-year cycle for a 2026 admission: base 30 - min(12, 10) == 20.
    assert attestation["required_hours"] == 20
    # The attested variant is compliant (32 >= 20) yet must not drive status.
    assert attestation["status"] == "ATTESTED"
    assert attestation["verified_hours"] is None


def test_cpd_verified_shortfall_drives_status(api):
    """PRD §3.8: "When the recorded `verified_hours` are at least the
    `required_hours`, the attestation becomes `VERIFIED`; when they fall short,
    it becomes `SHORTFALL`."

    Design: Difficulty/dual_variant_calc/cpd_attested_vs_verified_compliance_diverge
    """
    outcome = setup_associate(api)
    candidate = outcome["candidate"]
    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_COMPLIANT,
                           carryover_hours=CPD_CARRYOVER_OVER_CAP)
    assert attestation["required_hours"] == 20
    verified = verify_cpd(api, attestation["id"], CPD_VERIFY_SHORTFALL)
    # 18 < 20 -> the verified (evidence) variant alone moves the row to
    # SHORTFALL even though the attested variant (32 >= 20) reads compliant.
    assert verified["status"] == "SHORTFALL"
    assert verified["verified_hours"] == CPD_VERIFY_SHORTFALL
