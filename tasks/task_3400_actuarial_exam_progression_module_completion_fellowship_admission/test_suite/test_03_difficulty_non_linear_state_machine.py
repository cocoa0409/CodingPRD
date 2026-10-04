"""Difficulty queue — non-linear state-machine shapes.

Parallel dimensions on the exam registration (PRD §3.3) and the re-verification
cycle on the CPD attestation (PRD §3.8).
"""
import pytest

from test_helpers import (
    CLOCK_SCORING,
    CPD_ATTESTED_HIGH,
    CPD_CYCLE_YEAR,
    CPD_VERIFY_EXACT,
    CPD_VERIFY_SHORTFALL,
    EXAM_COMMITTEE,
    PASS_MARK_RATIFIED,
    RAW_SCORE_HIGH,
    REGISTRAR,
    SCALED_HIGH,
    WINDOW_CAPACITY_TIGHT,
    create_pass_mark_setting_payload,
    get_success_data,
    get_window,
    make_cpd,
    ratify_pass_mark_payload,
    record_score,
    set_clock,
    setup_associate,
    setup_registered,
    verify_cpd,
)


def _capacity_one_scoring_scenario(api):
    """Capacity-1 window: cand1 REGISTERED, cand2 WAITLISTED; swept to SCORING
    (reg1 auto-SAT) with raw 45 recorded and a RATIFIED mark of 6.5."""
    ctx = setup_registered(api, num_candidates=2, capacity=WINDOW_CAPACITY_TIGHT)
    window = ctx["window"]
    reg1, reg2 = ctx["registrations"]
    set_clock(api, CLOCK_SCORING)
    record_score(api, reg1["id"], RAW_SCORE_HIGH)
    fresh = get_window(api, window["id"])
    setting = get_success_data(api.create_pass_mark_setting(
        window["id"],
        create_pass_mark_setting_payload(PASS_MARK_RATIFIED, fresh["version"]),
        EXAM_COMMITTEE))
    setting = get_success_data(api.ratify_pass_mark(
        setting["id"], ratify_pass_mark_payload(PASS_MARK_RATIFIED), EXAM_COMMITTEE))
    return {"ctx": ctx, "window": fresh, "reg1": reg1, "reg2": reg2,
            "cand1": ctx["candidates"][0], "cand2": ctx["candidates"][1],
            "setting": setting}


def _window_rows(api, window_id):
    return get_success_data(api.list_window_registrations(window_id, REGISTRAR))


def test_sat_sweep_leaves_waitlisted_row_pending(api):
    """PRD §3.3: "when `seats_held` has reached `capacity` — the boundary is
    inclusive, so equality waitlists — the registration is `WAITLISTED`, and
    this overflow is expressly not an error."
    PRD §3.3: "at which moment every registration still `REGISTERED` on the
    window is marked `SAT` with `sat_at` stamped to the current clock reading,
    while `WAITLISTED` registrations remain waitlisted."

    Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions_evolve_independently
    """
    sc = _capacity_one_scoring_scenario(api)
    assert sc["reg1"]["logistics_status"] == "REGISTERED"
    assert sc["reg2"]["logistics_status"] == "WAITLISTED"
    rows = _window_rows(api, sc["window"]["id"])
    row1 = [r for r in rows if r["id"] == sc["reg1"]["id"]][0]
    row2 = [r for r in rows if r["id"] == sc["reg2"]["id"]][0]
    # Logistics dimension advanced on the seated row only.
    assert row1["logistics_status"] == "SAT"
    assert row1["grading_status"] == "PENDING"
    assert row2["logistics_status"] == "WAITLISTED"
    assert row2["grading_status"] == "PENDING"
    assert row2["result"] is None


def test_publish_releases_sat_row_only(api):
    """PRD §3.3: "A registration may thus be observed in any independent
    combination of its two parallel dimensions, such as `SAT` with `PENDING`
    or `SAT` with `RELEASED`; the grading and logistics dimensions never
    constrain one another."
    PRD §3.3: "every `SAT` registration of the window is graded at once — its
    official `result` is set to `PASS` when its `scaled_score` is at least the
    `ratified_mark` (equality passes) and to `FAIL` otherwise, and its
    `grading_status` moves `PENDING` → `RELEASED`."

    Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions_evolve_independently
    """
    sc = _capacity_one_scoring_scenario(api)
    get_success_data(api.publish_pass_mark(sc["setting"]["id"], EXAM_COMMITTEE))
    rows = _window_rows(api, sc["window"]["id"])
    row1 = [r for r in rows if r["id"] == sc["reg1"]["id"]][0]
    row2 = [r for r in rows if r["id"] == sc["reg2"]["id"]][0]
    # raw 45 -> scaled 7.5 >= 6.5 -> PASS; only the SAT row is graded.
    assert row1["scaled_score"] == pytest.approx(SCALED_HIGH, abs=1e-6)
    assert row1["logistics_status"] == "SAT"
    assert row1["grading_status"] == "RELEASED"
    assert row1["result"] == "PASS"
    # The waitlisted row's grading dimension is untouched by the publication.
    assert row2["logistics_status"] == "WAITLISTED"
    assert row2["grading_status"] == "PENDING"
    assert row2["result"] is None


def test_cpd_shortfall_on_first_verify(api):
    """PRD §3.8: "When the recorded `verified_hours` are at least the
    `required_hours`, the attestation becomes `VERIFIED`; when they fall short,
    it becomes `SHORTFALL`."

    Design: Difficulty/non_linear_state_machine/cpd_shortfall_cure_cycle
    """
    candidate = setup_associate(api)["candidate"]
    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_HIGH, carryover_hours=0)
    assert attestation["required_hours"] == 30
    assert attestation["status"] == "ATTESTED"
    verified = verify_cpd(api, attestation["id"], CPD_VERIFY_SHORTFALL)
    assert verified["status"] == "SHORTFALL"
    assert verified["verified_hours"] == CPD_VERIFY_SHORTFALL


def test_cpd_shortfall_cured_at_exact_boundary(api):
    """PRD §3.8: "A shortfall is curable: a later verification on a `SHORTFALL`
    attestation whose new `verified_hours` meets the requirement moves it to
    `VERIFIED`."
    PRD §2.7: "all hour comparisons use an at-least boundary in which equality
    satisfies the requirement."

    Design: Difficulty/non_linear_state_machine/cpd_shortfall_cure_cycle
    """
    candidate = setup_associate(api)["candidate"]
    attestation = make_cpd(api, candidate, cycle_year=CPD_CYCLE_YEAR,
                           attested_hours=CPD_ATTESTED_HIGH, carryover_hours=0)
    verify_cpd(api, attestation["id"], CPD_VERIFY_SHORTFALL)
    cured = verify_cpd(api, attestation["id"], CPD_VERIFY_EXACT)
    # verified 30 == required 30: the at-least boundary cures the shortfall.
    assert cured["status"] == "VERIFIED"
    assert cured["verified_hours"] == CPD_VERIFY_EXACT
